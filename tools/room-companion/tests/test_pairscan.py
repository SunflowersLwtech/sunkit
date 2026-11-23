"""Reading the owner's pairing code with the camera (`e2ee-pair --scan`, room_companion/pairscan.py and the
connector's scan window, docs/e2ee.md): QR codes made here with the decoder's own writer, pasted into a room
frame and served through the same local snapshot that live video reads.

Needs zxing-cpp, Pillow, websockets and the hm_seal binding; skipped without them, unless HM_SEAL_REQUIRED=1
(as in CI, which installs the scan extra too), when it fails instead.
"""
import asyncio
import contextlib
import io
import json
import logging
import os
import shutil
import stat
import tempfile
import time
import unittest
from unittest import mock

from room_companion import e2ee, pairscan
from room_companion import hipimind as hm
from tests import test_hipimind_e2ee as connector  # not its TestCase by name: discovery would run it twice

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = ImageDraw = None

zx = pairscan.zxingcpp
SKIP = (zx is None or Image is None or e2ee.hm_seal is None or connector.websockets is None) \
    and os.environ.get("HM_SEAL_REQUIRED") != "1"
OTHER = "https://example.com/menu?table=4"


def qr(text: str, scale: int = 4):
    barcode = zx.create_barcode(text, zx.BarcodeFormat.QRCode)
    return Image.fromarray(zx.write_barcode_to_image(barcode, scale=scale)).convert("RGB")


def room_frame(*texts: str, size=(1280, 720), scale=4) -> bytes:
    """A JPEG like a camera's: a room with some clutter, and a QR code for each text, side by side."""
    im = Image.new("RGB", size, (88, 78, 66))
    draw = ImageDraw.Draw(im)
    for i in range(12):
        draw.rectangle((60 * i, size[1] - 160 + (i % 3) * 20, 60 * i + 45, size[1] - 20), fill=(30 + 15 * i, 120, 90))
    x = 40
    for text in texts:
        code = qr(text, scale)
        im.paste(code, (x, 60))
        x += code.width + 40
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    return buf.getvalue()


def a_code() -> str:
    return e2ee.pairing_code(os.urandom(e2ee.SECRET_BYTES), os.urandom(e2ee.SIGNATURE_KEY_BYTES))


def damaged_codes(code: str) -> list[str]:
    body = code[len(e2ee.PAIRING_PREFIX):]
    return ["hmroom2." + body, code[:-1], code[:-1] + "+", body]


@unittest.skipIf(SKIP, "zxing-cpp, Pillow, websockets or the hm_seal binding is not installed")
class ReadTest(unittest.TestCase):
    def test_a_code_in_a_room_frame_is_read_exactly(self):
        code = a_code()
        self.assertEqual(pairscan.pairing_code_in(room_frame(code)), (code, 0))

    def test_other_qr_codes_and_damaged_codes_are_ignored_and_counted(self):
        code = a_code()
        others = [OTHER] + damaged_codes(code)
        for text in others:
            self.assertEqual(pairscan.pairing_code_in(room_frame(text)), (None, 1), text)
        self.assertEqual(pairscan.pairing_code_in(room_frame(OTHER, code)), (code, 1))

    def test_a_large_frame_is_read_scaled_down_no_further_than_1920(self):
        # Three pixels a module in 4K: still readable at 1920 wide, no longer at 960 (measured).
        code = a_code()
        self.assertEqual(pairscan.pairing_code_in(room_frame(code, size=(3840, 2160), scale=3)), (code, 0))

    def test_a_frame_that_is_not_a_picture_holds_no_code(self):
        self.assertEqual(pairscan.pairing_code_in(b"\xff\xd8" + b"\x00" * 64), (None, 0))
        self.assertEqual(pairscan.pairing_code_in(b""), (None, 0))

    def test_without_the_decoder_nothing_is_read(self):
        with mock.patch.object(pairscan, "zxingcpp", None):
            self.assertFalse(pairscan.available())
            self.assertEqual(pairscan.pairing_code_in(room_frame(a_code())), (None, 0))


