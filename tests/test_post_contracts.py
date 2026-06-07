from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_harness.douyin_distribution import evaluate_douyin_distribution_gate
from agent_harness.evidence import build_evidence_bundle, cross_check_evidence, http_source_url
from agent_harness.stages import build_claims_ledger, build_douyin_copy, build_main_task_plan, build_video_payload, public_content_preflight_text, write_post_artifacts
from scripts.content_scorer import deterministic_blocking_checks


AGENT_VISUAL = {
    "enabled": True,
    "render_mode": "full_canvas",
    "description": "定制 Remotion 视觉",
    "component_code": "  return <AbsoluteFill className=\"agent-demo\"><div>{data.displayTitle}</div></AbsoluteFill>;",
    "css": ".agent-demo { background: #070a10; color: #fffdf4; }",
}

STORYBOARD = {
    "version": 1,
    "style": {"theme": "minimal"},
    "scenes": [
        {"type": "statement", "props": {"title": "Demo Tool 要先看证据", "sub": "不是结论"}},
        {"type": "context", "props": {"text": "把来源和待验证部分分开讲。"}},
        {"type": "cta", "props": {"text": "跑通 demo 再判断"}},
    ],
}

STRONG_REVIEW = {
    "status": "pass",
    "research_sufficient": True,
    "fact_bank_status": "pass",
    "supplemental_source_count": 2,
    "independent_source_hosts": ["docs.example.org", "blog.example.net"],
    "source_facts": ["description: demo"],
    "constructive_angles": ["看问题边界"],
    "warnings": [],
    "errors": [],
}


