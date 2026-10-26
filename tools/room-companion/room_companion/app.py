"""Wires switches, capture pipelines, voice commands, the AI gate, reminders and notifications."""
from __future__ import annotations

import collections
import json
import os
import queue
import re
import threading
import time
import uuid

from . import commands
from .ai import AIGate
from .audio import AudioPipeline
from .events import EventLog
from .models import (SLOTS, TEST_JPEG, CloudVision, ModelCallError, ModelSettings, OpenAIVision, RemoteSpeech,
                     RemoteTTS, chat_image, clean_base_url, cloud_synth, cloud_transcriber, speech_wav, test_slot,
                     transcribe_wav)
from .notifiers import make_notifier
from .policy import CATEGORIES, Policy, parse_policy_command
from .switches import KEYS, LABELS, Switches, SwitchWriteError, describe
from .video import VideoPipeline

REMOTE_JOB = {"vision": "看画面", "stt": "听写", "tts": "说话"}

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
        # Which model does each job (models.py). With no "models" config and nothing chosen at run time,
        # every slot is "engine": exactly the clients built above.
        self.models = ModelSettings(cfg, os.path.join(d, "state"))
        self.cloud = None  # set by the HipiMind connector: cloud(kind, payload) -> result dict
        self.connector = None
        self._engine_server, self._engine_ai = self.model_server, ai_client
        self._apply_vision()
        self.evidence = evidence
        self.interop = None
        vkw, akw = {}, {}
        if cfg.get("capture") == "dshow":
            from .windows import Dshow, Evidence, Interop
            self.interop = Interop()
            ds = Dshow(cfg["ffmpeg_exe"], interop=self.interop)
            # the usage record names the exe by its full path with "#" for "\\"; the last parts identify ours
            self.evidence = evidence or Evidence(app_key="#".join(cfg["ffmpeg_exe"].split("/")[-3:]), interop=self.interop)
            vkw = dict(find_device=lambda: ds.find("video", [w for w in cfg["video_prefer"] if not self._hidden(w)]),
                       list_formats=ds.formats, build_cmd=ds.video_cmd, motion_from_frames=True)
            akw = dict(find_device=lambda: ds.find("audio", [w for w in cfg["audio_prefer"]
                                                             if not self._muted(w) and not self._hidden(w)]),
                       build_cmd=ds.audio_cmd)
        akw["speech_factory"] = self._make_speech
        self.video = video or VideoPipeline(self.switches, self.events, cfg, **vkw)
        self.audio = audio or AudioPipeline(self.switches, self.events, cfg, on_transcript=self.on_transcript,
                                            on_device_change=self._on_mic_change,
                                            is_echo=lambda a, b: self.speaker is not None and self.speaker.echo(now=b, since=a),
                                            **akw)
        if speaker is None and cfg.get("tts"):
            from .speaker import Speaker
            speaker = Speaker({"language": cfg.get("language", "zh"), **cfg["tts"]}, self.events,
                              tts_factory=self._make_tts, state_path=os.path.join(d, "state", "output.json"))
        self.speaker = speaker
        self.policy = Policy(os.path.join(d, "state", "policy.json"), cfg.get("policy", {}), self._deliver,
                             self.events)
        self._overrides_path = os.path.join(d, "state", "overrides.json")
        # The language reminders are written and spoken in: the config's "language" (default Chinese),
        # or the one chosen on the HipiMind page (kept in state/overrides.json).
        self.language = cfg.get("language") if cfg.get("language") in ("zh", "en") else "zh"
        self._load_overrides()
        self.policy.language = self.language
        self.web_token = env("WEB_TOKEN") or None
        self.started = time.time()
        self.last_obs_at = 0.0
        self._tap_reminded = False
        self._mic_notified_at, self._mic_notices = "", 0
        self.gpu = None
        self._gpu_checked_at = 0.0
        self.gpu_pause_until = 0.0
        # typed text read out in the room: the words stay in memory for today only
        self.broadcasts = collections.deque(maxlen=50)
        self._bc_times = collections.deque(maxlen=100)
        self._bc_day, self._bc_count = "", 0
        self._bc_lock = threading.Lock()
        self._bc_results = collections.OrderedDict()  # id -> state, kept for the last 50
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
        if self.interop is not None and not self.interop.ensure():
            self.events.add("interop_broken", detail="no /run/WSL socket can start Windows programs")
        self.video.start()
        self.audio.start()
        threading.Thread(target=self._observe_loop, name="observer", daemon=True).start()
        self.events.add("service_start", switches={k: self.switches.get(k) for k in KEYS})
        if self.cfg.get("hipimind"):
            from .hipimind import start_in_process
            self.connector = start_in_process(self, self.cfg["hipimind"])

    def shutdown(self):
        self._stop.set()
        if self.connector is not None:
            self.connector.stop()
        self.video.shutdown()
        self.audio.shutdown()
        if self.model_server is not None:
            self.model_server.stop()
        if self._engine_server is not None and self._engine_server is not self.model_server:
            self._engine_server.stop()

    # ---- models (models.py): one source per job ----
    def _cloud_call(self, request_type: str, **payload) -> dict:
        cloud = self.cloud
        if cloud is None:
            return {"ok": False, "error": {"code": "unavailable", "message": "not connected to HipiMind"}}
        return cloud(request_type, payload)

    def _park_engine(self):
        if self._engine_server is not None:
            self._engine_server.ensure(False)
        self.model_server = None

    def _apply_vision(self):
        slot = self.models.slot("vision")
        src = slot["source"]
        if src == "engine":
            self.model_server, self.ai.client = self._engine_server, self._engine_ai
        elif src == "openai":
            self._park_engine()
            self.ai.client = OpenAIVision(slot, lambda: self.models.key("vision")) if slot.get("base_url") else None
        elif src == "cloud":
            self._park_engine()
            self.ai.client = CloudVision(self._cloud_call)
        else:
            self._park_engine()
            self.ai.client = None

    def _vad_only(self):
        from .audio import EnergyVAD, SherpaSpeech
        try:
            return SherpaSpeech(None, self.cfg["vad_model"], self.cfg.get("asr_threads", 2))
        except Exception:
            return EnergyVAD()

    def _make_speech(self):
        """The audio pipeline's speech object for the current speech-to-text slot."""
        slot = self.models.slot("stt")
        src = slot["source"]
        if src == "engine":
            return self.audio._default_speech()
        vad = self._vad_only()
        if src == "off":
            return vad
        if src == "openai":
            if not slot.get("base_url"):
                return vad  # no usable server address: hear nothing rather than send anywhere
            def transcribe(wav, slot=slot):
                return transcribe_wav(slot["base_url"], slot.get("model"), self.models.key("stt"), wav, 30,
                                      language=slot.get("language"))
        else:
            transcribe = cloud_transcriber(self._cloud_call)
        # Speech leaves the machine only while the AI switch is on.
        return RemoteSpeech(vad, transcribe, allowed=lambda: self.switches.get("ai"))

    def _make_tts(self):
        slot = self.models.slot("tts")
        src = slot["source"]
        # Like remote speech-to-text: text leaves for a remote speech model only while the AI switch is on.
        ai_on = lambda: bool(self.switches.get("ai"))  # noqa: E731
        if src == "openai":
            if not slot.get("base_url"):
                raise ModelCallError("connect_failed", slot.get("base_url_error") or "no server address for speech")
            return RemoteTTS(lambda text, slot=slot: speech_wav(slot["base_url"], slot.get("model"),
                                                                self.models.key("tts"), text, slot.get("voice"), 30),
                             allowed=ai_on)
        if src == "cloud":
            return RemoteTTS(cloud_synth(self._cloud_call), allowed=ai_on)
        if src == "off":
            raise ModelCallError("unsupported", "speech is off")
        return self.speaker._default_tts()

    def _can_speak(self) -> bool:
        if self.speaker is None:
            return False
        src = self.models.slot("tts")["source"]
        if src == "off":
            return False
        # a remote speech model hears nothing while the AI switch is off; the built-in engine may still speak
        return src == "engine" or bool(self.switches.get("ai"))

    def apply_models(self, models: dict, keys: dict | None = None) -> list[str]:
        """A run-time model choice (from the HipiMind page). Returns the slots that changed."""
        return self._models_changed(self.models.set(models or {}, keys))

    def reset_remote_models(self) -> list[str]:
        """The account that chose the models is gone (its token was refused or replaced): every slot the
        page moved to a remote server goes back to this device's own config, and the keys are deleted."""
        return self._models_changed(self.models.reset_remote(), reason="token")

    def bind_token(self, fingerprint: str) -> list[str]:
        """Called with the device token in use; another token than the one the choices were made under
        resets them (reset_remote_models)."""
        return self._models_changed(self.models.bind_token(fingerprint), reason="token")

    def _models_changed(self, changed: list[str], reason: str | None = None) -> list[str]:
        if "vision" in changed:
            self._apply_vision()
        if "stt" in changed and hasattr(self.audio, "_speech_lock"):
            with self.audio._speech_lock:
                self.audio.speech = None  # the next utterance builds the new one
        if "tts" in changed and self.speaker is not None:
            self.speaker.tts = None
        if changed:
            self.events.add("models_changed", slots=changed,
                            sources={k: self.models.slot(k)["source"] for k in changed},
                            **({"reason": reason} if reason else {}))
        return changed

    def remote_models_text(self) -> str:
        """For the local page: which jobs go to another machine right now, and where. Empty when none."""
        parts = []
        for name in SLOTS:
            slot = self.models.slot(name)
            if slot["source"] == "openai" and slot.get("base_url"):
                where = slot["base_url"]
            elif slot["source"] == "cloud":
                where = "HipiMind 云"
            else:
                continue
            by = "（HipiMind 网页选的）" if self.models.from_page(name) else ""
            parts.append(f"{REMOTE_JOB[name]} → {where}{by}")
        return ("注意，这些交给别的机器：" + "；".join(parts)) if parts else ""

    def models_state(self) -> dict:
        out = {}
        for name in SLOTS:
            slot = self.models.slot(name)
            st = {"source": slot["source"]}
            if slot["source"] == "openai":
                st["base_url"] = slot.get("base_url")
                if slot.get("model"):
                    st["name"] = slot["model"]
                st["has_key"] = self.models.has_key(name)
            st["state"] = self._slot_state(name, slot)
            if slot["source"] == "engine":
                n = self._engine_name(name)
                if n:
                    st["name"] = n
            out[name] = st
        return out

    def _slot_state(self, name, slot) -> str:
        src = slot["source"]
        if src == "off":
            return "off"
        if src == "openai" and not slot.get("base_url"):
            return "error"
        if name == "vision":
            if src == "engine":
                if self._engine_server is not None:
                    return {"ready": "ready", "starting": "starting", "error": "error"}.get(self._engine_server.state, "off")
                return "ready" if self._engine_ai is not None else "error"
            return "error" if getattr(self.ai.client, "ok", None) is False else "ready"
        if name == "stt":
            sp = getattr(self.audio, "speech", None)
            if src == "engine":
                st = (self.audio.status() or {}).get("asr") if hasattr(self.audio, "status") else None
                return "ready" if st == "ready" else ("error" if isinstance(st, str) and "unavailable" in st else "off")
            return "error" if getattr(sp, "last_error", None) and getattr(sp, "errors", 0) else "ready"
        if self.speaker is None:
            return "off"
        return "error" if self.speaker.error else ("ready" if self.speaker.tts is not None or src != "engine" else "off")

    def _engine_name(self, name):
        if name == "vision" and self.cfg.get("llama"):
            base = str(self.cfg["llama"].get("model", "")).replace("\\", "/").split("/")[-1]
            return base[:-5] if base.endswith(".gguf") else base or None
        if name == "stt":
            return "SenseVoice-Small" if self.cfg.get("asr_dir") else None
        if name == "tts" and self.cfg.get("tts"):
            return str(self.cfg["tts"].get("model_dir", "")).rstrip("/").split("/")[-1] or None
        return None

    def _engine_check(self, name) -> dict:
        """The built-in engine's side of "Test connection": a real call when it is running, else its files."""
        if name == "vision":
            srv = self._engine_server
            if srv is None:
                if self._engine_ai is not None:
                    return {"model": None, "detail": "built-in vision client present"}
                raise ModelCallError("engine_unavailable", "no built-in vision engine is configured (llama)")
            if srv.ready():
                key = None
                try:
                    with open(self.cfg["llama"]["key_file"], "r", encoding="utf-8") as f:
                        key = f.read().strip()
                except OSError:
                    pass
                chat_image(srv.base + "/v1", None, key, TEST_JPEG, "Reply with OK", 15)
                return {"model": self._engine_name("vision"), "detail": "HTTP 200 from the running engine"}
            missing = [k for k in ("exe", "key_file") if not os.path.exists(str(self.cfg["llama"].get(k, "")))]
            if missing:
                raise ModelCallError("engine_unavailable", "engine files missing: " + ", ".join(missing))
            return {"model": self._engine_name("vision"),
                    "detail": "engine files present; it starts when AI and video are both on"}
        if name == "stt":
            sp = getattr(self.audio, "speech", None)
            if getattr(sp, "rec", None) is not None:
                sp.transcribe(sp.np.zeros(16000, dtype=sp.np.float32))
                return {"model": "SenseVoice-Small", "detail": "transcribed 1 s of silence"}
            need = [self.cfg.get("vad_model", "")]
            if self.cfg.get("asr_dir"):
                need += [os.path.join(self.cfg["asr_dir"], "model.int8.onnx"), os.path.join(self.cfg["asr_dir"], "tokens.txt")]
            missing = [os.path.basename(p) or p for p in need if not os.path.exists(str(p))] + _sherpa_missing()
            if missing:
                raise ModelCallError("engine_unavailable", "engine files missing: " + ", ".join(missing))
            return {"model": "SenseVoice-Small", "detail": "engine files present"}
        if self.speaker is None:
            raise ModelCallError("engine_unavailable", "no speaker is configured (tts)")
        d = self.cfg["tts"].get("model_dir", "")
        missing = [f for f in ("model.onnx", "tokens.txt") if not os.path.exists(os.path.join(d, f))] + _sherpa_missing()
        if missing:
            raise ModelCallError("engine_unavailable", "engine files missing: " + ", ".join(missing))
        return {"model": self._engine_name("tts"), "detail": "engine files present"}

    def test_model(self, name: str, slot: dict, key: str | None = None) -> dict:
        """ "Test connection" for one slot with exactly this setting; nothing is saved."""
        if name not in SLOTS:
            return {"ok": False, "error": {"code": "bad_request", "message": "unknown slot"}}
        if key is None:
            base = clean_base_url((slot or {}).get("base_url"))
            if base:
                key = self.models.key(name, base_url=base)  # only a key that was entered for this very server
        return test_slot(name, slot, key, cloud=self._cloud_call, engine_check=self._engine_check)

    # ---- reminder settings changed at run time ----
    def _load_overrides(self):
        try:
            with open(self._overrides_path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        qh = d.get("quiet_hours") if isinstance(d, dict) else None
        if isinstance(qh, list) and len(qh) == 2:
            self.policy.cfg["quiet_hours"] = qh
        if isinstance(d, dict) and d.get("language") in ("zh", "en"):
            self.language = d["language"]

    def _save_override(self, key, value):
        try:
            with open(self._overrides_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            d = {}
        d[key] = value
        os.makedirs(os.path.dirname(self._overrides_path), exist_ok=True)
        tmp = self._overrides_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, self._overrides_path)

    def set_language(self, lang: str):
        """"zh" or "en": the language reminders are written and spoken in (raises ValueError otherwise)."""
        if lang not in ("zh", "en"):
            raise ValueError("language must be zh or en")
        self._save_override("language", lang)  # kept first, so a language in use is always one on disk
        self.language = lang
        self.policy.language = lang

    def set_quiet_hours(self, start: str | None, end: str | None):
        """None/None means no quiet hours."""
        from .policy import _hm
        qh = [start, end] if start and end else ["00:00", "00:00"]
        _hm(qh[0]), _hm(qh[1])  # raises ValueError on a bad time
        self.policy.cfg["quiet_hours"] = qh
        self._save_override("quiet_hours", qh)

    def quiet_hours(self):
        qh = self.policy.cfg.get("quiet_hours", ["23:00", "08:00"])
        return None if qh[0] == qh[1] else {"start": qh[0], "end": qh[1]}

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
        if self.interop is not None:
            ok_before = self.interop.ok
            if self.interop.ensure(now=now) != ok_before and ok_before is not None:
                self.events.add("interop", ok=self.interop.ok, socket=self.interop.socket or "default")
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
        if speak and self._can_speak():
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
            self.notifier.send(f"房间AI：声音改用「{_mic_label(new, self.cfg.get('language', 'zh'))}」（{why}）。")

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

    def wait_settled(self, timeout=15.0) -> bool:
        # the first Windows calls after a restart are slow: turning video on has taken 8 s
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
            text += "\n注意：采集进程没有在 15 秒内按开关停下或启动，请看网页上的状态。"
        self.notifier.send(text)

    # ---- plain-language status ----
    def plain_status(self, local: bool = False) -> str:
        """The status in one line. It goes into messages that leave the machine, so error details are
        left out unless `local` (the page itself)."""
        s = self.switches
        parts = []
        v = self.video
        if not s.get("video"):
            parts.append("视频关（摄像头已释放）" if v.proc is None else "视频关（正在停止）")
        else:
            parts.append({"running": "视频开（正在看）", "waiting_device": "视频开，但没接上相机", "off": "视频开（正在启动）"}
                         .get(v.state, f"视频开，但出错：{v.detail[:60]}" if local else "视频开，但出错了（详情看网页）"))
        a = self.audio
        if not s.get("audio"):
            parts.append("声音关（麦克风已释放）" if a.proc is None else "声音关（正在停止）")
        else:
            parts.append({"running": "声音开（正在听）", "waiting_device": "声音开，但没接上麦克风", "off": "声音开（正在启动）"}
                         .get(a.state, f"声音开，但出错：{a.detail[:60]}" if local else "声音开，但出错了（详情看网页）"))
        if not s.get("ai"):
            parts.append("AI 关（不发给任何模型）")
        elif not self.ai.client:
            parts.append("AI 开（还没接模型，什么也不发）")
        elif self.model_server is not None:
            st = self.model_server.state
            parts.append("AI 开（本地模型" + {"ready": "在看", "starting": "正在启动", "error": "出错了",
                                               "off": "待命：视频开着才会看"}.get(st, st) + "）")
        elif self.models.slot("vision")["source"] == "openai":
            parts.append("AI 开（自选模型）")
        elif self.models.slot("vision")["source"] == "cloud":
            parts.append("AI 开（HipiMind 云模型）")
        else:
            parts.append("AI 开")
        if self.speaker is not None:
            parts.append(self.speaker.describe())
        return "；".join(parts)

    def status(self, evidence: bool = True) -> dict:
        """Everything the local page shows. `evidence=False` skips the Windows evidence (process lists,
        camera/microphone usage), which starts helper processes: the HipiMind connector polls every
        second and needs none of it."""
        snap = self.switches.snapshot()
        return {
            "switches": {k: snap[k] for k in KEYS},
            "switch_updated_at": snap.get("updated_at"),
            "switch_source": snap.get("source"),
            "state_load_error": self.switches.load_error,
            "summary": self.plain_status(local=True),
            "video": self.video.status(),
            "audio": self.audio.status(),
            "ai": self.ai.status(),
            "model": dict(self.model_server.status(), gpu=self.gpu,
                          paused_hot=time.time() < self.gpu_pause_until) if self.model_server is not None else None,
            "policy": self.policy.status(),
            "speaker": self.speaker.status() if self.speaker is not None else None,
            "broadcast": self.broadcast_status(),
            "models": self.models_state(),
            "remote_text": self.remote_models_text(),
            "windows": self.windows_evidence() if evidence and self.evidence is not None else None,
            "interop": self.interop.status() if self.interop is not None else None,
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

    # ---- reading typed text out loud ----
    def broadcast(self, text: str, source: str, now=None, request_id=None, on_done=None) -> dict:
        """Read `text` out in the room. Not tied to the three switches; limited per minute and per day.

        Returns at once with {"ok", "id", "message"}. When it has been played (or failed),
        on_done({"id", "ok", "output", "seconds", "peak", "error"}) is called from the speaker's thread,
        and broadcast_result(id) has the same fields plus "state".
        """
        now = now or time.time()
        bid = str(request_id or "")[:64] or uuid.uuid4().hex[:12]
        text = " ".join(str(text or "").split())
        limit = self.cfg.get("broadcast_max_chars", 300)
        if not text:
            return {"ok": False, "id": bid, "code": "empty", "message": "没有要念的文字。"}
        if len(text) > limit:
            return {"ok": False, "id": bid, "code": "too_long", "message": f"太长了：{len(text)} 字，一次最多 {limit} 字。"}
        if self.speaker is None:
            return {"ok": False, "id": bid, "code": "no_output", "message": "这台电脑没有配置出声。"}
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        per_min, per_day = self.cfg.get("broadcast_per_minute", 6), self.cfg.get("broadcast_per_day", 200)
        with self._bc_lock:
            if self._bc_day != day:
                self._bc_day, self._bc_count = day, 0
            if sum(1 for t in self._bc_times if now - t < 60) >= per_min:
                return {"ok": False, "id": bid, "code": "rate_limited", "message": f"念得太频繁了：每分钟最多 {per_min} 次，等一会儿再试。"}
            if self._bc_count >= per_day:
                return {"ok": False, "id": bid, "code": "rate_limited", "message": f"今天已经念了 {per_day} 次，到上限了，明天再用。"}
            res = {"id": bid, "state": "queued", "chars": len(text), "source": source, "t": now, "day": day,
                   "ok": None, "output": None, "seconds": None, "peak": None, "error": None}

            def done(r, res=res):
                res.update({k: r.get(k) for k in ("ok", "output", "seconds", "peak", "error")},
                           state="done" if r.get("ok") else "failed")
                if on_done is not None:
                    on_done({k: res[k] for k in ("id", "ok", "output", "seconds", "peak", "error")})

            done.res = res  # lets broadcast_result see that this one is being spoken
            if not self.speaker.say(text, on_done=done):
                return {"ok": False, "id": bid, "code": "busy", "message": "前面还有好几句没念完，等一会儿再试。"}
            self._bc_results[bid] = res
            while len(self._bc_results) > 50:
                self._bc_results.popitem(last=False)
            self._bc_times.append(now)
            self._bc_count += 1
            self.broadcasts.append({"t": now, "day": day, "text": text, "source": source})
        self.events.add("broadcast", chars=len(text), source=source)
        where = self.speaker.describe().replace("出声：", "")
        return {"ok": True, "id": bid, "message": f"好，{len(text)} 字，马上念（{where}）。", "summary": self.plain_status()}

    def broadcast_result(self, bid: str):
        with self._bc_lock:
            r = self._bc_results.get(bid)
            if r is None:
                return None
            out = {k: r[k] for k in ("id", "state", "ok", "output", "seconds", "peak", "error", "chars", "source")}
        if out["state"] == "queued" and self.speaker is not None and getattr(self.speaker.current, "res", None) is r:
            out["state"] = "speaking"
        return out

    def broadcast_status(self, now=None) -> dict:
        now = now or time.time()
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        with self._bc_lock:
            while self.broadcasts and self.broadcasts[0]["day"] != day:
                self.broadcasts.popleft()  # only today's words are kept
            recent = [{"t": b["t"], "text": b["text"], "source": b["source"]} for b in list(self.broadcasts)[-10:]]
            count = self._bc_count if self._bc_day == day else 0
        return {"today": count, "max_per_day": self.cfg.get("broadcast_per_day", 200),
                "max_chars": self.cfg.get("broadcast_max_chars", 300), "recent": recent}

    def set_output(self, choice: str, source: str) -> dict:
        if self.speaker is None:
            raise ValueError("这台电脑没有配置出声")
        self.speaker.set_choice(choice)
        self.events.add("output_choice", choice="自动" if self.speaker.choice == "auto" else
                        self.speaker.label(self.speaker.choice), source=source)
        return {"ok": True, "message": self.speaker.describe(), "summary": self.plain_status()}

    def run_command(self, text: str, source: str) -> dict:
        m = re.match(r"\s*播报\s*[:：]?\s*(.*)$", text or "", re.S)
        if m:
            return self.broadcast(m.group(1), source)
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

    def on_transcript(self, text: str, remote: bool = False):
        """One utterance. `remote`: a remote speech-to-text server (openai or cloud) wrote these words, so
        a command in them may only turn things off — a server we do not control must not be able to
        switch the camera back on by "hearing" it."""
        if self.speaker is not None and self.speaker.echo():
            return  # our own voice coming back through the mic
        rest = commands.strip_wake(text, self.cfg.get("wake_words", []), self.cfg.get("wake_fuzzy_suffix"))
        # Without the wake word only a reply to a reminder just given counts ("不用", "别再提醒这个");
        # mode changes need the wake word.
        if rest is not None:
            pc = parse_policy_command(rest)
            if remote and pc and pc != ("mode", "quiet"):
                self._refuse_remote(pc[0], " ".join(pc))  # more reminders: an "on", refused
                return
            reply = self._policy_text(rest, within_s=self.cfg.get("reply_window_s", 180))
        else:
            reply = self.policy.on_reply(text, within_s=self.cfg.get("reply_window_s", 180))
        if reply:
            self.events.add("reminder_setting", source="语音")
            self.notifier.send("房间AI：" + reply)
            if self._can_speak() and self.policy.state["mode"] != "quiet":
                self.speaker.say(reply)
            return
        if self.cfg.get("voice_commands", True):
            if rest is not None:
                r = commands.parse(rest) if rest else {"error": "只听到唤醒词"}
                if r.get("changes") and remote:
                    turn_on = {k: v for k, v in r["changes"].items() if v}
                    if turn_on:
                        self._refuse_remote("switch", turn_on)
                    r["changes"] = {k: v for k, v in r["changes"].items() if not v}
                    if not r["changes"]:
                        return
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

    def _refuse_remote(self, what: str, detail):
        self.events.add("voice_command_refused", what=what, detail=detail, why="remote_stt")


def _sherpa_missing() -> list[str]:
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError:
        return ["sherpa-onnx (pip)"]
    return []


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


def _mic_label(name: str, language: str = "zh") -> str:
    """A short name for a microphone. It goes into messages, so never the hardware name itself."""
    en = str(language).startswith("en")
    if "osmo" in name.lower():
        return "camera microphone" if en else "相机的麦克风"
    if "microphone array" in name.lower():
        return "built-in microphone" if en else "电脑自带的麦克风"
    return "microphone" if en else "麦克风"


def describe_switches(app: App) -> str:
    return describe(app.switches.snapshot())
