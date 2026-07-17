from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from scripts.deepseek_polish import (
    chinese_char_count,
    compact_voiceover_if_over_target,
    deepseek_chat,
    deepseek_variant_chat,
    fit_video_profile_to_voiceover,
    parse_deepseek_payload,
    public_visible_text,
    request_voiceover_section,
    scrub_polish_external_guidance,
)


AGENT_VISUAL = {
    "enabled": True,
    "render_mode": "full_canvas",
    "description": "Scrapling evidence-flow visual",
    "component_code": "return <AbsoluteFill className=\"agent-scrapling\"><div>{data.displayTitle}</div></AbsoluteFill>;",
    "css": ".agent-scrapling { background: #18466a; color: #f8fbff; }",
}


def polish_payload(*, invalid_storyboard: bool = False) -> dict[str, object]:
    statement_props = {"kicker": "先看"} if invalid_storyboard else {"title": "Scrapling 先看问题"}
    return {
        "polished_title": "Scrapling 先看问题",
        "voiceover_text": "Scrapling 是一个需要按源码和文档边界验证的抓取工具观察稿。",
        "douyin_title": "Scrapling 先看验证边界",
        "douyin_desc": "Scrapling 观察稿，先看机制和适用边界。",
        "tags": ["Python", "开源工具", "数据抓取"],
        "cards": [{"label": "边界", "value": "源码文档", "detail": "先验证再判断"}],
        "storyboard": {
            "version": 1,
            "scenes": [
                {"type": "statement", "props": statement_props},
                {"type": "cta", "props": {"text": "跑通再判断"}},
            ],
        },
        "agent_visual": AGENT_VISUAL,
        "video_profile": {
            "duration_seconds": 30,
            "orientation": "vertical",
            "aspect_ratio": "9:16",
            "motion": "calm",
            "animation_style": "diagrammatic",
            "decision_reason": "短视频观察稿",
        },
        "caveats": ["需要继续验证真实使用场景"],
    }


def response(payload: dict[str, object]) -> dict[str, object]:
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}], "usage": {"total_tokens": 10}}


