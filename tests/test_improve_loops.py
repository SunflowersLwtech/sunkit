from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from agent_harness.core import HarnessContext, TaskBoard, write_json
from agent_harness.agent_visual import require_agent_visual
from agent_harness.service_artifacts import build_fact_bank_artifact, build_topic_brief_artifact
from agent_harness.stages import ContentImproveLoopStage
from scripts.content_scorer import deterministic_blocking_checks, score_target_report
from scripts.deepseek_polish import (
    apply_source_visual_for_motion_feedback,
    deepseek_body,
    ensure_candidate_reference,
    motion_feedback_requires_source_visual,
    parse_deepseek_payload_with_safe_fallbacks,
    parse_deepseek_payload_with_safe_visual,
    repair_agent_visual_structure,
    repair_storyboard_structure,
    source_grounded_agent_visual,
    unsafe_hits_for,
)
from scripts.deterministic_visual_audit import _max_inactive_seconds, _motion_pairs, _publish_layout_check, _visual_intent_check, _visual_state_hint_count, _visual_structure_check
from scripts.gemini_visual_audit import (
    audit_contract_errors,
    build_prompt,
    choose_video_input_mode,
    classify_audit_result,
    route_contract_errors,
)
import agent_harness.stages as stages
import scripts.video_quality_loop as video_loop
from scripts.video_quality_loop import deterministic_decision


