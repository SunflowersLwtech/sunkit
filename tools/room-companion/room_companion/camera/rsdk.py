"""DJI's official camera remote protocol ("DJI R SDK", SOF 0xAA) over Bluetooth LE.

Written from DJI's published protocol description for the Osmo Action 4 / 5 Pro / 6 and Osmo 360
(github.com/dji-sdk/Osmo-GPS-Controller-Demo, docs/protocol.md and docs/protocol_data_segment.md).
No code was copied from that repository. What the protocol can do on an Action 5 Pro: pair (the camera
asks for a tap the first time), report its status (mode, battery, temperature, sleep), switch modes
(its mode list includes the USB webcam mode, 0x23, which is how this tool tries to bring the webcam
back), start/stop recording, press its buttons, sleep, wake (by advertising, within 30 minutes of
sleep) and restart. It cannot set up Wi-Fi or a livestream. This module implements only what the
tool uses: pairing, status, mode switch, stop recording, sleep/normal and the wake broadcast.

Frame (little-endian):
    0  SOF 0xAA
    1  u16 bits[9:0] total length, bits[15:10] version (0)
    3  cmd type: bits[4:0] reply wanted (0 no, 1 optional, 2 required), bit 5 = response frame
    4  encryption (0)
    5  3 reserved bytes
    8  u16 sequence (a response carries the request's)
    10 CRC16 over bytes [0:10]
    12 cmd set, cmd id, payload
    -4 CRC32 over everything before it
CRC16: reflected 0x8005 (0xA001), init 0x3AA3. CRC32: reflected 0x04C11DB7 (0xEDB88320), init 0x3AA3.
Neither has a final XOR.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

SOF = 0xAA
HEADER_LEN = 12
OVERHEAD = 16  # header + CRC32

CMD_NO_REPLY = 0x00
CMD_REPLY_OPTIONAL = 0x01
CMD_REPLY_REQUIRED = 0x02
RESPONSE_BIT = 0x20

# What the camera reports as its device id in the connection exchange.
DEVICE_IDS = {0xFF33: "Osmo Action 4", 0xFF44: "Osmo Action 5 Pro", 0xFF55: "Osmo Action 6", 0xFF66: "Osmo 360"}

# Camera modes (status push byte 0, mode-switch payload).
MODES = {
    0x00: "slow_motion", 0x01: "video", 0x02: "timelapse", 0x05: "photo", 0x0A: "hyperlapse",
    0x1A: "live_streaming", 0x23: "uvc_webcam", 0x28: "supernight", 0x34: "subject_tracking",
}
MODE_CODES = {v: k for k, v in MODES.items()}
CAMERA_STATUS = {0: "screen_off", 1: "live_view", 2: "playback", 3: "recording", 5: "pre_recording"}
TEMPERATURE = {0: "normal", 1: "warm", 2: "too_hot_to_record", 3: "overheating_shutdown"}

# Remote-side constants the published demo sends in its commands.
SENDER_ID_MODE = 0xFF330000
SENDER_ID_RECORD = 0x33FF0000
MODE_RESERVED = bytes.fromhex("01473936")


def _table(poly: int) -> list[int]:
    out = []
    for n in range(256):
        c = n
        for _ in range(8):
            c = (c >> 1) ^ poly if c & 1 else c >> 1
        out.append(c)
    return out


_T16 = _table(0xA001)
_T32 = _table(0xEDB88320)


def crc16(data: bytes, init: int = 0x3AA3) -> int:
    c = init
    for b in data:
        c = (c >> 8) ^ _T16[(c ^ b) & 0xFF]
    return c & 0xFFFF


def crc32(data: bytes, init: int = 0x3AA3) -> int:
    c = init
    for b in data:
        c = (c >> 8) ^ _T32[(c ^ b) & 0xFF]
    return c & 0xFFFFFFFF


@dataclass(frozen=True)
class Frame:
    cmd_type: int
    seq: int
    cmd_set: int
    cmd_id: int
    payload: bytes = b""

    @property
    def is_response(self) -> bool:
        return bool(self.cmd_type & RESPONSE_BIT)

    @property
    def key(self) -> tuple[int, int]:
        return (self.cmd_set, self.cmd_id)

    def encode(self) -> bytes:
        total = OVERHEAD + 2 + len(self.payload)
        if total > 0x3FF:
            raise ValueError(f"frame too long: {total}")
        head = struct.pack("<BHBB3sH", SOF, total, self.cmd_type, 0, b"\x00\x00\x00", self.seq & 0xFFFF)
        head += struct.pack("<H", crc16(head))
        body = head + bytes([self.cmd_set, self.cmd_id]) + self.payload
        return body + struct.pack("<I", crc32(body))

    def describe(self) -> str:
        kind = "rsp" if self.is_response else "cmd"
        return f"rsdk {kind} {self.cmd_set:02x}{self.cmd_id:02x} seq={self.seq:04x} payload={self.payload.hex()}"


def decode(raw: bytes) -> Frame:
    if len(raw) < OVERHEAD + 2 or raw[0] != SOF:
        raise ValueError("not an R SDK frame")
    total = struct.unpack_from("<H", raw, 1)[0] & 0x3FF
    if total != len(raw):
        raise ValueError(f"length mismatch: header {total}, got {len(raw)}")
    if crc16(raw[:10]) != struct.unpack_from("<H", raw, 10)[0]:
        raise ValueError("bad CRC16")
    if crc32(raw[:-4]) != struct.unpack_from("<I", raw, total - 4)[0]:
        raise ValueError("bad CRC32")
    seq = struct.unpack_from("<H", raw, 8)[0]
    return Frame(raw[3], seq, raw[12], raw[13], bytes(raw[14:-4]))


# ---- commands (payloads) ----

def connection_request(sender_id: int, sender_mac: bytes, verify_code: int, verify_mode: int = 0) -> bytes:
    """0x00/0x19. verify_mode 0: the camera asks for a tap only if it does not remember us."""
    mac = bytes(sender_mac)[:16]
    return struct.pack("<IB16sIBBH4s", sender_id, len(mac), mac.ljust(16, b"\x00"), 0, 0, verify_mode,
                       verify_code & 0xFFFF, b"\x00" * 4)


def parse_connection_request(payload: bytes) -> dict | None:
    """The camera's own 0x00/0x19 request: verify_mode 2 carries the verdict (0 allowed, 1 refused)."""
    if len(payload) < 29:
        return None
    device_id, _mac_len, _mac, _fw, _conidx, mode, data = struct.unpack_from("<IB16sIBBH", payload, 0)
    return {"device_id": device_id & 0xFFFF, "model": DEVICE_IDS.get(device_id & 0xFFFF), "verify_mode": mode,
            "verify_data": data}


