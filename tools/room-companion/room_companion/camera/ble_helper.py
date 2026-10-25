"""Bluetooth helper for DJI cameras: one process, JSON lines on stdin/stdout.

It runs wherever the Bluetooth adapter is: on Linux next to the app, or, when the app runs in WSL,
with Windows Python (WSL has no Bluetooth), started from WSL like the Windows ffmpeg. It needs
`bleak`. It keeps no state of its own; the app passes identifiers in and stores what comes back.

Requests: {"id": 1, "cmd": "...", ...}  ->  {"id": 1, "ok": true, ...} or {"id": 1, "ok": false, "error": "..."}
Events (unasked): {"ev": "need_tap" | "status" | "battery" | "disconnected" | "log", ...}

Commands: check, scan, connect, disconnect, rsdk_connect, rsdk, rsdk_subscribe, duml_pair, duml,
keepalive, wake_adv, quit. See the handlers below.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import threading
import time

try:  # inside the package
    from . import duml, rsdk
except ImportError:  # copied next to this file and run as a script (Windows side)
    import duml  # type: ignore
    import rsdk  # type: ignore

DJI_COMPANY_IDS = (0x08AA, 0xF7AA, 0xE5C0)
CHAR_NOTIFY = "0000fff4-0000-1000-8000-00805f9b34fb"
CHAR_WRITE = "0000fff5-0000-1000-8000-00805f9b34fb"
MODEL_NAMES = {0x12: "Osmo Action 3", 0x14: "Osmo Action 4", 0x15: "Osmo Action 5 Pro", 0x17: "Osmo 360",
               0x18: "Osmo Action 6", 0x20: "Osmo Pocket 3"}
WRITE_GAP_S = 0.05  # back-to-back writes without response get dropped


class Out:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.lock = threading.Lock()

    def send(self, obj: dict):
        # ASCII only: Windows Python writes piped stdout in the system code page, which cannot hold
        # every character (a localized error message would kill the helper)
        line = json.dumps(obj, ensure_ascii=True)
        with self.lock:
            self.stream.write(line + "\n")
            self.stream.flush()


class BleakTransport:
    """The real radio. Imported lazily so `check` can report a missing bleak cleanly."""

    def __init__(self):
        import bleak  # noqa: F401
        self.client = None
        self.on_data = None
        self.on_disconnect = None

    async def scan(self, timeout: float):
        from bleak import BleakScanner
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        out = []
        for addr, (dev, adv) in found.items():
            mfr = adv.manufacturer_data or {}
            name = adv.local_name or dev.name or ""
            cid = next((c for c in DJI_COMPANY_IDS if c in mfr), None)
            if cid is None and not name.lower().startswith("osmo"):
                continue
            model = mfr[cid][0] if cid is not None and mfr[cid] else None
            out.append({"addr": addr, "name": name, "model_byte": model, "rssi": adv.rssi})
        return sorted(out, key=lambda d: -(d["rssi"] or -999))

    async def connect(self, addr: str, timeout: float):
        from bleak import BleakClient
        self.client = BleakClient(addr, timeout=timeout,
                                  disconnected_callback=lambda c: self.on_disconnect and self.on_disconnect())
        await self.client.connect()
        await self.client.start_notify(CHAR_NOTIFY, lambda _c, data: self.on_data(bytes(data)))
        try:
            await self.client.start_notify(CHAR_WRITE, lambda _c, data: self.on_data(bytes(data)))
        except Exception:  # not every body notifies on fff5
            pass
        return {"mtu": getattr(self.client, "mtu_size", None)}

    async def arm(self):
        """Osmosis/dji-vcam write 01 00 to fff4's value before DUML pairing; harmless otherwise."""
        try:
            await self.client.write_gatt_char(CHAR_NOTIFY, b"\x01\x00", response=True)
        except Exception:  # some stacks refuse a write on a notify-only characteristic; pairing still works
            pass

    async def write(self, data: bytes):
        await self.client.write_gatt_char(CHAR_WRITE, data, response=False)

    async def disconnect(self):
        if self.client is not None:
            try:
                await self.client.disconnect()
            finally:
                self.client = None

    @property
    def connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    async def advertise(self, company_id: int, data: bytes, seconds: float):
        """Wake-up broadcast. Windows only (WinRT publisher); BlueZ needs a different API."""
        if sys.platform != "win32":
            raise RuntimeError("wake broadcast is only implemented on Windows")
        from winrt.windows.devices.bluetooth.advertisement import (BluetoothLEAdvertisementPublisher,
                                                                   BluetoothLEManufacturerData)
        from winrt.windows.storage.streams import DataWriter
        w = DataWriter()
        w.write_bytes(bytes(data))
        md = BluetoothLEManufacturerData()
        md.company_id = company_id
        md.data = w.detach_buffer()
        pub = BluetoothLEAdvertisementPublisher()
        pub.advertisement.manufacturer_data.append(md)
        pub.start()
        try:
            await asyncio.sleep(seconds)
            return {"publisher_status": int(pub.status)}
        finally:
            pub.stop()


