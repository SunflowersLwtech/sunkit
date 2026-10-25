"""Speaking in the room: local Chinese TTS (sherpa-onnx, CPU) played through Windows' default output.

While something is being played, transcripts are treated as our own echo and ignored,
unless the caller asked to hear it (used by the self-test that plays a known sentence).
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import wave

SYS32 = "/mnt/c/Windows/System32"


class Speaker:
    def __init__(self, cfg: dict, events, tts_factory=None, play=None):
        self.cfg = cfg
        self.events = events
        self.tts_factory = tts_factory or self._default_tts
        self.play = play or self._play_windows
        self.tts = None
        self.error = None
        self.spoken = 0
        self.speaking_until = 0.0
        self.hear_until = 0.0
        self.output = None  # Windows default output: name, volume, mute (read-only check)
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

    def say(self, text: str, hear: bool = False) -> bool:
        try:
            self._q.put_nowait((text, hear))
            return True
        except queue.Full:
            return False

    def echo(self, now=None) -> bool:
        """True while our own voice may be what the mic is hearing."""
        now = now or time.time()
        return now < self.speaking_until + self.cfg.get("echo_tail_s", 1.5) and now >= self.hear_until

    def check_output(self):
        """Ask Windows which output is the default and whether it is muted (shown on the page; nothing is changed)."""
        try:
            src = os.path.join(os.path.dirname(__file__), "winaudio.ps1")
            dst = os.path.join(self.cfg["win_dir_wsl"], "winaudio.ps1")
            os.makedirs(self.cfg["win_dir_wsl"], exist_ok=True)
            with open(src, "rb") as a, open(dst, "wb") as b:
                b.write(a.read())
            out = subprocess.run([f"{SYS32}/WindowsPowerShell/v1.0/powershell.exe", "-NoProfile", "-NonInteractive",
                                  "-ExecutionPolicy", "Bypass", "-File", self.cfg["win_dir"] + "\\winaudio.ps1"],
                                 capture_output=True, timeout=60, cwd="/mnt/c").stdout.decode("utf-8", "replace")
            self.output = parse_default_output(out)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.output = {"error": str(e)[:120]}
        return self.output

    def _worker(self):
        if self.cfg.get("check_output", True):
            self.check_output()
        while True:
            try:
                text, hear = self._q.get(timeout=self.cfg.get("output_check_s", 300))
            except queue.Empty:
                if self.cfg.get("check_output", True):
                    self.check_output()
                continue
            try:
                if self.tts is None:
                    self.tts = self.tts_factory()
                audio = self.tts.generate(text, sid=self.cfg.get("speaker_id", 0), speed=self.cfg.get("speed", 1.0))
                path = os.path.join(self.cfg["win_dir_wsl"], "say.wav")
                _write_wav(path, audio.samples, audio.sample_rate)
                secs = len(audio.samples) / audio.sample_rate
                start = time.time()
                self.speaking_until = start + secs + 2.0
                self.hear_until = self.speaking_until + self.cfg.get("echo_tail_s", 1.5) if hear else 0.0
                self.play(path, secs)
                self.speaking_until = time.time()
                self.spoken += 1
                self.events.add("spoke", seconds=round(secs, 1))
            except Exception as e:
                self.error = str(e)[:200]
                self.speaking_until = time.time()

    def _play_windows(self, path_wsl: str, secs: float):
        win = self.cfg["win_dir"] + "\\say.wav"
        subprocess.run([f"{SYS32}/WindowsPowerShell/v1.0/powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                        f"(New-Object Media.SoundPlayer '{win}').PlaySync()"],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=secs + 30, cwd="/mnt/c")

    def status(self):
        return {"ready": self.tts is not None, "spoken": self.spoken, "error": self.error,
                "speaking": time.time() < self.speaking_until, "output": self.output}


def parse_default_output(text: str) -> dict | None:
    """From winaudio.ps1's report: the default output line, e.g. 'OUT [default] Speakers (...) | volume=0% mute=True'."""
    import re
    for line in text.splitlines():
        m = re.match(r"OUT \[default\]\s+(.*?) \| volume=(\d+)% mute=(True|False)", line.strip())
        if m:
            return {"name": m.group(1), "volume": int(m.group(2)), "muted": m.group(3) == "True"}
    return None


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
