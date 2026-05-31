from __future__ import annotations

import unittest

from agent_harness.speech_quality import (
    chinese_ratio,
    evaluate_quality_gate,
    normalize_display_title,
    normalize_voiceover_text,
    plan_cover_title_lines,
)
from scripts.build_captions import build_caption_segments, orphan_caption_texts


class SpeechQualityTests(unittest.TestCase):
    def test_repo_slash_is_naturalized_for_speech(self) -> None:
        text = normalize_voiceover_text("obra/superpowers 是一个待验证的技能框架观察稿。")
        self.assertIn("obra 的 superpowers", text)
        self.assertNotIn("obra/superpowers", text)

    def test_display_title_softens_repo_slash(self) -> None:
        self.assertEqual(normalize_display_title("obra/superpowers"), "obra / superpowers")

    def test_chinese_ratio_catches_english_fallback(self) -> None:
        self.assertLess(chinese_ratio("Superpowers is an MIT licensed framework."), 0.1)
        self.assertGreater(chinese_ratio("这是一个待验证的中文观察稿。"), 0.9)

    def test_cover_layout_keeps_long_repo_slug_safe(self) -> None:
        layout = plan_cover_title_lines("obra/superpowers")
        self.assertTrue(layout["safe"], layout)
        self.assertGreaterEqual(layout["font_size"], 64)
        self.assertGreaterEqual(len(layout["lines"]), 2)

    def test_cover_layout_keeps_words_and_punctuation_attached(self) -> None:
        layout = plan_cover_title_lines("Gemini Embedding 2，让检索更稳")
        self.assertFalse(any(line[0] in "，。,.!?！？" for line in layout["lines"]), layout)
        self.assertTrue(any("Gemini" in line for line in layout["lines"]), layout)
        self.assertTrue(any("Embedding" in line for line in layout["lines"]), layout)

    def test_caption_orphan_detector_blocks_short_word_isolates(self) -> None:
        segments = [
            {"text": "Launch now", "start_frame": 0, "end_frame": 20},
            {"text": "这段字幕有足够上下文", "start_frame": 21, "end_frame": 60},
            {"text": "好", "start_frame": 61, "end_frame": 70},
        ]
        self.assertEqual(orphan_caption_texts(segments, set()), ["Launch now", "好"])
        self.assertEqual(orphan_caption_texts(segments, {"Launch now", "好"}), [])

    def test_caption_orphan_detector_allows_mixed_cjk_latin_context(self) -> None:
        segments = [
            {"text": "微软开源的 MarkItDown 能把 PDF", "start_frame": 0, "end_frame": 50},
            {"text": "Word 等文件直接转成 Markdown", "start_frame": 51, "end_frame": 100},
        ]
        self.assertEqual(orphan_caption_texts(segments, set()), [])

    def test_caption_orphan_detector_allows_platform_punch_words(self) -> None:
        segments = [
            {"text": "B站", "start_frame": 0, "end_frame": 20},
            {"text": "抖音", "start_frame": 21, "end_frame": 40},
            {"text": "TikTok", "start_frame": 41, "end_frame": 60},
            {"text": "YouTube", "start_frame": 61, "end_frame": 80},
            {"text": "Bilibili", "start_frame": 81, "end_frame": 100},
            {"text": "social-auto-upload", "start_frame": 101, "end_frame": 120},
        ]
        self.assertEqual(
            orphan_caption_texts(segments, {"B站", "抖音", "TikTok", "YouTube", "Bilibili", "social-auto-upload"}),
            [],
        )

    def test_caption_builder_respects_display_char_limit_with_latin_terms(self) -> None:
        segments = build_caption_segments(
            "Anthropic 在 GitHub 上公开了一个 Agent Skills 仓库，把可复用能力封装成可安装的 Skill。",
            audio_sec=8.0,
            max_display_chars=36,
        )
        self.assertTrue(segments)
        self.assertLessEqual(max(len(segment["text"]) for segment in segments), 36)

    def test_quality_gate_blocks_internal_terms_and_raw_slash(self) -> None:
        candidate = {
            "input_mode": "operator_topic",
            "selection_source": "operator_topic",
            "canonical_url": "manual-topic://abc",
            "signals": {},
        }
        payload = {
            "title": "obra / superpowers",
            "displayTitle": "obra / superpowers",
            "summary": "指定主题观察。",
            "source": "operator topic",
            "metricLine": "operator supplied topic",
            "audienceMetricLine": "operator supplied topic",
            "cta": "待验证",
            "footer": "待验证",
            "verificationNextStep": "补充 demo。",
            "evidenceLevel": "operator_topic_unverified",
            "cards": [],
            "voiceoverText": "obra/superpowers 是一个待验证项目。",
        }
        result = evaluate_quality_gate(
            candidate=candidate,
            render_payload=payload,
            voiceover_manifest={"voiceover_text": payload["voiceoverText"]},
            captions=[{"text": "待验证项目", "startFrame": 0, "endFrame": 30}],
        )
        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["no_internal_terms"])
        self.assertFalse(result["checks"]["speech_pronunciation_safe"])

    def test_quality_gate_blocks_generic_snake_case_public_copy(self) -> None:
        candidate = {
            "input_mode": "shortlist",
            "selection_source": "candidate_shortlist",
            "canonical_url": "https://example.com/demo",
            "signals": {"has_demo_keyword": True},
        }
        payload = {
            "title": "Demo Tool",
            "displayTitle": "Demo Tool",
            "summary": "daily_radar 选出的项目。",
            "source": "official",
            "metricLine": "source observation",
            "audienceMetricLine": "source observation",
            "cta": "看 demo 再判断。",
            "footer": "来源观察",
            "verificationNextStep": "继续复核。",
            "evidenceLevel": "source_observation_with_artifact_signal",
            "cards": [{"label": "证据", "value": "operator_topic", "detail": "不要泄露内部变量"}],
            "voiceoverText": "Demo Tool 是一个来源观察项目。",
        }
        result = evaluate_quality_gate(
            candidate=candidate,
            render_payload=payload,
            voiceover_manifest={"normalized_voiceover_text": payload["voiceoverText"]},
            captions=[{"text": "来源观察项目", "startFrame": 0, "endFrame": 30}],
        )
        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["no_internal_terms"])
        self.assertTrue(any("operator_topic" in issue or "daily_radar" in issue for issue in result["blocking_issues"]))

    def test_quality_gate_passes_observation_copy(self) -> None:
        candidate = {
            "input_mode": "operator_topic",
            "selection_source": "operator_topic",
            "canonical_url": "manual-topic://abc",
            "signals": {},
        }
        payload = {
            "title": "obra / superpowers",
            "displayTitle": "obra / superpowers",
            "summary": "指定主题观察，当前只做待验证分析。",
            "source": "指定主题",
            "metricLine": "指定主题 · 待验证",
            "audienceMetricLine": "指定主题 · 待验证",
            "cta": "没有实测证据时，只按观察稿处理。",
            "footer": "未实测内容不做结论",
            "verificationNextStep": "下一步补充 demo 后再判断。",
            "evidenceLevel": "operator_topic_unverified",
            "cards": [
                {"label": "用户痛点", "value": "AI 需求对齐", "detail": "先说明它想解决什么。"},
                {"label": "已知证据", "value": "指定主题", "detail": "没有外部来源。"},
            ],
            "voiceoverText": "obra 的 superpowers 现在只能作为待验证观察稿，没有实测证据时不能做结论。",
        }
        result = evaluate_quality_gate(
            candidate=candidate,
            render_payload=payload,
            voiceover_manifest={"normalized_voiceover_text": payload["voiceoverText"]},
            captions=[{"text": "待验证观察稿", "startFrame": 0, "endFrame": 30}],
        )
        self.assertEqual(result["status"], "pass", result["blocking_issues"])


if __name__ == "__main__":
    unittest.main()
