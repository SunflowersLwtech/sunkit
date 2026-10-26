"""Speaking in the room: local Chinese TTS (sherpa-onnx, CPU) played on one Windows output device.

The device is picked by name: a choice made on the page, or the first word of `output_prefer` that a
connected output's name contains (e.g. a Bluetooth speaker, then the camera if it has a speaker, then
the PC's own speakers), else Windows' default. `output_labels` gives outputs short names for the page,
`missing_notes` a line to show when a preferred device is not connected. While it speaks, a muted or quiet device is raised to `volume` and put back afterwards.
While something is being played, transcripts are treated as our own echo and ignored, unless the
caller asked to hear it (used by the self-test that plays a known sentence).
"""
from __future__ import annotations

import collections
import json
import os
import queue
import re
import subprocess
import threading
import time
import wave

SYS32 = "/mnt/c/Windows/System32"
PS = f"{SYS32}/WindowsPowerShell/v1.0/powershell.exe"
# built-in short names, by the device's language; `output_labels` in the config adds to and overrides them
DEFAULT_LABELS = {"zh": {"Realtek": "电脑喇叭"}, "en": {"Realtek": "Computer speakers"}}


class Speaker:
    def __init__(self, cfg: dict, events, tts_factory=None, play=None, list_outputs=None, state_path=None):
        self.cfg = cfg
        self.events = events
        self.tts_factory = tts_factory or self._default_tts
        self.play = play or self._play_windows
        self.list_outputs = list_outputs or self._list_windows
        self.state_path = state_path
        self.tts = None
        self.error = None
        self.spoken = 0
        self.speaking_until = 0.0
        self._spans = collections.deque(maxlen=20)  # (start, end) when our voice was in the room
        self._cur = None  # (start, expected end, hear) of what is playing now
        self.outputs = []  # active Windows outputs: name, volume, muted, default
        self.output = None  # the one we would speak on now
        self.last_play = None
        self.choice = self._load_choice()  # "auto" or an output's full name
        self.current = None  # on_done of the utterance being spoken
        self._q: queue.Queue = queue.Queue(maxsize=10)
        threading.Thread(target=self._worker, name="speaker", daemon=True).start()

    def _default_tts(self):
        import sherpa_onnx
        d = self.cfg["model_dir"]
        c = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=f"{d}/model.onnx", lexicon=f"{d}/lexicon.txt", tokens=f"{d}/tokens.txt",
                    dict_dir=f"{d}/dict"),
                num_threads=self.cfg.get("threads", 2)),
            rule_fsts=",".join(p for p in (f"{d}/phone.fst", f"{d}/date.fst", f"{d}/number.fst") if os.path.exists(p)),
            max_num_sentences=1)
        return sherpa_onnx.OfflineTts(c)

    # ---- which output ----
    def _load_choice(self) -> str:
        try:
            with open(self.state_path, encoding="utf-8") as f:
                c = json.load(f).get("choice")
            return c if isinstance(c, str) and c else "auto"
        except (OSError, ValueError, TypeError, AttributeError):
            return "auto"

    def set_choice(self, choice: str) -> dict:
        choice = (choice or "auto").strip()
        if choice != "auto" and choice not in [o["name"] for o in self.outputs]:
            raise ValueError("没有这个出声设备：" + choice[:60])
        self.choice = choice
        if self.state_path:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"choice": choice}, f, ensure_ascii=False)
            os.replace(tmp, self.state_path)
        self.output = self.pick()
        return self.output or {}

    def pick(self):
        outs = self.outputs
        if self.choice != "auto":
            for o in outs:
                if o["name"] == self.choice:
                    return o
        for word in self.cfg.get("output_prefer", []):
            for o in outs:
                if word.lower() in o["name"].lower():
                    return o
        for o in outs:
            if o.get("default"):
                return o
        return outs[0] if outs else None

    def check_output(self):
        """Ask Windows which outputs are connected, and pick one (nothing is changed)."""
        try:
            self.outputs = self.list_outputs()
        except Exception as e:  # keep the last known list
            self.error = f"output list failed: {e}"[:200]
        self.output = self.pick()
        return self.output

    def label(self, name: str) -> str:
        base = DEFAULT_LABELS.get(str(self.cfg.get("language", "zh"))[:2], DEFAULT_LABELS["zh"])
        return output_label(name, {**self.cfg.get("output_labels", {}), **{k: v for k, v in base.items()
                                                                            if k not in self.cfg.get("output_labels", {})}})

    def notes(self) -> list[str]:
        names = " ".join(o["name"].lower() for o in self.outputs)
        out = [note for word, note in self.cfg.get("missing_notes", {}).items() if word.lower() not in names]
        o = self.output
        if o and (o.get("muted") or o.get("volume", 0) < self.volume()):
            out.append(f"{self.label(o['name'])}平时静音或音量低，念的时候临时开到 {self.volume()}%，念完恢复原样")
        return out

    def volume(self) -> int:
        return int(self.cfg.get("volume", 70))

    def describe(self) -> str:
        o = self.output
        if not o:
            return "出声：没有能出声的设备（只发通知）"
        how = "手动选的" if self.choice != "auto" else ""
        if o.get("muted") or o.get("volume", 0) < self.volume():
            how = "，".join(x for x in (how, f"念的时候临时开到 {self.volume()}%") if x)
        return "出声：" + self.label(o["name"]) + (f"（{how}）" if how else "")

    # ---- speaking ----
    def say(self, text: str, hear: bool = False, on_done=None) -> bool:
        """Queue `text`. on_done(result) is called after it was played or failed:
        {"ok", "output", "seconds", "peak", "error"}."""
        try:
            self._q.put_nowait((text, hear, on_done))
            return True
        except queue.Full:
            return False

    def echo(self, now=None, since=None) -> bool:
        """True when the mic may be hearing our own voice: at `now`, or anywhere in [since, now] (a speech
        segment that started while we were speaking). Utterances played with hear=True don't count."""
        now = now or time.time()
        t0 = now if since is None else since
        tail = self.cfg.get("echo_tail_s", 1.5)
        spans = list(self._spans)
        cur = self._cur
        if cur is not None and not cur[2]:
            spans.append(cur[:2])
        return any(t0 <= e + tail and now >= s for s, e in spans)

    def _worker(self):
        if self.cfg.get("check_output", True):
            self.check_output()
        if self.cfg.get("preload", True) and self.tts is None:
            try:
                self.tts = self.tts_factory()  # the first sentence would otherwise wait for the model load
            except Exception as e:
                self.error = f"TTS load failed: {e}"[:200]
        while True:
            try:
                text, hear, on_done = self._q.get(timeout=self.cfg.get("output_check_s", 300))
            except queue.Empty:
                if self.cfg.get("check_output", True):
                    self.check_output()
                continue
            self.current = on_done
            try:
                r = self._speak(text, hear)
            except Exception as e:
                self.error = str(e)[:200]
                self.speaking_until = time.time()
                r = {"ok": False, "error": self.error}
            finally:
                self.current = None
            if on_done is not None:
                try:
                    on_done(r)
                except Exception:
                    pass

    def _speak(self, text: str, hear: bool):
        if self.cfg.get("check_output", True):
            self.check_output()  # a speaker may have connected or gone since the last look
        out = self.output
        if out is None:
            raise RuntimeError("没有能出声的设备")
        if self.tts is None:
            self.tts = self.tts_factory()
        audio = self.tts.generate(text, sid=self.cfg.get("speaker_id", 0), speed=self.cfg.get("speed", 1.0))
        path = os.path.join(self.cfg["win_dir_wsl"], "say.wav")
        _write_wav(path, audio.samples, audio.sample_rate)
        secs = len(audio.samples) / audio.sample_rate
        start = time.time()
        self.speaking_until = start + secs + 3.0
        self._cur = (start, self.speaking_until, hear)  # before playback starts: the mic may already hear it
        try:
            self.last_play = dict(self.play(path, secs, out["name"], self.volume()) or {}, at=time.time())
        finally:
            self.speaking_until = time.time()
            if not hear:
                self._spans.append((start, self.speaking_until))
            self._cur = None
        self.spoken += 1
        self.error = None
        self.events.add("spoke", seconds=round(secs, 1), output=self.label(out["name"]),
                        peak=self.last_play.get("peak"))
        return {"ok": True, "output": self.label(out["name"]), "seconds": round(secs, 1),
                "peak": self.last_play.get("peak"), "error": None}

    def _ps1(self, name: str) -> str:
        """Copy a helper script next to the Windows-side files (only when it changed); return its Windows path."""
        src = os.path.join(os.path.dirname(__file__), name)
        dst = os.path.join(self.cfg["win_dir_wsl"], name)
        with open(src, "rb") as f:
            body = f.read()
        try:
            with open(dst, "rb") as f:
                same = f.read() == body
        except OSError:
            same = False
        if not same:
            os.makedirs(self.cfg["win_dir_wsl"], exist_ok=True)
            with open(dst, "wb") as f:
                f.write(body)
        return self.cfg["win_dir"] + "\\" + name

    def _list_windows(self):
        p = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-File", self._ps1("winplay.ps1"), "-List"], capture_output=True, timeout=60, cwd="/mnt/c")
        return parse_outputs(p.stdout.decode("utf-8", "replace"))

    def _play_windows(self, path_wsl: str, secs: float, device: str, volume: int):
        win = self.cfg["win_dir"] + "\\" + os.path.basename(path_wsl)
        p = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                            self._ps1("winplay.ps1"), "-Wav", win, "-Device", device, "-Volume", str(volume)],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=secs + 30, cwd="/mnt/c")
        r = parse_played(p.stdout.decode("utf-8", "replace"))
        if r is None:
            raise RuntimeError("playback failed: " + (p.stdout + p.stderr).decode("utf-8", "replace").strip()[-160:])
        return r

    def status(self):
        return {"ready": self.tts is not None, "spoken": self.spoken, "error": self.error,
                "speaking": time.time() < self.speaking_until,
                "output": dict(self.output, label=self.label(self.output["name"])) if self.output else None,
                "outputs": [dict(o, label=self.label(o["name"])) for o in self.outputs],
                "choice": self.choice, "volume": self.volume(), "notes": self.notes(), "last_play": self.last_play}


