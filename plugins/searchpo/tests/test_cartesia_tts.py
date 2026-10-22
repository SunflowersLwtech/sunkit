from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.cartesia_tts as cartesia
from agent_harness.stages import voiceover_manifest_errors
from scripts.build_captions import require_voiceover_audio
from scripts.gemini_tts import gemini_previous_manifest

SAMPLE_RATE = 44100
TEST_KEY = "cartesia-test-key-not-real"
VOICEOVER = "这是一个关于开源抓取工具的知识讲解。它先解决网页结构变化带来的维护成本，再说明适用边界和失败场景。"
# Keys gemini_tts.py writes into voiceover_manifest.json; the Cartesia manifest must carry all of them.
GEMINI_MANIFEST_KEYS = {
    "schema_version", "created_at", "provider", "model", "api_mode", "voice", "tts_style", "language",
    "audio_encoding", "sample_rate_hz", "speed", "volume_gain_db", "target_lufs", "status", "source_mime_type",
    "output_mime_type", "audio_path", "audio_duration_sec", "audio_frames", "fps", "voiceover_text", "text_hash",
    "source_voiceover_text", "normalized_voiceover_text", "audio_sha256", "retry_history", "tts_chunking",
    "speech_quality_checks", "response_meta",
}


def streamed_wav(seconds: float, *, extra_chunk: bool = False, trailing_odd_byte: bool = False) -> bytes:
    """A WAV the way a streaming encoder writes it: RIFF and data sizes are placeholders."""
    frames = int(SAMPLE_RATE * seconds)
    pcm = b"".join(struct.pack("<h", (index * 37) % 2000 - 1000) for index in range(frames))
    if trailing_odd_byte:
        pcm += b"\x01"
    fmt = struct.pack("<HHIIHH", 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    if extra_chunk:
        body += b"LIST" + struct.pack("<I", 5) + b"INFOx" + b"\x00"
    body += b"data" + struct.pack("<I", 0xFFFFFFFF) + pcm
    return b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + body


class FakeAudioResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.headers = {"Content-Type": "audio/wav"}

    def __enter__(self) -> "FakeAudioResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._data


class StreamedWavTests(unittest.TestCase):
    def test_duration_comes_from_the_data_chunk_not_the_placeholder_header(self) -> None:
        pcm, fmt = cartesia.parse_streamed_wav(streamed_wav(1.5))
        self.assertEqual(fmt, {"channels": 1, "sample_rate": SAMPLE_RATE, "bits_per_sample": 16})
        self.assertEqual(len(pcm), int(SAMPLE_RATE * 1.5) * 2)
        self.assertAlmostEqual(cartesia.pcm_duration_sec(pcm, fmt), 1.5, places=6)

    def test_other_chunks_and_a_partial_trailing_sample_are_handled(self) -> None:
        pcm, fmt = cartesia.parse_streamed_wav(streamed_wav(0.25, extra_chunk=True, trailing_odd_byte=True))
        self.assertEqual(len(pcm) % 2, 0)
        self.assertAlmostEqual(cartesia.pcm_duration_sec(pcm, fmt), 0.25, places=6)

    def test_rewritten_wav_has_a_valid_header(self) -> None:
        pcm, fmt = cartesia.parse_streamed_wav(streamed_wav(0.5))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chunk.wav"
            cartesia.write_wav(path, pcm, fmt)
            again, again_fmt = cartesia.read_wav(path)
        self.assertEqual(again, pcm)
        self.assertEqual(again_fmt, fmt)

    def test_non_wav_and_empty_streams_are_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            cartesia.parse_streamed_wav(b'{"error": "bad request"}')
        empty = streamed_wav(0.0)
        with self.assertRaises(RuntimeError):
            cartesia.parse_streamed_wav(empty)

    def test_request_body_matches_the_api_contract(self) -> None:
        body = cartesia.cartesia_request_body("sonic-3.6", "voice-123", "你好")
        self.assertEqual(
            body,
            {
                "model_id": "sonic-3.6",
                "transcript": "你好",
                "voice": {"mode": "id", "id": "voice-123"},
                "language": "zh",
                "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100},
            },
        )


class DailyCapTests(unittest.TestCase):
    def test_cap_refuses_once_the_day_is_used_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            ledger = cartesia.DailyCharLedger(path, 100, today="2026-10-22")
            self.assertEqual(ledger.reserve(80), 80)
            self.assertEqual(ledger.check(20), 80)
            with self.assertRaises(cartesia.DailyCapExceeded) as caught:
                ledger.check(21)
            self.assertIn("80 of 100", str(caught.exception))
            with self.assertRaises(cartesia.DailyCapExceeded):
                ledger.reserve(21)
            self.assertEqual(json.loads(path.read_text())["days"]["2026-10-22"]["chars"], 80)
            # A new UTC day starts from zero.
            self.assertEqual(cartesia.DailyCharLedger(path, 100, today="2026-10-23").check(100), 0)

    def test_main_refuses_before_any_request_when_the_cap_would_be_exceeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "deepseek_polish.json").write_text(json.dumps({"voiceover_text": VOICEOVER}, ensure_ascii=False), encoding="utf-8")
            ledger_path = Path(tmp) / "ledger.json"
            cartesia.DailyCharLedger(ledger_path, 5000).reserve(4990)
            env = {"CARTESIA_API_KEY": TEST_KEY, "SEARCHPO_CARTESIA_VOICE": "voice-123", "SEARCHPO_TTS_DAILY_CHARS": "5000"}
            argv = ["cartesia_tts.py", str(run_dir), "--env-file", str(Path(tmp) / "none.env"), "--ledger", str(ledger_path)]
            with patch.dict(os.environ, env), patch.object(sys, "argv", argv), patch("urllib.request.urlopen") as urlopen:
                with self.assertRaises(SystemExit) as caught:
                    cartesia.main()
            urlopen.assert_not_called()
            message = str(caught.exception.code)
            self.assertIn("daily character cap", message)
            self.assertIn("No request was sent", message)
            self.assertNotIn(TEST_KEY, message)
            self.assertFalse((run_dir / "voiceover_manifest.json").exists())
            self.assertEqual(json.loads(ledger_path.read_text())["days"][cartesia.utc_date()]["chars"], 4990)


