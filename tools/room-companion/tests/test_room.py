import json
import os
import tempfile
import time
import unittest

from room_companion.ai import AIGate
from room_companion.app import DEFAULTS, App, parse_nvidia_smi
from room_companion.events import EventLog
from room_companion.policy import Policy, parse_policy_command
from room_companion.switches import Switches
from room_companion.vision import LlamaServer, parse_observation
from room_companion.windows import parse_consent, parse_dshow_devices, parse_dshow_formats, parse_tasklist_csv
from tests.fakes import FakeNotifier


def at(hh, mm=0, day=25):
    return time.mktime((2026, 10, day, hh, mm, 0, 0, 0, -1))


def obs(scene, **kw):
    d = {"person": scene != "empty", "scene": scene, "hot_oil": False, "on_phone_call": False, "note": ""}
    d.update(kw)
    return d


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.said = []
        self.p = Policy(os.path.join(tempfile.mkdtemp(), "policy.json"), {}, lambda t, c, sp: self.said.append((c, t, sp)))
        self.p.set_context(True, 0.0)

    def feed(self, scene, start, minutes, step=1, **kw):
        t = start
        for _ in range(int(minutes / step) + 1):
            self.p.observe(obs(scene, **kw), t)
            t += step * 60
        return t

    def test_coding_reminder_waits_for_a_two_minute_break(self):
        t = self.feed("coding", at(14), 95)
        self.assertEqual(self.said, [], "never interrupts while coding")
        self.assertIn("久坐", self.p.pending)
        self.p.observe(obs("other"), t)
        self.p.observe(obs("other"), t + 30)        # scene switches to other
        self.assertEqual(self.said, [], "not before 2 minutes off the keyboard")
        self.p.observe(obs("other"), t + 150)
        self.assertEqual([c for c, _, _ in self.said], ["久坐"])

    def test_quiet_hours_sleep_and_empty_room_say_nothing(self):
        self.feed("sofa_phone", at(23, 5), 60)        # quiet hours
        self.feed("sofa_phone", at(7, 0, day=26), 50)  # still quiet before 08:00
        self.assertEqual(self.said, [])
        self.p.state["delivered"] = []
        p2 = Policy(os.path.join(tempfile.mkdtemp(), "p.json"), {}, lambda *a: self.said.append(a))
        p2.set_context(True, 0.0)
        t = at(15)
        for i in range(40):
            p2.observe(obs("empty"), t + i * 60)
            p2.tick(t + i * 60)
        self.assertEqual(self.said, [], "an empty room gets no reminders")
        self.assertEqual(p2.why_not(t + 2400), "房间里没人")

    def test_pending_reminder_waits_while_room_is_empty(self):
        t = self.feed("laundry", at(16), 3)
        t = self.feed("empty", t, 3)                   # the room is empty now; laundry timer still running
        for i in range(0, 50 * 60, 60):
            self.p.observe(obs("empty"), t + i)
            self.p.tick(t + i)
        self.assertIn("晾衣服", self.p.pending, "queued, but not said to an empty room")
        self.assertEqual(self.said, [])
        self.feed("other", t + 50 * 60, 2)             # someone is back
        self.assertEqual([c for c, _, _ in self.said], ["晾衣服"])

    def test_talking_phone_call_hot_oil_and_yoga_defer(self):
        self.p.set_context(True, at(15))                          # speech was heard a few seconds ago
        self.p._queue("手机", "x", at(15))
        self.p.observe(obs("other"), at(15) + 10)
        self.assertEqual(self.said, [])
        self.p.set_context(True, 0.0)
        self.p.observe(obs("other", on_phone_call=True), at(15, 3))
        self.assertEqual(self.said, [])
        self.p.observe(obs("cooking", hot_oil=True), at(15, 4))
        self.assertEqual(self.said, [])
        self.p.observe(obs("other"), at(15, 6))
        self.assertEqual([c for c, _, _ in self.said], ["手机"])

    def test_daily_cap_and_once_per_kind(self):
        t = at(10)
        self.p.observe(obs("other"), t)
        for i, cat in enumerate(["久坐", "路由器", "手机", "晾衣服", "厨房", "运动后", "久坐"]):
            self.p._queue(cat, cat, t)
            self.p.tick(t + 300 * (i + 1))
        self.p._queue("extra", "x", t)
        self.p.tick(t + 4000)
        cats = [c for c, _, _ in self.said]
        self.assertEqual(len(cats), 6)
        self.assertEqual(cats.count("久坐"), 1)
        self.assertNotIn("extra", cats)

    def test_no_today_and_never_again(self):
        t = at(10)
        self.p.observe(obs("other"), t)
        self.p._queue("手机", "看手机", t)
        self.p.tick(t + 10)
        self.assertIsNone(self.p.on_reply("今天天气不错", within_s=180, now=t + 30))
        self.assertIn("今天", self.p.on_reply("不用了", within_s=180, now=t + 30))
        self.assertIn("手机", self.p.state["suppress_today"])
        self.p._queue("手机", "again", t + 60)
        self.assertNotIn("手机", self.p.pending)
        self.p._queue("厨房", "关火", t + 60)
        self.p.tick(t + 70)
        self.assertIn("以后", self.p.on_reply("别再提醒这个", within_s=180, now=t + 80))
        self.assertIn("厨房", self.p.state["suppress_forever"])
        # the next day: today's "不用" is gone, the permanent one stays (and is persisted)
        p2 = Policy(self.p.path, {}, lambda *a: None)
        p2.set_context(True, 0.0)
        p2.observe(obs("other"), at(10, day=26))
        self.assertEqual(p2.state["suppress_today"], [])
        self.assertIn("厨房", p2.state["suppress_forever"])
        # a reply long after the reminder does not count by voice
        self.assertIsNone(self.p.on_reply("不用", within_s=180, now=t + 3600))

    def test_laundry_timer_and_after_activity_reminders(self):
        t = self.feed("laundry", at(16), 3)
        t = self.feed("other", t, 2)
        self.p.tick(t + 45 * 60)
        self.assertIn("晾衣服", [c for c, _, _ in self.said])
        t2 = self.feed("yoga", t + 50 * 60, 15)
        self.assertNotIn("运动后", [c for c, _, _ in self.said])
        self.feed("other", t2, 3)
        self.assertIn("运动后", [c for c, _, _ in self.said])

    def test_debounce_one_odd_frame_does_not_switch_scene(self):
        self.p.observe(obs("coding"), at(14))
        self.p.observe(obs("coding"), at(14, 1))
        self.p.observe(obs("sleeping"), at(14, 2))
        self.assertEqual(self.p.scene, "coding")
        self.p.observe(obs("sleeping"), at(14, 3))
        self.assertEqual(self.p.scene, "sleeping")

    def test_morning_summary_once(self):
        self.feed("coding", at(14, day=24), 120)
        self.feed("sleeping", at(23, 30, day=24), 10)
        self.feed("other", at(8, 10), 2)
        self.p.tick(at(8, 31))
        self.p.tick(at(8, 45))
        summaries = [t for c, t, _ in self.said if c == "早报"]
        self.assertEqual(len(summaries), 1)
        self.assertIn("写代码", summaries[0])
        self.assertIn("23:3", summaries[0])  # sleep is noted once two frames agree

    def test_ai_off_says_nothing(self):
        self.p.set_context(False, 0.0)
        self.p.observe(obs("other"), at(10))
        self.p._queue("手机", "x", at(10))
        self.p.tick(at(10, 5))
        self.p.tick(at(8, 40, day=26))
        self.assertEqual(self.said, [])

    def test_quiet_mode_does_not_speak(self):
        self.p.set_mode("quiet")
        self.p.observe(obs("other"), at(10))
        self.p._queue("手机", "x", at(10))
        self.p.tick(at(10, 1))
        self.assertEqual(self.said[0][2], False)

    def test_policy_commands(self):
        self.assertEqual(parse_policy_command("安静模式"), ("mode", "quiet"))
        self.assertEqual(parse_policy_command("恢复提醒"), ("reset",))
        self.assertIsNone(parse_policy_command("关视频"))


