"""The HipiMind bridge against a fake HipiMind server and a fake room-companion, both on loopback.

Needs the optional `websockets` package (pip install '.[hipimind]'); skipped without it.
"""
import asyncio
import io
import json
import logging
import os
import stat
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import websockets  # noqa: F401
    from websockets.asyncio.server import serve
except ImportError:  # pragma: no cover
    websockets = None

from room_companion import hipimind as hm

TRANSCRIPT_SENTINEL = "SENTINEL-TRANSCRIPT-7731"
HARDWARE_SENTINEL = "SENTINEL-CAMERA-MODEL-42"
TOKEN = "hmr_dev_" + "T" * 43


def tiny_jpeg(width=1920, height=1080) -> bytes:
    try:
        from PIL import Image
    except ImportError:
        return b"\xff\xd8" + b"\x00" * 2000 + b"\xff\xd9"
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(buf, "JPEG", quality=60)
    return buf.getvalue()


def base_status():
    return {
        "switches": {"video": False, "audio": True, "ai": True},
        "summary": "视频关；声音开；AI 开",
        "video": {"state": "off", "device": HARDWARE_SENTINEL, "stderr": [TRANSCRIPT_SENTINEL]},
        "audio": {"state": "running", "device": HARDWARE_SENTINEL, "level_db": -30.0},
        "ai": {"client": "LocalVision", "sent": 3},
        "model": {"state": "ready", "pid": 4242, "gpu": {"temp_c": 50}, "paused_hot": False},
        "policy": {"mode": "active", "scene": "coding", "scene_text": "写代码", "note": "在桌前打字",
                   "observed_at": 1792930647.0, "delivered_today": 2},
        "windows": {"ffmpeg_pids": [1, 2], "camera": {"in_use": True}},
        "transcripts": [{"t": 1.0, "text": TRANSCRIPT_SENTINEL}],
        "events": [{"ts": "2026-10-25T20:00:00+0800", "kind": "service_start"}],
    }


class FakeLocal:
    """room-companion's local API: /api/status, /snapshot.jpg, /api/switch, /api/command."""

    def __init__(self):
        self.status = base_status()
        self.posts = []
        self.snapshots = 0
        self.jpeg = tiny_jpeg()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, ctype, data):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/status":
                    return self._send(200, "application/json", json.dumps(fake.status, ensure_ascii=False).encode())
                if self.path == "/snapshot.jpg":
                    fake.snapshots += 1
                    if not fake.status["switches"]["video"]:
                        return self._send(404, "text/plain", b"video off")
                    return self._send(200, "image/jpeg", fake.jpeg)
                self._send(404, "text/plain", b"")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode() or "{}")
                fake.posts.append({"path": self.path, "body": body,
                                   "headers": {k.lower(): v for k, v in self.headers.items()}})
                if self.headers.get("X-Room-AI") != "1":
                    return self._send(403, "text/plain", b"missing X-Room-AI header")
                if self.path == "/api/switch":
                    for k in ("video", "audio", "ai"):
                        if k in body:
                            fake.status["switches"][k] = body[k]
                    fake.status["video"]["state"] = "running" if fake.status["switches"]["video"] else "off"
                    fake.status["events"].append({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": "switch",
                                                  "source": body.get("source"),
                                                  "changes": {k: body[k] for k in body if k != "source"}})
                    return self._send(200, "application/json", b'{"ok": true}')
                if self.path == "/api/command":
                    mode = {"安静模式": "quiet", "平衡模式": "balanced", "主动模式": "active"}.get(body.get("text"))
                    if mode:
                        fake.status["policy"]["mode"] = mode
                    return self._send(200, "application/json", b'{"ok": true}')
                self._send(404, "text/plain", b"")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FakeHipiMind:
    """Records every message a device sends; the test drives what it sends back."""

    def __init__(self, close_with=None):
        self.received = []  # (connection number, raw message)
        self.connections = 0
        self.auth_headers = []
        self.close_with = close_with
        self.socket = None
        self.inbox: asyncio.Queue = asyncio.Queue()

    async def handler(self, ws):
        self.connections += 1
        n = self.connections
        self.auth_headers.append(ws.request.headers.get("Authorization"))
        self.socket = ws
        try:
            hello = await ws.recv()
            self.received.append((n, hello))
            await self.inbox.put(json.loads(hello))
            if self.close_with:
                await ws.close(self.close_with, "test")
                return
            await ws.send(json.dumps({"type": "welcome", "v": 1, "device_id": "dev-1", "name": "Room",
                                      "config": {"reminders": {"level": "balanced", "quiet_hours": None},
                                                 "model": {"source": "local"}},
                                      "limits": {"frame_max_bytes": 300000, "live_max_fps": 5,
                                                 "infer_per_minute": 6}}))
            async for raw in ws:
                self.received.append((n, raw))
                await self.inbox.put(raw if isinstance(raw, bytes) else json.loads(raw))
        except Exception:
            pass

    async def start(self):
        self.server = await serve(self.handler, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}"

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    async def next(self, pred, timeout=5.0):
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise AssertionError("expected message did not arrive")
            msg = await asyncio.wait_for(self.inbox.get(), left)
            if pred(msg):
                return msg

    def all_text(self) -> str:
        return "\n".join(r.decode("latin-1") if isinstance(r, bytes) else r for _, r in self.received)


