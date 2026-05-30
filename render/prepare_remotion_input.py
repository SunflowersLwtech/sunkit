#!/usr/bin/env python3
"""Prepare run-scoped Remotion props without modifying tracked public fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"
PUBLIC_GENERATED_DIR = ROOT / "public" / "generated"


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
                "audio_duration_sec": manifest.get("audio_duration_sec"),
                "audio_frames": manifest.get("audio_frames"),
                "title": payload.get("title"),
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
