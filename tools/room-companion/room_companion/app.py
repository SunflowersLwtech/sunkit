"""Wires switches, capture pipelines, voice commands, the AI gate, reminders and notifications."""
from __future__ import annotations

import json
import os
import queue
import threading
import time

from . import commands
from .ai import AIGate
from .audio import AudioPipeline
from .events import EventLog
from .notifiers import make_notifier
from .policy import CATEGORIES, Policy, parse_policy_command
from .switches import KEYS, LABELS, Switches, SwitchWriteError, describe
from .video import VideoPipeline

DEFAULTS = {
    "data_dir": "/data",
    "listen": "0.0.0.0",
    "port": 8790,
    "allowed_cidrs": ["100.64.0.0/10", "fd7a:115c:a1e0::/48"],  # Tailscale; add your LAN in config
    "video_vendor": "2ca3,05c6",
    "capture_max_width": 1920,
    "capture_max_fps": 30,
    "live_fps": 5,
    "live_width": 1280,
    "motion_threshold": 6.0,
    "asr_dir": "/models/sense-voice",
    "vad_model": "/models/silero_vad.onnx",
    "asr_threads": 2,
    "voice_commands": True,
    "wake_words": ["房间助手"],
    "wake_fuzzy_suffix": "助手",
    "transcript_ttl_seconds": 600,
    "event_retention_days": 30,
    "max_streams": 4,
    "capture": "linux",           # "dshow" when running in WSL with Windows ffmpeg.exe
    "video_prefer": ["OsmoAction5pro", "Osmo"],
    "audio_prefer": ["OsmoAction5pro", "Microphone Array"],
    "observe_active_s": 60,       # one frame to the model per minute while something moves
    "observe_idle_s": 300,        # and every 5 minutes when nothing moves (e.g. asleep)
    "observe_min_gap_s": 20,
    "camera_tap_remind_s": 180,
    "reply_window_s": 180,
    "policy": {},
    "notifier": {"type": "log"},
}


def env(name: str) -> str | None:
    """ROOM_COMPANION_<NAME>; the short form ROOMAI_<NAME> is accepted too."""
    return os.environ.get("ROOM_COMPANION_" + name) or os.environ.get("ROOMAI_" + name)


