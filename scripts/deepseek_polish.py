#!/usr/bin/env python3
"""Polish the selected searchpo candidate through DeepSeek and write run artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from agent_harness.policy import policy_get, policy_format, unsupported_claim_regex, unsupported_terms
from agent_harness.evidence import strong_research_review_errors
from agent_harness.agent_visual import agent_visual_text_items, require_agent_visual
from agent_harness.content_guard import (
    dismissive_verification_hits,
    public_content_payload,
    scrub_dismissive_verification_text,
)
from agent_harness.premium_director import compile_premium_agent_visual, normalize_premium_director_spec
from agent_harness.storyboard import card_scenes, storyboard_text_items, validate_storyboard
from agent_harness.video_profile import choose_video_profile, normalize_video_profile
from env_utils import env_value

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"
UNSAFE_RE = unsupported_claim_regex()
VIEWER_BURDEN_QUESTION_RE = re.compile(
    r"(?P<question>(?:你|大家|观众|评论区|会不会|要不要|该不该|怎么选|怎么判断)[^。！？!?\n]{0,140}[？?])\s*$"
)
JUDGMENT_FRAMEWORK_ENDING = "判断顺序是：先看机制是否解决真实问题，再看它放在架构哪一层，最后看失败边界和维护成本是否可承受。"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def latest_run_dir() -> Path:
    if not LATEST_RUN_PATH.exists():
        raise SystemExit("runtime/latest_run.txt is missing; run data_prep/scripts/run_pipeline.py first")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip()).resolve()


def bounded_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_list(value: Any, key: str, max_items: int) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"DeepSeek response missing non-empty `{key}` list")
    rows = [bounded_text(item, 40) for item in value[:max_items] if str(item).strip()]
    if not rows:
        raise RuntimeError(f"DeepSeek response `{key}` list has no usable values")
    return rows


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
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            unique.append(term)
    return unique[:6]


def validate_candidate_reference(candidate: dict[str, Any], polished: dict[str, Any]) -> None:
    terms = candidate_entity_terms(candidate)
    voiceover = str(polished.get("voiceover_text") or "").lower()
    if terms and not any(term.lower() in voiceover for term in terms):
        raise RuntimeError(f"DeepSeek voiceover_text must mention one of: {', '.join(terms)}")


def rendered_polish_text(polished: dict[str, Any]) -> str:
    return " ".join(
        [
            str(polished.get("polished_title") or ""),
            str(polished.get("voiceover_text") or ""),
            str(polished.get("douyin_title") or ""),
            str(polished.get("douyin_desc") or ""),
            json.dumps(polished.get("cards") or [], ensure_ascii=False),
            " ".join(storyboard_text_items(polished.get("storyboard"))),
            " ".join(agent_visual_text_items(polished.get("agent_visual") or polished.get("agentVisual"))),
        ]
    )


def unsafe_hits_for(polished: dict[str, Any]) -> list[str]:
    return sorted(set(match.group(0) for match in UNSAFE_RE.finditer(rendered_polish_text(polished))))


def dismissive_hits_for(polished: dict[str, Any]) -> list[str]:
    return dismissive_verification_hits(public_content_payload(polished))


def viewer_question_endings_for(polished: dict[str, Any]) -> list[str]:
    hits: list[str] = []
    for key in ("voiceover_text", "douyin_desc"):
        text = str(polished.get(key) or "").strip()
        match = VIEWER_BURDEN_QUESTION_RE.search(text)
        if match:
            hits.append(f"{key}:{match.group('question')}")
    return hits


def scrub_polish_payload(polished: dict[str, Any]) -> dict[str, Any]:
    cleaned = scrub_dismissive_verification_text(polished)
    if isinstance(cleaned, dict):
        def fix_provider_typos(value: Any) -> Any:
            if isinstance(value, str):
                return value.replace("关键次", "刚开始")
            if isinstance(value, list):
                return [fix_provider_typos(item) for item in value]
            if isinstance(value, dict):
                return {key: fix_provider_typos(item) for key, item in value.items()}
            return value

        cleaned = fix_provider_typos(cleaned)
        for key in ("voiceover_text", "douyin_desc"):
            text = str(cleaned.get(key) or "").strip()
            if VIEWER_BURDEN_QUESTION_RE.search(text):
                cleaned[key] = VIEWER_BURDEN_QUESTION_RE.sub(JUDGMENT_FRAMEWORK_ENDING, text).strip()
    return cleaned



def apply_premium_director_visual(
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    polished: dict[str, Any],
    video_profile: dict[str, Any] | None = None,
    *,
    reason: str = "deepseek premium director compiler",
) -> dict[str, Any]:
    spec = normalize_premium_director_spec(
        polished.get("premium_director_spec") or polished.get("visual_recipe"),
        candidate=candidate,
        content_plan=content_plan,
        polish=polished,
        video_profile=video_profile or polished.get("video_profile"),
    )
    polished["premium_director_spec"] = spec
    polished["agent_visual"] = compile_premium_agent_visual(spec, reason=reason)
    return polished


def compatibility_storyboard_from_premium(data: dict[str, Any]) -> dict[str, Any]:
    spec = data.get("premium_director_spec") if isinstance(data.get("premium_director_spec"), dict) else {}
    arc = spec.get("knowledge_arc") if isinstance(spec.get("knowledge_arc"), dict) else {}
    objects = spec.get("topic_objects") if isinstance(spec.get("topic_objects"), list) else []
    object_labels = [
        bounded_text(item.get("label"), 28)
        for item in objects
        if isinstance(item, dict) and str(item.get("label") or "").strip()
    ]
    scenes = spec.get("visual_scenes") if isinstance(spec.get("visual_scenes"), list) else []
    scene_titles = [
        bounded_text(item.get("title"), 34)
        for item in scenes
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    title = bounded_text(data.get("polished_title") or arc.get("hook") or "机制判断框架", 52)
    mechanism = bounded_text(arc.get("mechanism") or data.get("voiceover_text") or "先把机制拆清楚", 58)
    architecture = bounded_text(arc.get("architecture_position") or "再看它放在系统里的位置", 58)
    failure = bounded_text(arc.get("failure_boundary") or "最后看失败边界是否可控", 58)
    judgment = bounded_text(arc.get("judgment_framework") or "用机制、适用场景和失败边界做判断", 78)
    visual_story_scenes: list[dict[str, Any]] = []
    for visual_scene in scenes:
        if not isinstance(visual_scene, dict):
            continue
        scene_type = str(visual_scene.get("scene_type") or "")
        scene_title = bounded_text(visual_scene.get("title") or title, 56)
        objective = bounded_text(visual_scene.get("objective") or "", 90)
        beats = [
            bounded_text(item, 64)
            for item in (visual_scene.get("teaching_beats") or [])
            if str(item or "").strip()
        ][:5]
        if scene_type == "HeroProblemScene":
            visual_story_scenes.append(
                {
                    "type": "statement",
                    "props": {
                        "kicker": "开场冲突",
                        "title": scene_title or title,
                        "sub": objective or mechanism,
                    },
                }
            )
        elif scene_type in {"MechanismExplodedView", "ArchitectureFlowScene", "TimelineBuildScene"}:
            visual_story_scenes.append(
                {
                    "type": "flow",
                    "props": {
                        "kicker": "机制怎么跑",
                        "heading": scene_title or architecture,
                        "nodes": beats or object_labels or scene_titles or ["输入", "运行", "检查", "重跑"],
                        "caption": objective,
                    },
                }
            )
        elif scene_type == "CodeOrTerminalScene":
            visual_story_scenes.append(
                {
                    "type": "terminal",
                    "props": {
                        "kicker": "验收规则",
                        "title": scene_title or "CLAUDE.md 示例",
                        "prompt": "$",
                        "lines": beats
                        or [
                            "context: write standards before loop",
                            "acceptance: npm test && npm run lint",
                            "review: split PRs over 20 files",
                        ],
                    },
                }
            )
        elif scene_type in {"MetricComparisonScene", "DecisionMatrixScene"}:
            rows = beats or [mechanism, failure, judgment]
            visual_story_scenes.append(
                {
                    "type": "compare_table",
                    "props": {
                        "kicker": "取舍判断",
                        "heading": scene_title or "适用与失败边界",
                        "leftLabel": "信号",
                        "rightLabel": "怎么判断",
                        "rows": rows,
                    },
                }
            )
        elif scene_type == "KnowledgeTakeawayScene":
            visual_story_scenes.append(
                {
                    "type": "cta",
                    "props": {
                        "kicker": "判断框架",
                        "text": bounded_text(judgment, 48),
                        "footer": objective or "证据边界内",
                    },
                }
            )
        elif scene_type in {"RepoFileTreeReveal"}:
            visual_story_scenes.append(
                {
                    "type": "bullets",
                    "props": {
                        "kicker": "看哪里",
                        "heading": scene_title,
                        "items": beats or object_labels or scene_titles,
                    },
                }
            )
        if len(visual_story_scenes) >= 7:
            break
    if visual_story_scenes:
        if not any(scene.get("type") == "statement" for scene in visual_story_scenes):
            visual_story_scenes.insert(0, {"type": "statement", "props": {"title": title, "sub": mechanism}})
        if not any(scene.get("type") == "cta" for scene in visual_story_scenes):
            visual_story_scenes.append({"type": "cta", "props": {"text": judgment, "footer": "证据边界内"}})
        return validate_storyboard(
            {
                "version": 1,
                "style": {
                    "theme": "minimal",
                    "density": "rich",
                    "motion": "standard",
                    "chrome": {"topbar": False, "progress": True, "beam": False},
                },
                "scenes": visual_story_scenes[:8],
            }
        )
    storyboard = {
        "version": 1,
        "style": {
            "theme": "minimal",
            "density": "rich",
            "motion": "calm",
            "chrome": {"topbar": False, "progress": True, "beam": False},
        },
        "scenes": [
            {"type": "statement", "props": {"title": title, "sub": mechanism}},
            {
                "type": "flow",
                "props": {
                    "kicker": "机制路径",
                    "heading": architecture,
                    "nodes": (object_labels or scene_titles or ["问题", "机制", "架构", "失败边界"])[:5],
                },
            },
            {
                "type": "compare_table",
                "props": {
                    "kicker": "判断框架",
                    "heading": "适用与失败边界",
                    "leftLabel": "看什么",
                    "rightLabel": "怎么判断",
                    "rows": [
                        f"机制|{mechanism}|是否解释真实问题",
                        f"架构|{architecture}|是否放在合适位置",
                        f"边界|{failure}|失败成本是否可控",
                    ],
                },
            },
            {"type": "cta", "props": {"text": judgment, "footer": "证据边界内"}},
        ],
    }
    return validate_storyboard(storyboard)


def validate_polish(candidate: dict[str, Any], polished: dict[str, Any]) -> None:
    validate_candidate_reference(candidate, polished)
    unsafe_hits = unsafe_hits_for(polished)
    if unsafe_hits:
        raise RuntimeError(f"DeepSeek candidate contains unsupported claim terms: {unsafe_hits}")
    dismissive_hits = dismissive_hits_for(polished)
    if dismissive_hits:
        raise RuntimeError(f"DeepSeek candidate contains banned dismissive verification phrasing: {dismissive_hits}")
    viewer_question_hits = viewer_question_endings_for(polished)
    if viewer_question_hits:
        raise RuntimeError(
            "DeepSeek candidate ends by asking the viewer to decide instead of teaching a judgment framework: "
            f"{viewer_question_hits}"
        )


def parse_json_object(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_polish_payload(data: dict[str, Any]) -> dict[str, Any]:
    required = policy_get("deepseek.required_keys", ["polished_title", "voiceover_text", "douyin_title", "douyin_desc", "tags", "cards"])
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise RuntimeError(f"DeepSeek response missing fields: {', '.join(missing)}")
    tags = require_list(data["tags"], "tags", 5)
    spec_input = data.get("premium_director_spec") or data.get("visual_recipe")
    if spec_input:
        try:
            data["premium_director_spec"] = normalize_premium_director_spec(spec_input, polish=data, video_profile=data.get("video_profile"))
        except ValueError as exc:
            raise RuntimeError(f"DeepSeek response premium_director_spec is invalid: {exc}") from exc
    storyboard = data.get("storyboard")
    if storyboard:
        try:
            data["storyboard"] = validate_storyboard(storyboard)
        except ValueError as exc:
            if data.get("premium_director_spec"):
                data["storyboard"] = compatibility_storyboard_from_premium(data)
                data["_storyboard_repair_error"] = str(exc)
            else:
                raise RuntimeError(f"DeepSeek response storyboard is invalid: {exc}") from exc
    elif data.get("premium_director_spec"):
        data["storyboard"] = compatibility_storyboard_from_premium(data)
    cards = data.get("cards") or (card_scenes(data.get("storyboard")) if data.get("storyboard") else [])
    try:
        if data.get("premium_director_spec"):
            data["agent_visual"] = require_agent_visual(
                compile_premium_agent_visual(data["premium_director_spec"], reason="deepseek normalized director spec")
            )
        else:
            data["agent_visual"] = require_agent_visual(data.get("agent_visual") or data.get("agentVisual"))
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    min_cards = 4 if any("cards must be 4" in str(item) for item in policy_get("deepseek.constraints", [])) else 1
    if not isinstance(cards, list) or len(cards) < min_cards:
        raise RuntimeError(f"DeepSeek response missing at least {min_cards} compatibility card")
    clean_cards = []
    for index, card in enumerate(cards[: max(min_cards, min(len(cards), 4))], start=1):
        if not isinstance(card, dict):
            raise RuntimeError(f"DeepSeek card {index} is not an object")
        clean_cards.append(
            {
                "label": bounded_text(card.get("label"), 18),
                "value": bounded_text(card.get("value"), 54),
                "detail": bounded_text(card.get("detail"), 118),
            }
        )
    data["tags"] = tags
    data["cards"] = clean_cards
    return scrub_polish_payload(data)


def parse_deepseek_payload(content: str) -> dict[str, Any]:
    return normalize_polish_payload(parse_json_object(content))


def parse_deepseek_variants(content: str, expected_count: int) -> list[dict[str, Any]]:
    data = parse_json_object(content)
    variants = data.get("variants")
    if not isinstance(variants, list) or len(variants) != expected_count:
        raise RuntimeError(f"DeepSeek response must include exactly {expected_count} variants")
    clean: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        if not isinstance(variant, dict):
            raise RuntimeError(f"DeepSeek variant {index} is not an object")
        clean.append(normalize_polish_payload(variant))
    return clean


def deepseek_constraints(video_seconds: int, *, variant_count: int = 1, video_profile: dict[str, Any] | None = None) -> list[str]:
    chars_per_second = int(policy_get("deepseek.chars_per_second", 7))
    lo = max(60, video_seconds * chars_per_second - 30)
    hi = video_seconds * chars_per_second + 20
    voiceover_chars_range = f"{lo}-{hi} Chinese characters"
    orientation = str((video_profile or {}).get("orientation") or "vertical")
    constraints = [
        policy_format(
            item,
            voiceover_chars_range=voiceover_chars_range,
            video_seconds=video_seconds,
            video_orientation=orientation,
        )
        for item in policy_get("deepseek.constraints", [])
    ]
    if variant_count > 1:
        constraints = [item for item in constraints if "Return exactly these keys" not in item]
        constraints.append(
            f"Return one JSON object with exactly one key `variants`, containing exactly {variant_count} objects."
        )
        constraints.append(
            "Each variants item must contain exactly these keys: polished_title, voiceover_text, douyin_title, douyin_desc, tags, cards, storyboard, premium_director_spec, agent_visual, video_profile, caveats."
        )
    return constraints


def request_deepseek(api_key: str, model: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    api_attempts = int(policy_get("deepseek.api_attempts", 2))
    last_exc: Exception | None = None
    for attempt in range(api_attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
            retryable = exc.code in (429, 500, 502, 503, 504) and attempt < api_attempts - 1
            if retryable:
                delay = 3.0 * (2 ** attempt)
                print(f"DeepSeek HTTP {exc.code}, retrying in {delay:.0f}s (attempt {attempt + 1}/{api_attempts})...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}")
                continue
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < api_attempts - 1:
                delay = 3.0 * (2 ** attempt)
                print(f"DeepSeek network error, retrying in {delay:.0f}s (attempt {attempt + 1}/{api_attempts})...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"DeepSeek network error: {exc}")
                continue
            raise RuntimeError(f"DeepSeek network error: {exc}") from exc
    raise last_exc or RuntimeError("DeepSeek call exhausted retries")


def response_message_content(payload: dict[str, Any]) -> str:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        finish_reason = choice.get("finish_reason")
        message_keys = sorted(str(key) for key in message.keys())
        raise RuntimeError(f"DeepSeek returned empty message content; finish_reason={finish_reason}; message_keys={message_keys}")
    return content.strip()


def deepseek_body(
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    *,
    temperature: float,
    video_seconds: int,
    video_profile: dict[str, Any] | None = None,
    variant_count: int = 1,
    evidence_bundle: dict[str, Any] | None = None,
    cross_check_review: dict[str, Any] | None = None,
    revision_feedback: dict[str, Any] | None = None,
    previous_polish: dict[str, Any] | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    system = policy_get("deepseek.system", "Return strict JSON only.")
    normalized_video_profile = normalize_video_profile(video_profile or choose_video_profile())
    user = {
        "task": (
            f"Polish {variant_count} distinct short-form video packages for Douyin and Remotion."
            if variant_count > 1
            else "Polish one short-form video package for Douyin and Remotion."
        ),
        "constraints": deepseek_constraints(video_seconds, variant_count=variant_count, video_profile=normalized_video_profile),
        "forbidden_claim_terms": unsupported_terms(),
        "required_entity_terms": candidate_entity_terms(candidate),
        "selected_candidate": candidate,
        "content_plan": content_plan,
        "topic_brief": content_plan.get("topic_brief") or content_plan.get("research_brief") or {},
        "research_brief": content_plan.get("research_brief") or content_plan.get("topic_brief") or {},
        "fact_bank": {
            "source_backed_facts": (content_plan.get("fact_bank") or {}).get("source_backed_facts") or [],
            "facts": (content_plan.get("fact_bank") or {}).get("facts") or [],
            "conflicts": (content_plan.get("fact_bank") or {}).get("conflicts") or [],
            "risk_notes": (content_plan.get("fact_bank") or {}).get("risk_notes") or [],
        },
        "evidence_bundle": {
            "source_kind": (evidence_bundle or {}).get("source_kind"),
            "source_facts": ((evidence_bundle or {}).get("evidence_summary") or {}).get("source_facts") or [],
            "constructive_angles": ((evidence_bundle or {}).get("evidence_summary") or {}).get("constructive_angles") or [],
            "combined_excerpt": ((evidence_bundle or {}).get("evidence_summary") or {}).get("combined_excerpt") or "",
        },
        "cross_check_review": cross_check_review or {},
        "suggested_video_profile": normalized_video_profile,
        "content_quality_requirement": [
            "Use research_brief and fact_bank to choose a concrete topic angle and visual scene path.",
            "Explain the concrete user problem, mechanism, architecture position, practical fit, failure boundary, and adoption judgment framework.",
            "Voiceover must sound like a top-tier technical explainer: every sentence should either clarify mechanism, locate the system layer, explain practical fit, define failure boundary, or sharpen the judgment framework.",
            "Synchronize voiceover beats with premium_director_spec.visual_scenes; each scene should teach one concrete concept rather than act like a title slide.",
            "Every strong public claim must be traceable to evidence_bundle source_facts or explicitly framed with a clear evidence boundary.",
            "For open-source projects, cover what the repo appears to do, why a developer would care, tradeoffs, and what to inspect before adopting.",
            "For GitHub/open-source topics, do not stop at a radar summary: include problem, mechanism or architecture, practical fit, tradeoff/risk, failure boundary, and a concrete judgment framework.",
            "Do not tell the viewer to verify, wait, or keep observing. Teach the reusable mechanism and decision framework inside the evidence boundary.",
            "Do not end voiceover_text or douyin_desc with a viewer question such as whether they would use it or how they would choose. End with a stated judgment framework.",
            "The rendered provider video is compiled from premium_director_spec. Author topic-specific visual intent; do not depend on the default storyboard scene renderer.",
            "Choose video_profile.duration_seconds, orientation, motion, and animation_style for the content depth; respect the suggested_video_profile unless you have a source-grounded reason to override it.",
        ],
    }
    if revision_feedback is not None:
        user["task"] = "Revise one complete short-form video package using Gemini evaluator feedback."
        user["attempt"] = attempt
        user["previous_polish"] = {
            "polished_title": (previous_polish or {}).get("polished_title"),
            "voiceover_text": (previous_polish or {}).get("voiceover_text"),
            "douyin_title": (previous_polish or {}).get("douyin_title"),
            "douyin_desc": (previous_polish or {}).get("douyin_desc"),
            "tags": (previous_polish or {}).get("tags"),
            "cards": (previous_polish or {}).get("cards"),
            "storyboard": (previous_polish or {}).get("storyboard"),
            "premium_director_spec": (previous_polish or {}).get("premium_director_spec"),
            "agent_visual": (previous_polish or {}).get("agent_visual"),
            "video_profile": (previous_polish or {}).get("video_profile"),
            "caveats": (previous_polish or {}).get("caveats"),
        }
        user["gemini_feedback"] = {
            "overall": revision_feedback.get("overall"),
            "verdict": revision_feedback.get("verdict"),
            "scores": revision_feedback.get("scores") or {},
            "failed_dimensions": revision_feedback.get("failed_dimensions") or {},
            "suggestions": revision_feedback.get("suggestions") or [],
            "revision_brief": revision_feedback.get("revision_brief") or {},
            "full_feedback": revision_feedback,
        }
        user["revision_rules"] = [
            "Return a full replacement JSON object, not a patch.",
            "Do not keep weak title, hook, storyboard, or caption-facing text if Gemini marked them below target.",
            "Preserve the selected candidate boundary and required_entity_terms reference.",
            "Do not introduce facts outside evidence_bundle or claims not supported by source_facts.",
            "Keep caveats when evidence is thin; improve the explanation, not the claim strength.",
            "Treat every required_changes, required_voiceover_structure, required_visual_structure, must_change, and must_not_do entry in gemini_feedback.full_feedback as a hard revision constraint.",
            "If the feedback names storyboard changes, rewrite storyboard.scenes directly with concrete scene types; do not rely on premium_director_spec alone.",
            "If the feedback names a target voiceover length or exact opening/final sentence, obey it unless it conflicts with evidence boundaries.",
            "Do not compress a 55-second explainer into a short summary; keep enough Mandarin voiceover detail for the configured duration.",
        ]
        user["content_quality_requirement"].extend(
            str(item)
            for item in policy_get("content_optimization.revision_focus", [])
            if str(item).strip()
        )
    storyboard_schema = {
        "version": 1,
        "style": {
            "theme": "radar|minimal|editorial",
            "density": "minimal|standard|rich",
            "motion": "calm|standard|punchy",
            "accent": "#ffd60a|#72e7ff|#ff2d55",
            "chrome": {"topbar": "boolean", "progress": "boolean", "beam": "boolean"},
        },
        "scenes": [
            {
                "type": "statement|context|stat|bullets|card|compare|compare_table|terminal|flow|chart|code_diff|quote|cta",
                "weight": "optional number 0-1",
                "emphasis": "optional low|normal|high",
                "props": "object bounded to the chosen scene type",
            }
        ],
    }
    package_schema = {
        "polished_title": "string",
        "voiceover_text": "string",
        "douyin_title": "string",
        "douyin_desc": "string",
        "tags": ["string"],
        "cards": [{"label": "string", "value": "string", "detail": "string"}],
        "storyboard": storyboard_schema,
        "premium_director_spec": {
            "schema_version": 1,
            "profile": {
                "orientation": "vertical|horizontal",
                "aspect_ratio": "9:16|16:9",
                "duration_seconds": "integer between 18 and 120",
                "style_family": "apple_keynote_showcase",
                "motion_comfort": "comfortable",
            },
            "knowledge_arc": {
                "hook": "topic-specific problem framing",
                "mechanism": "mechanism explanation",
                "architecture_position": "where it sits in a real system",
                "practical_fit": "where it is useful",
                "tradeoff": "main tradeoff",
                "failure_boundary": "where it fails or becomes costly",
                "judgment_framework": "how to decide whether to adopt or care",
                "takeaway": "non-generic knowledge takeaway",
            },
            "topic_objects": [
                {"id": "obj_1", "kind": "repo_file|api_surface|architecture_node|metric|failure_boundary", "label": "string", "detail": "string", "source_ref": "source id or evidence field"}
            ],
            "visual_scenes": [
                {
                    "id": "scene id",
                    "scene_type": "HeroProblemScene|MechanismExplodedView|RepoFileTreeReveal|ArchitectureFlowScene|MetricComparisonScene|DecisionMatrixScene|TimelineBuildScene|CodeOrTerminalScene|KnowledgeTakeawayScene",
                    "title": "short on-screen title",
                    "objective": "what knowledge this scene teaches",
                    "teaching_beats": ["2-4 short beats the voiceover should teach in this scene"],
                    "object_refs": ["topic object ids"],
                    "layout": "full_canvas_keynote",
                    "motion_beats": ["reveal|build|pan|morph|path_draw|metric_count|object_focus|dwell"],
                }
            ],
            "motion_beats": [{"type": "reveal|build|pan|morph|path_draw|metric_count|object_focus|dwell", "target": "string", "intensity": "calm|restrained|medium"}],
            "content_constraints": {
                "source_boundary": "claims stay inside evidence",
                "knowledge_takeaway_required": True,
                "forbid_dismissive_verification_language": True,
            },
        },
        "agent_visual": {
            "enabled": True,
            "render_mode": "full_canvas",
            "description": "short note on why the premium_director_spec fits the topic. Runtime will compile this locally; do not include raw TSX/CSS unless explicitly needed for compatibility.",
        },
        "video_profile": {
            "duration_seconds": "integer between 18 and 120",
            "orientation": "vertical|horizontal",
            "aspect_ratio": "9:16|16:9",
            "motion": "calm|standard|punchy",
            "animation_style": "kinetic_text|diagrammatic|evidence_cards|minimal",
            "decision_reason": "short string explaining why this format fits the topic",
        },
        "caveats": ["string"],
    }
    if variant_count > 1:
        user["output_schema"] = {"variants": [package_schema]}
    else:
        user["output_schema"] = package_schema
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": temperature,
        "max_tokens": int(os.environ.get("SEARCHPO_DEEPSEEK_MAX_TOKENS") or policy_get("deepseek.max_tokens", 1800)),
    }
    thinking_type = str(policy_get("deepseek.thinking_type", "") or "").strip()
    if thinking_type:
        body["thinking"] = {"type": thinking_type}
    if variant_count == 1:
        body["response_format"] = {"type": "json_object"}
    return body


def deepseek_chat(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    timeout: float,
    temperature: float = 0.4,
    video_seconds: int = 12,
    video_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = deepseek_body(
        model,
        candidate,
        content_plan,
        temperature=temperature,
        video_seconds=video_seconds,
        video_profile=video_profile,
        evidence_bundle=evidence_bundle,
        cross_check_review=cross_check_review,
    )
    payload = request_deepseek(api_key, model, body, timeout)
    content = response_message_content(payload)
    parsed = parse_deepseek_payload(content)
    try:
        validate_polish(candidate, parsed)
        parsed["_raw_usage"] = payload.get("usage")
        parsed["_correction_applied"] = False
        return parsed
    except RuntimeError as exc:
        corrected = correct_deepseek_polish(
            api_key,
            model,
            candidate,
            content_plan,
            evidence_bundle,
            cross_check_review,
            parsed,
            str(exc),
            timeout,
            video_seconds=video_seconds,
            video_profile=video_profile,
        )
        validate_polish(candidate, corrected)
        corrected["_correction_applied"] = True
        corrected["_initial_error"] = str(exc)
        return corrected


def deepseek_revision_chat(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    previous_polish: dict[str, Any],
    revision_feedback: dict[str, Any],
    timeout: float,
    temperature: float = 0.35,
    video_seconds: int = 12,
    video_profile: dict[str, Any] | None = None,
    attempt: int = 2,
) -> dict[str, Any]:
    body = deepseek_body(
        model,
        candidate,
        content_plan,
        temperature=temperature,
        video_seconds=video_seconds,
        video_profile=video_profile,
        evidence_bundle=evidence_bundle,
        cross_check_review=cross_check_review,
        revision_feedback=revision_feedback,
        previous_polish=previous_polish,
        attempt=attempt,
    )
    payload = request_deepseek(api_key, model, body, timeout)
    content = response_message_content(payload)
    parsed = parse_deepseek_payload(content)
    try:
        validate_polish(candidate, parsed)
        parsed["_raw_usage"] = payload.get("usage")
        parsed["_correction_applied"] = False
        return parsed
    except RuntimeError as exc:
        corrected = correct_deepseek_polish(
            api_key,
            model,
            candidate,
            content_plan,
            evidence_bundle,
            cross_check_review,
            parsed,
            str(exc),
            timeout,
            video_seconds=video_seconds,
            video_profile=video_profile,
        )
        validate_polish(candidate, corrected)
        corrected["_correction_applied"] = True
        corrected["_initial_error"] = str(exc)
        return corrected


def correct_deepseek_polish(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    rejected: dict[str, Any],
    validation_error: str,
    timeout: float,
    video_seconds: int = 12,
    video_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = deepseek_body(
        model,
        candidate,
        content_plan,
        temperature=0.1,
        video_seconds=video_seconds,
        video_profile=video_profile,
        evidence_bundle=evidence_bundle,
        cross_check_review=cross_check_review,
    )
    user = json.loads(body["messages"][1]["content"])
    user["task"] = "Correct the rejected short-form video JSON so it passes the validation error exactly."
    user["validation_error"] = validation_error
    user["rejected_json"] = rejected
    user["correction_rules"] = [
        "Return a complete replacement JSON object with the required keys only.",
        "Remove every forbidden claim term named in validation_error.",
        "Remove any phrasing that tells viewers to verify, wait, observe, or test for themselves; replace it with mechanism, architecture position, failure boundary, and judgment framework.",
        "If the rejected voiceover ends with a viewer question, replace the ending with a concrete judgment framework statement.",
        "Keep or rebuild premium_director_spec with at least five visual_scenes, four distinct scene_type values, three topic_objects, and three motion_beats.",
        "Keep the selected candidate boundary and required_entity_terms reference.",
    ]
    body["messages"][1]["content"] = json.dumps(user, ensure_ascii=False)
    payload = request_deepseek(api_key, model, body, timeout)
    content = response_message_content(payload)
    corrected = parse_deepseek_payload(content)
    corrected["_raw_usage"] = payload.get("usage")
    return corrected


def deepseek_variant_chat(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    timeout: float,
    video_seconds: int = 12,
    video_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    variant_count = int(os.environ.get("SEARCHPO_POLISH_VARIANT_COUNT") or policy_get("deepseek.variant_count", 3))
    body = deepseek_body(
        model,
        candidate,
        content_plan,
        temperature=float(policy_get("deepseek.variant_temperature", 0.5)),
        video_seconds=video_seconds,
        video_profile=video_profile,
        variant_count=variant_count,
        evidence_bundle=evidence_bundle,
        cross_check_review=cross_check_review,
    )
    payload = request_deepseek(api_key, model, body, timeout)
    content = response_message_content(payload)
    parsed_variants = parse_deepseek_variants(content, variant_count)
    valid: list[dict[str, Any]] = []
    rejected: list[str] = []
    for index, parsed in enumerate(parsed_variants, start=1):
        try:
            validate_polish(candidate, parsed)
        except RuntimeError as exc:
            rejected.append(f"variant {index}: {exc}")
            continue
        parsed["_raw_usage"] = payload.get("usage")
        valid.append(parsed)
    if not valid:
        raise RuntimeError("DeepSeek returned no valid variants: " + "; ".join(rejected))
    return valid


def _score_polish(polished: dict[str, Any]) -> float:
    """Heuristic quality score: information density, hook strength, length fit."""
    score = 0.0
    voiceover = str(polished.get("voiceover_text") or "")
    cn_chars = len(re.findall(r"[一-鿿]", voiceover))
    if 60 <= cn_chars <= 600:
        score += 3.0
    elif 40 <= cn_chars <= 700:
        score += 1.5
    title = str(polished.get("polished_title") or "")
    if any(hook in title for hook in policy_get("deepseek.hook_terms", ["为什么", "怎么"])):
        score += 2.0
    cards = polished.get("cards") or []
    storyboard = polished.get("storyboard") or {}
    scene_types = [str(scene.get("type")) for scene in storyboard.get("scenes") or [] if isinstance(scene, dict)]
    if len(set(scene_types)) >= 3 and {"statement", "cta"}.issubset(set(scene_types)):
        score += 2.0
    elif len(cards) >= 2 and all(len(str(c.get("value") or "")) > 4 for c in cards):
        score += 1.0
    if polished.get("caveats"):
        score += 1.0
    return score


def _multi_candidate_polish(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    timeout: float,
    video_seconds: int = 12,
    video_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask the provider for multiple variants in one structured response and pick the highest-scoring valid one."""
    polished_variants = deepseek_variant_chat(
        api_key,
        model,
        candidate,
        content_plan,
        evidence_bundle,
        cross_check_review,
        timeout,
        video_seconds=video_seconds,
        video_profile=video_profile,
    )
    variants: list[tuple[float, dict[str, Any]]] = [(_score_polish(polished), polished) for polished in polished_variants]
    if not variants:
        raise RuntimeError("All multi-candidate polish attempts failed")
    variants.sort(key=lambda x: x[0], reverse=True)
    best = variants[0][1]
    best["_multi_candidate_scores"] = [v[0] for v in variants]
    best["_multi_candidate_count"] = len(variants)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--mode", choices=["initial", "revise"], default="initial")
    parser.add_argument("--feedback", help="Gemini content_score JSON used in revise mode.")
    parser.add_argument("--input-polish", help="Previous DeepSeek polish JSON used in revise mode.")
    parser.add_argument("--output", help="Output JSON path. Defaults to run_dir/deepseek_polish.json.")
    parser.add_argument("--attempt", type=int, default=1, help="Optimization attempt number for artifact metadata.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    env_file = Path(args.env_file).resolve()
    api_key = env_value("DEEPSEEK_API_KEY", env_file)
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required for scripts/deepseek_polish.py")
    model = env_value("SEARCHPO_DEEPSEEK_MODEL", env_file, "deepseek-v4-pro")
    candidate_path = run_dir / "selected_candidate.json"
    plan_path = run_dir / "content_plan.json"
    evidence_path = run_dir / "evidence_bundle.json"
    cross_check_path = run_dir / "cross_check_review.json"
    if not candidate_path.exists() or not plan_path.exists() or not evidence_path.exists() or not cross_check_path.exists():
        raise SystemExit("selected_candidate.json, content_plan.json, evidence_bundle.json, and cross_check_review.json are required before DeepSeek polish")

    candidate = read_json(candidate_path)
    content_plan = read_json(plan_path)
    topic_brief_path = run_dir / "topic_brief.json"
    fact_bank_path = run_dir / "fact_bank.json"
    source_map_path = run_dir / "source_map.json"
    if topic_brief_path.exists():
        topic_brief = read_json(topic_brief_path)
        content_plan["topic_brief"] = topic_brief
        content_plan.setdefault("research_brief", topic_brief)
    if fact_bank_path.exists():
        content_plan["fact_bank"] = read_json(fact_bank_path)
    if source_map_path.exists():
        content_plan["source_map"] = read_json(source_map_path)
    evidence_bundle = read_json(evidence_path)
    cross_check_review = read_json(cross_check_path)
    strong_research_errors = strong_research_review_errors(cross_check_review)
    if strong_research_errors:
        raise SystemExit(f"strong research review must pass before DeepSeek polish: {strong_research_errors}")
    fallback_video_profile = choose_video_profile(candidate, content_plan, evidence_bundle)
    video_profile_override: dict[str, Any] = {}
    env_seconds = env_value("SEARCHPO_VIDEO_SECONDS", env_file, "")
    env_duration_frames = env_value("SEARCHPO_DURATION_FRAMES", env_file, "")
    env_orientation = env_value("SEARCHPO_VIDEO_ORIENTATION", env_file, "")
    if env_seconds:
        video_profile_override["duration_seconds"] = env_seconds
    elif env_duration_frames:
        try:
            video_profile_override["duration_seconds"] = max(1, round(int(env_duration_frames) / 30))
        except ValueError:
            pass
    if env_orientation:
        video_profile_override["orientation"] = env_orientation
    video_profile = normalize_video_profile(
        {
            **(content_plan.get("suggested_video_profile") or {}),
            **video_profile_override,
        },
        fallback=fallback_video_profile,
    )
    video_seconds = int(video_profile["duration_seconds"])
    multi_candidate = env_value("SEARCHPO_POLISH_MULTI_CANDIDATE", env_file, "0") == "1"
    revision_meta: dict[str, Any] | None = None
    if args.mode == "revise":
        if not args.feedback or not args.input_polish:
            raise SystemExit("--feedback and --input-polish are required when --mode revise")
        feedback_path = Path(args.feedback).resolve()
        input_polish_path = Path(args.input_polish).resolve()
        feedback = read_json(feedback_path)
        previous_polish = read_json(input_polish_path)
        polished = deepseek_revision_chat(
            api_key,
            model,
            candidate,
            content_plan,
            evidence_bundle,
            cross_check_review,
            previous_polish,
            feedback,
            args.timeout,
            video_seconds=video_seconds,
            video_profile=video_profile,
            attempt=args.attempt,
        )
        revision_meta = {
            "attempt": args.attempt,
            "mode": "revise",
            "feedback_path": str(feedback_path),
            "input_polish_path": str(input_polish_path),
            "previous_overall": feedback.get("overall"),
            "previous_verdict": feedback.get("verdict"),
            "failed_dimensions": feedback.get("failed_dimensions") or {},
            "suggestions": feedback.get("suggestions") or [],
        }
    elif multi_candidate:
        polished = _multi_candidate_polish(
            api_key,
            model,
            candidate,
            content_plan,
            evidence_bundle,
            cross_check_review,
            args.timeout,
            video_seconds=video_seconds,
            video_profile=video_profile,
        )
    else:
        polished = deepseek_chat(
            api_key,
            model,
            candidate,
            content_plan,
            evidence_bundle,
            cross_check_review,
            args.timeout,
            video_seconds=video_seconds,
            video_profile=video_profile,
        )
    polished = scrub_polish_payload(polished)
    polished_video_profile = normalize_video_profile(polished.get("video_profile"), fallback=video_profile)
    polished = apply_premium_director_visual(
        candidate,
        content_plan,
        polished,
        polished_video_profile,
        reason=f"deepseek {args.mode} premium director compiler",
    )
    polished = scrub_polish_payload(polished)
    validate_polish(candidate, polished)
    unsafe_hits = unsafe_hits_for(polished)
    dismissive_hits = dismissive_hits_for(polished)
    status = "pass" if not unsafe_hits and not dismissive_hits else "fail"
    result = {
        "schema_version": 1,
        "created_at": utc_now(),
        "provider": "deepseek",
        "model": model,
        "attempt": args.attempt,
        "mode": args.mode,
        "selected_candidate_id": candidate.get("candidate_id"),
        "status": status,
        "polished_title": bounded_text(polished["polished_title"], 80),
        "voiceover_text": bounded_text(polished["voiceover_text"], 1000),
        "script_text_hash": sha256_text(str(polished["voiceover_text"] or "")),
        "douyin_title": bounded_text(polished["douyin_title"], 55),
        "douyin_desc": bounded_text(polished["douyin_desc"], 600),
        "tags": polished["tags"],
        "cards": polished["cards"],
        "storyboard": polished.get("storyboard"),
        "premium_director_spec": polished.get("premium_director_spec"),
        "agent_visual": polished.get("agent_visual"),
        "video_profile": polished_video_profile,
        "caveats": polished.get("caveats") or [],
        "unsafe_claim_hits": unsafe_hits,
        "dismissive_verification_hits": dismissive_hits,
        "storyboard_repair_error": polished.get("_storyboard_repair_error"),
        "correction_applied": bool(polished.get("_correction_applied")),
        "initial_error": polished.get("_initial_error"),
        "usage": polished.get("_raw_usage"),
        "revision_meta": revision_meta,
        "input_files": [
            str(path)
            for path in [candidate_path, plan_path, topic_brief_path, fact_bank_path, source_map_path, evidence_path, cross_check_path]
            if path.exists()
        ],
    }
    output_path = Path(args.output).resolve() if args.output else run_dir / "deepseek_polish.json"
    write_json(output_path, result)
    print(json.dumps({"deepseek_polish": str(output_path), "status": result["status"]}, ensure_ascii=False, indent=2))
    if unsafe_hits:
        raise SystemExit(f"DeepSeek polish generated unsupported claim terms: {unsafe_hits}")
    if dismissive_hits:
        raise SystemExit(f"DeepSeek polish generated banned dismissive verification phrasing: {dismissive_hits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
