"""HipiMind's announce: the owner types a sentence on the website and the room reads it out.

The device acks at once (taken, or why not), sends announce_result once it has really been played,
and HipiMind only ever hears the length of the text back, never the words.
"""

import asyncio
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None

from room_companion import hipimind as hm
from room_companion.app import DEFAULTS, App
from tests.fakes import FakeNotifier
from tests.test_hipimind import TOKEN, FakeHipiMind
from tests.test_room import Pipe
from tests.test_speaker import REALTEK, make_speaker

WORDS = "晚饭好了，下楼吃饭"


def is_type(kind, req=None):
    return lambda x: isinstance(x, dict) and x.get("type") == kind and (req is None or x.get("req") == req)


ANNOUNCE_EVENT = lambda x: isinstance(x, dict) and x.get("type") == "event" and x.get("kind") == "announce"  # noqa: E731


async def expect(hub, timeout=10, **preds):
    """The first message matching each predicate, whatever order they arrive in (the hub drops the rest)."""
    found = {}
    while len(found) < len(preds):
        msg = await hub.next(lambda x: any(p(x) for k, p in preds.items() if k not in found), timeout)
        for k, p in preds.items():
            if k not in found and p(msg):
                found[k] = msg
                break
    return found


@unittest.skipIf(websockets is None, "websockets not installed")
class AnnounceInTheApp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        d = tempfile.mkdtemp()
        token_file = os.path.join(d, "token")
        hm.write_secret(token_file, TOKEN)
        self.hub = FakeHipiMind()
        await self.hub.start()
        self.sp, self.tts, self.played = make_speaker([REALTEK])
        cfg = dict(DEFAULTS, data_dir=d, hipimind={"ws_url": self.hub.url, "token_file": token_file,
                                                   "poll_seconds": 0.1})
        self.app = App(cfg, video=Pipe(), audio=Pipe(), notifier=FakeNotifier(), speaker=self.sp)
        self.conn = hm.start_in_process(self.app, cfg["hipimind"])
        self.hello = await self.hub.next(is_type("hello"))

    async def asyncTearDown(self):
        await asyncio.to_thread(self.conn.stop)
        await self.hub.stop()

    async def test_typed_text_is_read_out_and_reported_back_without_the_words(self):
        self.assertIn("announce", self.hello["device"]["capabilities"])
        await self.hub.socket.send(json.dumps({"type": "announce", "req": "a-1", "text": WORDS, "source": "web"}))
        got = await expect(self.hub, ack=is_type("ack", "a-1"), done=is_type("announce_result", "a-1"),
                           event=ANNOUNCE_EVENT)
        ack, done, event = got["ack"], got["done"], got["event"]
        self.assertTrue(ack["ok"], ack)
        self.assertEqual(ack["result"], {"id": "a-1"})  # nothing of the local message (it names the output)
        self.assertEqual(done, {"type": "announce_result", "req": "a-1", "ok": True, "output": "电脑喇叭",
                                "seconds": 1.0, "peak": 0.3, "error": None})
        self.assertEqual(self.tts.texts, [WORDS])
        self.assertEqual(event["text"], f"播报了一句（{len(WORDS)} 字）")
        self.assertEqual(event["data"], {"chars": len(WORDS), "source": "web"})
        sent = [raw for _, raw in self.hub.received if isinstance(raw, str)]
        self.assertFalse([raw for raw in sent if "晚饭" in raw], "the words went back to HipiMind")

    async def test_what_the_device_will_not_take_is_refused_with_a_code(self):
        cases = [("e", ""), ("l", "字" * 301)]
        for req, text in cases:
            await self.hub.socket.send(json.dumps({"type": "announce", "req": req, "text": text}))
        got = await expect(self.hub, e=is_type("ack", "e"), l=is_type("ack", "l"))
        self.assertEqual({k: (a["ok"], a["error"]["code"]) for k, a in got.items()},
                         {"e": (False, "empty"), "l": (False, "too_long")})
        self.assertEqual(self.tts.texts, [])

    async def test_more_than_six_a_minute_are_refused_by_the_device(self):
        for i in range(7):
            await self.hub.socket.send(json.dumps({"type": "announce", "req": f"r{i}", "text": f"第{i}句"}))
        acks = {}
        while len(acks) < 7:  # handled side by side, so the acks come in any order
            ack = await self.hub.next(lambda x: is_type("ack")(x) and str(x.get("req")).startswith("r"))
            acks[ack["req"]] = ack
        refused = [a for a in acks.values() if not a["ok"]]
        self.assertEqual(len(refused), 1, acks)
        self.assertEqual(refused[0]["error"]["code"], "rate_limited")

    async def test_a_failed_playback_is_reported_as_failed(self):
        self.sp.outputs, self.sp.cfg["check_output"] = [], False
        self.sp.output = None  # nothing that can make a sound
        await self.hub.socket.send(json.dumps({"type": "announce", "req": "f-1", "text": "没有喇叭"}))
        got = await expect(self.hub, ack=is_type("ack", "f-1"), done=is_type("announce_result", "f-1"))
        ack, done = got["ack"], got["done"]
        self.assertTrue(ack["ok"])
        self.assertEqual((done["ok"], done["error"], done["output"]), (False, "no_output", None))
        self.assertNotIn("没有喇叭", json.dumps(done, ensure_ascii=False))

    async def test_hardware_names_and_local_paths_never_reach_hipimind(self):
        """Like the summary's guard: an output with no short name is sent as a plain word, a failure as a
        code. The sentinels must be in nothing that was sent."""
        headphones = {"name": "Headphones (SENTINEL-HW-99 Pods)", "volume": 50, "muted": False, "default": True}
        self.sp.list_outputs = lambda: [dict(headphones)]
        self.sp.check_output()
        await self.hub.socket.send(json.dumps({"type": "announce", "req": "h-1", "text": "开饭了"}))
        played = await expect(self.hub, ack=is_type("ack", "h-1"), done=is_type("announce_result", "h-1"))
        self.assertEqual(played["done"]["output"], "音箱")
        def fails(path, secs, device, volume):  # what winplay.ps1's output and a WSL path look like
            raise RuntimeError(r"playback failed: C:\Users\SENTINEL-USER\room-companion\tts\say.wav: denied")

        self.sp.play = fails
        await self.hub.socket.send(json.dumps({"type": "announce", "req": "h-2", "text": "再来"}))
        failed = await expect(self.hub, ack=is_type("ack", "h-2"), done=is_type("announce_result", "h-2"))
        self.assertEqual((failed["done"]["ok"], failed["done"]["error"]), (False, "playback_failed"))
        sent = " ".join(raw for _, raw in self.hub.received if isinstance(raw, str))
        self.assertNotIn("SENTINEL", sent)

    async def test_a_remote_voice_with_ai_off_is_refused_at_once(self):
        self.app.apply_models({"tts": {"source": "cloud"}})
        self.assertFalse(self.app.switches.get("ai"))
        await self.hub.socket.send(json.dumps({"type": "announce", "req": "o-1", "text": "开饭了"}))
        ack = await self.hub.next(is_type("ack", "o-1"))
        self.assertEqual((ack["ok"], ack["error"]["code"]), (False, "ai_off"))
        self.assertEqual(self.tts.texts, [])


