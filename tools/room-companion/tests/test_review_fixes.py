"""Regression tests for the review of the HipiMind connector and the models layer.

Each test pins one finding: the receive loop never blocks, cloud payloads fit the server's limits,
the page cannot make the device read local files or follow a key to another server, nothing that
names hardware or a local address leaves the machine, and malformed commands are answered, not fatal.
"""
import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

try:
    import websockets  # noqa: F401
except ImportError:  # pragma: no cover
    websockets = None

from room_companion import hipimind as hm
from room_companion import models as m
from room_companion.app import DEFAULTS, App
from tests.fakes import FakeNotifier
from tests.test_hipimind import TOKEN, FakeHipiMind, FakeLocal
from tests.test_models import FakeModel
from tests.test_room import FakeClient, FakeServer, Pipe

CLOUD_LIMIT = 1_700_000
TEXT_LIMIT = 65_536


def make_app(**cfg_over):
    cfg = dict(DEFAULTS, data_dir=tempfile.mkdtemp(), **cfg_over)
    return App(cfg, video=Pipe("running"), audio=Pipe(), notifier=FakeNotifier(), ai_client=FakeClient("coding"),
               model_server=FakeServer())


def noise_jpeg(w=1280, h=720) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.effect_noise((w, h), 40).convert("RGB").save(buf, "JPEG", quality=75)
    return buf.getvalue()


class LimitHub(FakeHipiMind):
    """Like the real server: a cloud request over 1.7 M characters, or any other text message over 64 KB,
    closes the socket with 4413."""

    async def handler(self, ws):
        self.connections += 1
        n = self.connections
        self.socket = ws
        try:
            hello = await ws.recv()
            self.received.append((n, hello))
            await self.inbox.put(json.loads(hello))
            await ws.send(json.dumps({"type": "welcome", "v": 1, "device_id": "dev-1", "name": "Room", "config": {},
                                      "limits": {"frame_max_bytes": 150000, "live_max_fps": 3, "infer_per_minute": 6,
                                                 "message_max_bytes": TEXT_LIMIT,
                                                 "cloud_message_max_bytes": CLOUD_LIMIT}}))
            async for raw in ws:
                if isinstance(raw, str):
                    kind = (json.loads(raw) or {}).get("type") if raw.startswith("{") else None
                    cap = CLOUD_LIMIT if kind in ("infer", "transcribe", "speak") else TEXT_LIMIT
                    if len(raw) > cap:
                        self.received.append((n, "TOO-LARGE %s %d" % (kind, len(raw))))
                        await ws.close(4413, "message too large")
                        return
                self.received.append((n, raw))
                await self.inbox.put(raw if isinstance(raw, bytes) else json.loads(raw))
        except Exception:
            pass


@unittest.skipIf(websockets is None, "websockets not installed")
class InProc(unittest.IsolatedAsyncioTestCase):
    hub_cls = FakeHipiMind

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        hm.write_secret(os.path.join(self.dir, "token"), TOKEN)
        self.hub = self.hub_cls()
        await self.hub.start()
        cfg = dict(DEFAULTS, data_dir=self.dir,
                   hipimind={"ws_url": self.hub.url, "token_file": os.path.join(self.dir, "token"),
                             "poll_seconds": 0.1, "platform": "linux"})
        self.app = App(cfg, video=Pipe("running"), audio=Pipe(), notifier=FakeNotifier(),
                       ai_client=FakeClient("coding"), model_server=FakeServer())
        self.conn = hm.start_in_process(self.app, cfg["hipimind"])
        await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "hello")
        for _ in range(60):
            if self.conn.bridge.ready:
                break
            await asyncio.sleep(0.05)

    async def asyncTearDown(self):
        await asyncio.to_thread(self.conn.stop, 1)
        await self.hub.stop()


class ReceiveLoopNeverBlocks(InProc):
    """P1-1: Test connection on a cloud slot waits for an answer only the receive loop can deliver."""

    async def test_cloud_test_connection_completes_and_pings_are_answered_meanwhile(self):
        await self.hub.socket.send(json.dumps({"type": "test_model", "req": "t1", "slot": "vision",
                                               "model": {"source": "cloud"}}))
        infer = await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "infer", timeout=10)
        t0 = time.monotonic()
        await self.hub.socket.send(json.dumps({"type": "infer_result", "req": infer["req"], "ok": True, "text": "OK"}))
        await self.hub.socket.send(json.dumps({"type": "ping", "t": 777}))

        def seen():
            msgs = [json.loads(r) for _, r in self.hub.received if isinstance(r, str)]
            pong = next((x for x in msgs if x.get("type") == "pong" and x.get("t") == 777), None)
            ack = next((x for x in msgs if x.get("type") == "ack" and x.get("req") == "t1"), None)
            return pong, ack

        pong = ack = None
        while time.monotonic() - t0 < 5 and not (pong and ack):
            await asyncio.sleep(0.05)
            pong, ack = seen()
        self.assertIsNotNone(pong, "the ping was not answered while Test connection was running")
        self.assertIsNotNone(ack, "Test connection did not answer within 5 s of the cloud's reply")
        self.assertTrue(ack["ok"], ack)


