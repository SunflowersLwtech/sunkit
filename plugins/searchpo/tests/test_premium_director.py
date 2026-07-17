from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from agent_harness.agent_visual import require_agent_visual
from agent_harness.content_guard import dismissive_verification_hits, scrub_dismissive_verification_text
from agent_harness.premium_director import build_premium_director_spec, compile_premium_agent_visual
from agent_harness.stages import build_video_payload
import scripts.video_quality_loop as video_loop
from scripts.deepseek_polish import scrub_polish_payload, unsafe_hits_for, viewer_question_endings_for
from scripts.premium_showcase_audit import decide_showcase_status
from scripts.video_quality_loop import premium_showcase_repair_route, preserve_premium_showcase_failure_evidence, reroute_agent_visual_failures


def repo_candidate() -> dict[str, object]:
    return {
        "candidate_id": "repo-1",
        "title": "Acme TraceKit",
        "summary": "Acme TraceKit helps developers inspect agent traces.",
        "canonical_url": "https://github.com/acme/tracekit",
        "source_ids": ["official"],
        "evidence": [{"source": "official"}],
        "signals": {"source_count": 2, "has_code_signal": True, "has_demo_keyword": True},
        "metrics": {"stars": "2400", "stars_today": "31"},
        "candidate_score": 8.4,
        "source_kind": "github_repo",
    }


VOICEOVER = {
    "fps": 30,
    "audio_frames": 900,
    "normalized_voiceover_text": "Acme TraceKit 把 agent trace 拆成输入、执行、错误边界和判断框架，适合排查复杂工作流。",
}

CAPTIONS = [{"text": "Acme TraceKit 拆清 agent trace", "startFrame": 0, "endFrame": 45}]


def polish_with_spec() -> dict[str, object]:
    candidate = repo_candidate()
    polish: dict[str, object] = {
        "polished_title": "Acme TraceKit 真正解决的不是日志，而是 trace 判断",
        "voiceover_text": VOICEOVER["normalized_voiceover_text"],
        "douyin_title": "TraceKit 怎么放进 agent 架构",
        "douyin_desc": "从机制、架构位置、适用场景和失败边界判断 Acme TraceKit。",
        "tags": ["AI工具", "开发工具"],
        "cards": [{"label": "机制", "value": "trace 分层", "detail": "输入、执行、失败边界"}],
        "storyboard": {
            "version": 1,
            "style": {"theme": "minimal", "density": "rich", "motion": "calm"},
            "scenes": [
                {"type": "statement", "props": {"title": "TraceKit 看的是 agent trace 的判断成本", "sub": "先看机制"}},
                {"type": "flow", "props": {"heading": "架构位置", "nodes": ["输入", "执行", "错误", "判断框架"]}},
                {"type": "terminal", "props": {"title": "最小工作流", "lines": ["collect traces", "group failures", "compare runs"]}},
                {"type": "cta", "props": {"text": "用机制和失败边界判断适用场景", "footer": "证据边界内"}},
            ],
        },
        "video_profile": {"duration_seconds": 72, "orientation": "horizontal", "aspect_ratio": "16:9", "motion": "calm"},
        "caveats": ["只在证据边界内判断适用场景"],
    }
    polish["premium_director_spec"] = build_premium_director_spec(
        candidate,
        {},
        polish,
        {"duration_seconds": 72, "orientation": "horizontal", "aspect_ratio": "16:9"},
    )
    return polish


