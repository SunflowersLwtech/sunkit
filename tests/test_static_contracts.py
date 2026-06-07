from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from agent_harness.core import Artifact, Gate, TaskBoard, write_json
from scripts.finalize_run import main as finalize_run_main


ROOT = Path(__file__).resolve().parents[1]


class StaticContractTests(unittest.TestCase):
    def test_caption_css_uses_svg_filter_not_jagged_text_shadow(self) -> None:
        css = (ROOT / "src" / "styles.css").read_text(encoding="utf-8")
        captions = css.split("/* ---------- captions ---------- */", 1)[1].split("/* ---------- cover", 1)[0]
        self.assertIn('filter: url("#caption-stroke")', captions)
        self.assertNotIn("text-shadow:", captions)
        self.assertIn("caption-svg-defs", (ROOT / "src" / "Captions.tsx").read_text(encoding="utf-8"))

    def test_storyboard_renderer_uses_offline_fonts_and_transition_series(self) -> None:
        fonts = (ROOT / "src" / "fonts.ts").read_text(encoding="utf-8")
        composition = (ROOT / "src" / "Composition.tsx").read_text(encoding="utf-8")
        self.assertIn("@fontsource/noto-sans-sc/700.css", fonts)
        self.assertIn("@fontsource/inter/latin-900.css", fonts)
        self.assertIn("document.fonts.ready", fonts)
        self.assertIn("TransitionSeries", composition)
        self.assertIn("legacy card fallback is not allowed", composition)
        self.assertNotIn("deriveStoryboardFromCards", composition)

    def test_render_payload_schema_round_trips_premium_director_spec_aliases(self) -> None:
        schema = json.loads((ROOT / "contracts" / "schemas" / "render_payload.schema.json").read_text(encoding="utf-8"))
        self.assertIn("premium_director_spec", schema["properties"])
        self.assertIn("premiumDirectorSpec", schema["properties"])
        self.assertEqual(schema["properties"]["premium_director_spec"], schema["properties"]["premiumDirectorSpec"])

    def test_contract_finalization_has_no_live_gate_or_live_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            post_dir = run_dir / "post"
            video_dir = run_dir / "video"
            cover_dir = run_dir / "cover"
            post_dir.mkdir(parents=True)
            video_dir.mkdir()
            cover_dir.mkdir()
            (video_dir / "final.mp4").write_bytes(b"video")
            (cover_dir / "final.jpg").write_bytes(b"cover")
            write_json(
                run_dir / "artifact_manifest.json",
                {
                    "execution_profile": "provider",
                    "side_effect_tier": "provider",
                    "render_mode": "local",
                    "publish_mode": "contract-check",
                    "selected_candidate_id": "cand-1",
                    "final_video_path": str(video_dir / "final.mp4"),
                    "cover_path": str(cover_dir / "final.jpg"),
                },
            )
            for name in [
                "render_metadata_check.json",
                "visual_audit_deterministic.json",
                "gemini_visual_audit.json",
                "premium_showcase_audit.json",
            ]:
                write_json(run_dir / name, {"status": "pass"})
            write_json(post_dir / "douyin_upload_check.json", {"status": "pass", "publish_mode": "contract-check"})
            board = TaskBoard(run_dir / "harness_board.sqlite3")
            try:
                root_task = board.create_task("root", "root", "test")
                board.set_status(root_task, "running", "test")
                task = board.create_task("douyin_publish", "publish", "test", root_task)
                board.gate(task, Gate("douyin_contract_gate", "pass", "contract only"))
                board.artifact(task, Artifact("douyin_upload_check", post_dir / "douyin_upload_check.json"))
                board.set_status(task, "completed", "test")
                write_json(run_dir / "agent_run.json", {"root_task_id": root_task})
            finally:
                board.close()

            old_argv = __import__("sys").argv
            try:
                __import__("sys").argv = ["finalize_run.py", str(run_dir), "--publish-mode", "contract-check"]
                with redirect_stdout(StringIO()):
                    self.assertEqual(finalize_run_main(), 0)
            finally:
                __import__("sys").argv = old_argv

            final = json.loads((run_dir / "run_final.json").read_text(encoding="utf-8"))
            self.assertEqual(final["execution_profile"], "provider")
            self.assertEqual(final["render_mode"], "local")
            self.assertEqual(final["publish_mode"], "contract-check")
            self.assertEqual(final["premium_showcase_audit_status"], "pass")
            gate_names = {gate["name"] for gate in final["board_snapshot"]["gates"]}
            self.assertIn("publish_release_gate", gate_names)
            self.assertNotIn("douyin_live_publish_gate", gate_names)
            self.assertFalse((post_dir / "post_publish_verification.json").exists())


if __name__ == "__main__":
    unittest.main()
