import json
import os
import tempfile
import time
import unittest

from room_companion import commands
from room_companion.ai import AIGate
from room_companion.events import EventLog
from room_companion.notifiers.feishu import FeishuNotifier
from room_companion.switches import Switches, SwitchWriteError
from room_companion.video import JpegSplitter, MotionTracker, choose_format, parse_formats
from room_companion.web import classify


class SwitchesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "state", "switches.json")

    def test_missing_file_means_all_off(self):
        s = Switches(self.path)
        self.assertEqual([s.get(k) for k in ("video", "audio", "ai")], [False, False, False])
        self.assertIsNotNone(s.load_error)

    def test_garbage_and_non_bool_mean_off(self):
        os.makedirs(os.path.dirname(self.path))
        for body in ("{not json", "[1,2]", json.dumps({"video": "true", "audio": 1, "ai": None})):
            with open(self.path, "w") as f:
                f.write(body)
            s = Switches(self.path)
            self.assertEqual([s.get(k) for k in ("video", "audio", "ai")], [False, False, False], body)

    def test_persist_and_reload(self):
        s = Switches(self.path)
        diff = s.set({"video": True, "ai": True}, "test")
        self.assertEqual(diff, {"video": (False, True), "ai": (False, True)})
        s2 = Switches(self.path)
        self.assertEqual([s2.get(k) for k in ("video", "audio", "ai")], [True, False, True])
        self.assertEqual(s.set({"video": True}, "test"), {})

    def test_turn_on_needs_successful_write_turn_off_does_not(self):
        s = Switches(self.path)
        s.set({"audio": True}, "test")
        s._write = lambda state: (_ for _ in ()).throw(OSError("disk full"))
        with self.assertRaises(SwitchWriteError):
            s.set({"video": True}, "test")
        self.assertFalse(s.get("video"))
        s.set({"audio": False}, "test")
        self.assertFalse(s.get("audio"))

    def test_rejects_unknown_and_non_bool(self):
        s = Switches(self.path)
        with self.assertRaises(ValueError):
            s.set({"camera": True}, "x")
        with self.assertRaises(ValueError):
            s.set({"video": "on"}, "x")


class CommandsTest(unittest.TestCase):
    def check(self, text, expected):
        self.assertEqual(commands.parse(text).get("changes"), expected, text)

    def test_sentences(self):
        self.check("关视频", {"video": False})
        self.check("关掉视频和声音", {"video": False, "audio": False})
        self.check("视频和声音都关掉", {"video": False, "audio": False})
        self.check("关视频开AI", {"video": False, "ai": True})
        self.check("视频关掉，AI打开", {"video": False, "ai": True})
        self.check("视频关掉AI打开", {"video": False, "ai": True})
        self.check("把摄像头打开", {"video": True})
        self.check("隐私模式", {"video": False, "audio": False, "ai": False})
        self.check("全部关闭", {"video": False, "audio": False, "ai": False})
        self.check("全关", {"video": False, "audio": False, "ai": False})
        self.check("恢复声音", {"audio": True})
        self.check("暂停录音", {"audio": False})
        self.check("ai off", {"ai": False})
        self.check("房间助手关视频", {"video": False})
        self.check("房间AI，关视频", {"video": False})

    def test_unclear(self):
        self.assertIn("error", commands.parse("我今天好开心"))
        self.assertIn("error", commands.parse("视频"))
        self.assertIn("error", commands.parse(""))
        self.assertTrue(commands.parse("现在什么状态").get("status"))
        # latin "ai" inside a word is not the AI switch
        self.assertIn("error", commands.parse("wait off"))

    def test_wake_word(self):
        self.assertEqual(commands.strip_wake("房间助手，关视频。", ["房间助手"]), "关视频")
        self.assertIsNone(commands.strip_wake("关视频", ["房间助手"]))
        # misheard wake words seen in real transcripts
        self.assertEqual(commands.strip_wake("放检助手，关视频。", ["房间助手"], "助手"), "关视频")
        self.assertEqual(commands.strip_wake("老年助手关声音", ["房间助手"], "助手"), "关声音")
        self.assertIsNone(commands.strip_wake("我觉得这个助手不错", ["房间助手"], "助手"))
        self.assertIsNone(commands.strip_wake("放检助手关视频", ["房间助手"]))


class WebAuthTest(unittest.TestCase):
    def test_classify(self):
        cidrs = ["100.64.0.0/10", "fd7a:115c:a1e0::/48", "192.168.50.0/24"]
        self.assertEqual(classify("127.0.0.1", cidrs), "local")
        self.assertEqual(classify("::ffff:127.0.0.1", cidrs), "local")
        self.assertEqual(classify("127.0.0.1", cidrs, trust_loopback=False), "deny")
        self.assertEqual(classify("100.101.102.103", cidrs), "remote")
        self.assertEqual(classify("192.168.50.20", cidrs), "remote")
        self.assertEqual(classify("10.1.2.3", cidrs), "deny")
        self.assertEqual(classify("8.8.8.8", cidrs), "deny")
        self.assertEqual(classify("garbage", cidrs), "deny")


