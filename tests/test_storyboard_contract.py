from __future__ import annotations

import unittest

from agent_harness.stages import build_video_payload
from agent_harness.storyboard import storyboard_text_items, validate_storyboard
from scripts.deepseek_polish import unsafe_hits_for


def candidate() -> dict[str, object]:
    return {
        "candidate_id": "cand-1",
        "title": "Demo Tool",
        "summary": "Demo Tool 是一个待验证的工具观察稿。",
        "canonical_url": "https://example.com/demo",
        "source_ids": ["official"],
        "evidence": [{"source": "official"}],
        "signals": {"source_count": 1, "has_code_signal": True, "has_demo_keyword": False},
        "candidate_score": 7.2,
    }


VOICEOVER = {
    "fps": 30,
    "audio_frames": 300,
    "normalized_voiceover_text": "Demo Tool 是一个待验证的工具观察稿，需要跑通 demo 后再判断。",
}
CAPTIONS = [{"text": "待验证工具观察稿", "startFrame": 0, "endFrame": 30}]
AGENT_VISUAL = {
    "enabled": True,
    "render_mode": "full_canvas",
    "description": "Demo Tool 定制 Remotion 画面",
    "component_code": "  return <AbsoluteFill className=\"agent-demo\"><div>{data.displayTitle}</div></AbsoluteFill>;",
    "css": ".agent-demo { background: #070a10; color: #fffdf4; }",
}


