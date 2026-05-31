#!/usr/bin/env python3
"""Machine-check rendered MP4 metadata before semantic visual audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(video: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required for render metadata verification")
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(video),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {video}: {proc.stderr[-1200:]}")
    return json.loads(proc.stdout)


def rate_to_float(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", help="Artifact run directory")
    parser.add_argument("--video", required=True, help="Rendered MP4 path")
    parser.add_argument("--output", help="Output JSON path. Defaults to run_dir/render_metadata_check.json")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    video = Path(args.video).expanduser()
    if not video.is_absolute():
        video = ROOT / video
    output = Path(args.output).resolve() if args.output else run_dir / "render_metadata_check.json"
    props = read_json(run_dir / "remotion_input_props.json")

    errors: list[str] = []
    warnings: list[str] = []
    if not video.is_file():
        errors.append(f"Rendered video missing: {video}")
        metadata: dict[str, Any] = {}
    else:
        metadata = probe(video)
    streams = metadata.get("streams") or []
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    fmt = metadata.get("format") or {}

    expected_fps = int(props.get("fps") or 30)
    expected_frames = int(props.get("durationInFrames") or 360)
    expected_duration = expected_frames / float(expected_fps)
    actual_duration = float(fmt.get("duration") or 0)
    duration_tolerance = max(0.5, expected_duration * 0.03)
    actual_fps = rate_to_float(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))

    checks = {
        "exists": video.is_file(),
        "video_sha256": sha256_file(video) if video.is_file() else None,
        "video_bytes": video.stat().st_size if video.is_file() else None,
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "video_codec": video_stream.get("codec_name"),
        "pixel_format": video_stream.get("pix_fmt"),
        "fps": actual_fps,
        "duration_sec": actual_duration,
        "audio_codec": audio_stream.get("codec_name"),
    }

    compatible_pixel_formats = {"yuv420p", "yuvj420p"}

    if video.is_file():
        if video_stream.get("width") != 1080 or video_stream.get("height") != 1920:
            errors.append(f"Expected 1080x1920, got {video_stream.get('width')}x{video_stream.get('height')}")
        if video_stream.get("codec_name") != "h264":
            errors.append(f"Expected h264 video, got {video_stream.get('codec_name')}")
        if video_stream.get("pix_fmt") not in compatible_pixel_formats:
            errors.append(f"Expected 4:2:0 pixel format, got {video_stream.get('pix_fmt')}")
        if actual_fps is None or abs(actual_fps - expected_fps) > 0.1:
            errors.append(f"Expected {expected_fps}fps, got {actual_fps}")
        if abs(actual_duration - expected_duration) > duration_tolerance:
            errors.append(
                f"Expected duration {expected_duration:.2f}s from props, got {actual_duration:.2f}s"
            )
        if props.get("audioSrc") and audio_stream.get("codec_name") != "aac":
            errors.append(f"Expected AAC audio for audioSrc, got {audio_stream.get('codec_name')}")

    result = {
        "schema_version": 1,
        "created_at": utc_now(),
        "status": "pass" if not errors else "fail",
        "run_dir": str(run_dir),
        "video_path": str(video),
        "expected": {
            "width": 1080,
            "height": 1920,
            "fps": expected_fps,
            "durationInFrames": expected_frames,
            "duration_sec": expected_duration,
            "video_codec": "h264",
            "pixel_format": sorted(compatible_pixel_formats),
            "audio_codec": "aac" if props.get("audioSrc") else None,
        },
        "policy": {
            "render_policy": "douyin_h264_1080x1920_aac_420p",
            "searchpo_policy_sha256": sha256_file(ROOT / "config" / "searchpo_policy.json")
            if (ROOT / "config" / "searchpo_policy.json").is_file()
            else None,
        },
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"render_metadata_check": str(output), "status": result["status"], "errors": errors, "warnings": warnings}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
