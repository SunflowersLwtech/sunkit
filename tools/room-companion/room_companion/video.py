"""Camera capture. ffmpeg holds the camera only while the video switch is on.

ffmpeg writes two streams: 5 fps JPEG frames (live view, later AI frames) on
stdout, and 1 fps 64x36 grey frames on a side pipe for cheap motion detection.
Frames live only in memory and are dropped when the switch goes off.
"""
from __future__ import annotations

import collections
import os
import re
import subprocess
import threading
import time

from . import devices

MOTION_W, MOTION_H = 64, 36


def jpeg_to_gray(jpeg: bytes, w=MOTION_W, h=MOTION_H) -> bytes | None:
    """Tiny greyscale thumbnail of a JPEG for motion scoring (JPEG draft mode keeps this cheap)."""
    try:
        import io

        from PIL import Image
        im = Image.open(io.BytesIO(jpeg))
        im.draft("L", (w * 4, h * 4))
        return im.convert("L").resize((w, h)).tobytes()
    except Exception:
        return None


def parse_formats(text: str):
    """Parse `v4l2-ctl --list-formats-ext` into [(pixfmt, w, h, fps)]."""
    out = []
    fmt = None
    size = None
    for line in text.splitlines():
        m = re.search(r"'(\w+)'", line)
        if m and "[" in line:
            fmt = m.group(1)
            size = None
            continue
        m = re.search(r"Size: \w+ (\d+)x(\d+)", line)
        if m:
            size = (int(m.group(1)), int(m.group(2)))
            continue
        m = re.search(r"\(([\d.]+) fps\)", line)
        if m and fmt and size:
            out.append((fmt, size[0], size[1], float(m.group(1))))
    return out


FFMPEG_FMT = {"MJPG": "mjpeg", "YUYV": "yuyv422", "H264": "h264", "NV12": "nv12"}


def choose_format(formats, max_width=1920, max_fps=30.0):
    best = None
    for pref in ("MJPG", "H264", "YUYV", "NV12"):
        cands = [f for f in formats if f[0] == pref and f[1] <= max_width and f[3] <= max_fps + 0.01]
        if pref == "YUYV":
            # raw frames over USB 2.0: keep it small
            cands = [f for f in cands if f[1] * f[2] * f[3] <= 1280 * 720 * 10]
        if cands:
            best = max(cands, key=lambda f: (f[1] * f[2], f[3]))
            break
    return best


def build_ffmpeg(dev_path, fmt, live_fps, live_width, motion_fd):
    pix, w, h, fps = fmt
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "v4l2", "-input_format", FFMPEG_FMT.get(pix, "mjpeg"),
        "-video_size", f"{w}x{h}", "-framerate", f"{fps:g}", "-i", dev_path,
        "-an",
        "-filter_complex",
        f"[0:v]fps={live_fps},scale={live_width}:-2,split=2[live][m];"
        f"[m]fps=1,scale={MOTION_W}:{MOTION_H},format=gray[mot]",
        "-map", "[live]", "-c:v", "mjpeg", "-q:v", "6", "-f", "image2pipe", "pipe:1",
        "-map", "[mot]", "-f", "rawvideo", f"pipe:{motion_fd}",
    ]


def end_process(proc, graceful: bool):
    """Stop a capture process. Graceful: ask ffmpeg to quit ("q" on stdin) first, force after 3 s.
    Off by default: Windows ffmpeg started through WSL interop ignores "q" (measured), so it only adds delay."""
    try:
        if graceful and proc.stdin is not None:
            try:
                proc.stdin.write(b"q")
                proc.stdin.flush()
                proc.stdin.close()
                proc.wait(3)
                return
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        proc.terminate()
        try:
            proc.wait(3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(3)
    except OSError:
        pass


class JpegSplitter:
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes):
        self.buf += data
        frames = []
        while True:
            s = self.buf.find(b"\xff\xd8")
            if s < 0:
                self.buf.clear()
                break
            e = self.buf.find(b"\xff\xd9", s + 2)
            if e < 0:
                if s > 0:
                    del self.buf[:s]
                break
            frames.append(bytes(self.buf[s:e + 2]))
            del self.buf[:e + 2]
        if len(self.buf) > 8 * 1024 * 1024:  # garbage, resync
            self.buf.clear()
        return frames


