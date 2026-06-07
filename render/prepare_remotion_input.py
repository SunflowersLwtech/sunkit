#!/usr/bin/env python3
"""Prepare run-scoped Remotion props without modifying tracked public fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from agent_harness.storyboard import validate_storyboard  # noqa: E402
from agent_harness.agent_visual import normalize_agent_visual, require_agent_visual  # noqa: E402
from agent_harness.premium_repo_visual import is_github_repo_subject, premium_repo_agent_visual  # noqa: E402
from agent_harness.video_profile import normalize_video_profile  # noqa: E402

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"
PUBLIC_GENERATED_DIR = ROOT / "public" / "generated"
GENERATED_VISUAL_TSX = ROOT / "src" / "generated" / "AgentVisual.generated.tsx"
GENERATED_VISUAL_CSS = ROOT / "src" / "generated" / "agent-visual.generated.css"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_captions(run_dir: Path) -> tuple[list[dict[str, Any]], Path | None]:
    path = run_dir / "captions.json"
    if not path.exists():
        raise SystemExit(f"captions artifact missing: {path}")
    data = read_json(path)
    normalized: list[dict[str, Any]] = []
    for segment in data.get("segments") or []:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        start = int(segment.get("startFrame", segment.get("start_frame", 0)))
        end = int(segment.get("endFrame", segment.get("end_frame", start + 1)))
        if end <= start:
            end = start + 1
        normalized.append({"text": text, "startFrame": start, "endFrame": end})
    if not normalized:
        raise SystemExit(f"captions artifact has no timed segments: {path}")
    return normalized, path


def run_asset_stem(run_dir: Path) -> str:
    date_part = run_dir.parent.name if run_dir.parent.name else "run"
    return f"{date_part}-{run_dir.name}"


def audio_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "voiceover_manifest.json"
    if not path.exists():
        raise SystemExit(f"voiceover manifest missing: {path}")
    return read_json(path)


def derive_duration(payload: dict[str, Any], captions: list[dict[str, Any]], manifest: dict[str, Any]) -> tuple[int, int]:
    fps = int(payload.get("fps") or manifest.get("fps") or os.environ.get("SEARCHPO_VIDEO_FPS") or 0)
    if fps <= 0:
        raise SystemExit("fps missing from render payload / voiceover manifest")
    tail = int(os.environ.get("SEARCHPO_VIDEO_TAIL_FRAMES") or round(fps * 0.4))
    payload_duration = int(payload.get("durationInFrames") or 0)
    if payload_duration <= 0:
        raise SystemExit("durationInFrames missing from render payload")
    audio_frames = manifest.get("audio_frames")
    if not audio_frames:
        raise SystemExit("audio_frames missing from voiceover manifest")
    caption_duration = max(int(segment["endFrame"]) for segment in captions) + tail
    audio_duration = int(audio_frames) + tail
    return max(60, payload_duration, audio_duration, caption_duration), fps


def apply_video_profile(payload: dict[str, Any]) -> dict[str, Any]:
    raw_profile = payload.get("videoProfile") or payload.get("video_profile") or {
        "orientation": payload.get("orientation"),
        "aspect_ratio": payload.get("aspectRatio") or payload.get("aspect_ratio"),
    }
    profile = normalize_video_profile(raw_profile)
    payload["videoProfile"] = profile
    payload["orientation"] = profile["orientation"]
    payload["aspectRatio"] = profile["aspect_ratio"]
    payload["width"] = profile["width"]
    payload["height"] = profile["height"]
    storyboard = payload.get("storyboard") if isinstance(payload.get("storyboard"), dict) else {}
    style = storyboard.get("style") if isinstance(storyboard.get("style"), dict) else {}
    if not style.get("motion") and profile.get("motion"):
        style["motion"] = profile["motion"]
        storyboard["style"] = style
        payload["storyboard"] = storyboard
    return payload


def _placeholder_agent_visual_source() -> str:
    return """// @ts-nocheck
import type {FC} from 'react';
import type {AgentVisualProps} from '../AgentVisualTypes';
import './agent-visual.generated.css';

export const AgentVisualGenerated: FC<AgentVisualProps> = () => {
  throw new Error('AgentVisualGenerated is missing. Run render/prepare_remotion_input.py with provider agent_visual first.');
};
"""


def _agent_visual_source(component_body: str) -> str:
    return f"""// @ts-nocheck
import type {{FC}} from 'react';
import React, {{useMemo}} from 'react';
import {{
  AbsoluteFill,
  Img,
  Series,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useVideoConfig,
}} from 'remotion';
import type {{AgentVisualProps}} from '../AgentVisualTypes';
import './agent-visual.generated.css';