@unittest.skipIf(SKIP, "zxing-cpp, Pillow, websockets or the hm_seal binding is not installed")
class CommandTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.e2ee_dir = os.path.join(self.dir, "e2ee")
        self.app_cfg = {"hipimind": {"e2ee": {"enabled": True, "dir": self.e2ee_dir}}}
        self.window = os.path.join(self.e2ee_dir, hm.PAIRING_SCAN_FILE)
        self.code_file = os.path.join(self.e2ee_dir, hm.PAIRING_CODE_FILE)

    def run_pair(self, *argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = hm.e2ee_pair_from_app_config(list(argv), self.app_cfg)
        return rc, out.getvalue(), err.getvalue()

    def test_scan_opens_a_window_of_two_minutes_readable_only_by_this_user(self):
        before = time.time()
        rc, out, _ = self.run_pair("--scan")
        self.assertEqual(rc, 0)
        self.assertIn("Video has to be on", out)
        self.assertIn("--code", out)
        with open(self.window, encoding="utf-8") as f:
            until = json.load(f)["until"]
        self.assertTrue(before + 120 <= until <= time.time() + 120, until - before)
        self.assertEqual(stat.S_IMODE(os.stat(self.window).st_mode), 0o600)
        self.assertFalse(os.path.exists(self.code_file))

    def test_the_window_has_bounds(self):
        for seconds in ("9", "601"):
            rc, _, err = self.run_pair("--scan", "--seconds", seconds)
            self.assertEqual(rc, 2, seconds)
            self.assertIn("between 10 and 600", err)
        self.assertFalse(os.path.exists(self.window))
        rc, _, _ = self.run_pair("--scan", "--seconds", "30")
        self.assertEqual(rc, 0)

    def test_code_and_scan_are_one_or_the_other(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.run_pair("--scan", "--code", a_code())
            with self.assertRaises(SystemExit):
                self.run_pair()
        rc, _, err = self.run_pair("--code", a_code(), "--seconds", "30")
        self.assertEqual(rc, 2)
        self.assertIn("--seconds goes with --scan", err)

    def test_without_the_decoder_scan_points_at_code(self):
        with mock.patch.object(pairscan, "zxingcpp", None):
            rc, _, err = self.run_pair("--scan")
        self.assertEqual(rc, 2)
        self.assertIn("pip install 'room-companion[scan]'", err)
        self.assertIn("--code", err)
        self.assertFalse(os.path.exists(self.window))

    def test_scan_needs_encryption_on(self):
        self.app_cfg["hipimind"]["e2ee"]["enabled"] = False
        rc, _, err = self.run_pair("--scan")
        self.assertEqual(rc, 2)
        self.assertIn("encryption is off", err)
        self.assertFalse(os.path.exists(self.window))

    def test_the_code_text_closes_an_open_window(self):
        self.assertEqual(self.run_pair("--scan")[0], 0)
        code = a_code()
        self.assertEqual(self.run_pair("--code", code)[0], 0)
        self.assertFalse(os.path.exists(self.window), "the camera kept looking after the code was given")
        with open(self.code_file, encoding="utf-8") as f:
            self.assertEqual(f.read(), code)

    def test_the_sidecar_command_scans_too(self):
        path = os.path.join(self.dir, "hipimind.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.app_cfg["hipimind"], f)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(hm.main(["e2ee-pair", "--config", path, "--scan", "--seconds", "60"]), 0)
        with open(self.window, encoding="utf-8") as f:
            self.assertLessEqual(json.load(f)["until"], time.time() + 60)


class _Camera:
    """A device whose camera only counts how often it is read."""

    def __init__(self, jpeg: bytes):
        self.jpeg, self.reads = jpeg, 0

    def snapshot(self):
        self.reads += 1
        return self.jpeg


@unittest.skipIf(SKIP, "zxing-cpp, Pillow, websockets or the hm_seal binding is not installed")
class EncryptionOffTest(unittest.IsolatedAsyncioTestCase):
    async def test_with_encryption_off_a_window_is_not_scanned(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        e2ee_dir = os.path.join(d, "e2ee")
        cfg = hm.load_config_dict({"server": "http://127.0.0.1", "token_file": os.path.join(d, "token"),
                                   "e2ee": {"enabled": False, "dir": e2ee_dir}})
        camera = _Camera(room_frame(a_code()))
        bridge = hm.Bridge(cfg, device=camera)
        bridge.state = {"switches": {"video": True, "audio": False, "ai": False}}
        window = os.path.join(e2ee_dir, hm.PAIRING_SCAN_FILE)
        hm.write_secret(window, json.dumps({"until": time.time() + 60}))
        await bridge._scan_for_pairing_code()
        self.assertEqual(camera.reads, 0)
        self.assertFalse(os.path.exists(os.path.join(e2ee_dir, hm.PAIRING_CODE_FILE)))
        # Control: the same bridge with encryption on reads the camera and leaves the code.
        bridge.e2ee_on = True
        await bridge._scan_for_pairing_code()
        self.assertEqual(camera.reads, 1)
        self.assertTrue(os.path.exists(os.path.join(e2ee_dir, hm.PAIRING_CODE_FILE)))


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@unittest.skipIf(SKIP, "zxing-cpp, Pillow, websockets or the hm_seal binding is not installed")
class ScanBridgeTest(unittest.IsolatedAsyncioTestCase):
    """The connector with encryption on, scanning the camera through the local snapshot."""

    asyncSetUp = connector.EncryptedBridgeTest.asyncSetUp
    asyncTearDown = connector.EncryptedBridgeTest.asyncTearDown
    until = connector.EncryptedBridgeTest.until
    find = connector.EncryptedBridgeTest.find
    welcomed = connector.EncryptedBridgeTest.welcomed
    paired = connector.EncryptedBridgeTest.paired

    def setUp(self):
        self.records = _Records()
        logger = logging.getLogger("room_companion")
        level = logger.level
        logger.addHandler(self.records)
        logger.setLevel(logging.INFO)
        self.addCleanup(logger.setLevel, level)
        self.addCleanup(logger.removeHandler, self.records)

    @property
    def window(self) -> str:
        return os.path.join(self.cfg["e2ee"]["dir"], hm.PAIRING_SCAN_FILE)

    def video(self, on: bool):
        self.local.status["switches"]["video"] = on
        self.local.status["video"]["state"] = "running" if on else "off"

    def joins(self) -> list[dict]:
        return [m for m in self.hub.messages if isinstance(m, dict) and m.get("type") == "group"
                and (e2ee.decode_body(m.get("body")) or {}).get("t") == "join"]

    def said(self, text: str) -> int:
        return sum(text in line for line in self.records.lines)

    def assert_secret_kept(self, *codes: str):
        logs, wire = "\n".join(self.records.lines), self.hub.text()
        for code in codes:
            for part in (code, code[len(e2ee.PAIRING_PREFIX):]):
                self.assertNotIn(part, logs, "a code's text was logged")
                self.assertNotIn(part, wire, "a code's text went to HipiMind")

    def assert_no_frame_on_disk(self):
        for root, _, files in os.walk(self.cfg["e2ee"]["dir"]):
            for name in files:
                with open(os.path.join(root, name), "rb") as f:
                    self.assertFalse(f.read(2) == b"\xff\xd8", f"a frame was written to {name}")

    async def test_the_camera_reads_the_code_and_the_device_joins_as_with_the_text(self):
        await self.welcomed()
        self.video(True)
        code = self.page.code()
        self.local.jpeg = room_frame(OTHER, code)
        hm.open_pairing_scan(self.cfg, 120)
        join = await self.find(lambda m: m in self.joins())
        self.assertIn(e2ee.unb64(e2ee.decode_body(join["body"])["id"]), self.page.codes,
                      "the join request answers another code")
        await self.until(lambda: self.bridge.group.last_seq is not None, what="the join request's number")
        self.page.answer_joins()  # checks the MAC the code's secret made
        await self.hub.push_new()
        await self.until(lambda: self.bridge.group.status == "joined", what="joining")
        self.assertFalse(os.path.exists(self.window), "the window stayed open after the code was read")
        self.assertFalse(os.path.exists(os.path.join(self.cfg["e2ee"]["dir"], hm.PAIRING_CODE_FILE)),
                         "the code was kept after it was used")
        self.assertEqual(self.said("the camera read a pairing code"), 1)
        self.assertEqual(self.said("not a HipiMind pairing code was ignored"), 1)
        self.assertEqual(len(self.joins()), 1)
        self.assert_secret_kept(code)
        self.assert_no_frame_on_disk()

    async def test_with_video_off_the_camera_is_not_read(self):
        await self.welcomed()
        self.local.jpeg = room_frame(self.page.code())
        hm.open_pairing_scan(self.cfg, 120)
        await asyncio.sleep(1.0)  # about ten polls
        self.assertEqual(self.local.snapshots, 0, "the camera was read while video was off")
        self.assertEqual(self.joins(), [])
        self.assertEqual(self.said("video is off, so the camera is not read"), 1)
        # Control: with video on, the same window reads the same code.
        self.video(True)
        await self.find(lambda m: m in self.joins())
        self.assertGreater(self.local.snapshots, 0)

    async def test_other_codes_are_ignored_until_the_window_ends(self):
        await self.welcomed()
        self.video(True)
        code = self.page.code()
        others = [OTHER] + damaged_codes(code)
        self.local.jpeg = room_frame(*others[:3])
        hm.open_pairing_scan(self.cfg, 1)
        await self.until(lambda: not os.path.exists(self.window), what="the window ending")
        self.assertGreater(self.local.snapshots, 0, "control: the camera was read")
        self.assertEqual(self.joins(), [])
        self.assertFalse(os.path.exists(os.path.join(self.cfg["e2ee"]["dir"], hm.PAIRING_CODE_FILE)))
        self.assertEqual(self.said("no pairing code was seen before the window ended"), 1)
        self.assertEqual(self.said("not a HipiMind pairing code was ignored"), 1)
        # After the window, the camera is not read for a code any more.
        seen = self.local.snapshots
        self.local.jpeg = room_frame(code)
        await asyncio.sleep(0.6)
        self.assertEqual((self.local.snapshots, self.joins()), (seen, []))
        self.assert_secret_kept(code, *others)

    async def test_a_device_in_a_group_does_not_look(self):
        await self.welcomed()
        await self.paired()
        self.video(True)
        self.local.jpeg = room_frame(self.page.code())
        seen = self.local.snapshots
        hm.open_pairing_scan(self.cfg, 120)
        await self.until(lambda: not os.path.exists(self.window), what="the window being closed")
        await asyncio.sleep(0.3)
        self.assertEqual(self.local.snapshots, seen)
        self.assertEqual(self.said("already in a group"), 1)
        self.assertEqual(len(self.joins()), 1, "a device in a group asked to join again")
        self.assertEqual(self.bridge.group.status, "joined")

    async def test_without_the_decoder_the_window_closes_and_says_so(self):
        await self.welcomed()
        self.video(True)
        self.local.jpeg = room_frame(self.page.code())
        with mock.patch.object(pairscan, "zxingcpp", None):
            hm.open_pairing_scan(self.cfg, 120)
            await self.until(lambda: not os.path.exists(self.window), what="the window being closed")
        self.assertEqual(self.local.snapshots, 0)
        self.assertEqual(self.said("use e2ee-pair --code"), 1)
        self.assertEqual(self.joins(), [])

    async def test_a_damaged_window_is_closed(self):
        await self.welcomed()
        self.video(True)
        self.local.jpeg = room_frame(self.page.code())
        hm.write_secret(self.window, json.dumps({"until": "soon"}))
        await self.until(lambda: not os.path.exists(self.window), what="the window being closed")
        self.assertEqual((self.local.snapshots, self.joins()), (0, []))
        self.assertEqual(self.said("could not be read; start it again"), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
