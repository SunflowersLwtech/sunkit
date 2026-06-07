#!/usr/bin/env python3
"""Backfill run-scoped Douyin covers and upload manifests for existing runs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_harness.artifact_identity import create_or_update_artifact_manifest  # noqa: E402
from agent_harness.artifact_paths import legacy_preview_globs, preview_output_paths  # noqa: E402
from scripts.cover_health import analyze_cover  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def run_dirs(explicit: list[str]) -> list[Path]:
    if explicit:
        return [Path(value).expanduser().resolve() for value in explicit]
    return sorted(path.parent.parent for path in (ROOT / "runtime" / "artifacts").glob("*/*/post/douyin_upload_manifest.json"))


def is_run_scoped(path: Path, run_dir: Path) -> bool:
    try:
        path.resolve().relative_to(run_dir.resolve())
        return True
    except ValueError:
        return False


def is_run_named(path: Path, run_id: str) -> bool:
    return run_id in path.name


def infer_publish_mode(run_dir: Path, upload_manifest: dict[str, Any]) -> str:
    check = read_json(run_dir / "post" / "douyin_upload_check.json")
    return str(check.get("publish_mode") or upload_manifest.get("publish_mode") or "contract-check")


def find_video(run_dir: Path, upload_manifest: dict[str, Any]) -> Path | None:
    manifest = read_json(run_dir / "artifact_manifest.json")
    candidates = [
        resolve_path(manifest.get("final_video_path")),
        run_dir / "video" / "final.mp4",
        resolve_path(upload_manifest.get("expected_video_path")),
    ]
    for pattern in legacy_preview_globs(run_dir, media="video"):
        candidates.extend(sorted((ROOT / "out").glob(pattern)))
    for candidate in candidates:
        if not candidate or not candidate.is_file():
            continue
        if is_run_scoped(candidate, run_dir) or is_run_named(candidate, run_dir.name):
            return candidate
    return None


def find_cover(run_dir: Path, upload_manifest: dict[str, Any]) -> Path | None:
    manifest = read_json(run_dir / "artifact_manifest.json")
    candidates = [
        resolve_path(manifest.get("cover_path")),
        run_dir / "cover" / "final.jpg",
        resolve_path(upload_manifest.get("cover_path")),
    ]
    for pattern in legacy_preview_globs(run_dir, media="cover"):
        candidates.extend(sorted((ROOT / "out").glob(pattern)))
    for candidate in candidates:
        if not candidate or not candidate.is_file():
            continue
        if is_run_scoped(candidate, run_dir) or is_run_named(candidate, run_dir.name):
            return candidate
    return None


def render_run(run_dir: Path, *, render_video: bool) -> tuple[Path | None, Path | None, dict[str, Any]]:
    props = run_dir / "remotion_input_props.json"
    if not props.is_file():
        return None, None, {"status": "skipped", "reason": "remotion_input_props.json missing"}
    env = os.environ.copy()
    env["SEARCHPO_RUN_DIR"] = str(run_dir)
    video_out, cover_out = preview_output_paths(ROOT, run_dir, backend="local", purpose="backfill")
    result: dict[str, Any] = {"status": "pass", "commands": []}
    try:
        if render_video:
            video_env = {**env, "SEARCHPO_RENDER_OUTPUT": str(video_out)}
            proc = subprocess.run(
                ["bash", "scripts/remotion_render.sh", "local"],
                cwd=ROOT,
                env=video_env,
                text=True,
                capture_output=True,
                timeout=600,
                check=False,
            )
            result["commands"].append({"action": "video", "returncode": proc.returncode, "stderr": proc.stderr[-1200:]})
            if proc.returncode != 0:
                return None, None, {**result, "status": "fail"}
        cover_env = {**env, "SEARCHPO_COVER_OUTPUT": str(cover_out)}
        proc = subprocess.run(
            ["bash", "scripts/remotion_render.sh", "cover"],
            cwd=ROOT,
            env=cover_env,
            text=True,
            capture_output=True,
            timeout=240,
            check=False,
        )
        result["commands"].append({"action": "cover", "returncode": proc.returncode, "stderr": proc.stderr[-1200:]})
        if proc.returncode != 0:
            return video_out if video_out.is_file() else None, None, {**result, "status": "fail"}
    except subprocess.TimeoutExpired as exc:
        return None, None, {"status": "fail", "reason": f"render timed out after {exc.timeout}s"}
    return video_out if render_video and video_out.is_file() else None, cover_out if cover_out.is_file() else None, result


def process_run(run_dir: Path, *, apply: bool, rerender_video: bool) -> dict[str, Any]:
    upload_manifest = read_json(run_dir / "post" / "douyin_upload_manifest.json")
    publish_mode = infer_publish_mode(run_dir, upload_manifest)
    video = find_video(run_dir, upload_manifest)
    cover = find_cover(run_dir, upload_manifest)
    render_result: dict[str, Any] = {"status": "not-run"}

    if rerender_video or cover is None:
        rendered_video, rendered_cover, render_result = render_run(run_dir, render_video=rerender_video)
        video = rendered_video or video
        cover = rendered_cover or cover

    cover_health = analyze_cover(cover) if cover else {"status": "fail", "errors": ["cover missing"]}
    action = "bind" if video and cover and cover_health.get("status") == "pass" else "skip"
    entry: dict[str, Any] = {
        "run_dir": str(run_dir),
        "publish_mode": publish_mode,
        "video": str(video) if video else "",
        "cover": str(cover) if cover else "",
        "cover_health": cover_health,
        "render": render_result,
        "action": action,
        "applied": False,
    }
    if action == "bind" and apply:
        manifest = create_or_update_artifact_manifest(
            run_dir,
            rendered_video=video,
            rendered_cover=cover,
            render_mode="lambda" if "lambda" in video.name else "local",
            publish_mode=publish_mode if publish_mode in {"contract-check", "live"} else "contract-check",
        )
        write_json(run_dir / "cover_health.json", cover_health)
        entry["artifact_manifest"] = str(run_dir / "artifact_manifest.json")
        entry["publish_hash"] = manifest.get("publish_hash")
        entry["applied"] = True
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", action="append", default=[], help="Specific run dir to process; repeatable")
    parser.add_argument("--apply", action="store_true", help="Copy healthy media into run-scoped final paths and update manifests")
    parser.add_argument("--rerender-video", action="store_true", help="Re-render MP4s with the current non-black first-frame poster")
    parser.add_argument("--published-only", action="store_true", help="Only process runs whose upload check or manifest says live")
    parser.add_argument("--report", default=str(ROOT / "runtime" / "cover_backfill_report.json"), help="Report JSON path")
    args = parser.parse_args()

    entries = []
    for run_dir in run_dirs(args.run_dir):
        upload_manifest = read_json(run_dir / "post" / "douyin_upload_manifest.json")
        if args.published_only and infer_publish_mode(run_dir, upload_manifest) != "live":
            continue
        entries.append(process_run(run_dir, apply=args.apply, rerender_video=args.rerender_video))

    report = {
        "schema_version": 1,
        "created_at": utc_now(),
        "apply": args.apply,
        "rerender_video": args.rerender_video,
        "published_only": args.published_only,
        "entries": entries,
        "summary": {
            "total": len(entries),
            "applied": sum(1 for item in entries if item.get("applied")),
            "bindable": sum(1 for item in entries if item.get("action") == "bind"),
            "skipped": sum(1 for item in entries if item.get("action") == "skip"),
        },
    }
    write_json(Path(args.report), report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
