from __future__ import annotations

import os
from typing import Any
import json
import re
from urllib.parse import urlparse

from agent_harness.policy import policy_get


ORIENTATION_SPECS: dict[str, dict[str, Any]] = {
    "vertical": {"aspect_ratio": "9:16", "width": 1080, "height": 1920},
    "horizontal": {"aspect_ratio": "16:9", "width": 1920, "height": 1080},
}

MOTIONS = {"calm", "standard", "punchy"}
ANIMATION_STYLES = {"kinetic_text", "diagrammatic", "evidence_cards", "minimal"}
TECHNICAL_WIDE_LAYOUT_TERMS = (
    "github.com",
    "repo",
    "repository",
    "readme",
    "code",
    "source code",
    "architecture",
    "diagram",
    "pipeline",
    "flow",
    "file tree",
    "module",
    "sdk",
    "api",
    "mcp",
    "proxy",
    "diff",
    "table",
    "timeline",
    "benchmark",
    "evaluation",
    "eval",
    "route",
    "router",
    "compressor",
    "cache",
    "agent",
    "claude-code",
    "cursor",
    "context-engineering",
)
VERTICAL_REASON_TERMS = (
    "douyin",
    "phone",
    "mobile",
    "caption",
    "subtitles",
    "人像",
    "手机",
    "抖音",
)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _policy_dict(path: str, default: dict[str, Any]) -> dict[str, Any]:
    value = policy_get(path, default)
    return value if isinstance(value, dict) else default


def _optional_positive_int(value: Any) -> int | None:
    if value in (None, "", False):
        return None
    parsed = _safe_int(value, 0)
    return parsed if parsed > 0 else None


