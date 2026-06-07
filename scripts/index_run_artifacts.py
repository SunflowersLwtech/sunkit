#!/usr/bin/env python3
"""Write a human-readable RUN.md index for a Searchpo artifact run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_harness.artifact_index import write_run_index

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"


def latest_run_dir() -> Path:
    if not LATEST_RUN_PATH.exists():
        raise SystemExit("runtime/latest_run.txt is missing")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip()).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    args = parser.parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else latest_run_dir()
    index_path = write_run_index(run_dir)
    print(json.dumps({"run_index": str(index_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
