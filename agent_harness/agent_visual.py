from __future__ import annotations

import json
import re
from typing import Any


RENDER_MODES = {"full_canvas", "overlay"}
MAX_COMPONENT_CHARS = 12000
MAX_CSS_CHARS = 6000
MAX_DESCRIPTION_CHARS = 400
MAX_MODULE_CHARS = 24000

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

BLOCKED_MODULE_PATTERNS = [
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


def _compact_visible_text(values: list[Any], *, limit: int = 120, max_items: int = 32) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value, limit)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(text)
        if len(rows) >= max_items:
            break
    return rows


def _premium_spec_from_module(module_code: str) -> dict[str, Any]:
    match = re.search(r"const\s+premiumDirectorSpec\s*=\s*(\{.*?\});\s*\n", module_code, re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _premium_visible_text_from_spec(spec: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    arc = spec.get("knowledge_arc") if isinstance(spec.get("knowledge_arc"), dict) else {}
    for key in (
        "hook",
        "mechanism",
        "architecture_position",
        "practical_fit",
        "tradeoff",
        "failure_boundary",
        "judgment_framework",
        "takeaway",
    ):
        values.append(arc.get(key))
    for item in spec.get("topic_objects") or []:
        if isinstance(item, dict):
            values.extend([item.get("label"), item.get("detail")])
    for scene in spec.get("visual_scenes") or []:
        if isinstance(scene, dict):
            values.extend([scene.get("title"), scene.get("objective")])
    return _compact_visible_text(values, limit=140, max_items=40)


def premium_visible_text_items(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    raw_visible = value.get("visible_text") or value.get("visibleText")
    if isinstance(raw_visible, list):
        return _compact_visible_text(raw_visible, limit=140, max_items=40)
    spec = value.get("premium_director_spec") or value.get("premiumDirectorSpec")
    if isinstance(spec, dict):
        return _premium_visible_text_from_spec(spec)
    module_code = str(value.get("module_code") or value.get("moduleCode") or "")
    if module_code:
        return _premium_visible_text_from_spec(_premium_spec_from_module(module_code))
    return []


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
    module_code = _raw_text(value.get("module_code") or value.get("moduleCode") or "", MAX_MODULE_CHARS + 1)
    component_code = _raw_text(
        value.get("component_code") or value.get("react_code") or value.get("component") or value.get("tsx"),
        MAX_COMPONENT_CHARS + 1,
    )
    css = _raw_text(value.get("css") or value.get("style") or "", MAX_CSS_CHARS + 1)
    render_mode = str(value.get("render_mode") or "full_canvas")
    if render_mode not in RENDER_MODES:
        render_mode = "full_canvas"

    errors: list[str] = []
    module_enabled = False
    if module_code:
        if len(module_code) > MAX_MODULE_CHARS:
            errors.append(f"module_code exceeds {MAX_MODULE_CHARS} chars")
            module_code = ""
        elif str(value.get("source") or "") != "premium_director_compiler":
            errors.append("module_code is only accepted from the premium director compiler")
            module_code = ""
        elif "PremiumDirectorVisual" not in module_code or "AgentVisualGenerated" not in module_code:
            errors.append("module_code must compile the PremiumDirectorVisual entrypoint")
            module_code = ""
        else:
            allowed_imports = (
                "import React from 'react';",
                'import React from "react";',
                "import type {AgentVisualProps} from '../AgentVisualTypes';",
                'import type {AgentVisualProps} from "../AgentVisualTypes";',
                "import {PremiumDirectorVisual} from '../premium/PremiumDirectorVisual';",
                'import {PremiumDirectorVisual} from "../premium/PremiumDirectorVisual";',
                "import './agent-visual.generated.css';",
                'import "./agent-visual.generated.css";',
            )
            unexpected_imports = [
                line.strip()
                for line in module_code.splitlines()
                if line.strip().startswith("import ") and line.strip() not in allowed_imports
            ]
            if unexpected_imports:
                errors.append("module_code contains unexpected import statements")
                module_code = ""
                module_enabled = False
                unexpected_imports = []
            module_violations = _violations(module_code, BLOCKED_MODULE_PATTERNS)
            if module_violations:
                errors.append("module_code uses blocked runtime capability")
                module_code = ""
            else:
                module_enabled = True
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
    enabled = requested_enabled and bool(component_code or module_code) and not errors
    if requested_enabled and component_code and "return" not in component_code and not errors:
        errors.append("component_code must be a React component function body with a return statement")
        component_code = ""
    if requested_enabled and not component_code and not module_enabled and not errors:
        errors.append("component_code is empty")
    return {
        "schema_version": 1,
        "enabled": enabled,
        "mode": "react_runtime",
        "render_mode": render_mode,
        "component_code": component_code if enabled and not module_enabled else "",
        "module_code": module_code if enabled and module_enabled else "",
        "css": css if enabled else "",
        "description": _clean_text(value.get("description") or value.get("notes") or "", MAX_DESCRIPTION_CHARS),
        "validation_errors": errors,
        "source": _clean_text(value.get("source") or "", 80),
        "recipe_scene_count": value.get("recipe_scene_count"),
        "visible_text": premium_visible_text_items(value) if module_enabled else _compact_visible_text(value.get("visible_text") or [], limit=140, max_items=40),
    }


def require_agent_visual(value: Any) -> dict[str, Any]:
    visual = normalize_agent_visual(value)
    if not visual.get("enabled"):
        errors = "; ".join(str(item) for item in visual.get("validation_errors") or [] if str(item).strip())
        raise ValueError(f"agent_visual is required and must contain valid custom React/CSS: {errors or 'missing'}")
    return visual


def agent_visual_text_items(value: Any) -> list[str]:
    visual = normalize_agent_visual(value)
    if visual.get("source") == "premium_director_compiler":
        return [str(item) for item in visual.get("visible_text") or [] if str(item or "").strip()]
    items = [visual.get("description") or ""]
    if visual.get("enabled"):
        items.append(visual.get("component_code") or visual.get("module_code") or "")
    return [str(item) for item in items if str(item or "").strip()]