class VisionTest(unittest.TestCase):
    def test_parse_observation(self):
        o = parse_observation(json.dumps({"person": True, "scene": "coding", "hot_oil": "yes", "on_phone_call": False, "note": "写代码"}))
        self.assertEqual((o["scene"], o["hot_oil"]), ("coding", False))
        self.assertEqual(parse_observation(json.dumps({"person": False, "scene": "coding"}))["scene"], "empty")
        self.assertIsNone(parse_observation("not json"))
        self.assertIsNone(parse_observation(json.dumps({"scene": "dancing"})))

    def test_server_backs_off_after_crash(self):
        starts = []

        class Proc:
            pid, returncode = 1, 1
            stderr = []

            def poll(self):
                return 1

            def terminate(self):
                pass

            def wait(self, t=None):
                return 1

        srv = LlamaServer({"exe": "x", "model": "m", "mmproj": "p", "key_file_win": "k"}, EventLog(tempfile.mkdtemp()),
                          popen=lambda *a, **k: starts.append(1) or Proc())
        srv.ensure(True)
        srv.ensure(True)   # sees the crash
        srv.ensure(True)   # must not restart right away
        self.assertEqual(len(starts), 1)
        self.assertEqual(srv.state, "error")
        srv.ensure(False)
        self.assertEqual(srv.state, "off")


