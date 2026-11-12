"""The HipiMind connector with end-to-end encryption on (room_companion/hipimind.py, docs/e2ee.md), against a
fake HipiMind that keeps the account's group log and relays sealed messages, and the owner's admin page played
with hm-seal directly. Nothing about the room may reach HipiMind in plaintext.

Needs websockets and the hm_seal binding; skipped without them, unless HM_SEAL_REQUIRED=1 (as in CI), when it
fails instead.
"""
import asyncio
import base64
import json
import os
import shutil
import stat
import tempfile
import time
import unittest
from unittest import mock

try:
    import websockets
    from websockets.asyncio.server import serve
except ImportError:  # pragma: no cover
    websockets = None

from room_companion import e2ee
from room_companion import hipimind as hm
from tests.test_e2ee import Log, Page
from tests.test_hipimind import TOKEN, FakeLocal, tiny_jpeg

hs = e2ee.hm_seal
SKIP = (hs is None or websockets is None) and os.environ.get("HM_SEAL_REQUIRED") != "1"
CANARY = "CANARY-ROOM-CONNECTOR-5521"
DEVICE_ID = "dev-1"
REMINDER = {"ts": "2026-11-12T21:00:00+0800", "kind": "reminder", "category": "久坐"}


class Hub:
    """HipiMind for one device: the welcome, the account's group log (§9.6) and the sealed relay (§9.2)."""

    def __init__(self, log: Log):
        self.log = log
        self.received = []   # every raw message from the device
        self.messages = []   # the same, parsed
        self.socket = None
        self.connections = 0
        self.pushed = 0      # log numbers already pushed to the device
        self.own = set()     # numbers the device appended (never pushed back to it)
        self.expired = 0     # numbers up to this one are gone from the log
        self.unanswered = 0  # appends to leave without a group_result

    async def handler(self, ws):
        self.connections += 1
        self.socket = ws
        try:
            hello = await ws.recv()
            self.received.append(hello)
            self.messages.append(json.loads(hello))
            # A welcome whose settings would change the device: with encryption on it must not.
            await ws.send(json.dumps({"type": "welcome", "v": 1, "device_id": DEVICE_ID, "name": "Room",
                                      "config": {"reminders": {"level": "quiet", "quiet_hours": None}},
                                      "limits": {"frame_max_bytes": 300000, "live_max_fps": 5}}))
            async for raw in ws:
                self.received.append(raw)
                msg = raw if isinstance(raw, bytes) else json.loads(raw)
                self.messages.append(msg)
                if isinstance(msg, dict) and msg.get("type") == "group":
                    seq = self.log.append(msg["body"])
                    self.own.add(seq)
                    if self.unanswered:
                        self.unanswered -= 1
                    else:
                        await ws.send(json.dumps({"type": "group_result", "req": msg.get("req"), "ok": True, "seq": seq}))
                elif isinstance(msg, dict) and msg.get("type") == "group_since":
                    after = msg["seq"]
                    rows = [(n, b) for n, b in self.log.after(after) if n > self.expired][:50]
                    for n, b in rows:
                        await ws.send(json.dumps({"type": "group", "seq": n, "body": b}))
                    last = rows[-1][0] if rows else after
                    await ws.send(json.dumps({"type": "group_end", "seq": last,
                                              "more": any(n > last for n, _ in self.log.after(last))}))
        except Exception:
            pass

    async def push_new(self):
        """Push what the page appended to the device, as HipiMind does (never the device's own)."""
        for n, b in self.log.after(self.pushed):
            if n not in self.own:
                await self.socket.send(json.dumps({"type": "group", "seq": n, "body": b}))
        self.pushed = len(self.log.bodies)

    def text(self) -> str:
        return "\n".join(r.decode("latin-1") if isinstance(r, bytes) else r for r in self.received)