class Helper:
    def __init__(self, transport, out: Out):
        self.t = transport
        self.out = out
        self.demux = duml.Demux()
        self.waiters: list[tuple[str, object, asyncio.Future]] = []
        self.loop: asyncio.AbstractEventLoop | None = None
        self.seq = 0x8000 + secrets.randbelow(0x1000)
        self.answer_requests = True
        self.duml_approved = asyncio.Event()
        self.rsdk_verdict: asyncio.Future | None = None
        self.keepalive_task = None
        self.log_frames = bool(os.environ.get("DJI_BLE_LOG"))
        self.t.on_data = self._on_data
        self.t.on_disconnect = self._on_disconnect

    def _next_seq(self) -> int:
        self.seq = (self.seq + 1) & 0xFFFF
        return self.seq

    # ---- inbound ----
    def _on_disconnect(self):
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.out.send, {"ev": "disconnected"})

    def _on_data(self, data: bytes):
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._feed, data)

    def _feed(self, data: bytes):
        for kind, raw in self.demux.feed(data):
            try:
                f = duml.decode(raw) if kind == "duml" else rsdk.decode(raw)
            except ValueError:
                continue
            if self.log_frames:
                self.out.send({"ev": "log", "rx": f.describe()})
            if kind == "duml":
                self._on_duml(f)
            else:
                self._on_rsdk(f)

    def _resolve(self, kind: str, frame) -> bool:
        for w in list(self.waiters):
            k, m, fut = w
            if k == kind and m(frame) and not fut.done():
                fut.set_result(frame)
                self.waiters.remove(w)
                return True
        return False

    def _on_duml(self, f: duml.Frame):
        if f.is_request:
            if f.key == (0x07, 0x46):
                self.duml_approved.set()
            if self.answer_requests or f.key == (0x07, 0x46):
                payload = duml.APP_DEVICE_INFO if f.key == (0x00, 0x81) else f.payload
                asyncio.ensure_future(self._write(f.reply(payload).encode()))
            return
        if f.key == (0x0D, 0x02) and f.sender == duml.ADDR_BATTERY:
            self.out.send({"ev": "battery", "percent": duml.parse_battery(f.payload)})
        if not self._resolve("duml", f) and f.is_response:
            self.out.send({"ev": "log", "stray": f.describe()})

    def _on_rsdk(self, f: rsdk.Frame):
        if f.key == (0x1D, 0x02) and not f.is_response:
            st = rsdk.parse_status(f.payload)
            if st:
                self.out.send({"ev": "status", **st})
            return
        if f.key == (0x00, 0x19) and not f.is_response:
            req = rsdk.parse_connection_request(f.payload)
            if req and req["verify_mode"] == 2 and self.rsdk_verdict is not None and not self.rsdk_verdict.done():
                self.rsdk_verdict.set_result((f, req))
            return
        self._resolve("rsdk", f)

    # ---- outbound ----
    async def _write(self, data: bytes):
        await self.t.write(data)
        await asyncio.sleep(WRITE_GAP_S)

    async def _wait(self, kind: str, match, timeout: float):
        fut = self.loop.create_future()
        self.waiters.append((kind, match, fut))
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self.waiters = [w for w in self.waiters if w[2] is not fut]
            return None

    async def rsdk_request(self, cmd_set, cmd_id, payload, cmd_type=rsdk.CMD_REPLY_REQUIRED, timeout=2.0, seq=None):
        seq = self._next_seq() if seq is None else seq
        frame = rsdk.Frame(cmd_type, seq, cmd_set, cmd_id, payload)
        waiting = asyncio.ensure_future(self._wait("rsdk", lambda x: x.key == frame.key and x.seq == seq and x.is_response, timeout))
        await asyncio.sleep(0)
        await self._write(frame.encode())
        if cmd_type == rsdk.CMD_NO_REPLY:
            waiting.cancel()
            return None
        return await waiting

    async def duml_request(self, receiver, cmd_set, cmd_id, payload=b"", timeout=2.0, seq=None, flags=duml.FLAG_REQUEST):
        seq = self._next_seq() if seq is None else seq
        frame = duml.Frame(duml.ADDR_APP, receiver, seq, flags, cmd_set, cmd_id, payload)
        # the camera echoes the sequence: a late answer to an earlier request (same command, sent to
        # another module) must not be taken as this one's
        waiting = asyncio.ensure_future(self._wait(
            "duml", lambda x: x.key == frame.key and x.is_response and x.seq == seq, timeout))
        await asyncio.sleep(0)
        await self._write(frame.encode())
        return await waiting

    # ---- commands ----
    async def cmd_check(self, req):
        return {"python": sys.version.split()[0], "platform": sys.platform}

    async def cmd_scan(self, req):
        return {"cameras": await self.t.scan(float(req.get("seconds", 8)))}

    async def cmd_connect(self, req):
        addr = req.get("addr")
        if not addr:
            cams = await self.t.scan(float(req.get("scan_seconds", 8)))
            want = (req.get("name") or "").lower()
            cams = [c for c in cams if not want or want in c["name"].lower()]
            if not cams:
                return {"ok": False, "error": "not_found"}
            addr = cams[0]["addr"]
        self.demux = duml.Demux()
        info = await self.t.connect(addr, float(req.get("connect_seconds", 20)))
        return {"addr": addr, **info}

    async def cmd_disconnect(self, req):
        await self._stop_keepalive()
        await self.t.disconnect()
        return {}

    async def cmd_rsdk_connect(self, req):
        """Official handshake: our 0x00/0x19, the camera's reply, then the camera's own 0x00/0x19 with
        its verdict (0 allowed) which we answer. With no remembered pairing the camera shows a prompt
        and the verdict waits for the tap."""
        sender_id = int(req.get("sender_id", 0x12345678))
        mac = bytes.fromhex(req["sender_mac"])
        code = int(req.get("verify_code", secrets.randbelow(10000)))
        self.rsdk_verdict = self.loop.create_future()
        reply = await self.rsdk_request(0x00, 0x19, rsdk.connection_request(sender_id, mac, code, int(req.get("verify_mode", 0))),
                                        timeout=float(req.get("reply_s", 2.0)))
        if reply is not None and rsdk.ret_code(reply.payload, 4) not in (0, None):
            return {"ok": False, "error": "refused", "ret": rsdk.ret_code(reply.payload, 4)}
        wait_s = float(req.get("wait", 5))
        try:
            frame, verdict = await asyncio.wait_for(asyncio.shield(self.rsdk_verdict), min(3.0, wait_s))
        except asyncio.TimeoutError:
            self.out.send({"ev": "need_tap", "proto": "rsdk", "code": f"{code:04d}"})
            try:
                frame, verdict = await asyncio.wait_for(self.rsdk_verdict, max(0.0, wait_s - 3.0))
            except asyncio.TimeoutError:
                return {"ok": False, "error": "no_tap", "replied": reply is not None}
        if verdict["verify_data"] != 0:
            return {"ok": False, "error": "rejected", "model": verdict["model"]}
        await self._write(rsdk.Frame(rsdk.RESPONSE_BIT, frame.seq, 0x00, 0x19,
                                     rsdk.connection_response(sender_id)).encode())
        return {"approved": True, "device_id": verdict["device_id"], "model": verdict["model"]}

    async def cmd_rsdk(self, req):
        reply = await self.rsdk_request(int(req["set"]), int(req["cid"]), bytes.fromhex(req.get("payload", "")),
                                        int(req.get("cmd_type", rsdk.CMD_REPLY_REQUIRED)), float(req.get("reply_s", 2.0)))
        return {"reply": reply.payload.hex() if reply is not None else None}

    async def cmd_rsdk_subscribe(self, req):
        """Status pushes arrive as {"ev": "status"} events; the push itself is the reply."""
        await self._write(rsdk.Frame(rsdk.CMD_NO_REPLY, self._next_seq(), 0x1D, 0x05,
                                     rsdk.status_subscribe(int(req.get("mode", 3)))).encode())
        return {}

    async def cmd_duml_pair(self, req):
        self.answer_requests = bool(req.get("answer_requests", True))
        await self.t.arm()
        await asyncio.sleep(0.2)
        await self.duml_request(duml.ADDR_SESSION, 0x00, 0x2B, b"\x04\x00", timeout=0.3)
        self.duml_approved = asyncio.Event()
        pairing = duml.pairing(req["identifier"], req.get("token", "room"))
        seq = self._next_seq()
        reply = None
        for _ in range(3):
            reply = await self.duml_request(duml.ADDR_WIFI, 0x07, 0x45, pairing, timeout=2.5, seq=seq)
            if reply is not None:
                break
        if reply is None:
            return {"ok": False, "error": "no_reply"}
        status = reply.payload[1] if len(reply.payload) > 1 else None
        if status == 0x01:
            return {"approved": True, "already": True}
        if status != 0x02:
            return {"ok": False, "error": "unexpected", "reply": reply.payload.hex()}
        self.out.send({"ev": "need_tap", "proto": "duml", "code": req.get("token", "room").upper()})
        try:
            await asyncio.wait_for(self.duml_approved.wait(), float(req.get("wait", 5)))
        except asyncio.TimeoutError:
            return {"ok": False, "error": "no_tap"}
        return {"approved": True, "already": False}

    async def cmd_duml(self, req):
        reply = await self.duml_request(int(req["to"]), int(req["set"]), int(req["cid"]),
                                        bytes.fromhex(req.get("payload", "")), float(req.get("reply_s", 2.0)))
        return {"reply": reply.payload.hex() if reply is not None else None}

    async def _keepalive(self, interval):
        while self.t.connected:
            await self._write(duml.Frame(duml.ADDR_APP, duml.ADDR_SESSION, self._next_seq(), duml.FLAG_REQUEST,
                                         0x00, 0x2B, b"\x04\x00").encode())
            await asyncio.sleep(interval)

    async def _stop_keepalive(self):
        if self.keepalive_task is not None:
            self.keepalive_task.cancel()
            self.keepalive_task = None

    async def cmd_keepalive(self, req):
        await self._stop_keepalive()
        if req.get("on", True):
            self.keepalive_task = asyncio.ensure_future(self._keepalive(float(req.get("interval", 2.5))))
        return {}

    async def cmd_wake_adv(self, req):
        cid, data = rsdk.wake_advertisement(req["addr"])
        return await self.t.advertise(cid, data, float(req.get("seconds", 2.0)))

    async def handle(self, req: dict):
        rid = req.get("id")
        fn = getattr(self, "cmd_" + str(req.get("cmd")), None)
        if fn is None:
            self.out.send({"id": rid, "ok": False, "error": "unknown_cmd"})
            return
        try:
            res = await fn(req) or {}
            res.setdefault("ok", True)
        except Exception as e:  # report, keep serving
            res = {"ok": False, "error": type(e).__name__, "detail": str(e)[:200]}
        self.out.send({"id": rid, **res})

    async def run(self, lines):
        self.loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()

        def reader():
            for line in lines:
                self.loop.call_soon_threadsafe(q.put_nowait, line)
            self.loop.call_soon_threadsafe(q.put_nowait, None)

        threading.Thread(target=reader, daemon=True).start()
        self.out.send({"ev": "ready", "platform": sys.platform})
        while True:
            line = await q.get()
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except ValueError:
                self.out.send({"ok": False, "error": "bad_json"})
                continue
            if req.get("cmd") == "quit":
                break
            await self.handle(req)  # one at a time: a camera handles one request in flight
        await self._stop_keepalive()
        await self.t.disconnect()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out = Out()
    if argv[:1] == ["--fake"]:
        import importlib.util
        spec = importlib.util.spec_from_file_location("fake_dji", argv[1])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        transport = mod.FakeTransport()
    else:
        try:
            transport = BleakTransport()
        except ImportError:
            out.send({"ev": "ready", "error": "bleak_missing"})
            return 2
    asyncio.run(Helper(transport, out).run(sys.stdin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