@unittest.skipIf(websockets is None, "websockets not installed")
class BridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.token_file = os.path.join(self.dir, "token")
        hm.write_secret(self.token_file, TOKEN)
        self.local = FakeLocal()
        self.hub = FakeHipiMind(close_with=getattr(self, "close_with", None))
        await self.hub.start()
        self.bridge = self.make_bridge()
        self.task = asyncio.create_task(self.bridge.run_forever())

    def make_bridge(self, **over):
        cfg = hm.load_config_dict({"server": "http://127.0.0.1", "ws_url": self.hub.url, "token_file": self.token_file,
                                   "local_api": self.local.url, "poll_seconds": 0.1, "platform": "linux",
                                   "live": {"max_fps": 4, "max_width": 640}, **over})
        return hm.Bridge(cfg)

    async def asyncTearDown(self):
        self.bridge.stop()
        try:
            await asyncio.wait_for(self.task, 5)
        except Exception:
            pass
        await self.hub.stop()
        self.local.close()

    async def welcomed(self):
        hello = await self.hub.next(lambda m: isinstance(m, dict) and m.get("type") == "hello")
        for _ in range(50):
            if self.bridge.ready:
                break
            await asyncio.sleep(0.05)
        return hello

    async def test_hello_maps_state_and_never_sends_transcripts_or_hardware_names(self):
        hello = await self.welcomed()
        self.assertEqual(self.hub.auth_headers[0], "Bearer " + TOKEN)
        self.assertEqual(hello["device"]["capabilities"], ["video", "audio", "ai", "live", "reminder_config", "announce"])
        st = hello["state"]
        self.assertEqual(st["switches"], {"video": False, "audio": True, "ai": True})
        self.assertEqual(st["capture"], {"video": "off", "audio": "running"})
        self.assertEqual(st["models"], {"vision": {"source": "engine", "state": "ready"}})
        self.assertEqual(st["reminders"], {"level": "proactive", "today": 2})
        self.assertEqual(st["scene"]["label"], "coding")
        self.assertEqual(st["scene"]["text"], "在桌前打字")
        # the status changes; a state message follows
        self.local.status["audio"]["state"] = "waiting_device"
        moved = await self.hub.next(lambda m: isinstance(m, dict) and m.get("type") == "state"
                                    and m["state"].get("capture", {}).get("audio") == "waiting_device")
        self.assertTrue(moved)
        text = self.hub.all_text()
        self.assertNotIn(TRANSCRIPT_SENTINEL, text, "a transcript (or stderr) left the machine")
        self.assertNotIn(HARDWARE_SENTINEL, text, "a device name left the machine")
        self.assertNotIn("4242", text, "a process id left the machine")

    async def test_set_posts_the_local_switch_with_the_header_and_acks_the_new_state(self):
        await self.welcomed()
        await self.hub.socket.send(json.dumps({"type": "set", "req": "q1", "switches": {"video": True},
                                               "source": "web"}))
        ack = await self.hub.next(lambda m: isinstance(m, dict) and m.get("type") == "ack" and m.get("req") == "q1")
        post = [p for p in self.local.posts if p["path"] == "/api/switch"][-1]
        self.assertEqual(post["headers"].get("x-room-ai"), "1")
        self.assertEqual(post["body"], {"video": True, "source": "HipiMind (web)"})
        self.assertTrue(ack["ok"], ack)
        self.assertTrue(ack["state"]["switches"]["video"])
        self.assertEqual(ack["state"]["capture"]["video"], "running")

    async def test_live_frames_flow_only_while_on_and_no_faster_than_fps(self):
        await self.welcomed()
        self.local.jpeg = tiny_jpeg(320, 180)  # cheap to fetch and scale, so the pace is the bridge's own
        self.local.status["switches"]["video"] = True
        await asyncio.sleep(0.6)
        before = [r for _, r in self.hub.received if isinstance(r, bytes)]
        self.assertEqual(before, [], "frames were sent before live was asked for")
        await self.hub.socket.send(json.dumps({"type": "live", "req": "l1", "on": True, "fps": 3, "max_width": 640}))
        await self.hub.next(lambda m: isinstance(m, dict) and m.get("req") == "l1")
        t0 = time.monotonic()
        await asyncio.sleep(2.0)
        frames = [r for _, r in self.hub.received if isinstance(r, bytes)]
        elapsed = time.monotonic() - t0
        self.assertGreaterEqual(len(frames), 2, "live video produced no frames")
        self.assertLessEqual(len(frames), int(3 * elapsed) + 1, f"{len(frames)} frames in {elapsed:.1f}s at fps 3")
        try:
            from PIL import Image
            self.assertLessEqual(Image.open(io.BytesIO(frames[-1])).width, 640)
        except ImportError:
            pass
        await self.hub.socket.send(json.dumps({"type": "live", "req": "l2", "on": False}))
        await self.hub.next(lambda m: isinstance(m, dict) and m.get("req") == "l2")
        await asyncio.sleep(0.2)
        n = len([r for _, r in self.hub.received if isinstance(r, bytes)])
        await asyncio.sleep(1.0)
        self.assertEqual(len([r for _, r in self.hub.received if isinstance(r, bytes)]), n,
                         "frames kept flowing after live off")

    async def test_reminders_become_events_with_ids_that_survive_a_resend(self):
        await self.welcomed()
        self.local.status["events"].append({"ts": "2026-10-25T21:00:00+0800", "kind": "reminder", "category": "久坐"})
        ev = await self.hub.next(lambda m: isinstance(m, dict) and m.get("type") == "event")
        self.assertEqual(ev["kind"], "reminder")
        self.assertEqual(ev["text"], "久坐提醒")
        self.assertEqual(ev["at"], "2026-10-25T21:00:00+08:00")
        # not acked: a new connection sends the same event again, same id
        await self.hub.socket.close(1012, "restart")
        again = await self.hub.next(lambda m: isinstance(m, dict) and m.get("type") == "event", timeout=8)
        self.assertEqual(again["id"], ev["id"])
        # acked: it is gone from what would be resent
        await self.hub.socket.send(json.dumps({"type": "event_ack", "id": ev["id"], "stored": True}))
        for _ in range(40):
            if ev["id"] not in self.bridge.unacked:
                break
            await asyncio.sleep(0.05)
        self.assertNotIn(ev["id"], self.bridge.unacked)

    async def test_config_changes_the_reminder_level_through_the_local_command(self):
        await self.welcomed()
        await self.hub.socket.send(json.dumps({"type": "config", "req": "c1", "config": {
            "reminders": {"level": "quiet", "quiet_hours": {"start": "22:00", "end": "07:00"}},
            "models": {"vision": {"source": "cloud"}}}}))
        ack = await self.hub.next(lambda m: isinstance(m, dict) and m.get("req") == "c1")
        cmd = [p for p in self.local.posts if p["path"] == "/api/command"][-1]
        self.assertEqual(cmd["body"]["text"], "安静模式")
        self.assertTrue(ack["ok"])
        self.assertEqual(ack["state"]["reminders"]["level"], "quiet")
        # the sidecar has no quiet-hours API and no models layer: both reported as ignored
        self.assertEqual(ack["ignored"], ["reminders.quiet_hours", "models"])

    async def test_the_sidecar_declines_test_model(self):
        await self.welcomed()
        await self.hub.socket.send(json.dumps({"type": "test_model", "req": "t1", "slot": "vision",
                                               "model": {"source": "engine"}}))
        ack = await self.hub.next(lambda m: isinstance(m, dict) and m.get("req") == "t1")
        self.assertFalse(ack["ok"])
        self.assertEqual(ack["error"]["code"], "unsupported")

    async def test_pings_are_answered(self):
        await self.welcomed()
        await self.hub.socket.send(json.dumps({"type": "ping", "t": 12345}))
        pong = await self.hub.next(lambda m: isinstance(m, dict) and m.get("type") == "pong")
        self.assertEqual(pong["t"], 12345)