def load_config(path: str | None = None) -> dict:
    cfg = dict(DEFAULTS)
    data_dir = env("DATA_DIR") or cfg["data_dir"]
    cfg["data_dir"] = data_dir
    path = path or os.path.join(data_dir, "config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    if env("PORT"):
        cfg["port"] = int(env("PORT"))
    return cfg


class App:
    def __init__(self, cfg: dict, video=None, audio=None, notifier=None, ai_client=None, model_server=None,
                 speaker=None, evidence=None, gpu_query=None):
        self.cfg = cfg
        d = cfg["data_dir"]
        self.switches = Switches(os.path.join(d, "state", "switches.json"))
        self.events = EventLog(os.path.join(d, "events"), cfg.get("event_retention_days", 30))
        self.notifier = notifier or make_notifier(cfg)
        self.model_server = model_server
        if ai_client is None and cfg.get("llama"):
            from .vision import LlamaServer, LocalVision
            self.model_server = model_server or LlamaServer(cfg["llama"], self.events)
            ai_client = LocalVision(self.model_server, cfg["llama"]["key_file"])
        self.ai = AIGate(self.switches, ai_client)
        self.evidence = evidence
        vkw, akw = {}, {}
        if cfg.get("capture") == "dshow":
            from .windows import Dshow, Evidence
            ds = Dshow(cfg["ffmpeg_exe"])
            # the usage record names the exe by its full path with "#" for "\\"; the last parts identify ours
            self.evidence = evidence or Evidence(app_key="#".join(cfg["ffmpeg_exe"].split("/")[-3:]))
            vkw = dict(find_device=lambda: ds.find("video", [w for w in cfg["video_prefer"] if not self._hidden(w)]),
                       list_formats=ds.formats, build_cmd=ds.video_cmd, motion_from_frames=True)
            akw = dict(find_device=lambda: ds.find("audio", [w for w in cfg["audio_prefer"]
                                                             if not self._muted(w) and not self._hidden(w)]),
                       build_cmd=ds.audio_cmd)
        self.video = video or VideoPipeline(self.switches, self.events, cfg, **vkw)
        self.audio = audio or AudioPipeline(self.switches, self.events, cfg, on_transcript=self.on_transcript,
                                            on_device_change=self._on_mic_change, **akw)
        if speaker is None and cfg.get("tts"):
            from .speaker import Speaker
            speaker = Speaker(cfg["tts"], self.events)
        self.speaker = speaker
        self.policy = Policy(os.path.join(d, "state", "policy.json"), cfg.get("policy", {}), self._deliver,
                             self.events)
        self.web_token = env("WEB_TOKEN") or None
        self.started = time.time()
        self.last_obs_at = 0.0
        self._tap_reminded = False
        self._mic_notified_at, self._mic_notices = "", 0
        self.gpu = None
        self._gpu_checked_at = 0.0
        self.gpu_pause_until = 0.0
        self.gpu_query = gpu_query
        self.hidden_devices: dict[str, float] = {}  # self-test: pretend these devices are unplugged until t
        self._stop = threading.Event()
        # One worker sends confirmations in the order the switches changed; a thread per change
        # could let an older "opened video" land after a newer "closed video".
        self._confirmations = queue.Queue()
        threading.Thread(target=self._confirm_worker, daemon=True).start()
        self.switches.on_change(self._on_switch_change)

    def start(self):
        if self.switches.load_error:
            self.events.add("state_load", detail=self.switches.load_error)
        self.notifier.start() if hasattr(self.notifier, "start") else None
        self.video.start()
        self.audio.start()
        threading.Thread(target=self._observe_loop, name="observer", daemon=True).start()
        self.events.add("service_start", switches={k: self.switches.get(k) for k in KEYS})

    def shutdown(self):
        self._stop.set()
        self.video.shutdown()
        self.audio.shutdown()
        if self.model_server is not None:
            self.model_server.stop()

    # ---- looking (AI) ----
    def _hidden(self, word: str) -> bool:
        now = time.time()
        return any(word.lower() in n.lower() or n.lower() in word.lower()
                   for n, t in self.hidden_devices.items() if t > now)

    def hide_devices(self, names, seconds: float):
        """Self-test of unplug/replug: the finders ignore these names for a while; capture using them is restarted."""
        until = time.time() + min(float(seconds), 600)
        for n in names:
            self.hidden_devices[str(n)] = until
        for pipe in (self.video, self.audio):
            dev = pipe.device
            if dev is not None and self._hidden(dev.name):
                with pipe._tick_lock:
                    pipe._stop_proc("self-test unplug")
            pipe.poke()
        self.events.add("selftest_unplug", seconds=round(until - time.time()))

    def _muted(self, word: str) -> bool:
        now = time.time()
        return any(word.lower() in name.lower() and t > now for name, t in self.audio.muted_until.items())

    def _observe_loop(self):
        while not self._stop.is_set():
            try:
                self.observe_once()
            except Exception as e:
                self.events.add("observer_error", detail=str(e)[:200])
            self._stop.wait(self.cfg.get("observe_tick_s", 5))

    def observe_once(self, now=None):
        now = now or time.time()
        ai_on = self.switches.get("ai")
        looking = ai_on and self.switches.get("video") and self.video.state == "running"
        if self.model_server is not None:
            self._gpu_check(now)
            self.model_server.ensure(looking and now >= self.gpu_pause_until)
        self.policy.set_context(ai_on, self.audio.last_speech_at)
        self._camera_tap_check(now)
        model_ready = looking and (self.model_server is None or self.model_server.ready())
        if model_ready and self._due(now):
            frame, _ = self.video.latest()
            if frame is not None:
                self.last_obs_at = now
                obs = self.ai.ask("frame", {"jpeg": frame})
                if obs is not None:
                    self.policy.observe(obs, now)
        self.policy.tick(now)

    def _gpu_check(self, now):
        """Every 5 minutes while the model runs: log GPU temperature/power; pause the model if it runs hot."""
        if self.model_server.state not in ("ready", "starting") or now - self._gpu_checked_at < self.cfg.get("gpu_check_s", 300):
            return
        self._gpu_checked_at = now
        g = (self.gpu_query or _nvidia_smi)()
        if not g:
            return
        self.gpu = g
        self.events.add("gpu", temp_c=g["temp_c"], power_w=g["power_w"], mem_mb=g["mem_mb"])
        if g["temp_c"] >= self.cfg.get("gpu_max_c", 85):
            self.gpu_pause_until = now + self.cfg.get("gpu_pause_s", 1800)
            self.events.add("gpu_too_hot", temp_c=g["temp_c"])
            self.notifier.send(f"房间AI：显卡到了 {g['temp_c']}°C，本地模型先停 30 分钟降温，视频和声音照常。")

    def _due(self, now) -> bool:
        gap = now - self.last_obs_at
        m = self.video.motion
        moving_recently = m.last_motion and now - m.last_motion < 120
        if m.active_since and m.active_since > self.last_obs_at and gap >= self.cfg.get("observe_min_gap_s", 20):
            return True
        return gap >= self.cfg.get("observe_active_s" if moving_recently else "observe_idle_s", 300)

    def _camera_tap_check(self, now):
        v = self.video
        if self.switches.get("video") and v.state == "waiting_device" and v.waiting_since \
                and now - v.waiting_since >= self.cfg.get("camera_tap_remind_s", 180):
            if not self._tap_reminded:
                self._tap_reminded = True
                self.events.add("camera_missing_reminder")
                self.notifier.send("房间AI：视频开着，但已经几分钟找不到相机了。相机可能断过电，"
                                   "请在相机屏幕上点一下「网络摄像头」；声音会先用电脑自带的麦克风。")
        elif v.state == "running":
            self._tap_reminded = False

    def _deliver(self, text: str, category: str, speak: bool):
        if speak and self.speaker is not None:
            self.speaker.say(text)
        head = "房间AI 早报：" if category == "早报" else "房间AI 提醒："
        tail = "" if category == "早报" else "\n（回「不用」今天不再提这类；回「别再提醒这个」以后都不提）"
        self.notifier.send(head + text + tail)

    def _on_mic_change(self, old: str, new: str, why: str):
        self.events.add("mic_change", reason=why)
        now = time.time()
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if self._mic_notified_at != day:
            self._mic_notified_at, self._mic_notices = day, 0
        # a flaky mic must not send messages all night: at most 4 a day, none in quiet hours
        if self._mic_notices < self.cfg.get("mic_notices_per_day", 4) and not self.policy.quiet_now(now):
            self._mic_notices += 1
            self.notifier.send(f"房间AI：声音改用「{_mic_label(new)}」（{why}）。")

    # ---- switching ----
    def set_switches(self, changes: dict, source: str) -> dict:
        diff = self.switches.set(changes, source)
        return diff

    def _on_switch_change(self, diff, source):
        self.events.add("switch", source=source,
                        changes={k: new for k, (old, new) in diff.items()})
        self.video.poke()
        self.audio.poke()
        self._confirmations.put((diff, source))

    def wait_settled(self, timeout=8.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            v_ok = (self.video.proc is None) if not self.switches.get("video") else (self.video.state != "off")
            a_ok = (self.audio.proc is None) if not self.switches.get("audio") else (self.audio.state != "off")
            if v_ok and a_ok:
                return True
            time.sleep(0.1)
        return False

    def _confirm_worker(self):
        while True:
            diff, source = self._confirmations.get()
            try:
                self._confirm(diff, source)
            except Exception as e:  # never let one bad message stop later confirmations
                self.events.add("confirm_error", detail=str(e)[:200])

    def _confirm(self, diff, source):
        settled = self.wait_settled()
        changed = "，".join(f"{'打开' if new else '关闭'}{LABELS[k]}" for k, (old, new) in diff.items())
        text = f"房间AI：已{changed}（来源：{source}）。\n现在：{self.plain_status()}"
        if not settled:
            text += "\n注意：采集进程没有在 8 秒内按开关停下或启动，请看网页上的状态。"
        self.notifier.send(text)

    # ---- plain-language status ----
    def plain_status(self) -> str:
        s = self.switches
        parts = []
        v = self.video
        if not s.get("video"):
            parts.append("视频关（摄像头已释放）" if v.proc is None else "视频关（正在停止）")
        else:
            parts.append({"running": "视频开（正在看）", "waiting_device": "视频开，但没接上相机"}
                         .get(v.state, f"视频开，但出错：{v.detail[:60]}"))
        a = self.audio
        if not s.get("audio"):
            parts.append("声音关（麦克风已释放）" if a.proc is None else "声音关（正在停止）")
        else:
            parts.append({"running": "声音开（正在听）", "waiting_device": "声音开，但没接上麦克风"}
                         .get(a.state, f"声音开，但出错：{a.detail[:60]}"))
        if not s.get("ai"):
            parts.append("AI 关（不发给任何模型）")
        elif not self.ai.client:
            parts.append("AI 开（还没接模型，什么也不发）")
        elif self.model_server is not None:
            st = self.model_server.state
            parts.append("AI 开（本地模型" + {"ready": "在看", "starting": "正在启动", "error": "出错了",
                                               "off": "待命：视频开着才会看"}.get(st, st) + "）")
        else:
            parts.append("AI 开")
        out = (self.speaker.output or {}) if self.speaker is not None else {}
        if out.get("name"):
            heard = not out.get("muted") and out.get("volume", 0) > 0
            parts.append("出声：" + _out_label(out["name"]) + ("" if heard else "（静音，只发通知）"))
        return "；".join(parts)

    def status(self) -> dict:
        snap = self.switches.snapshot()
        return {
            "switches": {k: snap[k] for k in KEYS},
            "switch_updated_at": snap.get("updated_at"),
            "switch_source": snap.get("source"),
            "state_load_error": self.switches.load_error,
            "summary": self.plain_status(),
            "video": self.video.status(),
            "audio": self.audio.status(),
            "ai": self.ai.status(),
            "model": dict(self.model_server.status(), gpu=self.gpu,
                          paused_hot=time.time() < self.gpu_pause_until) if self.model_server is not None else None,
            "policy": self.policy.status(),
            "speaker": self.speaker.status() if self.speaker is not None else None,
            "windows": self.windows_evidence() if self.evidence is not None else None,
            "feishu": {"configured": getattr(self.notifier, "configured", False),
                       "sent": getattr(self.notifier, "sent", 0),
                       "last_error": getattr(self.notifier, "last_error", None)},
            "uptime_s": int(time.time() - self.started),
        }

    # ---- commands ----
    def windows_evidence(self) -> dict:
        ev = self.evidence
        return {"ffmpeg_pids": ev.pids("ffmpeg.exe"), "model_pids": ev.pids("llama-server.exe"),
                "camera": ev.usage("webcam"), "microphone": ev.usage("microphone"),
                "camera_used_by_others": ev.in_use_by_others("webcam")}

    def _policy_text(self, text: str, within_s=None):
        """Mode changes and replies to a reminder; returns a reply message or None."""
        pc = parse_policy_command(text)
        if pc and pc[0] == "mode":
            return "好的，提醒改成" + self.policy.set_mode(pc[1]) + "。"
        if pc and pc[0] == "reset":
            self.policy.reset_suppressions()
            return "好的，之前关掉的提醒都恢复了。"
        return self.policy.on_reply(text, within_s=within_s)

    def run_command(self, text: str, source: str) -> dict:
        reply = self._policy_text(text)
        if reply:
            self.events.add("reminder_setting", source=source)
            return {"ok": True, "message": reply, "summary": self.plain_status()}
        r = commands.parse(text)
        if "error" in r:
            return {"ok": False, "message": r["error"], "summary": self.plain_status()}
        if r.get("status"):
            return {"ok": True, "message": self.plain_status(), "summary": self.plain_status()}
        try:
            diff = self.set_switches(r["changes"], source)
        except SwitchWriteError as e:
            return {"ok": False, "message": f"没能保存开关状态：{e}", "summary": self.plain_status()}
        if not diff:
            return {"ok": True, "message": "本来就是这样，没有变化。" + self.plain_status(),
                    "changes": {}, "summary": self.plain_status()}
        self.wait_settled()
        return {"ok": True, "changes": {k: new for k, (old, new) in diff.items()},
                "message": self.plain_status(), "summary": self.plain_status()}

    def on_transcript(self, text: str):
        if self.speaker is not None and self.speaker.echo():
            return  # our own voice coming back through the mic
        rest = commands.strip_wake(text, self.cfg.get("wake_words", []), self.cfg.get("wake_fuzzy_suffix"))
        # Without the wake word only a reply to a reminder just given counts ("不用", "别再提醒这个");
        # mode changes need the wake word.
        if rest is not None:
            reply = self._policy_text(rest, within_s=self.cfg.get("reply_window_s", 180))
        else:
            reply = self.policy.on_reply(text, within_s=self.cfg.get("reply_window_s", 180))
        if reply:
            self.events.add("reminder_setting", source="语音")
            self.notifier.send("房间AI：" + reply)
            if self.speaker is not None and self.policy.state["mode"] != "quiet":
                self.speaker.say(reply)
            return
        if self.cfg.get("voice_commands", True):
            if rest is not None:
                r = commands.parse(rest) if rest else {"error": "只听到唤醒词"}
                if r.get("changes"):
                    self.events.add("voice_command", changes=r["changes"])
                    try:
                        self.set_switches(r["changes"], "语音")
                    except SwitchWriteError:
                        self.notifier.send("房间AI：听到语音命令，但没能保存开关状态。")
                elif r.get("status"):
                    self.notifier.send("房间AI：" + self.plain_status())
                else:
                    self.events.add("voice_command_unparsed")
                    self.notifier.send("房间AI：听到了唤醒词，但没听懂要开还是关哪一个。")
                return  # commands are never forwarded to the AI
        self.ai.submit("transcript", {"t": time.time(), "text": text})


def _nvidia_smi():
    import subprocess
    try:
        out = subprocess.run(["/mnt/c/Windows/System32/nvidia-smi.exe", "--query-gpu=temperature.gpu,power.draw,memory.used",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15).stdout
        return parse_nvidia_smi(out)
    except (OSError, subprocess.TimeoutExpired):
        return None


def parse_nvidia_smi(out: str):
    try:
        t, p, m = [x.strip() for x in out.strip().splitlines()[0].split(",")]
        return {"temp_c": int(float(t)), "power_w": round(float(p), 1), "mem_mb": int(float(m))}
    except (ValueError, IndexError):
        return None


def _out_label(name: str) -> str:
    if "realtek" in name.lower() or "speakers" in name.lower():
        return "电脑喇叭"
    return name


def _mic_label(name: str) -> str:
    if "osmo" in name.lower():
        return "相机的麦克风"
    if "microphone array" in name.lower():
        return "电脑自带的麦克风"
    return name


def describe_switches(app: App) -> str:
    return describe(app.switches.snapshot())
