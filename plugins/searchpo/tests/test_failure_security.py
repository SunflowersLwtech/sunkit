from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_harness.core import _quarantine_partial_artifacts
from scripts.redact_trace_export import assert_final_video_included
from scripts.scan_secrets import scan


class FailureAndSecurityTests(unittest.TestCase):
    def test_failed_provider_partials_are_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "voiceover.wav").write_bytes(b"partial")
            (run_dir / "voiceover_manifest.json").write_text('{"status":"partial"}\n', encoding="utf-8")

            quarantine = _quarantine_partial_artifacts(run_dir, "gemini_tts")

            self.assertIsNotNone(quarantine)
            self.assertFalse((run_dir / "voiceover.wav").exists())
            self.assertTrue((quarantine / "voiceover.wav").is_file())  # type: ignore[union-attr]
            self.assertTrue((quarantine / "quarantine_manifest.json").is_file())  # type: ignore[union-attr]

    def test_secret_scanner_reports_high_confidence_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            fake_key = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
            path.write_text(f'{{"token":"{fake_key}"}}\n', encoding="utf-8")
            report = scan(path)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["finding_count"], 1)

    def test_run_export_requires_final_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "run_final.json").write_text('{"status":"pass"}\n', encoding="utf-8")
            with self.assertRaises(SystemExit) as raised:
                assert_final_video_included(run_dir)
            self.assertIn("video omitted => cannot claim production success", str(raised.exception))

            video = run_dir / "video" / "final.mp4"
            video.parent.mkdir()
            video.write_bytes(b"real-video-required")
            assert_final_video_included(run_dir)


if __name__ == "__main__":
    unittest.main()