@unittest.skipIf(websockets is None, "websockets not installed")
class PermanentCloseTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_revoked_token_stops_the_bridge_instead_of_reconnecting(self):
        d = tempfile.mkdtemp()
        hm.write_secret(os.path.join(d, "token"), TOKEN)
        local = FakeLocal()
        hub = FakeHipiMind(close_with=4401)
        await hub.start()
        cfg = hm.load_config_dict({"ws_url": hub.url, "token_file": os.path.join(d, "token"),
                                   "local_api": local.url, "poll_seconds": 0.1})
        bridge = hm.Bridge(cfg)
        try:
            try:
                reason = await asyncio.wait_for(bridge.run_forever(), 6)
            except asyncio.TimeoutError:
                self.fail(f"the bridge kept reconnecting after 4401 ({hub.connections} connections)")
            self.assertIn("4401", reason or "")
            await asyncio.sleep(1.5)
            self.assertEqual(hub.connections, 1, "the bridge reconnected after 4401")
        finally:
            bridge.stop()
            await hub.stop()
            local.close()

    async def test_an_ordinary_drop_is_reconnected(self):
        d = tempfile.mkdtemp()
        hm.write_secret(os.path.join(d, "token"), TOKEN)
        local = FakeLocal()
        hub = FakeHipiMind(close_with=1012)
        await hub.start()
        cfg = hm.load_config_dict({"ws_url": hub.url, "token_file": os.path.join(d, "token"),
                                   "local_api": local.url, "poll_seconds": 0.1})
        bridge = hm.Bridge(cfg)
        task = asyncio.create_task(bridge.run_forever())
        try:
            for _ in range(60):
                if hub.connections >= 2:
                    break
                await asyncio.sleep(0.1)
            self.assertGreaterEqual(hub.connections, 2, "the bridge did not reconnect after 1012")
        finally:
            bridge.stop()
            await asyncio.wait_for(task, 5)
            await hub.stop()
            local.close()