def _force_vertical_video() -> bool:
    value = str(os.environ.get("SEARCHPO_FORCE_VERTICAL_VIDEO") or policy_get("video_profile.force_vertical", False)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _respect_provider_orientation() -> bool:
    value = str(os.environ.get("SEARCHPO_RESPECT_PROVIDER_ORIENTATION") or policy_get("video_profile.respect_provider_orientation", False)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _explicit_orientation_env() -> str:
    return str(os.environ.get("SEARCHPO_VIDEO_ORIENTATION") or "").strip().lower()


def _bound_duration(value: int, min_seconds: int, max_seconds: int | None) -> int:
    bounded = max(min_seconds, value)
    if max_seconds is not None:
        return min(bounded, max_seconds)
    return bounded


def _candidate_host(candidate: dict[str, Any] | None) -> str:
    url = str((candidate or {}).get("canonical_url") or "")
    return urlparse(url).netloc.lower()


def _profile_context_text(
    candidate: dict[str, Any] | None = None,
    content_plan: dict[str, Any] | None = None,
    evidence_bundle: dict[str, Any] | None = None,
) -> str:
    chunks: list[Any] = []
    candidate = candidate or {}
    content_plan = content_plan or {}
    evidence_bundle = evidence_bundle or {}
    chunks.extend(
        [
            candidate.get("title"),
            candidate.get("canonical_url"),
            candidate.get("summary"),
            candidate.get("entity_key"),
            candidate.get("signals"),
            content_plan.get("title"),
            content_plan.get("angle"),
            content_plan.get("source_facts"),
            content_plan.get("constructive_angles"),
            content_plan.get("repo_context"),
            content_plan.get("fact_bank"),
            content_plan.get("source_map"),
            (evidence_bundle.get("evidence_summary") or {}).get("source_facts"),
            (evidence_bundle.get("evidence_summary") or {}).get("constructive_angles"),
        ]
    )
    try:
        return json.dumps(chunks, ensure_ascii=False).lower()
    except TypeError:
        return " ".join(str(chunk) for chunk in chunks).lower()


def _has_wide_technical_layout_signal(
    candidate: dict[str, Any] | None = None,
    content_plan: dict[str, Any] | None = None,
    evidence_bundle: dict[str, Any] | None = None,
) -> bool:
    host = _candidate_host(candidate)
    signals = (candidate or {}).get("signals") if isinstance((candidate or {}).get("signals"), dict) else {}
    if "github.com" in host or signals.get("has_code_signal"):
        return True
    text = _profile_context_text(candidate, content_plan, evidence_bundle)
    hits = sum(1 for term in TECHNICAL_WIDE_LAYOUT_TERMS if term in text)
    has_file_path = bool(re.search(r"\b[\w.-]+(?:/[\w.-]+){0,4}\.(?:py|ts|tsx|js|jsx|go|rs|java|md|json|ya?ml|toml)\b", text, re.I))
    return hits >= 3 or has_file_path


def _provider_vertical_reason_is_strong(data: dict[str, Any]) -> bool:
    reason = str(data.get("decision_reason") or data.get("reason") or "").lower()
    return bool(reason and any(term in reason for term in VERTICAL_REASON_TERMS))


def _prefer_horizontal_orientation(
    content_depth: str,
    candidate: dict[str, Any] | None = None,
    content_plan: dict[str, Any] | None = None,
    evidence_bundle: dict[str, Any] | None = None,
) -> bool:
    if _force_vertical_video():
        return False
    if content_depth == "open_source_repo_explainer":
        return _has_wide_technical_layout_signal(candidate, content_plan, evidence_bundle)
    if content_depth == "source_explainer":
        return _has_wide_technical_layout_signal(candidate, content_plan, evidence_bundle)
    return False


def classify_content_depth(
    candidate: dict[str, Any] | None = None,
    content_plan: dict[str, Any] | None = None,
    evidence_bundle: dict[str, Any] | None = None,
) -> str:
    candidate = candidate or {}
    content_plan = content_plan or {}
    evidence_summary = (evidence_bundle or {}).get("evidence_summary") or {}
    host = _candidate_host(candidate)
    signals = candidate.get("signals") if isinstance(candidate.get("signals"), dict) else {}
    source_facts = content_plan.get("source_facts") or evidence_summary.get("source_facts") or []
    constructive_angles = content_plan.get("constructive_angles") or evidence_summary.get("constructive_angles") or []

    if "github.com" in host or signals.get("has_code_signal"):
        return "open_source_repo_explainer"
    if len(source_facts) >= 3 and len(constructive_angles) >= 2:
        return "source_explainer"
    if candidate.get("input_mode") == "operator_topic" or candidate.get("selection_source") == "operator_topic":
        return "topic_explainer"
    return "radar_signal"


def _default_duration_seconds(content_depth: str) -> int:
    defaults = _policy_dict(
        "video_profile.duration_seconds",
        {
            "radar_signal": 24,
            "topic_explainer": 45,
            "source_explainer": 55,
            "open_source_repo_explainer": 70,
        },
    )
    return _safe_int(defaults.get(content_depth), _safe_int(defaults.get("radar_signal"), 24))


def _default_orientation(content_depth: str) -> str:
    defaults = _policy_dict(
        "video_profile.orientation",
        {
            "radar_signal": "vertical",
            "topic_explainer": "vertical",
            "source_explainer": "vertical",
            "open_source_repo_explainer": "horizontal",
        },
    )
    orientation = str(defaults.get(content_depth) or defaults.get("radar_signal") or "vertical")
    return orientation if orientation in ORIENTATION_SPECS else "vertical"


def _duration_from_env(fps: int = 30) -> int | None:
    seconds = os.environ.get("SEARCHPO_VIDEO_SECONDS")
    if seconds:
        return _safe_int(seconds, 0) or None
    frames = os.environ.get("SEARCHPO_DURATION_FRAMES")
    if frames:
        frame_count = _safe_int(frames, 0)
        return max(1, round(frame_count / max(1, fps))) if frame_count else None
    return None


def choose_video_profile(
    candidate: dict[str, Any] | None = None,
    content_plan: dict[str, Any] | None = None,
    evidence_bundle: dict[str, Any] | None = None,
    *,
    fps: int = 30,
) -> dict[str, Any]:
    content_depth = classify_content_depth(candidate, content_plan, evidence_bundle)
    min_seconds = _safe_int(policy_get("video_profile.min_duration_seconds", 18), 18)
    max_seconds = _optional_positive_int(policy_get("video_profile.max_duration_seconds", None))
    duration_seconds = _duration_from_env(fps=fps) or _default_duration_seconds(content_depth)
    explicit_orientation = _explicit_orientation_env()
    orientation = explicit_orientation or _default_orientation(content_depth)
    if not explicit_orientation and _prefer_horizontal_orientation(content_depth, candidate, content_plan, evidence_bundle):
        orientation = "horizontal"
    if orientation not in ORIENTATION_SPECS:
        orientation = _default_orientation(content_depth)
    motion_defaults = _policy_dict(
        "video_profile.motion",
        {
            "radar_signal": "punchy",
            "topic_explainer": "standard",
            "source_explainer": "standard",
            "open_source_repo_explainer": "standard",
        },
    )
    animation_defaults = _policy_dict(
        "video_profile.animation_style",
        {
            "radar_signal": "kinetic_text",
            "topic_explainer": "evidence_cards",
            "source_explainer": "evidence_cards",
            "open_source_repo_explainer": "diagrammatic",
        },
    )
    spec = ORIENTATION_SPECS[orientation]
    return {
        "schema_version": 1,
        "source": "agent_fallback",
        "content_depth": content_depth,
        "duration_seconds": _bound_duration(duration_seconds, min_seconds, max_seconds),
        "orientation": orientation,
        "aspect_ratio": spec["aspect_ratio"],
        "width": spec["width"],
        "height": spec["height"],
        "motion": str(motion_defaults.get(content_depth) or "standard")
        if str(motion_defaults.get(content_depth) or "standard") in MOTIONS
        else "standard",
        "animation_style": str(animation_defaults.get(content_depth) or "evidence_cards")
        if str(animation_defaults.get(content_depth) or "evidence_cards") in ANIMATION_STYLES
        else "evidence_cards",
        "decision_reason": (
            f"{content_depth} profile selected from source type and evidence depth"
            + ("; horizontal canvas selected for code/architecture/layout density" if orientation == "horizontal" else "")
        ),
    }


def normalize_video_profile(raw: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    base = dict(fallback or choose_video_profile())
    data = raw if isinstance(raw, dict) else {}
    min_seconds = _safe_int(policy_get("video_profile.min_duration_seconds", 18), 18)
    max_seconds = _optional_positive_int(policy_get("video_profile.max_duration_seconds", None))

    explicit_orientation = _explicit_orientation_env()
    orientation = str(data.get("orientation") or base.get("orientation") or "vertical").lower()
    aspect_ratio = str(data.get("aspect_ratio") or data.get("aspectRatio") or "")
    if aspect_ratio == "16:9":
        orientation = "horizontal"
    elif aspect_ratio == "9:16":
        orientation = "vertical"
    if orientation == "horizontal" and _force_vertical_video():
        orientation = "vertical"
    content_depth = str(data.get("content_depth") or data.get("contentDepth") or base.get("content_depth") or "radar_signal")
    coerced_horizontal = False
    if (
        orientation == "vertical"
        and not explicit_orientation
        and not _respect_provider_orientation()
        and not _force_vertical_video()
        and str(base.get("orientation") or "") == "horizontal"
        and content_depth in {"open_source_repo_explainer", "source_explainer"}
        and not _provider_vertical_reason_is_strong(data)
    ):
        orientation = "horizontal"
        coerced_horizontal = True
    if orientation not in ORIENTATION_SPECS:
        orientation = str(base.get("orientation") or "vertical")
    if orientation not in ORIENTATION_SPECS:
        orientation = "vertical"
    spec = ORIENTATION_SPECS[orientation]

    duration_seconds = _safe_int(
        data.get("duration_seconds") or data.get("target_duration_seconds") or data.get("durationSeconds"),
        _safe_int(base.get("duration_seconds"), 24),
    )
    motion = str(data.get("motion") or base.get("motion") or "standard")
    animation_style = str(data.get("animation_style") or data.get("animationStyle") or base.get("animation_style") or "evidence_cards")
    decision_reason = str(data.get("decision_reason") or data.get("reason") or base.get("decision_reason") or "").strip()
    if coerced_horizontal:
        decision_reason = (decision_reason + "; " if decision_reason else "") + "normalized to horizontal for code/architecture layout density"
    return {
        "schema_version": 1,
        "source": "provider" if data else base.get("source", "agent_fallback"),
        "content_depth": content_depth,
        "duration_seconds": _bound_duration(duration_seconds, min_seconds, max_seconds),
        "orientation": orientation,
        "aspect_ratio": spec["aspect_ratio"],
        "width": spec["width"],
        "height": spec["height"],
        "motion": motion if motion in MOTIONS else str(base.get("motion") or "standard"),
        "animation_style": animation_style if animation_style in ANIMATION_STYLES else str(base.get("animation_style") or "evidence_cards"),
        "decision_reason": decision_reason[:220],
    }