class MotionTracker:
    def __init__(self, events, threshold=6.0, quiet_seconds=20.0):
        self.events = events
        self.threshold = threshold
        self.quiet = quiet_seconds
        self.prev = None
        self.active_since = None
        self.last_motion = 0.0
        self.peak = 0.0
        self.score = 0.0
        self.brightness = None

    def feed(self, gray: bytes, now: float | None = None):
        now = now or time.time()
        self.brightness = sum(gray) / len(gray)
        if self.prev is not None:
            self.score = sum(abs(a - b) for a, b in zip(gray, self.prev)) / len(gray)
            if self.score >= self.threshold:
                if self.active_since is None:
                    self.active_since = now
                    self.peak = 0.0
                    self.events.add("motion_start", score=round(self.score, 1))
                self.last_motion = now
                self.peak = max(self.peak, self.score)
        self.prev = gray
        self.check_end(now)

    def check_end(self, now: float | None = None, force=False):
        now = now or time.time()
        if self.active_since is not None and (force or now - self.last_motion >= self.quiet):
            self.events.add("motion_end", seconds=round(self.last_motion - self.active_since + 1),
                            peak=round(self.peak, 1))
            self.active_since = None

    def reset(self):
        self.check_end(force=True)
        self.prev = None
        self.score = 0.0
        self.brightness = None