class CartesiaManifestTests(unittest.TestCase):
    def test_manifest_matches_the_gemini_contract_and_feeds_captions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "deepseek_polish.json").write_text(json.dumps({"voiceover_text": VOICEOVER}, ensure_ascii=False), encoding="utf-8")
            ledger_path = Path(tmp) / "ledger.json"
            env = {"CARTESIA_API_KEY": TEST_KEY, "SEARCHPO_CARTESIA_VOICE": "voice-123", "SEARCHPO_TTS_DAILY_CHARS": "5000", "SEARCHPO_VIDEO_FPS": "30"}
            argv = ["cartesia_tts.py", str(run_dir), "--env-file", str(Path(tmp) / "none.env"), "--ledger", str(ledger_path)]
            requests: list[object] = []

            def fake_urlopen(request: object, timeout: float = 0) -> FakeAudioResponse:
                requests.append(request)
                return FakeAudioResponse(streamed_wav(2.0))

            # ffmpeg loudness normalization is exercised on the operator machine; here it is a no-op.
            with patch.dict(os.environ, env), patch.object(sys, "argv", argv), patch("urllib.request.urlopen", side_effect=fake_urlopen), patch.object(
                cartesia, "normalize_audio"
            ), patch("sys.stdout"):
                self.assertEqual(cartesia.main(), 0)

            self.assertEqual(len(requests), 1)
            request = requests[0]
            self.assertEqual(request.full_url, "https://api.cartesia.ai/tts/bytes")  # type: ignore[attr-defined]
            self.assertEqual(request.get_header("Authorization"), f"Bearer {TEST_KEY}")  # type: ignore[attr-defined]
            self.assertEqual(request.get_header("Cartesia-version"), "2026-08-14")  # type: ignore[attr-defined]
            body = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            self.assertEqual(body["voice"], {"mode": "id", "id": "voice-123"})
            self.assertEqual(body["model_id"], "sonic-3.6")

            manifest = json.loads((run_dir / "voiceover_manifest.json").read_text(encoding="utf-8"))
            self.assertLessEqual(GEMINI_MANIFEST_KEYS, set(manifest))
            self.assertEqual(manifest["provider"], "cartesia")
            self.assertEqual(manifest["status"], "pass")
            self.assertAlmostEqual(manifest["audio_duration_sec"], 2.0, places=3)
            self.assertEqual(manifest["audio_frames"], 60)
            self.assertNotIn(TEST_KEY, json.dumps(manifest))
            ledger = json.loads(ledger_path.read_text())
            self.assertEqual(ledger["days"][cartesia.utc_date()]["chars"], len(manifest["voiceover_text"]))

            audio_path = Path(manifest["audio_path"])
            self.assertEqual(voiceover_manifest_errors(manifest, audio_path), [])
            _path, seconds = require_voiceover_audio(manifest, run_dir)
            self.assertAlmostEqual(seconds, 2.0, places=3)

    def test_chunks_are_never_reused_across_tts_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            chunk = run_dir / "voiceover_part_001.wav"
            pcm, fmt = cartesia.parse_streamed_wav(streamed_wav(0.5))
            cartesia.write_wav(chunk, pcm, fmt)
            record = {"index": 1, "text_hash": "h", "audio_sha256": cartesia.sha256_file(chunk)}
            manifest = {"provider": "cartesia", "model": "sonic-3.6", "voice": "voice-123", "tts_chunking": {"chunks": [record]}}
            reuse = dict(text_hash="h", index=1, model="sonic-3.6", voice="voice-123")
            self.assertTrue(cartesia.reusable_chunk(chunk, previous_manifest=manifest, **reuse))
            self.assertFalse(cartesia.reusable_chunk(chunk, previous_manifest={**manifest, "provider": "gemini"}, **reuse))
            self.assertFalse(cartesia.reusable_chunk(chunk, previous_manifest={**manifest, "voice": "other"}, **reuse))
            (run_dir / "voiceover_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(gemini_previous_manifest(run_dir), {})
            (run_dir / "voiceover_manifest.json").write_text(json.dumps({**manifest, "provider": "gemini"}), encoding="utf-8")
            self.assertEqual(gemini_previous_manifest(run_dir)["provider"], "gemini")

    def test_unknown_tts_provider_is_still_rejected_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "voiceover.wav"
            pcm, fmt = cartesia.parse_streamed_wav(streamed_wav(0.5))
            cartesia.write_wav(audio, pcm, fmt)
            manifest = {
                "status": "pass",
                "provider": "contract",
                "audio_path": str(audio),
                "audio_sha256": cartesia.sha256_file(audio),
                "audio_duration_sec": 0.5,
                "audio_frames": 15,
            }
            self.assertIn("provider is contract", voiceover_manifest_errors(manifest, audio))
            with self.assertRaises(SystemExit):
                require_voiceover_audio(manifest, Path(tmp))


if __name__ == "__main__":
    unittest.main()
