"""Windows side of the capture when room-companion runs in WSL on a Windows PC.

The camera and microphone stay Windows devices (no USB passthrough into WSL).
Windows ffmpeg.exe reads them through DirectShow and is started from WSL via
interop; killing the WSL-side process also ends the Windows process, which is
what releases the device. Evidence that a device is really released comes from
Windows itself: the process table, and the per-app camera/microphone usage
record that drives the privacy indicator (LastUsedTimeStop == 0 means in use).
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import threading
import time
from dataclasses import dataclass

SYS32 = "/mnt/c/Windows/System32"
CONSENT = r"HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"


class Interop:
    """Keeps WSL_INTEROP pointing at a socket that can start Windows programs.

    A systemd service has no WSL_INTEROP and falls back to /run/WSL/1_interop. After WSL restarts that
    default can be broken (every .exe fails with "Invalid argument") while the socket of another WSL
    session still works. This checks the current choice with a trivial cmd.exe call and, if it fails,
    tries every socket in /run/WSL, newest first. The choice goes into os.environ, so every Windows
    program started afterwards (ffmpeg.exe, powershell.exe, tasklist.exe, llama-server.exe, ...) uses it.
    """

    def __init__(self, run=subprocess.run, sock_dir="/run/WSL", environ=None, min_interval=600.0, min_retry=10.0,
                 owner_uid=0):
        self.run = run
        self.sock_dir = sock_dir
        self.environ = os.environ if environ is None else environ
        self.min_interval = min_interval  # re-check a working choice this often
        self.min_retry = min_retry  # after a failure, don't probe again sooner than this
        self.owner_uid = owner_uid  # WSL's own sockets belong to root; anything else in that folder is ignored
        self.ok = None
        self.socket = None  # None: the default (no WSL_INTEROP)
        self.repairs = 0
        self._checked = 0.0
        self._lock = threading.Lock()

    def _works(self, sock) -> bool:
        env = dict(self.environ)
        if sock is None:
            env.pop("WSL_INTEROP", None)
        else:
            env["WSL_INTEROP"] = sock
        try:
            p = self.run([f"{SYS32}/cmd.exe", "/d", "/c", "exit 0"], env=env, capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return p.returncode == 0

    def _candidates(self):
        cur = self.environ.get("WSL_INTEROP")
        out = [cur] if cur else []
        out.append(None)
        try:
            names = [n for n in os.listdir(self.sock_dir) if n.endswith("_interop")]
        except OSError:
            names = []
        socks = []
        for n in names:
            p = os.path.join(self.sock_dir, n)
            try:
                st = os.stat(p)  # follows 1_interop -> 2_interop; one call, so a socket that just went away is skipped
            except OSError:
                continue
            if stat.S_ISSOCK(st.st_mode) and st.st_uid == self.owner_uid:
                socks.append((st.st_mtime, p))
        socks.sort(reverse=True)
        out += [p for _, p in socks if p != cur]
        return out

    def ensure(self, force=False, now=None) -> bool:
        """True when Windows programs can be started. Cheap when checked recently."""
        now = time.time() if now is None else now
        with self._lock:
            if self.ok is not None:
                # a working choice is re-checked every min_interval; after a failure (or when a caller saw a
                # Windows program fail to start) at most every min_retry
                limit = self.min_retry if (force or not self.ok) else self.min_interval
                if now - self._checked < limit:
                    return bool(self.ok)
            self._checked = now
            before = self.environ.get("WSL_INTEROP")
            for sock in self._candidates():
                if self._works(sock):
                    if sock is None:
                        self.environ.pop("WSL_INTEROP", None)
                    else:
                        self.environ["WSL_INTEROP"] = sock
                    if sock != before:
                        self.repairs += 1
                    self.ok, self.socket = True, sock
                    return True
            self.ok = False
            return False

    def status(self):
        return {"ok": self.ok, "socket": self.socket or "default", "repairs": self.repairs}


@dataclass
class DshowDevice:
    """A DirectShow device; `path` and `alsa_name` are the dshow name so the pipelines can stay generic."""
    name: str
    kind: str  # "video" or "audio"
    vendor: str | None = None
    card_index: int | None = None

    @property
    def path(self) -> str:
        return self.name

    @property
    def alsa_name(self) -> str:
        return self.name


def parse_dshow_devices(text: str) -> list[DshowDevice]:
    """Parse `ffmpeg -list_devices true -f dshow -i dummy` output."""
    out = []
    for m in re.finditer(r'"([^"]+)"\s+\((video|audio)\)', text):
        out.append(DshowDevice(name=m.group(1), kind=m.group(2)))
    return out


def parse_dshow_formats(text: str):
    """Parse `ffmpeg -f dshow -list_options true -i video=NAME` into [(fmt, w, h, fps)]."""
    names = {"mjpeg": "MJPG", "h264": "H264", "yuyv422": "YUYV", "nv12": "NV12"}
    out = set()
    for m in re.finditer(r"(?:vcodec|pixel_format)=(\w+)\s+min s=\d+x\d+ fps=[\d.]+ max s=(\d+)x(\d+) fps=([\d.]+)", text):
        fmt = names.get(m.group(1))
        if fmt:
            out.add((fmt, int(m.group(2)), int(m.group(3)), float(m.group(4))))
    return sorted(out)


class Dshow:
    def __init__(self, ffmpeg_exe: str, run=subprocess.run, interop=None):
        self.ffmpeg = ffmpeg_exe
        self.run = run
        self.interop = interop
        self._cache = (0.0, [])

    def _ffmpeg_out(self, args, timeout=15) -> str:
        return run_windows(self.run, [self.ffmpeg, "-hide_banner", *args], self.interop, timeout,
                           lambda p: (p.stdout + p.stderr).decode("utf-8", "replace")) or ""

    def devices(self, max_age=5.0) -> list[DshowDevice]:
        t, devs = self._cache
        if time.time() - t < max_age:
            return devs
        devs = parse_dshow_devices(self._ffmpeg_out(["-list_devices", "true", "-f", "dshow", "-i", "dummy"]))
        self._cache = (time.time(), devs)
        return devs

    def find(self, kind: str, prefer: list[str]) -> DshowDevice | None:
        """First device of `kind` whose name contains a preferred word, in preference order."""
        devs = [d for d in self.devices() if d.kind == kind]
        for word in prefer:
            for d in devs:
                if word.lower() in d.name.lower():
                    return d
        return None

    def formats(self, name: str):
        return parse_dshow_formats(self._ffmpeg_out(["-f", "dshow", "-list_options", "true", "-i", f"video={name}"]))

    def video_cmd(self, name, fmt, live_fps, live_width, motion_fd=None):
        pix, w, h, fps = fmt
        codec = {"MJPG": "mjpeg", "H264": "h264"}.get(pix)
        src = ["-vcodec", codec] if codec else ["-pixel_format", {"YUYV": "yuyv422", "NV12": "nv12"}.get(pix, "yuyv422")]
        return [self.ffmpeg, "-hide_banner", "-loglevel", "error",
                "-f", "dshow", "-rtbufsize", "64M", *src, "-video_size", f"{w}x{h}", "-framerate", f"{fps:g}",
                "-i", f"video={name}", "-an",
                "-vf", f"fps={live_fps},scale={live_width}:-2",
                "-c:v", "mjpeg", "-q:v", "6", "-f", "image2pipe", "pipe:1"]

    def audio_cmd(self, name, rate=16000):
        return [self.ffmpeg, "-hide_banner", "-loglevel", "error",
                "-f", "dshow", "-audio_buffer_size", "50", "-i", f"audio={name}",
                "-ac", "1", "-ar", str(rate), "-f", "s16le", "pipe:1"]


def interop_failed(args, p) -> bool:
    """A Windows program that never started because the interop channel is broken: WSL's loader exits
    with 1 and prints "<path>: Invalid argument" (measured), not an OSError in the caller."""
    err = p.stderr.decode("utf-8", "replace") if isinstance(p.stderr, bytes) else (p.stderr or "")
    first = err.strip().splitlines()[0] if err.strip() else ""
    return p.returncode != 0 and not p.stdout and first == f"{args[0]}: Invalid argument"


def run_windows(run, args, interop, timeout, read):
    """Run a Windows program and return read(result), or None when it could not be run. If it could not
    start because the interop channel is broken, let `interop` find a working one and try once more."""
    for attempt in (0, 1):
        try:
            p = run(args, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        except FileNotFoundError:
            return None  # wrong path, not a channel problem
        except OSError:
            p = None
        if p is not None and not interop_failed(args, p):
            return read(p)
        if attempt or interop is None or not interop.ensure(force=True):
            return None
    return None


# ---- evidence ----

def parse_tasklist_csv(text: str, image: str) -> list[int]:
    pids = []
    for line in text.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) >= 2 and cols[0].strip('"').lower() == image.lower():
            try:
                pids.append(int(cols[1]))
            except ValueError:
                pass
    return pids


def parse_consent(text: str, needle: str) -> dict | None:
    """From `reg query <ConsentStore>\\<cap>\\NonPackaged /s`, the usage record of the app whose key contains needle."""
    best = None
    for b in re.split(r"\r?\n(?=HKEY_)", text):
        head = b.splitlines()[0] if b else ""
        if needle.lower() not in head.lower():
            continue
        vals = dict(re.findall(r"\s+(LastUsedTime(?:Start|Stop))\s+REG_QWORD\s+0x([0-9a-fA-F]+)", b))
        if not vals:
            continue
        start = int(vals.get("LastUsedTimeStart", "0"), 16)
        stop = int(vals.get("LastUsedTimeStop", "0"), 16)
        rec = {"in_use": start > 0 and stop == 0, "start": filetime_to_unix(start), "stop": filetime_to_unix(stop)}
        if best is None or (rec["start"] or 0) > (best["start"] or 0):
            best = rec
    return best


def filetime_to_unix(ft: int) -> float | None:
    return ft / 1e7 - 11644473600 if ft else None


class Evidence:
    """What Windows says about the devices, cached briefly because each probe spawns a Windows process."""

    def __init__(self, run=subprocess.run, ttl=3.0, app_key="ffmpeg.exe", interop=None):
        self.run = run
        self.ttl = ttl
        self.app_key = app_key  # how our ffmpeg.exe shows up in the usage record, e.g. "full_build#bin#ffmpeg.exe"
        self.interop = interop
        self._cache = {}

    def _cmd(self, args, timeout=10) -> str | None:
        """The program's output, or None when it could not be asked (then the answer is unknown, not empty)."""
        return run_windows(self.run, args, self.interop, timeout,
                           lambda p: p.stdout.decode("utf-8", "replace") if isinstance(p.stdout, bytes) else (p.stdout or ""))

    def _cached(self, key, fn):
        t, v = self._cache.get(key, (0.0, None))
        if time.time() - t < self.ttl:
            return v
        v = fn()
        self._cache[key] = (time.time(), v)
        return v

    def pids(self, image: str) -> list[int] | None:
        """PIDs of `image`; None when Windows could not be asked (not the same as "none running")."""
        def probe():
            text = self._cmd([f"{SYS32}/tasklist.exe", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"])
            return None if text is None else parse_tasklist_csv(text, image)
        return self._cached(("pids", image), probe)

    def usage(self, capability: str) -> dict | None:
        def probe():
            text = self._cmd([f"{SYS32}/reg.exe", "query", f"{CONSENT}\\{capability}\\NonPackaged", "/s"])
            return None if text is None else parse_consent(text, self.app_key)
        return self._cached(("usage", capability), probe)

    def in_use_by_others(self, capability: str) -> list[str] | None:
        """Apps (other than ours) that Windows says are using the camera or mic right now; None if unknown."""
        def probe():
            out = []
            for sub in ("", "\\NonPackaged"):
                text = self._cmd([f"{SYS32}/reg.exe", "query", f"{CONSENT}\\{capability}{sub}", "/s"])
                if text is None:
                    return None
                for b in re.split(r"\r?\n(?=HKEY_)", text):
                    head = b.splitlines()[0] if b else ""
                    if not head or self.app_key.lower() in head.lower():
                        continue
                    vals = dict(re.findall(r"\s+(LastUsedTime(?:Start|Stop))\s+REG_QWORD\s+0x([0-9a-fA-F]+)", b))
                    if vals and int(vals.get("LastUsedTimeStart", "0"), 16) > 0 and int(vals.get("LastUsedTimeStop", "1"), 16) == 0:
                        out.append(head.rsplit("\\", 1)[-1].split("#")[-1])
            return sorted(set(out))
        return self._cached(("others", capability), probe)