class WindowsParsersTest(unittest.TestCase):
    def test_devices_and_formats(self):
        devs = parse_dshow_devices('[in#0 @ 0] "HD Webcam" (video)\n[in#0 @ 0]   Alternative name "@x"\n'
                                   '[in#0 @ 0] "OsmoAction5pro" (video)\n[in#0 @ 0] "Microphone (OsmoAction5pro)" (audio)\n')
        self.assertEqual([(d.name, d.kind) for d in devs],
                         [("HD Webcam", "video"), ("OsmoAction5pro", "video"), ("Microphone (OsmoAction5pro)", "audio")])
        f = parse_dshow_formats("vcodec=mjpeg  min s=1920x1080 fps=25 max s=1920x1080 fps=30\n"
                                "vcodec=h264  min s=1280x720 fps=25 max s=1280x720 fps=30 (tv, bt709)\n")
        self.assertIn(("MJPG", 1920, 1080, 30.0), f)
        self.assertIn(("H264", 1280, 720, 30.0), f)

    def test_nvidia_smi(self):
        self.assertEqual(parse_nvidia_smi("52, 9.34, 4453\r\n"), {"temp_c": 52, "power_w": 9.3, "mem_mb": 4453})
        self.assertIsNone(parse_nvidia_smi(""))

    def test_tasklist_and_consent(self):
        self.assertEqual(parse_tasklist_csv('"ffmpeg.exe","4242","Console","1","35,676 K"\n"other.exe","1","C","1","1 K"', "ffmpeg.exe"), [4242])
        self.assertEqual(parse_tasklist_csv("INFO: No tasks are running which match the specified criteria.", "ffmpeg.exe"), [])
        reg = ("HKEY_CURRENT_USER\\X\\NonPackaged\\C:#old#ffmpeg.exe\n    LastUsedTimeStart    REG_QWORD    0x1d000000000000\n"
               "    LastUsedTimeStop    REG_QWORD    0x1d000000000001\n\n"
               "HKEY_CURRENT_USER\\X\\NonPackaged\\C:#pkg#full_build#bin#ffmpeg.exe\n    LastUsedTimeStart    REG_QWORD    0x1dc0123456789ab\n"
               "    LastUsedTimeStop    REG_QWORD    0x0\n")
        u = parse_consent(reg, "full_build#bin#ffmpeg.exe")
        self.assertTrue(u["in_use"])
        self.assertIsNone(u["stop"])
        self.assertFalse(parse_consent(reg, "#old#ffmpeg.exe")["in_use"])


class FakeServer:
    def __init__(self):
        self.want, self.state, self.proc = None, "off", None

    def ensure(self, want):
        self.want = want
        self.state = "ready" if want else "off"

    def ready(self):
        return self.state == "ready"

    def status(self):
        return {"state": self.state}

    def stop(self):
        self.state = "off"


class FakeClient:
    def __init__(self, scene="empty"):
        self.asked = 0
        self.scene = scene

    def send(self, kind, payload):
        return None

    def ask(self, kind, payload):
        self.asked += 1
        return obs(self.scene)


class Pipe:
    """Minimal stand-in for a capture pipeline."""

    def __init__(self, state="off"):
        self.state, self.proc, self.device, self.last_speech_at = state, None, None, 0.0
        self.waiting_since = None
        self.muted_until = {}

        class M:
            last_motion, active_since = 0.0, None

        self.motion = M()

    def latest(self):
        return (b"\xff\xd8jpeg\xff\xd9", 1) if self.state == "running" else (None, 1)

    def start(self): pass
    def poke(self): pass
    def shutdown(self): pass
    def status(self): return {"state": self.state}


