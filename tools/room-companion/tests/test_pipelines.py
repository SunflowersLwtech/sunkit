import json
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import socket
import threading

from room_companion.app import App, DEFAULTS
from room_companion.audio import AudioPipeline, EnergyVAD
from room_companion.devices import AudioDevice, VideoDevice
from room_companion.video import VideoPipeline
from room_companion.web import make_handler, serve
from tests.fakes import FAKE_ARECORD, FAKE_FFMPEG, PY, FakeNotifier, ignoring_sigterm, pid_alive, write_script


def wait_for(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class ScriptedSpeech(EnergyVAD):
    """Energy VAD with canned transcripts, one per segment."""

    def __init__(self, texts):
        super().__init__(threshold_db=-30)
        self.texts = list(texts)
        self.calls = 0

    def transcribe(self, seg):
        self.calls += 1
        return self.texts.pop(0) if self.texts else ""


def confirmation_after_exit(test, key, label, install_stub, pid_of):
    """Switch `key` on, then off, with a capture process that ignores SIGTERM; record whether that process
    was still alive at the moment the off confirmation went out."""
    app, notifier = make_app(tempfile.mkdtemp())
    install_stub(app)
    seen, pid = [], {}
    real_send = notifier.send

    def send(text, *a, **k):
        if "已关闭" + label in text:
            seen.append(pid_alive(pid["p"]))
        return real_send(text, *a, **k)

    notifier.send = send
    app.start()
    try:
        app.set_switches({key: True}, "t")
        test.assertTrue(wait_for(lambda: pid_of(app) is not None))
        pid["p"] = pid_of(app)
        app.set_switches({key: False}, "t")
        app.wait_settled()
        test.assertTrue(wait_for(lambda: seen, timeout=15))
        test.assertEqual(seen, [False], "confirmation sent while the capture process was still alive")
    finally:
        app.shutdown()


def make_app(tmp, texts=(), ffmpeg_exit_after=0, video_device=True, audio_device=True):
    cfg = dict(DEFAULTS, data_dir=tmp, port=0, listen="127.0.0.1")
    fake_ff = write_script(FAKE_FFMPEG)
    fake_ar = write_script(FAKE_ARECORD)
    notifier = FakeNotifier()
    # placeholders, replaced below by pipelines that run fake commands on fake devices
    app = App(cfg, video=object(), audio=object(), notifier=notifier)
    app.video = VideoPipeline(
        app.switches, app.events, cfg,
        find_device=lambda: VideoDevice("/dev/video0", "Fake Osmo", "2ca3") if video_device else None,
        list_formats=lambda p: [("MJPG", 1920, 1080, 30.0)],
        build_cmd=lambda dev, fmt, fps, w, fd: [PY, fake_ff, str(fd)] + ([str(ffmpeg_exit_after)] if ffmpeg_exit_after else []))
    speech = ScriptedSpeech(texts)
    app.audio = AudioPipeline(
        app.switches, app.events, cfg, on_transcript=app.on_transcript,
        find_device=lambda: AudioDevice(1, "Mini", "Fake DJI MIC MINI") if audio_device else None,
        build_cmd=lambda alsa: [PY, fake_ar], speech_factory=lambda: speech)
    app.speech = speech
    return app, notifier


class VideoPipelineTest(unittest.TestCase):
    def setUp(self):
        self.app, self.notifier = make_app(tempfile.mkdtemp())
        self.app.start()

    def tearDown(self):
        self.app.shutdown()

    def test_switch_controls_the_process(self):
        v = self.app.video
        time.sleep(0.3)
        self.assertIsNone(v.proc, "must not open the camera while the switch is off")
        self.app.set_switches({"video": True}, "test")
        self.assertTrue(wait_for(lambda: v.state == "running" and v.latest()[0] is not None))
        pid = v.pid
        self.assertTrue(pid_alive(pid))
        self.app.set_switches({"video": False}, "test")
        self.assertTrue(self.app.wait_settled())
        self.assertIsNone(v.proc)
        self.assertFalse(pid_alive(pid), "ffmpeg must have exited, not just be ignored")
        self.assertIsNone(v.latest()[0], "frames must be dropped from memory")
        self.assertTrue(wait_for(lambda: len(self.notifier.messages) >= 2))
        self.assertIn("已关闭视频", self.notifier.messages[-1])
        self.assertIn("摄像头已释放", self.notifier.messages[-1])

    def test_off_confirmation_only_after_exit(self):
        stub = write_script(ignoring_sigterm(FAKE_FFMPEG))

        def install(app):
            app.video.build_cmd = lambda dev, fmt, fps, w, fd: [PY, stub, str(fd)]
        confirmation_after_exit(self, "video", "视频", install,
                                lambda app: app.video.pid if app.video.latest()[0] is not None else None)

    def test_confirmations_arrive_in_switch_order(self):
        # The first confirmation is slow to settle, the second is instant: they must still go out in order.
        real = self.app.wait_settled
        calls = []

        def slow_first(timeout=8.0):
            calls.append(1)
            if len(calls) == 1:
                time.sleep(0.8)
            return real(timeout)

        self.app.wait_settled = slow_first
        self.app.set_switches({"ai": True}, "test")
        self.app.set_switches({"ai": False}, "test")
        self.assertTrue(wait_for(lambda: len(self.notifier.messages) >= 2))
        self.assertIn("已打开AI", self.notifier.messages[0])
        self.assertIn("已关闭AI", self.notifier.messages[1])

    def test_restart_after_crash(self):
        self.app.shutdown()
        self.app, self.notifier = make_app(tempfile.mkdtemp(), ffmpeg_exit_after=0.5)
        self.app.start()
        v = self.app.video
        self.app.set_switches({"video": True}, "test")
        self.assertTrue(wait_for(lambda: v.state == "running"))
        first = v.pid
        self.assertTrue(wait_for(lambda: v.pid not in (None, first), timeout=8))

    def test_waits_for_device(self):
        self.app.shutdown()
        self.app, _ = make_app(tempfile.mkdtemp(), video_device=False)
        self.app.start()
        self.app.set_switches({"video": True}, "test")
        self.assertTrue(wait_for(lambda: self.app.video.state == "waiting_device"))
        self.assertIn("没接上相机", self.app.plain_status())


class AudioPipelineTest(unittest.TestCase):
    def test_voice_command_turns_video_off_and_ai_never_sees_it(self):
        app, notifier = make_app(tempfile.mkdtemp(), texts=["今天天气不错", "房间助手，关视频"])
        sent = []

        class Client:
            def send(self, kind, payload):
                sent.append(payload["text"])

        app.ai.client = Client()
        app.start()
        try:
            app.set_switches({"video": True, "audio": True, "ai": True}, "test")
            self.assertTrue(wait_for(lambda: app.audio.state == "running"))
            self.assertTrue(wait_for(lambda: not app.switches.get("video"), timeout=10))
            self.assertEqual(sent, ["今天天气不错"])
            self.assertTrue(wait_for(lambda: any("来源：语音" in m for m in notifier.messages)))
            kinds = [e["kind"] for e in app.events.latest(100)]
            self.assertIn("voice_command", kinds)
        finally:
            app.shutdown()

    def test_off_confirmation_only_after_exit(self):
        stub = write_script(ignoring_sigterm(FAKE_ARECORD))

        def install(app):
            app.audio.build_cmd = lambda alsa: [PY, stub]
        confirmation_after_exit(self, "audio", "声音", install,
                                # only once audio has arrived: before that the stub may not have set its handler yet
                                lambda app: app.audio.pid if app.audio.level_db > -100 else None)

    def test_audio_off_kills_recorder_and_clears_transcripts(self):
        app, _ = make_app(tempfile.mkdtemp(), texts=["一句话"])
        app.start()
        try:
            app.set_switches({"audio": True}, "test")
            self.assertTrue(wait_for(lambda: len(app.audio.recent_transcripts()) == 1, timeout=10))
            pid = app.audio.pid
            app.set_switches({"audio": False}, "test")
            self.assertTrue(app.wait_settled())
            self.assertFalse(pid_alive(pid))
            self.assertEqual(app.audio.recent_transcripts(), [])
            # nothing with the words reaches the disk
            for n in os.listdir(os.path.join(app.cfg["data_dir"], "events")):
                with open(os.path.join(app.cfg["data_dir"], "events", n), encoding="utf-8") as f:
                    self.assertNotIn("一句话", f.read())
        finally:
            app.shutdown()


class WebTest(unittest.TestCase):
    def setUp(self):
        self.app, self.notifier = make_app(tempfile.mkdtemp())
        self.app.web_token = "k" * 32
        self.app.start()
        self.srv = serve(self.app)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.app.shutdown()

    def req(self, path, body=None, headers=None):
        if body is None:
            return self.raw(path, None, headers)
        return self.raw(path, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})

    def raw(self, path, data, headers=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                   method="POST" if data is not None else "GET", headers=headers or {})
        try:
            with urllib.request.urlopen(r, timeout=15) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_local_needs_no_key(self):
        code, body = self.req("/api/command", {"text": "开AI", "source": "飞书"}, headers={"X-Room-AI": "1"})
        self.assertEqual(code, 200, body)
        self.assertTrue(self.app.switches.get("ai"))
        self.assertTrue(wait_for(lambda: any("来源：飞书" in m for m in self.notifier.messages)))

    def test_remote_needs_key_and_header(self):
        self.app.cfg["trust_loopback"] = False
        self.app.cfg["allowed_cidrs"] = ["127.0.0.0/8"]
        self.srv.RequestHandlerClass = __import__("room_companion.web", fromlist=["x"]).make_handler(self.app)
        self.assertEqual(self.req("/api/status")[0], 401)
        self.assertEqual(self.req("/api/status", headers={"Cookie": "room_k=wrong"})[0], 401)
        ok = {"Cookie": "room_k=" + "k" * 32}
        self.assertEqual(self.req("/api/status", headers=ok)[0], 200)
        # cookie alone is not enough to switch (cross-site form posts carry cookies)
        self.assertEqual(self.req("/api/switch", {"video": True}, headers=ok)[0], 403)
        self.assertFalse(self.app.switches.get("video"))
        code, _ = self.req("/api/switch", {"video": True}, headers={**ok, "X-Room-AI": "1"})
        self.assertEqual(code, 200)
        self.assertTrue(self.app.switches.get("video"))
        # a remote caller cannot pretend to be Feishu
        self.req("/api/switch", {"video": False, "source": "飞书"}, headers={**ok, "X-Room-AI": "1"})
        self.assertTrue(self.app.switches.snapshot()["source"].startswith("网页"))

    def test_request_through_caddy_is_not_local(self):
        # a reverse proxy passes the browser's Host through, so the name has to be in allowed_hosts
        self.app.cfg["allowed_hosts"] = ["room.example.org"]
        self.srv.RequestHandlerClass = make_handler(self.app)
        via = {"Host": "room.example.org", "X-Forwarded-For": "100.101.102.103",
               "X-Forwarded-Host": "room.example.org"}
        self.assertEqual(self.req("/api/status", headers=via)[0], 401)
        self.assertEqual(self.req("/api/command", {"text": "开视频", "source": "飞书"},
                                  headers={**via, "X-Room-AI": "1"})[0], 401)
        self.assertFalse(self.app.switches.get("video"))
        # a proxy on the same box can forward LAN clients, so the forwarded address can be loopback too
        self.assertEqual(self.req("/api/status", headers={**via, "X-Forwarded-For": "127.0.0.1"})[0], 401)
        ok = {**via, "Cookie": "room_k=" + "k" * 32, "X-Room-AI": "1"}
        self.assertEqual(self.req("/api/switch", {"ai": True, "source": "飞书"}, headers=ok)[0], 200)
        self.assertEqual(self.app.switches.snapshot()["source"], "网页（经反向代理）")

    def test_cross_site_form_post_is_refused(self):
        # what <form enctype="text/plain"> on another site, open in a browser on this machine, sends to 127.0.0.1
        form = {"Content-Type": "text/plain", "Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
        for path, text in (("/api/switch", '{"video":true,"audio":true,"ai":true,"x":"="}'),
                           ("/api/command", '{"text":"全开","x":"="}')):
            self.assertEqual(self.raw(path, text.encode(), form)[0], 403, path)
        self.assertEqual([self.app.switches.get(k) for k in ("video", "audio", "ai")], [False, False, False])
        self.assertIsNone(self.app.video.proc)
        self.assertIsNone(self.app.audio.proc)
        self.assertFalse(any("打开" in m for m in self.notifier.messages), self.notifier.messages)

    def test_every_post_needs_the_header_and_json(self):
        self.assertEqual(self.req("/api/switch", {"video": True})[0], 403)  # same machine, no header
        self.assertEqual(self.raw("/api/switch", b'{"video":true}',
                                  {"X-Room-AI": "1", "Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.req("/api/switch", {"video": True},
                                  headers={"X-Room-AI": "1", "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("/api/switch", {"video": True},
                                  headers={"X-Room-AI": "1", "Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertFalse(self.app.switches.get("video"))
        code, _ = self.req("/api/switch", {"ai": True}, headers={"X-Room-AI": "1", "Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(code, 200)
        self.assertTrue(self.app.switches.get("ai"))

    def test_foreign_host_is_refused(self):
        # DNS rebinding: a hostile name that now resolves to 127.0.0.1
        self.app.set_switches({"video": True}, "test")
        self.assertTrue(wait_for(lambda: self.app.video.latest()[0] is not None))
        evil = {"Host": "evil.example:8790"}
        for path in ("/api/status", "/snapshot.jpg", "/", "/healthz", "/stream.mjpg"):
            self.assertEqual(self.req(path, headers=evil)[0], 403, path)
        self.assertEqual(self.req("/api/switch", {"video": False}, headers={**evil, "X-Room-AI": "1"})[0], 403)
        self.assertTrue(self.app.switches.get("video"))
        for host in (f"127.0.0.1:{self.port}", "localhost", "[::1]:8790"):
            self.assertEqual(self.req("/api/status", headers={"Host": host})[0], 200, host)

    def test_refused_body_is_not_read_as_a_second_request(self):
        # a cross-site POST whose body is itself a complete request with every header the guard wants
        inner = (b"POST /api/switch HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Room-AI: 1\r\n"
                 b"Content-Type: application/json\r\nContent-Length: 11\r\n\r\n{\"ai\":true}")
        outer = (b"POST /api/switch HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: text/plain\r\n"
                 b"Origin: https://evil.example\r\nSec-Fetch-Site: cross-site\r\n"
                 b"Content-Length: " + str(len(inner)).encode() + b"\r\n\r\n" + inner)
        got = b""
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as c:
            c.sendall(outer)
            try:
                while True:
                    chunk = c.recv(65536)
                    if not chunk:
                        break
                    got += chunk
            except socket.timeout:
                pass
        self.assertEqual(got.count(b"HTTP/1.1 "), 1, got[:300])
        self.assertTrue(got.startswith(b"HTTP/1.1 403"), got[:100])
        self.assertFalse(self.app.switches.get("ai"))

    def test_configured_host_and_cross_site_reads(self):
        self.assertEqual(self.req("/api/status", headers={"Host": "room.example.test"})[0], 403)
        self.app.cfg["allowed_hosts"] = ["room.example.test"]
        self.srv.RequestHandlerClass = make_handler(self.app)
        self.assertEqual(self.req("/api/status", headers={"Host": "room.example.test"})[0], 200)
        # a page on another site cannot load the data, even with an allowed Host (the browser marks it cross-site)
        self.assertEqual(self.req("/api/status", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "cors"})[0], 403)
        self.assertEqual(self.req("/snapshot.jpg", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors",
                                                             "Sec-Fetch-Dest": "image"})[0], 403)
        # following a link to the page from elsewhere still opens it, but not inside a frame
        nav = {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        self.assertEqual(self.req("/", headers=nav)[0], 200)
        self.assertEqual(self.req("/", headers={**nav, "Sec-Fetch-Dest": "iframe"})[0], 403)

    def test_stream_refused_when_video_off(self):
        self.assertEqual(self.req("/stream.mjpg")[0], 409)
        self.assertEqual(self.req("/snapshot.jpg")[0], 404)
        self.app.set_switches({"video": True}, "test")
        self.assertTrue(wait_for(lambda: self.app.video.latest()[0] is not None))
        code, body = self.req("/snapshot.jpg")
        self.assertEqual(code, 200)
        self.assertTrue(body.startswith(b"\xff\xd8"))


if __name__ == "__main__":
    unittest.main()
