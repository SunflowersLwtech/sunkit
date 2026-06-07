#!/usr/bin/env python3
"""Score polished content quality via Gemini for searchpo quality gate."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from agent_harness.policy import policy_get
from agent_harness.content_guard import dismissive_verification_hits, public_content_payload
from agent_harness.evidence import strong_research_review_errors
from agent_harness.service_artifacts import RENDER_TO_PLANNING_TYPE, bounded_text
from env_utils import first_env, env_value
from gemini_api import default_gemini_mode, generate_content_url

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def latest_run_dir() -> Path:
    if not LATEST_RUN_PATH.exists():
        raise SystemExit("runtime/latest_run.txt is missing")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip()).resolve()


def score_content(
    api_key: str,
    model: str,
    polish: dict[str, Any],
    candidate: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    timeout: float,
    env_file: Path,
    topic_brief: dict[str, Any] | None = None,
    fact_bank: dict[str, Any] | None = None,
    scene_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = generate_content_url(model, api_key, env_file)
    target_overall = float(policy_get("content_optimization.target_overall", 8.0))
    min_dimension = float(policy_get("content_optimization.min_dimension", 7.0))
    prompt = json.dumps({
        "task": "Score this short-video content package for Douyin quality. Return JSON only.",
        "score_calibration": {
            "6": "adequate but visibly weak for a publishable short video; one important dimension still needs work",
            "7": "solid baseline; acceptable structure and source safety, but not yet a strong publishable package",
            "8": "strong publishable quality for this dimension: concrete, source-grounded, mobile-readable, and clearly tailored to the topic",
            "9": "exceptional; unusually sharp, memorable, and polished while staying inside evidence boundaries",
            "10": "rare; near-perfect for the specific dimension",
            "important": [
                "Do not reserve 8+ only for hype, virality certainty, or unsupported certainty.",
                "Careful caveats and source boundaries can score 8 or 9 when they improve trust instead of weakening the hook.",
                "A technical explainer can earn 8+ when it has a concrete opening conflict, a clear mechanism, an actionable judgment framework, and topic-specific visuals.",
                "Score each dimension independently; do not cap every dimension at 7 merely because the subject is technical or evidence-bounded."
            ]
        },
        "scoring_dimensions": {
            "hook_strength": "1-10: Does the title/opening grab attention in first 2 seconds?",
            "retention_structure": "1-10: Does it quickly move from problem to mechanism, architecture position, failure boundary, and judgment framework so viewers have a reason to keep watching?",
            "information_density": "1-10: Is the voiceover packed with useful info, no filler?",
            "emotional_tension": "1-10: Does it create curiosity, surprise, or urgency?",
            "claim_safety": "1-10: Are claims properly bounded? No hype without evidence?",
            "douyin_algorithm_fit": "1-10: Are title, captions, description, and tags content-relevant without keyword stuffing or folklore about secret thresholds?",
            "constructive_interaction_fit": "1-10: Does the copy invite useful comments, saves, or follow-up evaluation without engagement bait?",
            "recommendation_eligibility_safety": "1-10: Does it avoid spam, duplicate-content framing, fake engagement, automation-growth tactics, and unsupported shadowban/限流 claims?",
            "constructive_interpretation": "1-10: Does it provide a useful, source-grounded explanation instead of generic hype?",
            "format_fit": "1-10: Does the chosen duration, orientation, storyboard motion, and animation style fit the subject instead of forcing every topic into the same short vertical template?",
            "custom_visual_fit": "1-10: Does agent_visual define a topic-specific Remotion visual instead of generic reusable cards?",
            "open_source_explainer_value": "1-10: For GitHub/open-source topics, does it explain repo value through problem, mechanism/architecture, usage or demo path, tradeoff/risk, failure boundary, and adoption judgment framework?",
        },
        "required_output": {
            "scores": {
                "hook_strength": "int",
                "retention_structure": "int",
                "information_density": "int",
                "emotional_tension": "int",
                "claim_safety": "int",
                "douyin_algorithm_fit": "int",
                "constructive_interaction_fit": "int",
                "recommendation_eligibility_safety": "int",
                "constructive_interpretation": "int",
                "format_fit": "int",
                "custom_visual_fit": "int",
                "open_source_explainer_value": "int",
            },
            "overall": "float weighted average; constructive interpretation, information density, format_fit, custom_visual_fit, and open_source_explainer_value must materially affect it",
            "suggestions": ["1-3 specific improvement suggestions"],
            "verdict": f"pass only if overall >= {target_overall} and every dimension >= {min_dimension}; otherwise improve",
        },
        "content": {
            "polished_title": polish.get("polished_title"),
            "voiceover_text": polish.get("voiceover_text"),
            "douyin_title": polish.get("douyin_title"),
            "douyin_desc": polish.get("douyin_desc"),
            "tags": polish.get("tags"),
            "cards": polish.get("cards"),
            "storyboard": polish.get("storyboard"),
            "premium_director_spec": polish.get("premium_director_spec") or polish.get("visual_recipe"),
            "agent_visual": {
                "enabled": (polish.get("agent_visual") or {}).get("enabled"),
                "render_mode": (polish.get("agent_visual") or {}).get("render_mode"),
                "description": (polish.get("agent_visual") or {}).get("description"),
                "component_code_preview": str(
                    (polish.get("agent_visual") or {}).get("component_code")
                    or (polish.get("agent_visual") or {}).get("module_code")
                    or ""
                )[:1600],
                "css_preview": str((polish.get("agent_visual") or {}).get("css") or "")[:1000],
            },
            "video_profile": polish.get("video_profile") or polish.get("videoProfile"),
            "scene_plan": scene_plan or {},
        },
        "candidate_context": {
            "title": candidate.get("title"),
            "source_ids": candidate.get("source_ids"),
            "candidate_score": candidate.get("candidate_score"),
        },
        "service_artifacts": {
            "topic_brief": topic_brief or {},
            "fact_bank": fact_bank or {},
            "scene_plan": scene_plan or {},
        },
        "evidence_bundle": {
            "source_kind": evidence_bundle.get("source_kind"),
            "source_facts": (evidence_bundle.get("evidence_summary") or {}).get("source_facts") or [],
            "constructive_angles": (evidence_bundle.get("evidence_summary") or {}).get("constructive_angles") or [],
            "combined_excerpt": (evidence_bundle.get("evidence_summary") or {}).get("combined_excerpt") or "",
            "research_brief": (evidence_bundle.get("evidence_summary") or {}).get("research_brief") or {},
            "fact_bank_risk_notes": (evidence_bundle.get("evidence_summary") or {}).get("fact_bank_risk_notes") or [],
        },
        "cross_check_review": cross_check_review,
        "fail_if": [
            "The content could have been written without reading the source.",
            "It makes project capability, ranking, benchmark, or adoption claims not supported by evidence_bundle.",
            "It does not explain the problem/mechanism/architecture fit/failure boundary/judgment framework for an open-source project or tool.",
            "For a GitHub/open-source topic, it gives only a trend or README summary and does not explain why a developer should care, how the project works, what could go wrong, and how to judge whether it fits.",
            "The video_profile forces a 12-second vertical radar treatment even though the source depth requires a longer explainer or a different presentation format.",
            "agent_visual is missing, disabled, generic, or not clearly tailored to this topic.",
            "premium_director_spec is missing, generic, card-only, or not clearly tailored to this topic.",
            "It tells viewers to verify, wait, observe, try it themselves, or otherwise shifts the knowledge burden to the viewer instead of teaching a mechanism and judgment framework.",
            "It presents private Douyin thresholds, fixed traffic-pool sizes, completion-rate cutoffs, or a definitive shadowban/限流 diagnosis as fact without official platform-rule evidence.",
            "It asks viewers for fake likes, follows, shares, comment spam, or other engagement bait.",
            "It contains raw URLs, GitHub links, website links, or source paths in public copy.",
            "It asks viewers to try, download, install, use, open, visit, or go to a third-party tool, site, repository, app, plugin, or framework.",
            "The selected subject is platform automation, account automation, multi-platform auto-posting, batch upload, auto-login, test-account, or platform-risk-control tooling.",
        ],
    }, ensure_ascii=False)

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
            if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(3.0 * (2 ** attempt))
                last_exc = RuntimeError(f"Gemini scorer HTTP {exc.code}: {detail}")
                continue
            raise RuntimeError(f"Gemini scorer HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                time.sleep(3.0 * (2 ** attempt))
                last_exc = RuntimeError(f"Gemini scorer network: {exc}")
                continue
            raise RuntimeError(f"Gemini scorer network: {exc}") from exc
    else:
        raise last_exc or RuntimeError("Gemini scorer exhausted retries")

    text = ""
    for c in payload.get("candidates") or []:
        for part in ((c.get("content") or {}).get("parts") or []):
            text += part.get("text") or ""
    if not text:
        raise RuntimeError("Gemini scorer returned no text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def candidate_entity_terms(candidate: dict[str, Any]) -> list[str]:
    raw_values = [
        str(candidate.get("title") or ""),
        str(candidate.get("entity_key") or ""),
        str(candidate.get("canonical_url") or "").rstrip("/").rsplit("/", 1)[-1],
    ]
    terms: list[str] = []
    for raw in raw_values:
        for part in re.split(r"[\s/_:.-]+", raw):
            cleaned = part.strip()
            if len(cleaned) >= 4 and cleaned.lower() not in {"github", "repo", "http", "https"}:
                terms.append(cleaned)
    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.lower()
        if key not in seen:
            unique.append(term)
            seen.add(key)
    return unique[:6]


def is_open_source_candidate(candidate: dict[str, Any]) -> bool:
    host = urlparse(str(candidate.get("canonical_url") or "")).netloc.lower()
    signals = candidate.get("signals") if isinstance(candidate.get("signals"), dict) else {}
    source_ids = " ".join(str(item) for item in candidate.get("source_ids") or []).lower()
    return "github.com" in host or bool(signals.get("has_code_signal")) or "github" in source_ids


def content_value_beats(polish: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    combined = " ".join(
        [
            str(polish.get("polished_title") or ""),
            str(polish.get("voiceover_text") or ""),
            json.dumps(polish.get("cards") or [], ensure_ascii=False),
            json.dumps(polish.get("storyboard") or {}, ensure_ascii=False),
        ]
    )
    beat_terms = {
        "problem": ["问题", "痛点", "为什么", "开发者", "用户", "成本", "效率"],
        "mechanism": ["机制", "架构", "原理", "流程", "怎么", "模块", "接口", "抽象", "调用链"],
        "usage_or_demo": ["demo", "示例", "quick start", "快速开始", "运行", "安装", "使用", "输入输出"],
        "tradeoff": ["取舍", "边界", "风险", "限制", "不适合", "代价", "坑"],
        "judgment_framework": ["判断", "框架", "适用", "失败边界", "源码", "README", "测试", "CI", "benchmark", "检查"],
    }
    found = {
        beat: any(term.lower() in combined.lower() for term in terms)
        for beat, terms in beat_terms.items()
    }
    cn_chars = len(re.findall(r"[一-鿿]", str(polish.get("voiceover_text") or "")))
    video_profile = polish.get("video_profile") if isinstance(polish.get("video_profile"), dict) else {}
    try:
        duration_seconds = int(video_profile.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        duration_seconds = 0
    return {
        "open_source_candidate": is_open_source_candidate(candidate),
        "found_beats": found,
        "beat_count": sum(1 for ok in found.values() if ok),
        "voiceover_chinese_chars": cn_chars,
        "video_duration_seconds": duration_seconds,
    }


def deterministic_content_metrics(polish: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    value_beats = content_value_beats(polish, candidate)
    duration_seconds = int(value_beats.get("video_duration_seconds") or 0)
    voiceover_chars = int(value_beats.get("voiceover_chinese_chars") or 0)
    chars_per_second = round(voiceover_chars / duration_seconds, 2) if duration_seconds > 0 else 0.0
    beat_count = int(value_beats.get("beat_count") or 0)
    density_score = min(10.0, round((beat_count * 1.6) + min(chars_per_second, 5.0) * 0.8, 2))
    dismissive_hits = dismissive_verification_hits(public_content_payload(polish))
    return {
        "knowledge_density": {
            "voiceover_chinese_chars": voiceover_chars,
            "video_duration_seconds": duration_seconds,
            "chars_per_second": chars_per_second,
            "beat_count": beat_count,
            "score": density_score,
            "required_beats": ["problem", "mechanism", "usage_or_demo", "tradeoff", "judgment_framework"],
            "found_beats": value_beats.get("found_beats") or {},
        },
        "dismissive_phrase_penalty": {
            "hit_count": len(dismissive_hits),
            "hits": dismissive_hits,
            "penalty": 10 if dismissive_hits else 0,
        },
    }


def deterministic_blocking_checks(
    polish: dict[str, Any],
    candidate: dict[str, Any],
    evidence_bundle: dict[str, Any] | None = None,
    cross_check_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = str(polish.get("polished_title") or polish.get("douyin_title") or "")
    voiceover = str(polish.get("voiceover_text") or "")
    combined = f"{title} {voiceover}".lower()
    terms = candidate_entity_terms(candidate)
    candidate_referenced = not terms or any(term.lower() in combined for term in terms)
    generic_hook_patterns = [
        r"^最近\s*(arxiv|有一篇|出现一篇|一篇论文)",
        r"^今天\s*我们\s*(来|聊)",
        r"^这是一篇",
    ]
    opening = re.split(r"[。！？!?\n]", voiceover.strip(), maxsplit=1)[0]
    hook_specific = not any(re.search(pattern, opening, re.I) for pattern in generic_hook_patterns)
    blockers: list[str] = []
    value_beats = content_value_beats(polish, candidate)
    evidence_bundle = evidence_bundle or {}
    cross_check_review = cross_check_review or {}
    if not candidate_referenced:
        blockers.append(f"voiceover/title does not reference selected candidate terms: {terms}")
    if not hook_specific:
        blockers.append(f"opening hook is too generic for short video: {opening}")
    if not evidence_bundle.get("sources"):
        blockers.append("evidence_bundle.json is missing fetched source details")
    strong_research_errors = strong_research_review_errors(cross_check_review)
    if strong_research_errors:
        blockers.append("strong research review did not pass: " + "; ".join(strong_research_errors))
    if value_beats["open_source_candidate"]:
        if value_beats["voiceover_chinese_chars"] < 180:
            blockers.append("open-source explainer voiceover is too short to deliver useful repo analysis")
        if value_beats["beat_count"] < 4:
            blockers.append(
                "open-source explainer is missing core value beats: problem, mechanism, usage/demo, tradeoff, judgment framework"
            )
    dismissive_hits = dismissive_verification_hits(public_content_payload(polish))
    if dismissive_hits:
        blockers.append(f"public content contains banned dismissive verification phrasing: {dismissive_hits}")
    deterministic_metrics = deterministic_content_metrics(polish, candidate)
    return {
        "candidate_terms": terms,
        "candidate_referenced": candidate_referenced,
        "hook_specific": hook_specific,
        "evidence_sources_present": bool(evidence_bundle.get("sources")),
        "cross_check_status": cross_check_review.get("status") or "missing",
        "content_value_beats": value_beats,
        "knowledge_density": deterministic_metrics["knowledge_density"],
        "dismissive_phrase_penalty": deterministic_metrics["dismissive_phrase_penalty"],
        "dismissive_verification_hits": dismissive_hits,
        "blocking_issues": blockers,
    }


def dimension_scores(result: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    raw_scores = result.get("scores") if isinstance(result.get("scores"), dict) else {}
    for key, value in raw_scores.items():
        try:
            scores[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return scores


def scene_plan_from_polish(polish: dict[str, Any]) -> dict[str, Any]:
    scenes = []
    storyboard = polish.get("storyboard") if isinstance(polish.get("storyboard"), dict) else {}
    for index, scene in enumerate(storyboard.get("scenes") or [], start=1):
        if not isinstance(scene, dict):
            continue
        props = scene.get("props") if isinstance(scene.get("props"), dict) else {}
        text_values = []
        for value in props.values():
            if isinstance(value, list):
                text_values.extend(str(item) for item in value if str(item).strip())
            elif str(value or "").strip():
                text_values.append(str(value))
        render_type = str(scene.get("type") or "card")
        scenes.append(
            {
                "id": f"s{index}",
                "planning_type": RENDER_TO_PLANNING_TYPE.get(render_type, "summary"),
                "render_type": render_type,
                "on_screen_text": {
                    "headline": bounded_text(text_values[0] if text_values else render_type, 80),
                    "body": bounded_text(" ".join(text_values[1:]), 180),
                },
            }
        )
    return {"schema_version": 1, "scenes": scenes}


def score_target_report(result: dict[str, Any], blocking_checks: dict[str, Any]) -> dict[str, Any]:
    target_overall = float(policy_get("content_optimization.target_overall", 8.0))
    min_dimension = float(policy_get("content_optimization.min_dimension", 7.0))
    scores = dimension_scores(result)
    overall = float(result.get("overall") or 0)
    failed_dimensions = {
        key: value
        for key, value in sorted(scores.items())
        if value < min_dimension
    }
    blocking_issues = blocking_checks.get("blocking_issues") or []
    target_met = not blocking_issues and overall >= target_overall and not failed_dimensions
    eligible_for_revision = not blocking_issues and not target_met
    suggestions = [str(item) for item in (result.get("suggestions") or []) if str(item).strip()]
    focus = [
        str(item)
        for item in policy_get("content_optimization.revision_focus", [])
        if str(item).strip()
    ]
    revision_brief = {
        "target_overall": target_overall,
        "min_dimension": min_dimension,
        "current_overall": overall,
        "failed_dimensions": failed_dimensions,
        "suggestions": suggestions,
        "focus": focus,
        "instruction": (
            "Revise the full public content package until it reaches the target, "
            "without adding claims beyond evidence_bundle or weakening caveats."
        ),
    }
    return {
        "target_overall": target_overall,
        "min_dimension": min_dimension,
        "failed_dimensions": failed_dimensions,
        "target_met": target_met,
        "eligible_for_revision": eligible_for_revision,
        "revision_brief": revision_brief,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--polish", help="Polish JSON to score. Defaults to run_dir/deepseek_polish.json.")
    parser.add_argument("--output", help="Output JSON path. Defaults to run_dir/content_score.json.")
    parser.add_argument("--attempt", type=int, default=1, help="Optimization attempt number for artifact metadata.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    env_file = Path(args.env_file).resolve()
    api_key = first_env(["GOOGLE_API_KEY", "GOOGLE_AGENT_PLATFORM_API"], env_file)
    if not api_key:
        raise SystemExit("GOOGLE_API_KEY or GOOGLE_AGENT_PLATFORM_API is required")
    model = env_value("SEARCHPO_GEMINI_SCORER_MODEL", env_file, "gemini-3.5-flash")

    polish_path = Path(args.polish).resolve() if args.polish else run_dir / "deepseek_polish.json"
    candidate_path = run_dir / "selected_candidate.json"
    evidence_path = run_dir / "evidence_bundle.json"
    cross_check_path = run_dir / "cross_check_review.json"
    if not polish_path.exists() or not candidate_path.exists() or not evidence_path.exists() or not cross_check_path.exists():
        raise SystemExit("deepseek_polish.json, selected_candidate.json, evidence_bundle.json, and cross_check_review.json required")

    polish = read_json(polish_path)
    candidate = read_json(candidate_path)
    evidence_bundle = read_json(evidence_path)
    cross_check_review = read_json(cross_check_path)
    topic_brief_path = run_dir / "topic_brief.json"
    fact_bank_path = run_dir / "fact_bank.json"
    scene_plan_path = run_dir / "scene_plan.json"
    topic_brief = read_json(topic_brief_path) if topic_brief_path.exists() else {}
    fact_bank = read_json(fact_bank_path) if fact_bank_path.exists() else {}
    scene_plan = read_json(scene_plan_path) if scene_plan_path.exists() else scene_plan_from_polish(polish)
    result = score_content(
        api_key,
        model,
        polish,
        candidate,
        evidence_bundle,
        cross_check_review,
        args.timeout,
        env_file,
        topic_brief=topic_brief,
        fact_bank=fact_bank,
        scene_plan=scene_plan,
    )
    blocking_checks = deterministic_blocking_checks(polish, candidate, evidence_bundle, cross_check_review)
    deterministic_metrics = deterministic_content_metrics(polish, candidate)
    target_report = score_target_report(result, blocking_checks)
    model_verdict = str(result.get("verdict") or "improve").lower()
    if blocking_checks["blocking_issues"] or model_verdict == "fail":
        verdict = "fail"
    elif target_report["target_met"]:
        verdict = "pass"
    else:
        verdict = "improve"

    output = {
        "schema_version": 1,
        "created_at": utc_now(),
        "provider": "gemini",
        "model": model,
        "attempt": args.attempt,
        "polish_path": str(polish_path),
        "input_files": [
            str(path)
            for path in [polish_path, candidate_path, topic_brief_path, fact_bank_path, scene_plan_path, evidence_path, cross_check_path]
            if path.exists()
        ],
        "topic_brief_present": bool(topic_brief),
        "fact_bank_present": bool(fact_bank),
        "scene_plan_scene_count": len(scene_plan.get("scenes") or []),
        "scores": result.get("scores") or {},
        "overall": result.get("overall") or 0,
        "suggestions": result.get("suggestions") or [],
        "model_verdict": model_verdict,
        "verdict": verdict,
        **deterministic_metrics,
        "blocking_checks": blocking_checks,
        **target_report,
    }
    output_path = Path(args.output).resolve() if args.output else run_dir / "content_score.json"
    write_json(output_path, output)
    print(json.dumps({"content_score": str(output_path), "overall": output["overall"], "verdict": output["verdict"]}, ensure_ascii=False, indent=2))
    return 0 if verdict != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
