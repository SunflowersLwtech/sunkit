#!/usr/bin/env python3
"""Bind rendered media to the current run before any publish adapter can use it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_harness.artifact_identity import create_or_update_artifact_manifest
from scripts.cover_health import assert_cover_healthy


def _path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", help="Artifact run directory")
    parser.add_argument("--video", required=True, help="Rendered video path, usually an out/ preview file")
    parser.add_argument("--cover", required=True, help="Rendered cover path, usually an out/ preview file")
    parser.add_argument("--execution-profile", choices=["provider", "lambda", "live"], help="Side-effect profile for this media run")
    parser.add_argument("--render-mode", required=True, choices=["local", "lambda"])
    parser.add_argument("--publish-mode", required=True, choices=["contract-check", "live"])
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    cover_path = _path(args.cover)
    cover_health = assert_cover_healthy(cover_path)
    (run_dir / "cover_health.json").write_text(
        json.dumps(cover_health, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = create_or_update_artifact_manifest(
        run_dir,
        rendered_video=_path(args.video),
        rendered_cover=cover_path,
        render_mode=args.render_mode,
        publish_mode=args.publish_mode,
        execution_profile=args.execution_profile,
    )
    print(json.dumps({"artifact_manifest": str(run_dir / "artifact_manifest.json"), **manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
