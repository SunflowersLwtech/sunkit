from __future__ import annotations

import re
from typing import Any


RENDER_MODES = {"full_canvas", "overlay"}
MAX_COMPONENT_CHARS = 60000
MAX_MODULE_CHARS = 180000
MAX_CSS_CHARS = 24000
MAX_DESCRIPTION_CHARS = 400
MIN_BACKGROUND_LUMA = 32

BLOCKED_CODE_PATTERNS = [
    # The visual can now be a full Remotion/React module. Keep only the
    # boundaries that protect local secrets, persistent browser state, and host
    # filesystem/process access.
    r"\bprocess\s*\.\s*env\b",
    r"\b(?:fs|node:fs|child_process|node:child_process)\b",
    r"\b(?:exec|execSync|spawn|spawnSync)\s*\(",
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

RISKY_LAYOUT_PATTERNS = [
    (r"\bthis\b", "agent_visual must use provided variables directly, not destructure from this"),
    (r"index\s*\*\s*18", "agent_visual motion must persist through the full video, not only reveal in the opening seconds"),
    (r"\bdata\s*\.\s*captions\b", "agent_visual must not render its own captions; global captions are overlaid separately"),
    (r"\bcaptions\b", "agent_visual must not access captions; global captions are overlaid separately"),
    (r"\bcurrentCaption\b", "agent_visual must not render its own captions; global captions are overlaid separately"),
    (r"\bdata\s*\.\s*cards\b", "agent_visual must not rely on compatibility cards as the main visual surface; author topic-specific flow/chart/terminal/code visuals"),
    (r"\bsafeCards\b", "agent_visual must not rely on compatibility cards as the main visual surface; author topic-specific flow/chart/terminal/code visuals"),
    (r"agent[-_]visual[-_]caption", "agent_visual must not create a second caption overlay"),
    (r"\bclass(?:Name)?\s*=\s*['\"][^'\"]*(?:caption|subtitle)[^'\"]*['\"]", "agent_visual must not create caption/subtitle overlay classes"),
    (r"\.[^{;\n]*(?:caption|subtitle)[^{;\n]*\{", "agent_visual css must not create caption/subtitle overlay classes"),
    (r"\bdata\s*\.\s*summary\b", "agent_visual must not render full data.summary; use bounded card or metric text"),
    (r"\bdata\s*\.\s*evidenceLevel\b", "agent_visual must not expose internal evidence metadata; render public-safe evidence copy"),
    (r"operator[_ -]?topic|source[-_ ]bounded", "agent_visual must not expose internal evidence metadata; render public-safe evidence copy"),
]

MOTION_COMFORT_PATTERNS = [
    (r"@keyframes\b|\banimation\s*:", "agent_visual must use Remotion frame-driven motion, not CSS keyframe animation"),
    (r"\btransition\s*:", "agent_visual must not rely on CSS transition timing"),
    (r"\bScreenShake\b|\bGlitchFlash\b", "agent_visual must not use shake, glitch, strobe, or flash effects"),
    (r"strokeDashoffset\s*=\s*\{\s*-?\s*frame\s*\*", "agent_visual must not run continuous high-contrast stroke dash sweeps from raw frame speed"),
    (r"rotate\s*\(\s*\$\{\s*frame\s*\*", "agent_visual must not use whole-video continuous rotation as a primary motion system"),
    (r"rotate\s*\(\s*\$\{\s*Math\.sin\s*\(\s*frame\s*/\s*(?:[1-9]|1[0-5])", "agent_visual must not rotate readable objects at high frequency"),
]

MOTION_COLLECTION_NAMES = (
    "flowPackets",
    "streamPackets",
    "orbitPackets",
    "gridDots",
    "nodeGrid",
    "particles",
    "sparkles",
    "rays",
    "lanes",
)


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


def _normalize_provider_module_code(value: str) -> str:
    """Repair provider-minified TSX modules without changing their semantics.

    DeepSeek sometimes compresses a full module to one line starting with
    `// @ts-nocheck import ...`. In TSX that comments out the entire module, so
    Remotion imports `AgentVisualGenerated` as undefined and React throws #130.
    """

    text = value.strip()
    if not text:
        return ""
    text = re.sub(
        r"^(\s*//\s*@ts-(?:no)?check)\s+(?=(?:import|export)\b)",
        r"\1\n",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"^(\s*//\s*@ts-ignore)\s+(?=(?:import|export)\b)",
        r"\1\n",
        text,
        flags=re.I,
    )
    return text


def _strip_line_comments_for_export_scan(value: str) -> str:
    return "\n".join(line for line in value.splitlines() if not line.lstrip().startswith("//"))


def _violations(value: str, patterns: list[str]) -> list[str]:
    return [pattern for pattern in patterns if re.search(pattern, value, re.I | re.M)]


def _hex_luma(value: str) -> float | None:
    color = value.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(ch * 2 for ch in color)
    if len(color) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", color):
        return None
    red = int(color[0:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _near_black_background_errors(value: str) -> list[str]:
    errors: list[str] = []
    background_color_pattern = re.compile(
        r"\bbackground(?:Color)?\b\s*[:=]\s*['\"]?(#[0-9a-fA-F]{3,6}|black|rgb\s*\(\s*0\s*,\s*0\s*,\s*0\s*\))",
        re.I,
    )
    for match in background_color_pattern.finditer(value):
        color = match.group(1)
        luma = 0 if color.lower() in {"black", "rgb(0,0,0)"} or color.lower().startswith("rgb") else _hex_luma(color)
        if luma is not None and luma < MIN_BACKGROUND_LUMA:
            errors.append("full-canvas background is too close to black for black-frame audit")
            break
    return errors


def agent_visual_layout_errors(component_code: str, css: str = "", orientation: str = "vertical") -> list[str]:
    joined = f"{component_code}\n{css}"
    errors: list[str] = []
    for pattern, message in RISKY_LAYOUT_PATTERNS:
        if re.search(pattern, joined, re.I | re.M):
            errors.append(message)
    errors.extend(agent_visual_motion_comfort_errors(component_code, css, orientation))

    errors.extend(_near_black_background_errors(joined))
    return sorted(set(errors))


def _declared_array_length(source: str, name: str) -> int | None:
    patterns = [
        rf"\b{name}\b[^=]*=\s*useMemo\s*\(\s*\(\s*\)\s*=>\s*Array\.from\s*\(\s*\{{\s*length\s*:\s*(\d+)\s*\}}",
        rf"\b{name}\b[^=]*=\s*Array\.from\s*\(\s*\{{\s*length\s*:\s*(\d+)\s*\}}",
    ]
    for pattern in patterns:
        match = re.search(pattern, source, re.I | re.S)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None


def _moving_collection_hits(source: str) -> list[str]:
    hits: list[str] = []
    for name in MOTION_COLLECTION_NAMES:
        if not re.search(rf"\b{name}\b", source):
            continue
        length = _declared_array_length(source, name)
        escaped = re.escape(name)
        map_pattern = rf"\b{escaped}\s*\.\s*map\s*\((.*?)\)\s*(?:\}}|\)|;)"
        bodies = [match.group(1) for match in re.finditer(map_pattern, source, re.I | re.S)]
        body = "\n".join(bodies) if bodies else source
        frame_driven = re.search(r"\bframe\b|\baudioPulse\b|\bMath\.sin\b|\bMath\.cos\b|\bstrokeDashoffset\b", body)
        moves_geometry = re.search(r"\btransform\b|\bcx\s*=|\bcy\s*=|\bx\s*=|\by\s*=|\bstrokeDashoffset\b|\bfilter\s*=", body)
        if frame_driven and moves_geometry:
            label = name
            if length is not None:
                label = f"{name}[{length}]"
            hits.append(label)
    return hits


def _max_numeric_scale(source: str) -> float:
    values: list[float] = []
    for match in re.finditer(r"scale\s*\(\s*\$\{[^}]*(?:\+|\[)\s*([0-9]+(?:\.[0-9]+)?)", source, re.I):
        try:
            values.append(float(match.group(1)))
        except ValueError:
            pass
    for match in re.finditer(r"\[\s*1\s*,\s*(1\.[0-9]+)\s*\]", source):
        try:
            values.append(float(match.group(1)))
        except ValueError:
            pass
    return max(values or [1.0])


def agent_visual_motion_comfort_errors(component_code: str, css: str = "", orientation: str = "vertical") -> list[str]:
    """Reject motion patterns that are technically valid but uncomfortable.

    The render can be visually ambitious, but it needs a director: one primary
    focal action, restrained secondary motion, and no whole-video orbit/swarm.
    """

    joined = f"{component_code}\n{css}"
    errors: list[str] = []
    for pattern, message in MOTION_COMFORT_PATTERNS:
        if re.search(pattern, joined, re.I | re.M):
            errors.append(f"motion comfort violation: {message}")

    moving_collections = _moving_collection_hits(joined)
    if len(moving_collections) > 3:
        errors.append(
            "motion comfort violation: too many simultaneous animated collections "
            f"({', '.join(moving_collections[:6])})"
        )
    for hit in moving_collections:
        match = re.search(r"\[(\d+)\]", hit)
        count = int(match.group(1)) if match else 0
        if "gridDots" in hit and count > 24:
            errors.append("motion comfort violation: animated gridDots collection must stay <= 24 and low contrast")
        if any(name in hit for name in ("flowPackets", "streamPackets", "orbitPackets", "particles")) and count > 8:
            errors.append("motion comfort violation: moving packet/orbit collections must stay <= 8")

    glow_mentions = len(re.findall(r"filter\s*=\s*['\"]url\([^'\"]*glow|filter:\s*url\([^)]*glow", joined, re.I))
    if glow_mentions > 2:
        errors.append("motion comfort violation: moving glow/filter systems must be rare; too many glow-filtered layers")
    for match in re.finditer(r"stdDeviation\s*=\s*['\"]?([0-9]+(?:\.[0-9]+)?)", joined, re.I):
        try:
            if float(match.group(1)) > 6:
                errors.append("motion comfort violation: moving glow blur stdDeviation must stay <= 6")
                break
        except ValueError:
            pass
    if _max_numeric_scale(joined) > 1.08:
        errors.append("motion comfort violation: audio/frame scale emphasis must stay <= 1.08")
    if re.search(r"\borbit(?:ing)?\b", joined, re.I) and len(moving_collections) >= 2:
        errors.append("motion comfort violation: orbiting visuals cannot combine with multiple other moving systems")
    return sorted(set(errors))


def _looks_like_full_module(value: str) -> bool:
    return bool(
        re.search(r"^\s*import\b", value, re.M)
        or re.search(r"\bexport\s+(?:const|function)\s+AgentVisualGenerated\b", value)
        or re.search(r"\bexport\s*\{\s*AgentVisualGenerated\b", value)
    )


def _exports_agent_visual(value: str) -> bool:
    value = _strip_line_comments_for_export_scan(value)
    return bool(
        re.search(r"\bexport\s+(?:const|function)\s+AgentVisualGenerated\b", value)
        or re.search(r"\bexport\s*\{\s*AgentVisualGenerated\b", value)
    )


def disabled_agent_visual(reason: str = "not provided") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "enabled": False,
        "mode": "react_runtime",
        "render_mode": "full_canvas",
        "component_code": "",
        "module_code": "",
        "css": "",
        "description": "",
        "validation_errors": [reason] if reason else [],
    }


def normalize_agent_visual(value: Any, orientation: str = "vertical") -> dict[str, Any]:
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
    module_code = _raw_text(
        value.get("module_code")
        or value.get("tsx_module")
        or value.get("source_code")
        or value.get("full_code")
        or "",
        MAX_MODULE_CHARS + 1,
    )
    module_code = _normalize_provider_module_code(module_code)
    if not module_code and component_code and _looks_like_full_module(component_code):
        module_code = _normalize_provider_module_code(component_code)
        component_code = ""
    css = _raw_text(value.get("css") or value.get("style") or "", MAX_CSS_CHARS + 1)
    render_mode = str(value.get("render_mode") or "full_canvas")
    if render_mode not in RENDER_MODES:
        render_mode = "full_canvas"

    errors: list[str] = []
    if component_code and len(component_code) > MAX_COMPONENT_CHARS:
        errors.append(f"component_code exceeds {MAX_COMPONENT_CHARS} chars")
        component_code = ""
    if module_code and len(module_code) > MAX_MODULE_CHARS:
        errors.append(f"module_code exceeds {MAX_MODULE_CHARS} chars")
        module_code = ""
    if css and len(css) > MAX_CSS_CHARS:
        errors.append(f"css exceeds {MAX_CSS_CHARS} chars")
        css = ""
    source_code = module_code or component_code
    code_violations = _violations(source_code, BLOCKED_CODE_PATTERNS)
    if code_violations:
        errors.append("agent_visual code uses blocked local secret/process capability")
        component_code = ""
        module_code = ""
    css_violations = _violations(css, BLOCKED_CSS_PATTERNS)
    if css_violations:
        errors.append("css uses blocked remote/script capability")
        component_code = ""
        module_code = ""
    source_code = module_code or component_code
    if source_code and not errors:
        layout_errors = agent_visual_layout_errors(source_code, css, orientation)
        if layout_errors:
            errors.extend(f"layout contract violation: {error}" for error in layout_errors)
            component_code = ""
            module_code = ""
            css = ""

    requested_enabled = bool(value.get("enabled", True))
    if requested_enabled and module_code and not _exports_agent_visual(module_code) and not errors:
        errors.append("module_code must export a named AgentVisualGenerated component")
        module_code = ""
    if requested_enabled and component_code and "return" not in component_code and not errors:
        errors.append("component_code must be a React component function body with a return statement")
        component_code = ""
    if requested_enabled and not (component_code or module_code) and not errors:
        errors.append("component_code/module_code is empty")
    enabled = requested_enabled and bool(component_code or module_code) and not errors
    visual = {
        "schema_version": 1,
        "enabled": enabled,
        "mode": "react_runtime",
        "render_mode": render_mode,
        "component_code": component_code if enabled else "",
        "module_code": module_code if enabled else "",
        "css": css if enabled else "",
        "description": _clean_text(value.get("description") or value.get("notes") or "", MAX_DESCRIPTION_CHARS),
        "validation_errors": errors,
    }
    for key in ("chapter_bridge", "motion_profile", "source", "reason"):
        if key in value:
            visual[key] = value.get(key)
    fallback_reason = _clean_text(value.get("fallback_reason") or value.get("_agent_visual_fallback_reason") or "", 500)
    if fallback_reason:
        visual["fallback_reason"] = fallback_reason
    if value.get("_agent_visual_fallback_applied"):
        visual["_agent_visual_fallback_applied"] = True
    return visual


def require_agent_visual(value: Any, orientation: str = "vertical") -> dict[str, Any]:
    visual = normalize_agent_visual(value, orientation)
    if not visual.get("enabled"):
        errors = "; ".join(str(item) for item in visual.get("validation_errors") or [] if str(item).strip())
        raise ValueError(f"agent_visual is required and must contain valid custom React/CSS: {errors or 'missing'}")
    return visual


def agent_visual_text_items(value: Any, orientation: str = "vertical") -> list[str]:
    visual = normalize_agent_visual(value, orientation)
    items = [visual.get("description") or ""]
    if visual.get("enabled"):
        source_code = str(visual.get("module_code") or visual.get("component_code") or "")
        for match in re.finditer(r"""(?<![\w$])(?:'([^'\\]*(?:\\.[^'\\]*)*)'|"([^"\\]*(?:\\.[^"\\]*)*)")""", source_code):
            literal = match.group(1) if match.group(1) is not None else match.group(2)
            literal = _clean_text(literal, 120)
            if (
                literal
                and not literal.startswith(("agent-", "agent_", "#", ".", "/", "@remotion", "remotion", "react"))
                and len(literal) > 1
            ):
                items.append(literal)
    return [str(item) for item in items if str(item or "").strip()]
