from __future__ import annotations

import unittest
import os
from unittest.mock import patch

from agent_harness.agent_visual import require_agent_visual
from agent_harness.service_artifacts import build_script_artifact
from agent_harness.stages import build_video_payload
from agent_harness.storyboard import storyboard_text_items, validate_storyboard
from agent_harness.video_profile import choose_video_profile, normalize_video_profile
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
    "css": ".agent-demo { background: #263449; color: #fffdf4; }",
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

    def test_validate_storyboard_accepts_statement_text_alias(self) -> None:
        storyboard = validate_storyboard({"version": 1, "scenes": [{"type": "statement", "props": {"text": "Demo Tool 先看问题"}}]})

        self.assertEqual(storyboard["scenes"][0]["props"]["title"], "Demo Tool 先看问题")

    def test_validate_storyboard_accepts_card_text_aliases(self) -> None:
        storyboard = validate_storyboard(
            {"version": 1, "scenes": [{"type": "card", "props": {"title": "源码边界", "text": "先跑 demo 再判断"}}]}
        )

        self.assertEqual(storyboard["scenes"][0]["props"]["value"], "源码边界")
        self.assertEqual(storyboard["scenes"][0]["props"]["detail"], "先跑 demo 再判断")

    def test_validate_storyboard_accepts_card_label_alias(self) -> None:
        storyboard = validate_storyboard({"version": 1, "scenes": [{"type": "card", "props": {"label": "源码边界"}}]})

        self.assertEqual(storyboard["scenes"][0]["props"]["value"], "源码边界")

    def test_validate_storyboard_accepts_code_diff_title_alias(self) -> None:
        storyboard = validate_storyboard({"version": 1, "scenes": [{"type": "code_diff", "props": {"title": "源码验证路径"}}]})

        self.assertEqual(storyboard["scenes"][0]["props"]["title"], "源码验证路径")

    def test_validate_storyboard_accepts_compare_text_alias(self) -> None:
        storyboard = validate_storyboard({"version": 1, "scenes": [{"type": "compare", "props": {"title": "适合和不适合分开看"}}]})

        self.assertEqual(storyboard["scenes"][0]["props"]["left"], "适合和不适合分开看")

    def test_validate_storyboard_accepts_terminal_title_alias(self) -> None:
        storyboard = validate_storyboard({"version": 1, "scenes": [{"type": "terminal", "props": {"title": "终端验证路径"}}]})

        self.assertEqual(storyboard["scenes"][0]["props"]["title"], "终端验证路径")

    def test_validate_storyboard_accepts_engineering_theme_and_scene_types(self) -> None:
        storyboard = validate_storyboard(
            {
                "version": 1,
                "style": {"theme": "engineering", "density": "minimal", "motion": "calm"},
                "scenes": [
                    {"type": "statement", "props": {"title": "Demo Tool 工程拆解"}},
                    {"type": "act_card", "props": {"detail": "The Engine"}},
                    {"type": "code_block", "props": {"filename": "engine.py", "lines": ["def run(ctx):", "    return decide(ctx)"]}},
                    {"type": "node_graph", "props": {"center": "planner", "nodes": ["research", "impl", "audit"]}},
                    {"type": "decision_table", "props": {"title": "规则到输出", "rules": ["证据不足 -> stop"], "categories": ["blocked"]}},
                    {"type": "closing", "props": {"mark": "searchpo"}},
                ],
            }
        )

        self.assertEqual(storyboard["style"]["theme"], "engineering")
        self.assertEqual(storyboard["style"]["accent"], "#f59e0b")
        self.assertEqual(storyboard["scenes"][2]["props"]["lines"], ["def run(ctx):", "    return decide(ctx)"])
        self.assertEqual(storyboard["scenes"][3]["props"]["nodes"], ["research", "impl", "audit"])
        self.assertEqual(storyboard["scenes"][4]["props"]["rules"], ["证据不足 -> stop"])
        self.assertEqual(storyboard["scenes"][5]["props"]["mark"], "searchpo")

    def test_validate_storyboard_rejects_title_only_structured_engineering_scenes(self) -> None:
        for scene_type in ["code_block", "node_graph", "decision_table"]:
            with self.subTest(scene_type=scene_type):
                with self.assertRaisesRegex(ValueError, "missing provider-authored text"):
                    validate_storyboard({"version": 1, "scenes": [{"type": scene_type, "props": {"title": "只有标题"}}]})

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
            "voiceover_text": "Demo Tool 的核心文件在 demo/memory/main.py，并按 user_id、agent_id 或 run_id 做隔离。",
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
                "decision_reason": "手机抖音竖屏适合这个简短观察稿",
            },
        }

        payload = build_video_payload(candidate(), polish=polish, voiceover_manifest=VOICEOVER, captions=CAPTIONS)

        self.assertEqual(payload["storyboard"]["style"]["theme"], "minimal")
        self.assertIn("demo 的 memory 里的 main Python 文件", payload["summary"])
        self.assertIn("用户 ID", payload["summary"])
        self.assertNotIn("user_id", payload["summary"])
        self.assertEqual(payload["videoProfile"]["duration_seconds"], 45)
        self.assertEqual(payload["orientation"], "vertical")
        self.assertEqual((payload["width"], payload["height"]), (1080, 1920))
        self.assertTrue(payload["agentVisual"]["enabled"])
        self.assertTrue(payload["agentVisualRequired"])
        self.assertEqual([scene["type"] for scene in payload["storyboard"]["scenes"]], ["statement", "stat", "bullets", "cta"])

    def test_build_video_payload_preserves_agent_visual_fallback_markers(self) -> None:
        polish = {
            "polished_title": "Demo Tool 为什么值得观察",
            "voiceover_text": "Demo Tool 的核心文件在 demo/memory/main.py，需要按真实 demo 验证。",
            "cards": [{"label": "证据", "value": "官方来源", "detail": "先看 demo"}],
            "agent_visual": {
                **AGENT_VISUAL,
                "fallback_reason": "layout contract violation",
                "_agent_visual_fallback_applied": True,
            },
            "storyboard": {
                "version": 1,
                "scenes": [
                    {"type": "statement", "props": {"title": "Demo Tool 先看问题", "sub": "别急着吹"}},
                    {"type": "cta", "props": {"text": "跑通再判断", "footer": "保留证据边界"}},
                ],
            },
            "video_profile": {"duration_seconds": 45, "orientation": "vertical"},
            "_agent_visual_fallback_applied": True,
            "_agent_visual_fallback_reason": "layout contract violation",
        }

        payload = build_video_payload(candidate(), polish=polish, voiceover_manifest=VOICEOVER, captions=CAPTIONS)

        self.assertTrue(payload["_agent_visual_fallback_applied"])
        self.assertEqual(payload["_agent_visual_fallback_reason"], "layout contract violation")
        self.assertEqual(payload["agentVisual"]["fallback_reason"], "layout contract violation")
        self.assertTrue(payload["agentVisual"]["_agent_visual_fallback_applied"])

    def test_agent_visual_allows_aggressive_absolute_layout(self) -> None:
        visual = require_agent_visual(
            {
                "enabled": True,
                "render_mode": "full_canvas",
                "component_code": """
const chartBottom = height - 200;
return <AbsoluteFill style={{backgroundColor: '#263449'}}>
  <div style={{position: 'absolute', bottom: chartBottom, height: 300}}>Chart</div>
</AbsoluteFill>;
""",
                "css": "",
            }
        )

        self.assertTrue(visual["enabled"])

    def test_agent_visual_rejects_near_black_canvas_background(self) -> None:
        with self.assertRaisesRegex(ValueError, "background is too close to black"):
            require_agent_visual(
                {
                    "enabled": True,
                    "render_mode": "full_canvas",
                    "component_code": "return <AbsoluteFill style={{backgroundColor: '#0a0a0a'}}><div>Chart</div></AbsoluteFill>;",
                    "css": "",
                }
            )

    def test_agent_visual_rejects_provider_caption_overlay(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not render its own captions"):
            require_agent_visual(
                {
                    "enabled": True,
                    "render_mode": "full_canvas",
                    "component_code": """
const currentCaption = data.captions?.[0];
return <AbsoluteFill style={{backgroundColor: '#263449'}}>
  <div className="agent-visual-caption">{currentCaption?.text}</div>
</AbsoluteFill>;
""",
                    "css": ".agent-visual-caption { position: absolute; bottom: 286px; }",
                }
            )

    def test_agent_visual_rejects_motion_overload(self) -> None:
        with self.assertRaisesRegex(ValueError, "motion comfort violation"):
            require_agent_visual(
                {
                    "enabled": True,
                    "render_mode": "full_canvas",
                    "module_code": """
import React, {useMemo} from 'react';
import {AbsoluteFill} from 'remotion';
export const AgentVisualGenerated = ({frame}) => {
  const flowPackets = useMemo(() => Array.from({length: 12}, (_, index) => index), []);
  const gridDots = useMemo(() => Array.from({length: 42}, (_, index) => index), []);
  return <AbsoluteFill style={{backgroundColor: '#263449'}}>
    <svg>
      <filter id="wideGlow"><feGaussianBlur stdDeviation="8" /></filter>
      {gridDots.map((dot) => <circle key={dot} cx={dot * 4 + Math.sin(frame / 9) * 12} cy={42} r={4} />)}
      {flowPackets.map((packet) => <g key={packet} filter="url(#wideGlow)" transform={`translate(${packet * 20} ${Math.sin(frame / 10) * 120}) rotate(${Math.sin(frame / 8) * 16})`} />)}
      <path strokeDashoffset={-frame * 3} />
    </svg>
  </AbsoluteFill>;
};
""",
                    "css": "",
                }
            )

    def test_agent_visual_accepts_full_module_code_with_imports(self) -> None:
        visual = require_agent_visual(
            {
                "enabled": True,
                "render_mode": "full_canvas",
                "module_code": """
import React from 'react';
import {AbsoluteFill, interpolate} from 'remotion';
import type {AgentVisualProps} from '../AgentVisualTypes';

export const AgentVisualGenerated: React.FC<AgentVisualProps> = ({frame, data}) => {
  const x = interpolate(frame, [0, 30], [0, 120], {extrapolateRight: 'clamp'});
  return <AbsoluteFill style={{backgroundColor: '#263449', color: '#fff'}}><div style={{transform: `translateX(${x}px)`}}>Repo graph {data.displayTitle}</div></AbsoluteFill>;
};
""",
                "css": "",
            }
        )

        self.assertTrue(visual["enabled"])
        self.assertIn("export const AgentVisualGenerated", visual["module_code"])

    def test_agent_visual_repairs_minified_ts_nocheck_module(self) -> None:
        visual = require_agent_visual(
            {
                "enabled": True,
                "render_mode": "full_canvas",
                "module_code": (
                    "// @ts-nocheck import React from 'react'; "
                    "import {AbsoluteFill} from 'remotion'; "
                    "export const AgentVisualGenerated = () => "
                    "<AbsoluteFill style={{backgroundColor: '#263449'}} />;"
                ),
                "css": "",
            }
        )

        self.assertTrue(visual["enabled"])
        self.assertTrue(visual["module_code"].startswith("// @ts-nocheck\nimport React"))
        self.assertIn("export const AgentVisualGenerated", visual["module_code"])

    def test_agent_visual_rejects_export_inside_line_comment(self) -> None:
        with self.assertRaisesRegex(ValueError, "named AgentVisualGenerated"):
            require_agent_visual(
                {
                    "enabled": True,
                    "render_mode": "full_canvas",
                    "module_code": "// export const AgentVisualGenerated = () => null;",
                    "css": "",
                }
            )

    def test_agent_visual_rejects_module_env_access(self) -> None:
        with self.assertRaisesRegex(ValueError, "blocked local secret"):
            require_agent_visual(
                {
                    "enabled": True,
                    "render_mode": "full_canvas",
                    "module_code": "export const AgentVisualGenerated = () => <div>{process.env.OPENAI_API_KEY}</div>;",
                    "css": "",
                }
            )

    def test_agent_visual_rejects_direct_captions_variable(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not access captions"):
            require_agent_visual(
                {
                    "enabled": True,
                    "render_mode": "full_canvas",
                    "component_code": "return <AbsoluteFill style={{backgroundColor: '#263449'}}><div>{captions}</div></AbsoluteFill>;",
                    "css": "",
                }
            )

    def test_agent_visual_rejects_compatibility_cards_surface(self) -> None:
        with self.assertRaisesRegex(ValueError, "compatibility cards"):
            require_agent_visual(
                {
                    "enabled": True,
                    "render_mode": "full_canvas",
                    "component_code": "const safeCards = data.cards || []; return <AbsoluteFill style={{backgroundColor: '#263449'}}>{safeCards.length}</AbsoluteFill>;",
                    "css": "",
                }
            )

    def test_agent_visual_allows_bottom_positioning_after_aggressive_mode(self) -> None:
        visual = require_agent_visual(
            {
                "enabled": True,
                "render_mode": "full_canvas",
                "component_code": "return <AbsoluteFill style={{backgroundColor: '#263449'}}><div className=\"metric-panel\">Chart</div></AbsoluteFill>;",
                "css": ".metric-panel { position: absolute; bottom: 520px; }",
            }
        )

        self.assertTrue(visual["enabled"])

    def test_agent_visual_rejects_raw_summary_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not render full data.summary"):
            require_agent_visual(
                {
                    "enabled": True,
                    "render_mode": "full_canvas",
                    "component_code": "return <AbsoluteFill style={{backgroundColor: '#263449'}}><div>{data.summary}</div></AbsoluteFill>;",
                    "css": "",
                }
            )

    def test_agent_visual_rejects_internal_evidence_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not expose internal evidence metadata"):
            require_agent_visual(
                {
                    "enabled": True,
                    "render_mode": "full_canvas",
                    "component_code": "return <AbsoluteFill style={{backgroundColor: '#263449'}}><div>{data.evidenceLevel}</div></AbsoluteFill>;",
                    "css": "",
                }
            )

    def test_agent_visual_rejects_this_destructuring(self) -> None:
        with self.assertRaisesRegex(ValueError, "not destructure from this"):
            require_agent_visual(
                {
                    "enabled": True,
                    "render_mode": "full_canvas",
                    "component_code": "const {data} = this; return <AbsoluteFill style={{backgroundColor: '#263449'}}><div>{data.title}</div></AbsoluteFill>;",
                    "css": "",
                }
            )

    def test_github_payload_uses_premium_repo_visual(self) -> None:
        repo_candidate = {
            **candidate(),
            "canonical_url": "https://github.com/acme/demo-tool",
            "source_kind": "github_repo",
        }
        polish = {
            "polished_title": "Demo Tool",
            "voiceover_text": VOICEOVER["normalized_voiceover_text"],
            "douyin_title": "Demo Tool",
            "douyin_desc": "Demo",
            "tags": ["AI"],
            "cards": [{"label": "API", "value": "compress()", "detail": "source backed"}],
            "storyboard": {
                "version": 1,
                "style": {"theme": "engineering", "motion": "calm"},
                "scenes": [
                    {"type": "statement", "props": {"title": "Demo Tool"}},
                    {"type": "flow", "props": {"title": "Repo path", "nodes": ["input", "core", "verify"]}},
                    {"type": "cta", "props": {"text": "Verify"}},
                ],
            },
            "agent_visual": {
                "enabled": True,
                "render_mode": "full_canvas",
                "component_code": "return <AbsoluteFill style={{backgroundColor: '#0a0a0a'}} />;",
            },
            "video_profile": {"duration_seconds": 90, "orientation": "horizontal", "aspect_ratio": "16:9"},
            "_agent_visual_fallback_applied": True,
            "_agent_visual_fallback_reason": "provider visual rejected",
        }

        payload = build_video_payload(repo_candidate, polish=polish, voiceover_manifest=VOICEOVER, captions=CAPTIONS)

        self.assertEqual(payload["agentVisual"]["source"], "searchpo_premium_repo_visual")
        self.assertIn("PremiumRepoVisual", payload["agentVisual"]["module_code"])
        self.assertNotIn("_agent_visual_fallback_applied", payload)

    def test_video_profile_keeps_long_duration_and_defaults_repo_to_horizontal(self) -> None:
        repo_candidate = {
            **candidate(),
            "canonical_url": "https://github.com/acme/demo-tool",
            "signals": {"has_code_signal": True},
        }
        with patch.dict(os.environ, {"SEARCHPO_VIDEO_SECONDS": "300"}, clear=False):
            profile = choose_video_profile(repo_candidate)

        self.assertEqual(profile["duration_seconds"], 300)
        self.assertEqual(profile["orientation"], "horizontal")
        normalized = normalize_video_profile(
            {"duration_seconds": 420, "orientation": "horizontal", "aspect_ratio": "16:9"},
            fallback=profile,
        )
        self.assertEqual(normalized["duration_seconds"], 420)
        self.assertEqual(normalized["orientation"], "horizontal")
        self.assertEqual(normalized["aspect_ratio"], "16:9")

    def test_video_profile_coerces_weak_provider_vertical_for_repo(self) -> None:
        repo_candidate = {
            **candidate(),
            "canonical_url": "https://github.com/acme/demo-tool",
            "signals": {"has_code_signal": True},
        }
        fallback = choose_video_profile(repo_candidate)

        normalized = normalize_video_profile(
            {
                "duration_seconds": 90,
                "orientation": "vertical",
                "aspect_ratio": "9:16",
                "content_depth": "open_source_repo_explainer",
                "decision_reason": "Vertical fits a narrative-driven explainer.",
            },
            fallback=fallback,
        )

        self.assertEqual(normalized["orientation"], "horizontal")
        self.assertEqual(normalized["aspect_ratio"], "16:9")

    def test_video_profile_respects_explicit_vertical_env(self) -> None:
        repo_candidate = {
            **candidate(),
            "canonical_url": "https://github.com/acme/demo-tool",
            "signals": {"has_code_signal": True},
        }
        with patch.dict(os.environ, {"SEARCHPO_VIDEO_ORIENTATION": "vertical"}, clear=False):
            profile = choose_video_profile(repo_candidate)

        self.assertEqual(profile["orientation"], "vertical")
        self.assertEqual(profile["aspect_ratio"], "9:16")

    def test_video_profile_default_does_not_force_longform(self) -> None:
        repo_candidate = {
            **candidate(),
            "canonical_url": "https://github.com/acme/demo-tool",
            "signals": {"has_code_signal": True},
        }

        profile = choose_video_profile(repo_candidate)

        self.assertLess(profile["duration_seconds"], 180)

    def test_script_artifact_preserves_long_voiceover_without_static_cap(self) -> None:
        long_voiceover = "Demo Tool " + ("这是一个需要展开机制、取舍、适用场景和验证路径的长介绍。" * 140)
        script = build_script_artifact(
            candidate(),
            {
                "polished_title": "Demo Tool 长介绍",
                "voiceover_text": long_voiceover,
                "douyin_desc": "Demo Tool 长介绍，保留证据边界。",
                "video_profile": {"duration_seconds": 420, "orientation": "vertical"},
            },
            {"core_question": "Demo Tool 解决什么问题？", "angle": "先讲机制再讲边界"},
            {"facts": [{"id": "fact_001", "source_refs": ["official"]}]},
        )

        self.assertEqual(script["voiceover_text"], long_voiceover)
        self.assertGreater(len(script["voiceover_segments"]), 20)

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