class CloudPayloadsFit(InProc):
    """P1-2: cloud requests stay under the server's limits; images are scaled, audio is cut at 30 s."""

    hub_cls = LimitHub

    async def test_a_full_size_frame_goes_to_the_cloud_scaled_and_within_the_limit(self):
        await self.hub.socket.send(json.dumps({"type": "config", "req": "c1",
                                               "config": {"models": {"vision": {"source": "cloud"}}}}))
        await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "ack" and x.get("req") == "c1", timeout=10)
        self.app.switches.set({"ai": True}, "t")
        asked = asyncio.create_task(asyncio.to_thread(self.app.ai.ask, "frame", {"jpeg": noise_jpeg()}))
        infer = await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "infer", timeout=10)
        await self.hub.socket.send(json.dumps({"type": "infer_result", "req": infer["req"], "ok": True,
                                               "text": '{"person": true, "scene": "coding", "hot_oil": false,'
                                                       ' "on_phone_call": false, "note": "x"}'}))
        await asked
        big = [r for _, r in self.hub.received if isinstance(r, str) and r.startswith("TOO-LARGE")]
        self.assertEqual(big, [], "a cloud request was closed with 4413")
        self.assertEqual(self.hub.connections, 1)
        from PIL import Image
        img = base64.b64decode(infer["images"][0])
        self.assertLessEqual(len(img), 300_000)
        with Image.open(io.BytesIO(img)) as im:
            self.assertLessEqual(max(im.size), 768)


class CloudSizesUnit(unittest.TestCase):
    def test_cloud_transcription_sends_at_most_30_seconds(self):
        sent = {}

        def cloud(kind, **payload):
            sent.update(payload)
            return {"ok": True, "text": "x"}

        go = m.cloud_transcriber(cloud)
        go(m.pcm16_wav(b"\x01\x00" * (16000 * 45)))
        import wave
        with wave.open(io.BytesIO(base64.b64decode(sent["audio"]))) as w:
            self.assertLessEqual(w.getnframes() / w.getframerate(), 30.0)

    def test_a_cloud_request_over_the_limit_is_refused_locally(self):
        bridge = hm.Bridge(hm.load_config_dict({"ws_url": "ws://127.0.0.1:9", "token_file": "/nonexistent"}),
                           device=object())

        class WS:
            def __init__(self):
                self.sent = []

            async def send(self, raw):
                self.sent.append(raw)

        bridge.ws, bridge.ready = WS(), True
        bridge.limits = {"cloud_message_max_bytes": 1000}
        res = asyncio.run(bridge.cloud("speak", {"text": "x" * 5000}, timeout=1))
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["code"], "bad_request")
        self.assertEqual(bridge.ws.sent, [])


class OnlyHttpModelServers(unittest.TestCase):
    """P1-3: the page cannot point a slot at a local file, and an endless answer cannot exhaust memory."""

    def test_a_file_url_is_refused_and_nothing_is_read(self):
        d = tempfile.mkdtemp()
        secret = os.path.join(d, "id_secret")
        with open(secret, "wb") as f:
            f.write(b"PRIVATE" * 1234)
        app = make_app()
        for url in ("file://" + secret + "#", "file://" + secret, "ftp://example.com/v1",
                    "http://user:s3cret@example.com/v1", "http://example.com/v1#frag", "http:///v1"):
            res = app.test_model("tts", {"source": "openai", "base_url": url, "model": "x"})
            self.assertFalse(res["ok"], url)
            self.assertNotIn(str(len(b"PRIVATE" * 1234)), json.dumps(res), url)
            self.assertNotIn("s3cret", json.dumps(res), url)
        self.assertIsNone(m.normalize_slot({"source": "openai", "base_url": "file:///etc/passwd"}).get("base_url"))

    def test_an_endless_answer_is_cut_off(self):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.end_headers()
                chunk = b"\x00" * 65536
                try:
                    for _ in range(400):  # 26 MB, more than any speech answer may be
                        self.wfile.write(chunk)
                except OSError:
                    pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
            with self.assertRaises(m.ModelCallError) as e:
                m.speech_wav(url, "x", None, "hello", None, 10)
            self.assertEqual(e.exception.code, "bad_response")
            self.assertIn("too large", e.exception.message)
        finally:
            srv.shutdown()
            srv.server_close()


