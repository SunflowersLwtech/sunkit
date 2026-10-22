from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from agent_harness.artifact_identity import sha256_json_file
from agent_harness.core import Artifact, Gate, HarnessContext, StageResult, utc_now, write_json, retry_call, logger
from agent_harness.douyin_distribution import evaluate_douyin_distribution_gate
from agent_harness.evidence import strong_research_review_errors, write_evidence_artifacts
from agent_harness.policy import content_profile, policy_format, policy_get, unsupported_terms
from agent_harness.premium_director import compile_premium_agent_visual, normalize_premium_director_spec
from agent_harness.research import run_research_enrichment
from agent_harness.runtime_contracts import (
    IMPL_AGENT,
    MAIN_AGENT,
    RESEARCH_AGENT,
    IMPLEMENTATION_LOOP_FILENAME,
    RUNTIME_CONTRACT_FILENAME,
    RESEARCH_BARRIER_FILENAME,
    build_main_task_plan,
    write_implementation_loop,
    write_research_barrier,
    write_runtime_contract,
)
from agent_harness.service_artifacts import (
    build_scene_plan_artifact,
    build_script_artifact,
    build_video_spec_artifact,
    write_environment_manifest,
    write_optional_analytics_feedback,
)
from agent_harness.side_effect_tiers import side_effect_axes
from agent_harness.speech_quality import (
    bounded_text,
    evaluate_quality_gate,
    evidence_level_for_candidate,
    normalize_display_title,
    normalize_voiceover_text,
    plan_cover_title_lines,
    unverified_quality_warning,
    verification_next_step_for_candidate,
)
from agent_harness.agent_visual import agent_visual_text_items, require_agent_visual
from agent_harness.premium_repo_visual import is_github_repo_subject, premium_repo_agent_visual
from agent_harness.storyboard import card_scenes, derive_default_storyboard, storyboard_text_items, validate_storyboard
from agent_harness.subjects import ensure_subject_pool, is_operator_topic
from agent_harness.video_profile import choose_video_profile, normalize_video_profile

# scripts/ holds the publishing/normalization helpers shared with the CLIs.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from douyin_tags import build_tag_bundle, extract_inline_hashtags  # noqa: E402
from provider_modes import REAL_TTS_PROVIDERS, TTS_SCRIPTS, tts_provider  # noqa: E402


PROVIDER_ENV_CONTRACT = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GOOGLE_AGENT_PLATFORM_API",
    "gemini_api_alias": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def voiceover_manifest_errors(manifest: dict[str, Any], audio_path: Path) -> list[str]:
    errors: list[str] = []
    if manifest.get("status") != "pass":
        errors.append(f"status is {manifest.get('status') or 'missing'}")
    if manifest.get("provider") not in REAL_TTS_PROVIDERS:
        errors.append(f"provider is {manifest.get('provider') or 'missing'}")
    if not audio_path.is_file():
        errors.append(f"audio file missing: {audio_path}")
    elif manifest.get("audio_sha256") != sha256_file(audio_path):
        errors.append("audio_sha256 does not match audio file")
    if not manifest.get("audio_duration_sec") or not manifest.get("audio_frames"):
        errors.append("audio_duration_sec/audio_frames missing")
    return errors


def _state_or_file(context: HarnessContext, key: str, filename: str) -> dict[str, Any]:
    value = context.state.get(key)
    if isinstance(value, dict):
        return value
    path = context.run_dir / filename
    if not path.exists():
        return {}
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def sanitize_post(text: Any, limit: int = 260) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."


def _sanitize_display(text: str, limit: int = 260) -> str:
    return bounded_text(str(text or ""), limit)


def _render_template_list(templates: list[str], **values: Any) -> list[str]:
    rows: list[str] = []
    for template in templates:
        if "{url}" in template and not values.get("url"):
            continue
        rendered = policy_format(template, **values).strip()
        if rendered:
            rows.append(rendered)
    return rows


def _candidate_evidence_sources(candidate: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for item in candidate.get("evidence") or []:
        source = str((item or {}).get("source") or "").strip()
        if source and source not in sources:
            sources.append(source)
    for source in candidate.get("source_ids") or []:
        source_text = str(source or "").strip()
        if source_text and source_text not in sources:
            sources.append(source_text)
    return sources


def _public_source_label(source_id: str) -> str:
    labels = policy_get("content.source_labels", {})
    if isinstance(labels, dict):
        label = str(labels.get(source_id) or "").strip()
        if label:
            return label
    return source_id.replace("_", " ").strip().title()


def _public_evidence_sources(candidate: dict[str, Any]) -> list[str]:
    return [_public_source_label(source) for source in _candidate_evidence_sources(candidate)]


def _public_operator_source_label(candidate: dict[str, Any], profile: dict[str, Any], has_external_url: bool) -> str:
    """Return a viewer-facing source label without leaking operator-topic ids."""
    if has_external_url:
        host = urlparse(str(candidate.get("canonical_url") or "")).netloc.lower()
        if host.endswith("github.com"):
            return "GitHub"
        if host:
            return host
    return str(profile.get("manual_source_label") or profile.get("source") or "指定主题")


def _candidate_has_external_url(candidate: dict[str, Any]) -> bool:
    url = str(candidate.get("canonical_url") or "")
    manual_scheme = str(policy_get("subject_inputs.operator_topic.manual_url_scheme", "manual-topic://"))
    return bool(url.startswith(("http://", "https://")) and not url.startswith(manual_scheme))


def _candidate_title_summary(candidate: dict[str, Any], polish: dict[str, Any] | None = None) -> tuple[str, str]:
    title = str((polish or {}).get("polished_title") or candidate.get("title") or "Searchpo Radar").strip()
    summary = str(
        (polish or {}).get("voiceover_text")
        or candidate.get("summary")
        or policy_get("content.default_summary", "Fresh signal detected from the daily source sweep.")
    ).strip()
    if not title:
        raise RuntimeError("selected candidate missing title")
    if not summary:
        raise RuntimeError("selected candidate missing summary")
    return title, summary


def _safe_cover_display_title(title: str, candidate: dict[str, Any]) -> str:
    normalized = normalize_display_title(title).replace("...", "").strip(" -:：，,。.")
    candidates = [normalized]
    for separator in (":", "：", " - ", " — ", " – "):
        if separator in normalized:
            candidates.append(normalized.split(separator, 1)[0].strip(" -:：，,。."))
    candidate_title = normalize_display_title(str(candidate.get("title") or "")).strip(" -:：，,。.")
    if candidate_title:
        candidates.append(candidate_title)
    seen: set[str] = set()
    for item in candidates:
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        if plan_cover_title_lines(item)["safe"]:
            return item
    words = normalized.split()
    for count in range(min(6, len(words)), 1, -1):
        shortened = " ".join(words[:count]).strip(" -:：，,。.")
        if shortened and plan_cover_title_lines(shortened)["safe"]:
            return shortened
    return bounded_text(normalized, 32)


def _public_title_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        host = parsed.netloc.lower().removeprefix("www.")
        if host == "github.com" and len(parts) >= 2:
            return f"{parts[0]}/{parts[1].removesuffix('.git')}"
        if parts and parts[-1].lower() in {"blog", "post", "posts", "article", "articles", "news"}:
            query = parse_qs(parsed.query)
            for key in ("id", "slug"):
                value = str((query.get(key) or [""])[0]).strip()
                if value and re.search(r"[A-Za-z]", value):
                    return value.replace("-", " ").replace("_", " ").strip() or parts[-1]
        if parts:
            return parts[-1].replace("-", " ").replace("_", " ").strip() or host
        return host


def _public_candidate_title(candidate: dict[str, Any]) -> str:
    title = str(candidate.get("title") or "").strip()
    canonical_url = str(candidate.get("canonical_url") or "").strip()
    parsed = urlparse(title)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        canonical = urlparse(canonical_url)
        if canonical.scheme in {"http", "https"} and canonical.netloc and canonical_url.rstrip("/") != title.rstrip("/"):
            return _public_title_from_url(canonical_url)
        return _public_title_from_url(title)
    return title or "today's signal"


def _normalize_caption_segments(caption_data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"text": s["text"], "startFrame": s["start_frame"], "endFrame": s["end_frame"]}
        for s in caption_data.get("segments") or []
        if str(s.get("text") or "").strip()
    ]