def connection_response(sender_id: int, camera_number: int = 0) -> bytes:
    return struct.pack("<IB4s", sender_id, 0, bytes([camera_number & 0xFF, 0, 0, 0]))


def mode_switch(mode: int) -> bytes:
    """0x1D/0x04."""
    return struct.pack("<IB4s", SENDER_ID_MODE, mode & 0xFF, MODE_RESERVED)


def record(start: bool) -> bytes:
    """0x1D/0x03: 0 start, 1 stop."""
    return struct.pack("<IB4s", SENDER_ID_RECORD, 0 if start else 1, b"\x00" * 4)


def status_subscribe(push_mode: int = 3, freq: int = 20) -> bytes:
    """0x1D/0x05: 3 = periodic (2 Hz, the only rate) plus a push on every change; 0 = off."""
    return struct.pack("<BB4s", push_mode, freq, b"\x00" * 4)


def power_mode(sleep: bool) -> bytes:
    """0x00/0x1A: 0 normal, 3 sleep."""
    return bytes([3 if sleep else 0])



def parse_status(payload: bytes) -> dict | None:
    """0x1D/0x02 status push (38 bytes on the Action 5 Pro)."""
    if len(payload) < 38:
        return None
    mode = payload[0]
    return {
        "mode": MODES.get(mode, f"0x{mode:02x}"),
        "mode_code": mode,
        "status": CAMERA_STATUS.get(payload[1], str(payload[1])),
        "record_s": struct.unpack_from("<H", payload, 5)[0],
        "sd_free_mb": struct.unpack_from("<I", payload, 15)[0],
        "power_mode": "sleep" if payload[28] == 3 else "normal",
        "temperature": TEMPERATURE.get(payload[30], str(payload[30])),
        "battery": payload[37],
    }


def ret_code(payload: bytes, offset: int = 0) -> int | None:
    return payload[offset] if len(payload) > offset else None


def wake_advertisement(camera_mac: str) -> tuple[int, bytes]:
    """Manufacturer data that wakes a sleeping camera: the bytes 'W' 'K' 'P' then the camera's
    address in reverse byte order. Returned as (company id, data) for advertising APIs that take
    the first two bytes as a company id."""
    mac = bytes(int(x, 16) for x in camera_mac.split(":"))
    if len(mac) != 6:
        raise ValueError("camera address must have 6 bytes")
    raw = b"WKP" + mac[::-1]
    return struct.unpack_from("<H", raw, 0)[0], raw[2:]