class KeyStaysWithItsServer(unittest.TestCase):
    """P1-4: a saved key is not sent to a server it was not typed for."""

    def test_moving_the_slot_to_another_server_does_not_carry_the_saved_key(self):
        a, b = FakeModel(key="sk-saved"), FakeModel()
        try:
            app = make_app()
            app.apply_models({"vision": {"source": "openai", "base_url": a.url, "model": "x"}}, {"vision": "sk-saved"})
            app.apply_models({"vision": {"source": "openai", "base_url": b.url, "model": "x"}})
            app.switches.set({"ai": True}, "t")
            app.ai.ask("frame", {"jpeg": b"\xff\xd8x\xff\xd9"})
            self.assertTrue(b.requests)
            self.assertNotIn("Bearer sk-saved", [r["auth"] for r in b.requests])
            self.assertFalse(app.models_state()["vision"]["has_key"])
            # and back on the server it was typed for, the key is used again
            app.apply_models({"vision": {"source": "openai", "base_url": a.url, "model": "x"}})
            self.assertTrue(app.models_state()["vision"]["has_key"])
        finally:
            a.close()
            b.close()


class SummaryNamesNoHardware(unittest.TestCase):
    """P1-5: the summary HipiMind stores and shows is built from facts, not from the local status text."""

    def test_no_device_names_or_error_output_in_what_is_sent(self):
        app = make_app()
        sentinel = "SENTINEL-HW-99"

        class Sp:
            error, tts = None, None
            output = {"name": sentinel + " (Bluetooth)", "volume": 40, "muted": False}

            def say(self, text, hear=False):
                pass

            def echo(self):
                return False

            def status(self):
                return {"output": self.output}

        app.speaker = Sp()
        app.switches.set({"video": True, "audio": True}, "t")
        app.video.state, app.video.detail = "error", sentinel + " ffmpeg: Could not run graph"
        app.audio.state, app.audio.detail = "error", sentinel + " arecord: device busy"
        st = hm.map_state(hm.AppDevice(app).status())
        text = json.dumps(st, ensure_ascii=False)
        self.assertNotIn(sentinel, text)
        self.assertTrue(st.get("summary"))
        # the sidecar path: whatever summary the local API carries is not forwarded either
        side = hm.map_state({"switches": {"video": True}, "summary": "出声：" + sentinel,
                             "video": {"state": "running"}})
        self.assertNotIn(sentinel, json.dumps(side, ensure_ascii=False))


class RemoteSpeechWaitsForAI(unittest.TestCase):
    """P2-1: with AI off, no text goes to a remote speech model."""

    def test_nothing_reaches_a_remote_tts_while_ai_is_off(self):
        srv = FakeModel()
        try:
            d = tempfile.mkdtemp()
            app = make_app(tts={"check_output": False, "win_dir_wsl": d, "win_dir": "C:\\x", "model_dir": d},
                           models={"tts": {"source": "openai", "base_url": srv.url, "model": "kokoro"}})
            app.speaker.play = lambda path, secs: None
            self.assertFalse(app.switches.get("ai"))
            app.on_transcript("房间助手平衡模式")
            app._deliver("起来走走", "久坐", True)
            time.sleep(1.0)
            self.assertEqual(srv.requests, [])
        finally:
            srv.close()


class NoLocalAddressesLeave(unittest.TestCase):
    def test_a_switch_event_carries_a_fixed_source_label(self):  # P2-2
        d = hm.EventDiffer()
        ev = d.map_event({"ts": "2026-10-25T20:00:00+0800", "kind": "switch", "source": "网页（192.168.1.23）",
                          "changes": {"video": False}})
        self.assertNotIn("192.168.1.23", json.dumps(ev, ensure_ascii=False))
        self.assertEqual(ev["data"]["source"], "local")

    def test_credentials_in_a_base_url_are_not_reported(self):  # P2-3
        st = hm.map_state({"switches": {}, "models": {"vision": {"source": "openai",
                           "base_url": "https://user:s3cret-pass@llm.example.com/v1", "has_key": False}}})
        self.assertNotIn("s3cret-pass", json.dumps(st))
        self.assertNotIn("s3cret-pass", m._host_of("https://user:s3cret-pass@llm.example.com/v1"))