class VideoPipeline:
    def __init__(self, switches, events, cfg, find_device=None, list_formats=None, build_cmd=None,
                 motion_from_frames=False):
        self.switches = switches
        self.events = events
        self.cfg = cfg
        self.find_device = find_device or (lambda: devices.find_video(cfg.get("video_vendor", "2ca3,05c6")))
        self.list_formats = list_formats or _list_formats
        self.build_cmd = build_cmd or build_ffmpeg
        # Windows ffmpeg (via WSL interop) only has stdout, so motion is scored from the live frames.
        self.motion_from_frames = motion_from_frames
        self.graceful_quit = cfg.get("graceful_quit", False)
        self.waiting_since = None
        self.state = "off"
        self.detail = ""
        self.device = None
        self.format = None
        self.proc = None
        self._accept = False
        self.pid = None
        self.motion = MotionTracker(events, cfg.get("motion_threshold", 6.0))
        self._cond = threading.Condition()
        self._frame = None
        self._frame_ts = 0.0
        self._frame_seq = 0
        self._fps_count = 0
        self._fps_t0 = time.time()
        self.fps = 0.0
        self._threads = []
        self._stderr = collections.deque(maxlen=20)
        self._retry_at = 0.0
        self._backoff = 2.0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._tick_lock = threading.Lock()

    # ---- public ----
    def start(self):
        t = threading.Thread(target=self._loop, name="video", daemon=True)
        t.start()

    def poke(self):
        self._wake.set()

    def shutdown(self):
        self._stop.set()
        self._wake.set()
        with self._tick_lock:
            self._stop_proc("shutdown")

    def latest(self, max_age=3.0):
        with self._cond:
            if self._frame is None or time.time() - self._frame_ts > max_age:
                return None, self._frame_seq
            return self._frame, self._frame_seq

    def wait_frame(self, after_seq, timeout=2.0):
        with self._cond:
            self._cond.wait_for(lambda: self._frame_seq != after_seq or self._frame is None, timeout)
            return self._frame, self._frame_seq

    def status(self):
        return {
            "state": self.state,
            "detail": self.detail,
            "device": self.device.path if self.device else None,
            "device_name": self.device.name if self.device else None,
            "format": "%s %dx%d@%g" % self.format if self.format else None,
            "fps": round(self.fps, 1),
            "pid": self.pid,
            "motion": round(self.motion.score, 1),
            "moving": self.motion.active_since is not None,
            "brightness": round(self.motion.brightness, 1) if self.motion.brightness is not None else None,
            "stderr": list(self._stderr)[-3:],
        }

    # ---- loop ----
    def _loop(self):
        while not self._stop.is_set():
            try:
                with self._tick_lock:
                    self._tick()
            except Exception as e:  # keep supervising
                self.detail = f"supervisor error: {e}"
            self._wake.wait(1.0)
            self._wake.clear()

    def _tick(self):
        if self._stop.is_set():
            return
        if not self.switches.get("video"):
            if self.proc is not None:
                self._stop_proc("switched off")
            self.state, self.detail = "off", ""
            self._backoff = 2.0
            self._retry_at = 0.0
            return
        if self.proc is not None:
            rc = self.proc.poll()
            if rc is None:
                self.motion.check_end()
                return
            err = " | ".join(list(self._stderr)[-2:])
            self._stop_proc(f"ffmpeg exited {rc}")
            self.state, self.detail = "error", f"ffmpeg exited {rc}: {err}"[:300]
            self._retry_at = time.time() + self._backoff
            self._backoff = min(self._backoff * 2, 60.0)
            return
        if time.time() < self._retry_at:
            return
        dev = self.find_device()
        if dev is None:
            self.device = None
            if self.state != "waiting_device":
                self.waiting_since = time.time()
            self.state, self.detail = "waiting_device", "没找到摄像头（相机要开机并进入网络摄像头模式）"
            return
        self.waiting_since = None
        fmt = choose_format(self.list_formats(dev.path), self.cfg.get("capture_max_width", 1920),
                            self.cfg.get("capture_max_fps", 30))
        if fmt is None:
            self.state, self.detail = "error", "摄像头没有可用的画面格式"
            self._retry_at = time.time() + 30
            return
        self.device, self.format = dev, fmt
        self._start_proc(dev, fmt)

    def _start_proc(self, dev, fmt):
        side = not self.motion_from_frames
        r, w = os.pipe() if side else (None, None)
        cmd = self.build_cmd(dev.path, fmt, self.cfg.get("live_fps", 5), self.cfg.get("live_width", 1280), w)
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if self.graceful_quit else subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, pass_fds=(w,) if side else ())
        except OSError as e:
            if side:
                os.close(r)
                os.close(w)
            self.state, self.detail = "error", f"cannot start ffmpeg: {e}"
            self._retry_at = time.time() + 30
            return
        if side:
            os.close(w)
        self._accept = True
        self.pid = self.proc.pid
        self.state, self.detail = "running", ""
        self._fps_t0, self._fps_count = time.time(), 0
        proc = self.proc
        self._threads = [
            threading.Thread(target=self._read_frames, args=(proc,), daemon=True),
            threading.Thread(target=self._read_motion, args=(proc, r), daemon=True) if side else
            threading.Thread(target=self._motion_from_frames, args=(proc,), daemon=True),
            threading.Thread(target=self._read_stderr, args=(proc,), daemon=True),
        ]
        for t in self._threads:
            t.start()
        self.events.add("video_on", device=dev.name, format="%s %dx%d@%g" % fmt)

    def _stop_proc(self, why):
        proc = self.proc
        if proc is None:
            return
        self._accept = False  # readers stop publishing frames right away
        end_process(proc, self.graceful_quit)
        # Only now is the camera released: proc stays set until ffmpeg has exited.
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
        with self._cond:
            self._frame = None
            self._frame_seq += 1
            self._cond.notify_all()
        self.motion.reset()
        self.fps = 0.0
        self.events.add("video_off", reason=why)

    def _read_frames(self, proc):
        sp = JpegSplitter()
        out = proc.stdout
        while True:
            data = out.read1(65536) if hasattr(out, "read1") else out.read(65536)
            if not data:
                break
            for fr in sp.feed(data):
                now = time.time()
                with self._cond:
                    if self.proc is not proc or not self._accept:
                        return
                    self._frame, self._frame_ts = fr, now
                    self._frame_seq += 1
                    self._cond.notify_all()
                self._fps_count += 1
                if now - self._fps_t0 >= 5:
                    self.fps = self._fps_count / (now - self._fps_t0)
                    self._fps_t0, self._fps_count = now, 0

    def _read_motion(self, proc, fd):
        size = MOTION_W * MOTION_H
        with os.fdopen(fd, "rb", buffering=0) as f:
            buf = b""
            while True:
                chunk = f.read(size - len(buf))
                if not chunk:
                    break
                buf += chunk
                if len(buf) == size:
                    if self.proc is proc and self._accept:
                        self.motion.feed(buf)
                    buf = b""

    def _motion_from_frames(self, proc):
        seq = -1
        while self.proc is proc and self._accept:
            frame, seq = self.wait_frame(seq, timeout=2.0)
            if frame is None:
                continue
            gray = jpeg_to_gray(frame)
            if gray is not None and self.proc is proc and self._accept:
                self.motion.feed(gray)
            time.sleep(1.0)

    def _read_stderr(self, proc):
        for line in proc.stderr:
            self._stderr.append(line.decode("utf-8", "replace").strip()[:300])


def _list_formats(path):
    try:
        return parse_formats(subprocess.run(["v4l2-ctl", "-d", path, "--list-formats-ext"],
                                            capture_output=True, text=True, timeout=5).stdout)
    except (OSError, subprocess.TimeoutExpired):
        return []
