#!/usr/bin/env python3
"""Append an external runtime stage to an existing searchpo harness board."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_harness.core import Artifact, Gate, TaskBoard


def parse_artifact(value: str) -> Artifact:
    kind, path = value.split("=", 1)
    return Artifact(kind, Path(path).resolve())


def parse_gate(value: str) -> Gate:
    name, status, summary = value.split(":", 2)
    return Gate(name, status, summary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--name", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--status", default="completed")
    parser.add_argument("--details", default="")
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--gate", action="append", default=[])
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    agent_run_path = run_dir / "agent_run.json"
    if not agent_run_path.exists():
        raise SystemExit(f"agent_run.json missing: {agent_run_path}")
    agent_run = json.loads(agent_run_path.read_text(encoding="utf-8"))
    root_task_id = agent_run["root_task_id"]
    board = TaskBoard(run_dir / "harness_board.sqlite3")
    try:
        task_id = board.create_task(args.name, args.title, args.owner, root_task_id)
        board.set_status(task_id, "running", args.owner, {"details": args.details})
        for artifact_value in args.artifact:
            board.artifact(task_id, parse_artifact(artifact_value))
        for gate_value in args.gate:
            board.gate(task_id, parse_gate(gate_value))
        board.set_status(task_id, args.status, args.owner, {"details": args.details})
        agent_run["board_snapshot"] = board.snapshot(root_task_id)
        agent_run_path.write_text(json.dumps(agent_run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"task_id": task_id, "stage": args.name, "status": args.status}, ensure_ascii=False, indent=2))
    finally:
        board.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