@unittest.skipIf(websockets is None, "websockets not installed")
class SidecarProtocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        hm.write_secret(os.path.join(self.dir, "token"), TOKEN)
        self.local = FakeLocal()  # local mode "active" (proactive); the hub's welcome says "balanced"
        self.hub = FakeHipiMind()
        await self.hub.start()
        self.bridge = hm.Bridge(hm.load_config_dict({"ws_url": self.hub.url, "token_file": os.path.join(self.dir, "token"),
                                                     "local_api": self.local.url, "poll_seconds": 0.1}))
        self.task = asyncio.create_task(self.bridge.run_forever())
        await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "hello")
        for _ in range(40):
            if self.bridge.ready:
                break
            await asyncio.sleep(0.05)

    async def asyncTearDown(self):
        self.bridge.stop()
        await asyncio.wait_for(self.task, 5)
        await self.hub.stop()
        self.local.close()

    async def test_the_welcome_config_is_applied(self):  # P2-4
        for _ in range(40):
            if any(p["path"] == "/api/command" for p in self.local.posts):
                break
            await asyncio.sleep(0.05)
        cmds = [p["body"]["text"] for p in self.local.posts if p["path"] == "/api/command"]
        self.assertIn("平衡模式", cmds)

    async def test_malformed_commands_are_answered_not_fatal(self):  # P2-5
        for msg in ({"type": "live", "req": "L", "on": True, "fps": "fast"},
                    {"type": "set", "req": "S", "switches": "video"},
                    {"type": "config", "req": "C", "config": {"reminders": {"level": 7}}},
                    {"type": "test_model", "req": "T", "slot": "vision", "model": "engine"}):
            await self.hub.socket.send(json.dumps(msg))
            ack = await self.hub.next(lambda x, r=msg["req"]: isinstance(x, dict) and x.get("type") == "ack"
                                      and x.get("req") == r, timeout=5)
            self.assertFalse(ack["ok"], msg)
            self.assertIn(ack["error"]["code"], ("bad_request", "unsupported"), msg)
        self.assertEqual(self.hub.connections, 1)


class CheapStatusForTheConnector(unittest.TestCase):
    def test_the_poll_does_not_start_windows_helpers_every_second(self):  # P2-6
        calls = []

        class Ev:
            def pids(self, name):
                calls.append(name)
                return []

            def usage(self, what):
                calls.append(what)
                return {}

            def in_use_by_others(self, what):
                return []

        app = make_app()
        app.evidence = Ev()
        dev = hm.AppDevice(app)
        for _ in range(10):
            dev.status()
        self.assertEqual(calls, [])


class SpecDefaults(unittest.TestCase):
    def test_live_defaults_follow_the_spec_when_limits_are_missing(self):  # P2-7
        bridge = hm.Bridge(hm.load_config_dict({"ws_url": "ws://127.0.0.1:9", "token_file": "/nonexistent",
                                                "live": {"max_fps": 10}}), device=object())

        async def go():
            bridge.limits = {}
            bridge._send_json = lambda obj: asyncio.sleep(0)
            bridge.poll_once = lambda: asyncio.sleep(0)
            await bridge.on_live({"type": "live", "req": "x", "on": True, "fps": 10, "max_width": 960})
            p = dict(bridge.live_params)
            await bridge._stop_live()
            return p

        p = asyncio.run(go())
        self.assertLessEqual(p["fps"], 3)
        self.assertEqual(p["max_bytes"], 150_000)

    def test_without_pillow_a_frame_wider_than_asked_is_skipped(self):
        wide = noise_jpeg(1920, 1080)
        small = noise_jpeg(320, 180)
        with mock.patch.dict(sys.modules, {"PIL": None}):
            self.assertIsNone(hm.fit_frame(wide, 960, 70, 10_000_000))
            self.assertEqual(hm.fit_frame(small, 960, 70, 10_000_000), small)

    def test_test_connection_uses_only_documented_codes(self):
        documented = {"connect_failed", "timeout", "unauthorized", "not_found", "model_not_found", "bad_response",
                      "engine_unavailable", "unsupported"}
        r1 = m.test_slot("vision", {"source": "openai", "model": "x"}, None)
        r2 = m.test_slot("vision", {"source": "cloud"}, None,
                         cloud=lambda kind, **p: {"ok": False, "error": {"code": "quota_exceeded", "message": "used"}})
        r3 = m.test_slot("vision", {"source": "cloud"}, None,
                         cloud=lambda kind, **p: {"ok": False, "error": {"code": "plan_required", "message": "plus"}})
        for r in (r1, r2, r3):
            self.assertFalse(r["ok"])
            self.assertIn(r["error"]["code"], documented, r)