@unittest.skipIf(SKIP, "websockets or the hm_seal binding is not installed")
class EncryptedBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.token_file = os.path.join(self.dir, "token")
        hm.write_secret(self.token_file, TOKEN)
        self.local = FakeLocal()
        self.local.status["policy"]["note"] = CANARY  # what the AI sees: the state's scene text
        self.local.jpeg = tiny_jpeg(320, 180)
        self.log = Log()
        self.hub = Hub(self.log)
        self.server = await serve(self.hub.handler, "127.0.0.1", 0)
        url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"
        self.cfg = hm.load_config_dict({"server": "http://127.0.0.1", "ws_url": url, "token_file": self.token_file,
                                        "local_api": self.local.url, "poll_seconds": 0.1, "platform": "linux",
                                        "live": {"max_fps": 4, "max_width": 320},
                                        "e2ee": {"enabled": True, "dir": os.path.join(self.dir, "e2ee")}})
        self.bridge = hm.Bridge(self.cfg)
        self.task = asyncio.create_task(self.bridge.run_forever())
        self.page = Page(self.log)
        self.replies = {}  # index in hub.messages -> what the page read from it

    async def asyncTearDown(self):
        self.bridge.stop()
        try:
            await asyncio.wait_for(self.task, 5)
        except Exception:
            pass
        self.server.close()
        await self.server.wait_closed()
        self.local.close()

    async def until(self, cond, timeout=5.0, what="the condition"):
        deadline = time.monotonic() + timeout
        while True:
            try:
                if cond():
                    return
            except AttributeError:
                pass
            if time.monotonic() > deadline:
                raise AssertionError(f"{what} never held")
            await asyncio.sleep(0.05)

    async def find(self, pred, timeout=5.0):
        deadline = time.monotonic() + timeout
        while True:
            for m in list(self.hub.messages):
                if pred(m):
                    return m
            if time.monotonic() > deadline:
                raise AssertionError("expected message did not arrive")
            await asyncio.sleep(0.05)

    def reply_for(self, req):
        """The page reads every MLS message the device sent, once each, and returns its answer to `req`."""
        for i, m in enumerate(list(self.hub.messages)):
            if not (isinstance(m, dict) and m.get("type") == "sealed" and not m.get("keep")):
                continue
            if i not in self.replies:
                got = self.page.m.handle(base64.b64decode(m["body"]))
                self.assertEqual(got[3], self.bridge.group.signature_key(), "an answer not from the device")
                self.replies[i] = json.loads(got[2])
            payload = self.replies[i]
            if payload.get("t") == "reply" and payload["msg"].get("req") == req:
                return payload["msg"]
        return None

    async def find_reply(self, req, timeout=5.0):
        deadline = time.monotonic() + timeout
        while True:
            got = self.reply_for(req)
            if got is not None:
                return got
            if time.monotonic() > deadline:
                raise AssertionError(f"no sealed answer to {req}")
            await asyncio.sleep(0.05)

    async def send_sealed(self, body):
        await self.hub.socket.send(json.dumps({"type": "sealed", "body": body}))

    async def welcomed(self):
        hello = await self.find(lambda m: isinstance(m, dict) and m.get("type") == "hello")
        await self.until(lambda: self.bridge.ready and self.bridge.group is not None, what="the welcome")
        return hello

    async def paired(self) -> bytes:
        hm.save_pairing_code(self.cfg, self.page.code())
        await self.find(lambda m: isinstance(m, dict) and m.get("type") == "group"
                        and (e2ee.decode_body(m.get("body")) or {}).get("t") == "join")
        await self.until(lambda: self.bridge.group.last_seq is not None, what="the join request's number")
        self.page.answer_joins()
        await self.hub.push_new()
        await self.until(lambda: self.bridge.group.status == "joined", what="joining")
        raw = os.urandom(32)
        self.page.send_data_key(b"K" * 8, raw)
        await self.hub.push_new()
        await self.until(lambda: self.bridge.group.has_data_key(), what="the data key")
        return raw

    def posts(self, path):
        return [p["body"] for p in self.local.posts if p["path"] == path]

    async def test_before_pairing_nothing_about_the_room_leaves_in_plaintext(self):
        hello = await self.welcomed()
        self.assertIn("e2ee", hello["device"]["capabilities"])
        self.assertEqual(set(hello["state"]), {"switches"}, "the hello carried more than the switches")
        self.local.status["events"].append(dict(REMINDER))
        await self.until(lambda: any(e.get("kind") == "reminder" for e in self.bridge.unacked.values()),
                         what="the reminder being noticed")
        # A plaintext command is refused and nothing is done.
        await self.hub.socket.send(json.dumps({"type": "set", "req": "p1", "switches": {"video": True}, "source": "web"}))
        ack = await self.find(lambda m: isinstance(m, dict) and m.get("req") == "p1")
        self.assertEqual((ack["ok"], ack["error"]["code"]), (False, "sealed_only"))
        # `live` is taken in plaintext, but no frame leaves before the device is in the owner's group.
        self.local.status["switches"]["video"] = True
        self.local.status["video"]["state"] = "running"
        await self.hub.socket.send(json.dumps({"type": "live", "req": "l1", "on": True, "fps": 4, "max_width": 320}))
        live = await self.find(lambda m: isinstance(m, dict) and m.get("req") == "l1")
        self.assertTrue(live["ok"])
        self.assertEqual(set(live["state"]), {"switches"}, "a plaintext answer carried more than the switches")
        await asyncio.sleep(1.0)
        self.assertGreater(self.local.snapshots, 0, "control: live video asked for frames")
        # HipiMind's cloud models would carry a frame in plaintext.
        res = await asyncio.wait_for(self.bridge.cloud("infer", {"prompt": "what is here?"}), 2)
        self.assertEqual(res["error"]["code"], "unavailable")
        self.assertIn("encryption", res["error"]["message"])
        await asyncio.sleep(0.3)
        self.assertEqual(self.posts("/api/switch"), [], "a plaintext command was obeyed")
        self.assertEqual(self.posts("/api/command"), [], "the settings in the welcome were applied")
        self.assertFalse(any(isinstance(m, bytes) for m in self.hub.messages), "a frame left outside the group")
        kinds = {m.get("type") for m in self.hub.messages if isinstance(m, dict)}
        self.assertFalse(kinds & {"event", "sealed_event", "infer"}, kinds)
        self.assertNotIn(CANARY, self.hub.text())
        self.assertNotIn("久坐", self.hub.text())

    async def test_once_paired_state_events_frames_and_answers_go_sealed(self):
        await self.welcomed()
        self.local.status["events"].append(dict(REMINDER))
        await self.until(lambda: any(e.get("kind") == "reminder" for e in self.bridge.unacked.values()))
        raw = await self.paired()
        self.assertFalse(os.path.exists(os.path.join(self.cfg["e2ee"]["dir"], hm.PAIRING_CODE_FILE)),
                         "the pairing code was kept after it was used")
        dk = hs.DataKey.from_bytes(raw)
        # The whole state, sealed under the data key, for HipiMind to hand to a page that opens later.
        kept = await self.find(lambda m: isinstance(m, dict) and m.get("type") == "sealed" and m.get("keep") is True)
        blob = base64.b64decode(kept["body"])
        self.assertEqual(blob[:8], b"K" * 8)
        self.assertEqual(json.loads(dk.open(e2ee.state_purpose(DEVICE_ID), blob[8:]))["scene"]["text"], CANARY)
        # The reminder that waited for the data key, sealed, and marked as a reminder for the notifications.
        ev = await self.find(lambda m: isinstance(m, dict) and m.get("type") == "sealed_event")
        self.assertIs(ev.get("remind"), True)
        opened = json.loads(dk.open(e2ee.event_purpose(DEVICE_ID), base64.b64decode(ev["body"])[8:]))
        self.assertEqual((opened["kind"], opened["text"]), ("reminder", "久坐提醒"))
        # A sealed command from the admin page is obeyed, and answered sealed with the whole state.
        await self.send_sealed(self.page.command({"type": "set", "switches": {"video": True}, "source": "web"}, req="s1"))
        reply = await self.find_reply("s1")
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(reply["state"]["switches"]["video"])
        self.assertEqual(reply["state"]["scene"]["text"], CANARY)
        self.assertEqual(self.posts("/api/switch")[-1], {"video": True, "source": "HipiMind (web)"})
        # Frames: 0x01 and an SFrame the page opens, bound to this device.
        await self.hub.socket.send(json.dumps({"type": "live", "req": "l1", "on": True, "fps": 4, "max_width": 320}))
        frame = await self.find(lambda m: isinstance(m, bytes))
        self.assertEqual(frame[0], 0x01)
        opener = hs.FrameOpener()
        self.page.m.update_opener(opener)
        self.assertEqual(opener.open(frame[1:], e2ee.frame_meta(DEVICE_ID))[:2], b"\xff\xd8")
        self.assertNotIn(CANARY, self.hub.text())
        self.assertNotIn("久坐", self.hub.text())

    async def test_a_command_from_a_device_that_is_not_an_admin_is_not_obeyed(self):
        await self.welcomed()
        await self.paired()
        laptop = hs.Member(b"laptop")
        commit, welcome = self.page.m.add(laptop.key_package(), laptop.signature_key())
        self.page.append_mls(commit)
        laptop.join(welcome, self.page.key())
        await self.hub.push_new()
        await self.until(lambda: self.bridge.group.epoch() == self.page.m.epoch(), what="the laptop's add")
        await self.send_sealed(self.page.command({"type": "set", "switches": {"video": True}}, req="n1", sender=laptop))
        await self.send_sealed(self.page.command({"type": "set", "switches": {"audio": False}}, req="a1"))
        self.assertTrue((await self.find_reply("a1"))["ok"], "control: the admin's next command")
        self.assertNotIn(True, [b.get("video") for b in self.posts("/api/switch")], "a non-admin's command was obeyed")
        self.assertIsNone(self.reply_for("n1"))

    async def test_a_command_for_an_epoch_not_read_yet_runs_once_the_log_is_read(self):
        await self.welcomed()
        await self.paired()
        tablet = hs.Member(b"tablet")
        commit, _ = self.page.m.add(tablet.key_package(), tablet.signature_key())
        self.page.append_mls(commit)
        self.hub.pushed = len(self.log.bodies)  # in the log, never pushed: the device has to read it
        await self.send_sealed(self.page.command({"type": "set", "switches": {"video": True}}, req="h1"))
        reply = await self.find_reply("h1", timeout=8)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(self.bridge.group.epoch(), self.page.m.epoch())

    async def test_after_a_reconnect_the_device_reads_on_from_where_it_was(self):
        await self.welcomed()
        await self.paired()
        tablet = hs.Member(b"tablet")
        commit, _ = self.page.m.add(tablet.key_package(), tablet.signature_key())
        self.page.append_mls(commit)
        self.hub.pushed = len(self.log.bodies)
        await self.hub.socket.close(1012, "restart")
        await self.until(lambda: self.hub.connections == 2 and self.bridge.group.epoch() == self.page.m.epoch(),
                         timeout=10, what="reading the log after reconnecting")

    async def test_a_device_whose_missed_messages_are_gone_from_the_log_starts_over(self):
        await self.welcomed()
        await self.paired()
        for name in (b"tablet", b"phone 2"):
            other = hs.Member(name)
            commit, _ = self.page.m.add(other.key_package(), other.signature_key())
            self.page.append_mls(commit)
        self.hub.pushed = len(self.log.bodies)
        self.hub.expired = len(self.log.bodies) - 1  # the first one the device needs is gone
        await self.hub.socket.close(1012, "restart")
        await self.until(lambda: self.bridge.group.status == "unpaired", timeout=10, what="giving up the group")
        self.assertIn("no longer has", self.bridge.group.reason)
        self.assertFalse(os.path.exists(os.path.join(self.cfg["e2ee"]["dir"], e2ee.SAVE_FILE)), "its keys were kept")

    async def test_a_join_request_left_unanswered_is_sent_again_on_the_next_connection(self):
        await self.welcomed()
        self.hub.unanswered = 1
        hm.save_pairing_code(self.cfg, self.page.code())
        first = await self.find(lambda m: isinstance(m, dict) and m.get("type") == "group")
        await asyncio.sleep(0.3)
        self.assertEqual((self.bridge.group.status, self.bridge.group.last_seq), ("joining", None))
        await self.hub.socket.close(1012, "restart")
        appends = lambda: [m for m in self.hub.messages if isinstance(m, dict) and m.get("type") == "group"]
        await self.until(lambda: len(appends()) == 2, timeout=10, what="the join request sent again")
        self.assertEqual(appends()[1]["body"], first["body"])
        await self.until(lambda: self.bridge.group.last_seq == 2, what="the join request's number")


    async def test_a_revoked_device_token_deletes_the_encrypted_group_too(self):
        await self.welcomed()
        await self.paired()
        await self.hub.socket.close(4401, "revoked")
        reason = await asyncio.wait_for(self.task, 10)
        self.assertIn("4401", reason)
        for name in (e2ee.SAVE_FILE, e2ee.KEYS_FILE):
            self.assertFalse(os.path.exists(os.path.join(self.cfg["e2ee"]["dir"], name)),
                             f"{name} was kept for the next account")

