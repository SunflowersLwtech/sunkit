"""Microphone capture. arecord holds the mic only while the audio switch is on.

Audio is cut into utterances by a voice activity detector and transcribed
locally (SenseVoice via sherpa-onnx, on this box; nothing leaves it here).
Transcripts stay in memory for a few minutes and are dropped when the switch
goes off. Nothing is written to disk except "someone spoke for N seconds".
"""
from __future__ import annotations

import array
import collections
import math
import queue
import subprocess
import threading
import time

from . import devices
from .video import end_process

RATE = 16000
CHUNK_BYTES = 1024  # 512 samples, 32 ms


def build_arecord(alsa_name: str):
    return ["arecord", "-q", "-D", alsa_name, "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"]


def rms_dbfs(pcm: bytes) -> float:
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if not a:
        return -120.0
    ms = sum(x * x for x in a) / len(a)
    return 10 * math.log10(ms / (32768.0 ** 2)) if ms > 0 else -120.0


class EnergyVAD:
    """Fallback when sherpa-onnx is not available: cut on loudness only, no ASR."""

    def __init__(self, threshold_db=-45.0, silence_s=0.6):
        self.th = threshold_db
        self.silence = silence_s
        self.cur = bytearray()
        self.quiet_for = 0.0
        self.ready = True

    def accept(self, pcm: bytes):
        loud = rms_dbfs(pcm) > self.th
        dur = len(pcm) / 2 / RATE
        segs = []
        if loud:
            self.cur += pcm
            self.quiet_for = 0.0
        elif self.cur:
            self.cur += pcm
            self.quiet_for += dur
            if self.quiet_for >= self.silence:
                if len(self.cur) / 2 / RATE >= 0.3:
                    segs.append(bytes(self.cur))
                self.cur = bytearray()
        return segs

    def reset(self):
        self.cur = bytearray()
        self.quiet_for = 0.0

    def transcribe(self, seg) -> str:
        return ""

    @staticmethod
    def seconds(seg) -> float:
        return len(seg) / 2 / RATE


class SherpaSpeech:
    def __init__(self, asr_dir: str, vad_model: str, threads: int = 2):
        import numpy as np
        import sherpa_onnx

        self.np = np
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = vad_model
        cfg.silero_vad.min_silence_duration = 0.5
        cfg.silero_vad.min_speech_duration = 0.25
        if hasattr(cfg.silero_vad, "max_speech_duration"):
            cfg.silero_vad.max_speech_duration = 20
        cfg.sample_rate = RATE
        self._vad_cfg = cfg
        self.window = cfg.silero_vad.window_size
        self.vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)
        self.rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=f"{asr_dir}/model.int8.onnx", tokens=f"{asr_dir}/tokens.txt",
            num_threads=threads, use_itn=True, language="auto")
        self.buf = np.zeros(0, dtype=np.float32)
        self.ready = True

    def accept(self, pcm: bytes):
        np = self.np
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        self.buf = np.concatenate([self.buf, x])
        while len(self.buf) >= self.window:
            self.vad.accept_waveform(self.buf[: self.window])
            self.buf = self.buf[self.window:]
        segs = []
        while not self.vad.empty():
            segs.append(np.array(self.vad.front.samples, dtype=np.float32))
            self.vad.pop()
        return segs

    def reset(self):
        self.vad.reset()
        self.buf = self.np.zeros(0, dtype=self.np.float32)

    def transcribe(self, seg) -> str:
        s = self.rec.create_stream()
        s.accept_waveform(RATE, seg)
        self.rec.decode_stream(s)
        return s.result.text.strip()

    @staticmethod
    def seconds(seg) -> float:
        return len(seg) / RATE


