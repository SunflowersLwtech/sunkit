from __future__ import annotations

import re
from typing import Any


RENDER_MODES = {"full_canvas", "overlay"}
MAX_COMPONENT_CHARS = 12000
MAX_CSS_CHARS = 6000
MAX_DESCRIPTION_CHARS = 400

BLOCKED_CODE_PATTERNS = [
    r"^\s*import\b",
    r"\bexport\s+",
    r"\bfetch\s*\(",
    r"\bXMLHttpRequest\b",
    r"\bimport\s*\(",
    r"\brequire\s*\(",
    r"\bprocess\s*\.",
    r"\blocalStorage\b",
    r"\bsessionStorage\b",
    r"\bdocument\s*\.\s*cookie\b",
    r"\bwindow\s*\.\s*location\b",
    r"\beval\s*\(",
]

BLOCKED_CSS_PATTERNS = [
    r"@import\b",
    r"url\s*\(\s*['\"]?\s*(?:https?:)?//",
    r"<\s*script\b",
]


def _clean_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _raw_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit]


def _violations(value: str, patterns: list[str]) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, value, re.I | re.M)]


def disabled_agent_visual(reason: str = "not provided") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "enabled": False,
        "mode": "react_runtime",
        "render_mode": "full_canvas",
        "component_code": "",
        "css": "",
        "description": "",
        "validation_errors": [reason] if reason else [],
    }


def normalize_agent_visual(value: Any) -> dict[str, Any]:
    """Normalize provider-authored React/CSS visual code.

    This is intentionally a render-time escape hatch, not a public web sandbox.
    It allows topic-specific React/CSS while blocking network/import/process
    access so Remotion renders stay reproducible and secret-free.
    """

    if not isinstance(value, dict):
        return disabled_agent_visual()
    component_code = _raw_text(
        value.get("component_code") or value.get("react_code") or value.get("component") or value.get("tsx"),
        MAX_COMPONENT_CHARS + 1,
    )
    css = _raw_text(value.get("css") or value.get("style") or "", MAX_CSS_CHARS + 1)
    render_mode = str(value.get("render_mode") or "full_canvas")
    if render_mode not in RENDER_MODES:
        render_mode = "full_canvas"

    errors: list[str] = []
    if component_code and len(component_code) > MAX_COMPONENT_CHARS:
        errors.append(f"component_code exceeds {MAX_COMPONENT_CHARS} chars")
        component_code = ""
    if css and len(css) > MAX_CSS_CHARS:
        errors.append(f"css exceeds {MAX_CSS_CHARS} chars")
        css = ""
    code_violations = _violations(component_code, BLOCKED_CODE_PATTERNS)
    if code_violations:
        errors.append("component_code uses blocked runtime capability")
        component_code = ""
    css_violations = _violations(css, BLOCKED_CSS_PATTERNS)
    if css_violations:
        errors.append("css uses blocked remote/script capability")
        css = ""

    requested_enabled = bool(value.get("enabled", True))
    enabled = requested_enabled and bool(component_code) and not errors
    if requested_enabled and "return" not in component_code and not errors:
        errors.append("component_code must be a React component function body with a return statement")
        component_code = ""
    if requested_enabled and not component_code and not errors:
        errors.append("component_code is empty")
    return {
        "schema_version": 1,
        "enabled": enabled,
        "mode": "react_runtime",
        "render_mode": render_mode,
        "component_code": component_code if enabled else "",
        "css": css if enabled else "",
        "description": _clean_text(value.get("description") or value.get("notes") or "", MAX_DESCRIPTION_CHARS),
        "validation_errors": errors,
    }


def require_agent_visual(value: Any) -> dict[str, Any]:
    visual = normalize_agent_visual(value)
    if not visual.get("enabled"):
        errors = "; ".join(str(item) for item in visual.get("validation_errors") or [] if str(item).strip())
        raise ValueError(f"agent_visual is required and must contain valid custom React/CSS: {errors or 'missing'}")
    return visual


def agent_visual_text_items(value: Any) -> list[str]:
    visual = normalize_agent_visual(value)
    items = [visual.get("description") or ""]
    if visual.get("enabled"):
        items.append(visual.get("component_code") or "")
    return [str(item) for item in items if str(item or "").strip()]