@unittest.skipIf(websockets is None, "websockets not installed")
class InProcessTest(unittest.IsolatedAsyncioTestCase):
    """The connector inside a real App (fake capture and model server), on its own thread and loop."""

    async def asyncSetUp(self):
        from room_companion.app import DEFAULTS, App
        from tests.fakes import FakeNotifier
        from tests.test_room import FakeClient, FakeServer, Pipe
        self.dir = tempfile.mkdtemp()
        hm.write_secret(os.path.join(self.dir, "token"), TOKEN)
        self.hub = FakeHipiMind()
        await self.hub.start()
        self.notifier = FakeNotifier()
        cfg = dict(DEFAULTS, data_dir=self.dir,
                   hipimind={"ws_url": self.hub.url, "token_file": os.path.join(self.dir, "token"),
                             "poll_seconds": 0.1, "platform": "linux"})
        self.app = App(cfg, video=Pipe("running"), audio=Pipe(), notifier=self.notifier,
                       ai_client=FakeClient("coding"), model_server=FakeServer())
        self.app.audio.transcripts = [{"t": time.time(), "text": TRANSCRIPT_SENTINEL}]
        self.conn = hm.start_in_process(self.app, cfg["hipimind"])
        self.hello = await self.hub.next(lambda m: isinstance(m, dict) and m.get("type") == "hello")
        for _ in range(60):
            if self.conn.bridge.ready:
                break
            await asyncio.sleep(0.05)

    async def asyncTearDown(self):
        await asyncio.to_thread(self.conn.stop)
        await self.hub.stop()

    async def ack(self, req):
        return await self.hub.next(lambda m: isinstance(m, dict) and m.get("type") == "ack" and m.get("req") == req,
                                   timeout=10)

    async def test_hello_offers_models_and_reports_all_three_slots(self):
        self.assertEqual(self.hello["device"]["capabilities"],
                         ["video", "audio", "ai", "live", "reminder_config", "model_config", "model_test",
                          "camera_config", "camera_action", "announce"])
        self.assertEqual([d["id"] for d in self.hello["device"]["camera_drivers"]],
                         ["auto", "uvc", "dji-ble-official", "dji-duml"])
        self.assertEqual(self.hello["state"]["camera"]["driver"], "auto")
        self.assertEqual(set(self.hello["state"]["models"]), {"vision", "stt", "tts"})
        self.assertEqual(self.hello["state"]["models"]["vision"]["source"], "engine")
        self.assertEqual(self.hello["state"]["reminders"]["quiet_hours"], {"start": "23:00", "end": "08:00"})
        self.assertNotIn(TRANSCRIPT_SENTINEL, self.hub.all_text())

    async def test_a_slow_camera_action_does_not_hold_up_video_off(self):
        started = threading.Event()

        def slow_action(action):
            started.set()
            time.sleep(3)
            return True, "done"
        self.app.camera_action = slow_action
        await self.hub.socket.send(json.dumps({"type": "camera_action", "req": "c1", "action": "pair"}))
        await asyncio.to_thread(started.wait, 5)
        t0 = time.monotonic()
        await self.hub.socket.send(json.dumps({"type": "set", "req": "s9", "switches": {"video": False}, "source": "web"}))
        ack = await self.ack("s9")
        self.assertTrue(ack["ok"])
        self.assertLess(time.monotonic() - t0, 2.0, "video off waited behind the camera action")
        cam = await self.ack("c1")
        self.assertTrue(cam["ok"])

    async def test_set_reaches_the_app_and_its_own_confirmation_still_goes_out(self):
        await self.hub.socket.send(json.dumps({"type": "set", "req": "s1", "switches": {"ai": True}, "source": "web"}))
        ack = await self.ack("s1")
        self.assertTrue(ack["ok"], ack)
        self.assertTrue(self.app.switches.get("ai"))
        self.assertTrue(ack["state"]["switches"]["ai"])
        for _ in range(100):
            if any("HipiMind (web)" in t for t in self.notifier.messages):
                break
            await asyncio.sleep(0.1)
        self.assertTrue(any("HipiMind (web)" in t for t in self.notifier.messages), self.notifier.messages)

    async def test_models_and_keys_from_the_page_are_applied_and_the_key_stays_on_the_device(self):
        from tests.test_models import FakeModel
        srv = FakeModel(key="sk-room-7")
        try:
            await self.hub.socket.send(json.dumps({"type": "config", "req": "c1", "model_keys": {"vision": "sk-room-7"},
                                                   "config": {"models": {"preset": "custom", "vision": {
                                                       "source": "openai", "base_url": srv.url, "model": "x"}}}}))
            ack = await self.ack("c1")
            self.assertTrue(ack["ok"], ack)
            self.assertEqual(ack["ignored"], [])
            v = ack["state"]["models"]["vision"]
            self.assertEqual((v["source"], v["base_url"], v["has_key"]), ("openai", srv.url, True))
            self.assertEqual(self.app.models.key("vision"), "sk-room-7")
            self.assertNotIn("sk-room-7", self.hub.all_text(), "the key came back to HipiMind")
            # the real vision client uses it
            self.app.switches.set({"ai": True}, "t")
            obs = await asyncio.to_thread(self.app.ai.ask, "frame", {"jpeg": b"\xff\xd8x\xff\xd9"})
            self.assertEqual(obs["scene"], "coding")
            self.assertEqual(srv.requests[-1]["auth"], "Bearer sk-room-7")
        finally:
            srv.close()

    async def test_test_model_runs_a_real_request_and_reports_errors_plainly(self):
        from tests.test_models import FakeModel, closed_port_url
        srv = FakeModel()
        try:
            await self.hub.socket.send(json.dumps({"type": "test_model", "req": "t1", "slot": "vision",
                                                   "model": {"source": "openai", "base_url": srv.url, "model": "x"}}))
            ok = await self.ack("t1")
            self.assertTrue(ok["ok"], ok)
            self.assertEqual(ok["result"]["model"], "served-model")
            self.assertEqual(srv.requests[-1]["path"], "/v1/chat/completions")
            self.assertEqual(self.app.models.slot("vision")["source"], "engine", "a test must not save the setting")
        finally:
            srv.close()
        await self.hub.socket.send(json.dumps({"type": "test_model", "req": "t2", "slot": "tts",
                                               "model": {"source": "openai", "base_url": closed_port_url(), "model": "k"}}))
        bad = await self.ack("t2")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"]["code"], "connect_failed")

    async def test_a_cloud_slot_asks_hipimind_over_the_same_socket(self):
        await self.hub.socket.send(json.dumps({"type": "config", "req": "c2",
                                               "config": {"models": {"vision": {"source": "cloud"}}}}))
        await self.ack("c2")
        self.app.switches.set({"ai": True}, "t")
        call = asyncio.create_task(asyncio.to_thread(self.app.ai.ask, "frame", {"jpeg": b"\xff\xd8x\xff\xd9"}))
        infer = await self.hub.next(lambda m: isinstance(m, dict) and m.get("type") == "infer", timeout=10)
        self.assertEqual(len(infer["images"]), 1)
        await self.hub.socket.send(json.dumps({"type": "infer_result", "req": infer["req"], "ok": True,
                                               "text": json.dumps({"person": True, "scene": "yoga", "hot_oil": False,
                                                                   "on_phone_call": False, "note": ""})}))
        obs = await call
        self.assertEqual(obs["scene"], "yoga")
        # a refusal (quota) is an answer of nothing, not a crash
        call = asyncio.create_task(asyncio.to_thread(self.app.ai.ask, "frame", {"jpeg": b"\xff\xd8x\xff\xd9"}))
        infer = await self.hub.next(lambda m: isinstance(m, dict) and m.get("type") == "infer", timeout=10)
        await self.hub.socket.send(json.dumps({"type": "infer_result", "req": infer["req"], "ok": False,
                                               "error": {"code": "quota_exceeded", "message": "used up"}}))
        self.assertIsNone(await call)

    async def test_quiet_hours_from_the_page_are_kept(self):
        await self.hub.socket.send(json.dumps({"type": "config", "req": "q1", "config": {
            "reminders": {"level": "balanced", "quiet_hours": {"start": "22:00", "end": "07:30"}}}}))
        ack = await self.ack("q1")
        self.assertTrue(ack["ok"], ack)
        self.assertEqual(ack["state"]["reminders"]["quiet_hours"], {"start": "22:00", "end": "07:30"})
        self.assertEqual(self.app.policy.cfg["quiet_hours"], ["22:00", "07:30"])

    async def test_live_frames_come_from_the_app_and_stop_when_video_goes_off(self):
        jpeg = tiny_jpeg()
        self.app.video.latest = lambda: (jpeg, 1)
        self.app.switches.set({"video": True}, "t")
        await self.hub.socket.send(json.dumps({"type": "live", "req": "l1", "on": True, "fps": 4}))
        await self.ack("l1")
        await asyncio.sleep(1.0)
        n = len([r for _, r in self.hub.received if isinstance(r, bytes)])
        self.assertGreaterEqual(n, 1, "no frames")
        self.app.switches.set({"video": False}, "t")
        await asyncio.sleep(0.4)
        n = len([r for _, r in self.hub.received if isinstance(r, bytes)])
        await asyncio.sleep(1.0)
        self.assertEqual(len([r for _, r in self.hub.received if isinstance(r, bytes)]), n,
                         "frames kept coming with the video switch off")


