"""Regression tests for the second review of the HipiMind connector and the models layer.

The account a device is paired to can go away (token refused or replaced) or be someone else's session;
nothing that account chose may outlive it, words from a remote speech server may only turn things off,
"Test connection" cannot be used to sweep the local network, the token never reaches a log or a
plain-text connection, one odd message never ends the connection, and a close code announced in-band
counts even when the close frame itself arrives as 1005.
"""
import asyncio
import json
import logging
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

try:
    import websockets  # noqa: F401
except ImportError:  # pragma: no cover
    websockets = None

from room_companion import hipimind as hm
from room_companion import models as m
from room_companion.app import DEFAULTS, App
from room_companion.audio import AudioPipeline
from room_companion.devices import AudioDevice
from room_companion.web import serve
from tests.fakes import FAKE_ARECORD, PY, FakeNotifier, write_script
from tests.test_hipimind import TOKEN, FakeHipiMind, FakeLocal
from tests.test_models import FakeModel, closed_port_url
from tests.test_pipelines import make_app as pipelines_app
from tests.test_review_fixes import InProc, make_app
from tests.test_room import FakeClient, FakeServer, Pipe

NEW_TOKEN = "hmr_dev_" + "N" * 43


def wait_until(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


async def async_until(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


def frames_on(hub, n):
    return len([r for c, r in hub.received if c == n and isinstance(r, bytes)])


def texts_on(hub, n):
    return [json.loads(r) for c, r in hub.received if c == n and isinstance(r, str)]


class InbandHub(FakeHipiMind):
    """Like the production edge: HipiMind says {"type": "close", "code": …} in-band, and the close frame
    that follows reaches the device without a status code (1005)."""

    def __init__(self, code, after_welcome=False):
        super().__init__()
        self.code, self.after_welcome = code, after_welcome

    async def handler(self, ws):
        self.connections += 1
        n = self.connections
        self.auth_headers.append(ws.request.headers.get("Authorization"))
        self.socket = ws
        try:
            hello = await ws.recv()
            self.received.append((n, hello))
            await self.inbox.put(json.loads(hello))
            if self.code is None:
                await ws.send(json.dumps({"type": "welcome", "v": 1, "device_id": "dev-1", "config": {}, "limits": {}}))
                async for raw in ws:
                    self.received.append((n, raw))
                    await self.inbox.put(raw if isinstance(raw, bytes) else json.loads(raw))
                return
            if self.after_welcome:
                await ws.send(json.dumps({"type": "welcome", "v": 1, "device_id": "dev-1", "config": {}, "limits": {}}))
                await asyncio.sleep(0.3)
            await ws.send(json.dumps({"type": "close", "code": self.code, "reason": "test"}))
            ws.transport.write(b"\x88\x00")  # a close frame with no status code: the device sees 1005
            await asyncio.wait_for(ws.wait_closed(), 3)
        except Exception:
            pass


def remote_page_config(model_url):
    return {"type": "config", "req": "c-remote",
            "config": {"models": {"vision": {"source": "openai", "base_url": model_url, "model": "x"},
                                  "stt": {"source": "cloud"}}},
            "model_keys": {"vision": "sk-page-key"}}


# ---------------------------------------------------------------- P1-1: models leave with the account

@unittest.skipIf(websockets is None, "websockets not installed")
class RemoteModelsLeaveWithTheAccount(InProc):
    async def asyncSetUp(self):
        self.model = FakeModel()
        await super().asyncSetUp()
        await self.hub.socket.send(json.dumps(remote_page_config(self.model.url)))
        ack = await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "ack"
                                  and x.get("req") == "c-remote", timeout=10)
        self.assertTrue(ack["ok"], ack)
        self.keys_file = os.path.join(self.dir, "state", "model_keys.json")
        self.assertEqual(self.app.models.slot("vision")["source"], "openai")
        self.assertTrue(os.path.exists(self.keys_file))

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.model.close()

    def assert_back_to_own_config(self):
        self.assertEqual(self.app.models.slot("vision"), {"source": "engine"},
                         "the page's remote vision server is still in use")
        self.assertEqual(self.app.models.slot("stt"), {"source": "engine"}, "speech still goes to the cloud")
        self.assertFalse(os.path.exists(self.keys_file), "the page's keys are still on disk")
        self.assertFalse(self.app.models.has_key("vision"))

    async def test_a_refused_token_puts_remote_slots_back_and_deletes_the_keys(self):
        await self.hub.socket.close(4401, "unknown device token")
        await async_until(lambda: self.app.models.slot("vision")["source"] == "engine", 5)
        self.assert_back_to_own_config()
        self.assertEqual(self.conn.bridge.unacked, {})
        self.assertIsNone(self.conn.bridge.device_id)

    async def test_a_replaced_token_ends_the_session_and_resets_them(self):
        hm.write_secret(os.path.join(self.dir, "token"), NEW_TOKEN)   # `pair` ran again
        await async_until(lambda: self.hub.connections >= 2, 6)
        self.assertGreaterEqual(self.hub.connections, 2, "the old account's session went on after the token was replaced")
        self.assertEqual(self.hub.auth_headers[-1], "Bearer " + NEW_TOKEN)
        await async_until(lambda: self.app.models.slot("vision")["source"] == "engine", 5)
        self.assert_back_to_own_config()


class PairingAgainResets(unittest.TestCase):
    def test_pairing_again_drops_the_previous_pages_remote_models_on_disk(self):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = json.dumps({"device_id": "dev-2", "device_token": NEW_TOKEN, "ws_url": "wss://x"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        d = tempfile.mkdtemp()
        cfg = {"data_dir": d, "hipimind": {"server": f"http://127.0.0.1:{srv.server_address[1]}",
                                            "token_file": os.path.join(d, "token")}}
        state = os.path.join(d, "state")
        m.ModelSettings(cfg, state).set({"vision": {"source": "openai", "base_url": "http://127.0.0.1:1/v1"}},
                                        {"vision": "sk-old-owner"})
        try:
            with mock.patch("sys.stdout"):
                self.assertEqual(hm.pair_from_app_config(["--code", "ABCD-EFGH"], cfg), 0)
        finally:
            srv.shutdown()
            srv.server_close()
        again = m.ModelSettings(cfg, state)
        self.assertEqual(again.slot("vision"), {"source": "engine"}, "the previous owner's server is still chosen")
        self.assertFalse(os.path.exists(os.path.join(state, "model_keys.json")))


@unittest.skipIf(websockets is None, "websockets not installed")
class TokenReplacedWhileStopped(unittest.IsolatedAsyncioTestCase):
    async def test_models_chosen_under_another_token_are_dropped_at_start(self):
        d = tempfile.mkdtemp()
        token_file = os.path.join(d, "token")
        hm.write_secret(token_file, TOKEN)
        hub = FakeHipiMind()
        await hub.start()
        cfg = dict(DEFAULTS, data_dir=d, hipimind={"ws_url": hub.url, "token_file": token_file, "poll_seconds": 0.1})

        def new_app():
            return App(cfg, video=Pipe("running"), audio=Pipe(), notifier=FakeNotifier(),
                       ai_client=FakeClient("coding"), model_server=FakeServer())

        first = new_app()
        conn = hm.start_in_process(first, cfg["hipimind"])
        await hub.next(lambda x: isinstance(x, dict) and x.get("type") == "hello", timeout=20)
        await async_until(lambda: conn.bridge.ready, 3)
        await hub.socket.send(json.dumps(remote_page_config("http://127.0.0.1:1/v1")))
        await hub.next(lambda x: isinstance(x, dict) and x.get("type") == "ack" and x.get("req") == "c-remote", timeout=10)
        await asyncio.to_thread(conn.stop)
        hm.write_secret(token_file, NEW_TOKEN)        # paired again while the app was stopped
        second = new_app()
        self.assertEqual(second.models.slot("vision")["source"], "openai")
        conn = hm.start_in_process(second, cfg["hipimind"])
        try:
            await hub.next(lambda x: isinstance(x, dict) and x.get("type") == "hello" and hub.connections == 2)
            self.assertEqual(second.models.slot("vision"), {"source": "engine"},
                             "models chosen under the old token survived the new one")
            self.assertFalse(second.models.has_key("vision"))
        finally:
            await asyncio.to_thread(conn.stop)
            await hub.stop()


class LinkRemovedOnTheDevice(unittest.TestCase):
    """Page choices belong to the token they were made under; with the hipimind section taken out (or
    the token file deleted) there is no token, so they go back to the device's own config."""

    def _bound_choices(self, d):
        cfg = dict(DEFAULTS, data_dir=d)
        ms = m.ModelSettings(cfg, os.path.join(d, "state"))
        ms.set({"vision": {"source": "openai", "base_url": "http://203.0.113.9/v1", "model": "x"}}, {"vision": "sk-page"})
        ms.bind_token(hm.token_fingerprint(TOKEN))
        return cfg

    def _app(self, cfg):
        return App(cfg, video=Pipe("running"), audio=Pipe(), notifier=FakeNotifier(),
                   ai_client=FakeClient("coding"), model_server=FakeServer())

    def test_a_start_without_a_hipimind_section_drops_the_pages_choices(self):
        d = tempfile.mkdtemp()
        app = self._app(self._bound_choices(d))
        self.assertEqual(app.models.slot("vision")["source"], "openai")
        app.start()
        try:
            self.assertEqual(app.models.slot("vision"), {"source": "engine"})
            self.assertFalse(app.models.has_key("vision"))
            self.assertEqual(app.remote_models_text(), "")
        finally:
            app.shutdown()

    def test_choices_never_tied_to_a_token_are_left_alone(self):
        d = tempfile.mkdtemp()
        cfg = dict(DEFAULTS, data_dir=d)
        m.ModelSettings(cfg, os.path.join(d, "state")).set(
            {"vision": {"source": "openai", "base_url": "http://203.0.113.9/v1", "model": "x"}})
        app = self._app(cfg)
        app.start()
        try:
            self.assertEqual(app.models.slot("vision")["source"], "openai")
        finally:
            app.shutdown()


@unittest.skipIf(websockets is None, "websockets not installed")
class TokenFileRemovedInTheApp(unittest.IsolatedAsyncioTestCase):
    async def test_a_missing_token_file_drops_the_pages_choices(self):
        d = tempfile.mkdtemp()
        token_file = os.path.join(d, "token")          # never written: the file was deleted
        cfg = dict(DEFAULTS, data_dir=d, hipimind={"ws_url": "ws://127.0.0.1:1/ws/room/device",
                                                   "token_file": token_file, "token_poll_seconds": 0.1})
        ms = m.ModelSettings(cfg, os.path.join(d, "state"))
        ms.set({"vision": {"source": "openai", "base_url": "http://203.0.113.9/v1", "model": "x"}}, {"vision": "sk-page"})
        ms.bind_token(hm.token_fingerprint(TOKEN))
        app = App(cfg, video=Pipe("running"), audio=Pipe(), notifier=FakeNotifier(),
                  ai_client=FakeClient("coding"), model_server=FakeServer())
        conn = hm.start_in_process(app, cfg["hipimind"])
        try:
            await async_until(lambda: app.models.slot("vision") == {"source": "engine"}, 5)
            self.assertFalse(app.models.has_key("vision"))
        finally:
            await asyncio.to_thread(conn.stop)


# ---------------------------------------------------------------- P1-1: the local page says where things go

class LocalPageShowsRemoteModels(unittest.TestCase):
    def test_the_local_page_names_the_remote_servers_in_use(self):
        app, _ = pipelines_app(tempfile.mkdtemp())
        srv = serve(app)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]

        def status():
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=10) as r:
                return json.loads(r.read())

        try:
            app.apply_models({"vision": {"source": "openai", "base_url": "http://127.0.0.1:11434/v1", "model": "q"},
                              "stt": {"source": "cloud"}})
            text = status().get("remote_text") or ""
            self.assertIn("http://127.0.0.1:11434/v1", text, "the local page does not say where frames go")
            self.assertIn("HipiMind 云", text, "the local page does not say speech goes to the cloud")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
                page = r.read().decode("utf-8")
            self.assertIn('$("remote").textContent=s.remote_text', page)
            self.assertIn('id="remote"', page)
            app.apply_models({"vision": {"source": "engine"}, "stt": {"source": "engine"}})
            self.assertEqual(status().get("remote_text"), "", "a warning with nothing remote")
        finally:
            srv.shutdown()
            srv.server_close()
            app.shutdown()


# ---------------------------------------------------------------- P1-1: remote transcripts only turn things off

class ScriptedTranscriber:
    """An OpenAI-compatible speech-to-text server on loopback that "hears" what the test says."""

    def __init__(self, texts):
        self.texts, self.calls = list(texts), 0
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.calls += 1
                text = fake.texts.pop(0) if fake.texts else ""
                body = json.dumps({"text": text}, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RemoteTranscriptsOnlyTurnThingsOff(unittest.TestCase):
    def test_a_remote_speech_server_cannot_turn_the_camera_on(self):
        stt = ScriptedTranscriber(["房间助手开视频", "房间助手关AI"])
        cfg = dict(DEFAULTS, data_dir=tempfile.mkdtemp())
        app = App(cfg, video=Pipe("off"), audio=object(), notifier=FakeNotifier(), ai_client=FakeClient("coding"),
                  model_server=FakeServer())
        app.audio = AudioPipeline(app.switches, app.events, cfg, on_transcript=app.on_transcript,
                                  find_device=lambda: AudioDevice(1, "Mini", "Fake mic"),
                                  build_cmd=lambda alsa: [PY, write_script(FAKE_ARECORD)],
                                  speech_factory=app._make_speech)
        app.apply_models({"stt": {"source": "openai", "base_url": stt.url, "model": "w"}})
        app.start()
        try:
            app.set_switches({"audio": True, "ai": True}, "test")
            self.assertTrue(wait_until(lambda: not app.switches.get("ai"), 20), "the remote 关AI was not applied")
            self.assertGreaterEqual(stt.calls, 2)
            self.assertFalse(app.switches.get("video"), "a remote transcript turned the camera on")
            kinds = [e["kind"] for e in app.events.latest(200)]
            self.assertIn("voice_command_refused", kinds)
        finally:
            app.shutdown()
            stt.close()

    def test_remote_words_may_turn_off_and_quiet_but_not_on(self):
        app = make_app()
        app.set_switches({"video": True, "audio": True, "ai": True}, "test")
        app.on_transcript("房间助手关视频", remote=True)
        self.assertFalse(app.switches.get("video"))
        app.on_transcript("房间助手开视频关声音", remote=True)       # the "off" half only
        self.assertFalse(app.switches.get("video"))
        self.assertFalse(app.switches.get("audio"))
        app.on_transcript("房间助手主动模式", remote=True)
        self.assertNotEqual(app.policy.state["mode"], "active")
        app.on_transcript("房间助手安静模式", remote=True)
        self.assertEqual(app.policy.state["mode"], "quiet")
        app.on_transcript("房间助手平衡模式", remote=True)            # busier than quiet: an "on"
        self.assertEqual(app.policy.state["mode"], "quiet")
        app.policy.state["suppress_forever"] = ["sitting"]
        app.on_transcript("房间助手恢复提醒", remote=True)            # reminders back on: an "on"
        self.assertEqual(app.policy.state["suppress_forever"], ["sitting"])
        app.on_transcript("房间助手开视频")                          # this machine's own recognizer
        self.assertTrue(app.switches.get("video"))
        app.on_transcript("房间助手恢复提醒")
        self.assertEqual(app.policy.state["suppress_forever"], [])


# ---------------------------------------------------------------- P1-2: Test connection cannot sweep the LAN

class TestConnectionStaysNarrow(unittest.TestCase):
    def test_a_query_string_cannot_pick_a_path_on_a_lan_host(self):
        lan = FakeModel()
        try:
            root = lan.url[:-len("/v1")]
            res = make_app().test_model("vision", {"source": "openai", "base_url": root + "/api/pull?",
                                                   "model": "attacker/evil:latest"})
            self.assertFalse(res["ok"])
            self.assertEqual([r["path"] for r in lan.requests], [], "the page picked a path on a LAN host")
        finally:
            lan.close()
        for url in ("http://h/v1?x=1", "http://h/v1?", "http://h/v1#f", "http://h/v1\x00", "http://h/v1\x7f"):
            self.assertIsNone(m.clean_base_url(url), repr(url))
        self.assertEqual(m.clean_base_url("http://h:8000/v1/"), "http://h:8000/v1")

    def test_the_model_name_reported_back_is_cut(self):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = json.dumps({"model": "INTERNAL-SECRET-" + "Z" * 3000,
                                   "choices": [{"message": {"content": "OK"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            res = m.test_slot("vision", {"source": "openai", "base_url": f"http://127.0.0.1:{srv.server_address[1]}/v1"},
                              None)
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertTrue(res["ok"], res)
        self.assertLessEqual(len(res["result"]["model"]), 80)


@unittest.skipIf(websockets is None, "websockets not installed")
class TestConnectionPerMinute(InProc):
    async def test_at_most_ten_tests_a_minute(self):
        for i in range(13):
            await self.hub.socket.send(json.dumps({"type": "test_model", "req": f"t{i}", "slot": "vision",
                                                   "model": {"source": "off"}}))

        def acks():
            return [x for x in texts_on(self.hub, 1) if x.get("type") == "ack" and str(x.get("req", "")).startswith("t")]

        await async_until(lambda: len(acks()) >= 13, 8)
        limited = [a for a in acks() if (a.get("error") or {}).get("code") == "rate_limited"]
        self.assertEqual(len(acks()), 13)
        self.assertEqual(len(limited), 3, "more than 10 connection tests ran in a minute")


# ---------------------------------------------------------------- P2-1: the token never reaches a log

@unittest.skipIf(websockets is None, "websockets not installed")
class TokenNeverLogged(unittest.IsolatedAsyncioTestCase):
    def grab_root(self):
        records = []

        class Grab(logging.Handler):
            def emit(self, record):
                records.append(f"{record.name} {record.getMessage()}")

        root = logging.getLogger()
        handler, old_level = Grab(), root.level
        ws_old = logging.getLogger("websockets").level

        def restore():
            root.removeHandler(handler)
            root.setLevel(old_level)
            logging.getLogger("websockets").setLevel(ws_old)

        self.addCleanup(restore)
        return records, handler

    async def test_the_sidecar_with_v_never_logs_the_token(self):
        records, handler = self.grab_root()
        d = tempfile.mkdtemp()
        hm.write_secret(os.path.join(d, "token"), TOKEN)
        local = FakeLocal()
        hub = FakeHipiMind(close_with=4401)
        await hub.start()
        path = os.path.join(d, "sidecar.json")
        with open(path, "w") as f:
            json.dump({"ws_url": hub.url, "token_file": os.path.join(d, "token"), "local_api": local.url,
                       "poll_seconds": 0.1}, f)

        def basic_config(level=None, **kw):  # what basicConfig does on a fresh process, into our handler
            logging.getLogger().addHandler(handler)
            logging.getLogger().setLevel(level)

        try:
            with mock.patch("logging.basicConfig", basic_config), mock.patch("sys.stderr"):
                code = await asyncio.to_thread(hm.main, ["run", "--config", path, "-v"])
        finally:
            await hub.stop()
            local.close()
        self.assertEqual(code, 3)
        self.assertTrue(any(r.startswith("room_companion") for r in records), records[:5])
        leaked = [r for r in records if TOKEN in r and not r.startswith("websockets.server")]  # not the fake hub's
        self.assertEqual(leaked, [], "the device token reached the log")

    async def test_a_host_logging_everything_at_debug_never_gets_the_token(self):
        records, handler = self.grab_root()
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.DEBUG)
        d = tempfile.mkdtemp()
        hm.write_secret(os.path.join(d, "token"), TOKEN)
        local = FakeLocal()
        hub = FakeHipiMind(close_with=4401)
        await hub.start()
        try:
            cfg = hm.load_config_dict({"ws_url": hub.url, "token_file": os.path.join(d, "token"),
                                       "local_api": local.url, "poll_seconds": 0.1})
            await asyncio.wait_for(hm.Bridge(cfg).run_forever(), 6)
        finally:
            await hub.stop()
            local.close()
        leaked = [r for r in records if TOKEN in r and not r.startswith("websockets.server")]  # not the fake hub's
        self.assertEqual(leaked, [], "the device token reached the log")


# ---------------------------------------------------------------- P2-2, P2-3: account change, malformed ids

@unittest.skipIf(websockets is None, "websockets not installed")
class SidecarHub(unittest.IsolatedAsyncioTestCase):
    hub_cls = FakeHipiMind

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.token_file = os.path.join(self.dir, "token")
        hm.write_secret(self.token_file, TOKEN)
        self.local = FakeLocal()
        self.hub = self.hub_cls()
        await self.hub.start()
        cfg = hm.load_config_dict({"ws_url": self.hub.url, "token_file": self.token_file, "local_api": self.local.url,
                                   "poll_seconds": 0.1, "platform": "linux", "wait_for_token": True,
                                   "token_poll_seconds": 0.2})
        self.bridge = hm.Bridge(cfg)
        self.task = asyncio.create_task(self.bridge.run_forever())
        await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "hello")
        await async_until(lambda: self.bridge.ready, 3)

    async def asyncTearDown(self):
        self.bridge.stop()
        try:
            await asyncio.wait_for(self.task, 5)
        except Exception:
            pass
        await self.hub.stop()
        self.local.close()

    async def unacked_reminder(self):
        self.local.status["events"].append({"ts": "2026-10-25T21:00:00+0800", "kind": "reminder", "category": "久坐"})
        return await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "event")


class EventsStayWithTheirAccount(SidecarHub):
    async def test_unsent_events_of_one_account_never_go_to_the_next(self):
        ev = await self.unacked_reminder()                 # account A never acks it
        hm.write_secret(self.token_file, NEW_TOKEN)        # paired to account B
        await self.hub.socket.close(1012, "restart")
        await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "hello" and self.hub.connections == 2,
                            timeout=8)
        await async_until(lambda: self.bridge.ready, 3)
        await asyncio.sleep(1.0)
        got = [(x.get("kind"), x.get("text")) for x in texts_on(self.hub, 2) if x.get("type") == "event"]
        self.assertEqual(got, [], "account B received account A's events")
        self.assertNotIn(ev["id"], self.bridge.unacked)


class MalformedIdsAreIgnored(SidecarHub):
    async def test_a_list_or_object_id_is_ignored_and_the_connection_stays(self):
        await self.unacked_reminder()                      # so the ack lookup has something to look in
        for msg in ({"type": "event_ack", "id": ["x"]}, {"type": "infer_result", "req": ["x"], "ok": True},
                    {"type": "set", "req": {"a": 1}, "switches": {"video": True}}):
            await self.hub.socket.send(json.dumps(msg))
        first = self.hub.socket
        await asyncio.sleep(0.5)
        self.assertIsNone(first.close_code, "a malformed id ended the connection")
        await first.send(json.dumps({"type": "ping", "t": 99}))
        try:
            pong = await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "pong", timeout=5)
        except (TimeoutError, AssertionError):
            self.fail("the device stopped answering after a message with a malformed id")
        self.assertEqual(pong["t"], 99)
        self.assertEqual(self.hub.connections, 1)
        self.assertFalse(self.local.status["switches"]["video"], "a command with a malformed req was run")


# ---------------------------------------------------------------- P2-4: keys with control characters

class KeysWithControlCharacters(unittest.TestCase):
    def test_a_value_error_from_the_http_client_loses_its_text(self):
        with self.assertRaises(m.ModelCallError) as e:
            m.http_call(closed_port_url() + "/chat/completions", b"{}",
                        {"Authorization": "Bearer sk-LEAKED\nX-Evil: 1"}, 2)
        self.assertNotIn("sk-LEAKED", e.exception.message)
        self.assertNotIn("sk-LEAKED", str(e.exception))

    def test_the_settings_refuse_a_key_or_address_with_a_control_character(self):
        d = tempfile.mkdtemp()
        st = m.ModelSettings({}, d)
        good = {"vision": {"source": "openai", "base_url": "http://127.0.0.1:1/v1"}}
        with self.assertRaises(ValueError):
            st.set(good, {"vision": "sk-a\nb"})
        with self.assertRaises(ValueError):
            st.set({"vision": {"source": "openai", "base_url": "http://127.0.0.1:1/v1\x1b"}})
        self.assertEqual(st.slot("vision"), {"source": "engine"})
        self.assertFalse(os.path.exists(os.path.join(d, "model_keys.json")))

    def test_a_key_file_with_a_line_break_never_reaches_the_event_log(self):
        d = tempfile.mkdtemp()
        key_file = os.path.join(d, "key")
        with open(key_file, "w") as f:
            f.write("sk-LEAKED\nX-Evil: 1")
        app = make_app(models={"vision": {"source": "openai", "base_url": closed_port_url(), "model": "x",
                                          "api_key_file": key_file}}, observe_tick_s=0.05)
        app.switches.set({"video": True, "ai": True}, "t")
        loop = threading.Thread(target=app._observe_loop, daemon=True)
        loop.start()
        time.sleep(0.6)
        app._stop.set()
        loop.join(5)
        logs = ""
        for n in os.listdir(os.path.join(app.cfg["data_dir"], "events")):
            with open(os.path.join(app.cfg["data_dir"], "events", n), encoding="utf-8") as f:
                logs += f.read()
        self.assertGreater(app.last_obs_at, 0, "the vision call was never tried")
        self.assertNotIn("sk-LEAKED", logs, "the key reached the event log")
        self.assertNotIn("sk-LEAKED", json.dumps({"models": app.models_state(), "error": app.ai.client.last_error}))


@unittest.skipIf(websockets is None, "websockets not installed")
class PageKeyWithControlCharacter(InProc):
    async def test_a_key_with_a_line_break_from_the_page_is_refused(self):
        msg = remote_page_config("http://127.0.0.1:1/v1")
        msg["model_keys"] = {"vision": "sk-a\nb"}
        await self.hub.socket.send(json.dumps(msg))
        ack = await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "ack" and x.get("req") == "c-remote",
                                  timeout=10)
        self.assertFalse(ack["ok"], "a key with a line break was accepted")
        self.assertEqual(ack["error"]["code"], "bad_request")
        self.assertNotIn("sk-a", json.dumps(ack))
        self.assertFalse(self.app.models.has_key("vision"))


# ---------------------------------------------------------------- P2-5: the token only over TLS

class TokenOnlyOverTls(unittest.TestCase):
    def test_plain_ws_or_http_to_another_host_is_refused(self):
        calls = []

        async def never(url, token):
            calls.append(url)
            raise OSError("no network in this test")

        for over in ({"ws_url": "ws://api.hipimind.example/ws/room/device"}, {"server": "http://api.hipimind.example"}):
            d = tempfile.mkdtemp()
            hm.write_secret(os.path.join(d, "token"), TOKEN)
            cfg = hm.load_config_dict({"token_file": os.path.join(d, "token"), "local_api": "http://127.0.0.1:9", **over})
            bridge = hm.Bridge(cfg, device=object(), connect=lambda url, token: never(url, token))

            async def go():
                return await asyncio.wait_for(bridge.run_forever(), 3)

            try:
                reason = asyncio.run(go())
            except asyncio.TimeoutError:
                self.fail(f"the bridge kept trying a plain-text address ({over})")
            self.assertIn("https://", reason or "")
        self.assertEqual(calls, [], "the device token was offered over plain ws://")

        opened = []
        with self.assertRaises(hm.PairError) as e:
            hm.pair("http://api.hipimind.example", "ABCD-EFGH", "Room", os.path.join(tempfile.mkdtemp(), "t"),
                    urlopen=lambda *a, **k: opened.append(a))
        self.assertEqual(e.exception.code, "insecure")
        self.assertEqual(opened, [])

    def test_loopback_and_tls_addresses_are_fine(self):
        for url in ("wss://api.hipimind.com/ws/room/device", "https://api.hipimind.com", "ws://127.0.0.1:9",
                    "ws://localhost:9", "ws://[::1]:9", "http://127.0.0.1:8000"):
            self.assertIsNone(hm.plain_text_refused(url), url)
        for url in ("ws://192.168.1.20:9", "http://api.hipimind.example", "ftp://api.hipimind.example", "wss://"):
            self.assertIsNotNone(hm.plain_text_refused(url), url)


# ---------------------------------------------------------------- tests the review found missing

class RecordingBridge(hm.Bridge):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.pauses = []

    async def _pause(self, seconds):
        self.pauses.append(seconds)
        if len(self.pauses) >= 9:
            self.stop()


class ReconnectBackoff(unittest.TestCase):
    def test_reconnect_waits_double_up_to_a_minute(self):
        d = tempfile.mkdtemp()
        hm.write_secret(os.path.join(d, "token"), TOKEN)

        async def refuse(url, token):
            raise OSError("connection refused")

        cfg = hm.load_config_dict({"ws_url": "ws://127.0.0.1:9", "token_file": os.path.join(d, "token"),
                                   "poll_seconds": 5})
        bridge = RecordingBridge(cfg, device=object(), connect=refuse)
        asyncio.run(asyncio.wait_for(bridge.run_forever(), 10))
        expected = [1, 2, 4, 8, 16, 32, 60, 60, 60]
        self.assertEqual(len(bridge.pauses), len(expected), bridge.pauses)
        for got, want in zip(bridge.pauses, expected):
            self.assertGreaterEqual(got, 0.8 * want, bridge.pauses)
            self.assertLessEqual(got, 1.2 * want, bridge.pauses)


class ErrorsCarryNoResponseBody(unittest.TestCase):
    def test_test_connection_errors_never_include_the_answer_body(self):
        # Two bodies: one that names no model, so 400, 500 and 502 reach the plain "HTTP <code> from
        # <host>" line, and one that does, so they take the model_not_found branch instead.
        bodies = (b'{"error": {"message": "BODY-SENTINEL-4412 internal path /srv/x"}}',
                  b'{"error": {"message": "BODY-SENTINEL-4412 model not found, internal path /srv/x"}}')
        reached_plain = []
        for body in bodies:
            for status in (400, 401, 404, 500, 502):
                srv = FakeModel(status=status, error_body=body)
                try:
                    for slot in ("vision", "stt", "tts"):
                        res = m.test_slot(slot, {"source": "openai", "base_url": srv.url, "model": "x"}, None)
                        self.assertFalse(res["ok"])
                        self.assertNotIn("BODY-SENTINEL", json.dumps(res), (status, slot, res))
                        if res["error"]["message"].startswith(f"HTTP {status} from"):
                            reached_plain.append(status)
                finally:
                    srv.close()
        self.assertTrue({400, 500, 502} <= set(reached_plain), reached_plain)
        secret = bodies[1]
        class NotOpenAI(BaseHTTPRequestHandler):   # 200, but not an OpenAI-shaped answer
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(secret)))
                self.end_headers()
                self.wfile.write(secret)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), NotOpenAI)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            for slot in ("vision", "stt", "tts"):
                res = m.test_slot(slot, {"source": "openai", "base_url": f"http://127.0.0.1:{srv.server_address[1]}/v1",
                                         "model": "x"}, None)
                self.assertFalse(res["ok"], (slot, res))
                self.assertNotIn("BODY-SENTINEL", json.dumps(res), (slot, res))
        finally:
            srv.shutdown()
            srv.server_close()


