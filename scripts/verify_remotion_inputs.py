#!/usr/bin/env python3
"""Verify that Remotion props and generated agent visual sources are prepared."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(value: Any, run_dir: Path) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return Path("")
    path = Path(raw)
    if path.is_absolute():
        return path
    run_relative = run_dir / path
    if run_relative.exists():
        return run_relative
    return ROOT / path


def verify_render_inputs(run_dir: Path, props_path: Path) -> list[str]:
    run_dir = run_dir.resolve()
    props_path = props_path.resolve()
    manifest_path = run_dir / "render_input_manifest.json"
    errors: list[str] = []
    if not manifest_path.is_file():
        return [f"Missing render input manifest: {manifest_path}"]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"render_input_manifest.json is invalid JSON: {exc}"]
    if not isinstance(manifest, dict):
        return ["render_input_manifest.json must be a JSON object"]

    expected_props_sha = str(manifest.get("props_sha256") or "")
    if not props_path.is_file():
        errors.append(f"Missing Remotion props file: {props_path}")
    elif not expected_props_sha:
        errors.append("render_input_manifest.json missing props_sha256")
    elif sha256_file(props_path) != expected_props_sha:
        errors.append("Remotion props do not match render_input_manifest.json; rerun prepare_remotion_input.py")

    for label, path_key, sha_key in (
        ("agent visual TSX", "agent_visual_source", "agent_visual_source_sha256"),
        ("agent visual CSS", "agent_visual_css", "agent_visual_css_sha256"),
    ):
        artifact = _manifest_path(manifest.get(path_key), run_dir)
        expected_sha = str(manifest.get(sha_key) or "")
        if not str(artifact):
            errors.append(f"render_input_manifest.json missing {path_key}; rerun prepare_remotion_input.py")
        elif not artifact.is_file():
            errors.append(f"Missing prepared {label}: {artifact}")
        elif not expected_sha:
            errors.append(f"render_input_manifest.json missing {sha_key}; rerun prepare_remotion_input.py")
        elif sha256_file(artifact) != expected_sha:
            errors.append(f"Prepared {label} is stale for this run; rerun prepare_remotion_input.py")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", help="Searchpo artifact run directory")
    parser.add_argument("--props", required=True, help="Remotion props JSON file")
    args = parser.parse_args()

    errors = verify_render_inputs(Path(args.run_dir), Path(args.props))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
