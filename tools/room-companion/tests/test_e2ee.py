"""The device's side of end-to-end encryption (room_companion/e2ee.py, docs/e2ee.md), against an owner's
admin page played here with hm-seal directly, and a group log kept in a list as HipiMind keeps it.

Needs the hm_seal binding (sunkit tools/hm-seal/python); skipped without it, unless HM_SEAL_REQUIRED=1
(as in CI), when it fails instead.
"""
import base64
import json
import os
import shutil
import stat
import tempfile
import unittest

from room_companion import e2ee

hm = e2ee.hm_seal
SKIP = hm is None and os.environ.get("HM_SEAL_REQUIRED") != "1"
CANARY = "CANARY-ROOM-E2EE-4417"
DEVICE_ID = "0342c48c-3de7-4806-82ec-97eeaba607f2"


class Log:
    """HipiMind's group log: numbered 1, 2, 3 … in the order bodies arrive."""

    def __init__(self):
        self.bodies = []

    def append(self, body: str) -> int:
        assert isinstance(body, str) and len(body) <= e2ee.GROUP_MAX_CHARS
        self.bodies.append(body)
        return len(self.bodies)

    def after(self, n: int):
        return [(i + 1, b) for i, b in enumerate(self.bodies) if i + 1 > n]


class Page:
    """The owner's admin page, as docs/e2ee.md has it do."""

    def __init__(self, log: Log, name=b"page"):
        self.m = hm.Member(name)
        self.m.create_group(b"account-1")
        self.log = log
        self.codes = {}
        self.seen = 0

    def key(self) -> bytes:
        return self.m.signature_key()

    def code(self) -> str:
        secret = os.urandom(e2ee.SECRET_BYTES)
        self.codes[e2ee.pairing_id(secret)] = secret
        return e2ee.pairing_code(secret, self.key())

    def append_mls(self, message: bytes) -> int:
        seq = self.log.append(e2ee.encode_body({"t": "mls", "msg": e2ee.b64(message)}))
        self.seen = seq
        return seq

    def answer_joins(self, between=None):
        """Read the log and add each device whose join request matches one of this page's codes.
        `between` runs after the add's commit is in the log and before the Welcome is."""
        for seq, body in self.log.after(self.seen):
            self.seen = seq
            envelope = e2ee.decode_body(body)
            if not envelope or envelope.get("t") != "join":
                continue
            secret = self.codes.pop(e2ee.unb64(envelope["id"]))
            key, kp = e2ee.check_join(secret, envelope)
            after = self.seen
            commit, welcome = self.m.add(kp, key)
            self.append_mls(commit)
            if between:
                between()
            self.seen = self.log.append(e2ee.encode_body({"t": "welcome", "to": e2ee.b64(key), "after": after,
                                                          "welcome": e2ee.b64(welcome)}))
            return

    def send_data_key(self, key_id: bytes, raw: bytes, sender=None) -> int:
        sender = sender or self.m
        msg = sender.seal(json.dumps({"t": "datakey", "id": e2ee.b64(key_id), "key": e2ee.b64(raw)}).encode())
        return self.append_mls(msg)

    def command(self, cmd: dict, req="r-1", sender=None) -> str:
        sender = sender or self.m
        return e2ee.b64(sender.seal(json.dumps({"t": "cmd", "req": req, "cmd": cmd}).encode()))


def drive(group: e2ee.DeviceGroup, log: Log) -> list:
    """What the connector does with the log: read after the last number dealt with, in order, and go
    back when told to."""
    out = []
    for _ in range(10):
        start = group.last_seq
        if start is None:
            return out
        rewound = False
        for seq, body in log.after(start):
            got = group.process(seq, body)
            out.extend(got)
            if any(g[0] in ("rewind", "gap") for g in got):
                rewound = True
                break
            if group.status not in ("joining", "joined"):
                return out
        if not rewound:
            return out
    raise AssertionError("the log never settled")


def joined_device(test, log=None, page=None, between=None):
    log = log or Log()
    page = page or Page(log)
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d, True)
    group = e2ee.DeviceGroup(os.path.join(d, "e2ee"), DEVICE_ID)
    group.join_sent(log.append(group.start_pairing(page.code())))
    page.answer_joins(between)
    out = drive(group, log)
    test.assertEqual(group.status, "joined", out)
    return log, page, group, out


