#!/usr/bin/env python3
"""Prepare run-scoped Remotion props without modifying tracked public fixtures."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"
PUBLIC_GENERATED_DIR = ROOT / "public" / "generated"
PUBLIC_VOICEOVER = PUBLIC_GENERATED_DIR / "voiceover.wav"


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
    payload = json.loads(source.read_text(encoding="utf-8"))
    voiceover_source = run_dir / "voiceover.wav"
    if payload.get("audioSrc") and not voiceover_source.exists():
        raise SystemExit(f"render payload references audioSrc but voiceover is missing: {voiceover_source}")
    props_path = run_dir / "remotion_input_props.json"
    PUBLIC_GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    if voiceover_source.exists():
        shutil.copyfile(voiceover_source, PUBLIC_VOICEOVER)
        payload["audioSrc"] = f"{PUBLIC_GENERATED_DIR.name}/{PUBLIC_VOICEOVER.name}"
    props_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "render_input_manifest.json").write_text(
        json.dumps(
            {
                "props": str(props_path),
                "public_fixture": str(ROOT / "public" / "searchpo-content.json"),
                "voiceover": str(PUBLIC_VOICEOVER) if voiceover_source.exists() else None,
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
