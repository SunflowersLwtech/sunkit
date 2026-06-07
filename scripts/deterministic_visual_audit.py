#!/usr/bin/env python3
"""Deterministic media checks before optional model visual audit."""

from __future__ import annotations

import argparse
import json
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
from build_captions import orphan_caption_texts


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


def _extract_frames(video: Path, run_dir: Path, duration_frames: int, fps: int) -> tuple[list[dict[str, Any]], list[str]]:
    ffmpeg = shutil.which("ffmpeg")
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


def _black_silence_checks(video: Path, provider: str) -> tuple[list[str], list[str], dict[str, Any]]:
    ffmpeg = shutil.which("ffmpeg")
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    if not ffmpeg:
        errors.append("ffmpeg is required for black/silence checks")
        return errors, warnings, checks
    if provider == "contract":
        errors.append("contract silent audio cannot pass deterministic video audit; run provider TTS for publishable media")
    black = _run([ffmpeg, "-i", str(video), "-vf", "blackdetect=d=0.4:pix_th=0.10", "-an", "-f", "null", "-"], timeout=90)
    checks["blackdetect"] = black
    black_durations = [float(value) for value in re.findall(r"black_duration:([0-9.]+)", black["stderr"])]
    checks["black_durations_sec"] = black_durations
    if black_durations and max(black_durations) >= 1.5:
        errors.append(f"video contains black frame span >= 1.5s: {max(black_durations):.2f}s")

    silence = _run([ffmpeg, "-i", str(video), "-af", "silencedetect=noise=-45dB:d=1.0", "-f", "null", "-"], timeout=90)
    checks["silencedetect"] = silence
    silence_durations = [float(value) for value in re.findall(r"silence_duration: ([0-9.]+)", silence["stderr"])]
    checks["silence_durations_sec"] = silence_durations
    if silence_durations and max(silence_durations) >= 3.0:
        errors.append(f"provider video contains silence span >= 3.0s: {max(silence_durations):.2f}s")
    return errors, warnings, checks


def _ocr_frames(frames: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    tesseract = shutil.which("tesseract")
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
        ocr_results, ocr_errors = _ocr_frames(frames)
        checks["ocr"] = ocr_results
        errors.extend(ocr_errors)
        if len(ocr_results) != len(frames):
            errors.append("OCR result count does not match extracted frame sample count")
        media_errors, media_warnings, media_checks = _black_silence_checks(video, provider)
        errors.extend(media_errors)
        warnings.extend(media_warnings)
        checks.update(media_checks)

    report = {
        "schema_version": 1,
        "created_at": utc_now(),
        "status": "pass" if not errors else "fail",
        "video_path": str(video),
        "durationInFrames": duration_frames,
        "fps": fps,
        "layout": layout,
        "provider": provider,
        "caption_count": len(captions),
        "caption_max_chars": max_caption_chars,
        "ocr_layout_report": {
            "method": "tesseract_ocr_plus_static_layout_constraints",
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
