"""Windows side of the capture when room-ai runs in WSL on a Windows PC.

The camera and microphone stay Windows devices (no USB passthrough into WSL).
Windows ffmpeg.exe reads them through DirectShow and is started from WSL via
interop; killing the WSL-side process also ends the Windows process, which is
what releases the device. Evidence that a device is really released comes from
Windows itself: the process table, and the per-app camera/microphone usage
record that drives the privacy indicator (LastUsedTimeStop == 0 means in use).
"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass

SYS32 = "/mnt/c/Windows/System32"
CONSENT = r"HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"


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
    def __init__(self, ffmpeg_exe: str, run=subprocess.run):
        self.ffmpeg = ffmpeg_exe
        self.run = run
        self._cache = (0.0, [])

    def _ffmpeg_out(self, args, timeout=15) -> str:
        try:
            p = self.run([self.ffmpeg, "-hide_banner", *args], capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return (p.stdout + p.stderr).decode("utf-8", "replace")

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

    def __init__(self, run=subprocess.run, ttl=3.0, app_key="ffmpeg.exe"):
        self.run = run
        self.ttl = ttl
        self.app_key = app_key  # how our ffmpeg.exe shows up in the usage record, e.g. "full_build#bin#ffmpeg.exe"
        self._cache = {}

    def _cmd(self, args, timeout=10) -> str:
        try:
            p = self.run(args, capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return p.stdout.decode("utf-8", "replace") if isinstance(p.stdout, bytes) else (p.stdout or "")

    def _cached(self, key, fn):
        t, v = self._cache.get(key, (0.0, None))
        if time.time() - t < self.ttl:
            return v
        v = fn()
        self._cache[key] = (time.time(), v)
        return v

    def pids(self, image: str) -> list[int]:
        return self._cached(("pids", image), lambda: parse_tasklist_csv(
            self._cmd([f"{SYS32}/tasklist.exe", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"]), image))

    def usage(self, capability: str) -> dict | None:
        return self._cached(("usage", capability), lambda: parse_consent(
            self._cmd([f"{SYS32}/reg.exe", "query", f"{CONSENT}\\{capability}\\NonPackaged", "/s"]), self.app_key))

    def in_use_by_others(self, capability: str) -> list[str]:
        """Apps (other than ours) that Windows says are using the camera or mic right now."""
        def probe():
            out = []
            for sub in ("", "\\NonPackaged"):
                text = self._cmd([f"{SYS32}/reg.exe", "query", f"{CONSENT}\\{capability}{sub}", "/s"])
                for b in re.split(r"\r?\n(?=HKEY_)", text):
                    head = b.splitlines()[0] if b else ""
                    if not head or self.app_key.lower() in head.lower():
                        continue
                    vals = dict(re.findall(r"\s+(LastUsedTime(?:Start|Stop))\s+REG_QWORD\s+0x([0-9a-fA-F]+)", b))
                    if vals and int(vals.get("LastUsedTimeStart", "0"), 16) > 0 and int(vals.get("LastUsedTimeStop", "1"), 16) == 0:
                        out.append(head.rsplit("\\", 1)[-1].split("#")[-1])
            return sorted(set(out))
        return self._cached(("others", capability), probe)