class AnnounceEventText(unittest.TestCase):
    def test_only_the_length_and_a_source_code_go_out(self):
        d = hm.EventDiffer(language=lambda: "en")
        m = d.map_event({"kind": "broadcast", "chars": 12, "source": "HipiMind (web)", "ts": "2026-10-26T10:00:00"})
        self.assertEqual(m["kind"], "announce")
        self.assertEqual(m["text"], "Announced a message (12 characters)")
        self.assertEqual(m["data"], {"chars": 12, "source": "web"})
        self.assertEqual(hm.EventDiffer(language=lambda: "zh").map_event(
            {"kind": "broadcast", "chars": 3, "source": "飞书"})["data"]["source"], "feishu")

    def test_it_can_be_turned_off(self):
        d = hm.EventDiffer(enabled={"announce": False})
        self.assertIsNone(d.map_event({"kind": "broadcast", "chars": 3, "source": "网页"}))


class AnnounceThroughTheLocalAPI(unittest.TestCase):
    """Sidecar mode: POST /api/broadcast, then GET /api/broadcast/<id> until it is played."""

    def serve(self, broadcast_status=200):
        calls = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                calls.append(("POST", self.path, body, self.headers.get("X-Room-AI")))
                if broadcast_status != 200:
                    return self._send(broadcast_status, {"error": "not found"})
                self._send(200, {"ok": True, "id": body["id"], "message": "好"})

            def do_GET(self):
                calls.append(("GET", self.path, None, None))
                state = "queued" if sum(1 for c in calls if c[0] == "GET") < 2 else "done"
                self._send(200, {"id": "s-1", "state": state, "ok": state == "done" or None, "output": "电脑喇叭",
                                 "seconds": 1.5, "peak": 0.4, "error": None})

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return hm.LocalAPI(f"http://127.0.0.1:{srv.server_address[1]}"), calls

    def test_a_sidecar_follows_the_announcement_until_it_is_played(self):
        api, calls = self.serve()
        got = threading.Event()
        results = []
        res = api.announce("开饭", "HipiMind (web)", "s-1", lambda r: (results.append(r), got.set()))
        self.assertTrue(res["ok"])
        self.assertTrue(got.wait(10))
        self.assertEqual(results[0], {"id": "s-1", "ok": True, "output": "电脑喇叭", "seconds": 1.5, "peak": 0.4,
                                      "error": None})
        self.assertEqual(calls[0][:3], ("POST", "/api/broadcast", {"text": "开饭", "id": "s-1",
                                                                   "source": "HipiMind (web)"}))
        self.assertEqual(calls[0][3], "1")
        self.assertTrue(all(c[1] == "/api/broadcast/s-1" for c in calls[1:]))

    def test_an_older_room_companion_without_broadcast_says_so(self):
        api, _ = self.serve(broadcast_status=404)
        res = api.announce("开饭", "HipiMind (web)", "s-2", lambda r: None)
        self.assertEqual((res["ok"], res["code"]), (False, "no_output"))
