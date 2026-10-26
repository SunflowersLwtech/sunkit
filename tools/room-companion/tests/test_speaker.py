import json
import os
import tempfile
import threading
import time
import unittest

from room_companion.app import DEFAULTS, App
from room_companion.speaker import Speaker, parse_outputs, parse_played
from tests.fakes import FakeNotifier
from tests.test_room import Pipe

REALTEK = {"name": "Speakers (Realtek(R) Audio)", "volume": 0, "muted": True, "default": True}
BT_SPEAKER = {"name": "Speakers (Example BT Speaker)", "volume": 40, "muted": False, "default": False}
CAMERA = {"name": "Speakers (Example Camera)", "volume": 80, "muted": False, "default": False}
CFG = {"output_prefer": ["BT Speaker", "Camera", "Speakers"],
       "output_labels": {"BT Speaker": "蓝牙音箱", "Camera": "相机的喇叭"},
       "missing_notes": {"Camera": "相机没有喇叭（它只当摄像头和麦克风用）"}}


class FakeAudio:
    def __init__(self, n=44100):
        self.samples, self.sample_rate = [0.1] * n, 44100


class FakeTTS:
    def __init__(self):
        self.texts = []

    def generate(self, text, sid=0, speed=1.0):
        self.texts.append(text)
        return FakeAudio()


class Events:
    def __init__(self):
        self.items = []

    def add(self, kind, **kw):
        self.items.append((kind, kw))


def make_speaker(outputs, play=None, state_path=None, **cfg):
    d = tempfile.mkdtemp()
    tts = FakeTTS()
    played = []

    def default_play(path, secs, device, volume):
        played.append((device, volume, round(secs, 2)))
        return {"device": device, "peak": 0.3, "seconds": secs}

    sp = Speaker(dict(CFG, win_dir="C:\\x", win_dir_wsl=d, **cfg), Events(), tts_factory=lambda: tts,
                 play=play or default_play, list_outputs=lambda: [dict(o) for o in outputs], state_path=state_path)
    return sp, tts, played