def visual_source_code(visual: dict[str, Any]) -> str:
    normalized = require_agent_visual(visual)
    return str(normalized.get("module_code") or normalized.get("component_code") or "")


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
    def test_fact_bank_rejects_host_only_repo_facts_and_adds_repo_visual_brief(self) -> None:
        candidate = {"candidate_id": "cand-mem0", "title": "mem0.ai", "risk_flags": []}
        github_excerpt = (
            "## GitHub - mem0ai/mem0: Universal memory layer for AI Agents. "
            "Folders and files: cli cookbooks docs evaluation examples mem0 mem0-ts openmemory server tests. "
            "Quickstart uses MemoryClient, then client.add(messages, user_id='user123') and client.search('query')."
        )
        evidence_bundle = {
            "sources": [
                {
                    "id": "primary_url",
                    "type": "primary_page",
                    "url": "https://mem0.ai/",
                    "host": "mem0.ai",
                    "title": "Mem0 - AI Memory Layer for your Agents & Apps | Persistent Context",
                    "text_chars": 1000,
                },
                {
                    "id": "research_supplement_1",
                    "type": "anysearch_extract",
                    "url": "https://github.com/mem0ai/mem0",
                    "host": "github.com",
                    "title": "github.com",
                    "excerpt": github_excerpt,
                    "text_chars": len(github_excerpt),
                },
                {
                    "id": "github_repo_context_mem0_memory_main_py",
                    "type": "github_source_file",
                    "url": "https://raw.githubusercontent.com/mem0ai/mem0/main/mem0/memory/main.py",
                    "host": "raw.githubusercontent.com",
                    "title": "mem0/memory/main.py",
                    "excerpt": "import os\n" * 200,
                    "text_chars": 5000,
                },
            ],
            "repo_context": {
                "repo": "mem0ai/mem0",
                "facts": [
                    "mem0/memory/main.py wires embedder, vector store, LLM, history, and optional reranking components",
                    "server/main.py exposes REST routes including /memories, /search",
                ],
            },
            "evidence_summary": {
                "source_facts": ["title: Mem0 - AI Memory Layer for your Agents & Apps | Persistent Context"]
            },
        }

        noisy_source = {
            "id": "research_supplement_2",
            "type": "anysearch_extract",
            "url": "https://example.com/share",
            "host": "example.com",
            "excerpt": "Check it out:%0A%0Ahttps%3A%2F%2Fexample.com](mailto:?subject=Mem0 Review)",
            "text_chars": 120,
        }
        fact_bank = build_fact_bank_artifact(candidate, evidence_bundle, [evidence_bundle["sources"][1], noisy_source])
        claims = fact_bank["source_backed_facts"]
        self.assertFalse(any(claim.strip().lower() == "github.com: github.com" for claim in claims))
        self.assertFalse(any("mailto:" in claim or "%0A" in claim for claim in claims))
        self.assertTrue(any("wires embedder, vector store, LLM" in claim for claim in claims))
        self.assertTrue(any("file tree highlights modules" in claim for claim in claims))
        self.assertTrue(any("add/search" in claim or "client.add" in claim for claim in claims))
        github_facts = [fact for fact in fact_bank["facts"] if "github.com:" in fact["claim"]]
        self.assertTrue(github_facts)
        self.assertTrue(all(fact["source_refs"] == ["research_supplement_1"] for fact in github_facts))
        repo_fact = next(fact for fact in fact_bank["facts"] if "mem0/memory/main.py wires" in fact["claim"])
        self.assertEqual(repo_fact["source_refs"], ["github_repo_context_mem0_memory_main_py"])

        brief = build_topic_brief_artifact(candidate, fact_bank, [evidence_bundle["sources"][1]])
        self.assertIn("repo-aware Remotion composition", " ".join(brief["visual_opportunities"]))

    def test_deepseek_body_includes_repo_aware_visual_brief(self) -> None:
        candidate = {"candidate_id": "cand-mem0", "title": "mem0.ai"}
        content_plan = {
            "fact_bank": {
                "source_backed_facts": ["github.com: github repo mem0ai/mem0: Universal memory layer for AI Agents"],
                "facts": [],
                "risk_notes": [],
                "source_map": [
                    {
                        "id": "research_supplement_1",
                        "type": "anysearch_extract",
                        "url": "https://github.com/mem0ai/mem0",
                        "host": "github.com",
                        "title": "mem0ai/mem0 README",
                        "text_chars": 12000,
                    }
                ],
            }
        }

        body = deepseek_body(
            "deepseek-v4-pro",
            candidate,
            content_plan,
            temperature=0.3,
            video_seconds=90,
            evidence_bundle={"evidence_summary": {"source_facts": []}},
            cross_check_review={"status": "pass"},
        )
        user = json.loads(body["messages"][1]["content"])

        self.assertIn("visual_brief", user)
        self.assertIn("repo_visual_requirement", user["visual_brief"])
        self.assertIn("safe_layout_recipe", user["visual_brief"])
        self.assertIn("position:absolute", " ".join(user["visual_brief"]["safe_layout_recipe"]))
        self.assertIn("could apply to any AI tool is invalid", " ".join(user["content_quality_requirement"]))

    def test_safe_agent_visual_fallback_replaces_unsafe_layout(self) -> None:
        rejected = {
            "polished_title": "Demo Tool hook",
            "voiceover_text": "Demo Tool 帮开发者先看机制，再看边界。",
            "douyin_title": "Demo Tool hook",
            "douyin_desc": "Demo Tool 观察稿，保留证据边界。",
            "tags": ["AI工具"],
            "cards": [{"label": "机制", "value": "日志排查", "detail": "先验证"}],
            "storyboard": {
                "version": 1,
                "scenes": [{"type": "statement", "props": {"title": "Demo Tool 先看问题"}}],
            },
            "agent_visual": {
                "enabled": True,
                "render_mode": "full_canvas",
                "component_code": "const chartBottom = height - 200; return <AbsoluteFill style={{backgroundColor: '#0a0a0a'}} />;",
                "css": "",
            },
            "video_profile": {"duration_seconds": 45, "orientation": "vertical"},
            "caveats": ["待验证"],
        }

        parsed = parse_deepseek_payload_with_safe_visual(json.dumps(rejected, ensure_ascii=False), "layout contract violation")

        self.assertTrue(parsed["_agent_visual_fallback_applied"])
        self.assertTrue(parsed["agent_visual"]["enabled"])
        self.assertIn("#263449", parsed["agent_visual"]["component_code"])
        self.assertNotIn("data.summary", parsed["agent_visual"]["component_code"])
        self.assertNotIn("data.evidenceLevel", parsed["agent_visual"]["component_code"])
        self.assertNotIn("data.cards", parsed["agent_visual"]["component_code"])
        self.assertNotIn("safeCards", parsed["agent_visual"]["component_code"])
        self.assertIn("fallback_reason", parsed["agent_visual"])

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(
                run_dir / "render_payload.json",
                {
                    "agentVisualRequired": True,
                    "_agent_visual_fallback_applied": parsed["_agent_visual_fallback_applied"],
                    "agentVisual": parsed["agent_visual"],
                },
            )
            report, errors = _visual_intent_check(run_dir)

        self.assertEqual(report["status"], "fail")
        self.assertIn("fallback cannot be published", "; ".join(errors))

    def test_safe_storyboard_fallback_replaces_invalid_compare_table(self) -> None:
        rejected = {
            "polished_title": "Demo Tool hook",
            "voiceover_text": "Demo Tool 帮开发者先看机制，再看边界。",
            "douyin_title": "Demo Tool hook",
            "douyin_desc": "Demo Tool 观察稿，保留证据边界。",
            "tags": ["AI工具"],
            "cards": [{"label": "机制", "value": "日志排查", "detail": "先验证"}],
            "storyboard": {"version": 1, "scenes": [{"type": "compare_table", "props": {"rows": []}}]},
            "agent_visual": {
                "enabled": True,
                "render_mode": "full_canvas",
                "component_code": "return <AbsoluteFill style={{backgroundColor: '#263449'}}><div>Chart</div></AbsoluteFill>;",
                "css": "",
            },
            "video_profile": {"duration_seconds": 45, "orientation": "vertical"},
            "caveats": ["待验证"],
        }

        parsed = parse_deepseek_payload_with_safe_fallbacks(json.dumps(rejected, ensure_ascii=False), "storyboard invalid")

        self.assertTrue(parsed["_storyboard_fallback_applied"])
        self.assertEqual(parsed["storyboard"]["scenes"][0]["type"], "statement")

    def test_lambda_timeout_is_not_rerouted_to_content_backtrack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(
                run_dir / "render_payload.json",
                {
                    "agentVisualRequired": True,
                    "agentVisual": {
                        "enabled": True,
                        "description": "custom visual",
                        "component_code": "return <AbsoluteFill style={{backgroundColor: '#263449'}}><div>Chart</div></AbsoluteFill>;",
                        "css": "",
                    },
                },
            )

            decision = video_loop.reroute_agent_visual_failures(
                run_dir,
                {
                    "status": "fail",
                    "repair_route": "hard_fail",
                    "repair_hint": "Command failed: lambda render timed out; Consider increasing the timeout of your function.",
                    "failed_checks": ["video_attempt_exception"],
                },
            )

        self.assertEqual(decision["repair_route"], "hard_fail")

    def test_agent_visual_compile_error_reroutes_to_content_backtrack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(
                run_dir / "render_payload.json",
                {
                    "agentVisualRequired": True,
                    "agentVisual": {
                        "enabled": True,
                        "description": "custom visual",
                        "component_code": "const progress = frame / durationInFrames; return <div />;",
                        "css": "",
                    },
                },
            )

            decision = video_loop.reroute_agent_visual_failures(
                run_dir,
                {
                    "status": "fail",
                    "repair_route": "hard_fail",
                    "repair_hint": (
                        "Command failed (1): render/prepare_remotion_input.py\n"
                        "esbuild transform failed: The symbol \"progress\" has already been declared"
                    ),
                    "failed_checks": ["video_attempt_exception"],
                },
            )

        self.assertEqual(decision["repair_route"], "content")
        self.assertIn("Regenerate agent_visual.component_code/css", decision["repair_hint"])

    def test_video_feedback_requires_central_motion_not_progress_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            audit_path = run_dir / "gemini_visual_audit.json"
            write_json(
                audit_path,
                {
                    "audit": {"issues": []},
                    "failed_checks": ["audit_contract"],
                    "repair_hint": "motion is caption/progress/fade-only, not central visual motion",
                },
            )

            feedback_path = video_loop.semantic_feedback_from_audit(
                run_dir,
                audit_path,
                1,
                {
                    "failed_checks": ["audit_contract"],
                    "repair_hint": "motion is caption/progress/fade-only, not central visual motion",
                },
            )

            feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
            instruction = feedback["revision_brief"]["instruction"]
            self.assertIn("central visual motion", instruction)
            self.assertIn("Progress bars", instruction)

    def test_video_feedback_names_central_animation_richness_repair_layers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            audit_path = run_dir / "gemini_visual_audit.json"
            write_json(
                audit_path,
                {
                    "audit": {"issues": []},
                    "failed_checks": ["audit_contract"],
                    "repair_hint": "Gemini audit rubric_scores.central_animation_richness is below publish target 7: 6",
                },
            )

            feedback_path = video_loop.semantic_feedback_from_audit(
                run_dir,
                audit_path,
                2,
                {
                    "failed_checks": ["audit_contract"],
                    "repair_hint": "Gemini audit rubric_scores.central_animation_richness is below publish target 7: 6",
                },
            )

            feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
            instruction = feedback["revision_brief"]["instruction"]
            self.assertIn("central_animation_richness", instruction)
            self.assertIn("orbiting nodes", instruction)
            self.assertIn("audio-reactive emphasis", instruction)

    def test_content_backtrack_preserves_spawned_delegation_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            audit_path = run_dir / "gemini_visual_audit.json"
            write_json(
                audit_path,
                {
                    "audit": {"issues": []},
                    "failed_checks": ["audit_contract"],
                    "repair_hint": "Gemini audit rubric_scores.central_animation_richness is below publish target 7: 6",
                },
            )
            captured: dict[str, Any] = {}

            def fake_run_command(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 900) -> dict[str, Any]:
                captured["cmd"] = cmd
                captured["env"] = env or {}
                captured["timeout"] = timeout
                return {"command": " ".join(cmd), "returncode": 0, "stdout_tail": "", "stderr_tail": ""}

            with patch.dict(
                os.environ,
                {
                    "SEARCHPO_DELEGATION_MODE": "spawned_subagents",
                    "SEARCHPO_DELEGATION_AGENT": "searchpo-impl-agent",
                    "SEARCHPO_DELEGATION_PROOF": "impl-proof-123",
                },
                clear=False,
            ), patch.object(video_loop, "run_command", fake_run_command):
                video_loop.run_content_backtrack(
                    run_dir,
                    audit_path,
                    2,
                    {
                        "failed_checks": ["audit_contract"],
                        "repair_hint": "Gemini audit rubric_scores.central_animation_richness is below publish target 7: 6",
                    },
                )

            cmd = captured["cmd"]
            self.assertIn("--delegation-mode", cmd)
            self.assertIn("spawned_subagents", cmd)
            self.assertIn("--delegation-agent", cmd)
            self.assertIn("searchpo-impl-agent", cmd)
            self.assertIn("--delegation-proof", cmd)
            self.assertIn("impl-proof-123", cmd)
            self.assertEqual(captured["env"]["SEARCHPO_VIDEO_FEEDBACK"], str(run_dir / "optimization" / "video" / "pending_content_feedback.json"))

    def test_deterministic_central_static_routes_to_content(self) -> None:
        decision = deterministic_decision(
            {
                "status": "fail",
                "errors": [
                    "central content motion is too sparse; captions/progress/highlights alone are insufficient",
                    "central content remains static for 94.0s, above 10.0s",
                    "first 8s lack central visual movement",
                ],
            }
        )

        self.assertEqual(decision["repair_route"], "content")

    def test_source_grounded_agent_visual_satisfies_layout_contract(self) -> None:
        visual = source_grounded_agent_visual(
            {"title": "Mem0 源码拆解"},
            {
                "repo_context": {
                    "repo": "mem0ai/mem0",
                    "facts": [
                        "mem0/memory/main.py contains add/search flows for writing and retrieving memories",
                        "mem0/utils/factory.py exposes vector-store/provider factory options: qdrant, chroma, pinecone",
                        "server/main.py exposes REST routes including /memories, /search",
                    ],
                }
            },
            {"failed_checks": ["central content remains static"]},
        )

        normalized = require_agent_visual(visual)
        code = normalized["component_code"]
        self.assertIn("mem0/memory/main.py", code)
        self.assertIn("browser chat contrast", visual["description"])
        self.assertIn("nodeGrid", code)
        self.assertIn("provider factory", code)
        self.assertIn("search(query)", code)
        self.assertIn("事件包", code)
        self.assertNotIn("data.cards", code)
        self.assertNotIn("user_id", code)
        self.assertNotIn("agent_id", code)
        self.assertNotIn("position:", code)

    def test_source_grounded_agent_visual_does_not_use_url_as_title(self) -> None:
        visual = source_grounded_agent_visual(
            {"title": "https://mem0.ai/"},
            {"repo_context": {"repo": "mem0ai/mem0", "facts": []}},
            {"failed_checks": ["central content remains static"]},
        )

        code = require_agent_visual(visual)["component_code"]
        self.assertIn('"mem0ai/mem0"', code)
        self.assertNotIn("https://mem0.ai", code)

    def test_source_grounded_agent_visual_uses_article_title_for_query_url(self) -> None:
        visual = source_grounded_agent_visual(
            {"title": "https://qwen.ai/blog?id=qwen3.7-plus", "canonical_url": "https://qwen.ai/blog?id=qwen3.7-plus"},
            {
                "repo_context": {
                    "repo": "qwen.ai",
                    "facts": [
                        "title: Qwen3.7-Plus: Multimodal Agent Intelligence",
                        "Qwen3.7-Plus describes GUI, coding, tools, and verification workflows",
                    ],
                }
            },
            {"failed_checks": ["Gemini audit rubric_scores.central_animation_richness is below publish target 7: 6"]},
        )

        normalized = require_agent_visual(visual)
        code = visual_source_code(visual)
        self.assertIn("export const AgentVisualGenerated", normalized["module_code"])
        self.assertIn("PremiumRepoVisual", code)
        self.assertIn("Premium source-grounded repo visual", visual["description"])
        self.assertNotIn("flowPackets", code)
        self.assertNotIn("token meter", code)
        self.assertNotIn('const title = "qwen.ai"', code)

    def test_source_grounded_agent_visual_uses_current_topic_for_non_mem0(self) -> None:
        visual = source_grounded_agent_visual(
            {"title": "D4Vinci/Scrapling 源码拆解", "canonical_url": "https://github.com/D4Vinci/Scrapling"},
            {
                "repo_context": {
                    "repo": "D4Vinci/Scrapling",
                    "facts": [
                        "scrapling/fetchers.py exposes AdaptiveFetcher for choosing browser or HTTP fetch paths",
                        "scrapling/parser.py includes find_similar() for resilient node selection",
                        "tests/test_fetchers.py covers fetcher behavior and fallback boundaries",
                    ],
                }
            },
            {"failed_checks": ["central content remains static"]},
        )

        normalized = require_agent_visual(visual)
        code = visual_source_code(visual)
        self.assertIn("export const AgentVisualGenerated", normalized["module_code"])
        self.assertIn("PremiumRepoVisual", code)
        self.assertNotIn("AdaptiveFetcher", code)
        self.assertNotIn("find similar()", code)
        self.assertNotIn("find_similar()", code)
        self.assertNotIn("scrapling/fetchers.py", code)
        self.assertIn("Premium source-grounded repo visual", visual["description"])
        self.assertNotIn("flowPackets", code)
        self.assertNotIn("token meter", code)
        self.assertNotIn("evalBars", code)
        self.assertNotIn("cursorTargets", code)
        self.assertNotIn("stages.map(stageTile)", code)
        self.assertNotIn("mem0/memory/main.py", code)
        self.assertNotIn("Memory.add", code)
        self.assertNotIn("search(query)", code)

    def test_motion_feedback_overrides_valid_generic_visual(self) -> None:
        polished = polish_payload(1)
        polished["agent_visual"] = {
            "enabled": True,
            "render_mode": "full_canvas",
            "description": "Generic card visual",
            "component_code": (
                "return <AbsoluteFill style={{backgroundColor: '#263449', color: '#f8fafc', "
                "padding: '160px 70px 620px'}}><div>ADD EMBED SEARCH</div></AbsoluteFill>;"
            ),
            "css": "",
        }
        polished["video_profile"] = {"duration_seconds": 90, "orientation": "vertical"}
        feedback = {
            "failed_checks": [
                "central content motion is too sparse; captions/progress/highlights alone are insufficient",
                "central content remains static for 76.0s, above 10.0s",
            ],
            "revision_brief": {"instruction": "Add central visual motion beyond captions/progress bars."},
        }

        self.assertTrue(motion_feedback_requires_source_visual(feedback))
        repaired = apply_source_visual_for_motion_feedback(
            {"title": "Mem0 源码拆解"},
            polished,
            {
                "repo_context": {
                    "repo": "mem0ai/mem0",
                    "facts": [
                        "mem0/memory/main.py contains add/search flows for writing and retrieving memories",
                    ],
                }
            },
            feedback,
            video_profile={"orientation": "vertical"},
        )

        self.assertTrue(repaired["_deterministic_agent_visual_repair"])
        self.assertIn("mem0/memory/main.py", repaired["agent_visual"]["component_code"])
        self.assertIn("nodeGrid", repaired["agent_visual"]["component_code"])
        self.assertIn("provider factory", repaired["agent_visual"]["component_code"])
        self.assertIn("search(query)", repaired["agent_visual"]["component_code"])
        self.assertIn("事件包", repaired["agent_visual"]["component_code"])
        self.assertNotIn("ADD EMBED SEARCH", repaired["agent_visual"]["component_code"])

    def test_central_animation_richness_feedback_overrides_valid_generic_visual(self) -> None:
        polished = polish_payload(1)
        polished["agent_visual"] = {
            "enabled": True,
            "render_mode": "full_canvas",
            "description": "Existing valid but thin visual",
            "component_code": (
                "return <AbsoluteFill style={{backgroundColor: '#263449', color: '#f8fafc', "
                "padding: '160px 70px 620px'}}><div>thin node pulse</div></AbsoluteFill>;"
            ),
            "css": "",
        }
        polished["video_profile"] = {"duration_seconds": 90, "orientation": "vertical"}
        feedback = {
            "failed_checks": ["audit_contract"],
            "revision_brief": {
                "instruction": "Gemini audit rubric_scores.central_animation_richness is below publish target 7: 6"
            },
        }

        self.assertTrue(motion_feedback_requires_source_visual(feedback))
        repaired = apply_source_visual_for_motion_feedback(
            {"title": "Qwen3.7-Plus", "canonical_url": "https://qwen.ai/blog?id=qwen3.7-plus"},
            polished,
            {
                "repo_context": {
                    "repo": "qwen.ai",
                    "facts": [
                        "Qwen3.7-Plus introduces a multimodal agent workflow",
                        "The article emphasizes GUI, code, tool use, and verification",
                    ],
                }
            },
            feedback,
            video_profile={"orientation": "vertical"},
        )

        code = visual_source_code(repaired["agent_visual"])
        self.assertTrue(repaired["_deterministic_agent_visual_repair"])
        self.assertIn("PremiumRepoVisual", code)
        self.assertNotIn("flowPackets", code)
        self.assertNotIn("token meter", code)
        self.assertNotIn("evalBars", code)
        self.assertNotIn("cursorTargets", code)
        self.assertNotIn("thin node pulse", code)

    def test_generic_motion_feedback_repair_scrubs_visual_claim_terms(self) -> None:
        polished = polish_payload(1)
        polished["agent_visual"] = {
            "enabled": True,
            "render_mode": "full_canvas",
            "description": "Generic card visual",
            "component_code": "return <AbsoluteFill><div>Only source facts</div></AbsoluteFill>;",
            "css": "",
        }
        feedback = {
            "failed_checks": ["central visual motion needs richer source-grounded layers"],
            "revision_brief": {"instruction": "Regenerate central visual motion."},
        }

        repaired = apply_source_visual_for_motion_feedback(
            {"title": "https://qwen.ai/blog?id=qwen3.7-plus", "canonical_url": "https://qwen.ai/blog?id=qwen3.7-plus"},
            polished,
            {"facts": ["title: Qwen3.7-Plus: Multimodal Agent Intelligence"]},
            feedback,
            video_profile={"orientation": "vertical"},
        )

        self.assertTrue(repaired["_deterministic_agent_visual_repair"])
        self.assertEqual(unsafe_hits_for(repaired), [])

    def test_candidate_reference_repair_prefixes_voiceover_anchor(self) -> None:
        polished = polish_payload(1)
        polished["voiceover_text"] = "这是一段没有英文锚点的中文解释。"

        repaired = ensure_candidate_reference(
            {"title": "Harness Complexity Paradox arXiv 2605.26731 DAIR.AI X post"},
            polished,
        )

        self.assertTrue(repaired["_candidate_reference_repaired"])
        self.assertIn("arXiv 2605.26731", repaired["voiceover_text"])

    def test_score_target_report_requires_best_practice_threshold(self) -> None:
        base_scores = {
            "hook_strength": 8,
            "retention_structure": 8,
            "information_density": 7,
            "emotional_tension": 8,
            "claim_safety": 8,
            "douyin_algorithm_fit": 8,
            "constructive_interaction_fit": 8,
            "recommendation_eligibility_safety": 8,
            "constructive_interpretation": 8,
            "format_fit": 8,
            "custom_visual_fit": 8,
            "long_form_structure": 8,
            "open_source_explainer_value": 8,
        }
        report = score_target_report(
            {"overall": 7.9, "scores": {**base_scores, "information_density": 6}},
            {"blocking_issues": []},
        )

        self.assertFalse(report["target_met"])
        self.assertTrue(report["eligible_for_revision"])
        self.assertEqual(report["failed_dimensions"], {"information_density": 6.0})

        passing = score_target_report(
            {"overall": 8.4, "scores": base_scores},
            {"blocking_issues": []},
        )
        self.assertTrue(passing["target_met"])
        self.assertFalse(passing["eligible_for_revision"])

    def test_content_blocking_rejects_midlength_three_scene_plan(self) -> None:
        polish = polish_payload(1)
        polish["video_profile"] = {"duration_seconds": 75, "orientation": "vertical", "aspect_ratio": "9:16"}
        polish["storyboard"] = {
            "version": 1,
            "scenes": [
                {"type": "statement", "props": {"title": "Demo Tool 先看问题"}},
                {"type": "bullets", "props": {"heading": "三点", "items": ["机制", "边界", "验证"]}},
                {"type": "cta", "props": {"text": "按证据判断"}},
            ],
        }

        checks = deterministic_blocking_checks(
            polish,
            {"title": "Demo Tool", "canonical_url": "https://example.com/demo"},
            {"sources": [{"id": "primary_url"}], "evidence_summary": {"source_facts": ["Demo Tool has a verification path"]}},
            {
                "status": "pass",
                "research_sufficient": True,
                "fact_bank_status": "pass",
                "supplemental_source_count": 2,
                "independent_source_hosts": ["a.example", "b.example"],
            },
        )

        joined = "; ".join(checks["blocking_issues"])
        self.assertIn("75s requires at least 5 storyboard scenes", joined)

        report = score_target_report({"overall": 8.7, "scores": {"hook_strength": 8}}, checks)
        self.assertFalse(report["target_met"])
        self.assertTrue(report["eligible_for_revision"])
        self.assertIn("75s requires at least 5 storyboard scenes", "; ".join(report["revision_brief"]["blocking_issues"]))

    def test_storyboard_structure_repair_expands_midlength_template(self) -> None:
        polish = polish_payload(1)
        polish["polished_title"] = "Qwen3.7-Plus 多模态智能体"
        polish["voiceover_text"] = "它不是只做聊天，而是把看屏幕、读界面、写代码和调工具放进一个循环。官方来源说明它强调 GUI 和 CLI 结合。采用前要用真实任务复测失败样例。"
        polish["video_profile"] = {"duration_seconds": 75, "orientation": "vertical", "aspect_ratio": "9:16"}
        polish["storyboard"] = {
            "version": 1,
            "scenes": [
                {"type": "statement", "props": {"title": "Qwen3.7-Plus"}},
                {"type": "bullets", "props": {"heading": "三点", "items": ["看屏幕", "写代码", "做验证"]}},
                {"type": "cta", "props": {"text": "按证据判断"}},
            ],
        }

        repaired = repair_storyboard_structure(
            {"title": "Qwen3.7-Plus", "canonical_url": "https://qwen.ai/blog?id=qwen3.7-plus"},
            {"fact_bank": {"source_backed_facts": ["Qwen3.7-Plus blends GUI and CLI interactions."]}},
            {"evidence_summary": {"source_facts": ["official blog describes multimodal agent intelligence"]}},
            polish,
        )

        scenes = repaired["storyboard"]["scenes"]
        scene_types = [scene["type"] for scene in scenes]
        self.assertGreaterEqual(len(scenes), 5)
        self.assertEqual(scene_types[0], "statement")
        self.assertEqual(scene_types[-1], "cta")
        self.assertGreaterEqual(len(set(scene_types)), 4)
        self.assertGreaterEqual(sum(1 for scene_type in scene_types if scene_type in {"terminal", "flow", "chart", "code_diff", "compare_table", "compare", "bullets", "stat"}), 3)
        self.assertEqual(repaired["_storyboard_structure_repair"]["after"]["scene_count"], len(scenes))

    def test_source_grounded_visual_exposes_six_states(self) -> None:
        visual = source_grounded_agent_visual(
            {"title": "https://qwen.ai/blog?id=qwen3.7-plus", "canonical_url": "https://qwen.ai/blog?id=qwen3.7-plus"},
            {
                "repo_context": {
                    "repo": "qwen.ai",
                    "facts": [
                        "title: Qwen3.7-Plus: Multimodal Agent Intelligence",
                        "Qwen3.7-Plus describes GUI, coding, tools, and verification workflows",
                        "facebook.com: **Source**: https://www.facebook.com/alibabacloud/posts/example ---",
                    ],
                }
            },
            {"failed_checks": ["agent_visual has too few visible states"]},
        )

        code = visual_source_code(visual)
        self.assertGreaterEqual(_visual_state_hint_count(code), 6)
        self.assertNotIn("https://", code)
        self.assertIn("PremiumRepoVisual", code)

    def test_source_grounded_visual_honors_minimum_state_count(self) -> None:
        visual = source_grounded_agent_visual(
            {"title": "https://qwen.ai/blog?id=qwen3.7-plus", "canonical_url": "https://qwen.ai/blog?id=qwen3.7-plus"},
            {
                "repo_context": {
                    "repo": "qwen.ai",
                    "facts": [
                        "title: Qwen3.7-Plus: Multimodal Agent Intelligence",
                        "Qwen3.7-Plus describes GUI, coding, tools, and verification workflows",
                    ],
                }
            },
            {"failed_checks": ["agent_visual has too few visible states"]},
            min_state_count=7,
        )

        code = visual_source_code(visual)
        self.assertGreaterEqual(_visual_state_hint_count(code), 7)
        self.assertIn("Risk check", code)

    def test_agent_visual_structure_repair_replaces_four_state_loop(self) -> None:
        polish = polish_payload(1)
        polish["video_profile"] = {"duration_seconds": 75, "orientation": "vertical", "aspect_ratio": "9:16"}
        polish["agent_visual"] = {
            "enabled": True,
            "render_mode": "full_canvas",
            "description": "four state loop",
            "component_code": 'const stages = [{"label":"看屏幕"},{"label":"写代码"},{"label":"调工具"},{"label":"做验证"}]; return <AbsoluteFill />;',
            "css": "",
        }

        repaired = repair_agent_visual_structure(
            {"title": "https://qwen.ai/blog?id=qwen3.7-plus", "canonical_url": "https://qwen.ai/blog?id=qwen3.7-plus"},
            {
                "repo_context": {
                    "repo": "qwen.ai",
                    "facts": [
                        "title: Qwen3.7-Plus: Multimodal Agent Intelligence",
                        "Qwen3.7-Plus describes GUI, coding, tools, and verification workflows",
                    ],
                }
            },
            polish,
        )

        self.assertGreaterEqual(_visual_state_hint_count(visual_source_code(repaired["agent_visual"])), 6)
        self.assertEqual(repaired["_agent_visual_structure_repair"]["before_state_hint_count"], 4)

    def test_agent_visual_structure_repair_uses_video_feedback_required_count(self) -> None:
        polish = polish_payload(1)
        polish["video_profile"] = {"duration_seconds": 75, "orientation": "vertical", "aspect_ratio": "9:16"}
        polish["agent_visual"] = {
            "enabled": True,
            "render_mode": "full_canvas",
            "description": "six state loop",
            "component_code": (
                'const stages = [{"label":"看屏幕"},{"label":"读界面"},{"label":"写代码"},'
                '{"label":"调工具"},{"label":"跑基准"},{"label":"做验证"}]; return <AbsoluteFill />;'
            ),
            "css": "",
        }

        repaired = repair_agent_visual_structure(
            {"title": "https://qwen.ai/blog?id=qwen3.7-plus", "canonical_url": "https://qwen.ai/blog?id=qwen3.7-plus"},
            {
                "repo_context": {
                    "repo": "qwen.ai",
                    "facts": [
                        "title: Qwen3.7-Plus: Multimodal Agent Intelligence",
                        "Qwen3.7-Plus describes GUI, coding, tools, and verification workflows",
                    ],
                }
            },
            polish,
            {"failed_checks": ["agent_visual has too few visible states for 125.8s video: detected 6, requires at least 7"]},
        )

        self.assertGreaterEqual(_visual_state_hint_count(visual_source_code(repaired["agent_visual"])), 7)
        self.assertEqual(repaired["_agent_visual_structure_repair"]["required_state_hint_count"], 7)

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
            revision_feedback={
                "overall": 5.7,
                "failed_dimensions": {"hook_strength": 5},
                "blocking_checks": {"blocking_issues": ["video duration 75s requires at least 5 storyboard scenes, got 3"]},
                "suggestions": ["make hook concrete"],
            },
            attempt=2,
        )

        user = json.loads(body["messages"][1]["content"])
        self.assertEqual(user["task"], "Revise one complete source-bounded video package using Gemini evaluator feedback.")
        self.assertEqual(user["gemini_feedback"]["failed_dimensions"], {"hook_strength": 5})
        self.assertIn("video duration 75s requires", user["gemini_feedback"]["blocking_issues"][0])
        self.assertEqual(user["previous_polish"]["polished_title"], "Demo Tool hook 1")
        self.assertEqual(user["evidence_bundle"]["source_facts"], ["official fact"])
        self.assertIn("Preserve the selected candidate boundary", " ".join(user["revision_rules"]))
        self.assertIn("Resolve every blocking_issues item", " ".join(user["revision_rules"]))

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

    def test_content_loop_revises_revisionable_fail_verdict(self) -> None:
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
                                "overall": 8.7,
                                "verdict": "fail",
                                "target_met": False,
                                "eligible_for_revision": True,
                                "failed_dimensions": {},
                                "blocking_checks": {
                                    "blocking_issues": ["video duration 75s requires at least 5 storyboard scenes, got 3"],
                                    "hard_blocking_issues": [],
                                    "revisionable_blocking_issues": [
                                        "video duration 75s requires at least 5 storyboard scenes, got 3"
                                    ],
                                },
                                "revision_brief": {
                                    "blocking_issues": ["video duration 75s requires at least 5 storyboard scenes, got 3"]
                                },
                                "suggestions": ["split the visual structure"],
                            },
                        )
                    else:
                        write_json(
                            output,
                            {
                                "overall": 8.4,
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
            summary = json.loads((run_dir / "content_optimization_loop.json").read_text())
            self.assertEqual(summary["attempt_count"], 2)
            self.assertEqual(summary["attempts"][0]["verdict"], "fail")
            self.assertTrue(summary["attempts"][0]["eligible_for_revision"])
            self.assertEqual(summary["attempts"][1]["mode"], "revise")


class VideoImproveLoopTests(unittest.TestCase):
    def test_deterministic_audit_accepts_horizontal_publish_layout(self) -> None:
        report, errors = _publish_layout_check({"width": 1920, "height": 1080, "orientation": "horizontal"})

        self.assertEqual(report["status"], "pass")
        self.assertEqual(errors, [])
        self.assertEqual(report["expected"]["aspect_ratio"], "16:9")

    def test_deterministic_structure_rejects_repeated_short_visual_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(
                run_dir / "remotion_input_props.json",
                {
                    "durationInFrames": 3026,
                    "fps": 30,
                    "videoProfile": {"duration_seconds": 75},
                    "storyboard": {
                        "version": 1,
                        "scenes": [
                            {"type": "statement", "props": {"title": "Qwen3 先看问题"}},
                            {"type": "bullets", "props": {"heading": "三点", "items": ["看屏幕", "写代码", "做验证"]}},
                            {"type": "cta", "props": {"text": "按证据判断"}},
                        ],
                    },
                    "agentVisual": {
                        "enabled": True,
                        "render_mode": "overlay",
                        "component_code": 'const stages = [{"label":"看屏幕"},{"label":"写代码"},{"label":"调工具"},{"label":"做验证"}]; return <AbsoluteFill />;',
                    },
                },
            )

            report, errors = _visual_structure_check(run_dir, 3026, 30)

        self.assertEqual(report["status"], "fail")
        joined = "; ".join(errors)
        self.assertIn("storyboard has 3 scenes, requires at least 6", joined)
        self.assertIn("only 1 motion-rich scenes", joined)

    def test_deterministic_structure_allows_full_canvas_agent_visual_state_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(
                run_dir / "remotion_input_props.json",
                {
                    "durationInFrames": 3026,
                    "fps": 30,
                    "videoProfile": {"duration_seconds": 75},
                    "storyboard": {
                        "version": 1,
                        "scenes": [
                            {"type": "statement", "props": {"title": "Qwen3 先看问题"}},
                            {"type": "cta", "props": {"text": "按证据判断"}},
                        ],
                    },
                    "agentVisual": {
                        "enabled": True,
                        "render_mode": "full_canvas",
                        "component_code": (
                            'const states = [{"label":"看屏幕"},{"label":"写代码"},{"label":"调工具"},'
                            '{"label":"做验证"},{"label":"看风险"},{"label":"留边界"}]; return <AbsoluteFill />;'
                        ),
                    },
                },
            )

            report, errors = _visual_structure_check(run_dir, 3026, 30)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(errors, [])

    def test_deterministic_motion_metrics_detect_static_center(self) -> None:
        frame_size = 4
        raw = bytes([10, 10, 10, 10] * 4)
        pairs = _motion_pairs(raw, frame_size)
        active = [pair["changed_pixel_ratio"] >= 0.012 or pair["mean_abs_delta"] >= 1.8 for pair in pairs]

        self.assertFalse(any(active))
        self.assertEqual(_max_inactive_seconds(active, 1.0), 3.0)

        moving_raw = bytes([0, 0, 0, 0, 80, 80, 80, 80, 160, 160, 160, 160])
        moving_pairs = _motion_pairs(moving_raw, frame_size)
        self.assertTrue(all(pair["changed_pixel_ratio"] >= 0.012 for pair in moving_pairs))

    def test_deterministic_visual_intent_rejects_cards_only_agent_visual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(
                run_dir / "render_payload.json",
                {
                    "agentVisualRequired": True,
                    "agentVisual": {
                        "enabled": True,
                        "description": "Custom Remotion visual with evidence cards and progress-linked highlights.",
                        "component_code": "const safeCards = data.cards || []; return <AbsoluteFill>{safeCards.length}</AbsoluteFill>;",
                        "css": "",
                    },
                },
            )

            report, errors = _visual_intent_check(run_dir)

            self.assertEqual(report["status"], "fail")
            joined = "; ".join(errors)
            self.assertIn("compatibility cards", joined)
            self.assertIn("topic-specific visual primitives", joined)

    def test_deterministic_visual_intent_rejects_hardcoded_other_topic_visual(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(
                run_dir / "selected_candidate.json",
                {"title": "D4Vinci/Scrapling", "canonical_url": "https://github.com/D4Vinci/Scrapling"},
            )
            write_json(
                run_dir / "render_payload.json",
                {
                    "agentVisualRequired": True,
                    "displayTitle": "D4Vinci/Scrapling",
                    "agentVisual": {
                        "enabled": True,
                        "description": "terminal code flow for Scrapling",
                        "component_code": (
                            "return <AbsoluteFill style={{backgroundColor: '#263449'}}>"
                            "<div>D4Vinci/Scrapling terminal code diagram mem0/memory/main.py MemoryClient</div>"
                            "</AbsoluteFill>;"
                        ),
                        "css": "",
                    },
                },
            )

            report, errors = _visual_intent_check(run_dir)

            self.assertEqual(report["status"], "fail")
            self.assertIn("different topic", "; ".join(errors))

    def test_deterministic_visual_intent_rejects_overcrowded_dashboard_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(run_dir / "selected_candidate.json", {"title": "Qwen3-Coder", "canonical_url": "https://github.com/QwenLM/Qwen3-Coder"})
            write_json(
                run_dir / "render_payload.json",
                {
                    "agentVisualRequired": True,
                    "displayTitle": "Qwen3-Coder",
                    "agentVisual": {
                        "enabled": True,
                        "render_mode": "full_canvas",
                        "description": "SOURCE FLOW dashboard with benchmark bars, status bars, fact cards, and orbit packets.",
                        "component_code": (
                            "const evalBars = stages.map((item) => item.tag); "
                            "const stageTile = (item) => <div />; "
                            "const factsBrief = ['stars','language']; "
                            "const orbitPackets = []; const streamPackets = []; "
                            "return <AbsoluteFill><text>SOURCE FLOW</text>{evalBars.map(Boolean)}"
                            "{stages.map(stageTile)}{factsBrief.slice(0, 2).map(Boolean)}{orbitPackets.map(Boolean)}</AbsoluteFill>;"
                        ),
                        "css": "",
                    },
                },
            )

            report, errors = _visual_intent_check(run_dir)

            self.assertEqual(report["status"], "fail")
            self.assertIn("visually overcrowded", "; ".join(errors))
            self.assertGreaterEqual(len(report["visual_density_markers"]), 4)

    def test_deterministic_visual_intent_rejects_headroom_style_orbit_swarm_from_prepared_props(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(run_dir / "selected_candidate.json", {"title": "chopratejas/headroom", "canonical_url": "https://github.com/chopratejas/headroom"})
            write_json(
                run_dir / "remotion_input_props.json",
                {
                    "agentVisualRequired": True,
                    "displayTitle": "chopratejas/headroom",
                    "agentVisual": {
                        "enabled": True,
                        "render_mode": "full_canvas",
                        "description": "dynamic circular module diagram with orbiting nodes, flow packets, grid dots, scanner sweep, and glow filters",
                        "module_code": (
                            "const flowPackets = useMemo(() => Array.from({length: 12}, (_, index) => index), []); "
                            "const gridDots = useMemo(() => Array.from({length: 42}, (_, index) => index), []); "
                            "const scanner = 16 + ((frame * 4) % 438); "
                            "const angle = frame / 31 + index * 0.785; "
                            "return <AbsoluteFill><svg><filter id='wideGlow'><feGaussianBlur stdDeviation='8' /></filter>"
                            "<path strokeDashoffset={-frame * 3}/>{gridDots.map(Boolean)}{flowPackets.map(Boolean)}"
                            "{files.slice(0, 5).map(Boolean)}</svg></AbsoluteFill>;"
                        ),
                        "css": "",
                    },
                },
            )

            report, errors = _visual_intent_check(run_dir)

            self.assertEqual(report["status"], "fail")
            self.assertIn("visually overcrowded", "; ".join(errors))
            self.assertIn("flow_packet_train", report["visual_density_markers"])
            self.assertIn("animated_grid_dots", report["visual_density_markers"])
            self.assertIn("continuous_orbit", report["visual_density_markers"])

    def test_visual_intent_allows_screen_code_tool_when_supported_by_evidence_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(
                run_dir / "selected_candidate.json",
                {"title": "Qwen3.7-Plus multimodal coding agent release", "canonical_url": "https://qwen.ai/blog?id=qwen3.7-plus"},
            )
            write_json(
                run_dir / "render_payload.json",
                {
                    "agentVisualRequired": True,
                    "displayTitle": "Qwen3.7-Plus",
                    "agentVisual": {
                        "enabled": True,
                        "description": "screen-code-tool VLM flow with code terminal diagram for Qwen3.7-Plus",
                        "component_code": "const stages = [{label:'screen'},{label:'code'},{label:'tool'}]; return <AbsoluteFill />;",
                        "css": "",
                    },
                },
            )
            write_json(
                run_dir / "evidence_bundle.json",
                {
                    "evidence_summary": {
                        "source_facts": [
                            "The model description mentions GUI screen interaction, coding workflow, CLI tool use, and terminal verification."
                        ]
                    }
                },
            )

            report, errors = _visual_intent_check(run_dir)

            self.assertEqual(report["status"], "pass")
            self.assertEqual(errors, [])

    def test_visual_audit_routes_failed_checks(self) -> None:
        safe_area = classify_audit_result({"checks": {"douyin_safe_area": False}, "issues": ["caption too low"]}, "fail")
        semantic = classify_audit_result({"checks": {"content_has_constructive_insight": False}, "issues": ["too generic"]}, "fail")
        hard = classify_audit_result({"checks": {"video_readable": False}, "issues": ["blank"]}, "fail")
        subject_alignment = classify_audit_result(
            {
                "checks": {"audio_visual_alignment_safe": False},
                "issues": ["spoken subject is Bedrock but visual subject is a GUI/VLM loop"],
            },
            "fail",
        )
        caption_timing = classify_audit_result(
            {"checks": {"audio_visual_alignment_safe": False}, "issues": ["caption timing is late"]},
            "fail",
        )

        self.assertEqual(safe_area["repair_route"], "caption")
        self.assertEqual(semantic["repair_route"], "content")
        self.assertEqual(hard["repair_route"], "hard_fail")
        self.assertEqual(subject_alignment["repair_route"], "content")
        self.assertEqual(caption_timing["repair_route"], "caption")

    def test_audit_contract_motion_failures_route_to_content_not_caption(self) -> None:
        route = route_contract_errors(
            [
                "timeline_reviews[1] motion is caption/progress/fade-only, not central visual motion",
                "Gemini audit required check `not_cards_only_template` did not pass",
            ]
        )

        self.assertEqual(route, "content")

    def test_visual_audit_pass_requires_native_video_timeline_reviews(self) -> None:
        weak_pass = {
            "verdict": "pass",
            "checks": {"video_readable": True, "publish_ready": True},
            "summary": "Looks fine.",
            "issues": [],
        }
        self.assertIn("timeline_reviews", "; ".join(audit_contract_errors(weak_pass)))
        frame_only_pass = {
            "verdict": "pass",
            "checks": {"video_readable": True, "publish_ready": True},
            "frame_reviews": [{"timestamp": "00:01", "commentary": "Static frame review"}],
            "motion_assessment": {"level": "adequate", "commentary": "Motion is visible in the video."},
        }
        self.assertIn("frame_reviews", "; ".join(audit_contract_errors(frame_only_pass)))

        detailed_pass = {
            "verdict": "pass",
            "checks": {
                "video_readable": True,
                "full_native_video_reviewed": True,
                "native_video_audio_reviewed": True,
                "publish_ready": True,
                "douyin_vertical_format": True,
                "voiceover_visual_same_subject": True,
                "captions_match_spoken_audio": True,
                "background_music_mix_safe": True,
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
                    "commentary": "Opening moment shows a readable title and moving interface blocks.",
                    "spoken_audio_observation": "The native MP4 voiceover introduces Demo Tool as a source-bounded developer workflow example.",
                    "background_music_observation": "Background music is present only as a low bed and does not mask the voiceover.",
                    "visual_subject": "The central visual shows Demo Tool workflow blocks and evidence panels.",
                    "spoken_subject": "The spoken subject is Demo Tool workflow evidence and verification.",
                    "audio_visual_subject_alignment": "The visual workflow blocks and the spoken Demo Tool verification topic describe the same subject at the opening.",
                    "text_readability": "The title and interface labels are legible with clear contrast.",
                    "caption_progress_alignment": "Global caption sits above the reserved bottom band without overlap.",
                    "motion_observation": "The central diagram nodes slide into position while a flow line builds between the evidence panels.",
                },
                {
                    "timestamp": "00:30",
                    "commentary": "Middle moment keeps the diagram readable while the metric panel changes.",
                    "spoken_audio_observation": "The native MP4 voiceover explains Demo Tool mechanism and tradeoff boundaries.",
                    "background_music_observation": "Music remains below speech and the voiceover stays intelligible.",
                    "visual_subject": "The central visual shows the same Demo Tool mechanism diagram and metric panel.",
                    "spoken_subject": "The spoken subject is Demo Tool mechanism and tradeoff boundaries.",
                    "audio_visual_subject_alignment": "The mechanism diagram builds while the voiceover explains the same mechanism and tradeoff.",
                    "text_readability": "Diagram labels and metric values remain readable at phone size.",
                    "caption_progress_alignment": "Subtitle and character progress stay in one global caption layer.",
                    "motion_observation": "The metric chart bars grow while the active mechanism node pulses in the central diagram.",
                },
                {
                    "timestamp": "01:00",
                    "commentary": "Late moment still has clean hierarchy and no cropped text.",
                    "spoken_audio_observation": "The native MP4 voiceover closes by naming the verification boundary for Demo Tool.",
                    "background_music_observation": "Background music stays low and does not compete with the closing voiceover.",
                    "visual_subject": "The central visual shows Demo Tool verification gates and CTA state.",
                    "spoken_subject": "The spoken subject is Demo Tool verification and adoption boundary.",
                    "audio_visual_subject_alignment": "The verification gates on screen match the spoken verification boundary at the ending.",
                    "text_readability": "Late-frame body text and CTA remain inside their safe bounds.",
                    "caption_progress_alignment": "Caption remains separated from the main visual content.",
                    "motion_observation": "The verification gate line sweeps across the central panel and the CTA node scales with the voice beat.",
                },
            ],
            "motion_assessment": {"level": "adequate", "commentary": "Motion is visible through central diagram node movement, chart bar growth, and flow line sweeps."},
            "audio_track_assessment": {
                "voiceover": "The native MP4 voiceover is clear and follows the same Demo Tool evidence narrative shown by the visuals.",
                "background_music": "Background music is audible as a low supporting bed and does not mask speech.",
                "mix": "Voiceover remains dominant over music with no audible clipping, dropouts, or masking.",
                "issues": [],
            },
            "subject_alignment": {
                "spoken_subject": "The voiceover is about Demo Tool as a source-bounded developer workflow and verification example.",
                "visual_subject": "The central visuals show Demo Tool workflow blocks, evidence panels, mechanism diagram, and verification gates.",
                "matches": True,
                "mismatches": [],
                "evidence": "At 00:01, 00:30, and 01:00 the spoken Demo Tool mechanism and verification points match the visible workflow, metric, and gate panels.",
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
                "opening_hook": "Opening uses a visible interface problem before moving into the explanation.",
                "middle_delivery": "Middle section builds the diagram and metric panel instead of dumping static text.",
                "ending_payoff": "Ending keeps the CTA readable and leaves a concrete verification boundary.",
                "pacing_issue": "No major pacing issue because each section has readable dwell time.",
            },
            "animation_diagnostics": {
                "main_motion_layers": ["spring card reveal", "staggered diagram node build", "flow beam movement"],
                "topic_specific_objects": ["diagram panel", "metric chart"],
                "weak_motion": ["progress bar is secondary only"],
                "recommended_repair": "",
            },
            "composition_director": {
                "primary_focal_target": "The central mechanism diagram and its active flow-line build.",
                "competing_visual_systems": ["Global captions as a secondary safe-area layer"],
                "simultaneous_motion_system_count": 2,
                "clutter_level": "medium",
                "hierarchy_issue": "none, the central diagram stays largest and the side text remains secondary.",
                "overload_issue": "none, only the central diagram and one caption layer move at the same time.",
                "director_verdict": "pass",
            },
        }
        self.assertEqual(audit_contract_errors(detailed_pass), [])
        old_visual_only_gemini_pass = {
            "verdict": "pass",
            "checks": {
                "video_readable": True,
                "text_not_overlapping": True,
                "candidate_matches_artifacts": True,
                "no_unsupported_claims": True,
                "voiceover_matches_copy": True,
                "cover_text_safe": True,
                "no_internal_terms": True,
                "no_hype_without_evidence": True,
                "speech_pronunciation_safe": True,
                "audio_visual_alignment_safe": True,
                "central_motion_not_caption_or_progress_only": True,
                "topic_specific_visual": True,
                "not_cards_only_template": True,
                "publish_ready": True,
                "content_has_constructive_insight": True,
                "douyin_safe_area": True,
                "douyin_vertical_format": True,
            },
            "timeline_reviews": [
                {
                    "timestamp": "00:00.000",
                    "commentary": "The video opens with the GUI tab active and a central VLM loop diagram.",
                    "text_readability": "Text is legible.",
                    "caption_progress_alignment": "Captions are aligned with the spoken intro regarding AWS and OpenAI.",
                    "motion_observation": "Orange circles pulse around GUI and VLM nodes.",
                    "issues": [],
                },
                {
                    "timestamp": "00:19.000",
                    "commentary": "The interface tab changes and the active node shifts to Bedrock.",
                    "text_readability": "Text is legible.",
                    "caption_progress_alignment": "Captions update with the Bedrock explanation.",
                    "motion_observation": "The highlight path moves from GUI to Bedrock.",
                    "issues": [],
                },
                {
                    "timestamp": "00:38.000",
                    "commentary": "The writing-code tab becomes active and terminal indicators flash.",
                    "text_readability": "Text is legible.",
                    "caption_progress_alignment": "Captions match the spoken SageMaker explanation.",
                    "motion_observation": "The CODE node and terminal indicators flash.",
                    "issues": [],
                },
            ],
            "motion_assessment": {
                "level": "adequate",
                "commentary": "The video features node highlights and path animations.",
            },
            "rubric_scores": {
                "hook_clarity": 7,
                "scene_pacing": 7,
                "visual_hierarchy": 7,
                "central_animation_richness": 7,
                "topic_visual_fit": 7,
                "caption_safe_area": 7,
                "audio_visual_sync": 7,
                "evidence_guardrail": 7,
            },
            "narrative_structure": {
                "opening_hook": "The video starts by discussing OpenAI models securely on AWS.",
                "middle_delivery": "The middle explains Bedrock and SageMaker with a flow diagram.",
                "ending_payoff": "The ending gives a verification path.",
                "pacing_issue": "none, with evidence",
            },
            "animation_diagnostics": {
                "main_motion_layers": ["Active node pulse indicators", "Staggered tab transitions", "Animated path connections"],
                "topic_specific_objects": ["VLM Loop architecture diagram", "AWS Bedrock and SageMaker node blocks"],
                "weak_motion": ["Bottom progress bar", "Subtitle text highlights"],
                "recommended_repair": "",
            },
        }
        old_errors = "; ".join(audit_contract_errors(old_visual_only_gemini_pass))
        self.assertIn("native_video_audio_reviewed", old_errors)
        self.assertIn("subject_alignment", old_errors)
        self.assertIn("audio_track_assessment", old_errors)

        horizontal_pass = {
            **detailed_pass,
            "checks": {
                **{key: value for key, value in detailed_pass["checks"].items() if key not in {"douyin_vertical_format", "douyin_safe_area"}},
                "profile_format_match": True,
            },
        }
        self.assertEqual(audit_contract_errors(horizontal_pass, expected_orientation="horizontal"), [])

        headroom_horizontal_pass = {
            **horizontal_pass,
            "motion_assessment": {
                "level": "strong",
                "commentary": (
                    "The video features continuous, smooth orbital rotation of nodes "
                    "and active pulsing transitions that keep the visual system dynamic."
                ),
            },
            "animation_diagnostics": {
                "main_motion_layers": [
                    "Token meter percentage counting up and down dynamically",
                    "Central circular pipeline diagram rotating and pulsing active nodes",
                    "Left repository panel highlighting active modules",
                ],
                "topic_specific_objects": [
                    "Token meter panel with README claim and live demo metrics",
                    "Compression pipeline diagram with SOURCE, CACHE, ROUTE, JSON, CODE, TEXT, VERIFY nodes",
                ],
                "weak_motion": [],
                "recommended_repair": "",
            },
        }
        self.assertEqual(audit_contract_errors(headroom_horizontal_pass, expected_orientation="horizontal"), [])

        headroom_native_review_pass = {
            **horizontal_pass,
            "timeline_reviews": [
                {
                    "timestamp": "00:00",
                    "commentary": "Opening scene introduces the core problem of context window pressure with a clean terminal simulation.",
                    "spoken_audio_observation": "The native MP4 voiceover asks whether AI coding or agent runs have hit context window pressure.",
                    "background_music_observation": "Background music is mixed safely below the voiceover.",
                    "visual_subject": "Terminal simulation showing agent run tool output.",
                    "spoken_subject": "AI coding and agent context window pressure.",
                    "audio_visual_subject_alignment": "The visual terminal output directly aligns with the spoken context of running AI agents.",
                    "text_readability": "Text is highly readable with high contrast on a dark background.",
                    "caption_progress_alignment": "Captions and progress bar are synchronized with the voiceover.",
                    "motion_observation": "Terminal text lines and status indicators animate sequentially.",
                    "issues": [],
                },
                {
                    "timestamp": "00:35",
                    "commentary": "Visualizes the data path and MCP server integration mechanism.",
                    "spoken_audio_observation": "The native MP4 voiceover explains that this is a Python library, agent path, and MCP server integration.",
                    "background_music_observation": "Background music remains at a safe, non-intrusive level.",
                    "visual_subject": "MCP data path diagram.",
                    "spoken_subject": "Structural compression via MCP server and Python library.",
                    "audio_visual_subject_alignment": "The diagram illustrates the exact data flow spoken about in the voiceover.",
                    "text_readability": "Diagram labels and node text are clear and legible.",
                    "caption_progress_alignment": "Captions update in sync with the spoken explanation of the mechanism.",
                    "motion_observation": "A green data packet moves along the horizontal path from MCP to headroom.",
                    "issues": [],
                },
                {
                    "timestamp": "01:10",
                    "commentary": "Presents the final adopter checklist and verification path.",
                    "spoken_audio_observation": "The native MP4 voiceover frames the context optimization layer claim as something to verify on real workloads.",
                    "background_music_observation": "Background music fades out smoothly toward the end.",
                    "visual_subject": "Adopter decision cards showing good fit versus verify before shipping.",
                    "spoken_subject": "Verification of lossless compression claims.",
                    "audio_visual_subject_alignment": "Pass. Spoken verification advice matches the adopter decision cards.",
                    "text_readability": "Clear columns with distinct colors for fit and verification.",
                    "caption_progress_alignment": "Pass. Captions match the final spoken words.",
                    "motion_observation": "Decision list items stagger in with smooth vertical transitions.",
                    "issues": [],
                },
            ],
            "motion_assessment": {
                "level": "adequate",
                "commentary": "The video features smooth node animations, terminal typing effects, and sequential checklist highlights that keep the presentation engaging.",
            },
            "audio_track_assessment": {
                "voiceover": "The voiceover is clear, natural, and follows the same headroom explanation shown by the visuals.",
                "background_music": "The background music is subtle and does not compete with the speech.",
                "mix": "The audio mix is well-balanced with no clipping, dropouts, or distortion.",
                "issues": [],
            },
            "subject_alignment": {
                "spoken_subject": "Introduction and evaluation of the headroom context compression library.",
                "visual_subject": "Terminal outputs, architecture diagrams, and verification checklists for headroom.",
                "matches": True,
                "mismatches": [],
                "evidence": "The 00:00 terminal, 00:35 MCP diagram, and 01:10 checklist all stay on headroom mechanism and verification.",
            },
            "rubric_scores": {
                "hook_clarity": 7,
                "scene_pacing": 7,
                "visual_hierarchy": 7,
                "central_animation_richness": 7,
                "topic_visual_fit": 7,
                "caption_safe_area": 7,
                "audio_visual_sync": 7,
                "evidence_guardrail": 7,
            },
            "narrative_structure": {
                "opening_hook": "The opening uses a terminal simulation to show the context window pressure problem.",
                "middle_delivery": "The middle builds the MCP pipeline diagram so the mechanism is visible instead of only narrated.",
                "ending_payoff": "The ending uses a checklist to leave a practical verification path for real workloads.",
                "pacing_issue": "none",
            },
            "animation_diagnostics": {
                "main_motion_layers": [
                    "Terminal text lines rendering sequentially",
                    "Data packet moving along the MCP pipeline path",
                    "Checklist items highlighting in sync with the voiceover",
                ],
                "topic_specific_objects": [
                    "Terminal output block",
                    "MCP pipeline diagram",
                    "Adopter decision checklist",
                ],
                "weak_motion": [],
                "recommended_repair": "",
            },
            "composition_director": {
                "primary_focal_target": "The central diagram and terminal blocks that illustrate the compression process.",
                "competing_visual_systems": [
                    "Left sidebar with project metadata",
                    "Central visual canvas",
                    "Bottom captions",
                ],
                "simultaneous_motion_system_count": 2,
                "clutter_level": "low",
                "hierarchy_issue": "none",
                "overload_issue": "none",
                "director_verdict": "pass",
            },
        }
        self.assertEqual(audit_contract_errors(headroom_native_review_pass, expected_orientation="horizontal"), [])

        node_pass = {
            **detailed_pass,
            "narrative_structure": {
                **detailed_pass["narrative_structure"],
                "pacing_issue": "none",
            },
            "animation_diagnostics": {
                "main_motion_layers": [
                    "Node pulsing and scaling",
                    "Staggered connection line animations",
                    "Active state highlights",
                ],
                "topic_specific_objects": [
                    "Interactive node diagram",
                    "Benchmark data cards",
                ],
                "weak_motion": [],
                "recommended_repair": "",
            },
        }
        self.assertEqual(audit_contract_errors(node_pass), [])
        qwen_loop_pass = {
            **detailed_pass,
            "narrative_structure": {
                **detailed_pass["narrative_structure"],
                "pacing_issue": "none, with evidence",
            },
            "animation_diagnostics": {
                "main_motion_layers": [
                    "rotating dashed loop circles",
                    "pulsing node highlights",
                    "staggered state node reveals",
                ],
                "topic_specific_objects": [
                    "VLM loop diagram",
                    "GUI/Code/Tool/Verify state cards",
                    "benchmark score indicators",
                ],
                "weak_motion": [
                    "caption text fade-in",
                    "progress bar movement",
                ],
                "recommended_repair": "",
            },
        }
        self.assertEqual(
            audit_contract_errors(
                qwen_loop_pass,
                public_subject_text="The public subject is a Qwen VLM GUI/code/tool loop with benchmark evaluation.",
            ),
            [],
        )
        bridge_preview_pass = {
            **detailed_pass,
            "timeline_reviews": [
                {
                    **detailed_pass["timeline_reviews"][0],
                    "motion_observation": "The central VLM diagram nodes pulse and orbit while packet labels move around the loop.",
                },
                {
                    **detailed_pass["timeline_reviews"][1],
                    "motion_observation": "The terminal cursor types commands and code lines highlight sequentially in the central panel.",
                },
                {
                    **detailed_pass["timeline_reviews"][2],
                    "motion_observation": "Benchmark table rows fade in with a staggered animation and active row emphasis.",
                },
            ],
            "motion_assessment": {
                "level": "adequate",
                "commentary": "Central motion is visible through VLM node pulsing, terminal typing, and table row staggering.",
            },
            "animation_diagnostics": {
                "main_motion_layers": [
                    "Staggered text reveals",
                    "Dynamic diagram node highlighting",
                    "Terminal cursor typing commands in the central panel",
                ],
                "topic_specific_objects": [
                    "VLM loop architecture diagram",
                    "Terminal benchmark table",
                ],
                "weak_motion": ["Static background gradient"],
                "recommended_repair": "",
            },
        }
        self.assertEqual(
            audit_contract_errors(
                bridge_preview_pass,
                public_subject_text="The public subject is a VLM bridge preview with terminal commands and benchmark tables.",
            ),
            [],
        )
        self.assertEqual(
            audit_contract_errors(
                {
                    "task": "Audit this rendered searchpo video before publishing.",
                    "video_first_rule": "Judge the native video input.",
                    "required_output": node_pass,
                }
            ),
            [],
        )

        shorthand_pass = {
            **detailed_pass,
            "timeline_reviews": [
                {**review, "caption_progress_alignment": "pass", "issues": []}
                for review in detailed_pass["timeline_reviews"]
            ],
        }
        self.assertIn("caption/progress alignment notes", "; ".join(audit_contract_errors(shorthand_pass)))

        progress_only_pass = {
            **detailed_pass,
            "timeline_reviews": [
                {
                    **review,
                    "motion_observation": "The progress bar moves smoothly while the caption highlight advances.",
                }
                for review in detailed_pass["timeline_reviews"]
            ],
            "motion_assessment": {
                "level": "adequate",
                "commentary": "The progress bar and captions move throughout the video.",
            },
        }
        joined = "; ".join(audit_contract_errors(progress_only_pass))
        self.assertIn("caption/progress/fade-only", joined)
        self.assertIn("caption/progress motion", joined)

        overcrowded_dashboard_pass = {
            **detailed_pass,
            "checks": {
                **detailed_pass["checks"],
                "composition_not_overcrowded": True,
                "single_primary_focal_action": True,
                "no_competing_overlays": True,
                "topic_visual_not_generic_dashboard": True,
            },
            "rubric_scores": {
                **detailed_pass["rubric_scores"],
                "visual_hierarchy": 9,
                "central_animation_richness": 9,
                "topic_visual_fit": 9,
            },
            "animation_diagnostics": {
                "main_motion_layers": [
                    "Central diagram nodes pulsing and scaling dynamically",
                    "Sidebar chapters and metrics updating with smooth transitions",
                    "Bottom progress bar moving continuously across scenes",
                ],
                "topic_specific_objects": [
                    "SOURCE FLOW node hub",
                    "MECH VERIFY RISK status cards",
                ],
                "weak_motion": [],
                "recommended_repair": "",
            },
            "composition_director": {
                "primary_focal_target": "The generic SOURCE FLOW hub and surrounding status dashboard.",
                "competing_visual_systems": [
                    "large title block",
                    "central SOURCE FLOW diagram",
                    "right-side metric bars",
                    "bottom state cards",
                    "chapter bridge panel",
                ],
                "simultaneous_motion_system_count": 5,
                "clutter_level": "overloaded",
                "hierarchy_issue": "The central hub, side metrics, bottom cards, and chapter bridge are competing for attention.",
                "overload_issue": "Too many animated systems are visible together, making the composition overcrowded.",
                "director_verdict": "fail",
            },
        }
        dashboard_joined = "; ".join(audit_contract_errors(overcrowded_dashboard_pass))
        self.assertIn("non-counting motion", dashboard_joined)
        self.assertIn("too many simultaneous motion systems", dashboard_joined)
        self.assertIn("clutter_level", dashboard_joined)

        bedrock_gui_false_positive = {
            **detailed_pass,
            "timeline_reviews": [
                {
                    **detailed_pass["timeline_reviews"][0],
                    "commentary": "The opening shows a GUI plugin tab and a central VLM loop with screen-code-tool state nodes.",
                    "spoken_audio_observation": "The native MP4 voiceover says OpenAI models and Codex are generally available on Amazon Bedrock.",
                    "visual_subject": "The central visual subject is a GUI/VLM screen-code-tool agent loop.",
                    "spoken_subject": "The spoken subject is OpenAI models and Codex on Amazon Bedrock for enterprise AWS governance.",
                    "audio_visual_subject_alignment": "The evaluator report claims the GUI loop represents the enterprise workflow.",
                    "motion_observation": "The VLM loop nodes pulse while screen-code-tool packets orbit around the GUI panel.",
                },
                {
                    **detailed_pass["timeline_reviews"][1],
                    "commentary": "The middle keeps the VLM loop and GUI state machine as the central surface.",
                    "spoken_audio_observation": "The native MP4 voiceover discusses IAM, VPC, CloudTrail, and Bedrock inference controls.",
                    "visual_subject": "The central visual subject remains a reusable GUI/VLM loop diagram.",
                    "spoken_subject": "The spoken subject is AWS Bedrock governance for OpenAI and Codex access.",
                    "audio_visual_subject_alignment": "The evaluator report says the GUI loop can stand for Bedrock governance.",
                    "motion_observation": "GUI and VLM nodes highlight in sequence while generic tool packets move.",
                },
                {
                    **detailed_pass["timeline_reviews"][2],
                    "commentary": "The ending still shows screen/code/tool states instead of AWS access or gateway evaluation.",
                    "spoken_audio_observation": "The native MP4 voiceover closes with Native AWS Access and LLM Gateway evaluation criteria.",
                    "visual_subject": "The central visual subject is a screen/code/tool agent loop.",
                    "spoken_subject": "The spoken subject is Native AWS Access, LLM Gateway, and enterprise validation metrics.",
                    "audio_visual_subject_alignment": "The evaluator report claims the generic loop is compatible with the spoken evaluation path.",
                    "motion_observation": "Screen-code-tool nodes pulse and orbit near the central VLM hub.",
                },
            ],
            "subject_alignment": {
                "spoken_subject": "The voiceover is about OpenAI models and Codex becoming available on Amazon Bedrock with IAM, VPC, CloudTrail, Native AWS Access, and LLM Gateway evaluation paths.",
                "visual_subject": "The central visuals show a GUI/VLM screen-code-tool agent loop with reusable interface and tool-use nodes.",
                "matches": True,
                "mismatches": [],
                "evidence": "The evaluator report claims the generic GUI/VLM loop can represent the enterprise Bedrock access workflow at 00:01, 00:30, and 01:00.",
            },
            "animation_diagnostics": {
                "main_motion_layers": ["VLM node pulsing", "screen-code-tool packet orbit", "GUI tab state transitions"],
                "topic_specific_objects": ["VLM loop architecture diagram", "GUI screen-code-tool state cards"],
                "weak_motion": ["bottom progress bar"],
                "recommended_repair": "",
            },
        }
        bedrock_errors = audit_contract_errors(
            bedrock_gui_false_positive,
            public_subject_text=(
                "OpenAI models and Codex on Amazon Bedrock; AWS governance; IAM; VPC; CloudTrail; "
                "Native AWS Access; LLM Gateway; enterprise model evaluation."
            ),
        )
        self.assertIn("off-boundary visual template markers", "; ".join(bedrock_errors))
        self.assertEqual(route_contract_errors(bedrock_errors), "content")

        explicit_subject_mismatch = {
            **detailed_pass,
            "checks": {**detailed_pass["checks"], "voiceover_visual_same_subject": False},
            "subject_alignment": {
                **detailed_pass["subject_alignment"],
                "matches": False,
                "mismatches": ["The voiceover is about Bedrock, while the central visual is a GUI/VLM loop."],
            },
        }
        explicit_errors = audit_contract_errors(explicit_subject_mismatch)
        self.assertIn("voiceover_visual_same_subject", "; ".join(explicit_errors))
        self.assertEqual(route_contract_errors(explicit_errors), "content")

        old_style_pass = {
            "verdict": "pass",
            "checks": {"video_readable": True, "publish_ready": True},
            "timeline_reviews": [
                {
                    "timestamp": "00:30",
                    "commentary": "The video highlights a metric while a progress bar updates.",
                    "text_readability": "pass",
                    "caption_progress_alignment": "pass",
                    "motion_observation": "The progress bar moves smoothly across the bottom of the screen.",
                },
                {
                    "timestamp": "01:00",
                    "commentary": "The video explains a failure mode using a static-looking card.",
                    "text_readability": "pass",
                    "caption_progress_alignment": "pass",
                    "motion_observation": "The active card transitions smoothly to a section.",
                },
                {
                    "timestamp": "01:25",
                    "commentary": "The video concludes with a reference and final card.",
                    "text_readability": "pass",
                    "caption_progress_alignment": "pass",
                    "motion_observation": "The final card fades out cleanly at the end.",
                },
            ],
            "motion_assessment": {
                "level": "adequate",
                "commentary": "The animation uses smooth card transitions, progress bar updates, and text highlights.",
            },
        }
        old_joined = "; ".join(audit_contract_errors(old_style_pass))
        self.assertIn("douyin_vertical_format", old_joined)
        self.assertIn("text readability evidence", old_joined)
        self.assertIn("overweights caption/progress", old_joined)

    def test_visual_audit_prompt_does_not_embed_self_certifying_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            write_json(run_dir / "selected_candidate.json", {"title": "Demo Tool", "canonical_url": "https://example.com/demo"})
            write_json(
                run_dir / "render_payload.json",
                {
                    "displayTitle": "Demo Tool",
                    "summary": "SELF_CERTIFYING_RENDER_SUMMARY_SHOULD_NOT_LEAK",
                    "cards": [{"label": "证据", "value": "官方来源", "detail": "先看 demo"}],
                    "videoProfile": {"motion": "calm"},
                },
            )
            write_json(
                run_dir / "deepseek_polish.json",
                {
                    "polished_title": "Demo Tool",
                    "voiceover_text": "SELF_CERTIFYING_PROVIDER_COPY_SHOULD_NOT_LEAK",
                    "douyin_desc": "provider says video is good",
                },
            )
            write_json(
                run_dir / "evidence_bundle.json",
                {"evidence_summary": {"source_facts": ["official fact"], "constructive_angles": ["angle"]}},
            )
            write_json(run_dir / "cross_check_review.json", {"source_facts": ["review fact"], "constructive_angles": ["review angle"]})
            post_dir = run_dir / "post"
            post_dir.mkdir()
            write_json(post_dir / "claims_ledger.json", {"claims": [{"claim": "SELF_CERTIFYING_CLAIM_SHOULD_NOT_LEAK"}]})
            video_path = run_dir / "video.mp4"
            video_path.write_bytes(b"video")

            prompt = build_prompt(run_dir, video_path)
            prompt_json = json.loads(prompt)

            self.assertIn("public_context", prompt_json)
            self.assertNotIn("render_payload", prompt_json)
            self.assertNotIn("deepseek_polish", prompt_json)
            self.assertNotIn("claims_ledger", prompt_json)
            self.assertNotIn("SELF_CERTIFYING_RENDER_SUMMARY_SHOULD_NOT_LEAK", prompt)
            self.assertNotIn("SELF_CERTIFYING_PROVIDER_COPY_SHOULD_NOT_LEAK", prompt)
            self.assertNotIn("SELF_CERTIFYING_CLAIM_SHOULD_NOT_LEAK", prompt)

    def test_visual_audit_routes_native_video_by_api_mode(self) -> None:
        self.assertEqual(choose_video_input_mode(Path("."), "auto", "developer", True), "file_api")
        self.assertEqual(choose_video_input_mode(Path("."), "auto", "vertex_express", True, True), "agent_platform")
        self.assertEqual(choose_video_input_mode(Path("."), "auto", "vertex_express", False, True), "agent_platform")
        self.assertEqual(choose_video_input_mode(Path("."), "agent_platform", "vertex_express", False, True), "agent_platform")

    def test_failed_video_attempt_does_not_publish_or_bind_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            old_render = video_loop.render_attempt
            old_audit = video_loop.audit_attempt

            def fake_render(run_dir_arg: Path, attempt_dir: Path, attempt: int, render_mode: str, publish_mode: str = "contract-check") -> dict[str, Any]:
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

    def test_lambda_site_deploys_after_prepare_assets_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            attempt_dir = run_dir / "optimization" / "video" / "attempt-01"
            run_dir.mkdir()
            attempt_dir.mkdir(parents=True)
            calls: list[str] = []
            old_run_command = video_loop.run_command
            old_record_stage = video_loop.record_stage

            def fake_run_command(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 900) -> dict[str, Any]:
                calls.append(" ".join(cmd))
                if "render/prepare_remotion_input.py" in cmd:
                    (run_dir / "remotion_input_props.json").write_text("{}", encoding="utf-8")
                    write_json(run_dir / "render_input_manifest.json", {"props": str(run_dir / "remotion_input_props.json")})
                elif cmd == ["bash", "scripts/lambda_render.sh", "site"]:
                    self.assertTrue((run_dir / "remotion_input_props.json").is_file())
                    self.assertEqual((env or {}).get("SEARCHPO_RUN_DIR"), str(run_dir))
                elif cmd == ["bash", "scripts/lambda_render.sh", "render"]:
                    output = video_loop.ROOT / str((env or {})["SEARCHPO_LAMBDA_RENDER_OUTPUT"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"video")
                elif cmd == ["bash", "scripts/lambda_render.sh", "still"]:
                    output = video_loop.ROOT / str((env or {})["SEARCHPO_LAMBDA_COVER_OUTPUT"])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"cover")
                return {"command": " ".join(cmd), "returncode": 0}

            try:
                video_loop.run_command = fake_run_command
                video_loop.record_stage = lambda *args, **kwargs: None
                info = video_loop.render_attempt(run_dir, attempt_dir, 1, "lambda")
            finally:
                video_loop.run_command = old_run_command
                video_loop.record_stage = old_record_stage

            self.assertTrue(Path(info["video_path"]).is_file())
            self.assertTrue(Path(info["preview_manifest"]).is_file())
            self.assertIn("/out/previews/", info["raw_preview_video_path"])
            self.assertIn("/attempt-01/lambda/", info["raw_preview_video_path"])
            self.assertLess(
                calls.index(f"{sys.executable} render/prepare_remotion_input.py {run_dir}"),
                calls.index("bash scripts/lambda_render.sh site"),
            )
            self.assertLess(
                calls.index("bash scripts/lambda_render.sh site"),
                calls.index("bash scripts/lambda_render.sh render"),
            )

    def test_lambda_render_failure_does_not_local_fallback_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            attempt_dir = run_dir / "optimization" / "video" / "attempt-01"
            run_dir.mkdir()
            attempt_dir.mkdir(parents=True)
            calls: list[str] = []
            old_run_command = video_loop.run_command
            old_record_stage = video_loop.record_stage

            def fake_run_command(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 900) -> dict[str, Any]:
                calls.append(" ".join(cmd))
                if "render/prepare_remotion_input.py" in cmd:
                    (run_dir / "remotion_input_props.json").write_text("{}", encoding="utf-8")
                    write_json(run_dir / "render_input_manifest.json", {"props": str(run_dir / "remotion_input_props.json")})
                    return {"command": " ".join(cmd), "returncode": 0}
                if cmd == ["bash", "scripts/lambda_render.sh", "site"]:
                    return {"command": " ".join(cmd), "returncode": 0}
                if cmd == ["bash", "scripts/lambda_render.sh", "render"]:
                    raise RuntimeError("lambda render failed")
                if cmd == ["bash", "scripts/remotion_render.sh", "local"]:
                    raise AssertionError("local fallback should not run")
                return {"command": " ".join(cmd), "returncode": 0}

            try:
                video_loop.run_command = fake_run_command
                video_loop.record_stage = lambda *args, **kwargs: None
                with self.assertRaisesRegex(RuntimeError, "lambda render failed"):
                    video_loop.render_attempt(run_dir, attempt_dir, 1, "lambda")
            finally:
                video_loop.run_command = old_run_command
                video_loop.record_stage = old_record_stage

        self.assertIn("bash scripts/lambda_render.sh render", calls)
        self.assertNotIn("bash scripts/remotion_render.sh local", calls)

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

            def fake_render(run_dir_arg: Path, attempt_dir: Path, attempt: int, render_mode: str, publish_mode: str = "contract-check") -> dict[str, Any]:
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