@unittest.skipIf(websockets is None, "websockets not installed")
class TokenWaitTest(unittest.IsolatedAsyncioTestCase):
    async def test_in_the_app_a_missing_or_revoked_token_is_waited_out_until_pair_writes_a_new_one(self):
        d = tempfile.mkdtemp()
        token_file = os.path.join(d, "token")
        local = FakeLocal()
        hub = FakeHipiMind(close_with=4401)
        await hub.start()
        cfg = hm.load_config_dict({"ws_url": hub.url, "token_file": token_file, "local_api": local.url,
                                   "poll_seconds": 0.1, "wait_for_token": True, "token_poll_seconds": 0.2})
        bridge = hm.Bridge(cfg)
        task = asyncio.create_task(bridge.run_forever())
        try:
            await asyncio.sleep(0.6)
            self.assertEqual(hub.connections, 0, "connected without a token")
            self.assertFalse(task.done(), "gave up instead of waiting for a token")
            hm.write_secret(token_file, TOKEN)            # pair
            for _ in range(40):
                if hub.connections:
                    break
                await asyncio.sleep(0.1)
            self.assertEqual(hub.connections, 1)
            await asyncio.sleep(0.8)                       # refused with 4401: the same token is not retried
            self.assertEqual(hub.connections, 1, "the refused token was tried again")
            self.assertFalse(task.done())
            hub.close_with = None
            hm.write_secret(token_file, "hmr_dev_" + "N" * 43)   # pair again
            await hub.next(lambda m: isinstance(m, dict) and m.get("type") == "hello"
                           and hub.connections == 2, timeout=5)
            self.assertEqual(hub.auth_headers[-1], "Bearer hmr_dev_" + "N" * 43)
        finally:
            bridge.stop()
            await asyncio.wait_for(task, 5)
            await hub.stop()
            local.close()