def wait_for(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class SpeakerTest(unittest.TestCase):
    def test_picks_speaker_then_camera_then_pc(self):
        outs = [REALTEK, BT_SPEAKER, CAMERA]
        sp, _, _ = make_speaker(outs)
        self.assertEqual(sp.check_output()["name"], BT_SPEAKER["name"])
        outs.remove(BT_SPEAKER)
        self.assertEqual(sp.check_output()["name"], CAMERA["name"])
        outs.remove(CAMERA)
        self.assertEqual(sp.check_output()["name"], REALTEK["name"])
        self.assertIn("相机没有喇叭（它只当摄像头和麦克风用）", sp.notes())
        outs.clear()
        self.assertIsNone(sp.check_output())
        self.assertEqual(sp.describe(), "出声：没有能出声的设备（只发通知）")

    def test_labels_follow_the_language_and_the_config(self):
        sp, _, _ = make_speaker([REALTEK, BT_SPEAKER], language="en")
        self.assertEqual(sp.label(REALTEK["name"]), "Computer speakers")
        self.assertEqual(sp.label(BT_SPEAKER["name"]), "蓝牙音箱")  # the owner's own label wins
        sp2, _, _ = make_speaker([REALTEK], output_prefer=[], output_labels={}, missing_notes={})
        self.assertEqual(sp2.check_output()["name"], REALTEK["name"])  # nothing preferred: Windows' default
        self.assertEqual(sp2.label("Speakers (Somebody's Headphones)"), "音箱", "never the hardware name")
        sp3, _, _ = make_speaker([REALTEK], language="en", output_labels={})
        self.assertEqual(sp3.label("Headphones (X)"), "speaker")
        self.assertEqual(sp2.notes(), ["电脑喇叭平时静音或音量低，念的时候临时开到 70%，念完恢复原样"])

    def test_manual_choice_is_kept_and_reloaded(self):
        path = os.path.join(tempfile.mkdtemp(), "state", "output.json")
        sp, _, _ = make_speaker([REALTEK, BT_SPEAKER], state_path=path)
        sp.check_output()
        sp.set_choice(REALTEK["name"])
        self.assertEqual(sp.output["name"], REALTEK["name"])
        with self.assertRaises(ValueError):
            sp.set_choice("Speakers (somewhere else)")
        sp2, _, _ = make_speaker([REALTEK, BT_SPEAKER], state_path=path)
        self.assertEqual(sp2.check_output()["name"], REALTEK["name"])
        self.assertIn("手动选的", sp2.describe())
        sp2.set_choice("auto")
        self.assertEqual(sp2.output["name"], BT_SPEAKER["name"])

    def test_muted_pc_speaker_is_raised_while_speaking(self):
        sp, tts, played = make_speaker([REALTEK])
        sp.check_output()
        self.assertEqual(sp.describe(), "出声：电脑喇叭（念的时候临时开到 70%）")
        self.assertTrue(sp.say("你好 hello"))
        self.assertTrue(wait_for(lambda: played))
        self.assertEqual(played[0][:2], (REALTEK["name"], 70))
        self.assertEqual(tts.texts, ["你好 hello"])
        self.assertTrue(wait_for(lambda: sp.spoken == 1))
        kinds = [k for k, _ in sp.events.items]
        self.assertIn("spoke", kinds)

    def test_echo_window_covers_playback(self):
        during = []
        gate = threading.Event()

        def slow_play(path, secs, device, volume):
            during.append(sp.echo())
            gate.wait(5)
            return {"peak": 0.2}

        sp, _, _ = make_speaker([REALTEK], play=slow_play)
        sp.say("一句话")
        self.assertTrue(wait_for(lambda: during))
        self.assertEqual(during, [True], "while playing, the mic hears our own voice")
        gate.set()
        self.assertTrue(wait_for(lambda: sp.spoken == 1))
        self.assertTrue(wait_for(lambda: not sp.echo(), timeout=5), "the echo window ends after the tail")

    def test_speech_that_started_while_speaking_is_echo(self):
        sp, _, _ = make_speaker([REALTEK])
        sp._spans.append((100.0, 104.0))  # we spoke from 100 to 104
        self.assertTrue(sp.echo(now=102.0))
        self.assertTrue(sp.echo(now=105.0))  # tail
        self.assertFalse(sp.echo(now=106.0))
        # a segment cut at 106.4 that began at 103.5 (our sentence, cut late by the VAD) is ours
        self.assertTrue(sp.echo(now=106.4, since=103.5))
        # someone talking from 107 to 110 is not
        self.assertFalse(sp.echo(now=110.0, since=107.0))

    def test_self_test_utterance_is_heard(self):
        sp, _, played = make_speaker([REALTEK])
        sp.say("自测", hear=True)
        self.assertTrue(wait_for(lambda: sp.spoken == 1))
        self.assertFalse(sp.echo(now=time.time(), since=time.time() - 10))

    def test_no_output_does_not_play(self):
        sp, _, played = make_speaker([])
        sp.say("x")
        self.assertTrue(wait_for(lambda: sp.error))
        self.assertIn("没有能出声的设备", sp.error)
        self.assertEqual(played, [])

    def test_parsers(self):
        outs = parse_outputs("OUT [default] Speakers (Realtek(R) Audio) | volume=0% mute=True\r\n"
                             "OUT           Speakers (Example BT Speaker) | volume=45% mute=False\r\n")
        self.assertEqual(outs, [dict(REALTEK), dict(BT_SPEAKER, volume=45)])
        r = parse_played("played device=Speakers (Realtek(R) Audio) | frames=147572 seconds=3.35 peak=0.338 "
                         "volume_before=0% mute_before=True volume_during=60%")
        self.assertEqual(r, {"device": "Speakers (Realtek(R) Audio)", "seconds": 3.35, "peak": 0.338,
                             "volume_before": 0, "muted_before": True, "volume_during": 60})
        self.assertIsNone(parse_played("error no active output matching 'BT Speaker'"))


class NothingIdentifyingLeavesTest(unittest.TestCase):
    """Confirmations, replies and results go to other services: no hardware names, error text or paths."""

    SENTINEL = {"name": "Headphones (SENTINEL-HW-99 Pods)", "volume": 0, "muted": True, "default": True}

    def test_messages_that_leave_the_machine(self):
        def failing_play(path, secs, device, volume):
            raise RuntimeError("playback failed: Exception: C:\\Users\\SENTINEL-USER\\tts\\say.wav")

        sp, _, _ = make_speaker([self.SENTINEL], play=failing_play, output_prefer=[], output_labels={}, missing_notes={})
        notifier = FakeNotifier()
        video = Pipe()
        app = App(dict(DEFAULTS, data_dir=tempfile.mkdtemp()), video=video, audio=Pipe(), notifier=notifier, speaker=sp)
        sp.check_output()
        video.state, video.detail = "error", "SENTINEL-CAM broke: device busy"
        app.start()
        try:
            app.set_switches({"video": True}, "网页（另一台设备）")
            self.assertTrue(wait_for(lambda: notifier.messages))
            got = []
            r = app.broadcast("你好", "网页（另一台设备）", on_done=got.append)
            self.assertTrue(wait_for(lambda: got))
            out = notifier.messages + [r["message"], app.run_command("状态", "手机")["message"],
                                       json.dumps(app.broadcast_result(r["id"]), ensure_ascii=False), json.dumps(got)]
            for text in out:
                self.assertNotIn("SENTINEL", text)
            self.assertIn("出声：音箱", notifier.messages[0])
            self.assertIn("出错了（详情看网页）", notifier.messages[0])
            self.assertEqual(got[0]["error"], "playback_failed")
            # the local page still has the details
            self.assertIn("SENTINEL-CAM", app.status()["summary"])
            self.assertIn("SENTINEL-USER", sp.error)
        finally:
            app.shutdown()

    def test_failure_codes(self):
        class BrokenTTS:
            def generate(self, *a, **k):
                raise RuntimeError("model file /home/SENTINEL/x.onnx missing")
        sp, _, _ = make_speaker([REALTEK])
        sp.tts_factory = lambda: BrokenTTS()
        sp.tts = None
        got = []
        sp.say("x", on_done=got.append)
        self.assertTrue(wait_for(lambda: got))
        self.assertEqual(got[0], {"ok": False, "error": "tts_failed"})


class BroadcastTest(unittest.TestCase):
    def make(self, **cfg):
        self.sp, self.tts, self.played = make_speaker([REALTEK])
        c = dict(DEFAULTS, data_dir=tempfile.mkdtemp(), **cfg)
        self.app = App(c, video=Pipe(), audio=Pipe(), notifier=FakeNotifier(), speaker=self.sp)
        return self.app

    def test_reads_out_with_all_switches_off_and_keeps_words_off_disk(self):
        app = self.make()
        self.assertEqual([app.switches.get(k) for k in ("video", "audio", "ai")], [False, False, False])
        r = app.broadcast("  晚饭好了，Dinner is ready  ", "网页")
        self.assertTrue(r["ok"], r)
        self.assertTrue(wait_for(lambda: self.tts.texts == ["晚饭好了，Dinner is ready"]))
        self.assertEqual(app.broadcast_status()["recent"][0]["text"], "晚饭好了，Dinner is ready")
        ev = [e for e in app.events.latest(10) if e["kind"] == "broadcast"]
        self.assertEqual(ev[0]["chars"], len("晚饭好了，Dinner is ready"))
        self.assertEqual(ev[0]["source"], "网页")
        for n in os.listdir(os.path.join(app.cfg["data_dir"], "events")):
            with open(os.path.join(app.cfg["data_dir"], "events", n), encoding="utf-8") as f:
                self.assertNotIn("晚饭", f.read())

    def test_result_and_callback(self):
        app = self.make()
        got = []
        r = app.broadcast("回报测试", "连接器", request_id="req-1", on_done=got.append)
        self.assertEqual(r["id"], "req-1")
        self.assertTrue(wait_for(lambda: got))
        self.assertEqual(got[0], {"id": "req-1", "ok": True, "output": "电脑喇叭", "seconds": 1.0, "peak": 0.3, "error": None})
        self.assertEqual(app.broadcast_result("req-1")["state"], "done")
        self.assertIsNone(app.broadcast_result("nope"))

    def test_failure_is_reported(self):
        app = self.make()
        self.sp.outputs, self.sp.cfg["check_output"] = [], False
        self.sp.output = None
        got = []
        app.broadcast("没有喇叭", "网页", on_done=got.append)
        self.assertTrue(wait_for(lambda: got))
        self.assertFalse(got[0]["ok"])
        self.assertEqual(got[0]["error"], "no_output")
        self.assertIn("没有能出声的设备", self.sp.error)  # the words stay on the local page
        self.assertEqual(app.broadcast_result(got[0]["id"])["state"], "failed")

    def test_length_and_empty(self):
        app = self.make()
        self.assertEqual(app.broadcast("", "网页")["code"], "empty")
        self.assertEqual(app.broadcast("字" * 301, "网页")["code"], "too_long")
        self.assertTrue(app.broadcast("字" * 300, "网页")["ok"])

    def test_per_minute_and_per_day_limits(self):
        app = self.make(broadcast_per_day=8)
        t = 1_800_000_000.0
        for i in range(6):
            self.assertTrue(app.broadcast(f"第{i}句", "手机", now=t + i)["ok"])
        r = app.broadcast("第7句", "手机", now=t + 10)
        self.assertEqual((r["ok"], r["code"]), (False, "rate_limited"))
        self.assertIn("每分钟最多 6 次", r["message"])
        self.assertTrue(app.broadcast("一分钟后", "手机", now=t + 61)["ok"])
        self.assertTrue(app.broadcast("一分钟后2", "手机", now=t + 62)["ok"])
        r = app.broadcast("今天第9句", "手机", now=t + 200)
        self.assertEqual((r["ok"], r["code"]), (False, "rate_limited"))
        self.assertIn("今天已经念了 8 次", r["message"])
        self.assertTrue(app.broadcast("第二天", "手机", now=t + 86400)["ok"])
        self.assertEqual([b["text"] for b in app.broadcast_status(now=t + 86400)["recent"]], ["第二天"])

    def test_text_command(self):
        app = self.make()
        r = app.run_command("播报：今天下午 3 点开会", "手机")
        self.assertTrue(r["ok"], r)
        self.assertTrue(wait_for(lambda: self.tts.texts == ["今天下午 3 点开会"]))
        self.assertFalse(app.run_command("播报：", "手机")["ok"])
        self.assertFalse(app.switches.get("audio"))

    def test_own_voice_is_not_a_command(self):
        app = self.make()
        self.sp._cur = (time.time(), time.time() + 30, False)  # playing right now
        app.on_transcript("房间助手，关视频")
        app.switches.set({"video": True}, "t")
        app.on_transcript("房间助手，关视频")
        self.assertTrue(app.switches.get("video"), "heard while speaking: ignored")

    def test_status_line(self):
        app = self.make()
        self.sp.check_output()
        self.assertIn("出声：电脑喇叭（念的时候临时开到 70%）", app.plain_status())


if __name__ == "__main__":
    unittest.main()