def select_candidate(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        raise RuntimeError("candidate_shortlist.json has no items")
    pin_url = os.environ.get("SEARCHPO_PIN_URL", "").strip()
    if pin_url:
        for item in items:
            if item.get("canonical_url") == pin_url:
                return item
        raise RuntimeError(f"SEARCHPO_PIN_URL was not found in candidate_shortlist.json: {pin_url}")
    return max(
        items,
        key=lambda item: (
            float(item.get("candidate_score") or 0),
            int(item.get("signals", {}).get("source_count") or 1),
            float(item.get("signals", {}).get("metric_strength") or 0),
        ),
    )


class ScriptTransientError(RuntimeError):
    """Raised for transient script failures (timeout, rate-limit signals)."""


def run_repo_script(context: HarnessContext, args: list[str], timeout: int = 180, max_retries: int = 3) -> dict[str, Any]:
    command = [sys.executable, *args]

    def _exec():
        try:
            proc = subprocess.run(
                command,
                cwd=context.root_dir,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ScriptTransientError(f"Script timed out after {timeout}s: {' '.join(command)}") from exc
        result = {
            "command": " ".join(command),
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
        if proc.returncode != 0:
            stderr = proc.stderr[-2000:]
            stderr_lower = stderr.lower()
            transient_signals = ("429", "rate limit", "quota", "503", "timed out", "etimedout", "temporarily unavailable")
            if any(sig in stderr_lower for sig in transient_signals):
                raise ScriptTransientError(
                    f"Script transient failure ({proc.returncode}): {' '.join(command)}\nstderr:\n{stderr}"
                )
            raise RuntimeError(
                f"Script failed ({proc.returncode}): {' '.join(command)}\n"
                f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{stderr}"
            )
        return result

    return retry_call(_exec, max_retries=max_retries, base_delay=3.0, retryable=(ScriptTransientError,))


def build_video_payload(
    candidate: dict[str, Any],
    polish: dict[str, Any] | None = None,
    voiceover_manifest: dict[str, Any] | None = None,
    captions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    operator_topic = is_operator_topic(candidate)
    profile = content_profile(candidate)
    if not voiceover_manifest:
        raise RuntimeError("voiceover_manifest.json is required to build the render payload.")
    if not captions:
        raise RuntimeError("captions.json is required to build the render payload.")
    title, summary = _candidate_title_summary(candidate, polish)
    display_title = _safe_cover_display_title(title, candidate)
    speech_title = normalize_voiceover_text(title)
    public_summary = normalize_voiceover_text(summary)
    evidence_level = evidence_level_for_candidate(candidate)
    verification_next_step = verification_next_step_for_candidate(candidate)
    quality_warnings = [warning for warning in [unverified_quality_warning(candidate)] if warning]
    source_ids = ", ".join(candidate.get("source_ids") or [])
    if not source_ids and not operator_topic:
        raise RuntimeError("selected candidate missing source_ids")
    url = candidate.get("canonical_url") or ""
    if not url:
        raise RuntimeError("selected candidate missing canonical_url")
    score = candidate.get("candidate_score")
    signals = candidate.get("signals") or {}
    metrics = candidate.get("metrics") or {}
    stars = metrics.get("stars")
    stars_today = metrics.get("stars_today")
    metric_parts = [
        f"{int(stars):,} stars" if str(stars or "").isdigit() else None,
        f"+{int(stars_today):,} today" if str(stars_today or "").isdigit() else None,
    ]
    metric_line = " · ".join(part for part in metric_parts if part)
    manual_scheme = policy_get("subject_inputs.operator_topic.manual_url_scheme", "manual-topic://")
    has_external_url = bool(url and not url.startswith(manual_scheme))
    public_source_ids = ", ".join(_public_source_label(source) for source in candidate.get("source_ids") or [])
    raw_evidence_source_value = ", ".join(_candidate_evidence_sources(candidate))
    public_evidence_source_value = ", ".join(_public_evidence_sources(candidate))
    if operator_topic and not has_external_url:
        evidence_value = profile.get("manual_source_label", "operator topic")
    elif operator_topic:
        evidence_value = raw_evidence_source_value or source_ids or _public_operator_source_label(candidate, profile, has_external_url)
    else:
        evidence_value = public_evidence_source_value or public_source_ids or policy_get("content.source_registry_label", "source registry")
    if operator_topic:
        internal_source_ids = {
            str(policy_get("subject_inputs.operator_topic.input_mode", "operator_topic")),
            str(policy_get("subject_inputs.operator_topic.selection_source", "operator_topic")),
            str(policy_get("subject_inputs.operator_topic.source_id", "operator_topic")),
        }
        evidence_parts = {part.strip() for part in str(evidence_value).split(",") if part.strip()}
        if evidence_parts and evidence_parts.issubset(internal_source_ids):
            evidence_value = _public_operator_source_label(candidate, profile, has_external_url)
        else:
            evidence_value = ", ".join(_public_source_label(part) for part in evidence_parts) or evidence_value
    evidence_detail = (
        "外部来源已抓取并留档，不在公开文案引导跳转。"
        if has_external_url
        else "未附外部来源时，只能引用输入本身，不做事实定论。"
    )
    template_values = {
        "title": sanitize_post(title, 64),
        "summary": sanitize_post(summary, 120),
        "url": sanitize_post(url, 110),
        "source_ids": evidence_value,
        "evidence_value": sanitize_post(
            evidence_value if operator_topic else (public_source_ids or policy_get("content.source_registry_label", "source registry")),
            64,
        ),
        "evidence_detail": sanitize_post(evidence_detail, 120),
        "verification_next_step": verification_next_step,
        "score": score,
        "has_code_signal": bool(signals.get("has_code_signal")),
        "has_demo_keyword": bool(signals.get("has_demo_keyword")),
        "source_count": signals.get("source_count"),
    }
    profile_cards = [
        {
            "label": policy_format(card.get("label", ""), **template_values),
            "value": sanitize_post(policy_format(card.get("value", ""), **template_values), 64),
            "detail": sanitize_post(policy_format(card.get("detail", ""), **template_values), 120),
        }
        for card in profile.get("cards", [])
    ]
    storyboard: dict[str, Any] | None = None
    polish_storyboard = (polish or {}).get("storyboard") if polish else None
    if polish_storyboard:
        try:
            storyboard = validate_storyboard(polish_storyboard)
        except ValueError as exc:
            raise RuntimeError(f"DeepSeek polish storyboard did not pass validation: {exc}") from exc
    elif polish:
        raise RuntimeError("DeepSeek polish storyboard is required; default storyboard fallback is not allowed in provider mode")
    fps = int(voiceover_manifest.get("fps") or os.environ.get("SEARCHPO_VIDEO_FPS") or 30)
    fallback_profile = choose_video_profile(candidate, fps=fps)
    video_profile = normalize_video_profile((polish or {}).get("video_profile") if polish else None, fallback=fallback_profile)
    orientation = video_profile.get("orientation") or "vertical"
    premium_repo_visual_applied = False
    cards = (polish or {}).get("cards") or (card_scenes(storyboard) if storyboard else []) or profile_cards
    if not polish and len(cards) < len(profile_cards):
        cards = list(cards) + profile_cards[len(cards):]
    cards = [
        {
            "label": _sanitize_display(card.get("label"), 18),
            "value": _sanitize_display(card.get("value"), 64),
            "detail": _sanitize_display(card.get("detail"), 120),
        }
        for card in cards[:4]
    ]
    if not cards:
        raise RuntimeError("render payload requires cards from DeepSeek polish or content profile data")
    fps = int(voiceover_manifest.get("fps") or os.environ.get("SEARCHPO_VIDEO_FPS") or 30)
    audio_frames = voiceover_manifest.get("audio_frames")
    if not audio_frames:
        raise RuntimeError("voiceover_manifest.json missing audio_frames")
    tail = int(os.environ.get("SEARCHPO_VIDEO_TAIL_FRAMES") or round(fps * 0.4))
    duration_frames = int(audio_frames) + tail
    max_caption_end = max(int(segment.get("endFrame") or 0) for segment in captions)
    if max_caption_end <= 0:
        raise RuntimeError("captions.json has no positive endFrame values")
    duration_frames = max(duration_frames, max_caption_end + tail)
    metric_template = profile.get("metric_template", "candidate score {score}")
    audience_metric_template = profile.get("audience_metric_template", metric_template)
    metric = policy_format(metric_template, score=score) if operator_topic or not metric_line else metric_line
    audience_metric = policy_format(audience_metric_template, score=score) if operator_topic or not metric_line else metric_line
    if not metric:
        raise RuntimeError("metricLine is required")
    badge = profile.get("badge", "指定主题分析" if operator_topic else "今日 AI 工具热点")
    cta = profile.get("cta", "")
    footer = profile.get("footer", "")
    if not badge or not cta or not footer:
        raise RuntimeError("content profile must define badge, cta, and footer for render payload")
    voiceover_text = normalize_voiceover_text(
        str(
            voiceover_manifest.get("normalized_voiceover_text")
            or voiceover_manifest.get("voiceover_text")
            or ""
        ).strip()
    )
    if not voiceover_text:
        raise RuntimeError("voiceover_manifest.json missing voiceover_text")
    if storyboard is None:
        storyboard = derive_default_storyboard(
            display_title=display_title,
            summary=summary,
            audience_metric=audience_metric,
            evidence_level=evidence_level,
            url=url,
            cards=cards,
            cta=cta,
            verification_next_step=verification_next_step,
            footer=footer,
        )
    storyboard_style = storyboard.get("style") if isinstance(storyboard.get("style"), dict) else {}
    if not storyboard_style.get("motion") and video_profile.get("motion"):
        storyboard_style["motion"] = video_profile["motion"]
        storyboard["style"] = storyboard_style

    premium_director_spec: dict[str, Any] | None = None
    agent_visual: dict[str, Any] | None = None
    if polish:
        has_explicit_director_spec = bool((polish or {}).get("premium_director_spec") or (polish or {}).get("visual_recipe"))
        try:
            if has_explicit_director_spec:
                premium_director_spec = normalize_premium_director_spec(
                    (polish or {}).get("premium_director_spec") or (polish or {}).get("visual_recipe"),
                    candidate=candidate,
                    polish=polish,
                    video_profile=video_profile,
                )
                agent_visual = require_agent_visual(
                    compile_premium_agent_visual(premium_director_spec, reason="render payload premium director compiler"),
                    orientation,
                )
            elif is_github_repo_subject(candidate, polish):
                agent_visual = require_agent_visual(
                    premium_repo_agent_visual("github repo subject without explicit premium director spec"),
                    orientation,
                )
                premium_repo_visual_applied = True
            else:
                agent_visual = require_agent_visual((polish or {}).get("agent_visual") or (polish or {}).get("agentVisual"), orientation)
        except (ValueError, TypeError) as exc:
            raise RuntimeError(f"provider render visual contract failed: {exc}") from exc

    payload = {
        "badge": badge,
        "title": _sanitize_display(display_title, 90),
        "displayTitle": _sanitize_display(display_title, 90),
        "speechTitle": _sanitize_display(speech_title, 120),
        "summary": _sanitize_display(public_summary, 700),
        "source": evidence_value if operator_topic and has_external_url else (profile.get("source") if operator_topic else public_source_ids),
        "url": url,
        "score": score,
        "metricLine": metric,
        "audienceMetricLine": audience_metric,
        "evidenceLevel": evidence_level,
        "qualityWarnings": quality_warnings,
        "verificationNextStep": verification_next_step,
        "cards": cards,
        "storyboard": storyboard,
        "premium_director_spec": premium_director_spec,
        "premiumDirectorSpec": premium_director_spec,
        "agentVisual": agent_visual or {"enabled": False},
        "agentVisualRequired": bool(polish),
        "videoProfile": video_profile,
        "orientation": video_profile["orientation"],
        "aspectRatio": video_profile["aspect_ratio"],
        "width": video_profile["width"],
        "height": video_profile["height"],
        "audioSrc": "voiceover.wav",
        "voiceoverText": voiceover_text,
        "captions": captions,
        "durationInFrames": duration_frames,
        "fps": fps,
        "cta": cta,
        "footer": footer,
    }
    if polish and polish.get("_agent_visual_fallback_applied") and not premium_repo_visual_applied:
        payload["_agent_visual_fallback_applied"] = True
        if polish.get("_agent_visual_fallback_reason"):
            payload["_agent_visual_fallback_reason"] = polish.get("_agent_visual_fallback_reason")
    return payload


def build_douyin_copy(candidate: dict[str, Any], polish: dict[str, Any] | None = None) -> dict[str, Any]:
    if polish:
        return {
            "title": sanitize_post(polish["douyin_title"], 55),
            "desc": sanitize_post(polish["douyin_desc"], 600),
            "tags": polish["tags"],
        }
    profile = content_profile(candidate)
    douyin = profile.get("douyin", {})
    title = _public_candidate_title(candidate)
    url = candidate.get("canonical_url") or ""
    manual_scheme = policy_get("subject_inputs.operator_topic.manual_url_scheme", "manual-topic://")
    has_external_url = bool(url and not str(url).startswith(manual_scheme))
    if is_operator_topic(candidate):
        source = _public_operator_source_label(candidate, profile, has_external_url)
    else:
        source = ", ".join(_public_source_label(source_id) for source_id in candidate.get("source_ids") or []) or profile.get("source", "searchpo")
    score = candidate.get("candidate_score")
    desc_lines = _render_template_list(
        douyin.get("desc_lines", []),
        title=title,
        source=source,
        score=score,
        url="",
    )
    return {
        "title": sanitize_post(policy_format(douyin.get("title_template", "{title}"), title=title), 55),
        "desc": sanitize_post("\n".join(desc_lines), 600),
        "tags": douyin.get("tags", []),
    }


def build_claims_ledger(
    candidate: dict[str, Any],
    douyin_copy: dict[str, Any],
    render_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    has_render_payload = render_payload is not None
    render_payload = render_payload or {}
    source_ids = [str(item) for item in candidate.get("source_ids") or [] if str(item).strip()]
    evidence = candidate.get("evidence") or []
    canonical_url = str(candidate.get("canonical_url") or "")
    evidence_url = "" if canonical_url.startswith(policy_get("subject_inputs.operator_topic.manual_url_scheme", "manual-topic://")) else canonical_url
    evidence_hash = (
        candidate.get("raw_sha256")
        or candidate.get("source_snapshot_sha256")
        or (evidence[0].get("raw_sha256") if evidence and isinstance(evidence[0], dict) else None)
        or candidate.get("candidate_id")
    )
    evidence_source = source_ids[0] if source_ids else str(candidate.get("selection_source") or "operator_topic")
    fields: dict[str, Any] = {
        "title": douyin_copy.get("title"),
        "description": douyin_copy.get("desc"),
        "voiceover": render_payload.get("voiceoverText"),
        "cards": render_payload.get("cards") or [],
        "storyboard": storyboard_text_items(render_payload.get("storyboard")),
        "agent_visual": agent_visual_text_items(render_payload.get("agentVisual") or render_payload.get("agent_visual"), render_payload.get("orientation") or "vertical"),
        "tags": douyin_copy.get("tags") or [],
    }
    claims: list[dict[str, Any]] = []

    def add_claim(field: str, value: Any, *, index: int | None = None, claim_type: str = "public_copy") -> None:
        text = sanitize_post(value, 700)
        if not text:
            return
        suffix = "" if index is None else f"_{index:02d}"
        claims.append(
            {
                "id": f"C{len(claims) + 1:03d}",
                "field": f"{field}{suffix}",
                "claim": text,
                "claim_type": claim_type,
                "source_id": evidence_source,
                "evidence_url": evidence_url,
                "evidence_hash": evidence_hash,
                "allowed_reason": "Bounded to selected subject and source evidence; not an external ranking or performance conclusion.",
                "status": "keep",
            }
        )

    add_claim("title", fields["title"], claim_type="platform_title")
    add_claim("description", fields["description"], claim_type="platform_description")
    add_claim("voiceover", fields["voiceover"], claim_type="spoken_copy")
    for index, card in enumerate(fields["cards"], start=1):
        if isinstance(card, dict):
            add_claim("cards", " / ".join(str(card.get(key) or "") for key in ("label", "value", "detail")), index=index)
    for index, scene_text in enumerate(fields["storyboard"], start=1):
        add_claim("storyboard", scene_text, index=index, claim_type="visible_scene_text")
    for index, visual_text in enumerate(fields["agent_visual"], start=1):
        add_claim("agent_visual", visual_text, index=index, claim_type="visible_scene_text")
    for index, tag in enumerate(fields["tags"], start=1):
        add_claim("tags", tag, index=index, claim_type="platform_tag")
    required_fields = ["title", "description", "tags"]
    not_applicable_fields: list[str] = []
    if has_render_payload:
        required_fields.extend(["voiceover", "cards"])
        if fields["storyboard"]:
            required_fields.append("storyboard")
        if fields["agent_visual"]:
            required_fields.append("agent_visual")
    else:
        not_applicable_fields.extend(["voiceover", "cards", "storyboard", "agent_visual"])
    coverage = {
        "required_fields": required_fields,
        "not_applicable_fields": not_applicable_fields,
        "covered_fields": sorted({claim["field"].split("_", 1)[0] for claim in claims}),
    }
    coverage["missing_fields"] = [
        field
        for field in coverage["required_fields"]
        if not any(str(claim.get("field", "")).startswith(field) for claim in claims)
    ]
    return {
        "schema_version": 2,
        "created_at": utc_now(),
        "review_status": "contract-check-pass" if not coverage["missing_fields"] else "fail",
        "selected_candidate_id": candidate.get("candidate_id"),
        "source_boundary": {
            "canonical_url": candidate.get("canonical_url"),
            "source_ids": candidate.get("source_ids") or [],
            "collected_at": candidate.get("collected_at"),
            "evidence": candidate.get("evidence") or [],
            "evidence_hash": evidence_hash,
        },
        "coverage": coverage,
        "claims": claims,
        "unknown_or_unsafe": policy_get("claims.unknown_or_unsafe", []),
    }


def build_content_plan(
    candidate: dict[str, Any],
    evidence_bundle: dict[str, Any] | None = None,
    cross_check_review: dict[str, Any] | None = None,
    fact_bank: dict[str, Any] | None = None,
    research_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = candidate.get("title") or "Searchpo Radar"
    plan = content_profile(candidate).get("plan", {})
    evidence_summary = (evidence_bundle or {}).get("evidence_summary") or {}
    suggested_video_profile = choose_video_profile(candidate, None, evidence_bundle)
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "service": "content",
        "service_chain": [
            "topic_brief",
            "fact_bank",
            "script",
            "scene_plan",
            "video_spec",
            "delivery_package",
            "analytics_feedback",
        ],
        "mode": plan.get("mode", "deterministic_plan"),
        "title": sanitize_post(title, 80),
        "angle": plan.get("angle", ""),
        "evidence_bundle_status": "present" if evidence_bundle else "missing",
        "cross_check_status": (cross_check_review or {}).get("status") or "missing",
        "source_facts": evidence_summary.get("source_facts") or [],
        "constructive_angles": evidence_summary.get("constructive_angles") or [],
        "fact_bank": fact_bank or {},
        "topic_brief": research_brief or evidence_summary.get("research_brief") or {},
        "research_brief": research_brief or evidence_summary.get("research_brief") or {},
        "execution_steps": plan.get("execution_steps", []),
        "gates": plan.get("gates", []),
        "publish_platforms": ["douyin"],
        "suggested_video_profile": suggested_video_profile,
    }


def write_post_artifacts(
    root_dir: Path,
    run_dir: Path,
    candidate: dict[str, Any],
    douyin_copy: dict[str, Any],
    render_payload: dict[str, Any] | None = None,
    evidence_bundle: dict[str, Any] | None = None,
    cross_check_review: dict[str, Any] | None = None,
) -> Path:
    post_dir = run_dir / "post"
    post_dir.mkdir(parents=True, exist_ok=True)
    title = douyin_copy["title"]
    # Enforce Douyin's hashtag limit holistically: catch any #topics the model
    # embedded in the description, merge them with the tags list, then sanitize,
    # de-duplicate and cap (default 5). The previous pipeline shipped raw tags.
    inline_tags, desc = extract_inline_hashtags(douyin_copy["desc"])
    tag_bundle = build_tag_bundle(list(douyin_copy.get("tags") or []) + inline_tags, desc=desc)
    tags = tag_bundle["tags"]
    tags_csv = ",".join(tags)
    hashtags_str = tag_bundle["hashtag_string"]
    expected_video_path = run_dir / "video" / "final.mp4"
    cover_path = run_dir / "cover" / "final.jpg"
    axes = side_effect_axes()
    publish_mode = axes["publish_mode"]
    posting_policy = content_profile(candidate).get("posting", {})
    subject_label = posting_policy.get("subject_label", "Candidate")
    caveat_text = posting_policy.get("caveat", "")
    cross_check = cross_check_review or {}
    evidence_summary = (evidence_bundle or {}).get("evidence_summary") or {}
    cross_check_status = str(cross_check.get("status") or "missing")
    strong_research_errors = strong_research_review_errors(cross_check)
    if strong_research_errors:
        raise RuntimeError("strong research review required before writing post artifacts: " + "; ".join(strong_research_errors))
    source_facts = [str(item) for item in cross_check.get("source_facts") or evidence_summary.get("source_facts") or []]
    constructive_angles = [str(item) for item in cross_check.get("constructive_angles") or evidence_summary.get("constructive_angles") or []]
    normalized_douyin_copy = {"title": title, "desc": desc, "tags": tags}
    distribution_review = {
        "schema_version": 1,
        "created_at": utc_now(),
        **evaluate_douyin_distribution_gate(
            candidate=candidate,
            douyin_copy=normalized_douyin_copy,
            render_payload=render_payload,
            cross_check_review=cross_check_review,
        ),
    }
    live_command = (
        f'cd "{post_dir}" && sau douyin upload-video --account "$DOUYIN_ACCOUNT_NAME" '
        f'--file "{expected_video_path}" --title "$(cat douyin_title.txt)" '
        f'--desc "$(cat douyin_desc.txt)" --tags "$(cat douyin_tags.txt)" --thumbnail "{cover_path}"'
    )
    posting_pack = f"""# Posting Pack

## Evidence Summary

- {subject_label}: {candidate.get('title')}
- Subject ID: `{candidate.get('candidate_id')}`
- Source IDs: `{', '.join(candidate.get('source_ids') or [])}`
- Source URL: {candidate.get('canonical_url') or ''}
- Caveats: {caveat_text}
- Cross-check status: `{cross_check_status}`
- Source facts: {'; '.join(source_facts[:4])}
- Constructive angles: {'; '.join(constructive_angles[:3])}

## Posting Strategy

{policy_get('claims.posting_strategy', 'Lead with the evidence boundary, not hype.')}

## Publish Mode

- execution_profile: `{axes['execution_profile']}`
- render_mode: `{axes['render_mode']}`
- publish_mode: `{axes['publish_mode']}`
- Upload adapter: `dreammis/social-auto-upload`
- Platform: `douyin`
- Live upload requires explicit `SEARCHPO_DOUYIN_LIVE=1` plus a valid `DOUYIN_ACCOUNT_NAME` or `SOCIAL_UPLOAD_ACCOUNT_NAME`.

## Douyin Upload Copy

- Title: {title}
- Tags: {tags_csv}

### Description

{desc}

## Upload Command

```bash
{live_command}
```

The command above is documentation only. The default E2E path does not run a live upload.

## Pre-Flight

- Source URL present.
- No unsupported claim terms from `config/searchpo_policy.json`.
- Cross-check review status is `pass` for contract-check only.
- `runtime/social-auto-upload` has the Douyin CLI contract.
- For live upload: user explicitly enables `SEARCHPO_DOUYIN_LIVE=1`.
"""
    (post_dir / "posting_pack.md").write_text(posting_pack, encoding="utf-8")
    write_json(
        post_dir / "douyin_upload_manifest.json",
        {
            "schema_version": 2,
            "created_at": utc_now(),
            "manifest_status": "pending-artifact-binding",
            "run_id": run_dir.name,
            "selected_candidate_id": candidate.get("candidate_id"),
            "platform": "douyin",
            "adapter": "dreammis/social-auto-upload",
            "execution_profile": axes["execution_profile"],
            "side_effect_tier": axes["side_effect_tier"],
            "cli": "sau douyin upload-video",
            "account_env": ["DOUYIN_ACCOUNT_NAME", "SOCIAL_UPLOAD_ACCOUNT_NAME"],
            "expected_video_path": str(expected_video_path),
            "expected_video_sha256": None,
            "expected_video_bytes": None,
            "cover_path": str(cover_path),
            "cover_sha256": None,
            "render_mode": axes["render_mode"],
            "publish_mode": publish_mode,
            "render_props_sha256": None,
            "render_payload_sha256": sha256_json_file(run_dir / "render_payload.json"),
            "voiceover_sha256": None,
            "captions_sha256": sha256_json_file(run_dir / "captions.json"),
            "title": title,
            "desc": desc,
            "tags": tags,
            "tags_raw": tag_bundle["tags_raw"],
            "hashtag_string": hashtags_str,
            "max_tags": tag_bundle["max_tags"],
            "caption_preview": tag_bundle["caption"],
            "live_upload_default": False,
            "live_upload_gate": "SEARCHPO_DOUYIN_LIVE=1",
            "contract_path": "runtime/social-auto-upload/skills/douyin-upload/references/cli-contract.md",
        },
    )
    (post_dir / "douyin_title.txt").write_text(title + "\n", encoding="utf-8")
    (post_dir / "douyin_desc.txt").write_text(desc + "\n", encoding="utf-8")
    (post_dir / "douyin_tags.txt").write_text(tags_csv + "\n", encoding="utf-8")
    write_json(
        post_dir / "claims_ledger.json",
        build_claims_ledger(candidate, normalized_douyin_copy, render_payload),
    )
    write_json(post_dir / "douyin_distribution_review.json", distribution_review)
    write_json(
        post_dir / "images_manifest.json",
        {
            "schema_version": 2,
            "created_at": utc_now(),
            "cover": {"role": "cover", "path": str(cover_path), "exists": cover_path.is_file()},
            "images": [{"role": "cover", "path": str(cover_path)}],
        },
    )
    if not cross_check_review:
        raise RuntimeError("cross_check_review.json is required before writing post artifacts")
    write_json(post_dir / "cross_check_review.json", cross_check_review)
    cross_check_md = "\n".join(
        [
            "# Cross-Check Review",
            "",
            f"status: {cross_check_status}",
            "",
            "## Source Facts",
            *[f"- {item}" for item in source_facts],
            "",
            "## Constructive Angles",
            *[f"- {item}" for item in constructive_angles],
            "",
            "## Warnings",
            *[f"- {item}" for item in cross_check.get("warnings") or []],
            "",
            "## Errors",
            *[f"- {item}" for item in cross_check.get("errors") or []],
            "",
        ]
    )
    (post_dir / "cross_check_review.md").write_text(cross_check_md, encoding="utf-8")
    (post_dir / "file_manifest.txt").write_text(
        "\n".join(
            [
                "posting_pack.md",
                "douyin_upload_manifest.json",
                "douyin_title.txt",
                "douyin_desc.txt",
                "douyin_tags.txt",
                "claims_ledger.json",
                "douyin_distribution_review.json",
                "cross_check_review.json",
                "images_manifest.json",
                "cross_check_review.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return post_dir


@dataclass(frozen=True)
class LoadShortlistStage:
    name: str = "load_shortlist"
    title: str = "Load subject input"
    owner: str = "data_prep"

    def run(self, context: HarnessContext) -> StageResult:
        path = context.run_dir / "candidate_shortlist.json"
        ensure_subject_pool(context.run_dir)
        if not path.exists():
            raise RuntimeError(f"candidate_shortlist.json missing: {path}")
        data = read_json(path)
        shortlist = data.get("items") or []
        input_mode = data.get("input_mode") or "shortlist"
        context.state["shortlist_data"] = data
        context.state["shortlist"] = shortlist
        context.state["subject_input_mode"] = input_mode
        status = "completed" if shortlist else "failed"
        return StageResult(
            step="observe",
            status=status,
            details=f"Loaded {len(shortlist)} subject candidates from {input_mode}.",
            artifacts=[Artifact("candidate_shortlist", path, {"item_count": len(shortlist), "input_mode": input_mode})],
            gates=[
                Gate(
                    "shortlist_available",
                    "pass" if shortlist else "fail",
                    f"{len(shortlist)} subject candidates available",
                    {"item_count": len(shortlist), "input_mode": input_mode},
                )
            ],
            metadata={"item_count": len(shortlist), "input_mode": input_mode},
        )


@dataclass(frozen=True)
class SelectCandidateStage:
    name: str = "select_candidate"
    title: str = "Select top candidate"
    owner: str = MAIN_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        candidate = select_candidate(context.state.get("shortlist") or [])
        path = context.run_dir / "selected_candidate.json"
        write_json(path, candidate)
        context.state["selected_candidate"] = candidate
        has_boundary = bool(candidate.get("canonical_url")) or is_operator_topic(candidate)
        gate_name = "operator_topic_recorded" if is_operator_topic(candidate) else "candidate_has_url"
        status = "completed" if has_boundary else "failed"
        return StageResult(
            step="select",
            status=status,
            details=f"Selected {candidate['candidate_id']} with score {candidate.get('candidate_score')}.",
            artifacts=[Artifact("selected_candidate", path, {"candidate_id": candidate["candidate_id"]})],
            gates=[
                Gate(
                    gate_name,
                    "pass" if has_boundary else "fail",
                    "Selected subject has a source URL or operator-topic boundary",
                    {"canonical_url": candidate.get("canonical_url"), "input_mode": candidate.get("input_mode") or "shortlist"},
                )
            ],
            metadata={"candidate_id": candidate["candidate_id"]},
        )


@dataclass(frozen=True)
class SubjectEvidenceStage:
    name: str = "subject_evidence"
    title: str = "Fetch subject detail evidence or record research seed"
    owner: str = RESEARCH_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        candidate = context.state["selected_candidate"]
        bundle, review = write_evidence_artifacts(context.run_dir, candidate)
        context.state["evidence_bundle"] = bundle
        context.state["cross_check_review"] = review
        selected_path = context.run_dir / "selected_candidate.json"
        candidate["evidence_bundle_sha256"] = sha256_json_file(context.run_dir / "evidence_bundle.json")
        candidate["cross_check_status"] = review.get("status")
        write_json(selected_path, candidate)
        source_count = int(bundle.get("source_count") or 0)
        seed_only = bundle.get("source_kind") == "operator_topic_seed"
        status_ok = bool(source_count) and (seed_only or review.get("status") == "pass")
        gates = [
            Gate(
                "subject_seed_recorded" if seed_only else "subject_detail_fetched",
                "pass" if source_count else "fail",
                (
                    "Operator topic seed was recorded; independent widesearch is still required"
                    if seed_only
                    else "Detailed subject evidence was fetched from the canonical URL"
                ),
                {"source_count": source_count, "source_kind": bundle.get("source_kind")},
            )
        ]
        if seed_only:
            gates.append(
                Gate(
                    "widesearch_required",
                    "pass",
                    "Topic seed is not external evidence; research enrichment must supply independent sources",
                    {"requires_widesearch": True, "external_evidence": False},
                )
            )
        else:
            gates.append(
                Gate(
                    "cross_check_passed",
                    str(review.get("status") or "fail"),
                    "Cross-check verified the evidence boundary before copy generation",
                    {"errors": review.get("errors") or [], "warnings": review.get("warnings") or []},
                )
            )
        return StageResult(
            step="observe",
            status="completed" if status_ok else "failed",
            details=(
                "Recorded operator topic research seed; widesearch enrichment must provide external evidence."
                if seed_only
                else f"Fetched {source_count} detailed source artifacts and cross-checked content boundary."
            ),
            artifacts=[
                Artifact("evidence_bundle", context.run_dir / "evidence_bundle.json", {"source_count": source_count}),
                Artifact("cross_check_review", context.run_dir / "cross_check_review.json", {"status": review.get("status")}),
            ],
            gates=gates,
            metadata={
                "canonical_url": bundle.get("canonical_url"),
                "source_kind": bundle.get("source_kind"),
                "requires_widesearch": seed_only,
            },
        )


@dataclass(frozen=True)
class ResearchEnrichmentStage:
    name: str = "research_enrichment"
    title: str = "Enrich subject research with AnySearch"
    owner: str = RESEARCH_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        candidate = context.state["selected_candidate"]
        evidence_bundle = context.state.get("evidence_bundle")
        if evidence_bundle is None:
            evidence_bundle = read_json(context.run_dir / "evidence_bundle.json")
        bundle, review, fact_bank, research_brief = run_research_enrichment(context.run_dir, candidate, evidence_bundle)
        context.state["evidence_bundle"] = bundle
        context.state["cross_check_review"] = review
        context.state["fact_bank"] = fact_bank
        context.state["topic_brief"] = research_brief
        context.state["research_brief"] = research_brief
        source_map = _state_or_file(context, "source_map", "source_map.json")
        if source_map:
            context.state["source_map"] = source_map
        selected_path = context.run_dir / "selected_candidate.json"
        candidate["evidence_bundle_sha256"] = sha256_json_file(context.run_dir / "evidence_bundle.json")
        candidate["cross_check_status"] = review.get("status")
        candidate["research_status"] = "pass" if review.get("research_sufficient") else "fail"
        write_json(selected_path, candidate)
        source_count = int(bundle.get("source_count") or 0)
        supplemental_count = int(review.get("supplemental_source_count") or 0)
        hosts = review.get("independent_source_hosts") or []
        strong_research_errors = strong_research_review_errors(review)
        return StageResult(
            step="observe",
            status="completed" if not strong_research_errors else "failed",
            details=(
                f"AnySearch enrichment added {supplemental_count} supplemental sources "
                f"across {len(hosts)} independent hosts."
            ),
            artifacts=[
                Artifact("widesearch_strategy", context.run_dir / "widesearch_strategy.json", {"status": review.get("status")}),
                Artifact("anysearch_research", context.run_dir / "anysearch_research.json", {"status": review.get("status")}),
                Artifact("fact_bank", context.run_dir / "fact_bank.json", {"fact_count": len(fact_bank.get("source_backed_facts") or [])}),
                Artifact("topic_brief", context.run_dir / "topic_brief.json", {"topic": research_brief.get("topic")}),
                Artifact("research_brief", context.run_dir / "research_brief.json", {"topic": research_brief.get("topic")}),
                Artifact("source_map", context.run_dir / "source_map.json", {"source_count": len((source_map or {}).get("sources") or [])}),
                Artifact("evidence_bundle", context.run_dir / "evidence_bundle.json", {"source_count": source_count}),
                Artifact("cross_check_review", context.run_dir / "cross_check_review.json", {"status": review.get("status")}),
            ],
            gates=[
                Gate(
                    "research_enrichment_passed",
                    "pass" if review.get("research_sufficient") else "fail",
                    "Primary source plus AnySearch supplemental extracts met the strong evidence gate",
                    {
                        "supplemental_source_count": supplemental_count,
                        "independent_source_hosts": hosts,
                        "fact_bank_status": review.get("fact_bank_status"),
                    },
                ),
                Gate(
                    "cross_check_passed",
                    "pass" if not strong_research_errors else "fail",
                    "Enriched cross-check verified the source boundary before copy generation",
                    {"errors": [*(review.get("errors") or []), *strong_research_errors], "warnings": review.get("warnings") or []},
                ),
            ],
            metadata={"supplemental_source_count": supplemental_count, "independent_source_hosts": hosts},
        )


@dataclass(frozen=True)
class PlanContentStage:
    name: str = "main_task_plan"
    title: str = "Main agent task plan"
    owner: str = MAIN_AGENT
    include_providers: bool = False

    def run(self, context: HarnessContext) -> StageResult:
        candidate = context.state["selected_candidate"]
        cross_check = context.state.get("cross_check_review")
        if cross_check is None:
            cross_check_path = context.run_dir / "cross_check_review.json"
            cross_check = read_json(cross_check_path) if cross_check_path.exists() else {}
        research_barrier = write_research_barrier(context.run_dir, cross_check)
        context.state["research_barrier"] = research_barrier
        if research_barrier["status"] != "pass":
            raise RuntimeError("research barrier failed: " + "; ".join(research_barrier["errors"]))
        plan = build_content_plan(
            candidate,
            context.state.get("evidence_bundle"),
            cross_check,
            context.state.get("fact_bank"),
            context.state.get("topic_brief") or context.state.get("research_brief"),
        )
        path = context.run_dir / "content_plan.json"
        write_json(path, plan)
        context.state["content_plan"] = plan
        environment_manifest = write_environment_manifest(context.root_dir, context.run_dir)
        context.state["environment_manifest"] = environment_manifest
        analytics_feedback = write_optional_analytics_feedback(context.run_dir, candidate)
        context.state["analytics_feedback"] = analytics_feedback
        axes = side_effect_axes()
        if self.include_providers and axes.get("agent_mode") != "provider":
            axes = side_effect_axes("provider")
        runtime_contract = write_runtime_contract(
            context.run_dir,
            candidate,
            self.include_providers,
            axes=axes,
            content_plan=plan,
            delegation=context.state.get("delegation") if isinstance(context.state.get("delegation"), dict) else None,
        )
        task_plan = runtime_contract
        task_plan_path = context.run_dir / "main_task_plan.json"
        write_json(task_plan_path, task_plan)
        context.state["main_task_plan"] = task_plan
        context.state["runtime_contract"] = runtime_contract
        return StageResult(
            step="plan",
            status="completed",
            details="Main agent assigned impl-agent script tasks and kept source-bounded publish gates.",
            artifacts=[
                Artifact("research_barrier", context.run_dir / RESEARCH_BARRIER_FILENAME, {"status": research_barrier["status"]}),
                Artifact("content_plan", path, {"mode": plan["mode"]}),
                Artifact("environment_manifest", context.run_dir / "environment_manifest.json", {"services": len(environment_manifest.get("service_boundaries") or [])}),
                Artifact("analytics_feedback", context.run_dir / "analytics_feedback.json", {"status": analytics_feedback.get("status")}),
                Artifact("runtime_contract", context.run_dir / RUNTIME_CONTRACT_FILENAME, {"architecture": runtime_contract["architecture"]}),
                Artifact("main_task_plan", task_plan_path, {"state": task_plan["task_plan_state"]}),
            ],
            gates=[
                Gate(
                    "research_barrier",
                    research_barrier["status"],
                    "Research barrier passed; implementation may start from artifact evidence",
                    {
                        "supplemental_source_count": research_barrier["supplemental_source_count"],
                        "independent_source_hosts": research_barrier["independent_source_hosts"],
                        "errors": research_barrier["errors"],
                    },
                ),
                Gate("claim_boundary_defined", "pass", "Plan limits public claims to the selected subject evidence boundary"),
                Gate("task_plan_owned_by_main", "pass", "Main agent owns task-plan state and release gates"),
                Gate("planning_contract_written", "pass", "Planning, delegation, verification, and recovery contracts were written"),
                Gate("service_chain_defined", "pass", "Full-service artifact chain is declared for this run", {"service_chain": plan.get("service_chain")}),
            ],
            metadata={"mode": plan["mode"]},
        )


@dataclass(frozen=True)
class DeepSeekPolishStage:
    name: str = "deepseek_polish"
    title: str = "Run DeepSeek polish script"
    owner: str = IMPL_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        script_result = run_repo_script(context, ["scripts/deepseek_polish.py", str(context.run_dir)], timeout=420)
        path = context.run_dir / "deepseek_polish.json"
        polish = read_json(path)
        context.state["deepseek_polish"] = polish
        status = "completed" if polish.get("status") == "pass" else "failed"
        return StageResult(
            step="act",
            status=status,
            details="DeepSeek polished Douyin copy and Remotion card text with source-bounded constraints.",
            artifacts=[Artifact("deepseek_polish", path, {"model": polish.get("model"), "status": polish.get("status")})],
            gates=[
                Gate(
                    "deepseek_polish_passed",
                    "pass" if status == "completed" else "fail",
                    "DeepSeek output avoided unsupported claim terms",
                    {"unsafe_claim_hits": polish.get("unsafe_claim_hits") or []},
                )
            ],
            metadata=script_result,
        )


@dataclass(frozen=True)
class GeminiTTSStage:
    # The stage keeps its historical name; SEARCHPO_TTS_PROVIDER picks the script that runs.
    name: str = "gemini_tts"
    title: str = "Run TTS script"
    owner: str = IMPL_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        provider = tts_provider()
        script_result = run_repo_script(context, [TTS_SCRIPTS[provider], str(context.run_dir)], timeout=600)
        manifest_path = context.run_dir / "voiceover_manifest.json"
        manifest = read_json(manifest_path)
        audio_path = Path(manifest["audio_path"])
        manifest_errors = voiceover_manifest_errors(manifest, audio_path)
        if manifest.get("provider") != provider:
            manifest_errors.append(f"provider is {manifest.get('provider') or 'missing'}, expected {provider}")
        context.state["voiceover_manifest"] = manifest
        return StageResult(
            step="act",
            status="completed" if not manifest_errors else "failed",
            details=f"{provider.capitalize()} TTS generated the run voiceover audio artifact.",
            artifacts=[
                Artifact("voiceover_manifest", manifest_path, {"model": manifest.get("model"), "voice": manifest.get("voice")}),
                Artifact("voiceover_audio", audio_path, {"mime_type": manifest.get("output_mime_type")}),
            ],
            gates=[
                Gate(
                    "voiceover_generated",
                    "pass" if not manifest_errors else "fail",
                    f"{provider.capitalize()} TTS wrote a hash-bound voiceover.wav",
                    {"errors": manifest_errors},
                )
            ],
            metadata=script_result,
        )


@dataclass(frozen=True)
class BuildCaptionsStage:
    name: str = "build_captions"
    title: str = "Build audio-synced caption timing"
    owner: str = IMPL_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        script_result = run_repo_script(context, ["scripts/build_captions.py", str(context.run_dir)], timeout=240)
        path = context.run_dir / "captions.json"
        audit_path = context.run_dir / "caption_audit.json"
        segment_count = 0
        audit_status = "missing"
        if path.exists():
            data = read_json(path)
            segments = data.get("segments") or []
            segment_count = data.get("segment_count") or len(segments)
            context.state["captions"] = [
                {"text": s["text"], "startFrame": s["start_frame"], "endFrame": s["end_frame"]}
                for s in segments
            ]
        if audit_path.exists():
            audit_status = str(read_json(audit_path).get("status") or "missing")
        return StageResult(
            step="act",
            status="completed" if segment_count and audit_status == "pass" else "failed",
            details=f"Built {segment_count} caption segments locked to the voiceover length.",
            artifacts=[
                artifact
                for artifact in [
                    Artifact("captions", path, {"segment_count": segment_count}) if path.exists() else None,
                    Artifact("caption_audit", audit_path, {"status": audit_status}) if audit_path.exists() else None,
                ]
                if artifact is not None
            ],
            gates=[
                Gate(
                    "captions_built",
                    "pass" if segment_count and audit_status == "pass" else "fail",
                    f"{segment_count} caption segments timed to the real audio",
                    {"caption_audit_status": audit_status},
                )
            ],
            metadata=script_result,
        )


@dataclass(frozen=True)
class ContentScoringStage:
    name: str = "content_scoring"
    title: str = "Score content quality via Gemini"
    owner: str = IMPL_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        script_result = run_repo_script(context, ["scripts/content_scorer.py", str(context.run_dir)], timeout=300)
        path = context.run_dir / "content_score.json"
        if path.exists():
            score_data = read_json(path)
            overall = score_data.get("overall") or 0
            verdict = score_data.get("verdict") or "improve"
        else:
            overall = 0
            verdict = "missing"
        context.state["content_score"] = {"overall": overall, "verdict": verdict}
        gate_status = "pass" if verdict == "pass" else "fail"
        return StageResult(
            step="act",
            status="completed" if gate_status == "pass" else "failed",
            details=f"Content quality score: {overall}/10 ({verdict})",
            artifacts=[Artifact("content_score", path, {"overall": overall, "verdict": verdict})] if path.exists() else [],
            gates=[Gate("content_quality_scored", gate_status, f"Quality {overall}/10: {verdict}", {"overall": overall})],
            metadata=script_result,
        )


@dataclass(frozen=True)
class ContentImproveLoopStage:
    name: str = "content_improvement_loop"
    title: str = "Improve content through Gemini feedback"
    owner: str = IMPL_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        max_attempts = max(1, int(policy_get("content_optimization.max_content_attempts", 3)))
        run_dir = context.run_dir
        optimization_root = run_dir / "optimization" / "content"
        attempts: list[dict[str, Any]] = []
        previous_polish_path: Path | None = None
        previous_score_path: Path | None = None
        final_polish_path: Path | None = None
        final_score_path: Path | None = None
        canonical_polish_path = run_dir / "deepseek_polish.json"
        canonical_score_path = run_dir / "content_score.json"
        failure_reason = ""
        pending_video_feedback = run_dir / "optimization" / "video" / "pending_content_feedback.json"
        external_feedback_used = False

        for attempt in range(1, max_attempts + 1):
            attempt_dir = optimization_root / f"attempt-{attempt:02d}"
            attempt_dir.mkdir(parents=True, exist_ok=True)
            polish_path = attempt_dir / "deepseek_polish.json"
            score_path = attempt_dir / "content_score.json"
            mode = "initial" if attempt == 1 else "revise"
            if attempt == 1 and pending_video_feedback.exists() and canonical_polish_path.exists():
                mode = "revise"
                previous_polish_path = canonical_polish_path
                previous_score_path = pending_video_feedback
                external_feedback_used = True
            polish_args = [
                "scripts/deepseek_polish.py",
                str(run_dir),
                "--mode",
                mode,
                "--attempt",
                str(attempt),
                "--output",
                str(polish_path),
            ]
            if mode == "revise":
                if previous_polish_path is None or previous_score_path is None:
                    raise RuntimeError("content revision requires previous polish and Gemini feedback artifacts")
                polish_args.extend(["--input-polish", str(previous_polish_path), "--feedback", str(previous_score_path)])
            can_reuse_attempt_artifacts = not external_feedback_used
            if polish_path.exists() and can_reuse_attempt_artifacts:
                polish_meta = {
                    "command": "reused existing " + str(polish_path),
                    "returncode": 0,
                    "stdout_tail": "",
                    "stderr_tail": "",
                    "reused_existing_artifact": True,
                }
            else:
                polish_meta = run_repo_script(context, polish_args, timeout=600)

            score_meta: dict[str, Any] | None = None
            score_error: str | None = None
            if score_path.exists() and can_reuse_attempt_artifacts:
                score_meta = {
                    "command": "reused existing " + str(score_path),
                    "returncode": 0,
                    "stdout_tail": "",
                    "stderr_tail": "",
                    "reused_existing_artifact": True,
                }
            else:
                try:
                    score_meta = run_repo_script(
                        context,
                        [
                            "scripts/content_scorer.py",
                            str(run_dir),
                            "--polish",
                            str(polish_path),
                            "--output",
                            str(score_path),
                            "--attempt",
                            str(attempt),
                        ],
                        timeout=360,
                    )
                except RuntimeError as exc:
                    if not score_path.exists():
                        raise
                    score_error = str(exc)[:1000]

            polish = read_json(polish_path)
            score = read_json(score_path)
            verdict = str(score.get("verdict") or "improve")
            overall = float(score.get("overall") or 0)
            target_met = bool(score.get("target_met"))
            eligible_for_revision = bool(score.get("eligible_for_revision"))
            attempt_summary = {
                "attempt": attempt,
                "mode": mode,
                "polish": str(polish_path),
                "score": str(score_path),
                "polish_status": polish.get("status"),
                "overall": overall,
                "verdict": verdict,
                "target_met": target_met,
                "eligible_for_revision": eligible_for_revision,
                "failed_dimensions": score.get("failed_dimensions") or {},
                "suggestions": score.get("suggestions") or [],
                "polish_command": polish_meta,
                "score_command": score_meta,
                "score_error": score_error,
            }
            attempts.append(attempt_summary)

            if polish.get("status") != "pass":
                failure_reason = f"DeepSeek polish attempt {attempt} did not pass"
                break
            if target_met and verdict == "pass":
                final_polish_path = polish_path
                final_score_path = score_path
                break
            if attempt >= max_attempts:
                failure_reason = (
                    f"content quality target not met after {max_attempts} attempts "
                    f"(overall={overall}, verdict={verdict})"
                )
                break
            if eligible_for_revision:
                previous_polish_path = polish_path
                previous_score_path = score_path
                continue
            if verdict == "fail":
                failure_reason = f"Gemini content score failed on attempt {attempt}"
                break
            failure_reason = f"content score {verdict} is not eligible for revision"
            break

        success = final_polish_path is not None and final_score_path is not None
        if success:
            shutil.copyfile(final_polish_path, canonical_polish_path)
            shutil.copyfile(final_score_path, canonical_score_path)
            context.state["deepseek_polish"] = read_json(canonical_polish_path)
            canonical_score = read_json(canonical_score_path)
            context.state["content_score"] = {
                "overall": canonical_score.get("overall") or 0,
                "verdict": canonical_score.get("verdict") or "improve",
                "target_met": canonical_score.get("target_met"),
            }
            topic_brief = _state_or_file(context, "topic_brief", "topic_brief.json") or _state_or_file(context, "research_brief", "research_brief.json")
            fact_bank = _state_or_file(context, "fact_bank", "fact_bank.json")
            selected_candidate = (
                context.state.get("selected_candidate")
                if isinstance(context.state.get("selected_candidate"), dict)
                else _state_or_file(context, "selected_candidate", "selected_candidate.json")
            )
            if not selected_candidate:
                selected_candidate = {
                    "candidate_id": context.state["deepseek_polish"].get("selected_candidate_id"),
                    "title": context.state["deepseek_polish"].get("polished_title") or "Searchpo topic",
                }
            script = build_script_artifact(
                selected_candidate,
                context.state["deepseek_polish"],
                topic_brief,
                fact_bank,
            )
            scene_plan = build_scene_plan_artifact(
                selected_candidate,
                context.state["deepseek_polish"],
                script,
                fact_bank,
            )
            write_json(run_dir / "script.json", script)
            write_json(run_dir / "scene_plan.json", scene_plan)
            context.state["script"] = script
            context.state["scene_plan"] = scene_plan

        summary_path = run_dir / "content_optimization_loop.json"
        summary = {
            "schema_version": 1,
            "created_at": utc_now(),
            "status": "pass" if success else "fail",
            "max_attempts": max_attempts,
            "attempt_count": len(attempts),
            "attempts": attempts,
            "final_polish": str(canonical_polish_path) if success else None,
            "final_score": str(canonical_score_path) if success else None,
            "failure_reason": failure_reason,
            "external_video_feedback_used": external_feedback_used,
            "policy": {
                "target_overall": policy_get("content_optimization.target_overall", 8.0),
                "min_dimension": policy_get("content_optimization.min_dimension", 7.0),
                "improve_requires_revision": policy_get("content_optimization.improve_requires_revision", True),
            },
        }
        write_json(summary_path, summary)
        if success and external_feedback_used and pending_video_feedback.exists():
            consumed_feedback = optimization_root / "consumed_video_feedback.json"
            shutil.copyfile(pending_video_feedback, consumed_feedback)
            pending_video_feedback.unlink()
        final_attempt = attempts[-1] if attempts else {}
        status = "completed" if success else "failed"
        details = (
            f"Content optimization reached target in {len(attempts)} attempt(s): "
            f"overall={final_attempt.get('overall')}, verdict={final_attempt.get('verdict')}"
            if success
            else f"Content optimization failed: {failure_reason}"
        )
        implementation_loop = write_implementation_loop(
            run_dir,
            phase="content_generation",
            status=status,
            owner=self.owner,
            artifacts={
                "content_optimization_loop": str(summary_path),
                "deepseek_polish": str(canonical_polish_path) if success else "",
                "content_score": str(canonical_score_path) if success else "",
                "script": str(run_dir / "script.json") if success else "",
                "scene_plan": str(run_dir / "scene_plan.json") if success else "",
            },
            gates={
                "content_improvement_loop": "pass" if success else "fail",
                "content_quality_target": "pass" if success else "fail",
                "script_scene_plan_written": "pass" if success else "fail",
            },
            errors=[failure_reason] if failure_reason else [],
            metadata={"attempt_count": len(attempts), "max_attempts": max_attempts},
        )
        artifacts = [Artifact("content_optimization_loop", summary_path, {"status": summary["status"]})]
        if success:
            artifacts.extend(
                [
                    Artifact(
                        "deepseek_polish",
                        canonical_polish_path,
                        {"model": context.state["deepseek_polish"].get("model"), "status": context.state["deepseek_polish"].get("status")},
                    ),
                    Artifact(
                        "content_score",
                        canonical_score_path,
                        {"overall": final_attempt.get("overall"), "verdict": final_attempt.get("verdict")},
                    ),
                    Artifact(
                        "script",
                        run_dir / "script.json",
                        {"segment_count": len((context.state.get("script") or {}).get("voiceover_segments") or [])},
                    ),
                    Artifact(
                        "scene_plan",
                        run_dir / "scene_plan.json",
                        {"scene_count": len((context.state.get("scene_plan") or {}).get("scenes") or [])},
                    ),
                ]
            )
        artifacts.append(Artifact("implementation_loop", run_dir / IMPLEMENTATION_LOOP_FILENAME, {"status": implementation_loop["status"]}))
        return StageResult(
            step="act",
            status=status,
            details=details,
            artifacts=artifacts,
            gates=[
                Gate(
                    "content_improvement_loop",
                    "pass" if success else "fail",
                    details,
                    {
                        "attempt_count": len(attempts),
                        "max_attempts": max_attempts,
                        "final_overall": final_attempt.get("overall"),
                        "final_verdict": final_attempt.get("verdict"),
                        "failure_reason": failure_reason,
                    },
                ),
                Gate(
                    "content_quality_target",
                    "pass" if success else "fail",
                    "Gemini content score met optimization policy target" if success else failure_reason,
                    final_attempt,
                ),
                Gate(
                    "script_scene_plan_written",
                    "pass" if success else "fail",
                    "script.json and scene_plan.json were written from the final provider content" if success else failure_reason,
                    {
                        "script": str(run_dir / "script.json") if success else None,
                        "scene_plan": str(run_dir / "scene_plan.json") if success else None,
                    },
                ),
            ],
            metadata={"content_optimization_loop": str(summary_path), "attempt_count": len(attempts)},
        )


@dataclass(frozen=True)
class RenderPayloadStage:
    name: str = "render_payload"
    title: str = "Build Remotion render payload"
    owner: str = IMPL_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        candidate = context.state["selected_candidate"]
        captions = context.state.get("captions")
        if captions is None:
            captions_path = context.run_dir / "captions.json"
            if captions_path.exists():
                captions = _normalize_caption_segments(read_json(captions_path))
        voiceover_manifest = context.state.get("voiceover_manifest")
        if voiceover_manifest is None:
            manifest_path = context.run_dir / "voiceover_manifest.json"
            if manifest_path.exists():
                voiceover_manifest = read_json(manifest_path)
        if voiceover_manifest is None:
            raise RuntimeError("voiceover_manifest.json is required; mock or silent contract audio is not allowed")
        if captions is None:
            raise RuntimeError("captions.json is required; estimated caption fallback is not allowed")
        payload = build_video_payload(
            candidate,
            context.state.get("deepseek_polish"),
            voiceover_manifest,
            captions,
        )
        scene_plan = _state_or_file(context, "scene_plan", "scene_plan.json")
        source_map = _state_or_file(context, "source_map", "source_map.json")
        video_spec = build_video_spec_artifact(context.run_dir, candidate, payload, scene_plan, source_map)
        video_spec_path = context.run_dir / "video_spec.json"
        write_json(video_spec_path, video_spec)
        payload["videoSpec"] = {
            "path": str(video_spec_path),
            "sha256": sha256_json_file(video_spec_path),
            "id": video_spec.get("id"),
            "schema_version": video_spec.get("schema_version"),
        }
        if source_map:
            payload["sourceMap"] = {
                "path": str(context.run_dir / "source_map.json"),
                "sha256": sha256_json_file(context.run_dir / "source_map.json"),
                "source_count": len(source_map.get("sources") or []),
            }
        path = context.run_dir / "render_payload.json"
        write_json(path, payload)
        context.state["render_payload"] = payload
        context.state["video_spec"] = video_spec
        implementation_loop = write_implementation_loop(
            context.run_dir,
            phase="media_contracts",
            status="completed",
            owner=self.owner,
            artifacts={"video_spec": str(video_spec_path), "render_payload": str(path)},
            gates={"video_spec_compiled": "pass", "render_payload_written": "pass"},
        )
        return StageResult(
            step="act",
            status="completed",
            details="Wrote render payload for Remotion public input.",
            artifacts=[
                Artifact("video_spec", video_spec_path, {"scene_count": len(video_spec.get("scenes") or [])}),
                Artifact("render_payload", path, {"title": payload.get("title")}),
                Artifact("implementation_loop", context.run_dir / IMPLEMENTATION_LOOP_FILENAME, {"status": implementation_loop["status"]}),
            ],
            gates=[
                Gate("video_spec_compiled", "pass", "Renderer-neutral video spec was compiled for Remotion", {"video_spec": str(video_spec_path)}),
                Gate("render_payload_written", "pass", "render_payload.json is available"),
            ],
            metadata={"render_payload": str(path), "video_spec": str(video_spec_path)},
        )


@dataclass(frozen=True)
class QualityGateStage:
    name: str = "quality_gate"
    title: str = "Evidence and audio quality gate"
    owner: str = MAIN_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        candidate = context.state["selected_candidate"]
        payload = context.state.get("render_payload")
        if payload is None:
            payload_path = context.run_dir / "render_payload.json"
            if not payload_path.exists():
                raise RuntimeError("render_payload.json is required before quality gate")
            payload = read_json(payload_path)
        voiceover_manifest = context.state.get("voiceover_manifest")
        if voiceover_manifest is None:
            manifest_path = context.run_dir / "voiceover_manifest.json"
            if not manifest_path.exists():
                raise RuntimeError("voiceover_manifest.json is required before quality gate")
            voiceover_manifest = read_json(manifest_path)
        captions = context.state.get("captions")
        if captions is None:
            captions_path = context.run_dir / "captions.json"
            if not captions_path.exists():
                raise RuntimeError("captions.json is required before quality gate")
            captions = _normalize_caption_segments(read_json(captions_path))
        result = {
            "schema_version": 1,
            "created_at": utc_now(),
            **evaluate_quality_gate(
                candidate=candidate,
                render_payload=payload,
                voiceover_manifest=voiceover_manifest,
                captions=captions,
            ),
        }
        path = context.run_dir / "quality_gate.json"
        write_json(path, result)
        status = "completed" if result["status"] == "pass" else "failed"
        details = (
            "Quality gate passed: evidence tone, speech, captions, and public copy are safe."
            if status == "completed"
            else "Quality gate failed: " + "; ".join(result["blocking_issues"])
        )
        return StageResult(
            step="review",
            status=status,
            details=details,
            artifacts=[Artifact("quality_gate", path, {"status": result["status"]})],
            gates=[
                Gate(
                    "quality_gate_passed",
                    result["status"],
                    details,
                    {"blocking_issues": result["blocking_issues"], "warnings": result["warnings"]},
                )
            ],
            metadata={"quality_gate": str(path), "quality_status": result["status"]},
        )


@dataclass(frozen=True)
class PublishPackageStage:
    name: str = "publish_package"
    title: str = "Build Douyin contract-check package"
    owner: str = IMPL_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        candidate = context.state["selected_candidate"]
        douyin_copy = build_douyin_copy(candidate, context.state.get("deepseek_polish"))
        post_dir = write_post_artifacts(
            context.root_dir,
            context.run_dir,
            candidate,
            douyin_copy,
            context.state.get("render_payload"),
            context.state.get("evidence_bundle") or read_json(context.run_dir / "evidence_bundle.json"),
            context.state.get("cross_check_review") or read_json(context.run_dir / "cross_check_review.json"),
        )
        post_manifest_path = context.run_dir / "post_manifest.json"
        write_json(
            post_manifest_path,
            {
                "created_at": utc_now(),
                "post_dir": str(post_dir),
                "posting_pack": str(post_dir / "posting_pack.md"),
            },
        )
        context.state["post_dir"] = post_dir
        claims_ledger = read_json(post_dir / "claims_ledger.json")
        claims_status = str(claims_ledger.get("review_status") or "missing")
        claims_gate_status = "pass" if claims_status == "contract-check-pass" else "fail"
        claims_missing = (claims_ledger.get("coverage") or {}).get("missing_fields") or []
        distribution_review = read_json(post_dir / "douyin_distribution_review.json")
        distribution_status = str(distribution_review.get("status") or "missing")
        status = "completed" if claims_gate_status == "pass" and distribution_status == "pass" else "failed"
        implementation_loop = write_implementation_loop(
            context.run_dir,
            phase="delivery_evidence",
            status=status,
            owner=self.owner,
            artifacts={
                "post_manifest": str(post_manifest_path),
                "claims_ledger": str(post_dir / "claims_ledger.json"),
                "douyin_distribution_review": str(post_dir / "douyin_distribution_review.json"),
            },
            gates={
                "claims_ledger_coverage": claims_gate_status,
                "douyin_distribution_review": distribution_status,
            },
            errors=[*claims_missing, *(distribution_review.get("blocking_issues") or [])],
        )
        return StageResult(
            step="act",
            status=status,
            details="Wrote Douyin upload package, claim ledger, and review artifacts.",
            artifacts=[
                Artifact("post_manifest", post_manifest_path),
                Artifact("posting_pack", post_dir / "posting_pack.md"),
                Artifact("douyin_upload_manifest", post_dir / "douyin_upload_manifest.json"),
                Artifact("claims_ledger", post_dir / "claims_ledger.json"),
                Artifact("douyin_distribution_review", post_dir / "douyin_distribution_review.json"),
                Artifact("cross_check_review", post_dir / "cross_check_review.md"),
                Artifact("implementation_loop", context.run_dir / IMPLEMENTATION_LOOP_FILENAME, {"status": implementation_loop["status"]}),
            ],
            gates=[
                Gate("publish_package_written", "pass", "Run-scoped Douyin package was written"),
                Gate(
                    "claims_ledger_coverage",
                    claims_gate_status,
                    "Claims ledger covers all public copy fields required for this mode",
                    {"review_status": claims_status, "missing_fields": claims_missing},
                ),
                Gate(
                    "douyin_distribution_review",
                    distribution_status,
                    "Douyin recommendation-eligibility and anti-spam review",
                    {
                        "blocking_issues": distribution_review.get("blocking_issues") or [],
                        "warnings": distribution_review.get("warnings") or [],
                    },
                ),
                Gate(
                    "live_publish_disabled_by_default",
                    "pass" if os.environ.get("SEARCHPO_DOUYIN_LIVE") != "1" else "warn",
                    "Live publishing requires explicit live profile and artifact-bound upload manifest",
                    {"live_upload_default": False, **side_effect_axes()},
                ),
            ],
            metadata={"post_dir": str(post_dir)},
        )


def public_content_preflight_text(render_payload: dict[str, Any], polish: dict[str, Any], post_dir: Path) -> str:
    visual = render_payload.get("agentVisual") or render_payload.get("agent_visual") or {}
    if not isinstance(visual, dict):
        visual = {}
    public_render_payload = {
        "title": render_payload.get("title"),
        "displayTitle": render_payload.get("displayTitle"),
        "speechTitle": render_payload.get("speechTitle"),
        "summary": render_payload.get("summary"),
        "metricLine": render_payload.get("metricLine"),
        "audienceMetricLine": render_payload.get("audienceMetricLine"),
        "voiceoverText": render_payload.get("voiceoverText"),
        "cta": render_payload.get("cta"),
        "footer": render_payload.get("footer"),
        "cards": render_payload.get("cards"),
        "storyboard": render_payload.get("storyboard"),
        "premiumDirectorSpec": render_payload.get("premiumDirectorSpec"),
        "agentVisual": {
            "description": visual.get("description"),
            "visible_text": visual.get("visible_text"),
        },
    }
    public_polish = {
        "polished_title": polish.get("polished_title"),
        "voiceover_text": polish.get("voiceover_text"),
        "douyin_title": polish.get("douyin_title"),
        "douyin_desc": polish.get("douyin_desc"),
        "tags": polish.get("tags"),
        "cards": polish.get("cards"),
        "storyboard": polish.get("storyboard"),
        "caveats": polish.get("caveats"),
        "premium_director_spec": polish.get("premium_director_spec"),
    }
    post_texts = []
    for name in ("douyin_title.txt", "douyin_desc.txt", "douyin_tags.txt"):
        path = post_dir / name
        if path.exists():
            post_texts.append(path.read_text(encoding="utf-8"))
    return " ".join(
        [
            json.dumps(public_render_payload, ensure_ascii=False),
            json.dumps(public_polish, ensure_ascii=False),
            *post_texts,
        ]
    )


@dataclass(frozen=True)
class ContentPreflightStage:
    name: str = "content_preflight"
    title: str = "Content preflight gate"
    owner: str = MAIN_AGENT

    def run(self, context: HarnessContext) -> StageResult:
        candidate = context.state["selected_candidate"]
        post_dir = context.state.get("post_dir")
        if post_dir is None:
            post_dir = context.run_dir / "post"
        unsafe_terms = unsupported_terms()
        generated_text = public_content_preflight_text(
            context.state.get("render_payload") or {},
            context.state.get("deepseek_polish") or {},
            Path(post_dir),
        )
        unsafe_hits = [term for term in unsafe_terms if term.lower() in generated_text.lower()]
        cross_check_path = context.run_dir / "cross_check_review.json"
        cross_check = context.state.get("cross_check_review") or (read_json(cross_check_path) if cross_check_path.exists() else {})
        cross_check_status = str(cross_check.get("status") or "missing")
        strong_research_errors = strong_research_review_errors(cross_check)
        distribution_path = post_dir / "douyin_distribution_review.json"
        distribution_review = read_json(distribution_path) if distribution_path.exists() else {}
        distribution_status = str(distribution_review.get("status") or "missing")

        coherence_ok = True
        coherence_issues: list[str] = []
        polish = context.state.get("deepseek_polish") or {}
        if polish:
            candidate_title = _public_candidate_title(candidate).lower()
            polish_title = str(polish.get("polished_title") or "").lower()
            voiceover = str(polish.get("voiceover_text") or "").lower()
            if candidate_title and candidate_title not in polish_title and candidate_title not in voiceover:
                # Split on dots/colons too so a domain-form title (e.g. "mem0.ai", from a
                # bare-link subject) yields the brand token ("mem0") that natural narration uses.
                key_words = [w for w in re.split(r"[\s/\-_.:]+", candidate_title) if len(w) > 3]
                if key_words and not any(w in voiceover for w in key_words):
                    coherence_issues.append("voiceover_text does not reference the selected candidate")
                    coherence_ok = False

        content_score = context.state.get("content_score") or {}
        quality_warning = content_score.get("overall", 10) < 5.0

        all_pass = not unsafe_hits and coherence_ok and not strong_research_errors and distribution_status == "pass"
        canonical_url = str(candidate.get("canonical_url") or "")
        source_url_present = canonical_url.startswith("http://") or canonical_url.startswith("https://")
        review = {
            "schema_version": 2,
            "created_at": utc_now(),
            "status": "pass" if all_pass else "fail",
            "selected_candidate_id": candidate["candidate_id"],
            "checks": {
                "source_url_present": source_url_present,
                "subject_boundary_present": bool(candidate.get("canonical_url")) or is_operator_topic(candidate),
                "unsupported_superlative_hits": unsafe_hits,
                "coherence_ok": coherence_ok,
                "coherence_issues": coherence_issues,
                "content_quality_warning": quality_warning,
                "cross_check_status": cross_check_status,
                "cross_check_errors": [*(cross_check.get("errors") or []), *strong_research_errors],
                "douyin_distribution_status": distribution_status,
                "douyin_distribution_blockers": distribution_review.get("blocking_issues") or [],
                "douyin_distribution_warnings": distribution_review.get("warnings") or [],
                "live_upload_gated": True,
            },
        }
        path = context.run_dir / "content_preflight_review.json"
        write_json(path, review)
        write_json(context.run_dir / "agent_review.json", review)
        details = (
            "Content preflight passed: no unsafe claims, content coherent."
            if all_pass
            else (
                f"Content preflight failed: unsafe={unsafe_hits}, coherence_issues={coherence_issues}, "
                f"douyin_distribution_status={distribution_status}"
            )
        )
        return StageResult(
            step="review",
            status="completed" if all_pass else "failed",
            details=details,
            artifacts=[
                Artifact("content_preflight_review", path, {"status": review["status"]}),
                Artifact("agent_review_compat", context.run_dir / "agent_review.json", {"status": review["status"]}),
            ],
            gates=[
                Gate(
                    "content_preflight_gate",
                    review["status"],
                    details,
                    review["checks"],
                )
            ],
            metadata={"review_status": review["status"]},
        )


def default_stages(include_providers: bool = False) -> list[Any]:
    stages: list[Any] = [
        LoadShortlistStage(),
        SelectCandidateStage(),
        SubjectEvidenceStage(),
        ResearchEnrichmentStage(),
        PlanContentStage(include_providers=include_providers),
    ]
    if include_providers:
        stages.extend([ContentImproveLoopStage(), GeminiTTSStage(), BuildCaptionsStage()])
        stages.extend([RenderPayloadStage(), QualityGateStage(), PublishPackageStage(), ContentPreflightStage()])
    else:
        stages.extend([PublishPackageStage(), ContentPreflightStage()])
    return stages