class PremiumDirectorTests(unittest.TestCase):
    def test_content_guard_rewrites_banned_dismissive_language(self) -> None:
        bad = {"cta": "按证据验证，不急着下结论。具体细节未知，需要自己去试。uv 还需验证兼容性。"}
        self.assertTrue(dismissive_verification_hits(bad))
        clean = scrub_dismissive_verification_text(bad)
        self.assertFalse(dismissive_verification_hits(clean))
        self.assertIn("机制", clean["cta"])
        self.assertIn("失败边界", clean["cta"])
        self.assertIn("兼容性边界", clean["cta"])

    def test_content_guard_rewrites_unsupported_rank_claims(self) -> None:
        bad = {
            "voiceover_text": "这是第一批值得关注的 10x 方案，不要说成最强或 only choice。",
            "douyin_title": "第一眼看懂 TraceKit",
            "cards": [{"label": "最强", "value": "唯一", "detail": "刚发布"}],
        }
        clean = scrub_dismissive_verification_text(bad)
        self.assertFalse(unsafe_hits_for(clean))
        rendered = json.dumps(clean, ensure_ascii=False)
        self.assertIn("关键", rendered)
        self.assertIn("高价值", rendered)

    def test_polish_scrubber_replaces_viewer_question_ending(self) -> None:
        bad = {
            "voiceover_text": "TraceKit 把机制、架构位置和失败边界拆清楚。你会优先采用它，还是先跑核心逻辑？",
            "douyin_desc": "讲清机制和判断框架。大家会怎么选？",
        }
        clean = scrub_polish_payload(bad)
        self.assertFalse(viewer_question_endings_for(clean))
        self.assertIn("判断顺序", clean["voiceover_text"])
        self.assertIn("失败边界", clean["voiceover_text"])

    def test_compiler_emits_trusted_module_visual(self) -> None:
        spec = build_premium_director_spec(
            repo_candidate(),
            {},
            polish_with_spec(),
            {"duration_seconds": 72, "orientation": "horizontal", "aspect_ratio": "16:9"},
        )
        self.assertGreaterEqual(len(spec["visual_scenes"]), 5)
        self.assertGreaterEqual(len({scene["scene_type"] for scene in spec["visual_scenes"]}), 4)
        self.assertGreaterEqual(len(spec["topic_objects"]), 3)
        visual = require_agent_visual(compile_premium_agent_visual(spec))
        self.assertEqual(visual["source"], "premium_director_compiler")
        self.assertIn("PremiumDirectorVisual", visual["module_code"])
        self.assertNotIn("data.cards", visual["module_code"])
        self.assertNotIn("data.summary", visual["module_code"])

    def test_provider_payload_uses_premium_director_compiler(self) -> None:
        payload = build_video_payload(
            repo_candidate(),
            polish=polish_with_spec(),
            voiceover_manifest=VOICEOVER,
            captions=CAPTIONS,
        )
        self.assertTrue(payload["agentVisualRequired"])
        self.assertEqual(payload["agentVisual"]["source"], "premium_director_compiler")
        self.assertTrue(payload["agentVisual"]["module_code"])
        self.assertIn("premium_director_spec", payload)
        self.assertIn("premiumDirectorSpec", payload)
        self.assertEqual(payload["premium_director_spec"], payload["premiumDirectorSpec"])
        self.assertGreaterEqual(len(payload["premiumDirectorSpec"]["visual_scenes"]), 5)
        self.assertEqual(payload["orientation"], "horizontal")

    def test_premium_showcase_accepts_pass_verdict_all_checks_scores_at_least_eight(self) -> None:
        audit = {
            "verdict": "pass",
            "checks": {
                "premium_visual_language": True,
                "topic_specific_scene_design": True,
                "not_generic_radar_or_cards": True,
                "not_ppt_or_slide_deck": True,
                "cinematic_motion_depth": True,
                "information_motion_primitives": True,
                "knowledge_sharing_content": True,
                "motion_comfort": True,
                "readability_and_safe_area": True,
                "reference_level_depth_or_clear_gap": True,
            },
            "scores": {
                "visual_premium": "8",
                "topic_specificity": "8",
                "knowledge_value": "8",
                "motion_polish": "8",
                "overall": "8",
            },
            "issues": [],
        }
        status, reason = decide_showcase_status(audit)
        self.assertEqual(status, "pass")
        self.assertTrue(reason["strict_score_pass"])
        self.assertFalse(reason["low_scores"])

    def test_premium_showcase_rejects_seven_score_even_when_checks_pass(self) -> None:
        audit = {
            "verdict": "pass",
            "checks": {
                "premium_visual_language": True,
                "topic_specific_scene_design": True,
                "not_generic_radar_or_cards": True,
                "not_ppt_or_slide_deck": True,
                "cinematic_motion_depth": True,
                "information_motion_primitives": True,
                "knowledge_sharing_content": True,
                "motion_comfort": True,
                "readability_and_safe_area": True,
                "reference_level_depth_or_clear_gap": True,
            },
            "scores": {
                "visual_premium": "7",
                "topic_specificity": "8",
                "knowledge_value": "8",
                "motion_polish": "7",
                "overall": "7",
            },
            "issues": [],
        }
        status, reason = decide_showcase_status(audit)
        self.assertEqual(status, "fail")
        self.assertIn("visual_premium", reason["low_scores"])
        self.assertIn("motion_polish", reason["low_scores"])
        self.assertIn("overall", reason["low_scores"])

    def test_premium_showcase_rejects_missing_non_ppt_motion_checks(self) -> None:
        audit = {
            "verdict": "pass",
            "checks": {
                "premium_visual_language": True,
                "topic_specific_scene_design": True,
                "not_generic_radar_or_cards": True,
                "knowledge_sharing_content": True,
                "motion_comfort": True,
                "readability_and_safe_area": True,
                "reference_level_depth_or_clear_gap": True,
            },
            "scores": {"overall": "9"},
            "issues": [],
        }
        status, reason = decide_showcase_status(audit)
        self.assertEqual(status, "fail")
        self.assertIn("not_ppt_or_slide_deck", reason["missing_required_checks"])
        self.assertIn("cinematic_motion_depth", reason["missing_required_checks"])
        self.assertIn("information_motion_primitives", reason["missing_required_checks"])

    def test_agent_visual_layout_failures_do_not_content_backtrack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "render_payload.json").write_text(
                json.dumps({"agentVisualRequired": True, "agentVisual": {"enabled": True}}),
                encoding="utf-8",
            )
            decision = {
                "status": "fail",
                "repair_route": "storyboard",
                "repair_hint": "topic object overlap in premium director scene",
                "failed_checks": ["text_not_overlapping"],
            }
            updated = reroute_agent_visual_failures(run_dir, decision)
            self.assertEqual(updated["repair_route"], "hard_fail")
            self.assertEqual(updated["repair_domain"], "agent_visual_compiler")
            self.assertIn("premium_director_spec/compiler", updated["repair_hint"])

    def test_premium_showcase_low_visual_scores_do_not_content_backtrack(self) -> None:
        route, domain, hint = premium_showcase_repair_route(
            {
                "status": "fail",
                "status_reason": {
                    "low_scores": ["visual_premium", "motion_polish", "overall"],
                    "failed_checks": [],
                },
            }
        )
        self.assertEqual(route, "hard_fail")
        self.assertEqual(domain, "premium_visual_compiler")
        self.assertIn("low premium scores", hint)

    def test_premium_showcase_route_uses_direct_scores_and_checks(self) -> None:
        route, domain, hint = premium_showcase_repair_route(
            {
                "status": "fail",
                "checks": {
                    "premium_visual_language": True,
                    "topic_specific_scene_design": True,
                    "not_generic_radar_or_cards": True,
                    "not_ppt_or_slide_deck": False,
                    "cinematic_motion_depth": False,
                    "information_motion_primitives": True,
                    "knowledge_sharing_content": True,
                    "motion_comfort": True,
                    "readability_and_safe_area": True,
                    "reference_level_depth_or_clear_gap": True,
                },
                "scores": {
                    "visual_premium": "7",
                    "topic_specificity": "8",
                    "knowledge_value": "8",
                    "motion_polish": "7",
                    "overall": "7",
                },
                "issues": ["Feels like a slide deck instead of a premium Remotion scene."],
                "repair_hint": "Add depth, camera motion, and information-motion primitives.",
            }
        )
        self.assertEqual(route, "hard_fail")
        self.assertEqual(domain, "premium_visual_compiler")
        self.assertIn("not_ppt_or_slide_deck", hint)

    def test_premium_showcase_failure_evidence_preserves_nested_audit_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            attempt_dir = run_dir / "optimization" / "video" / "attempt-01"
            attempt_dir.mkdir(parents=True)
            premium_path = attempt_dir / "premium_showcase_audit.json"
            premium_prompt_path = attempt_dir / "premium_showcase_audit_prompt.json"
            premium_prompt_path.write_text(json.dumps({"prompt": "audit"}), encoding="utf-8")

            preserve_premium_showcase_failure_evidence(
                run_dir,
                premium_path,
                premium_prompt_path,
                {
                    "status": "fail",
                    "scores": None,
                    "checks": None,
                    "audit": {
                        "checks": {
                            "premium_visual_language": True,
                            "cinematic_motion_depth": False,
                        },
                        "scores": {
                            "visual_premium": "7",
                            "motion_polish": "7",
                            "overall": "7",
                        },
                        "issues": ["Missing depth and camera choreography."],
                        "repair_brief": "Rebuild the premium visual compiler scene with depth layers.",
                    },
                },
                repair_route="hard_fail",
                repair_domain="premium_visual_compiler",
                repair_hint="Premium visual compiler repair required.",
            )

            root_audit = json.loads((run_dir / "premium_showcase_audit.json").read_text(encoding="utf-8"))
            attempt_audit = json.loads(premium_path.read_text(encoding="utf-8"))
            for audit in (root_audit, attempt_audit):
                self.assertEqual(audit["status"], "fail")
                self.assertEqual(audit["repair_route"], "hard_fail")
                self.assertEqual(audit["repair_domain"], "premium_visual_compiler")
                self.assertEqual(audit["scores"]["visual_premium"], "7")
                self.assertFalse(audit["checks"]["cinematic_motion_depth"])
                self.assertEqual(audit["issues"], ["Missing depth and camera choreography."])
                self.assertIn("depth layers", audit["repair_hint"])
            self.assertTrue((run_dir / "premium_showcase_audit_prompt.json").is_file())

    def test_premium_showcase_pure_knowledge_gap_can_content_backtrack(self) -> None:
        route, domain, _ = premium_showcase_repair_route(
            {
                "status": "fail",
                "status_reason": {
                    "low_scores": ["knowledge_value"],
                    "failed_checks": [],
                },
            }
        )
        self.assertEqual(route, "content")
        self.assertEqual(domain, "knowledge_sharing_content")

    def test_video_optimization_summary_records_route_and_repair_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            old_render = video_loop.render_attempt
            old_audit = video_loop.audit_attempt

            def fake_render(run_dir_arg: Path, attempt_dir: Path, attempt: int, render_mode: str, publish_mode: str = "contract-check") -> dict[str, Any]:
                return {"video_path": str(attempt_dir / "rendered_video.mp4"), "cover_path": str(attempt_dir / "rendered_cover.jpg")}

            def fake_audit(run_dir_arg: Path, attempt_dir: Path, attempt: int, video_path: Path) -> dict[str, Any]:
                return {
                    "status": "fail",
                    "repair_route": "hard_fail",
                    "repair_domain": "premium_visual_compiler",
                    "repair_hint": "Premium showcase audit failed at the visual/compiler bar.",
                    "failed_checks": ["cinematic_motion_depth"],
                    "premium_showcase": {"status": "fail", "scores": {"overall": "7"}},
                }

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

            summary = json.loads((run_dir / "video_optimization_loop.json").read_text(encoding="utf-8"))
            attempt = summary["attempts"][0]
            self.assertEqual(attempt["route"], "hard_fail")
            self.assertEqual(attempt["repair_route"], "hard_fail")
            self.assertEqual(attempt["repair_domain"], "premium_visual_compiler")
            self.assertEqual(attempt["decision"]["route"], "hard_fail")
            self.assertEqual(attempt["decision"]["repair_domain"], "premium_visual_compiler")


if __name__ == "__main__":
    unittest.main()
