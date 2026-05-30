#!/usr/bin/env python3
"""Run the tracked sync agent harness over a searchpo subject input."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_harness.core import HarnessContext, StageResult, SyncHarness, TaskBoard, utc_now, write_json
from agent_harness.stages import PROVIDER_ENV_CONTRACT, default_stages
from agent_harness.subjects import write_operator_topic_run

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"


def latest_run_dir() -> Path:
    if not LATEST_RUN_PATH.exists():
        raise SystemExit("runtime/latest_run.txt is missing; run data_prep/scripts/run_pipeline.py first")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip())


def build_agent_state(
    run_dir: Path,
    board: TaskBoard,
    root_task_id: str,
    stage_results: list[StageResult],
    selected_candidate: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "mode": mode,
        "run_dir": str(run_dir),
        "board_db": str(board.db_path),
        "root_task_id": root_task_id,
        "main_agent": "claude_main_agent",
        "impl_agent": "claude_impl_agent",
        "loop": [
            {"step": result.step, "status": "pass" if result.status == "completed" else result.status, "details": result.details}
            for result in stage_results
        ],
        "selected_candidate_id": selected_candidate["candidate_id"],
        "selected_candidate": selected_candidate,
        "subject_input_mode": selected_candidate.get("input_mode") or "shortlist",
        "subject_selection_source": selected_candidate.get("selection_source") or "candidate_shortlist",
        "provider_env_contract": PROVIDER_ENV_CONTRACT,
        "board_snapshot": board.snapshot(root_task_id),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    parser.add_argument("--topic", help="Operator-specified topic to analyze instead of running shortlist selection.")
    parser.add_argument("--topic-summary", help="Optional operator context for --topic.")
    parser.add_argument("--topic-url", help="Optional source URL boundary for --topic.")
    parser.add_argument("--topic-source", default="operator_topic", help="Evidence source label for --topic.")
    parser.add_argument(
        "--mode",
        choices=["contract", "provider"],
        default=os.environ.get("SEARCHPO_AGENT_MODE", "contract"),
        help="contract avoids provider API calls; provider runs DeepSeek and Gemini adapters.",
    )
    parser.add_argument(
        "--resume-from",
        type=int,
        default=0,
        help="Resume from stage index N (0-based). Stages before N are skipped if previously completed.",
    )
    args = parser.parse_args()

    if args.topic:
        run_dir = write_operator_topic_run(
            ROOT,
            topic=args.topic,
            summary=args.topic_summary,
            url=args.topic_url,
            source=args.topic_source,
            run_dir=Path(args.run_dir).resolve() if args.run_dir else None,
        )
    else:
        run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    board = TaskBoard(run_dir / "harness_board.sqlite3")
    try:
        context = HarnessContext(root_dir=ROOT, run_dir=run_dir, board=board)
        result = SyncHarness(default_stages(include_providers=args.mode == "provider")).run(context, resume_from=args.resume_from)
        selected_candidate = context.state["selected_candidate"]
        agent_state = build_agent_state(
            run_dir,
            board,
            result.root_task_id,
            result.stage_results,
            selected_candidate,
            f"searchpo-{args.mode}-script-flow",
        )
        write_json(run_dir / "agent_run.json", agent_state)
        print(
            json.dumps(
                {
                    "run_dir": str(run_dir),
                    "selected_candidate_id": selected_candidate["candidate_id"],
                    "post_dir": str(context.state["post_dir"]),
                    "render_payload": str(run_dir / "render_payload.json"),
                    "board_db": str(board.db_path),
                    "agent_run": str(run_dir / "agent_run.json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        board.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
