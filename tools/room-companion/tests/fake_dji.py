"""A fake DJI camera behind the Bluetooth helper's transport interface (no radio).

Behaviour comes from the JSON file named by FAKE_DJI_CONF; the camera writes its mode to
FAKE_DJI_STATE so a test can make the "webcam" appear when the camera enters webcam mode.
Conf keys: found (bool), rsdk_paired, duml_paired, tap (bool: someone taps the prompt),
rsdk_uvc_ret (ret code for mode 0x23 via the official command), duml_uvc (bool: accepts 02/E1 23),
mode (start mode), sleeping (bool), wake_ok (bool).
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "room_companion", "camera"))
import duml  # noqa: E402
import rsdk  # noqa: E402

ADDR = "11:22:33:44:55:66"


def _conf():
    with open(os.environ["FAKE_DJI_CONF"]) as f:
        return json.load(f)


class FakeTransport:
    def __init__(self):
        self.on_data = None
        self.on_disconnect = None
        self.connected = False
        self.c = _conf()
        self.mode = self.c.get("mode", 0x01)
        self.sleeping = self.c.get("sleeping", False)
        self.demux = duml.Demux()
        self.seq = 0x100
        self._save()

    def _save(self):
        path = os.environ.get("FAKE_DJI_STATE")
        if path:
            with open(path, "w") as f:
                json.dump({"mode": self.mode, "sleeping": self.sleeping, "connected": self.connected,
                           "rsdk_paired": self.c.get("rsdk_paired"), "duml_paired": self.c.get("duml_paired")}, f)

    async def scan(self, timeout):
        await asyncio.sleep(0.01)
        if not self.c.get("found", True) or self.sleeping:
            return []
        return [{"addr": ADDR, "name": "OsmoAction5ProFAKE", "model_byte": 0x15, "rssi": -40}]

    async def connect(self, addr, timeout):
        if not self.c.get("found", True) or self.sleeping:
            raise OSError("not found")
        self.connected = True
        self._save()
        return {"mtu": 247}

    async def arm(self):
        pass

    async def disconnect(self):
        self.connected = False
        self._save()

    async def advertise(self, company_id, data, seconds):
        await asyncio.sleep(0.01)
        expect = rsdk.wake_advertisement(ADDR)
        if (company_id, bytes(data)) == expect and self.c.get("wake_ok", True):
            self.sleeping = False
            self._save()
        return {"publisher_status": 2}

    def _push(self, frame_bytes: bytes, delay=0.0):
        """Deliver in two notifications (exercises reassembly), never interleaved with another frame."""
        loop = asyncio.get_running_loop()
        half = len(frame_bytes) // 2

        def send():
            self.on_data(frame_bytes[:half])
            self.on_data(frame_bytes[half:])
        loop.call_later(delay, send)

    async def write(self, data: bytes):
        for kind, raw in self.demux.feed(data):
            if kind == "rsdk":
                self._rsdk(rsdk.decode(raw))
            else:
                self._duml(duml.decode(raw))

    def _rsdk_reply(self, f, payload):
        self._push(rsdk.Frame(rsdk.RESPONSE_BIT, f.seq, f.cmd_set, f.cmd_id, payload).encode())

    def _rsdk(self, f):
        if f.is_response:
            if f.key == (0x00, 0x19):
                self.c["rsdk_paired"] = True
                self._save()
            return
        if f.key == (0x00, 0x19):
            self._rsdk_reply(f, b"\x44\xff\x00\x00" + b"\x00" + b"\x00" * 4)
            if self.c.get("rsdk_paired") or self.c.get("tap"):
                self.seq += 1
                verdict = rsdk.connection_request(0xFF44, bytes(6), 0, 2)
                delay = 0.0 if self.c.get("rsdk_paired") else 3.2  # a person taps after a few seconds
                self._push(rsdk.Frame(rsdk.CMD_REPLY_REQUIRED, self.seq, 0x00, 0x19, verdict).encode(), delay)
        elif f.key == (0x1D, 0x04):
            mode = f.payload[4]
            ret = self.c.get("rsdk_uvc_ret", 0) if mode == 0x23 else 0
            if ret == 0:
                self.mode = mode
                self._save()
            self._rsdk_reply(f, bytes([ret]) + b"\x00" * 4)
        elif f.key == (0x1D, 0x05):
            st = bytearray(38)
            st[0] = self.mode
            st[1] = 1
            st[28] = 3 if self.sleeping else 0
            st[37] = 87
            self.seq += 1
            self._push(rsdk.Frame(rsdk.CMD_NO_REPLY, self.seq, 0x1D, 0x02, bytes(st)).encode())
        elif f.key == (0x00, 0x1A):
            self.sleeping = f.payload[0] == 3
            self._save()
            self._rsdk_reply(f, b"\x00")

    def _duml(self, f):
        if f.is_response:
            return
        reply = None
        if f.key == (0x07, 0x45):
            if self.c.get("duml_paired"):
                reply = b"\x00\x01"
            else:
                reply = b"\x00\x02"
                if self.c.get("tap"):
                    def approved():
                        self.c["duml_paired"] = True
                        self._save()
                        self.seq += 1
                        req = duml.Frame(duml.ADDR_WIFI, duml.ADDR_APP, self.seq, duml.FLAG_REQUEST, 0x07, 0x46, b"\x01")
                        self.on_data(req.encode())
                    asyncio.get_running_loop().call_later(0.3, approved)
        elif f.key == (0x02, 0xE1) and self.c.get("duml_late_01"):
            # the camera module answers "00" too late (after the app gave up on it) and changes nothing;
            # the other module refuses, a little slowly
            if f.receiver == duml.ADDR_CAMERA:
                self._push(f.reply(b"\x00").encode(), delay=3.5)
            else:
                self._push(f.reply(b"\xe0").encode(), delay=1.0)
        elif f.key == (0x02, 0xE1):
            if f.payload[:1] == b"\x23" and not self.c.get("duml_uvc", True):
                reply = b"\xe0"
            else:
                self.mode = f.payload[0]
                self._save()
                reply = b"\x00"
        elif f.key == (0x00, 0x2B):
            reply = b"\x00"
        if reply is not None:
            self._push(f.reply(reply).encode())
