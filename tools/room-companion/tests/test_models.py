"""The models layer: settings, the three OpenAI-compatible clients, "Test connection", and the App wiring."""
import io
import json
import os
import socket
import stat
import tempfile
import threading
import time
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from room_companion import models as m
from room_companion.app import DEFAULTS, App
from room_companion.vision import parse_observation
from tests.fakes import FakeNotifier
from tests.test_room import FakeClient, FakeServer, Pipe

OBS = {"person": True, "scene": "coding", "hot_oil": False, "on_phone_call": False, "note": "在桌前"}


def wav_bytes(seconds=0.2, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(rate * seconds))
    return buf.getvalue()


class FakeModel:
    """An OpenAI-compatible server on loopback: chat/completions, audio/transcriptions, audio/speech."""

    def __init__(self, answer=None, key=None, status=200, delay=0.0, reject_schema=False, error_body=b""):
        self.requests = []
        self.answer = answer if answer is not None else json.dumps(OBS, ensure_ascii=False)
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, ctype, data):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n)
                ctype = self.headers.get("Content-Type", "")
                body = json.loads(raw) if ctype.startswith("application/json") else raw
                fake.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                      "ctype": ctype, "body": body})
                if delay:
                    time.sleep(delay)
                if key and self.headers.get("Authorization") != "Bearer " + key:
                    return self._send(401, "application/json", b'{"error":{"message":"bad key"}}')
                if status != 200:
                    return self._send(status, "application/json", error_body or b'{"error":{"message":"x"}}')
                if self.path.endswith("/chat/completions"):
                    if reject_schema and isinstance(body, dict) and "response_format" in body:
                        return self._send(400, "application/json", b'{"error":{"message":"response_format unsupported"}}')
                    out = {"model": "served-model", "usage": {"completion_tokens": 2},
                           "choices": [{"message": {"role": "assistant", "content": fake.answer}}]}
                    return self._send(200, "application/json", json.dumps(out).encode())
                if self.path.endswith("/audio/transcriptions"):
                    return self._send(200, "application/json", '{"text": " 房间助手关视频 "}'.encode())
                if self.path.endswith("/audio/speech"):
                    return self._send(200, "audio/wav", wav_bytes())
                self._send(404, "application/json", b'{"error":"no route"}')

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def closed_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/v1"


class SettingsTest(unittest.TestCase):
    def test_no_models_config_means_engine_everywhere(self):
        st = m.ModelSettings({}, tempfile.mkdtemp())
        self.assertEqual([st.slot(s) for s in m.SLOTS], [{"source": "engine"}] * 3)

    def test_runtime_choice_wins_over_the_file_and_is_kept_private(self):
        d = tempfile.mkdtemp()
        st = m.ModelSettings({"models": {"vision": {"source": "off"}}}, d)
        self.assertEqual(st.slot("vision"), {"source": "off"})
        changed = st.set({"vision": {"source": "openai", "base_url": "http://h:1/v1/", "model": "x",
                                     "api_key_file": "/etc/shadow"}}, {"vision": "sk-secret"})
        self.assertEqual(changed, ["vision"])
        self.assertEqual(st.slot("vision"), {"source": "openai", "base_url": "http://h:1/v1", "model": "x"},
                         "a key file path from the website must not be accepted")
        self.assertEqual(st.key("vision"), "sk-secret")
        for f in ("models.json", "model_keys.json"):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(d, f)).st_mode), 0o600, f)
        again = m.ModelSettings({"models": {"vision": {"source": "off"}}}, d)
        self.assertEqual(again.slot("vision")["source"], "openai")
        self.assertEqual(again.key("vision"), "sk-secret")
        self.assertNotIn("sk-secret", open(os.path.join(d, "models.json")).read())
        again.set({}, {"vision": ""})
        self.assertIsNone(again.key("vision"))

    def test_unknown_source_reads_as_engine(self):
        self.assertEqual(m.normalize_slot({"source": "magic", "base_url": "x"}), {"source": "engine"})


