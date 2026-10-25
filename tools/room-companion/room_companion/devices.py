"""Find the camera and microphone from sysfs and make their device nodes exist in /dev.

The container is started with device cgroup rules that only allow video4linux
(major 81) and ALSA (major 116), so it can create those nodes itself when the
camera or mic is plugged in after the container started.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass

SYS_V4L = "/sys/class/video4linux"
SYS_SOUND = "/sys/class/sound"
PROC_CARDS = "/proc/asound/cards"


@dataclass
class VideoDevice:
    path: str
    name: str
    vendor: str | None


@dataclass
class AudioDevice:
    card_index: int
    card_id: str
    name: str

    @property
    def alsa_name(self) -> str:
        return f"plughw:CARD={self.card_id},DEV=0"


def _read(p: str) -> str | None:
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return None


def ensure_node(dev_path: str, sys_dev_file: str) -> bool:
    """Create or fix a char device node from a sysfs 'dev' file ("81:0")."""
    mm = _read(sys_dev_file)
    if not mm or ":" not in mm:
        return False
    major, minor = (int(x) for x in mm.split(":"))
    want = os.makedev(major, minor)
    try:
        st = os.stat(dev_path)
        if stat.S_ISCHR(st.st_mode) and st.st_rdev == want:
            return True
        os.unlink(dev_path)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    try:
        os.makedirs(os.path.dirname(dev_path), exist_ok=True)
        os.mknod(dev_path, 0o660 | stat.S_IFCHR, want)
        return True
    except OSError:
        return False


def _usb_vendor(sys_node: str) -> str | None:
    # .../videoN/device -> USB interface; its parent is the USB device with idVendor
    dev = os.path.realpath(os.path.join(sys_node, "device"))
    for p in (dev, os.path.dirname(dev)):
        v = _read(os.path.join(p, "idVendor"))
        if v:
            return v
    return None


def _is_capture(path: str) -> bool:
    try:
        out = subprocess.run(["v4l2-ctl", "-d", path, "--info"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    m = re.search(r"Device Caps\s*:.*?\n((?:\t\t.*\n)+)", out)
    caps = m.group(1) if m else out
    return "Video Capture" in caps


def find_video(prefer_vendor: str | None = "2ca3,05c6", dev_root: str = "/dev") -> VideoDevice | None:
    # The Osmo Action 5 Pro enumerates as 05c6:8004 (Qualcomm), not DJI's own 2ca3.
    try:
        names = sorted(os.listdir(SYS_V4L), key=lambda s: int(re.sub(r"\D", "", s) or 0))
    except OSError:
        return None
    found = []
    for n in names:
        node = os.path.join(SYS_V4L, n)
        path = os.path.join(dev_root, n)
        if not ensure_node(path, os.path.join(node, "dev")):
            continue
        if not _is_capture(path):
            continue
        found.append(VideoDevice(path=path, name=_read(os.path.join(node, "name")) or n, vendor=_usb_vendor(node)))
    if not found:
        return None
    wanted = {v.strip().lower() for v in (prefer_vendor or "").split(",") if v.strip()}
    for d in found:
        if d.vendor in wanted or "osmo" in (d.name or "").lower():
            return d
    return found[0]


def list_audio_cards() -> list[AudioDevice]:
    txt = _read(PROC_CARDS) or ""
    cards = []
    # " 1 [Mini           ]: USB-Audio - DJI MIC MINI"
    for m in re.finditer(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*)$", txt, re.M):
        idx = int(m.group(1))
        if os.path.isdir(f"/proc/asound/card{idx}/pcm0c"):
            cards.append(AudioDevice(card_index=idx, card_id=m.group(2), name=m.group(3).strip()))
    return cards


def ensure_sound_nodes(dev_root: str = "/dev") -> None:
    try:
        names = os.listdir(SYS_SOUND)
    except OSError:
        return
    for n in names:
        f = os.path.join(SYS_SOUND, n, "dev")
        if os.path.exists(f):
            ensure_node(os.path.join(dev_root, "snd", n), f)


def find_audio(prefer=("dji", "mic", "osmo", "usb")) -> AudioDevice | None:
    cards = list_audio_cards()
    if not cards:
        return None
    ensure_sound_nodes()
    for word in prefer:
        for c in cards:
            if word in c.name.lower() or word in c.card_id.lower():
                return c
    return cards[0]


def capture_status(card_index: int) -> str:
    """Kernel's view of the capture stream: 'closed' when nothing is recording."""
    s = _read(f"/proc/asound/card{card_index}/pcm0c/sub0/status")
    if s is None:
        return "unknown"
    if s.startswith("closed"):
        return "closed"
    m = re.search(r"state:\s*(\w+)", s)
    return m.group(1).lower() if m else "open"