export const AgentVisualGenerated: FC<AgentVisualProps> = (props) => {{
  const {{
    data,
    frame,
    fps,
    durationInFrames,
    width,
    height,
    progress,
    audioPulse,
  }} = props;
  // Scope the generated body in its own block so it may safely re-declare any
  // prop-provided name (e.g. progress, audioPulse, frame) without an esbuild
  // "symbol has already been declared" collision against the destructured props.
  {{
{component_body.rstrip()}
  }}
}};
"""


def write_agent_visual_source(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("agentVisual") or payload.get("agent_visual")
    required = bool(payload.get("agentVisualRequired"))
    orientation = payload.get("orientation") or "vertical"
    try:
        if is_github_repo_subject(payload=payload):
            visual = require_agent_visual(premium_repo_agent_visual("prepared GitHub repo visual"), orientation)
        else:
            visual = require_agent_visual(raw, orientation) if required else normalize_agent_visual(raw, orientation)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    GENERATED_VISUAL_TSX.parent.mkdir(parents=True, exist_ok=True)
    if visual.get("enabled"):
        module_code = str(visual.get("module_code") or "").strip()
        if module_code:
            GENERATED_VISUAL_TSX.write_text(module_code.rstrip() + "\n", encoding="utf-8")
        else:
            GENERATED_VISUAL_TSX.write_text(_agent_visual_source(str(visual.get("component_code") or "")), encoding="utf-8")
        GENERATED_VISUAL_CSS.write_text(str(visual.get("css") or ""), encoding="utf-8")
    else:
        if required:
            errors = "; ".join(str(item) for item in visual.get("validation_errors") or [])
            raise SystemExit(f"agent_visual is required for provider render: {errors or 'missing'}")
        GENERATED_VISUAL_TSX.write_text(_placeholder_agent_visual_source(), encoding="utf-8")
        GENERATED_VISUAL_CSS.write_text("/* Agent visual not enabled for this contract render. */\n", encoding="utf-8")
    payload["agentVisual"] = visual
    return payload


def latest_run_dir() -> Path:
    if not LATEST_RUN_PATH.exists():
        raise SystemExit("runtime/latest_run.txt is missing; run the data pipeline first")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    source = run_dir / "render_payload.json"
    if not source.exists():
        raise SystemExit(f"render payload missing: {source}")
    payload = read_json(source)
    video_spec_path = run_dir / "video_spec.json"
    video_spec: dict[str, Any] = {}
    if video_spec_path.exists():
        video_spec = read_json(video_spec_path)
        payload["videoSpec"] = {
            "path": str(video_spec_path),
            "sha256": hashlib.sha256(video_spec_path.read_bytes()).hexdigest(),
            "id": video_spec.get("id"),
            "schema_version": video_spec.get("schema_version"),
        }
    try:
        if not payload.get("storyboard"):
            raise ValueError("render payload requires storyboard; legacy cards fallback is not allowed")
        payload["storyboard"] = validate_storyboard(payload["storyboard"])
    except ValueError as exc:
        raise SystemExit(f"render payload storyboard validation failed: {exc}") from exc
    payload = apply_video_profile(payload)
    payload = write_agent_visual_source(payload)
    voiceover_source = run_dir / "voiceover.wav"
    if not payload.get("audioSrc"):
        raise SystemExit("render payload missing audioSrc")
    if not voiceover_source.exists():
        raise SystemExit(f"render payload references audioSrc but voiceover is missing: {voiceover_source}")
    captions, captions_path = normalize_captions(run_dir)
    if captions:
        payload["captions"] = captions
    manifest = audio_manifest(run_dir)
    duration, fps = derive_duration(payload, captions, manifest)
    payload["durationInFrames"] = duration
    payload["fps"] = fps
    props_path = run_dir / "remotion_input_props.json"
    PUBLIC_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    public_voiceover = PUBLIC_GENERATED_DIR / f"{run_asset_stem(run_dir)}-voiceover.wav"
    shutil.copyfile(voiceover_source, public_voiceover)
    payload["audioSrc"] = f"{PUBLIC_GENERATED_DIR.name}/{public_voiceover.name}"
    props_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    props_sha256 = hashlib.sha256(props_path.read_bytes()).hexdigest()
    (run_dir / "render_input_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "props": str(props_path),
                "props_sha256": props_sha256,
                "public_fixture": str(ROOT / "public" / "searchpo-content.json"),
                "voiceover": str(public_voiceover),
                "voiceover_sha256": sha256_file(public_voiceover),
                "captions": str(captions_path),
                "caption_segments": len(captions),
                "durationInFrames": duration,
                "fps": fps,
                "orientation": payload.get("orientation"),
                "width": payload.get("width"),
                "height": payload.get("height"),
                "video_profile": payload.get("videoProfile"),
                "agent_visual_required": bool(payload.get("agentVisualRequired")),
                "agent_visual_enabled": bool((payload.get("agentVisual") or {}).get("enabled")),
                "agent_visual_source": str(GENERATED_VISUAL_TSX),
                "agent_visual_source_sha256": sha256_file(GENERATED_VISUAL_TSX),
                "agent_visual_css": str(GENERATED_VISUAL_CSS),
                "agent_visual_css_sha256": sha256_file(GENERATED_VISUAL_CSS),
                "audio_duration_sec": manifest.get("audio_duration_sec"),
                "audio_frames": manifest.get("audio_frames"),
                "title": payload.get("title"),
                "video_spec": str(video_spec_path) if video_spec else None,
                "video_spec_sha256": hashlib.sha256(video_spec_path.read_bytes()).hexdigest() if video_spec else None,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"props": str(props_path), "source": str(source)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