class DeepSeekPolishTests(unittest.TestCase):
    def test_public_visible_text_tolerates_malformed_urls(self) -> None:
        text = public_visible_text("facebook.com: **Source**: https://[bad --- web_demo_mm.py")

        self.assertNotIn("https://", text)
        self.assertNotIn("web_demo_mm", text)
        self.assertIn("外部来源", text)

    def test_deepseek_chat_corrects_normalization_errors(self) -> None:
        candidate = {
            "candidate_id": "scrapling",
            "title": "D4Vinci/Scrapling",
            "canonical_url": "https://github.com/D4Vinci/Scrapling",
        }
        content_plan = {"topic_brief": {}, "fact_bank": {"source_backed_facts": []}}
        evidence_bundle = {"evidence_summary": {"source_facts": []}}
        cross_check_review = {"status": "pass", "research_sufficient": True}

        with patch(
            "scripts.deepseek_polish.request_deepseek",
            side_effect=[response(polish_payload(invalid_storyboard=True)), response(polish_payload())],
        ) as request:
            polished = deepseek_chat(
                "test-key",
                "deepseek-test",
                candidate,
                content_plan,
                evidence_bundle,
                cross_check_review,
                timeout=1,
                video_seconds=30,
            )

        self.assertEqual(request.call_count, 2)
        self.assertTrue(polished["_correction_applied"])
        self.assertIn("storyboard scene 1", polished["_initial_error"])
        self.assertEqual(polished["storyboard"]["scenes"][0]["props"]["title"], "Scrapling 先看问题")

    def test_deepseek_chat_falls_back_when_correction_visual_breaks_layout(self) -> None:
        candidate = {
            "candidate_id": "scrapling",
            "title": "D4Vinci/Scrapling",
            "canonical_url": "https://github.com/D4Vinci/Scrapling",
        }
        corrected = polish_payload()
        corrected["agent_visual"] = {
            "enabled": True,
            "render_mode": "full_canvas",
            "description": "unsafe bottom visual",
            "component_code": "const chartBottom = height - 200; return <AbsoluteFill style={{backgroundColor: '#0a0a0a'}} />;",
            "css": "",
        }

        with patch(
            "scripts.deepseek_polish.request_deepseek",
            side_effect=[response(polish_payload(invalid_storyboard=True)), response(corrected)],
        ):
            polished = deepseek_chat(
                "test-key",
                "deepseek-test",
                candidate,
                {"topic_brief": {}, "fact_bank": {"source_backed_facts": []}},
                {"evidence_summary": {"source_facts": []}},
                {"status": "pass", "research_sufficient": True},
                timeout=1,
                video_seconds=30,
            )

        self.assertTrue(polished["_correction_applied"])
        self.assertTrue(polished["_agent_visual_fallback_applied"])
        self.assertIn("#263449", polished["agent_visual"]["component_code"])

    def test_voiceover_section_rewrites_forbidden_claim_terms(self) -> None:
        with patch(
            "scripts.deepseek_polish.request_deepseek",
            side_effect=[
                response({"section_text": "第一，Scrapling 需要先看源码边界。", "section_summary": "含禁用词"}),
                response({"section_text": "先看 Scrapling 的源码边界，再判断适用场景。", "section_summary": "已改写"}),
            ],
        ) as request:
            section = request_voiceover_section(
                "test-key",
                "deepseek-test",
                {"title": "D4Vinci/Scrapling"},
                {},
                {"evidence_summary": {}},
                {"status": "pass"},
                {"polished_title": "Scrapling", "video_profile": {"duration_seconds": 30}},
                section_index=1,
                section_count=1,
                target_chars=160,
                previous_summary="",
                previous_tail="",
                timeout=1,
            )

        self.assertEqual(request.call_count, 2)
        self.assertEqual(section["rewrite_attempt"], 2)
        self.assertNotIn("第一", section["section_text"])

    def test_deepseek_chat_scrubs_forbidden_terms_after_correction(self) -> None:
        candidate = {
            "candidate_id": "scrapling",
            "title": "D4Vinci/Scrapling",
            "canonical_url": "https://github.com/D4Vinci/Scrapling",
        }
        initial = polish_payload()
        initial["voiceover_text"] = "第一，Scrapling 是一个需要验证的抓取工具。"
        corrected = polish_payload()
        corrected["voiceover_text"] = "第一，Scrapling 仍然需要验证源码边界。"

        with patch("scripts.deepseek_polish.request_deepseek", side_effect=[response(initial), response(corrected)]):
            polished = deepseek_chat("test-key", "deepseek-test", candidate, {}, {"evidence_summary": {}}, {"status": "pass"}, timeout=1)

        self.assertTrue(polished["_claim_scrub_applied"])
        self.assertNotIn("第一", polished["voiceover_text"])

    def test_deepseek_variant_chat_scrubs_forbidden_terms_before_validation(self) -> None:
        candidate = {"candidate_id": "scrapling", "title": "D4Vinci/Scrapling", "canonical_url": "https://github.com/D4Vinci/Scrapling"}
        variants = []
        for _ in range(3):
            variant = polish_payload()
            variant["voiceover_text"] = "第一，Scrapling 需要验证源码和文档边界。"
            variants.append(variant)

        with patch("scripts.deepseek_polish.request_deepseek", return_value=response({"variants": variants})):
            polished = deepseek_variant_chat("test-key", "deepseek-test", candidate, {}, {"evidence_summary": {}}, {"status": "pass"}, timeout=1)

        self.assertEqual(len(polished), 3)
        self.assertTrue(all(item["_claim_scrub_applied"] for item in polished))
        self.assertTrue(all("第一" not in item["voiceover_text"] for item in polished))

    def test_scrub_polish_external_guidance_removes_install_download_language(self) -> None:
        cleaned = scrub_polish_external_guidance(
            {
                "voiceover_text": "可以 pip install scrapling，然后看下载量统计；GitHub 仓库链接。",
                "cards": [{"detail": "Docker中安装，用不同网站测试解析稳定性。"}],
            }
        )

        rendered = json.dumps(cleaned, ensure_ascii=False)
        self.assertNotIn("pip install", rendered)
        self.assertNotIn("下载", rendered)
        self.assertNotIn("安装", rendered)
        self.assertNotIn("链接", rendered)
        self.assertNotIn("仓库", rendered)

    def test_fit_video_profile_to_voiceover_reduces_oversized_duration(self) -> None:
        polished = fit_video_profile_to_voiceover(
            {
                "voiceover_text": "Scrapling " + ("需要验证机制。" * 80),
                "video_profile": {"duration_seconds": 300, "orientation": "horizontal", "aspect_ratio": "16:9"},
            }
        )

        self.assertLess(polished["video_profile"]["duration_seconds"], 180)
        self.assertEqual(polished["video_profile"]["orientation"], "horizontal")
        self.assertEqual(polished["video_profile"]["aspect_ratio"], "16:9")
        self.assertEqual(polished["_video_profile_duration_adjusted"]["from_seconds"], 300)

    def test_fit_video_profile_to_voiceover_raises_understated_duration(self) -> None:
        polished = fit_video_profile_to_voiceover(
            {
                "voiceover_text": "Scrapling " + ("需要按源码和文档边界验证。" * 42),
                "video_profile": {"duration_seconds": 75, "orientation": "vertical", "aspect_ratio": "9:16"},
            }
        )

        self.assertGreaterEqual(polished["video_profile"]["duration_seconds"], 90)
        self.assertEqual(polished["video_profile"]["orientation"], "vertical")
        self.assertEqual(polished["_video_profile_duration_adjusted"]["from_seconds"], 75)
        self.assertEqual(polished["_video_profile_duration_adjusted"]["strategy"], "estimated_tts_duration_alignment")

    def test_voiceover_compaction_uses_source_facts_without_mem0_template(self) -> None:
        payload = polish_payload()
        payload["voiceover_text"] = "Scrapling " + ("需要按源码和文档边界验证这个抓取工具。" * 140)
        payload["video_profile"] = {"duration_seconds": 60, "orientation": "vertical", "aspect_ratio": "9:16"}
        compact = compact_voiceover_if_over_target(
            {"title": "D4Vinci/Scrapling", "summary": "Scrapling 是一个抓取工具。"},
            {
                "repo_context": {"repo": "D4Vinci/Scrapling", "facts": ["README: Scrapling focuses on web scraping and extraction."]},
                "fact_bank": {"source_backed_facts": ["Scrapling 文档强调抓取、解析和验证边界。"]},
            },
            payload,
        )

        self.assertLess(chinese_char_count(compact["voiceover_text"]), chinese_char_count(payload["voiceover_text"]))
        self.assertIn("D4Vinci/Scrapling", compact["voiceover_text"])
        self.assertNotIn("长期记忆", compact["voiceover_text"])
        self.assertNotIn("向量库", compact["voiceover_text"])

    def test_longform_payload_requires_chaptered_storyboard(self) -> None:
        payload = polish_payload()
        payload["video_profile"] = {"duration_seconds": 300, "orientation": "horizontal", "aspect_ratio": "16:9"}

        with self.assertRaisesRegex(RuntimeError, "long-form storyboard contract"):
            parse_deepseek_payload(json.dumps(payload, ensure_ascii=False))

    def test_longform_payload_accepts_rich_storyboard(self) -> None:
        payload = polish_payload()
        payload["video_profile"] = {"duration_seconds": 300, "orientation": "horizontal", "aspect_ratio": "16:9"}
        payload["storyboard"] = {
            "version": 1,
            "scenes": [
                {"type": "statement", "props": {"title": "Scrapling 先看真实问题"}},
                {"type": "context", "props": {"text": "抓取稳定性要按源码边界看"}},
                {"type": "terminal", "props": {"title": "验证入口", "lines": ["read docs", "inspect fetchers"]}},
                {"type": "flow", "props": {"heading": "抓取流程", "nodes": ["请求", "解析", "选择器", "输出"]}},
                {"type": "code_diff", "props": {"title": "源码检查", "additions": ["fetchers.py", "find_similar()"]}},
                {"type": "compare_table", "props": {"heading": "适用边界", "rows": ["动态页面 / 需复核", "静态页面 / 更稳定"]}},
                {"type": "chart", "props": {"heading": "评估维度", "value": "3 条线", "points": ["稳定", "速度", "边界"]}},
                {"type": "bullets", "props": {"heading": "风险点", "items": ["反爬", "结构变化", "测试样本"]}},
                {"type": "compare", "props": {"heading": "不要混淆", "left": "源码能证明", "right": "实测才知道"}},
                {"type": "quote", "props": {"quote": "先把证据和假设分开"}},
                {"type": "stat", "props": {"value": "5 个检查点", "label": "上线前复核"}},
                {"type": "cta", "props": {"text": "按证据边界判断"}},
            ],
        }

        parsed = parse_deepseek_payload(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(parsed["video_profile"]["orientation"], "horizontal")
        self.assertEqual(len(parsed["storyboard"]["scenes"]), 12)

    def test_longform_payload_accepts_engineering_closing_scene(self) -> None:
        payload = polish_payload()
        payload["video_profile"] = {"duration_seconds": 180, "orientation": "horizontal", "aspect_ratio": "16:9"}
        payload["storyboard"] = {
            "version": 1,
            "style": {"theme": "engineering"},
            "scenes": [
                {"type": "statement", "props": {"title": "Scrapling 工程拆解"}},
                {"type": "act_card", "props": {"detail": "The Engine"}},
                {"type": "code_block", "props": {"lines": ["def run(ctx):", "    return decide(ctx)"], "title": "入口代码"}},
                {"type": "node_graph", "props": {"center": "runner", "nodes": ["fetch", "parse", "rank"]}},
                {"type": "decision_table", "props": {"title": "规则到输出", "rules": ["静态页面 -> 优先", "动态页面 -> 复核"], "categories": ["stable", "review"]}},
                {"type": "terminal", "props": {"title": "验证入口", "lines": ["run tests"]}},
                {"type": "flow", "props": {"heading": "抓取流程", "nodes": ["请求", "解析", "输出"]}},
                {"type": "chart", "props": {"heading": "评估维度", "value": "3 条线", "points": ["稳定", "速度", "边界"]}},
                {"type": "compare", "props": {"heading": "不要混淆", "left": "源码能证明", "right": "实测才知道"}},
                {"type": "quote", "props": {"quote": "先把证据和假设分开"}},
                {"type": "stat", "props": {"value": "5 个检查点", "label": "上线前复核"}},
                {"type": "closing", "props": {"mark": "searchpo", "sub": "bounded engineering explainer"}},
            ],
        }

        parsed = parse_deepseek_payload(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(parsed["storyboard"]["style"]["theme"], "engineering")
        self.assertEqual(parsed["storyboard"]["scenes"][-1]["type"], "closing")


if __name__ == "__main__":
    unittest.main()
