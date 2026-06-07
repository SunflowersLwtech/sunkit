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


def passing_gemini_visual_audit() -> dict[str, object]:
    return {
        "status": "pass",
        "video_input_mode": "agent_platform",
        "video_sha256": "video-sha",
        "audit_contract_errors": [],
        "audit": {
            "checks": {
                "video_readable": True,
                "full_native_video_reviewed": True,
                "native_video_audio_reviewed": True,
                "text_not_overlapping": True,
                "candidate_matches_artifacts": True,
                "no_unsupported_claims": True,
                "voiceover_matches_copy": True,
                "voiceover_visual_same_subject": True,
                "captions_match_spoken_audio": True,
                "background_music_mix_safe": True,
                "cover_text_safe": True,
                "no_internal_terms": True,
                "no_hype_without_evidence": True,
                "speech_pronunciation_safe": True,
                "audio_visual_alignment_safe": True,
                "douyin_vertical_format": True,
                "douyin_safe_area": True,
                "publish_ready": True,
                "content_has_constructive_insight": True,
                "central_motion_not_caption_or_progress_only": True,
                "topic_specific_visual": True,
                "not_cards_only_template": True,
                "composition_not_overcrowded": True,
                "single_primary_focal_action": True,
                "no_competing_overlays": True,
                "topic_visual_not_generic_dashboard": True,
            },
            "timeline_reviews": [
                {
                    "timestamp": "00:01",
                    "commentary": "Readable opening visual with a moving evidence panel.",
                    "spoken_audio_observation": "The native MP4 voiceover introduces the selected source-bounded topic and verification frame.",
                    "background_music_observation": "Background music is either absent or mixed below the voiceover at the opening.",
                    "visual_subject": "The central visual shows the selected topic evidence panel and moving interface blocks.",
                    "spoken_subject": "The spoken subject is the selected topic evidence and verification frame.",
                    "audio_visual_subject_alignment": "The opening visual evidence panel and spoken verification frame refer to the same selected topic.",
                    "text_readability": "Title and evidence panel text are readable with strong contrast.",
                    "caption_progress_alignment": "Global caption stays above the reserved bottom safe area.",
                    "motion_observation": "Evidence cards slide into the central visual area.",
                },
                {
                    "timestamp": "00:30",
                    "commentary": "Readable middle visual with a diagram panel changing state.",
                    "spoken_audio_observation": "The native MP4 voiceover explains the same mechanism and tradeoff shown in the diagram.",
                    "background_music_observation": "Music remains below speech and does not mask the middle explanation.",
                    "visual_subject": "The central visual shows the selected topic mechanism diagram and table rows.",
                    "spoken_subject": "The spoken subject is the selected topic mechanism and tradeoff.",
                    "audio_visual_subject_alignment": "The mechanism diagram and table rows match the spoken mechanism and tradeoff explanation.",
                    "text_readability": "Diagram labels and row text remain legible at phone size.",
                    "caption_progress_alignment": "Caption remains separate from the main diagram and progress UI.",
                    "motion_observation": "Diagram panels and table rows animate between states.",
                },
                {
                    "timestamp": "01:00",
                    "commentary": "Readable closing visual with no cropped public copy.",
                    "spoken_audio_observation": "The native MP4 voiceover closes with a verification path for the selected topic.",
                    "background_music_observation": "The closing mix keeps music low and the voiceover remains clearly audible.",
                    "visual_subject": "The central visual shows the selected topic verification gate and CTA.",
                    "spoken_subject": "The spoken subject is the selected topic verification path and boundary.",
                    "audio_visual_subject_alignment": "The verification gate on screen matches the spoken verification path at the ending.",
                    "text_readability": "Closing CTA remains inside frame with no clipped words.",
                    "caption_progress_alignment": "Subtitle timing still follows the spoken beat without overlap.",
                    "motion_observation": "CTA card and flow line move before the outro.",
                },
            ],
            "motion_assessment": {
                "level": "adequate",
                "commentary": "Central evidence cards, diagram panels, tables, and flow lines move through the video.",
            },
            "audio_track_assessment": {
                "voiceover": "The native MP4 voiceover is clear and follows the same selected-topic evidence narrative shown by the visuals.",
                "background_music": "Background music is absent or present only as a low supporting bed below speech.",
                "mix": "Voiceover remains dominant over the mix with no clipping, masking, or audible dropouts.",
                "issues": [],
            },
            "subject_alignment": {
                "spoken_subject": "The voiceover is about the selected source-bounded topic and its verification boundary.",
                "visual_subject": "The central visuals show the same selected topic through evidence panels, mechanism diagram, and verification gates.",
                "matches": True,
                "mismatches": [],
                "evidence": "At 00:01, 00:30, and 01:00 the spoken topic and visible evidence, mechanism, and verification panels match.",
            },
            "rubric_scores": {
                "hook_clarity": 8,
                "scene_pacing": 8,
                "visual_hierarchy": 8,
                "central_animation_richness": 8,
                "topic_visual_fit": 8,
                "caption_safe_area": 8,
                "audio_visual_sync": 8,
                "evidence_guardrail": 8,
            },
            "narrative_structure": {
                "opening_hook": "Opening shows the topic with a readable moving evidence panel.",
                "middle_delivery": "Middle uses a changing diagram panel and table rows to explain mechanism and tradeoff.",
                "ending_payoff": "Ending keeps the CTA inside frame and preserves a verification path.",
                "pacing_issue": "No pacing issue visible because text and motion have enough dwell time.",
            },
            "animation_diagnostics": {
                "main_motion_layers": ["spring evidence card entrance", "staggered table row reveal", "flow line movement"],
                "topic_specific_objects": ["diagram panel", "table rows"],
                "weak_motion": ["progress bar is only supporting chrome"],
                "recommended_repair": "",
            },
            "composition_director": {
                "primary_focal_target": "The central selected-topic diagram panel and its active flow line.",
                "competing_visual_systems": ["Global captions as a secondary safe-area layer"],
                "simultaneous_motion_system_count": 2,
                "clutter_level": "medium",
                "hierarchy_issue": "none, the central diagram panel is the largest visual object.",
                "overload_issue": "none, captions remain secondary and do not compete with the diagram.",
                "director_verdict": "pass",
            },
        },
    }


