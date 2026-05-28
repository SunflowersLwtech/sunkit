#!/usr/bin/env python3
"""Copy an agent render payload into Remotion's public input file."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"
PUBLIC_INPUT = ROOT / "public" / "searchpo-content.json"


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
    PUBLIC_INPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, PUBLIC_INPUT)
    (run_dir / "render_input_manifest.json").write_text(
        json.dumps({"public_input": str(PUBLIC_INPUT), "title": payload.get("title")}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"public_input": str(PUBLIC_INPUT), "source": str(source)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
