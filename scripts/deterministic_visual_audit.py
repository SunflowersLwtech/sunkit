#!/usr/bin/env python3
"""Deterministic media checks before optional model visual audit."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from agent_harness.policy import policy_get
from agent_harness.content_guard import dismissive_verification_hits
from agent_harness.storyboard import minimum_storyboard_scene_count
from build_captions import orphan_caption_texts

DOUYIN_WIDTH = 1080
DOUYIN_HEIGHT = 1920
DOUYIN_ASPECT = "9:16"
PUBLISHABLE_LAYOUTS = {
    "vertical": {"width": 1080, "height": 1920, "aspect_ratio": "9:16"},
    "horizontal": {"width": 1920, "height": 1080, "aspect_ratio": "16:9"},
}
TOOL_FALLBACKS = {
    "ffmpeg": ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"],
    "ffprobe": ["/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"],
    "tesseract": ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"],
}
TOPIC_VISUAL_PRIMITIVES = (
    "diagram",
    "chart",
    "terminal",
    "code",
    "file tree",
    "diff",
    "architecture",
    "browser",
    "table",
    "matrix",
    "graph",
    "flow",
    "timeline",
    "canvas",
    "nodes",
    "network",
)
TOPIC_LOCKED_MARKERS = {
    "mem0": ("mem0/memory", "memoryclient", "memory.add", "mem0 后", "接入 mem0", "mem0ai/mem0"),
}
VISUAL_SUBJECT_DRIFT_MARKERS = {
    "gui": ("gui", "看屏幕", "读界面", "界面图", "screen", "interface"),
    "vlm": ("vlm", "vision-language", "multimodal", "多模态", "视觉语义", "vision to ui"),
    "screen_agent": ("screen · code · tool", "screen-code-tool", "screen/code/tool"),
}


def _marker_hits(text: str, markers: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for marker in markers:
        lowered_marker = marker.lower()
        if re.fullmatch(r"[a-z0-9]{2,6}", lowered_marker):
            if re.search(rf"(?<![a-z0-9]){re.escape(lowered_marker)}(?![a-z0-9])", lowered):
                hits.append(marker)
            continue
        if lowered_marker in lowered:
            hits.append(marker)
    return hits


SCENE_GRAMMAR_FAMILIES = {
    "HeroProblemScene": "hero_problem",
    "MechanismExplodedView": "mechanism_exploded_view",
    "RepoFileTreeReveal": "repo_file_tree",
    "ArchitectureFlowScene": "architecture_flow",
    "MetricComparisonScene": "metric_comparison",
    "DecisionMatrixScene": "decision_matrix",
    "TimelineBuildScene": "timeline_build",
    "CodeOrTerminalScene": "code_terminal",
    "KnowledgeTakeawayScene": "knowledge_takeaway",
}

MOTION_GRAMMAR_FAMILIES = {
    "camera_push": "camera_depth",
    "camera_pan": "camera_depth",
    "pan": "camera_depth",
    "parallax": "depth_layers",
    "mask_reveal": "mask_reveal",
    "path_draw": "vector_path_build",
    "metric_count": "metric_counter",
    "morph": "metric_morph",
    "typewriter": "code_terminal_type",
    "object_focus": "object_focus",
    "dwell": "readable_dwell",
    "reveal": "basic_reveal",
    "build": "basic_build",
}

CINEMATIC_MOTION = {"camera_push", "camera_pan", "pan", "parallax"}
INFORMATION_MOTION = {"mask_reveal", "path_draw", "metric_count", "morph", "typewriter"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _video_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def _run(cmd: list[str], timeout: int = 60) -> dict[str, Any]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    return {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-1600:],
        "stderr": proc.stderr[-2400:],
    }


def _run_bytes(cmd: list[str], timeout: int = 60) -> dict[str, Any]:
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    return {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr.decode("utf-8", errors="replace")[-2400:],
    }


def _which_tool(name: str) -> str | None:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    for fallback in TOOL_FALLBACKS.get(name, []):
        if Path(fallback).is_file():
            return fallback
    return None


def _caption_segments(run_dir: Path) -> list[dict[str, Any]]:
    captions_path = run_dir / "captions.json"
    if not captions_path.exists():
        return []
    data = read_json(captions_path)
    segments = data.get("segments") or []
    normalized: list[dict[str, Any]] = []
    for segment in segments:
        normalized.append(
            {
                "text": str(segment.get("text") or "").strip(),
                "startFrame": int(segment.get("startFrame", segment.get("start_frame", 0))),
                "endFrame": int(segment.get("endFrame", segment.get("end_frame", 0))),
            }
        )
    return normalized


def _duration(run_dir: Path) -> tuple[int, int]:
    props = read_json(run_dir / "remotion_input_props.json")
    return int(props.get("durationInFrames") or 0), int(props.get("fps") or 30)


def _duration_seconds(duration_frames: int, fps: int) -> float:
    return duration_frames / float(max(1, fps))


def _layout(run_dir: Path) -> dict[str, Any]:
    props = read_json(run_dir / "remotion_input_props.json")
    width = int(props.get("width") or 1080)
    height = int(props.get("height") or 1920)
    orientation = str(props.get("orientation") or ("horizontal" if width > height else "vertical"))
    return {"width": width, "height": height, "orientation": orientation}


def _premium_director_contract_checks(run_dir: Path) -> tuple[list[str], dict[str, Any]]:
    props = read_json(run_dir / "remotion_input_props.json")
    errors: list[str] = []
    spec = (
        props.get("premiumDirectorSpec")
        or props.get("premium_director_spec")
        or props.get("visualRecipe")
        or props.get("visual_recipe")
    )
    agent_visual = props.get("agentVisual") if isinstance(props.get("agentVisual"), dict) else {}
    required = bool(props.get("agentVisualRequired"))
    check: dict[str, Any] = {
        "agent_visual_required": required,
        "agent_visual_enabled": bool(agent_visual.get("enabled")),
        "agent_visual_source": agent_visual.get("source"),
        "premium_director_spec_present": isinstance(spec, dict),
        "scene_count": 0,
        "distinct_scene_types": [],
        "scene_grammar_family_count": 0,
        "scene_grammar_families": [],
        "topic_object_count": 0,
        "motion_beat_count": 0,
        "motion_grammar_types": [],
        "motion_grammar_family_count": 0,
        "motion_grammar_families": [],
        "cinematic_motion_types": [],
        "information_motion_types": [],
        "full_canvas_keynote_scene_count": 0,
    }
    public_payload = {
        "title": props.get("title"),
        "summary": props.get("summary"),
        "metricLine": props.get("metricLine"),
        "audienceMetricLine": props.get("audienceMetricLine"),
        "qualityWarnings": props.get("qualityWarnings"),
        "verificationNextStep": props.get("verificationNextStep"),
        "cards": props.get("cards"),
        "storyboard": props.get("storyboard"),
        "voiceoverText": props.get("voiceoverText"),
        "cta": props.get("cta"),
        "footer": props.get("footer"),
    }
    banned_hits = dismissive_verification_hits(public_payload)
    check["dismissive_verification_hits"] = banned_hits
    if banned_hits:
        errors.append(f"public payload contains banned dismissive verification phrasing: {banned_hits}")
    if not required:
        return errors, check
    if not agent_visual.get("enabled"):
        errors.append("provider render requires enabled agentVisual")
    if agent_visual.get("source") != "premium_director_compiler":
        errors.append("provider render agentVisual must come from premium_director_compiler")
    if not isinstance(spec, dict):
        errors.append("provider render requires premiumDirectorSpec")
        return errors, check
    profile = spec.get("profile") if isinstance(spec.get("profile"), dict) else {}
    scenes = spec.get("visual_scenes") if isinstance(spec.get("visual_scenes"), list) else []
    scene_types = sorted(
        {
            str(scene.get("scene_type") or scene.get("kind") or "")
            for scene in scenes
            if isinstance(scene, dict) and (scene.get("scene_type") or scene.get("kind"))
        }
    )
    grammar_families = sorted({SCENE_GRAMMAR_FAMILIES.get(scene_type, scene_type) for scene_type in scene_types})
    objects = spec.get("topic_objects") if isinstance(spec.get("topic_objects"), list) else []
    motion_beats = spec.get("motion_beats") if isinstance(spec.get("motion_beats"), list) else []
    scene_motion_types = sorted(
        {
            str(beat)
            for scene in scenes
            if isinstance(scene, dict)
            for beat in (scene.get("motion_beats") if isinstance(scene.get("motion_beats"), list) else [])
            if str(beat)
        }
    )
    global_motion_types = sorted(
        {
            str(beat.get("type") or beat.get("motion") or "")
            for beat in motion_beats
            if isinstance(beat, dict) and (beat.get("type") or beat.get("motion"))
        }
    )
    motion_types = sorted({*scene_motion_types, *global_motion_types})
    motion_families = sorted({MOTION_GRAMMAR_FAMILIES.get(motion_type, motion_type) for motion_type in motion_types})
    cinematic_motion = sorted(set(motion_types) & CINEMATIC_MOTION)
    information_motion = sorted(set(motion_types) & INFORMATION_MOTION)
    full_canvas_scene_count = len(
        [
            scene
            for scene in scenes
            if isinstance(scene, dict) and str(scene.get("layout") or "").lower() == "full_canvas_keynote"
        ]
    )
    check.update(
        {
            "scene_count": len(scenes),
            "distinct_scene_types": scene_types,
            "scene_grammar_family_count": len(grammar_families),
            "scene_grammar_families": grammar_families,
            "topic_object_count": len(objects),
            "motion_beat_count": len(motion_beats),
            "scene_motion_types": scene_motion_types,
            "global_motion_types": global_motion_types,
            "motion_grammar_types": motion_types,
            "motion_grammar_family_count": len(motion_families),
            "motion_grammar_families": motion_families,
            "cinematic_motion_types": cinematic_motion,
            "information_motion_types": information_motion,
            "full_canvas_keynote_scene_count": full_canvas_scene_count,
            "profile_orientation": profile.get("orientation"),
        }
    )
    if len(scenes) < 5:
        errors.append(f"premiumDirectorSpec.visual_scenes must contain at least 5 scenes, got {len(scenes)}")
    if len(scene_types) < 4:
        errors.append(f"premiumDirectorSpec must contain at least 4 distinct scene types, got {scene_types}")
    if len(grammar_families) < 3:
        errors.append(f"premiumDirectorSpec must contain at least 3 visual grammar families, got {grammar_families}")
    if full_canvas_scene_count != len(scenes):
        errors.append(f"premiumDirectorSpec scenes must all use full_canvas_keynote layout, got {full_canvas_scene_count}/{len(scenes)}")
    if len(motion_types) < 6:
        errors.append(f"premiumDirectorSpec must contain at least 6 distinct motion grammar types, got {motion_types}")
    if not cinematic_motion:
        errors.append("premiumDirectorSpec must include at least one cinematic motion type: camera_push, camera_pan, pan, or parallax")
    if len(information_motion) < 3:
        errors.append(f"premiumDirectorSpec must include at least 3 information-design motion types, got {information_motion}")
    if len(motion_families) < 5:
        errors.append(f"premiumDirectorSpec must contain at least 5 motion grammar families, got {motion_families}")
    if len(objects) < 3:
        errors.append(f"premiumDirectorSpec.topic_objects must contain at least 3 objects, got {len(objects)}")
    if len(motion_beats) < 3:
        errors.append(f"premiumDirectorSpec.motion_beats must contain at least 3 beats, got {len(motion_beats)}")
    if profile.get("orientation") and profile.get("orientation") != props.get("orientation"):
        errors.append(f"premiumDirectorSpec profile orientation {profile.get('orientation')} does not match payload orientation {props.get('orientation')}")
    return errors, check


def _publish_layout_check(layout: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    width = int(layout.get("width") or 0)
    height = int(layout.get("height") or 0)
    orientation = str(layout.get("orientation") or "")
    expected = PUBLISHABLE_LAYOUTS.get(orientation)
    errors: list[str] = []
    if not expected or width != expected["width"] or height != expected["height"]:
        errors.append(
            "publishable Searchpo/Douyin video must be vertical 1080x1920 or horizontal 1920x1080; "
            f"got {width}x{height} ({orientation or 'unknown'})"
        )
    return {
        "status": "pass" if not errors else "fail",
        "expected": expected or PUBLISHABLE_LAYOUTS,
        "actual": {"width": width, "height": height, "orientation": orientation},
        "errors": errors,
    }, errors


def _visual_state_hint_count(component_code: str) -> int:
    if not component_code:
        return 0
    narrative_array_count = 0
    narrative_names = r"(?:stages|beats|steps|chapters|sections|states|pipeline|timeline)"
    for match in re.finditer(rf"\b(?:const|let|var)\s+{narrative_names}\s*=\s*\[(.*?)\]\s*;", component_code, flags=re.S | re.I):
        body = match.group(1)
        object_count = len(re.findall(r"[{,]\s*['\"]?(?:label|title|name|k)['\"]?\s*:", body, flags=re.I))
        string_count = len(re.findall(r"['\"][^'\"]{2,60}['\"]", body))
        narrative_array_count = max(narrative_array_count, object_count or string_count)
    if narrative_array_count:
        return narrative_array_count
    return len(re.findall(r"[{,]\s*['\"]?(?:label|title|name|k)['\"]?\s*:", component_code, flags=re.I))


def _agent_visual_source(agent_visual: dict[str, Any]) -> str:
    return str(agent_visual.get("module_code") or agent_visual.get("component_code") or "")


def _visual_structure_check(run_dir: Path, duration_frames: int, fps: int) -> tuple[dict[str, Any], list[str]]:
    props_path = run_dir / "remotion_input_props.json"
    props = read_json(props_path) if props_path.exists() else {}
    duration_sec = _duration_seconds(duration_frames, fps)
    profile = props.get("videoProfile") if isinstance(props.get("videoProfile"), dict) else {}
    profile_duration = 0.0
    try:
        profile_duration = float(profile.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        profile_duration = 0.0
    effective_duration = max(duration_sec, profile_duration)
    storyboard = props.get("storyboard") if isinstance(props.get("storyboard"), dict) else {}
    scenes = [scene for scene in storyboard.get("scenes") or [] if isinstance(scene, dict)]
    scene_types = [str(scene.get("type") or "") for scene in scenes]
    motion_scene_types = {
        "terminal",
        "flow",
        "chart",
        "code_diff",
        "code_block",
        "node_graph",
        "decision_table",
        "compare_table",
        "compare",
        "bullets",
        "stat",
    }
    agent_visual = props.get("agentVisual") if isinstance(props.get("agentVisual"), dict) else {}
    agent_visual_full_canvas = bool(agent_visual.get("enabled")) and str(agent_visual.get("render_mode") or "") == "full_canvas"
    visual_state_count = _visual_state_hint_count(_agent_visual_source(agent_visual))
    required_scenes = minimum_storyboard_scene_count(effective_duration)
    errors: list[str] = []
    if effective_duration >= 60:
        if not agent_visual_full_canvas:
            if len(scenes) < required_scenes:
                errors.append(
                    f"visual plan underfits {effective_duration:.1f}s video: storyboard has {len(scenes)} scenes, requires at least {required_scenes}"
                )
            min_type_count = 5 if effective_duration >= 180 else 4
            if len(set(scene_types)) < min_type_count:
                errors.append(
                    f"visual plan underfits {effective_duration:.1f}s video: only {len(set(scene_types))} scene types, requires at least {min_type_count}"
                )
            min_motion_count = 5 if effective_duration >= 180 else 3
            motion_count = sum(1 for scene_type in scene_types if scene_type in motion_scene_types)
            if motion_count < min_motion_count:
                errors.append(
                    f"visual plan underfits {effective_duration:.1f}s video: only {motion_count} motion-rich scenes, requires at least {min_motion_count}"
                )
        if agent_visual_full_canvas and visual_state_count < required_scenes:
            errors.append(
                f"agent_visual has too few visible states for {effective_duration:.1f}s video: detected {visual_state_count}, requires at least {required_scenes}"
            )
    return {
        "status": "pass" if not errors else "fail",
        "duration_sec": round(duration_sec, 3),
        "video_profile_duration_sec": profile_duration or None,
        "effective_duration_sec": round(effective_duration, 3),
        "required_scene_count": required_scenes,
        "storyboard_scene_count": len(scenes),
        "storyboard_scene_types": scene_types,
        "storyboard_distinct_scene_type_count": len(set(scene_types)),
        "motion_rich_scene_count": sum(1 for scene_type in scene_types if scene_type in motion_scene_types),
        "agent_visual_enabled": bool(agent_visual.get("enabled")),
        "agent_visual_state_hint_count": visual_state_count,
        "errors": errors,
    }, errors


def _candidate_visual_terms(selected: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    raw_values = [
        selected.get("title"),
        selected.get("entity_key"),
        selected.get("canonical_url"),
        payload.get("displayTitle"),
        payload.get("title"),
    ]
    terms: list[str] = []
    for raw in raw_values:
        value = str(raw or "").strip()
        if not value:
            continue
        if value.startswith(("http://", "https://")):
            tail = value.rstrip("/").rsplit("/", 1)[-1]
            if tail:
                value = tail
        if "/" in value and not value.startswith("/"):
            compact = value.strip()
            if 4 <= len(compact) <= 48:
                terms.append(compact)
        for part in re.split(r"[\s/_:.-]+", value):
            cleaned = part.strip()
            if len(cleaned) >= 4 and cleaned.lower() not in {"github", "repo", "http", "https", "www", "com"}:
                terms.append(cleaned)
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            unique.append(term)
    return unique[:8]


def _public_subject_boundary_text(run_dir: Path, selected: dict[str, Any], payload: dict[str, Any]) -> str:
    values: list[Any] = [selected]
    public_payload = {key: value for key, value in payload.items() if key not in {"agentVisual", "agent_visual"}}
    values.append(public_payload)
    for name in [
        "voiceover_manifest.json",
        "fact_bank.json",
        "topic_brief.json",
        "research_brief.json",
        "cross_check_review.json",
        "evidence_bundle.json",
    ]:
        path = run_dir / name
        if path.exists():
            try:
                values.append(read_json(path))
            except (OSError, json.JSONDecodeError):
                continue
    return json.dumps(values, ensure_ascii=False).lower()


def _subject_supports_visual_marker_group(group: str, markers: tuple[str, ...], public_subject: str) -> bool:
    if _marker_hits(public_subject, markers):
        return True
    if group == "screen_agent":
        return (
            ("code" in public_subject or "coding" in public_subject)
            and ("screen" in public_subject or "gui" in public_subject or "interface" in public_subject)
            and ("tool" in public_subject or "cli" in public_subject or "terminal" in public_subject)
        )
    return False


def _visual_density_markers(component_code: str, description: str) -> list[str]:
    joined = f"{description}\n{component_code}".lower()
    markers: list[str] = []
    patterns = [
        ("generic_source_flow_hub", r"source flow|source\s*[·.\-]\s*risk\s*[·.\-]\s*verify"),
        ("bottom_state_card_grid", r"stages\.map\(stageTile\)|gridtemplatecolumns:\s*`repeat\(\$\{math\.max\(6"),
        ("side_metric_bars", r"evalbars\.map|benchmark bars|status bars|metric bars"),
        ("fact_cards", r"factsbrief\.slice|factlines\.slice|source facts|fact cards"),
        ("large_status_counter", r"状态\s*\{active\s*\+\s*1\}|state\s*\{active\s*\+\s*1\}|镜头\s*\{active\s*\+\s*1\}"),
        ("multi_packet_orbit", r"orbitpackets\.map|streampackets\.map|nodegrid\.map"),
        ("flow_packet_train", r"flowpackets\.map|streampackets\.map|packet\s*/\s*\d+\s*\+\s*frame\s*/"),
        ("animated_grid_dots", r"griddots\.map|particles\.map|sparkles\.map"),
        ("continuous_orbit", r"\borbit\w*|angle\s*=\s*frame\s*/|radius\s*=\s*[^;\n]*math\.sin"),
        ("dash_sweep", r"strokedashoffset\s*=\s*\{\s*-?\s*frame\s*\*|strokedashoffset\s*:\s*-?\s*frame\s*\*"),
        ("moving_glow_system", r"filter\s*=\s*['\"]url\([^'\"]*glow|stddeviation\s*=\s*['\"]?(?:[7-9]|\d{2,})"),
        ("scanner_sweep", r"scanner\s*=|scanline|sweep"),
        ("animated_file_rail", r"files\.slice\([^)]*\)\.map|filerail|repo surface.*map"),
    ]
    for label, pattern in patterns:
        if re.search(pattern, joined, flags=re.I):
            markers.append(label)
    return markers


def _visual_intent_check(run_dir: Path) -> tuple[dict[str, Any], list[str]]:
    payload_path = run_dir / "remotion_input_props.json"
    if not payload_path.exists():
        payload_path = run_dir / "render_payload.json"
    if not payload_path.exists():
        return {"status": "fail", "errors": ["Remotion props/render_payload missing for visual intent check"]}, [
            "Remotion props/render_payload missing for visual intent check"
        ]
    payload = read_json(payload_path)
    agent_visual = payload.get("agentVisual") if isinstance(payload.get("agentVisual"), dict) else {}
    code = _agent_visual_source(agent_visual)
    css = str(agent_visual.get("css") or "")
    description = str(agent_visual.get("description") or "")
    joined = f"{description}\n{code}\n{css}".lower()
    errors: list[str] = []
    selected = read_json(run_dir / "selected_candidate.json") if (run_dir / "selected_candidate.json").exists() else {}
    candidate_terms = _candidate_visual_terms(selected, payload)
    public_subject = _public_subject_boundary_text(run_dir, selected, payload)
    if payload.get("agentVisualRequired") and not agent_visual.get("enabled"):
        errors.append("agent_visual is required for provider media but is not enabled")
    if agent_visual.get("fallback_reason") or payload.get("_agent_visual_fallback_applied"):
        errors.append("agent_visual fallback cannot be published; regenerate topic-specific Remotion visual code")
    if re.search(r"\bdata\s*\.\s*cards\b|\bsafeCards\b", code):
        errors.append("agent_visual relies on compatibility cards as the main visual surface")
    if ("progress bar" in joined or "progress-linked" in joined or "text highlights" in joined) and not any(
        term in joined for term in TOPIC_VISUAL_PRIMITIVES
    ):
        errors.append("agent_visual describes progress/text-highlight motion without topic-specific visual primitives")
    primitive_hits = [term for term in TOPIC_VISUAL_PRIMITIVES if term in joined]
    density_markers = _visual_density_markers(code, description)
    if payload.get("agentVisualRequired") and agent_visual.get("enabled") and len(primitive_hits) < 1:
        errors.append("agent_visual lacks topic-specific visual primitives such as chart, terminal, code, diagram, table, or flow")
    if payload.get("agentVisualRequired") and agent_visual.get("enabled") and candidate_terms:
        binds_dynamic_title = bool(re.search(r"\bdata\s*\.\s*(?:displayTitle|title|speechTitle)\b", code))
        topic_hits = [term for term in candidate_terms if term.lower() in joined]
        if not topic_hits and not binds_dynamic_title:
            errors.append("agent_visual does not reference the current candidate/topic title or dynamic display title")
        unrelated_markers = [
            marker
            for topic, markers in TOPIC_LOCKED_MARKERS.items()
            if topic not in {term.lower() for term in candidate_terms}
            for marker in markers
            if marker in joined
        ]
        if unrelated_markers:
            errors.append(f"agent_visual contains hard-coded visual terms from a different topic: {unrelated_markers[:4]}")
    drift_markers: list[str] = []
    for group, markers in VISUAL_SUBJECT_DRIFT_MARKERS.items():
        visual_hits = _marker_hits(joined, markers)
        if visual_hits and not _subject_supports_visual_marker_group(group, markers, public_subject):
            drift_markers.append(f"{group}: {visual_hits[:3]}")
    if drift_markers:
        errors.append(
            "agent_visual central visual subject is not grounded in the public voiceover/evidence boundary: "
            + "; ".join(drift_markers)
        )
    if (
        payload.get("agentVisualRequired")
        and agent_visual.get("enabled")
        and str(agent_visual.get("render_mode") or "") == "full_canvas"
        and len(density_markers) >= 4
    ):
        errors.append(
            "agent_visual is visually overcrowded: full-canvas render combines too many competing systems "
            + str(density_markers[:6])
        )
    return {
        "status": "pass" if not errors else "fail",
        "method": "render_payload_agent_visual_contract",
        "agent_visual_required": bool(payload.get("agentVisualRequired")),
        "agent_visual_enabled": bool(agent_visual.get("enabled")),
        "primitive_hits": primitive_hits,
        "topic_entity_hits": [term for term in candidate_terms if term.lower() in joined],
        "visual_subject_drift_markers": drift_markers,
        "visual_density_markers": density_markers,
        "uses_compatibility_cards": bool(re.search(r"\bdata\s*\.\s*cards\b|\bsafeCards\b", code)),
        "description": description,
        "errors": errors,
    }, errors


def _extract_frames(video: Path, run_dir: Path, duration_frames: int, fps: int) -> tuple[list[dict[str, Any]], list[str]]:
    ffmpeg = _which_tool("ffmpeg")
    warnings: list[str] = []
    frames: list[dict[str, Any]] = []
    if not ffmpeg:
        warnings.append("ffmpeg not found; frame extraction cannot run")
        return frames, warnings
    duration_sec = max(1.0, duration_frames / float(fps or 30))
    sample_points = sorted(set([1.0, max(1.0, duration_sec / 2), max(1.0, duration_sec - 1.0)]))
    frame_dir = run_dir / "frame_checks"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for index, second in enumerate(sample_points, start=1):
        output = frame_dir / f"frame_{index:02d}_{int(second):02d}s.jpg"
        result = _run([ffmpeg, "-y", "-ss", f"{second:.2f}", "-i", str(video), "-frames:v", "1", str(output)], timeout=45)
        frames.append({"second": round(second, 3), "path": str(output), "exists": output.is_file(), "ffmpeg": result})
        if result["returncode"] != 0 or not output.is_file():
            warnings.append(f"failed to extract frame at {second:.2f}s")
    return frames, warnings


def _even(value: int, minimum: int = 2) -> int:
    value = max(minimum, value)
    return value if value % 2 == 0 else value - 1


def _motion_crop(layout: dict[str, Any]) -> dict[str, int]:
    width = max(1, int(layout.get("width") or DOUYIN_WIDTH))
    height = max(1, int(layout.get("height") or DOUYIN_HEIGHT))
    scaled_width = 160
    scaled_height = _even(round(scaled_width * height / width), 20)
    crop_x = _even(round(scaled_width * 0.10), 0)
    crop_width = _even(scaled_width - crop_x * 2, 32)
    crop_y = _even(round(scaled_height * 0.06), 0)
    visible_fraction = 0.68 if height >= width else 0.64
    crop_height = _even(min(scaled_height - crop_y, round(scaled_height * visible_fraction)), 20)
    return {
        "scaled_width": scaled_width,
        "scaled_height": scaled_height,
        "crop_x": crop_x,
        "crop_y": crop_y,
        "crop_width": crop_width,
        "crop_height": crop_height,
    }


def _motion_pairs(raw: bytes, frame_size: int) -> list[dict[str, float]]:
    frame_count = len(raw) // frame_size if frame_size > 0 else 0
    pairs: list[dict[str, float]] = []
    for index in range(1, frame_count):
        previous = raw[(index - 1) * frame_size : index * frame_size]
        current = raw[index * frame_size : (index + 1) * frame_size]
        total = 0
        changed = 0
        for old, new in zip(previous, current):
            delta = abs(new - old)
            total += delta
            if delta >= 10:
                changed += 1
        pairs.append(
            {
                "pair_index": float(index),
                "mean_abs_delta": total / frame_size,
                "changed_pixel_ratio": changed / frame_size,
            }
        )
    return pairs


def _max_inactive_seconds(active_flags: list[bool], sample_period_sec: float) -> float:
    longest = 0
    current = 0
    for active in active_flags:
        if active:
            longest = max(longest, current)
            current = 0
        else:
            current += 1
    longest = max(longest, current)
    return round(longest * sample_period_sec, 3)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _motion_check(video: Path, layout: dict[str, Any], duration_frames: int, fps: int) -> tuple[dict[str, Any], list[str]]:
    ffmpeg = _which_tool("ffmpeg")
    if not ffmpeg:
        return {"status": "fail", "errors": ["ffmpeg is required for central motion check"]}, ["ffmpeg is required for central motion check"]
    duration_sec = max(1.0, duration_frames / float(fps or 30))
    sample_period_sec = 1.0 if duration_sec <= 120 else 2.0
    sample_filter = "fps=1" if sample_period_sec == 1.0 else "fps=1/2"
    crop = _motion_crop(layout)
    filter_chain = (
        f"{sample_filter},"
        f"scale={crop['scaled_width']}:{crop['scaled_height']},"
        f"crop={crop['crop_width']}:{crop['crop_height']}:{crop['crop_x']}:{crop['crop_y']},"
        "format=gray"
    )
    result = _run_bytes([ffmpeg, "-v", "error", "-i", str(video), "-vf", filter_chain, "-an", "-f", "rawvideo", "-"], timeout=240)
    if result["returncode"] != 0:
        errors = [f"central motion ffmpeg sample failed: {result['stderr']}"]
        return {"status": "fail", "filter": filter_chain, "errors": errors}, errors
    frame_size = int(crop["crop_width"]) * int(crop["crop_height"])
    raw = bytes(result["stdout"])
    frame_count = len(raw) // frame_size if frame_size else 0
    pairs = _motion_pairs(raw[: frame_count * frame_size], frame_size)
    thresholds = {
        "mean_abs_delta_min": 1.8,
        "changed_pixel_ratio_min": 0.012,
        "active_pair_ratio_min": 0.2,
        "min_active_pairs": 4,
        "max_static_seconds": 10.0,
        "opening_window_seconds": 4.0 if sample_period_sec == 1.0 else 8.0,
        "mean_abs_delta_overload": 18.0,
        "changed_pixel_ratio_overload": 0.24,
        "motion_overload_pair_ratio_max": 0.55,
        "opening_overload_ratio_max": 0.75,
    }
    active_flags = [
        pair["mean_abs_delta"] >= thresholds["mean_abs_delta_min"]
        or pair["changed_pixel_ratio"] >= thresholds["changed_pixel_ratio_min"]
        for pair in pairs
    ]
    active_count = sum(1 for active in active_flags if active)
    active_ratio = active_count / len(active_flags) if active_flags else 0.0
    max_static_seconds = _max_inactive_seconds(active_flags, sample_period_sec)
    opening_pairs = max(1, round(thresholds["opening_window_seconds"] / sample_period_sec))
    opening_active = any(active_flags[:opening_pairs])
    overload_flags = [
        pair["mean_abs_delta"] >= thresholds["mean_abs_delta_overload"]
        or pair["changed_pixel_ratio"] >= thresholds["changed_pixel_ratio_overload"]
        for pair in pairs
    ]
    overload_count = sum(1 for active in overload_flags if active)
    overload_ratio = overload_count / len(overload_flags) if overload_flags else 0.0
    opening_overload_ratio = (
        sum(1 for active in overload_flags[:opening_pairs] if active) / min(opening_pairs, len(overload_flags))
        if overload_flags
        else 0.0
    )
    mean_abs_values = [pair["mean_abs_delta"] for pair in pairs]
    changed_ratio_values = [pair["changed_pixel_ratio"] for pair in pairs]
    median_mean_abs_delta = _median(mean_abs_values)
    median_changed_pixel_ratio = _median(changed_ratio_values)
    errors: list[str] = []
    if frame_count < 8:
        errors.append(f"central motion audit requires at least 8 sampled frames, got {frame_count}")
    if active_count < thresholds["min_active_pairs"] or active_ratio < thresholds["active_pair_ratio_min"]:
        errors.append(
            "central content motion is too sparse; captions/progress/highlights alone are insufficient "
            f"(active_pairs={active_count}/{len(active_flags)}, active_ratio={active_ratio:.2f})"
        )
    if max_static_seconds > thresholds["max_static_seconds"]:
        errors.append(f"central content remains static for {max_static_seconds:.1f}s, above {thresholds['max_static_seconds']:.1f}s")
    if not opening_active:
        errors.append(f"first {thresholds['opening_window_seconds']:.0f}s lack central visual movement")
    if overload_ratio > thresholds["motion_overload_pair_ratio_max"]:
        errors.append(
            "central content motion is overloaded for too much of the video "
            f"(overload_pairs={overload_count}/{len(overload_flags)}, overload_ratio={overload_ratio:.2f})"
        )
    if opening_overload_ratio > thresholds["opening_overload_ratio_max"]:
        errors.append(
            "opening motion is too aggressive; viewer gets no stable focal target "
            f"(opening_overload_ratio={opening_overload_ratio:.2f})"
        )
    return {
        "status": "pass" if not errors else "fail",
        "method": "ffmpeg_gray_frame_delta_cropping_caption_and_edge_ui_regions",
        "filter": filter_chain,
        "sample_period_sec": sample_period_sec,
        "frame_count": frame_count,
        "pair_count": len(active_flags),
        "active_pair_count": active_count,
        "active_pair_ratio": round(active_ratio, 4),
        "motion_overload_pair_count": overload_count,
        "motion_overload_pair_ratio": round(overload_ratio, 4),
        "opening_overload_ratio": round(opening_overload_ratio, 4),
        "median_mean_abs_delta": round(median_mean_abs_delta, 4),
        "median_changed_pixel_ratio": round(median_changed_pixel_ratio, 4),
        "max_static_seconds": max_static_seconds,
        "opening_active": opening_active,
        "crop": crop,
        "thresholds": thresholds,
        "pairs_preview": pairs[:5] + ([{"omitted_pairs": float(max(0, len(pairs) - 10))}] if len(pairs) > 10 else []) + pairs[-5:],
        "errors": errors,
    }, errors


def _black_silence_checks(video: Path, provider: str) -> tuple[list[str], list[str], dict[str, Any]]:
    ffmpeg = _which_tool("ffmpeg")
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    if not ffmpeg:
        errors.append("ffmpeg is required for black/silence checks")
        return errors, warnings, checks
    if provider == "contract":
        errors.append("contract silent audio cannot pass deterministic video audit; run provider TTS for publishable media")
    black = _run([ffmpeg, "-i", str(video), "-vf", "blackdetect=d=0.4:pix_th=0.10", "-an", "-f", "null", "-"], timeout=240)
    checks["blackdetect"] = black
    black_durations = [float(value) for value in re.findall(r"black_duration:([0-9.]+)", black["stderr"])]
    checks["black_durations_sec"] = black_durations
    if black_durations and max(black_durations) >= 1.5:
        errors.append(f"video contains black frame span >= 1.5s: {max(black_durations):.2f}s")

    silence = _run([ffmpeg, "-i", str(video), "-af", "silencedetect=noise=-45dB:d=1.0", "-f", "null", "-"], timeout=240)
    checks["silencedetect"] = silence
    silence_durations = [float(value) for value in re.findall(r"silence_duration: ([0-9.]+)", silence["stderr"])]
    checks["silence_durations_sec"] = silence_durations
    if silence_durations and max(silence_durations) >= 3.0:
        errors.append(f"provider video contains silence span >= 3.0s: {max(silence_durations):.2f}s")
    return errors, warnings, checks


def _ocr_frames(frames: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    tesseract = _which_tool("tesseract")
    errors: list[str] = []
    results: list[dict[str, Any]] = []
    if not tesseract:
        return results, ["tesseract OCR is required for text verification"]
    for frame in frames:
        frame_path = Path(str(frame.get("path") or ""))
        if not frame_path.is_file():
            continue
        result = _run([tesseract, str(frame_path), "stdout", "--psm", "6"], timeout=45)
        text = result.get("stdout") or ""
        results.append({"frame": str(frame_path), "text": text.strip(), "tesseract": result})
        if result["returncode"] != 0:
            errors.append(f"OCR failed for frame: {frame_path}")
        elif not text.strip():
            errors.append(f"OCR produced no text for frame: {frame_path}")
    return results, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", help="Output JSON path. Defaults to run_dir/visual_audit_deterministic.json")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    video = _video_path(args.video)
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    if not video.is_file():
        errors.append(f"video missing: {video}")

    duration_frames, fps = _duration(run_dir)
    layout = _layout(run_dir)
    premium_errors, premium_check = _premium_director_contract_checks(run_dir)
    errors.extend(premium_errors)
    checks["premium_director_contract"] = premium_check
    layout_check, layout_errors = _publish_layout_check(layout)
    errors.extend(layout_errors)
    visual_structure_check, visual_structure_errors = _visual_structure_check(run_dir, duration_frames, fps)
    errors.extend(visual_structure_errors)
    visual_intent_check, visual_intent_errors = _visual_intent_check(run_dir)
    errors.extend(visual_intent_errors)
    captions = _caption_segments(run_dir)
    punch_words = {str(item).strip() for item in policy_get("visual_audit.punch_words", [])}
    short_segments = orphan_caption_texts(captions, punch_words)
    if not captions:
        errors.append("captions missing")
    if short_segments:
        errors.append(f"caption contains orphan 1-2 word/character segments: {short_segments[:8]}")
    bad_ranges = [
        segment
        for segment in captions
        if int(segment["startFrame"]) < 0 or int(segment["endFrame"]) <= int(segment["startFrame"]) or int(segment["endFrame"]) > duration_frames
    ]
    if bad_ranges:
        errors.append(f"caption frame ranges are invalid or exceed video duration: {bad_ranges[:3]}")
    max_caption_chars = max([len(segment["text"]) for segment in captions] or [0])
    max_allowed_caption_chars = int(policy_get("quality_gate.max_caption_chars", 36))
    if max_caption_chars > max_allowed_caption_chars:
        errors.append(f"caption segment too long for safe area: {max_caption_chars} chars")

    provider = str((read_json(run_dir / "voiceover_manifest.json") if (run_dir / "voiceover_manifest.json").exists() else {}).get("provider") or "")
    if video.is_file():
        frames, frame_warnings = _extract_frames(video, run_dir, duration_frames, fps)
        checks["frames"] = frames
        errors.extend(frame_warnings)
        if len(frames) < 3 or any(not frame.get("exists") for frame in frames):
            errors.append("deterministic audit requires 3 successfully extracted frame samples")
        if str(os.environ.get("SEARCHPO_ENABLE_OCR_AUDIT") or "").strip().lower() in {"1", "true", "yes", "on"}:
            ocr_results, ocr_errors = _ocr_frames(frames)
            checks["ocr"] = ocr_results
            warnings.extend(ocr_errors)
            if len(ocr_results) != len(frames):
                warnings.append("OCR result count does not match extracted frame sample count")
        else:
            checks["ocr"] = []
            warnings.append("OCR audit disabled; deterministic gate uses layout, motion, visual intent, black/silence, and captions")
        media_errors, media_warnings, media_checks = _black_silence_checks(video, provider)
        errors.extend(media_errors)
        warnings.extend(media_warnings)
        checks.update(media_checks)
        motion_check, motion_errors = _motion_check(video, layout, duration_frames, fps)
        errors.extend(motion_errors)
        checks["motion"] = motion_check

    report = {
        "schema_version": 2,
        "created_at": utc_now(),
        "status": "pass" if not errors else "fail",
        "video_path": str(video),
        "durationInFrames": duration_frames,
        "fps": fps,
        "layout": layout,
        "layout_check": layout_check,
        "visual_structure_check": visual_structure_check,
        "visual_intent_check": visual_intent_check,
        "motion_check": checks.get("motion"),
        "provider": provider,
        "caption_count": len(captions),
        "caption_max_chars": max_caption_chars,
        "ocr_layout_report": {
            "method": "optional_tesseract_diagnostics_plus_static_layout_constraints",
            "enabled": str(os.environ.get("SEARCHPO_ENABLE_OCR_AUDIT") or "").strip().lower() in {"1", "true", "yes", "on"},
            "caption_safe_area": {
                "bottom_px": 96 if layout["orientation"] == "horizontal" else 330,
                "left_px": 180 if layout["orientation"] == "horizontal" else 70,
                "right_px": 180 if layout["orientation"] == "horizontal" else 70,
                "max_chars": max_allowed_caption_chars,
            },
            "frame_samples": [frame.get("path") for frame in checks.get("frames", [])],
            "ocr_text": [item.get("text") for item in checks.get("ocr", [])],
        },
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }
    output = Path(args.output).resolve() if args.output else run_dir / "visual_audit_deterministic.json"
    write_json(output, report)
    print(json.dumps({"visual_audit_deterministic": str(output), "status": report["status"], "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