def output_label(name: str, labels=None) -> str:
    """A short name for an output: the label of the first word (of `labels`) its name contains."""
    n = name.lower()
    for word, label in (DEFAULT_LABELS["zh"] if labels is None else labels).items():
        if word.lower() in n:
            return label
    return name


def parse_outputs(text: str) -> list[dict]:
    """winplay.ps1 -List: 'OUT [default] Speakers (Realtek(R) Audio) | volume=0% mute=True' per active output."""
    out = []
    for line in text.splitlines():
        m = re.match(r"OUT (\[default\])?\s*(.*?) \| volume=(\d+)% mute=(True|False)\s*$", line.strip())
        if m:
            out.append({"name": m.group(2), "volume": int(m.group(3)), "muted": m.group(4) == "True",
                        "default": bool(m.group(1))})
    return out


def parse_played(text: str) -> dict | None:
    """winplay.ps1's result line; None when it did not play."""
    m = re.search(r"played device=(.*?) \| frames=(\d+) seconds=([\d.]+) peak=([\d.]+) volume_before=(\d+)% "
                  r"mute_before=(True|False) volume_during=(\d+)%", text)
    if not m:
        return None
    return {"device": m.group(1), "seconds": float(m.group(3)), "peak": float(m.group(4)),
            "volume_before": int(m.group(5)), "muted_before": m.group(6) == "True", "volume_during": int(m.group(7))}


def _write_wav(path: str, samples, rate: int):
    import array
    pcm = array.array("h", (max(-32768, min(32767, int(x * 32767))) for x in samples))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)
