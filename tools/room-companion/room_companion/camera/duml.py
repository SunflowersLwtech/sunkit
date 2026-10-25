"""DJI's internal command protocol ("DUML", SOF 0x55) as community projects reverse-engineered it.

Not supported by DJI. It is what DJI Mimo itself speaks, so it can do more than the official
protocol (pick the camera's mode including its USB webcam mode, join a Wi-Fi network, live view),
and it may stop working after a firmware update. Framing, CRC parameters and command bytes follow the
protocol notes of RB14/dji-vcam (MIT, verified on an Action 5 Pro), which build on KonradIT/osmosis,
eerimoq/moblin and DJI's own demo. The frame codec below is adapted from dji-vcam's tools/duml.py
(MIT License, Copyright (c) 2026 razboy; see THIRD_PARTY_NOTICES.md).

Frame:
    0     SOF 0x55
    1..2  u16-LE: bits[9:0] total length (13 + payload), bits[15:10] version (1)
    3     CRC8 over bytes [0:3]   (reflected 0x31, init 0xEE / table form init 0x77, poly 0x8C)
    4     sender   (id << 5) | type
    5     receiver (id << 5) | type
    6..7  sequence (the camera echoes it)
    8     flags: 0x40 request, 0xC0 response, 0x00 push
    9     command set
    10    command id
    11..  payload
    -2..  CRC16-LE over everything before it (table init 0x3692, poly 0x8408)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

try:
    from . import rsdk
except ImportError:  # run as a script next to rsdk.py
    import rsdk  # type: ignore

SOF = 0x55
HEADER_LEN = 11
OVERHEAD = 13
VERSION_BITS = 0x0400

FLAG_PUSH = 0x00
FLAG_REQUEST = 0x40
FLAG_WRITE = 0x80
FLAG_RESPONSE = 0xC0

ADDR_CAMERA = 0x01
ADDR_APP = 0x02
ADDR_BATTERY = 0x05
ADDR_WIFI = 0x07
ADDR_DM368_0 = 0x08
ADDR_SYSTEM = 0x1C
ADDR_DM368_1 = 0x28
ADDR_DM368_2 = 0x48
ADDR_SESSION = 0xF0

# Shooting modes for 0x02/0xE1 (same codes as the official protocol). Only these are ever sent:
# enumerating unknown values froze a camera until it was power-cycled (dji-vcam camera-controls.md).
MODES = {"video": 0x01, "photo": 0x05, "live_streaming": 0x1A, "uvc_webcam": 0x23}

# 62-byte "APP" device-info blob a camera expects in reply to its 0x00/0x81 request.
APP_DEVICE_INFO = b"\x00APP" + bytes(37) + b"\x02" + bytes(8) + b"\x02\x08" + bytes(10)


def _table(poly: int) -> list[int]:
    out = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (c >> 1) ^ poly if c & 1 else c >> 1
        out.append(c)
    return out


_T8 = _table(0x8C)
_T16 = _table(0x8408)


def crc8(data: bytes) -> int:
    c = 0x77
    for b in data:
        c = _T8[(c ^ b) & 0xFF]
    return c


def crc16(data: bytes) -> int:
    c = 0x3692
    for b in data:
        c = (c >> 8) ^ _T16[(c ^ b) & 0xFF]
    return c & 0xFFFF


def pack_string(text: str) -> bytes:
    raw = text.encode("utf-8")
    if len(raw) > 255:
        raise ValueError("string too long")
    return bytes([len(raw)]) + raw


@dataclass(frozen=True)
class Frame:
    sender: int
    receiver: int
    seq: int
    flags: int
    cmd_set: int
    cmd_id: int
    payload: bytes = b""

    @property
    def is_request(self) -> bool:
        return self.flags & 0xE0 == FLAG_REQUEST

    @property
    def is_response(self) -> bool:
        return self.flags & 0xC0 == FLAG_RESPONSE

    @property
    def key(self) -> tuple[int, int]:
        return (self.cmd_set, self.cmd_id)

    def encode(self) -> bytes:
        total = OVERHEAD + len(self.payload)
        if total > 0x3FF:
            raise ValueError(f"frame too long: {total}")
        head = bytearray(struct.pack("<BH", SOF, VERSION_BITS | total))
        head.append(crc8(head))
        head += bytes([self.sender, self.receiver])
        head += struct.pack("<H", self.seq & 0xFFFF)
        head += bytes([self.flags, self.cmd_set, self.cmd_id])
        head += self.payload
        return bytes(head) + struct.pack("<H", crc16(head))

    def reply(self, payload: bytes) -> "Frame":
        """The response to this request: addresses swapped, same sequence."""
        return Frame(self.receiver, self.sender, self.seq, FLAG_RESPONSE, self.cmd_set, self.cmd_id, payload)

    def describe(self) -> str:
        kind = {FLAG_REQUEST: "req", FLAG_RESPONSE: "rsp", FLAG_PUSH: "push"}.get(self.flags, f"f{self.flags:02x}")
        return (f"duml {self.sender:02x}->{self.receiver:02x} {kind} {self.cmd_set:02x}/{self.cmd_id:02x} "
                f"seq={self.seq:04x} payload={self.payload.hex()}")


def decode(raw: bytes) -> Frame:
    if len(raw) < OVERHEAD or raw[0] != SOF:
        raise ValueError("not a DUML frame")
    total = struct.unpack_from("<H", raw, 1)[0] & 0x3FF
    if total != len(raw):
        raise ValueError(f"length mismatch: header {total}, got {len(raw)}")
    if crc8(raw[:3]) != raw[3]:
        raise ValueError("bad CRC8")
    if crc16(raw[:-2]) != struct.unpack_from("<H", raw, total - 2)[0]:
        raise ValueError("bad CRC16")
    return Frame(raw[4], raw[5], struct.unpack_from("<H", raw, 6)[0], raw[8], raw[9], raw[10], bytes(raw[11:-2]))


# ---- payloads ----

def pairing(identifier: str, token: str) -> bytes:
    """0x07/0x45 to the Wi-Fi module. Reply byte 1: 01 already approved, 02 the camera shows a
    prompt with `token`; after the tap it sends us a 0x07/0x46 request that must be answered."""
    return pack_string(identifier) + pack_string(token)


def wifi_join(ssid: str, password: str) -> bytes:
    """0x07/0x47: join a network as a client (only in Live Streaming mode). Reply 00 00 = joined."""
    return pack_string(ssid) + pack_string(password)


LIVESTREAM_STOP = bytes.fromhex("01011a000102")  # 0x02/0x8E to 0x08: ends a livestream, the join and the mode


def parse_status_reply(frame: Frame | None) -> int | None:
    return frame.payload[0] if frame is not None and frame.payload else None


def parse_battery(payload: bytes) -> int | None:
    """0x0D/0x02 push from the battery (sender 0x05): percent at byte 20."""
    return payload[20] if len(payload) > 20 else None


def parse_mac(frame: Frame | None) -> str | None:
    """0x07/0x0C reply: [status][6-byte MAC]."""
    if frame is None or len(frame.payload) < 7 or frame.payload[0] != 0:
        return None
    return ":".join(f"{b:02x}" for b in frame.payload[1:7])


# ---- both framings on one notify characteristic ----

class Demux:
    """The camera's notify characteristic carries DUML (0x55) and official (0xAA) frames, and a frame
    can span notifications. Splits the byte stream into complete frames of either kind."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[tuple[str, bytes]]:
        self._buf += data
        out = []
        while self._buf:
            sof = self._buf[0]
            if sof not in (SOF, 0xAA):
                del self._buf[0]
                continue
            if len(self._buf) < 4:
                break
            total = struct.unpack_from("<H", self._buf, 1)[0] & 0x3FF
            if sof == SOF and (total < OVERHEAD or crc8(self._buf[:3]) != self._buf[3]):
                del self._buf[0]
                continue
            if sof == 0xAA:
                # check the official header's CRC16 before trusting its length: a stray 0xAA would
                # otherwise hold back everything after it while waiting for up to 1023 bytes
                if len(self._buf) < 12:
                    break
                if total < 18 or rsdk.crc16(bytes(self._buf[:10])) != struct.unpack_from("<H", self._buf, 10)[0]:
                    del self._buf[0]
                    continue
            if len(self._buf) < total:
                break
            out.append(("duml" if sof == SOF else "rsdk", bytes(self._buf[:total])))
            del self._buf[:total]
        if len(self._buf) > 4096:
            self._buf.clear()
        return out
