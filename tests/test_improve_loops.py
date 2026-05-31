from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from agent_harness.core import HarnessContext, TaskBoard, write_json
from agent_harness.stages import ContentImproveLoopStage
from scripts.content_scorer import score_target_report
from scripts.deepseek_polish import deepseek_body
from scripts.gemini_visual_audit import classify_audit_result
import agent_harness.stages as stages
import scripts.video_quality_loop as video_loop


def polish_payload(attempt: int, mode: str = "initial") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": "2026-05-31T00:00:00+00:00",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "attempt": attempt,
        "mode": mode,
        "selected_candidate_id": "cand-1",
        "status": "pass",
        "polished_title": f"Demo Tool hook {attempt}",
        "voiceover_text": "Demo Tool 帮开发者把日志排查流程拆清楚，先看机制，再看取舍，最后保留验证边界。",
        "script_text_hash": "hash",
        "douyin_title": f"Demo Tool hook {attempt}",
        "douyin_desc": "Demo Tool 观察稿，先看证据边界。",
        "tags": ["AI工具", "开发工具"],
        "cards": [{"label": "机制", "value": "日志排查", "detail": "先验证"}],
        "storyboard": {
            "version": 1,
            "style": {"theme": "minimal"},
            "scenes": [
                {"type": "statement", "props": {"title": "Demo Tool 为什么值得看", "sub": "先看问题"}},
                {"type": "cta", "props": {"text": "跑通再判断", "footer": "保留证据边界"}},
            ],
        },
        "caveats": ["待验证"],
        "unsafe_claim_hits": [],
        "usage": {"total_tokens": 100},
    }


class ContentImproveLoopTests(unittest.TestCase):
    def test_score_target_report_requires_best_practice_threshold(self) -> None:
        report = score_target_report(
            {"overall": 7.9, "scores": {"hook_strength": 8, "information_density": 6}},
            {"blocking_issues": []},
        )

        self.assertFalse(report["target_met"])
        self.assertTrue(report["eligible_for_revision"])
        self.assertEqual(report["failed_dimensions"], {"information_density": 6.0})

        passing = score_target_report(
            {"overall": 8.4, "scores": {"hook_strength": 8, "information_density": 7}},
            {"blocking_issues": []},
        )
        self.assertTrue(passing["target_met"])
        self.assertFalse(passing["eligible_for_revision"])

    def test_deepseek_revision_prompt_carries_feedback_and_evidence_boundary(self) -> None:
        body = deepseek_body(
            "deepseek-v4-pro",
            {"title": "Demo Tool", "canonical_url": "https://example.com/demo"},
            {"mode": "provider"},
            temperature=0.2,
            video_seconds=12,
            evidence_bundle={"evidence_summary": {"source_facts": ["official fact"], "constructive_angles": ["angle"]}},
            cross_check_review={"status": "pass"},
            previous_polish=polish_payload(1),
            revision_feedback={"overall": 5.7, "failed_dimensions": {"hook_strength": 5}, "suggestions": ["make hook concrete"]},
            attempt=2,
        )

        user = json.loads(body["messages"][1]["content"])
        self.assertEqual(user["task"], "Revise one complete short-form video package using Gemini evaluator feedback.")
        self.assertEqual(user["gemini_feedback"]["failed_dimensions"], {"hook_strength": 5})
        self.assertEqual(user["previous_polish"]["polished_title"], "Demo Tool hook 1")
        self.assertEqual(user["evidence_bundle"]["source_facts"], ["official fact"])
        self.assertIn("Preserve the selected candidate boundary", " ".join(user["revision_rules"]))

    def test_content_loop_promotes_only_passing_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            board = TaskBoard(run_dir / "harness_board.sqlite3")
            old_runner = stages.run_repo_script

            def fake_run(context: HarnessContext, args: list[str], timeout: int = 180, max_retries: int = 3) -> dict[str, Any]:
                output = Path(args[args.index("--output") + 1])
                attempt = int(args[args.index("--attempt") + 1])
                if args[0] == "scripts/deepseek_polish.py":
                    mode = args[args.index("--mode") + 1]
                    write_json(output, polish_payload(attempt, mode))
                elif args[0] == "scripts/content_scorer.py":
                    if attempt == 1:
                        write_json(
                            output,
                            {
                                "overall": 6.1,
                                "verdict": "improve",
                                "target_met": False,
                                "eligible_for_revision": True,
                                "failed_dimensions": {"hook_strength": 5},
                                "suggestions": ["stronger hook"],
                            },
                        )
                    else:
                        write_json(
                            output,
                            {
                                "overall": 8.2,
                                "verdict": "pass",
                                "target_met": True,
                                "eligible_for_revision": False,
                                "failed_dimensions": {},
                                "suggestions": [],
                            },
                        )
                return {"command": " ".join(args), "returncode": 0}

            try:
                stages.run_repo_script = fake_run
                result = ContentImproveLoopStage().run(HarnessContext(root_dir=Path(tmp), run_dir=run_dir, board=board))
            finally:
                stages.run_repo_script = old_runner
                board.close()

            self.assertEqual(result.status, "completed")
            self.assertEqual(json.loads((run_dir / "deepseek_polish.json").read_text())["attempt"], 2)
            self.assertEqual(json.loads((run_dir / "content_score.json").read_text())["overall"], 8.2)
            summary = json.loads((run_dir / "content_optimization_loop.json").read_text())
            self.assertEqual(summary["attempt_count"], 2)
            self.assertEqual(summary["attempts"][1]["mode"], "revise")