class SetAnswersInTime(unittest.TestCase):
    def test_a_switch_ack_does_not_wait_past_the_server_window(self):
        seen = {}

        class FakeApp:
            switches = {}

            def set_switches(self, changes, source):
                return {}

            def wait_settled(self, timeout=8.0):
                seen["timeout"] = timeout
                return True

        code, _ = hm.AppDevice(FakeApp()).switch({"video": True}, "HipiMind (web)")
        self.assertEqual(code, 200)
        self.assertLessEqual(seen["timeout"], 6)


class PairShowsTheAccount(unittest.TestCase):
    def test_pairing_reports_which_account_the_device_joined(self):
        class R:
            status = 201

            def __init__(self, body):
                self.body = body

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        body = json.dumps({"device_id": "d1", "device_token": TOKEN, "account": "a***e@example.com",
                           "ws_url": "wss://x/ws/room/device"}).encode()
        d = tempfile.mkdtemp()
        res = hm.pair("https://api.example.com", "K7QM-2WXH", "Room", os.path.join(d, "t"),
                      urlopen=lambda req, timeout: R(body))
        self.assertEqual(res["account"], "a***e@example.com")
        out = io.StringIO()
        with mock.patch.object(hm, "pair", lambda *a, **k: res), mock.patch("sys.stdout", out):
            hm.main(["pair", "--code", "K7QM-2WXH", "--token-file", os.path.join(d, "t2")])
        self.assertIn("Paired to a***e@example.com", out.getvalue())


class SidecarClientPassesLocalChecks(unittest.TestCase):
    """The sidecar talks to room-companion's local API the way its request checks require: JSON bodies,
    a loopback Host, no Origin, the X-Room-AI header (so tightening those checks does not break it)."""

    def test_switch_and_command_requests_are_json_from_loopback_without_origin(self):
        local = FakeLocal()
        try:
            api = hm.LocalAPI(local.url)
            api.switch({"video": True}, "HipiMind (web)")
            api.command("平衡模式", "HipiMind")
            self.assertEqual(len(local.posts), 2)
            for post in local.posts:
                h = post["headers"]
                self.assertEqual(h.get("content-type"), "application/json")
                self.assertEqual(h.get("x-room-ai"), "1")
                self.assertNotIn("origin", h)
                self.assertTrue(h.get("host", "").startswith("127.0.0.1:"), h.get("host"))
        finally:
            local.close()



HAN = __import__("re").compile(r"[\u4e00-\u9fff]")


class SwitchEventData(unittest.TestCase):
    def test_switch_events_carry_the_changes_and_a_mapped_source(self):
        d = hm.EventDiffer()
        for source, code in (("HipiMind (web)", "web"), ("网页（192.168.1.23）", "local"), ("语音", "voice"),
                             ("飞书", "feishu"), ("本机", "device"), (None, "device")):
            ev = d.map_event({"ts": "2026-10-25T20:00:00+0800", "kind": "switch", "source": source,
                              "changes": {"video": False, "ai": True, "x": 1}})
            self.assertEqual(ev["data"], {"changes": {"video": False, "ai": True}, "source": code}, source)
            self.assertNotIn("192.168.1.23", json.dumps(ev, ensure_ascii=False))

    def test_event_text_follows_the_language(self):
        lang = {"v": "en"}
        d = hm.EventDiffer(language=lambda: lang["v"])
        reminder = {"ts": "2026-10-25T20:00:00+0800", "kind": "reminder", "category": "久坐"}
        switch = {"ts": "2026-10-25T20:00:01+0800", "kind": "switch", "source": "语音", "changes": {"audio": False}}
        notice = {"ts": "2026-10-25T20:00:02+0800", "kind": "gpu_too_hot"}
        en = [d.map_event(e)["text"] for e in (reminder, switch, notice)]
        self.assertEqual(en[0], "Time to move")
        self.assertEqual(en[1], "Sound off (voice)")
        for t in en:
            self.assertIsNone(HAN.search(t), t)
        lang["v"] = "zh"
        zh = [d.map_event(e)["text"] for e in (reminder, switch, notice)]
        self.assertEqual(zh[0], "久坐提醒")
        self.assertEqual(zh[1], "关声音（语音）")
        self.assertTrue(all(HAN.search(t) for t in zh))