class VideoPartsTest(unittest.TestCase):
    LIST = """ioctl: VIDIOC_ENUM_FMT
\tType: Video Capture

\t[0]: 'MJPG' (Motion-JPEG, compressed)
\t\tSize: Discrete 1920x1080
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t\tSize: Discrete 1280x720
\t\t\tInterval: Discrete 0.033s (30.000 fps)
\t[1]: 'YUYV' (YUYV 4:2:2)
\t\tSize: Discrete 1920x1080
\t\t\tInterval: Discrete 0.200s (5.000 fps)
"""

    def test_formats(self):
        f = parse_formats(self.LIST)
        self.assertIn(("MJPG", 1920, 1080, 30.0), f)
        self.assertEqual(choose_format(f), ("MJPG", 1920, 1080, 30.0))
        self.assertEqual(choose_format(f, max_width=1280), ("MJPG", 1280, 720, 30.0))
        # raw 1080p over USB 2.0 is refused, nothing else left
        self.assertIsNone(choose_format([("YUYV", 1920, 1080, 5.0)]))

    def test_jpeg_splitter_across_chunks(self):
        a = b"\xff\xd8" + b"A" * 10 + b"\xff\xd9"
        b = b"\xff\xd8" + b"B" * 10 + b"\xff\xd9"
        sp = JpegSplitter()
        data = b"junk" + a + b
        out = []
        for i in range(0, len(data), 3):
            out += sp.feed(data[i:i + 3])
        self.assertEqual(out, [a, b])

    def test_motion(self):
        ev = EventLog(tempfile.mkdtemp())
        m = MotionTracker(ev, threshold=6.0, quiet_seconds=5)
        m.feed(bytes([10]) * 2304, now=100)
        m.feed(bytes([10]) * 2304, now=101)
        self.assertIsNone(m.active_since)
        m.feed(bytes([60]) * 2304, now=102)
        self.assertIsNotNone(m.active_since)
        m.feed(bytes([60]) * 2304, now=110)
        self.assertIsNone(m.active_since)
        kinds = [e["kind"] for e in ev.latest()]
        self.assertEqual(kinds, ["motion_start", "motion_end"])


class FindVideoTest(unittest.TestCase):
    def test_prefers_osmo_over_builtin_webcam(self):
        from unittest import mock
        from room_companion import devices
        root = tempfile.mkdtemp()
        sysv4l = os.path.join(root, "sys")
        # video0: built-in webcam listed first; video2: Osmo Action 5 Pro (05c6:8004)
        for node, name, vendor in (("video0", "HD Webcam", "5986"), ("video2", "OsmoAction5pro", "05c6")):
            usb = os.path.join(root, "usb", node)
            os.makedirs(os.path.join(usb, "intf"))
            with open(os.path.join(usb, "idVendor"), "w") as f:
                f.write(vendor + "\n")
            os.makedirs(os.path.join(sysv4l, node))
            with open(os.path.join(sysv4l, node, "name"), "w") as f:
                f.write(name + "\n")
            os.symlink(os.path.join(usb, "intf"), os.path.join(sysv4l, node, "device"))
        with mock.patch.object(devices, "SYS_V4L", sysv4l), \
                mock.patch.object(devices, "ensure_node", lambda *a: True), \
                mock.patch.object(devices, "_is_capture", lambda p: True):
            self.assertEqual(devices.find_video(dev_root="/dev").path, "/dev/video2")
            self.assertEqual(devices.find_video("05c6", dev_root="/dev").vendor, "05c6")
            # nothing preferred and no Osmo name: first capture node
            with open(os.path.join(sysv4l, "video2", "name"), "w") as f:
                f.write("Other Cam\n")
            self.assertEqual(devices.find_video("abcd", dev_root="/dev").path, "/dev/video0")


class AIGateTest(unittest.TestCase):
    def test_off_never_reaches_client(self):
        s = Switches(os.path.join(tempfile.mkdtemp(), "s.json"))
        calls = []

        class Client:
            def send(self, kind, payload):
                calls.append(kind)

        g = AIGate(s, Client())
        self.assertFalse(g.submit("frame", b"x"))
        s.set({"ai": True}, "t")
        self.assertTrue(g.submit("frame", b"x"))
        s.set({"ai": False}, "t")
        self.assertFalse(g.submit("transcript", "hi"))
        self.assertEqual(calls, ["frame"])
        self.assertEqual(g.dropped_off, 2)


class EventsTest(unittest.TestCase):
    def test_retention(self):
        d = tempfile.mkdtemp()
        ev = EventLog(d, retention_days=30)
        for day in ("2026-01-01", time.strftime("%Y-%m-%d")):
            open(os.path.join(d, day + ".jsonl"), "w").close()
        ev.purge()
        self.assertEqual(sorted(os.listdir(d)), [time.strftime("%Y-%m-%d") + ".jsonl"])

    def test_no_text_on_disk(self):
        d = tempfile.mkdtemp()
        ev = EventLog(d)
        ev.add("speech", seconds=1.2)
        with open(os.path.join(d, time.strftime("%Y-%m-%d") + ".jsonl")) as f:
            self.assertEqual(json.loads(f.read())["seconds"], 1.2)


class NotifyTest(unittest.TestCase):
    def test_token_then_message(self):
        calls = []

        def post(url, body, headers):
            calls.append((url, body, headers))
            if "tenant_access_token" in url:
                return {"code": 0, "tenant_access_token": "t-abc", "expire": 7200}
            return {"code": 0}

        n = FeishuNotifier("cli_x", "sec", "ou_x", post=post)
        self.assertTrue(n.send_now("你好"))
        self.assertTrue(n.send_now("再来"))
        self.assertEqual(len(calls), 3)  # token cached
        self.assertEqual(calls[1][2]["Authorization"], "Bearer t-abc")
        self.assertEqual(json.loads(calls[1][1]["content"])["text"], "你好")

    def test_unconfigured_does_not_send(self):
        n = FeishuNotifier(None, None, None, post=lambda *a: self.fail("must not post"))
        self.assertFalse(n.send_now("x"))


if __name__ == "__main__":
    unittest.main()