def passing_horizontal_gemini_visual_audit() -> dict[str, object]:
    audit = passing_gemini_visual_audit()
    nested = audit["audit"]  # type: ignore[index]
    checks = dict(nested["checks"])  # type: ignore[index]
    checks.pop("douyin_vertical_format", None)
    checks.pop("douyin_safe_area", None)
    checks["profile_format_match"] = True
    nested["checks"] = checks  # type: ignore[index]
    return audit


def passing_deterministic_visual_audit() -> dict[str, object]:
    return {
        "schema_version": 2,
        "status": "pass",
        "layout_check": {"status": "pass"},
        "visual_intent_check": {"status": "pass", "primitive_hits": ["diagram"]},
        "motion_check": {"status": "pass", "active_pair_ratio": 0.34, "max_static_seconds": 4.0},
    }


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

    def test_full_canvas_agent_visual_does_not_add_chapter_rail_by_default(self) -> None:
        composition = (ROOT / "src" / "Composition.tsx").read_text(encoding="utf-8")
        self.assertIn("const ProviderChapterBridge", composition)
        self.assertIn("const showProviderChapterBridge", composition)
        self.assertIn("data.agentVisual?.chapter_bridge === true", composition)
        self.assertIn("<ProviderChapterBridge", composition)
        self.assertIn("width: isVertical ? 312 : 380", composition)
        self.assertNotIn("<ProviderChapterObject", composition)
        self.assertNotIn("bottom: isVertical ? 590 : 205", composition)

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
            for name in ["render_metadata_check.json", "visual_audit_deterministic.json"]:
                write_json(run_dir / name, {"status": "pass"} if name == "render_metadata_check.json" else passing_deterministic_visual_audit())
            write_json(run_dir / "gemini_visual_audit.json", passing_gemini_visual_audit())
            write_json(run_dir / "premium_showcase_audit.json", {"status": "pass"})
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
            self.assertEqual(final["final_video"], str(run_dir / "video" / "final.mp4"))
            self.assertEqual(final["final_cover"], str(run_dir / "cover" / "final.jpg"))
            self.assertTrue((run_dir / "RUN.md").is_file())
            gate_names = {gate["name"] for gate in final["board_snapshot"]["gates"]}
            self.assertIn("publish_release_gate", gate_names)
            self.assertNotIn("douyin_live_publish_gate", gate_names)
            self.assertFalse((post_dir / "post_publish_verification.json").exists())

    def test_horizontal_contract_finalization_uses_profile_format_gate(self) -> None:
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
            write_json(run_dir / "render_payload.json", {"orientation": "horizontal", "aspectRatio": "16:9"})
            write_json(run_dir / "render_metadata_check.json", {"status": "pass"})
            write_json(run_dir / "visual_audit_deterministic.json", passing_deterministic_visual_audit())
            write_json(run_dir / "gemini_visual_audit.json", passing_horizontal_gemini_visual_audit())
            write_json(run_dir / "premium_showcase_audit.json", {"status": "pass"})
            write_json(post_dir / "douyin_upload_check.json", {"status": "pass", "publish_mode": "contract-check"})
            board = TaskBoard(run_dir / "harness_board.sqlite3")
            try:
                root_task = board.create_task("root", "root", "test")
                board.set_status(root_task, "running", "test")
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
            self.assertEqual(final["status"], "pass")
            self.assertEqual(final["errors"], [])

    def test_manual_visual_review_failure_blocks_finalization(self) -> None:
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
            for name in ["render_metadata_check.json", "visual_audit_deterministic.json"]:
                write_json(run_dir / name, {"status": "pass"} if name == "render_metadata_check.json" else passing_deterministic_visual_audit())
            write_json(run_dir / "gemini_visual_audit.json", passing_gemini_visual_audit())
            write_json(run_dir / "manual_visual_review.json", {"status": "fail", "reason": "captions overlap provider visual"})
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
                    self.assertEqual(finalize_run_main(), 1)
            finally:
                __import__("sys").argv = old_argv

            final = json.loads((run_dir / "run_final.json").read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "fail")
            self.assertIn("manual visual review", "; ".join(final["errors"]))

    def test_weak_gemini_visual_audit_pass_blocks_finalization(self) -> None:
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
            write_json(run_dir / "render_metadata_check.json", {"status": "pass"})
            write_json(run_dir / "visual_audit_deterministic.json", passing_deterministic_visual_audit())
            write_json(run_dir / "gemini_visual_audit.json", {"status": "pass", "audit": {"summary": "looks fine"}})
            write_json(post_dir / "douyin_upload_check.json", {"status": "pass", "publish_mode": "contract-check"})
            board = TaskBoard(run_dir / "harness_board.sqlite3")
            try:
                root_task = board.create_task("root", "root", "test")
                board.set_status(root_task, "running", "test")
                write_json(run_dir / "agent_run.json", {"root_task_id": root_task})
            finally:
                board.close()

            old_argv = __import__("sys").argv
            try:
                __import__("sys").argv = ["finalize_run.py", str(run_dir), "--publish-mode", "contract-check"]
                with redirect_stdout(StringIO()):
                    self.assertEqual(finalize_run_main(), 1)
            finally:
                __import__("sys").argv = old_argv

            final = json.loads((run_dir / "run_final.json").read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "fail")
            self.assertIn("native video input mode", "; ".join(final["errors"]))
            self.assertIn("timeline_reviews", "; ".join(final["errors"]))

    def test_stale_deterministic_audit_blocks_finalization(self) -> None:
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
            write_json(run_dir / "render_metadata_check.json", {"status": "pass"})
            write_json(run_dir / "visual_audit_deterministic.json", {"status": "pass", "schema_version": 1})
            write_json(run_dir / "gemini_visual_audit.json", passing_gemini_visual_audit())
            write_json(post_dir / "douyin_upload_check.json", {"status": "pass", "publish_mode": "contract-check"})
            board = TaskBoard(run_dir / "harness_board.sqlite3")
            try:
                root_task = board.create_task("root", "root", "test")
                board.set_status(root_task, "running", "test")
                write_json(run_dir / "agent_run.json", {"root_task_id": root_task})
            finally:
                board.close()

            old_argv = __import__("sys").argv
            try:
                __import__("sys").argv = ["finalize_run.py", str(run_dir), "--publish-mode", "contract-check"]
                with redirect_stdout(StringIO()):
                    self.assertEqual(finalize_run_main(), 1)
            finally:
                __import__("sys").argv = old_argv

            final = json.loads((run_dir / "run_final.json").read_text(encoding="utf-8"))
            joined = "; ".join(final["errors"])
            self.assertIn("stale", joined)
            self.assertIn("central motion", joined)


if __name__ == "__main__":
    unittest.main()