class PostContractTests(unittest.TestCase):
    def test_content_preflight_scans_public_text_not_provider_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            post_dir = Path(tmp) / "post"
            post_dir.mkdir()
            (post_dir / "douyin_title.txt").write_text("Google 搜索 AI 模式怎么用", encoding="utf-8")
            (post_dir / "douyin_desc.txt").write_text("讲清机制、适用边界和内容创作者机会。", encoding="utf-8")
            (post_dir / "douyin_tags.txt").write_text("AI搜索\nGoogle\n", encoding="utf-8")
            (post_dir / "posting_pack.md").write_text("Operational note: first public pass is contract-check only.", encoding="utf-8")
            text = public_content_preflight_text(
                {"title": "Google 搜索 AI 模式", "voiceoverText": "搜索框变成任务入口。"},
                {
                    "polished_title": "Google 搜索 AI 模式",
                    "voiceover_text": "搜索框变成任务入口。",
                    "douyin_desc": "讲清机制、适用边界和内容创作者机会。",
                    "initial_error": "DeepSeek candidate contains unsupported claim terms: ['第一']",
                    "tts_style": "开头第一句稍微更有好奇感。",
                },
                post_dir,
            )

        self.assertNotIn("initial_error", text)
        self.assertNotIn("开头第一句", text)
        self.assertNotIn("第一", text)

    def test_claims_ledger_covers_public_fields(self) -> None:
        candidate = {
            "candidate_id": "cand-1",
            "title": "Demo Tool",
            "canonical_url": "https://example.com/demo",
            "source_ids": ["official"],
            "evidence": [{"source": "official", "raw_sha256": "abc"}],
        }
        douyin_copy = {"title": "Demo Tool 值得关注", "desc": "这是一个有来源边界的观察。", "tags": ["AI工具", "Demo"]}
        render_payload = {
            "voiceoverText": "Demo Tool 现在只能作为观察稿处理。",
            "cards": [{"label": "证据", "value": "官方来源", "detail": "先看 demo 再下结论"}],
        }

        ledger = build_claims_ledger(candidate, douyin_copy, render_payload)

        self.assertEqual(ledger["review_status"], "contract-check-pass")
        self.assertEqual(ledger["coverage"]["missing_fields"], [])
        fields = {claim["field"].split("_", 1)[0] for claim in ledger["claims"]}
        self.assertTrue({"title", "description", "voiceover", "cards", "tags"}.issubset(fields))

    def test_contract_claims_ledger_does_not_fabricate_media_fields(self) -> None:
        candidate = {
            "candidate_id": "cand-1",
            "title": "Demo Tool",
            "canonical_url": "https://example.com/demo",
            "source_ids": ["official"],
            "evidence": [{"source": "official", "raw_sha256": "abc"}],
        }
        ledger = build_claims_ledger(
            candidate,
            {"title": "Demo Tool", "desc": "Demo Tool 观察稿", "tags": ["AI工具"]},
            None,
        )

        self.assertEqual(ledger["review_status"], "contract-check-pass")
        self.assertEqual(ledger["coverage"]["missing_fields"], [])
        self.assertEqual(ledger["coverage"]["not_applicable_fields"], ["voiceover", "cards", "storyboard", "agent_visual"])
        self.assertNotIn("voiceover", ledger["coverage"]["required_fields"])
        self.assertNotIn("cards", ledger["coverage"]["required_fields"])
        self.assertNotIn("storyboard", ledger["coverage"]["required_fields"])

    def test_claims_ledger_covers_storyboard_scene_text(self) -> None:
        candidate = {
            "candidate_id": "cand-1",
            "title": "Demo Tool",
            "canonical_url": "https://example.com/demo",
            "source_ids": ["official"],
            "evidence": [{"source": "official", "raw_sha256": "abc"}],
        }
        douyin_copy = {"title": "Demo Tool 值得关注", "desc": "这是一个有来源边界的观察。", "tags": ["AI工具"]}
        render_payload = {
            "voiceoverText": "Demo Tool 现在只能作为观察稿处理。",
            "cards": [{"label": "证据", "value": "官方来源", "detail": "先看 demo 再下结论"}],
            "storyboard": {
                "version": 1,
                "style": {"theme": "minimal"},
                "scenes": [
                    {"type": "statement", "props": {"title": "Demo Tool 要先看证据", "sub": "不是结论"}},
                    {"type": "stat", "props": {"value": "1 个来源", "label": "官方页面", "detail": "继续验证"}},
                    {"type": "cta", "props": {"text": "跑通 demo 再判断", "footer": "保留证据边界"}},
                ],
            },
        }

        ledger = build_claims_ledger(candidate, douyin_copy, render_payload)

        self.assertEqual(ledger["coverage"]["missing_fields"], [])
        fields = {claim["field"].split("_", 1)[0] for claim in ledger["claims"]}
        self.assertIn("storyboard", fields)
        storyboard_claims = [claim for claim in ledger["claims"] if claim["field"].startswith("storyboard")]
        self.assertTrue(any("Demo Tool 要先看证据" in claim["claim"] for claim in storyboard_claims))

    def test_task_plan_matches_contract_and_provider_modes(self) -> None:
        candidate = {
            "candidate_id": "cand-1",
            "title": "Demo Tool",
            "canonical_url": "https://example.com/demo",
        }
        contract_task_ids = [task["id"] for task in build_main_task_plan(candidate, include_providers=False)["ordered_tasks"]]
        provider_task_ids = [task["id"] for task in build_main_task_plan(candidate, include_providers=True)["ordered_tasks"]]

        self.assertEqual(
            contract_task_ids,
            [
                "select_candidate",
                "subject_detail_fetch",
                "research_enrichment",
                "cross_check",
                "publish_package",
                "content_preflight",
            ],
        )
        provider_tasks = {task["id"]: task for task in build_main_task_plan(candidate, include_providers=True)["ordered_tasks"]}
        self.assertEqual(provider_tasks["research_enrichment"]["owner"], "searchpo-research-agent")
        self.assertIn("content_improvement_loop", provider_task_ids)
        self.assertIn("remotion_render_payload", provider_task_ids)
        self.assertIn("final_verification", provider_task_ids)
        self.assertNotIn("remotion_render", contract_task_ids)

    def test_operator_topic_external_url_uses_public_source_label(self) -> None:
        candidate = {
            "candidate_id": "topic-1",
            "input_mode": "operator_topic",
            "selection_source": "operator_topic",
            "title": "https://github.com/microsoft/markitdown",
            "summary": "指定主题观察。",
            "canonical_url": "https://github.com/microsoft/markitdown",
            "source_ids": ["operator_topic"],
            "evidence": [{"source": "operator_topic"}],
            "signals": {"source_count": 1},
            "candidate_score": 8.0,
        }
        payload = build_video_payload(
            candidate,
            polish={
                "polished_title": "微软 MarkItDown 文档转换观察",
                "voiceover_text": "微软 MarkItDown 是一个待验证观察稿，需要实测转换质量后再判断。",
                "agent_visual": AGENT_VISUAL,
                "storyboard": STORYBOARD,
                "cards": [
                    {"label": "用户痛点", "value": "文档转换", "detail": "先看它想解决什么。"},
                    {"label": "已知证据", "value": "GitHub", "detail": "有公开仓库来源。"},
                ],
            },
            voiceover_manifest={
                "fps": 30,
                "audio_frames": 300,
                "normalized_voiceover_text": "微软 MarkItDown 是一个待验证观察稿，需要实测转换质量后再判断。",
            },
            captions=[{"text": "待验证观察稿", "startFrame": 0, "endFrame": 30}],
        )
        self.assertEqual(payload["source"], "GitHub")
        public_text = " ".join(
            str(item or "")
            for item in [
                payload.get("source"),
                payload.get("metricLine"),
                payload.get("audienceMetricLine"),
                payload.get("footer"),
                *(field for card in payload.get("cards", []) for field in [card.get("label"), card.get("value"), card.get("detail")]),
            ]
        )
        self.assertNotIn("operator_topic", public_text)

    def test_direct_link_douyin_copy_does_not_emit_raw_url(self) -> None:
        candidate = {
            "candidate_id": "topic-1",
            "input_mode": "operator_topic",
            "selection_source": "operator_topic",
            "title": "https://github.com/anysearch-ai/anysearch-skill",
            "summary": "指定链接观察。",
            "canonical_url": "https://github.com/anysearch-ai/anysearch-skill",
            "source_ids": ["operator_topic"],
            "evidence": [{"source": "operator_topic"}],
            "signals": {"source_count": 1},
            "candidate_score": 8.0,
        }
        copy = build_douyin_copy(candidate)
        public_text = f"{copy['title']} {copy['desc']}"
        self.assertIn("anysearch-ai/anysearch-skill", public_text)
        self.assertNotIn("https://", public_text)
        self.assertNotIn("github.com", public_text)
        self.assertNotIn("operator_topic", public_text)

    def test_daily_radar_uses_public_source_label(self) -> None:
        candidate = {
            "candidate_id": "cand-github",
            "title": "anthropics/claude-code",
            "summary": "Claude Code 是一个待验证的终端编程工具观察稿。",
            "canonical_url": "https://github.com/anthropics/claude-code",
            "source_ids": ["github_trending"],
            "evidence": [{"source": "github_trending"}],
            "signals": {"source_count": 1, "has_code_signal": True, "has_demo_keyword": False},
            "metrics": {"stars": "128327", "stars_today": "595"},
            "candidate_score": 5.9,
        }
        payload = build_video_payload(
            candidate,
            polish={
                "polished_title": "Claude Code 在 GitHub Trending 上获得关注",
                "voiceover_text": "Claude Code 是一个待验证的终端编程工具观察稿。",
                "agent_visual": AGENT_VISUAL,
                "storyboard": STORYBOARD,
                "cards": [
                    {"label": "用户痛点", "value": "终端编程", "detail": "减少工具切换。"},
                    {"label": "已知证据", "value": "GitHub Trending", "detail": "公开仓库来源。"},
                ],
            },
            voiceover_manifest={
                "fps": 30,
                "audio_frames": 300,
                "normalized_voiceover_text": "Claude Code 是一个待验证的终端编程工具观察稿。",
            },
            captions=[{"text": "待验证观察稿", "startFrame": 0, "endFrame": 30}],
        )

        self.assertEqual(payload["source"], "GitHub Trending")
        public_text = " ".join(
            str(item or "")
            for item in [
                payload.get("source"),
                payload.get("metricLine"),
                payload.get("audienceMetricLine"),
                *(field for card in payload.get("cards", []) for field in [card.get("label"), card.get("value"), card.get("detail")]),
            ]
        )
        self.assertNotIn("github_trending", public_text)

    def test_post_artifacts_start_pending_until_media_is_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "runtime" / "artifacts" / "2026-05-31" / "run-abc"
            run_dir.mkdir(parents=True)
            candidate = {
                "candidate_id": "cand-1",
                "title": "Demo Tool",
                "canonical_url": "https://example.com/demo",
                "source_ids": ["official"],
            }
            post_dir = write_post_artifacts(
                root,
                run_dir,
                candidate,
                {"title": "Demo Tool", "desc": "Demo Tool 观察稿", "tags": ["AI工具"]},
                {"voiceoverText": "Demo Tool 是一个观察稿。", "cards": [{"label": "证据", "value": "来源", "detail": "待验证"}]},
                {"evidence_summary": {"source_facts": ["description: demo"], "constructive_angles": ["看问题边界"]}},
                STRONG_REVIEW,
            )
            manifest = json.loads((post_dir / "douyin_upload_manifest.json").read_text())
            distribution_review = json.loads((post_dir / "douyin_distribution_review.json").read_text())
            self.assertEqual(manifest["manifest_status"], "pending-artifact-binding")
            self.assertEqual(manifest["expected_video_path"], str(run_dir / "video" / "final.mp4"))
            self.assertIsNone(manifest["expected_video_sha256"])
            self.assertEqual(distribution_review["status"], "pass")
            self.assertTrue((post_dir / "cross_check_review.json").is_file())

    def test_douyin_distribution_gate_blocks_folk_thresholds_and_bait(self) -> None:
        review = evaluate_douyin_distribution_gate(
            candidate={
                "candidate_id": "cand-1",
                "title": "Demo Tool",
                "canonical_url": "https://example.com/demo-tool",
            },
            douyin_copy={
                "title": "Demo Tool 首轮 500 播放必爆",
                "desc": "Demo Tool 只要 3 秒完播率必须超过就能破限流，评论区扣 1 求点赞。",
                "tags": ["AI工具", "Demo"],
            },
            render_payload={"voiceoverText": "Demo Tool 这个说法没有官方证据。"},
            cross_check_review=STRONG_REVIEW,
        )

        self.assertEqual(review["status"], "fail")
        self.assertFalse(review["checks"]["no_private_threshold_claims"])
        self.assertFalse(review["checks"]["no_engagement_bait"])
        self.assertGreaterEqual(len(review["blocking_issues"]), 2)

    def test_douyin_distribution_gate_blocks_platform_automation_subjects(self) -> None:
        review = evaluate_douyin_distribution_gate(
            candidate={
                "candidate_id": "topic-automation",
                "title": "social-auto-upload 多平台视频自动发布工具",
                "summary": "分析对抖音、小红书、视频号、TikTok、YouTube、Bilibili 的自动上传价值。",
                "canonical_url": "https://github.com/dreammis/social-auto-upload",
            },
            douyin_copy={
                "title": "创作者流程怎么少做重复劳动",
                "desc": "这期只做来源边界内的观察，不引导下载或交易。",
                "tags": ["创作流程", "效率工具"],
            },
            render_payload={"voiceoverText": "创作者流程需要先看平台规则边界。"},
            cross_check_review=STRONG_REVIEW,
        )

        self.assertEqual(review["status"], "fail")
        self.assertFalse(review["checks"]["subject_not_platform_abuse"])
        self.assertTrue(review["hits"]["platform_abuse_subject_patterns"])

    def test_douyin_distribution_gate_blocks_external_redirect_copy(self) -> None:
        review = evaluate_douyin_distribution_gate(
            candidate={
                "candidate_id": "topic-superpowers",
                "title": "obra/superpowers",
                "canonical_url": "https://github.com/obra/superpowers",
            },
            douyin_copy={
                "title": "AI编程助手总跑偏？试试这个MIT开源技能框架",
                "desc": "这个项目可以去 https://github.com/obra/superpowers 下载使用，先看看是否适合你的工作流。",
                "tags": ["AI编程", "开源"],
            },
            render_payload={"voiceoverText": "obra superpowers 是一个待验证观察稿。"},
            cross_check_review=STRONG_REVIEW,
        )

        self.assertEqual(review["status"], "fail")
        self.assertFalse(review["checks"]["no_external_redirect_guidance"])
        self.assertFalse(review["checks"]["no_raw_public_urls"])

    def test_douyin_distribution_gate_does_not_match_external_redirect_across_fields(self) -> None:
        review = evaluate_douyin_distribution_gate(
            candidate={
                "candidate_id": "topic-nomad",
                "title": "Project Nomad",
                "canonical_url": "https://github.com/Crosstalk-Solutions/project-nomad",
            },
            douyin_copy={
                "title": "Project Nomad 离线知识库观察",
                "desc": "只按来源边界做观察，实际效果仍需验证。",
                "tags": ["离线知识", "开源项目"],
            },
            render_payload={
                "verificationNextStep": "下一步应补充真实使用记录，再判断是否值得发布。",
                "source": "GitHub",
                "voiceoverText": "Project Nomad 是一个待验证观察稿。",
            },
            cross_check_review=STRONG_REVIEW,
        )

        self.assertEqual(review["status"], "pass")
        self.assertTrue(review["checks"]["no_external_redirect_guidance"])

    def test_content_scorer_blocks_candidate_mismatch_and_generic_hook(self) -> None:
        checks = deterministic_blocking_checks(
            {"polished_title": "别错过这个工具", "voiceover_text": "最近 arXiv 出现一篇论文，值得看看。"},
            {"title": "obra/superpowers", "canonical_url": "https://github.com/obra/superpowers"},
            {"sources": [{"id": "primary_url"}]},
            {"status": "pass", "errors": []},
        )
        self.assertFalse(checks["candidate_referenced"])
        self.assertFalse(checks["hook_specific"])
        self.assertGreaterEqual(len(checks["blocking_issues"]), 2)

    def test_content_scorer_blocks_missing_evidence_or_failed_cross_check(self) -> None:
        checks = deterministic_blocking_checks(
            {"polished_title": "Demo Tool", "voiceover_text": "Demo Tool 解决日志排查问题。"},
            {"title": "Demo Tool", "canonical_url": "https://example.com/demo"},
            {},
            {"status": "fail", "errors": ["primary source text too short"]},
        )
        self.assertFalse(checks["evidence_sources_present"])
        self.assertEqual(checks["cross_check_status"], "fail")
        self.assertGreaterEqual(len(checks["blocking_issues"]), 2)

    def test_github_evidence_requires_repo_api_and_readme(self) -> None:
        def fake_fetch(url: str, headers: dict[str, str] | None, timeout: float) -> dict[str, object]:
            if url == "https://github.com/acme/demo":
                return {
                    "url": url,
                    "status": 200,
                    "content_type": "text/html",
                    "sha256": "a",
                    "text": "<html><title>acme demo</title><body>Demo project helps developers inspect logs with source-grounded traces. It documents a CLI workflow, compares runs, explains regression checks, and gives enough implementation context to support a bounded short-video analysis.</body></html>",
                }
            if url == "https://api.github.com/repos/acme/demo":
                return {
                    "url": url,
                    "status": 200,
                    "content_type": "application/json",
                    "sha256": "b",
                    "text": json.dumps({"description": "Trace inspection tool", "stargazers_count": 42, "language": "Python", "license": {"spdx_id": "MIT"}}),
                }
            if url == "https://api.github.com/repos/acme/demo/readme":
                return {
                    "url": url,
                    "status": 200,
                    "content_type": "text/plain",
                    "sha256": "c",
                    "text": "Demo provides a CLI for inspecting logs, comparing runs, and identifying regressions before adoption.",
                }
            raise AssertionError(url)

        candidate = {"candidate_id": "cand-1", "title": "acme demo", "canonical_url": "https://github.com/acme/demo"}
        bundle = build_evidence_bundle(candidate, fetcher=fake_fetch)
        review = cross_check_evidence(candidate, bundle)
        self.assertEqual(bundle["source_kind"], "github_repo")
        self.assertEqual(bundle["source_count"], 3)
        self.assertEqual(review["status"], "pass", review)

    def test_operator_topic_without_url_is_not_evidence_backed(self) -> None:
        with self.assertRaises(RuntimeError):
            http_source_url({"candidate_id": "topic-1", "canonical_url": "manual-topic://topic-1"})

    def test_operator_topic_without_url_builds_widesearch_seed_bundle(self) -> None:
        candidate = {
            "candidate_id": "topic-1",
            "input_mode": "operator_topic",
            "selection_source": "operator_topic",
            "title": "AI agent search strategy",
            "summary": "Find the strongest evidence and useful angles.",
            "canonical_url": "manual-topic://topic-1",
        }
        bundle = build_evidence_bundle(candidate)
        review = cross_check_evidence(candidate, bundle)
        self.assertEqual(bundle["source_kind"], "operator_topic_seed")
        self.assertEqual(bundle["sources"][0]["id"], "operator_topic_seed")
        self.assertEqual(bundle["sources"][0]["evidence_role"], "research_seed")
        self.assertTrue(bundle["requires_widesearch"])
        self.assertFalse(bundle["external_evidence"])
        self.assertEqual(review["status"], "pending_research", review)
        self.assertTrue(any("not external evidence" in warning for warning in review["warnings"]))


if __name__ == "__main__":
    unittest.main()