@unittest.skipIf(SKIP, "the hm_seal binding is not installed")
class PairingCodeTest(unittest.TestCase):
    def test_a_pairing_code_is_read_only_in_its_one_form(self):
        secret, admin = os.urandom(16), os.urandom(32)
        code = e2ee.pairing_code(secret, admin)
        self.assertTrue(code.startswith("hmroom1.") and len(code) == 72, code)
        self.assertEqual(e2ee.parse_pairing_code(code), e2ee.PairingCode(secret, admin))
        self.assertEqual(e2ee.parse_pairing_code(f"  {code}\n"), e2ee.PairingCode(secret, admin))
        body = code[len("hmroom1."):]
        refused = {
            "another version": "hmroom2." + body,
            "no prefix": body,
            "one character short": code[:-1],
            "one character long": code + "A",
            "padding": code[:-2] + "==",
            "a standard base64 character": code[:-1] + "+",
            "a space inside": code[:30] + " " + code[31:],
            "empty": "",
            "not text": 12345,
        }
        for label, text in refused.items():
            with self.assertRaises(e2ee.PairingRefused, msg=label):
                e2ee.parse_pairing_code(text)


@unittest.skipIf(SKIP, "the hm_seal binding is not installed")
class PairingTest(unittest.TestCase):
    def new_group(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return e2ee.DeviceGroup(os.path.join(d, "e2ee"), DEVICE_ID)

    def test_the_device_joins_the_group_of_the_code_it_scanned(self):
        log, page, group, out = joined_device(self)
        self.assertIn(("joined", page.m.epoch()), out)
        self.assertEqual(group.epoch(), page.m.epoch())
        self.assertNotIn(group.signature_key(), page.m.admins(), "the room device became an admin")
        msg = page.m.seal(b"hello room")
        self.assertEqual(group._member.handle(msg)[2], b"hello room")

    def test_a_code_naming_another_admin_is_refused_at_the_welcome(self):
        # The QR code was changed: same secret, the admin key swapped for someone else's.
        log = Log()
        page = Page(log)
        secret = os.urandom(16)
        page.codes[e2ee.pairing_id(secret)] = secret
        stranger = hm.Member(b"stranger")
        group = self.new_group()
        group.join_sent(log.append(group.start_pairing(e2ee.pairing_code(secret, stranger.signature_key()))))
        page.answer_joins()
        out = drive(group, log)
        self.assertEqual(group.status, "unpaired", out)
        self.assertTrue(any(o[0] == "pairing_failed" for o in out), out)
        self.assertIn("other than the one whose code was scanned", group.reason)
        self.assertFalse(os.path.exists(os.path.join(group.directory, e2ee.SAVE_FILE)), "its keys were kept")
        self.assertIsNone(group.seal_frame(b"jpeg"))

    def test_a_welcome_hipimind_made_is_refused(self):
        # HipiMind relays the join request, so it can add the device to a group of its own.
        log = Log()
        page = Page(log)
        group = self.new_group()
        seq = log.append(group.start_pairing(page.code()))
        group.join_sent(seq)
        relay = hm.Member(b"relay")
        relay.create_group(b"account-1")
        request = e2ee.decode_body(log.bodies[seq - 1])
        _, welcome = relay.add(e2ee.unb64(request["kp"]), e2ee.unb64(request["key"]))
        log.append(e2ee.encode_body({"t": "welcome", "to": request["key"], "after": seq, "welcome": e2ee.b64(welcome)}))
        out = drive(group, log)
        self.assertEqual(group.status, "unpaired", out)
        self.assertTrue(any(o[0] == "pairing_failed" for o in out), out)

    def test_the_page_refuses_a_join_request_that_does_not_match_its_code(self):
        log = Log()
        page = Page(log)
        code = page.code()
        parsed = e2ee.parse_pairing_code(code)
        group = self.new_group()
        envelope = e2ee.decode_body(group.start_pairing(code))
        self.assertEqual(e2ee.check_join(parsed.secret, envelope)[0], group.signature_key(), "control")
        # HipiMind puts in a key package of its own, keeping everything else.
        relay = hm.Member(b"relay")
        swapped = dict(envelope, kp=e2ee.b64(relay.key_package()), key=e2ee.b64(relay.signature_key()))
        with self.assertRaisesRegex(e2ee.PairingRefused, "does not match"):
            e2ee.check_join(parsed.secret, swapped)
        only_kp = dict(envelope, kp=e2ee.b64(relay.key_package()))
        with self.assertRaisesRegex(e2ee.PairingRefused, "does not match"):
            e2ee.check_join(parsed.secret, only_kp)
        mac = bytearray(e2ee.unb64(envelope["mac"]))
        mac[0] ^= 1
        with self.assertRaisesRegex(e2ee.PairingRefused, "does not match"):
            e2ee.check_join(parsed.secret, dict(envelope, mac=e2ee.b64(bytes(mac))))
        # A code with another secret answers no code of this page's.
        with self.assertRaisesRegex(e2ee.PairingRefused, "another code"):
            e2ee.check_join(os.urandom(16), envelope)


@unittest.skipIf(SKIP, "the hm_seal binding is not installed")
class LogTest(unittest.TestCase):
    def test_the_log_is_read_strictly_in_order(self):
        log, page, group, _ = joined_device(self)
        last = group.last_seq
        tablet = hm.Member(b"tablet")
        commit, _ = page.m.add(tablet.key_package(), tablet.signature_key())
        page.append_mls(commit)
        msg = page.m.seal(b"after the tablet")
        page.append_mls(msg)
        epoch = group.epoch()
        self.assertEqual(group.process(last + 2, log.bodies[last + 1]), [("gap", last)])
        self.assertEqual((group.last_seq, group.epoch()), (last, epoch), "a message was processed out of order")
        self.assertEqual(group.process(last + 1, log.bodies[last])[0][:2], ("commit", epoch + 1))
        self.assertEqual(group.process(last + 1, log.bodies[last]), [], "a number dealt with was processed again")
        self.assertEqual(group.epoch(), epoch + 1)

    def test_after_joining_the_device_applies_a_commit_made_before_its_welcome(self):
        # Another commit for the device's new epoch lands between the commit that adds it and its
        # Welcome: the device must go back and apply it.
        log = Log()
        page = Page(log)
        tablet = hm.Member(b"tablet")

        def another_commit():
            commit, _ = page.m.add(tablet.key_package(), tablet.signature_key())
            page.append_mls(commit)

        _, _, group, out = joined_device(self, log, page, between=another_commit)
        self.assertTrue(any(o[0] == "rewind" for o in out), out)
        self.assertEqual(group.epoch(), page.m.epoch(), f"the device missed the commit before its Welcome: {out}")
        self.assertTrue(any(o[0] == "skipped" for o in out), "the commit that added the device was not skipped")
        msg = page.m.seal(b"to everyone")
        self.assertEqual(group._member.handle(msg)[2], b"to everyone")


@unittest.skipIf(SKIP, "the hm_seal binding is not installed")
class DataKeyAndCommandTest(unittest.TestCase):
    def add_laptop(self, page, log, group):
        laptop = hm.Member(b"laptop")
        commit, welcome = page.m.add(laptop.key_package(), laptop.signature_key())
        page.append_mls(commit)
        laptop.join(welcome, page.key())
        drive(group, log)
        self.assertEqual(group.epoch(), laptop.epoch())
        return laptop

    def test_a_data_key_is_taken_only_from_an_admin(self):
        log, page, group, _ = joined_device(self)
        laptop = self.add_laptop(page, log, group)
        page.send_data_key(b"L" * 8, b"l" * 32, sender=laptop)
        out = drive(group, log)
        self.assertTrue(any(o[0] == "ignored" and "not an admin" in o[2] for o in out), out)
        self.assertFalse(group.has_data_key(), "a data key from a device that is not an admin was taken")
        page.send_data_key(b"K" * 8, b"k" * 32)
        self.assertIn(("datakey", (b"K" * 8).hex()), drive(group, log))
        self.assertTrue(group.has_data_key())

    def test_a_command_is_acted_on_only_from_an_admin(self):
        log, page, group, _ = joined_device(self)
        laptop = self.add_laptop(page, log, group)
        got = group.open_command(page.command({"type": "set", "video": False}, req="r-7"))
        self.assertEqual(got, e2ee.Command(sender_key=page.key(), req="r-7", cmd={"type": "set", "video": False}))
        self.assertIsNone(group.open_command(page.command({"type": "set", "video": True}, sender=laptop)),
                          "a command from a device that is not an admin was taken")
        # Made an admin, the same laptop is obeyed: it is the admin rule that refused it.
        page.append_mls(page.m.make_admin(laptop.signature_key()))
        laptop.handle(e2ee.unb64(e2ee.decode_body(log.bodies[-1])["msg"]))
        drive(group, log)
        got = group.open_command(page.command({"type": "set", "video": True}, sender=laptop))
        self.assertEqual(got and got.sender_key, laptop.signature_key())
        for body in ("", "not base64!", e2ee.b64(b"\x00" * 40), page.command({"type": "set"}, req="x" * 65)):
            self.assertIsNone(group.open_command(body))

    def test_a_commit_sent_as_a_command_is_refused_and_still_applies_from_the_log(self):
        log, page, group, _ = joined_device(self)
        tablet = hm.Member(b"tablet")
        commit, _ = page.m.add(tablet.key_package(), tablet.signature_key())
        epoch = group.epoch()
        self.assertIsNone(group.open_command(e2ee.b64(commit)))
        self.assertEqual(group.epoch(), epoch, "a commit sent as a command was applied")
        page.append_mls(commit)
        out = drive(group, log)
        self.assertEqual(group.epoch(), epoch + 1, f"the commit no longer applied from the log: {out}")


@unittest.skipIf(SKIP, "the hm_seal binding is not installed")
class SealingTest(unittest.TestCase):
    def test_nothing_the_device_sends_carries_its_contents_in_the_clear(self):
        log, page, group, _ = joined_device(self)
        self.assertIsNone(group.seal_event({"kind": "reminder", "text": CANARY}), "sealed without a data key")
        self.assertIsNone(group.seal_state({"summary": CANARY}), "sealed without a data key")
        raw = os.urandom(32)
        page.send_data_key(b"K" * 8, raw)
        drive(group, log)
        sent = []
        event = {"kind": "reminder", "text": f"{CANARY} 喝水", "data": {"category": "运动后"}, "at": "2026-11-12T10:00:00Z"}
        body = group.seal_event(event)
        sent.append(body.encode())
        state = {"switches": {"video": True}, "summary": CANARY}
        kept = group.seal_state(state)
        sent.append(kept.encode())
        jpeg = b"\xff\xd8" + CANARY.encode() + b"\xff\xd9"
        frame = group.seal_frame(jpeg)
        sent.append(frame)
        answer = group.seal_message({"t": "result", "req": "r-1", "text": CANARY})
        sent.append(answer.encode())
        sent.extend(b.encode() for b in log.bodies)
        for item in sent:
            for form in (item, _unb64_or_empty(item)):
                self.assertNotIn(CANARY.encode(), form)
                self.assertNotIn("喝水".encode(), form)

        dk = hm.DataKey.from_bytes(raw)
        blob = base64.b64decode(body)
        self.assertEqual(blob[:8], b"K" * 8)
        self.assertEqual(json.loads(dk.open(e2ee.event_purpose(DEVICE_ID), blob[8:])), event)
        with self.assertRaises(hm.SealError, msg="an event opened as another device's"):
            dk.open(e2ee.event_purpose("another-device"), blob[8:])
        with self.assertRaises(hm.SealError, msg="an event opened as the device's state"):
            dk.open(e2ee.state_purpose(DEVICE_ID), blob[8:])
        self.assertEqual(json.loads(dk.open(e2ee.state_purpose(DEVICE_ID), base64.b64decode(kept)[8:])), state)
        self.assertTrue(e2ee.SEALED_EVENT_MIN_CHARS <= len(body) <= e2ee.SEALED_EVENT_MAX_CHARS)

        self.assertEqual(frame[0], 0x01)
        opener = hm.FrameOpener()
        page.m.update_opener(opener)
        self.assertEqual(opener.open(frame[1:], e2ee.frame_meta(DEVICE_ID)), jpeg)
        other = hm.FrameOpener()
        page.m.update_opener(other)
        with self.assertRaises(hm.SealError, msg="a frame opened as another device's"):
            other.open(frame[1:], e2ee.frame_meta("another-device"))
        got = page.m.handle(base64.b64decode(answer))
        self.assertEqual((got[0], got[3]), ("application", group.signature_key()))
        self.assertEqual(json.loads(got[2])["text"], CANARY)

    def test_frames_after_a_removal_use_the_new_epoch(self):
        # After a removal a page drops the previous epoch's frames (the removed device knows its
        # keys), so a sealer kept from before the commit would be refused.
        log, page, group, _ = joined_device(self)
        tablet = hm.Member(b"tablet")
        commit, _ = page.m.add(tablet.key_package(), tablet.signature_key())
        page.append_mls(commit)
        drive(group, log)
        group.seal_frame(b"before")
        leaf = next(leaf for leaf, name in page.m.members() if name == b"tablet")
        page.append_mls(page.m.remove(leaf))
        drive(group, log)
        self.assertEqual(group.epoch(), page.m.epoch())
        opener = hm.FrameOpener()
        page.m.update_opener(opener)
        self.assertEqual(opener.open(group.seal_frame(b"after")[1:], e2ee.frame_meta(DEVICE_ID)), b"after",
                         "a frame after the removal was sealed under the epoch before it")


@unittest.skipIf(SKIP, "the hm_seal binding is not installed")
class LifecycleTest(unittest.TestCase):
    def test_a_device_the_admin_removes_forgets_its_keys(self):
        log, page, group, _ = joined_device(self)
        page.send_data_key(b"K" * 8, os.urandom(32))
        drive(group, log)
        leaf = next(leaf for leaf, name in page.m.members() if name == b"room")
        page.append_mls(page.m.remove(leaf))
        out = drive(group, log)
        self.assertIn(("removed",), out)
        self.assertEqual(group.status, "removed")
        for name in (e2ee.SAVE_FILE, e2ee.KEYS_FILE):
            self.assertFalse(os.path.exists(os.path.join(group.directory, name)), f"{name} was kept after removal")
        self.assertIsNone(group.seal_event({"kind": "reminder", "text": "x"}))
        self.assertIsNone(group.seal_frame(b"jpeg"))
        self.assertIsNone(group.open_command(page.command({"type": "set", "video": True})))
        again = e2ee.DeviceGroup(group.directory, DEVICE_ID)
        self.assertEqual((again.status, again.reason), ("removed", "an admin removed this device"))

    def test_a_restarted_device_goes_on_where_it_was(self):
        log, page, group, _ = joined_device(self)
        page.send_data_key(b"K" * 8, os.urandom(32))
        laptop = hm.Member(b"laptop")
        commit, _ = page.m.add(laptop.key_package(), laptop.signature_key())
        page.append_mls(commit)
        drive(group, log)
        # Restarted right after a commit: the save must already hold it.
        again = e2ee.DeviceGroup(group.directory, DEVICE_ID)
        self.assertEqual((again.status, again.last_seq), ("joined", group.last_seq))
        self.assertEqual(again.epoch(), page.m.epoch(), "the commit before the restart was not saved")
        self.assertTrue(again.has_data_key())
        self.assertEqual(stat.S_IMODE(os.stat(again.directory).st_mode), 0o700)
        for name in (e2ee.SAVE_FILE, e2ee.KEYS_FILE, e2ee.GROUP_FILE):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(again.directory, name)).st_mode), 0o600, name)
        # Restarted right after sending: what it sends next must not reuse what it sent (SecretReuseError).
        first = again.seal_message({"t": "result", "req": "r-1"})
        self.assertEqual(json.loads(page.m.handle(base64.b64decode(first))[2])["req"], "r-1")
        third = e2ee.DeviceGroup(group.directory, DEVICE_ID)
        second = third.seal_message({"t": "result", "req": "r-2"})
        try:
            got = page.m.handle(base64.b64decode(second))
        except hm.SealError as e:
            self.fail(f"the page could not read what the device sent after a restart: {e}")
        self.assertEqual(json.loads(got[2])["req"], "r-2")
        tablet = hm.Member(b"tablet")
        commit, _ = page.m.add(tablet.key_package(), tablet.signature_key())
        page.append_mls(commit)
        drive(third, log)
        self.assertEqual(third.epoch(), page.m.epoch())
        self.assertEqual(third._member.handle(page.m.seal(b"after a restart"))[2], b"after a restart")

    def test_a_damaged_save_turns_encryption_off_until_the_device_is_paired_again(self):
        log, page, group, _ = joined_device(self)
        path = os.path.join(group.directory, e2ee.SAVE_FILE)
        with open(path, "r+b") as f:
            f.seek(100)
            byte = f.read(1)
            f.seek(100)
            f.write(bytes([byte[0] ^ 0xFF]))
        again = e2ee.DeviceGroup(group.directory, DEVICE_ID)
        self.assertEqual(again.status, "broken")
        self.assertIsNone(again.seal_frame(b"jpeg"))
        self.assertIsNone(again.seal_event({"kind": "reminder", "text": "x"}))
        self.assertEqual(again.process(again.last_seq or 1, log.bodies[0]), [])
        page2 = Page(log)
        again.join_sent(log.append(again.start_pairing(page2.code())))
        self.assertEqual(again.status, "joining")


def _unb64_or_empty(item: bytes) -> bytes:
    try:
        return base64.b64decode(item, validate=True)
    except Exception:
        return b""


if __name__ == "__main__":
    unittest.main()