class AudioPipeline:
    def __init__(self, switches, events, cfg, on_transcript=None, find_device=None, build_cmd=None,
                 speech_factory=None, on_device_change=None):
        self.switches = switches
        self.events = events
        self.cfg = cfg
        self.on_transcript = on_transcript or (lambda text: None)
        self.find_device = find_device or devices.find_audio
        self.build_cmd = build_cmd or build_arecord
        self.speech_factory = speech_factory or self._default_speech
        self.speech = None
        self.speech_error = None
        self.state = "off"
        self.detail = ""
        self.device = None
        self.proc = None
        self.pid = None
        self.level_db = -120.0
        self.segments = 0
        self.last_speech_at = 0.0
        # Fallback between microphones: devices that went quiet are skipped for a while.
        self.on_device_change = on_device_change or (lambda old, new, why: None)
        self.muted_until: dict[str, float] = {}
        self._silent_since = None
        self._last_device_name = None
        self._next_prefer_check = 0.0
        self.transcripts = collections.deque(maxlen=50)
        self._gen = 0
        self._transcripts_lock = threading.Lock()
        self._q: queue.Queue = queue.Queue(maxsize=20)
        self._threads = []
        self._stderr = collections.deque(maxlen=20)
        self._retry_at = 0.0
        self._backoff = 2.0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._tick_lock = threading.Lock()
        self._speech_lock = threading.Lock()
        self._change_reason = None
        self.graceful_quit = cfg.get("graceful_quit", False)

    def _default_speech(self):
        try:
            return SherpaSpeech(self.cfg["asr_dir"], self.cfg["vad_model"], self.cfg.get("asr_threads", 2))
        except Exception as e:  # missing model or library: keep recording levels, no text
            self.speech_error = f"ASR unavailable: {e}"[:200]
            return EnergyVAD()

    def start(self):
        threading.Thread(target=self._loop, name="audio", daemon=True).start()
        threading.Thread(target=self._asr_worker, name="asr", daemon=True).start()

    def poke(self):
        self._wake.set()

    def shutdown(self):
        self._stop.set()
        self._wake.set()
        with self._tick_lock:
            self._stop_proc("shutdown")

    def recent_transcripts(self, ttl=600):
        cutoff = time.time() - ttl
        return [t for t in list(self.transcripts) if t["t"] >= cutoff]

    def status(self):
        return {
            "state": self.state,
            "detail": self.detail,
            "device": self.device.name if self.device else None,
            "alsa": self.device.alsa_name if self.device else None,
            "kernel_capture": devices.capture_status(self.device.card_index)
                              if self.device and self.device.card_index is not None else None,
            "pid": self.pid,
            "level_db": round(self.level_db, 1),
            "segments": self.segments,
            "asr": "ready" if (self.speech is not None and not isinstance(self.speech, EnergyVAD))
                   else (self.speech_error or ("loading" if self.state == "running" else "idle")),
            "stderr": list(self._stderr)[-3:],
        }

    def _loop(self):
        while not self._stop.is_set():
            try:
                with self._tick_lock:
                    self._tick()
            except Exception as e:
                self.detail = f"supervisor error: {e}"
            self._wake.wait(1.0)
            self._wake.clear()

    def _tick(self):
        if self._stop.is_set():
            return
        if not self.switches.get("audio"):
            if self.proc is not None:
                self._stop_proc("switched off")
            self.state, self.detail = "off", ""
            self._backoff, self._retry_at = 2.0, 0.0
            return
        if self.proc is not None:
            rc = self.proc.poll()
            if rc is None:
                self._check_fallback()
                return
            err = " | ".join(list(self._stderr)[-2:])
            self._stop_proc(f"recorder exited {rc}")
            self.state, self.detail = "error", f"arecord exited {rc}: {err}"[:300]
            self._retry_at = time.time() + self._backoff
            self._backoff = min(self._backoff * 2, 60.0)
            return
        if time.time() < self._retry_at:
            return
        dev = self.find_device()
        if dev is None:
            self.device = None
            self.state, self.detail = "waiting_device", "没找到麦克风"
            return
        self.device = dev
        if self._last_device_name is not None and dev.name != self._last_device_name:
            self.on_device_change(self._last_device_name, dev.name, self._change_reason or "原来的麦克风不在了")
        self._last_device_name, self._change_reason = dev.name, None
        self._silent_since = None
        self._next_prefer_check = time.time() + self.cfg.get("audio_prefer_check_s", 30)
        try:
            self.proc = subprocess.Popen(self.build_cmd(dev.alsa_name), stdin=subprocess.PIPE if self.graceful_quit else subprocess.DEVNULL,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            self.state, self.detail = "error", f"cannot start arecord: {e}"
            self._retry_at = time.time() + 30
            return
        self.pid = self.proc.pid
        self.state, self.detail = "running", ""
        self._gen += 1
        proc, gen = self.proc, self._gen
        self._threads = [threading.Thread(target=self._read_pcm, args=(proc, gen), daemon=True),
                         threading.Thread(target=self._read_stderr, args=(proc,), daemon=True)]
        for t in self._threads:
            t.start()
        self.events.add("audio_on", device=dev.name)

    def _check_fallback(self):
        """While recording: give up a mic that is digitally silent, and go back to a preferred one when it returns."""
        now = time.time()
        # "Dead" means near-digital silence for a long time; a quiet room with noise reduction still flickers above it.
        mute_db = self.cfg.get("audio_mute_db", -95.0)
        if self.level_db <= mute_db:
            self._silent_since = self._silent_since or now
            if now - self._silent_since >= self.cfg.get("audio_mute_s", 600):
                self.muted_until[self.device.name] = now + self.cfg.get("audio_mute_skip_s", 600)
                self._change_reason = "原来的麦克风一直没有声音"
                self._stop_proc("mic silent")
                return
        else:
            self._silent_since = None
        if now >= self._next_prefer_check:
            self._next_prefer_check = now + self.cfg.get("audio_prefer_check_s", 30)
            best = self.find_device()
            if best is not None and self.device is not None and best.name != self.device.name:
                self._change_reason = "首选的麦克风回来了"
                self._stop_proc("preferred mic back")

    def inject(self, pcm: bytes) -> int:
        """Self-test: push 16 kHz mono s16le audio through the same VAD/ASR path as the mic (only while recording)."""
        if self.proc is None:
            return 0
        speech, gen, n = self._ensure_speech(), self._gen, 0
        for i in range(0, len(pcm) - CHUNK_BYTES + 1, CHUNK_BYTES):
            with self._speech_lock:
                segs = speech.accept(pcm[i:i + CHUNK_BYTES])
            for seg in segs:
                n += 1
                try:
                    self._q.put_nowait((gen, seg))
                except queue.Full:
                    pass
        return n

    def _stop_proc(self, why):
        proc = self.proc
        if proc is None:
            return
        with self._transcripts_lock:
            self._gen += 1  # in-flight audio and transcriptions of the old generation are dropped
            self.transcripts.clear()
        end_process(proc, self.graceful_quit)
        # Only now is the mic released: proc stays set until arecord has exited.
        self.proc = None
        for t in self._threads:
            t.join(2)
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except (OSError, AttributeError):
                pass
        self._threads = []
        self.pid = None
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        with self._speech_lock:
            if self.speech is not None:
                self.speech.reset()
        self.transcripts.clear()
        self.level_db = -120.0
        self.events.add("audio_off", reason=why)

    def _ensure_speech(self):
        with self._speech_lock:
            if self.speech is None:
                self.speech = self.speech_factory()
            return self.speech

    def _read_pcm(self, proc, gen):
        speech = self._ensure_speech()
        out = proc.stdout
        lv_acc, lv_n = [], 0
        while True:
            data = out.read(CHUNK_BYTES)
            if not data:
                break
            if gen != self._gen:
                return
            lv_acc.append(rms_dbfs(data))
            lv_n += 1
            if lv_n >= 15:  # ~0.5 s
                self.level_db = max(lv_acc)
                lv_acc, lv_n = [], 0
            with self._speech_lock:
                segs = speech.accept(data)
            for seg in segs:
                self.segments += 1
                self.last_speech_at = time.time()
                secs = speech.seconds(seg)
                self.events.add("speech", seconds=round(secs, 1))
                try:
                    self._q.put_nowait((gen, seg))
                except queue.Full:
                    try:
                        self._q.get_nowait()
                    except queue.Empty:
                        pass
                    self._q.put_nowait((gen, seg))

    def _asr_worker(self):
        while not self._stop.is_set():
            try:
                gen, seg = self._q.get(timeout=1)
            except queue.Empty:
                continue
            if gen != self._gen:
                continue
            speech = self._ensure_speech()
            try:
                text = speech.transcribe(seg)
            except Exception as e:
                self.speech_error = f"ASR failed: {e}"[:200]
                continue
            with self._transcripts_lock:  # a switch-off between the check and the append wins
                if gen != self._gen or not text:
                    continue
                self.transcripts.append({"t": time.time(), "text": text})
            try:
                self.on_transcript(text)
            except Exception:
                pass

    def _read_stderr(self, proc):
        for line in proc.stderr:
            self._stderr.append(line.decode("utf-8", "replace").strip()[:300])