class VideoImproveLoopTests(unittest.TestCase):
    def test_visual_audit_routes_failed_checks(self) -> None:
        safe_area = classify_audit_result({"checks": {"douyin_safe_area": False}, "issues": ["caption too low"]}, "fail")
        semantic = classify_audit_result({"checks": {"content_has_constructive_insight": False}, "issues": ["too generic"]}, "fail")
        hard = classify_audit_result({"checks": {"video_readable": False}, "issues": ["blank"]}, "fail")

        self.assertEqual(safe_area["repair_route"], "caption")
        self.assertEqual(semantic["repair_route"], "content")
        self.assertEqual(hard["repair_route"], "hard_fail")

    def test_failed_video_attempt_does_not_publish_or_bind_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            old_render = video_loop.render_attempt
            old_audit = video_loop.audit_attempt

            def fake_render(run_dir_arg: Path, attempt_dir: Path, attempt: int, render_mode: str) -> dict[str, Any]:
                return {"video_path": str(attempt_dir / "rendered_video.mp4"), "cover_path": str(attempt_dir / "rendered_cover.jpg")}

            def fake_audit(run_dir_arg: Path, attempt_dir: Path, attempt: int, video_path: Path) -> dict[str, Any]:
                return {"status": "fail", "repair_route": "hard_fail", "repair_hint": "codec broken", "failed_checks": ["render_metadata"]}

            try:
                video_loop.render_attempt = fake_render
                video_loop.audit_attempt = fake_audit
                old_argv = sys.argv
                sys.argv = [
                    "video_quality_loop.py",
                    str(run_dir),
                    "--execution-profile",
                    "provider",
                    "--render-mode",
                    "local",
                    "--publish-mode",
                    "contract-check",
                ]
                with redirect_stdout(StringIO()):
                    self.assertEqual(video_loop.main(), 1)
            finally:
                sys.argv = old_argv
                video_loop.render_attempt = old_render
                video_loop.audit_attempt = old_audit

            self.assertFalse((run_dir / "artifact_manifest.json").exists())
            self.assertFalse((run_dir / "post" / "douyin_upload_check.json").exists())
            self.assertEqual(json.loads((run_dir / "video_optimization_loop.json").read_text())["status"], "fail")

    def test_repairable_video_attempt_retries_then_promotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(
                run_dir / "render_payload.json",
                {
                    "title": "A very long title that should be shortened by repair",
                    "displayTitle": "A very long title that should be shortened by repair",
                    "storyboard": {
                        "version": 1,
                        "style": {"theme": "radar", "density": "rich", "motion": "punchy"},
                        "scenes": [{"type": "statement", "props": {"title": "A crowded statement title that needs repair"}}],
                    },
                },
            )
            old_render = video_loop.render_attempt
            old_audit = video_loop.audit_attempt
            old_promote = video_loop.promote_attempt

            def fake_render(run_dir_arg: Path, attempt_dir: Path, attempt: int, render_mode: str) -> dict[str, Any]:
                return {"video_path": str(attempt_dir / "rendered_video.mp4"), "cover_path": str(attempt_dir / "rendered_cover.jpg")}

            def fake_audit(run_dir_arg: Path, attempt_dir: Path, attempt: int, video_path: Path) -> dict[str, Any]:
                if attempt == 1:
                    return {"status": "fail", "repair_route": "storyboard", "repair_hint": "text overlaps", "failed_checks": ["text_not_overlapping"]}
                return {"status": "pass", "repair_route": "none", "repair_hint": "", "failed_checks": []}

            def fake_promote(run_dir_arg: Path, attempt_dir: Path, render_info: dict[str, Any], args: Any) -> None:
                write_json(run_dir_arg / "artifact_manifest.json", {"status": "pass", "attempt": 2})

            try:
                video_loop.render_attempt = fake_render
                video_loop.audit_attempt = fake_audit
                video_loop.promote_attempt = fake_promote
                old_argv = sys.argv
                sys.argv = [
                    "video_quality_loop.py",
                    str(run_dir),
                    "--execution-profile",
                    "provider",
                    "--render-mode",
                    "local",
                    "--publish-mode",
                    "contract-check",
                ]
                with redirect_stdout(StringIO()):
                    self.assertEqual(video_loop.main(), 0)
            finally:
                sys.argv = old_argv
                video_loop.render_attempt = old_render
                video_loop.audit_attempt = old_audit
                video_loop.promote_attempt = old_promote

            summary = json.loads((run_dir / "video_optimization_loop.json").read_text())
            self.assertEqual(summary["status"], "pass")
            self.assertEqual(summary["attempt_count"], 2)
            self.assertTrue((run_dir / "artifact_manifest.json").exists())
            self.assertFalse((run_dir / "post" / "douyin_upload_check.json").exists())
            repaired_payload = json.loads((run_dir / "render_payload.json").read_text())
            self.assertEqual(repaired_payload["storyboard"]["style"]["density"], "minimal")


if __name__ == "__main__":
    unittest.main()
