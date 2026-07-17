from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_harness.premium_director import build_premium_director_spec
from agent_harness.premium_director_spec import DirectorSpec, validate_director_spec
from agent_harness.stages import build_video_payload
from scripts.content_scorer import deterministic_content_metrics
from scripts.deterministic_visual_audit import _premium_director_contract_checks
from scripts.premium_showcase_audit import reference_paths_from_dir


def repo_candidate() -> dict[str, object]:
    return {
        "candidate_id": "repo-typed-1",
        "title": "Acme TraceKit",
        "summary": "Acme TraceKit helps developers inspect agent traces.",
        "canonical_url": "https://github.com/acme/tracekit",
        "source_ids": ["official", "github"],
        "evidence": [{"source": "official"}],
        "signals": {"source_count": 2, "has_code_signal": True, "has_demo_keyword": True},
        "metrics": {"stars": "2400", "stars_today": "31"},
        "candidate_score": 8.4,
        "source_kind": "github_repo",
    }


def polish() -> dict[str, object]:
    return {
        "polished_title": "Acme TraceKit 真正解决的不是日志，而是 trace 判断",
        "voiceover_text": "Acme TraceKit 把 agent trace 拆成输入、执行、错误边界和判断框架，解释机制、架构位置、适用场景和失败边界。",
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


VOICEOVER = {
    "fps": 30,
    "audio_frames": 900,
    "normalized_voiceover_text": "Acme TraceKit 把 agent trace 拆成输入、执行、错误边界和判断框架，适合排查复杂工作流。",
}
CAPTIONS = [{"text": "Acme TraceKit 拆清 agent trace", "startFrame": 0, "endFrame": 45}]


class PremiumDirectorSpecTests(unittest.TestCase):
    def test_director_spec_dataclass_round_trip(self) -> None:
        candidate = repo_candidate()
        raw_polish = polish()
        spec = build_premium_director_spec(
            candidate,
            {},
            raw_polish,
            {"duration_seconds": 72, "orientation": "horizontal", "aspect_ratio": "16:9"},
        )
        typed = DirectorSpec.from_mapping(spec)
        round_trip = validate_director_spec(typed.to_mapping())
        self.assertGreaterEqual(len(typed.visual_scenes), 5)
        self.assertGreaterEqual(len({scene.kind for scene in typed.visual_scenes}), 4)
        self.assertTrue(all(scene.teaching_beats for scene in typed.visual_scenes))
        scene_motion = {beat for scene in typed.visual_scenes for beat in scene.motion_beats}
        global_motion = {str(beat.get("type") or "") for beat in typed.motion_beats}
        self.assertIn("camera_push", scene_motion | global_motion)
        self.assertIn("parallax", scene_motion | global_motion)
        self.assertIn("mask_reveal", scene_motion | global_motion)
        self.assertIn("path_draw", scene_motion | global_motion)
        self.assertIn("metric_count", scene_motion | global_motion)
        self.assertIn("typewriter", scene_motion | global_motion)
        self.assertEqual(round_trip["profile"]["orientation"], "horizontal")
        self.assertTrue(all(scene.get("teaching_beats") for scene in round_trip["visual_scenes"]))
        self.assertIn("visual_scenes", round_trip)

    def test_standalone_schema_contains_premium_contract(self) -> None:
        schema_path = Path("contracts/schemas/premium_director_spec.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertIn("visual_scenes", schema["required"])
        self.assertIn("motion_beats", schema["required"])
        scene_enum = schema["properties"]["visual_scenes"]["items"]["properties"]["scene_type"]["enum"]
        self.assertIn("RepoFileTreeReveal", scene_enum)
        self.assertIn("KnowledgeTakeawayScene", scene_enum)
        scene_motion_enum = schema["properties"]["visual_scenes"]["items"]["properties"]["motion_beats"]["items"]["enum"]
        global_motion_enum = schema["properties"]["motion_beats"]["items"]["properties"]["type"]["enum"]
        for motion in ["camera_push", "parallax", "mask_reveal", "path_draw", "metric_count", "typewriter", "morph"]:
            self.assertIn(motion, scene_motion_enum)
            self.assertIn(motion, global_motion_enum)

    def test_deterministic_audit_reports_scene_grammar_families(self) -> None:
        raw_polish = polish()
        raw_polish["premium_director_spec"] = build_premium_director_spec(
            repo_candidate(),
            {},
            raw_polish,
            {"duration_seconds": 72, "orientation": "horizontal", "aspect_ratio": "16:9"},
        )
        payload = build_video_payload(repo_candidate(), polish=raw_polish, voiceover_manifest=VOICEOVER, captions=CAPTIONS)
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "remotion_input_props.json").write_text(json.dumps(payload), encoding="utf-8")
            errors, check = _premium_director_contract_checks(run_dir)
        self.assertFalse(errors)
        self.assertGreaterEqual(check["scene_grammar_family_count"], 3)
        self.assertIn("repo_file_tree", check["scene_grammar_families"])
        self.assertGreaterEqual(check["motion_grammar_family_count"], 5)
        self.assertIn("camera_depth", check["motion_grammar_families"])
        self.assertIn("vector_path_build", check["motion_grammar_families"])
        self.assertIn("metric_counter", check["motion_grammar_families"])
        self.assertIn("typewriter", check["motion_grammar_types"])
        self.assertEqual(check["full_canvas_keynote_scene_count"], check["scene_count"])

    def test_normalizer_upgrades_old_slide_like_motion_spec(self) -> None:
        spec = build_premium_director_spec(
            repo_candidate(),
            {},
            polish(),
            {"duration_seconds": 72, "orientation": "horizontal", "aspect_ratio": "16:9"},
        )
        for scene in spec["visual_scenes"]:
            scene["motion_beats"] = ["reveal"]
            scene["layout"] = "card_panel"
        spec["motion_beats"] = [{"type": "reveal", "target": "scene_1", "intensity": "calm"}]
        typed = DirectorSpec.from_mapping(spec)
        scene_motion = {beat for scene in typed.visual_scenes for beat in scene.motion_beats}
        global_motion = {str(beat.get("type") or "") for beat in typed.motion_beats}
        self.assertIn("camera_push", scene_motion | global_motion)
        self.assertIn("parallax", scene_motion | global_motion)
        self.assertIn("mask_reveal", scene_motion | global_motion)
        self.assertIn("metric_count", scene_motion | global_motion)
        self.assertTrue(all(scene.layout == "full_canvas_keynote" for scene in typed.visual_scenes))

    def test_repo_spec_missing_code_scene_gets_topic_coverage(self) -> None:
        spec = build_premium_director_spec(
            repo_candidate(),
            {},
            polish(),
            {"duration_seconds": 72, "orientation": "horizontal", "aspect_ratio": "16:9"},
        )
        spec["visual_scenes"] = [scene for scene in spec["visual_scenes"] if scene["scene_type"] != "CodeOrTerminalScene"]
        typed = DirectorSpec.from_mapping(spec)
        scene_types = [scene.kind for scene in typed.visual_scenes]
        self.assertIn("CodeOrTerminalScene", scene_types)
        self.assertLess(scene_types.index("CodeOrTerminalScene"), scene_types.index("DecisionMatrixScene"))

    def test_reference_dir_selects_small_video_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.mp4").write_bytes(b"mp4")
            (root / "b.mov").write_bytes(b"mov")
            (root / "c.txt").write_text("ignore", encoding="utf-8")
            (root / "large.mp4").write_bytes(b"x" * 12)
            refs = reference_paths_from_dir(str(root), max_reference_bytes=8)
        self.assertEqual([path.name for path in refs], ["a.mp4", "b.mov"])

    def test_reference_dir_can_recurse_and_include_oversized_for_proxying(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "nested" / "showcase"
            nested.mkdir(parents=True)
            (nested / "large-reference.mp4").write_bytes(b"x" * 12)
            refs = reference_paths_from_dir(
                str(root),
                max_reference_bytes=8,
                recursive=True,
                include_oversized=True,
            )
        self.assertEqual([path.name for path in refs], ["large-reference.mp4"])

    def test_content_metrics_expose_density_and_dismissive_penalty(self) -> None:
        bad_polish = polish()
        bad_polish["voiceover_text"] = f"{bad_polish['voiceover_text']} 需要自己去试。"
        metrics = deterministic_content_metrics(bad_polish, repo_candidate())
        self.assertIn("knowledge_density", metrics)
        self.assertIn("dismissive_phrase_penalty", metrics)
        self.assertGreater(metrics["knowledge_density"]["score"], 0)
        self.assertGreater(metrics["dismissive_phrase_penalty"]["penalty"], 0)


if __name__ == "__main__":
    unittest.main()