class ClientsTest(unittest.TestCase):
    def setUp(self):
        self.srv = None

    def tearDown(self):
        if self.srv:
            self.srv.close()

    def test_openai_vision_sends_the_frame_with_the_schema_and_parses_the_answer(self):
        self.srv = FakeModel(key="sk-v")
        c = m.OpenAIVision({"source": "openai", "base_url": self.srv.url, "model": "qwen2.5vl:3b"}, lambda: "sk-v")
        obs = c.ask("frame", {"jpeg": m.TEST_JPEG})
        self.assertEqual(obs["scene"], "coding")
        req = self.srv.requests[-1]
        self.assertEqual(req["path"], "/v1/chat/completions")
        self.assertEqual(req["body"]["model"], "qwen2.5vl:3b")
        self.assertEqual(req["body"]["response_format"]["type"], "json_schema")
        self.assertTrue(req["body"]["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_a_server_without_structured_output_is_asked_again_and_prose_is_parsed(self):
        self.srv = FakeModel(answer="Sure! " + json.dumps(OBS) + " Hope that helps.", reject_schema=True)
        c = m.OpenAIVision({"source": "openai", "base_url": self.srv.url, "model": "x"}, lambda: None)
        obs = c.ask("frame", {"jpeg": m.TEST_JPEG})
        self.assertEqual(obs["scene"], "coding")
        self.assertEqual(len(self.srv.requests), 2)
        self.assertNotIn("response_format", self.srv.requests[1]["body"])

    def test_speech_to_text_posts_a_wav_as_multipart(self):
        self.srv = FakeModel()
        text = m.transcribe_wav(self.srv.url, "whisper-small", "k", m.pcm16_wav(b"\x00\x00" * 1600), 5)
        self.assertEqual(text, "房间助手关视频")
        req = self.srv.requests[-1]
        self.assertTrue(req["ctype"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="model"\r\n\r\nwhisper-small', req["body"])
        self.assertIn(b'filename="audio.wav"', req["body"])
        self.assertIn(b"RIFF", req["body"])

    def test_text_to_speech_comes_back_as_samples(self):
        self.srv = FakeModel()
        audio = m.RemoteTTS(lambda t: m.speech_wav(self.srv.url, "kokoro", None, t, "af_heart", 5)).generate("你好")
        self.assertEqual(audio.sample_rate, 16000)
        self.assertEqual(len(audio.samples), 3200)
        self.assertEqual(self.srv.requests[-1]["body"]["response_format"], "wav")
        self.assertEqual(self.srv.requests[-1]["body"]["voice"], "af_heart")

    def test_remote_speech_sends_nothing_while_ai_is_off(self):
        self.srv = FakeModel()
        ai = [False]

        class Vad:
            def accept(self, pcm): return []
            def reset(self): pass
            def seconds(self, seg): return 0.1

        rs = m.RemoteSpeech(Vad(), lambda wav: m.transcribe_wav(self.srv.url, "w", None, wav, 5), lambda: ai[0])
        self.assertEqual(rs.transcribe(b"\x00\x00" * 1600), "")
        self.assertEqual(self.srv.requests, [], "speech left the machine with AI off")
        ai[0] = True
        self.assertEqual(rs.transcribe(b"\x00\x00" * 1600), "房间助手关视频")


class TestConnectionTest(unittest.TestCase):
    def test_success_reports_model_and_latency(self):
        srv = FakeModel()
        try:
            r = m.test_slot("vision", {"source": "openai", "base_url": srv.url, "model": "x"}, None)
        finally:
            srv.close()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["result"]["model"], "served-model")
        self.assertIsInstance(r["result"]["latency_ms"], int)
        self.assertEqual(r["result"]["detail"], "HTTP 200, 2 tokens")

    def test_error_codes(self):
        cases = []
        cases.append(("connect_failed", closed_port_url(), {}))
        for code, kw in (("unauthorized", {"key": "right"}), ("not_found", {"status": 404}),
                         ("model_not_found", {"status": 404, "error_body": b'{"error":{"message":"model \\"zz\\" not found"}}'}),
                         ("bad_response", {"status": 500})):
            cases.append((code, None, kw))
        for want, url, kw in cases:
            srv = None
            if url is None:
                srv = FakeModel(**kw)
                url = srv.url
            try:
                r = m.test_slot("vision", {"source": "openai", "base_url": url, "model": "zz"}, "wrong")
            finally:
                if srv:
                    srv.close()
            self.assertFalse(r["ok"], (want, r))
            self.assertEqual(r["error"]["code"], want, r)

    def test_timeout(self):
        srv = FakeModel(delay=2.0)
        try:
            r = m.test_slot("stt", {"source": "openai", "base_url": srv.url, "model": "w"}, None, timeout=0.5)
        finally:
            srv.close()
        self.assertEqual(r["error"]["code"], "timeout", r)

    def test_each_slot_makes_its_own_kind_of_request(self):
        srv = FakeModel()
        try:
            for slot, path in (("vision", "/v1/chat/completions"), ("stt", "/v1/audio/transcriptions"),
                               ("tts", "/v1/audio/speech")):
                r = m.test_slot(slot, {"source": "openai", "base_url": srv.url, "model": "x"}, None)
                self.assertTrue(r["ok"], (slot, r))
                self.assertEqual(srv.requests[-1]["path"], path)
        finally:
            srv.close()

    def test_engine_without_a_check_and_off_are_explained(self):
        self.assertEqual(m.test_slot("vision", {"source": "engine"}, None)["error"]["code"], "engine_unavailable")
        self.assertEqual(m.test_slot("tts", {"source": "off"}, None)["error"]["code"], "unsupported")


class AppModelsTest(unittest.TestCase):
    def make(self, models=None):
        cfg = dict(DEFAULTS, data_dir=tempfile.mkdtemp())
        if models is not None:
            cfg["models"] = models
        self.client, self.server, self.notifier = FakeClient("coding"), FakeServer(), FakeNotifier()
        return App(cfg, video=Pipe("running"), audio=Pipe(), notifier=self.notifier, ai_client=self.client,
                   model_server=self.server)

    def test_without_a_models_section_the_engine_clients_are_used_unchanged(self):
        app = self.make()
        self.assertIs(app.ai.client, self.client)
        self.assertIs(app.model_server, self.server)
        self.assertEqual({k: v["source"] for k, v in app.models_state().items()},
                         {"vision": "engine", "stt": "engine", "tts": "engine"})

    def test_switching_vision_to_a_server_parks_the_engine_and_back(self):
        srv = FakeModel()
        try:
            app = self.make()
            app.switches.set({"video": True, "ai": True}, "t")
            app.observe_once(now=time.time())
            self.assertTrue(self.server.want, "engine started for AI+video")
            changed = app.apply_models({"vision": {"source": "openai", "base_url": srv.url, "model": "x"}})
            self.assertEqual(changed, ["vision"])
            self.assertFalse(self.server.want, "the engine kept running after vision moved to a server")
            self.assertIsInstance(app.ai.client, m.OpenAIVision)
            app.last_obs_at = 0
            app.observe_once(now=time.time() + 400)
            self.assertEqual(srv.requests[-1]["path"], "/v1/chat/completions")
            self.assertEqual(app.policy.scene, "coding")
            self.assertEqual(app.models_state()["vision"]["base_url"], srv.url)
            app.apply_models({"vision": {"source": "engine"}})
            self.assertIs(app.ai.client, self.client)
            self.assertIs(app.model_server, self.server)
        finally:
            srv.close()

    def test_vision_off_sends_nothing(self):
        app = self.make({"vision": {"source": "off"}})
        app.switches.set({"video": True, "ai": True}, "t")
        app.observe_once(now=time.time())
        self.assertEqual(self.client.asked, 0)
        self.assertEqual(app.ai.status()["dropped_no_client"], 1)

    def test_cloud_vision_asks_through_the_connector(self):
        app = self.make({"vision": {"source": "cloud"}})
        calls = []

        def cloud(kind, payload):
            calls.append((kind, payload))
            return {"ok": True, "text": "```json\n" + json.dumps(OBS) + "\n```"}

        app.cloud = cloud
        app.switches.set({"video": True, "ai": True}, "t")
        app.observe_once(now=time.time())
        self.assertEqual(calls[0][0], "infer")
        self.assertEqual(len(calls[0][1]["images"]), 1)
        self.assertEqual(app.policy.scene, "coding")
        app.cloud = None
        self.assertIsNone(app.ai.client.ask("frame", {"jpeg": b"x"}), "no connector, no answer")

    def test_tts_off_keeps_the_speaker_silent(self):
        app = self.make({"tts": {"source": "off"}})
        said = []

        class Sp:
            error, tts, output = None, None, None
            def say(self, text, hear=False): said.append(text)
            def echo(self): return False
            def status(self): return {}

        app.speaker = Sp()
        app._deliver("起来走走", "久坐", True)
        self.assertEqual(said, [])
        app.apply_models({"tts": {"source": "engine"}})
        app._deliver("起来走走", "久坐", True)
        self.assertEqual(said, ["起来走走"])

    def test_quiet_hours_set_at_run_time_survive_a_restart(self):
        d = tempfile.mkdtemp()
        cfg = dict(DEFAULTS, data_dir=d)
        app = App(cfg, video=Pipe(), audio=Pipe(), notifier=FakeNotifier(), ai_client=FakeClient())
        app.set_quiet_hours("22:30", "07:00")
        self.assertEqual(app.quiet_hours(), {"start": "22:30", "end": "07:00"})
        again = App(dict(DEFAULTS, data_dir=d), video=Pipe(), audio=Pipe(), notifier=FakeNotifier(), ai_client=FakeClient())
        self.assertEqual(again.quiet_hours(), {"start": "22:30", "end": "07:00"})
        again.set_quiet_hours(None, None)
        self.assertIsNone(again.quiet_hours())
        with self.assertRaises(ValueError):
            again.set_quiet_hours("late", "early")

    def test_test_model_reuses_the_saved_key_only_for_the_saved_server(self):
        srv = FakeModel(key="sk-saved")
        try:
            app = self.make()
            app.apply_models({"vision": {"source": "openai", "base_url": srv.url, "model": "x"}}, {"vision": "sk-saved"})
            self.assertTrue(app.test_model("vision", {"source": "openai", "base_url": srv.url, "model": "x"})["ok"])
            other = app.test_model("vision", {"source": "openai", "base_url": srv.url.replace("127.0.0.1", "localhost"),
                                              "model": "x"})
            self.assertFalse(other["ok"], "the saved key went to a different server")
            self.assertEqual(other["error"]["code"], "unauthorized")
            self.assertNotIn("sk-saved", json.dumps(app.status(), ensure_ascii=False),
                             "the key shows up in the local status (and on the local web page)")
        finally:
            srv.close()


class AppSpeechTest(unittest.TestCase):
    def test_the_real_audio_pipeline_picks_up_a_speech_to_text_server_at_run_time(self):
        srv = FakeModel()
        try:
            cfg = dict(DEFAULTS, data_dir=tempfile.mkdtemp(), vad_model="/nonexistent/silero.onnx")
            app = App(cfg, video=Pipe(), notifier=FakeNotifier(), ai_client=FakeClient())
            app.apply_models({"stt": {"source": "openai", "base_url": srv.url, "model": "whisper-small"}})
            speech = app.audio._ensure_speech()
            self.assertIsInstance(speech, m.RemoteSpeech)
            self.assertEqual(speech.transcribe(b"\x00\x00" * 1600), "", "sent with AI off")
            self.assertEqual(srv.requests, [])
            app.switches.set({"ai": True}, "t")
            self.assertEqual(speech.transcribe(b"\x00\x00" * 1600), "房间助手关视频")
            self.assertEqual(srv.requests[-1]["path"], "/v1/audio/transcriptions")
            app.apply_models({"stt": {"source": "off"}})
            self.assertNotIsInstance(app.audio._ensure_speech(), m.RemoteSpeech)
        finally:
            srv.close()


class ParseTest(unittest.TestCase):
    def test_extract_json_from_prose_and_fences(self):
        self.assertEqual(m.extract_json('x {"a": 1} y'), {"a": 1})
        self.assertEqual(parse_observation(json.dumps(m.extract_json("```json\n" + json.dumps(OBS) + "\n```")))["scene"], "coding")
        self.assertIsNone(m.extract_json("no json here"))


if __name__ == "__main__":
    unittest.main()