@unittest.skipIf(websockets is None and os.environ.get("HM_SEAL_REQUIRED") != "1", "websockets is not installed")
class FailClosedTest(unittest.IsolatedAsyncioTestCase):
    async def test_with_encryption_on_and_no_binding_the_connector_does_not_connect(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        hub = Hub(Log())
        server = await serve(hub.handler, "127.0.0.1", 0)
        try:
            token_file = os.path.join(d, "token")
            hm.write_secret(token_file, TOKEN)
            cfg = hm.load_config_dict({"server": "http://127.0.0.1",
                                       "ws_url": f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}",
                                       "token_file": token_file, "local_api": "http://127.0.0.1:9",
                                       "e2ee": {"enabled": True, "dir": os.path.join(d, "e2ee")}})
            with mock.patch.object(e2ee, "available", return_value=False):
                bridge = hm.Bridge(cfg)
                reason = await asyncio.wait_for(bridge.run_forever(), 5)
            self.assertIn("hm_seal", reason)
            self.assertEqual(hub.connections, 0, "connected without the binding")
        finally:
            server.close()
            await server.wait_closed()


class PairingCodeFileTest(unittest.TestCase):
    def test_the_code_is_left_only_this_users_and_a_damaged_one_is_refused(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        cfg = hm.load_config_dict({"e2ee": {"enabled": True, "dir": os.path.join(d, "e2ee")}})
        path = os.path.join(d, "e2ee", hm.PAIRING_CODE_FILE)
        with self.assertRaises(e2ee.PairingRefused):
            hm.save_pairing_code(cfg, "hmroom1.not-a-code")
        self.assertFalse(os.path.exists(path), "a damaged code was left for the connector")
        code = e2ee.pairing_code(os.urandom(16), os.urandom(32))
        self.assertEqual(hm.save_pairing_code(cfg, f" {code}\n"), path)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), code)
        off = hm.load_config_dict({"e2ee": {"enabled": False, "dir": os.path.join(d, "off")}})
        self.assertEqual(hm._e2ee_pair(off, code), 2)
        self.assertFalse(os.path.exists(os.path.join(d, "off", hm.PAIRING_CODE_FILE)))


if __name__ == "__main__":
    unittest.main()