class PairTest(unittest.TestCase):
    def test_pair_saves_the_token_readable_only_by_this_user_and_never_prints_it(self):
        token = "hmr_dev_" + "P" * 43
        seen = {}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                seen["path"], seen["body"] = self.path, json.loads(self.rfile.read(n))
                data = json.dumps({"device_id": "dev-9", "device_token": token,
                                   "ws_url": "wss://example.invalid/ws/room/device"}).encode()
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        d = os.path.join(tempfile.mkdtemp(), "new-dir")
        path = os.path.join(d, "hipimind.token")
        out = io.StringIO()
        try:
            from contextlib import redirect_stdout
            with redirect_stdout(out):
                code = hm.main(["pair", "--server", f"http://127.0.0.1:{srv.server_address[1]}",
                                "--code", "K7QM-2WXH", "--name", "Desk", "--token-file", path])
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(code, 0)
        self.assertEqual(seen["path"], "/api/room/pair")
        self.assertEqual(seen["body"]["code"], "K7QM-2WXH")
        with open(path) as f:
            self.assertEqual(f.read(), token)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(d).st_mode), 0o700)
        self.assertNotIn(token, out.getvalue())
        self.assertIn("dev-9", out.getvalue())

    def test_pair_reports_an_expired_code(self):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                data = b'{"error":"code_expired","message":"This pairing code has expired."}'
                self.send_response(410)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(hm.PairError) as ctx:
                hm.pair(f"http://127.0.0.1:{srv.server_address[1]}", "AAAA-BBBB", "x",
                        os.path.join(tempfile.mkdtemp(), "t"))
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual((ctx.exception.status, ctx.exception.code), (410, "code_expired"))