class ObserverTest(unittest.TestCase):
    def make(self, scene="empty"):
        cfg = dict(DEFAULTS, data_dir=tempfile.mkdtemp())
        self.client, self.server, self.notifier = FakeClient(scene), FakeServer(), FakeNotifier()
        app = App(cfg, video=Pipe("running"), audio=Pipe(), notifier=self.notifier, ai_client=self.client,
                  model_server=self.server)
        return app

    def test_model_runs_only_with_ai_and_video_on(self):
        app = self.make()
        app.switches.set({"video": True}, "t")
        app.observe_once(now=at(15))
        self.assertFalse(self.server.want, "AI off: the model is not started")
        self.assertEqual(self.client.asked, 0)
        app.switches.set({"ai": True}, "t")
        app.observe_once(now=at(15, 1))
        self.assertTrue(self.server.want)
        self.assertEqual(self.client.asked, 1)
        app.switches.set({"ai": False}, "t")
        app.observe_once(now=at(15, 30))
        self.assertFalse(self.server.want, "AI off again: the model is stopped")
        self.assertEqual(self.client.asked, 1)

    def test_empty_room_half_hour_no_push(self):
        app = self.make("empty")
        app.switches.set({"video": True, "ai": True}, "t")
        sent_before = len(self.notifier.messages)
        for i in range(0, 31 * 60, 5):
            app.observe_once(now=at(15) + i)
        self.assertGreater(self.client.asked, 3)
        self.assertEqual(len(self.notifier.messages), sent_before, "no reminders in an empty room")

    def test_gpu_too_hot_pauses_model(self):
        cfg = dict(DEFAULTS, data_dir=tempfile.mkdtemp())
        temps = [70, 88]
        self.client, self.server, self.notifier = FakeClient(), FakeServer(), FakeNotifier()
        app = App(cfg, video=Pipe("running"), audio=Pipe(), notifier=self.notifier, ai_client=self.client,
                  model_server=self.server, gpu_query=lambda: {"temp_c": temps.pop(0), "power_w": 40.0, "mem_mb": 4400})
        app.switches.set({"video": True, "ai": True}, "t")
        app.observe_once(now=at(15))            # starts the model
        app.observe_once(now=at(15, 1))         # 70 C: fine
        self.assertTrue(self.server.want)
        app.observe_once(now=at(15, 7))         # 88 C: pause
        app.observe_once(now=at(15, 8))
        self.assertFalse(self.server.want, "model stopped while hot")
        self.assertIn("显卡", self.notifier.messages[-1])
        app.observe_once(now=at(15, 40))        # 30 minutes later it may run again
        self.assertTrue(self.server.want)

    def test_camera_tap_reminder_once(self):
        app = self.make()
        app.video.state, app.video.waiting_since = "waiting_device", at(15)
        app.switches.set({"video": True}, "t")
        n = len(self.notifier.messages)
        app.observe_once(now=at(15, 1))
        self.assertEqual(len(self.notifier.messages), n)
        app.observe_once(now=at(15, 4))
        app.observe_once(now=at(15, 6))
        self.assertEqual(len(self.notifier.messages), n + 1)
        self.assertIn("网络摄像头", self.notifier.messages[-1])

    def test_voice_mode_change_needs_wake_word_but_reply_does_not(self):
        app = self.make()
        app.switches.set({"ai": True}, "t")
        app.on_transcript("我们安静模式聊天吧")
        self.assertEqual(app.policy.state["mode"], "balanced")
        app.on_transcript("房间助手，安静模式")
        self.assertEqual(app.policy.state["mode"], "quiet")
        app.policy.state["delivered"].append({"t": time.time(), "cat": "手机"})
        app.on_transcript("不用了")
        self.assertIn("手机", app.policy.state["suppress_today"])


class AIGateAskTest(unittest.TestCase):
    def test_ask_respects_switch(self):
        s = Switches(os.path.join(tempfile.mkdtemp(), "s.json"))
        c = FakeClient("coding")
        g = AIGate(s, c)
        self.assertIsNone(g.ask("frame", {"jpeg": b""}))
        s.set({"ai": True}, "t")
        self.assertEqual(g.ask("frame", {"jpeg": b""})["scene"], "coding")
        self.assertEqual((c.asked, g.dropped_off, g.sent), (1, 1, 1))

    def test_transcripts_the_client_does_not_take_are_not_counted_as_sent(self):
        from room_companion.vision import LocalVision
        s = Switches(os.path.join(tempfile.mkdtemp(), "s.json"))
        s.set({"ai": True}, "t")
        g = AIGate(s, LocalVision(server=None, key_file="/nonexistent"))
        self.assertFalse(g.submit("transcript", {"text": "hi"}))
        self.assertEqual(g.sent, 0)


if __name__ == "__main__":
    unittest.main()