class StoryboardContractTests(unittest.TestCase):
    def test_validate_storyboard_bounds_scene_types_and_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown type"):
            validate_storyboard(
                {
                    "version": 1,
                    "scenes": [
                        {"type": "unknown", "props": {"title": "drop me"}},
                    ],
                }
            )

        storyboard = validate_storyboard(
            {
                "version": 1,
                "style": {"theme": "minimal", "density": "rich", "motion": "punchy", "accent": "#ff2d55"},
                "scenes": [
                    {"type": "statement", "weight": 0.2, "props": {"title": "Demo Tool 要先看证据", "sub": "不是结论"}},
                    {"type": "bullets", "props": {"heading": "验证路径", "items": ["跑 demo", "看源码", "复查来源", "多余项", "再多余"]}},
                    {"type": "terminal", "props": {"title": "终端验证", "lines": ["clone", "run tests"]}},
                    {"type": "flow", "props": {"heading": "机制路径", "nodes": ["输入", "分析", "输出"]}},
                    {"type": "code_diff", "props": {"title": "源码检查", "additions": ["看入口模块"], "removals": ["只看星数"]}},
                    {"type": "cta", "props": {"text": "跑通再判断", "footer": "保留边界"}},
                ],
            }
        )

        self.assertEqual([scene["type"] for scene in storyboard["scenes"]], ["statement", "bullets", "terminal", "flow", "code_diff", "cta"])
        self.assertEqual(storyboard["style"]["theme"], "minimal")
        self.assertEqual(len(storyboard["scenes"][1]["props"]["items"]), 4)
        self.assertEqual(storyboard["scenes"][2]["props"]["lines"], ["clone", "run tests"])

    def test_validate_storyboard_rejects_empty_provider_scene(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing provider-authored text"):
            validate_storyboard({"version": 1, "scenes": [{"type": "terminal", "props": {"kicker": "验证"}}]})

    def test_build_video_payload_synthesizes_default_storyboard(self) -> None:
        payload = build_video_payload(candidate(), voiceover_manifest=VOICEOVER, captions=CAPTIONS)

        self.assertIn("storyboard", payload)
        self.assertIn("videoProfile", payload)
        self.assertEqual(payload["orientation"], "horizontal")
        self.assertEqual((payload["width"], payload["height"]), (1920, 1080))
        scene_types = [scene["type"] for scene in payload["storyboard"]["scenes"]]
        self.assertEqual(scene_types[0], "statement")
        self.assertIn("context", scene_types)
        self.assertIn("card", scene_types)
        self.assertEqual(scene_types[-1], "cta")

    def test_github_default_storyboard_injects_premium_repo_scenes(self) -> None:
        repo_candidate = {
            **candidate(),
            "canonical_url": "https://github.com/acme/demo-tool",
            "metrics": {"stars": "1200", "stars_today": "34"},
        }
        payload = build_video_payload(repo_candidate, voiceover_manifest=VOICEOVER, captions=CAPTIONS)

        scene_types = [scene["type"] for scene in payload["storyboard"]["scenes"]]
        self.assertIn("chart", scene_types)
        self.assertIn("terminal", scene_types)
        self.assertIn("flow", scene_types)
        self.assertIn("code_diff", scene_types)
        self.assertLessEqual(scene_types.count("card"), 2)

    def test_build_video_payload_uses_provider_storyboard(self) -> None:
        polish = {
            "polished_title": "Demo Tool 为什么值得观察",
            "voiceover_text": "Demo Tool 是一个待验证的工具观察稿，需要跑通 demo 后再判断。",
            "cards": [{"label": "证据", "value": "官方来源", "detail": "先看 demo"}],
            "agent_visual": AGENT_VISUAL,
            "storyboard": {
                "version": 1,
                "style": {"theme": "minimal", "density": "minimal", "motion": "calm", "chrome": {"topbar": False}},
                "scenes": [
                    {"type": "statement", "props": {"title": "Demo Tool 先看问题", "sub": "别急着吹"}},
                    {"type": "stat", "props": {"value": "1 个来源", "label": "来源边界", "detail": "继续验证"}},
                    {"type": "bullets", "props": {"heading": "下一步", "items": ["跑 demo", "看源码"]}},
                    {"type": "cta", "props": {"text": "跑通再判断", "footer": "保留证据边界"}},
                ],
            },
            "video_profile": {
                "duration_seconds": 45,
                "orientation": "vertical",
                "motion": "calm",
                "animation_style": "evidence_cards",
                "decision_reason": "竖屏适合这个简短观察稿",
            },
        }

        payload = build_video_payload(candidate(), polish=polish, voiceover_manifest=VOICEOVER, captions=CAPTIONS)

        self.assertEqual(payload["storyboard"]["style"]["theme"], "minimal")
        self.assertEqual(payload["videoProfile"]["duration_seconds"], 45)
        self.assertEqual(payload["orientation"], "vertical")
        self.assertEqual((payload["width"], payload["height"]), (1080, 1920))
        self.assertTrue(payload["agentVisual"]["enabled"])
        self.assertTrue(payload["agentVisualRequired"])
        self.assertEqual([scene["type"] for scene in payload["storyboard"]["scenes"]], ["statement", "stat", "bullets", "cta"])

    def test_provider_payload_requires_agent_visual(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "storyboard is required"):
            build_video_payload(
                candidate(),
                polish={
                    "polished_title": "Demo Tool 为什么值得观察",
                    "voiceover_text": "Demo Tool 是一个待验证的工具观察稿，需要跑通 demo 后再判断。",
                    "cards": [{"label": "证据", "value": "官方来源", "detail": "先看 demo"}],
                },
                voiceover_manifest=VOICEOVER,
                captions=CAPTIONS,
            )

    def test_unsafe_term_scan_includes_storyboard_scene_text(self) -> None:
        storyboard = validate_storyboard(
            {
                "version": 1,
                "scenes": [
                    {"type": "statement", "props": {"title": "Demo Tool 最强方案", "sub": "这句话应被拦住"}},
                    {"type": "cta", "props": {"text": "跑通再判断", "footer": "保留证据边界"}},
                ],
            }
        )
        polished = {
            "polished_title": "Demo Tool",
            "voiceover_text": "Demo Tool 是一个观察稿。",
            "douyin_title": "Demo Tool",
            "douyin_desc": "Demo Tool 观察稿",
            "tags": ["AI工具"],
            "cards": [{"label": "证据", "value": "来源", "detail": "待验证"}],
            "storyboard": storyboard,
        }

        self.assertIn("最强", unsafe_hits_for(polished))
        self.assertTrue(any("最强方案" in item for item in storyboard_text_items(storyboard)))


if __name__ == "__main__":
    unittest.main()