class MappingTest(unittest.TestCase):
    def test_missing_fields_do_not_break_the_mapping_and_unknown_states_read_as_error(self):
        self.assertEqual(hm.map_state({}), {"switches": {"video": False, "audio": False, "ai": False},
                                            "models": {"vision": {"source": "off", "state": "off"}},
                                            "summary": "Video off; Sound off; AI off (nothing goes to any model)"})
        st = hm.map_state({"switches": {"video": "yes", "ai": True}, "video": {"state": "exploded"}})
        self.assertEqual(st["switches"], {"video": False, "audio": False, "ai": True})
        self.assertEqual(st["capture"], {"video": "error"})

    def test_a_model_paused_for_heat_is_reported_off(self):
        st = hm.map_state({"model": {"state": "ready", "paused_hot": True}})
        self.assertEqual(st["models"], {"vision": {"source": "engine", "state": "off"}})

    def test_the_models_layer_is_mapped_without_keys_or_key_files(self):
        st = hm.map_state({"models": {
            "vision": {"source": "openai", "base_url": "http://127.0.0.1:11434/v1", "name": "qwen2.5vl:3b",
                       "state": "ready", "has_key": False, "api_key_file": "/secret/path", "key": "sk-x"},
            "stt": {"source": "engine", "state": "ready", "name": "SenseVoice-Small"},
            "tts": {"source": "off", "state": "off"}}})
        self.assertEqual(st["models"]["vision"], {"source": "openai", "base_url": "http://127.0.0.1:11434/v1",
                                                   "name": "qwen2.5vl:3b", "state": "ready", "has_key": False})
        self.assertNotIn("sk-x", json.dumps(st))
        self.assertNotIn("/secret/path", json.dumps(st))

    def test_scene_events_are_rate_limited_and_history_is_not_replayed(self):
        clock = [1000.0]
        d = hm.EventDiffer(scene_min_minutes=10, clock=lambda: clock[0])
        history = [{"ts": "2026-10-25T08:00:00+0800", "kind": "reminder", "category": "手机"}]
        self.assertEqual(d.new_events(history, "dev"), [], "history was replayed")
        evs = history + [{"ts": "2026-10-25T09:00:00+0800", "kind": "scene", "scene": "yoga"}]
        self.assertEqual([e["text"] for e in d.new_events(evs, "dev")], ["瑜伽"])
        clock[0] += 60
        evs = evs + [{"ts": "2026-10-25T09:01:00+0800", "kind": "scene", "scene": "sofa_phone"}]
        self.assertEqual(d.new_events(evs, "dev"), [], "a second scene event within 10 minutes")
        clock[0] += 600
        evs = evs + [{"ts": "2026-10-25T09:11:00+0800", "kind": "scene", "scene": "coding"}]
        self.assertEqual([e["text"] for e in d.new_events(evs, "dev")], ["写代码"])

    def test_event_ids_are_deterministic(self):
        e = {"ts": "2026-10-25T09:00:00+0800", "kind": "reminder", "category": "久坐"}
        a, b = hm.EventDiffer(), hm.EventDiffer()
        a.new_events([], "dev"), b.new_events([], "dev")
        self.assertEqual(a.new_events([e], "dev")[0]["id"], b.new_events([e], "dev")[0]["id"])
        c = hm.EventDiffer()
        c.new_events([], "other-device")
        b2 = hm.EventDiffer()
        b2.new_events([], "dev")
        self.assertNotEqual(c.new_events([e], "other-device")[0]["id"], b2.new_events([e], "dev")[0]["id"])


class LoggingTest(unittest.TestCase):
    def test_the_token_never_reaches_the_log(self):
        if websockets is None:
            self.skipTest("websockets not installed")
        d = tempfile.mkdtemp()
        hm.write_secret(os.path.join(d, "token"), TOKEN)
        local = FakeLocal()
        records = []

        class Grab(logging.Handler):
            def emit(self, record):
                records.append(self.format(record))

        h = Grab()
        logging.getLogger("room_companion").addHandler(h)
        logging.getLogger("room_companion").setLevel(logging.DEBUG)

        async def go():
            hub = FakeHipiMind(close_with=4401)
            await hub.start()
            cfg = hm.load_config_dict({"ws_url": hub.url, "token_file": os.path.join(d, "token"),
                                       "local_api": local.url, "poll_seconds": 0.1})
            await asyncio.wait_for(hm.Bridge(cfg).run_forever(), 6)
            await hub.stop()

        try:
            asyncio.run(go())
        finally:
            logging.getLogger("room_companion").removeHandler(h)
            local.close()
        self.assertTrue(records, "nothing was logged at all")
        self.assertNotIn(TOKEN, "\n".join(records))


if __name__ == "__main__":
    unittest.main()