class LiveStopsWithTheConnection(SidecarHub):
    async def test_a_new_connection_that_never_asked_for_live_gets_no_frames(self):
        self.local.status["switches"]["video"] = True
        self.local.status["video"]["state"] = "running"
        await self.hub.socket.send(json.dumps({"type": "live", "req": "l1", "on": True, "fps": 3, "max_width": 320}))
        await async_until(lambda: frames_on(self.hub, 1) >= 2, 5)
        self.assertGreaterEqual(frames_on(self.hub, 1), 2, "live video never started")
        await self.hub.socket.close(1012, "restart")
        await self.hub.next(lambda x: isinstance(x, dict) and x.get("type") == "hello" and self.hub.connections == 2,
                            timeout=8)
        await async_until(lambda: self.bridge.ready, 3)
        await asyncio.sleep(1.5)
        self.assertEqual(frames_on(self.hub, 2), 0, "frames went to a connection that never asked for live")


# ---------------------------------------------------------------- in-band close (production delivers 1005)

@unittest.skipIf(websockets is None, "websockets not installed")
class InbandClose(unittest.IsolatedAsyncioTestCase):
    async def run_sidecar(self, hub, seconds):
        d = tempfile.mkdtemp()
        hm.write_secret(os.path.join(d, "token"), TOKEN)
        local = FakeLocal()
        await hub.start()
        cfg = hm.load_config_dict({"ws_url": hub.url, "token_file": os.path.join(d, "token"),
                                   "local_api": local.url, "poll_seconds": 0.1})
        bridge = hm.Bridge(cfg)
        task = asyncio.create_task(bridge.run_forever())
        try:
            done, _ = await asyncio.wait({task}, timeout=seconds)
            return (task.result() if done else None), hub.connections
        finally:
            bridge.stop()
            await asyncio.wait_for(task, 5)
            await hub.stop()
            local.close()

    async def test_an_in_band_4401_stops_the_sidecar_though_the_frame_says_1005(self):
        reason, connections = await self.run_sidecar(InbandHub(4401), 4)
        self.assertEqual(connections, 1, "the device reconnected after HipiMind said 4401")
        self.assertIn("4401", reason or "")

    async def test_an_in_band_4409_after_welcome_stops(self):
        reason, connections = await self.run_sidecar(InbandHub(4409, after_welcome=True), 4)
        self.assertEqual(connections, 1)
        self.assertIn("4409", reason or "")

    async def test_an_in_band_4429_backs_off_and_reconnects(self):
        reason, connections = await self.run_sidecar(InbandHub(4429), 4)
        self.assertIsNone(reason)
        self.assertGreaterEqual(connections, 2)