class EnglishHub(FakeHipiMind):
    """A HipiMind whose welcome carries config.language = "en"."""

    async def handler(self, ws):
        self.connections += 1
        n = self.connections
        self.socket = ws
        try:
            hello = await ws.recv()
            self.received.append((n, hello))
            await self.inbox.put(json.loads(hello))
            await ws.send(json.dumps({"type": "welcome", "v": 1, "device_id": "dev-1", "name": "Room",
                                      "config": {"language": "en"},
                                      "limits": {"frame_max_bytes": 150000, "live_max_fps": 3}}))
            async for raw in ws:
                self.received.append((n, raw))
                await self.inbox.put(raw if isinstance(raw, bytes) else json.loads(raw))
        except Exception:
            pass


@unittest.skipIf(websockets is None, "websockets not installed")
class WelcomeLanguageSidecar(unittest.IsolatedAsyncioTestCase):
    async def test_a_welcome_in_english_gives_english_event_text(self):
        d = tempfile.mkdtemp()
        hm.write_secret(os.path.join(d, "token"), TOKEN)
        local = FakeLocal()
        hub = EnglishHub()
        await hub.start()
        bridge = hm.Bridge(hm.load_config_dict({"ws_url": hub.url, "token_file": os.path.join(d, "token"),
                                                "local_api": local.url, "poll_seconds": 0.1}))
        task = asyncio.create_task(bridge.run_forever())
        try:
            await hub.next(lambda x: isinstance(x, dict) and x.get("type") == "hello")
            for _ in range(60):
                if bridge.ready and bridge.lang() == "en":
                    break
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.3)
            local.status["events"].append({"ts": "2026-10-25T21:00:00+0800", "kind": "reminder", "category": "久坐"})
            ev = await hub.next(lambda x: isinstance(x, dict) and x.get("type") == "event" and x.get("kind") == "reminder",
                                timeout=5)
            self.assertEqual(ev["text"], "Time to move")
            state = await hub.next(lambda x: isinstance(x, dict) and x.get("type") == "state", timeout=5)
            self.assertIsNone(HAN.search(state["state"]["summary"]), state["state"]["summary"])
        finally:
            bridge.stop()
            await asyncio.wait_for(task, 5)
            await hub.stop()
            local.close()


class WelcomeLanguageInProcess(InProc):
    hub_cls = EnglishHub

    async def test_the_app_writes_and_speaks_reminders_in_english_after_the_welcome(self):
        for _ in range(60):
            if self.app.language == "en":
                break
            await asyncio.sleep(0.05)
        self.assertEqual(self.app.language, "en")
        self.assertEqual(self.app.policy.language, "en")
        said = []
        self.app.policy.deliver = lambda text, cat, speak: said.append(text)
        self.app.policy.set_context(True, 0)
        now = time.time()
        self.app.policy.scene, self.app.policy.scene_since = "coding", now - 95 * 60
        self.app.policy._triggers(now)
        text = self.app.policy.pending["久坐"]["text"]
        self.assertIn("95 minutes of coding", text)
        self.assertIsNone(HAN.search(text), text)
        # kept across a restart, and a config can switch it back
        self.assertEqual(json.load(open(os.path.join(self.dir, "state", "overrides.json")))["language"], "en")
        await self.hub.socket.send(json.dumps({"type": "config", "req": "z", "config": {"language": "zh"}}))
        ack = await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "ack" and x.get("req") == "z")
        self.assertTrue(ack["ok"], ack)
        self.assertEqual(self.app.language, "zh")
        await self.hub.socket.send(json.dumps({"type": "config", "req": "b", "config": {"language": "fr"}}))
        bad = await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "ack" and x.get("req") == "b")
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"]["code"], "bad_request")


class DefaultLanguage(unittest.TestCase):
    def test_without_a_language_the_device_keeps_its_own(self):
        app = make_app()
        self.assertEqual(app.language, "zh")
        self.assertIn("分钟", app.policy._t("久坐", m=90))
        app_en = make_app(language="en")
        self.assertEqual(app_en.policy.language, "en")
        bridge = hm.Bridge(hm.load_config_dict({"ws_url": "ws://127.0.0.1:9", "token_file": "/nonexistent"}),
                           device=hm.AppDevice(app_en))
        self.assertEqual(bridge.lang(), "en")


if __name__ == "__main__":
    unittest.main()
