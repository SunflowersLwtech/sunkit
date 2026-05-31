from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_harness.core import write_json
from agent_harness.service_artifacts import (
    build_delivery_package_artifact,
    build_fact_bank_artifact,
    build_scene_plan_artifact,
    build_script_artifact,
    build_topic_brief_artifact,
    build_video_spec_artifact,
    validate_service_artifact,
    write_environment_manifest,
    write_optional_analytics_feedback,
)


def candidate() -> dict[str, object]:
    return {
        "candidate_id": "cand-1",
        "title": "Demo Tool",
        "canonical_url": "https://example.com/demo",
        "risk_flags": ["needs_hands_on_verification"],
    }


def evidence_bundle() -> dict[str, object]:
    return {
        "sources": [
            {
                "id": "primary_url",
                "type": "primary_page",
                "url": "https://example.com/demo",
                "sha256": "abc",
                "title": "Demo Tool",
                "text_chars": 420,
            }
        ],
        "evidence_summary": {
            "source_facts": ["description: Demo Tool helps inspect logs"],
            "constructive_angles": ["Explain the evaluation path"],
        },
    }


class ServiceArtifactTests(unittest.TestCase):
    def test_research_artifacts_keep_compatibility_fields(self) -> None:
        fact_bank = build_fact_bank_artifact(candidate(), evidence_bundle(), [])
        topic_brief = build_topic_brief_artifact(candidate(), fact_bank, [])

        self.assertEqual(fact_bank["schema_version"], 2)
        self.assertTrue(fact_bank["facts"])
        self.assertEqual(fact_bank["source_backed_facts"][0], fact_bank["facts"][0]["claim"])
        self.assertEqual(topic_brief["topic"], "Demo Tool")
        validate_service_artifact("fact_bank", fact_bank)
        validate_service_artifact("topic_brief", topic_brief)

    def test_script_scene_plan_and_video_spec_compile(self) -> None:
        fact_bank = build_fact_bank_artifact(candidate(), evidence_bundle(), [])
        topic_brief = build_topic_brief_artifact(candidate(), fact_bank, [])
        polish = {
            "polished_title": "Demo Tool 为什么值得观察",
            "voiceover_text": "Demo Tool 先看证据。它解决日志排查的问题。最后要跑通再判断。",
            "douyin_desc": "保留证据边界。",
            "storyboard": {
                "version": 1,
                "scenes": [
                    {"type": "statement", "props": {"title": "Demo Tool 先看证据"}},
                    {"type": "bullets", "props": {"heading": "怎么验证", "items": ["跑 demo", "看源码"]}},
                    {"type": "cta", "props": {"text": "跑通再判断"}},
                ],
            },
        }
        script = build_script_artifact(candidate(), polish, topic_brief, fact_bank)
        scene_plan = build_scene_plan_artifact(candidate(), polish, script, fact_bank)
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            video_spec = build_video_spec_artifact(
                run_dir,
                candidate(),
                {
                    "title": "Demo Tool",
                    "fps": 30,
                    "durationInFrames": 300,
                    "storyboard": polish["storyboard"],
                    "audioSrc": "voiceover.wav",
                },
                scene_plan,
                {"sources": [{"id": "primary_url"}]},
            )

        self.assertEqual(script["voiceover_segments"][0]["role"], "hook")
        self.assertEqual(scene_plan["scenes"][1]["planning_type"], "process")
        self.assertEqual(video_spec["scenes"][0]["startFrame"], 0)
        self.assertEqual(sum(scene["durationInFrames"] for scene in video_spec["scenes"]), 300)

    def test_environment_feedback_and_delivery_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            run_dir.mkdir()
            write_json(run_dir / "captions.json", {"segments": []})
            write_json(run_dir / "source_map.json", {"sources": []})
            write_json(run_dir / "artifact_manifest.json", {"status": "pass"})
            env_manifest = write_environment_manifest(root, run_dir, command=["searchpo-test"])
            feedback = write_optional_analytics_feedback(run_dir, {"candidate_id": "cand-1"})
            delivery = build_delivery_package_artifact(
                run_dir,
                {
                    "selected_candidate_id": "cand-1",
                    "selected_candidate_title": "Demo Tool",
                    "execution_profile": "provider",
                    "render_mode": "local",
                    "publish_mode": "contract-check",
                },
                status="pass",
                publish_status="contract-check-pass",
            )

        self.assertIn("topic_intake", env_manifest["service_boundaries"])
        self.assertFalse(feedback["required"])
        self.assertEqual(delivery["platform_target"], "douyin")


if __name__ == "__main__":
    unittest.main()