@unittest.skipIf(websockets is None, "websockets not installed")
class InbandRefusalInTheApp(unittest.IsolatedAsyncioTestCase):
    async def test_an_in_band_4401_resets_the_pages_models_and_is_not_retried(self):
        d = tempfile.mkdtemp()
        token_file = os.path.join(d, "token")
        hm.write_secret(token_file, TOKEN)
        hub = InbandHub(None)
        await hub.start()
        cfg = dict(DEFAULTS, data_dir=d, hipimind={"ws_url": hub.url, "token_file": token_file, "poll_seconds": 0.1,
                                                   "token_poll_seconds": 0.2})
        app = App(cfg, video=Pipe("running"), audio=Pipe(), notifier=FakeNotifier(), ai_client=FakeClient("coding"),
                  model_server=FakeServer())
        conn = hm.start_in_process(app, cfg["hipimind"])
        try:
            await hub.next(lambda x: isinstance(x, dict) and x.get("type") == "hello")
            await async_until(lambda: conn.bridge.ready, 3)
            await hub.socket.send(json.dumps(remote_page_config("http://127.0.0.1:1/v1")))
            await hub.next(lambda x: isinstance(x, dict) and x.get("type") == "ack" and x.get("req") == "c-remote",
                           timeout=10)
            hub.code = 4401                                   # the device is removed on the website
            await hub.socket.close(1012, "restart")
            await async_until(lambda: hub.connections >= 2, 6)
            await async_until(lambda: app.models.slot("vision")["source"] == "engine", 4)
            await asyncio.sleep(1.0)
            self.assertEqual(hub.connections, 2, "the refused token was tried again")
            self.assertEqual(app.models.slot("vision"), {"source": "engine"})
            self.assertFalse(app.models.has_key("vision"))
        finally:
            await asyncio.to_thread(conn.stop)
            await hub.stop()


if __name__ == "__main__":
    unittest.main()
