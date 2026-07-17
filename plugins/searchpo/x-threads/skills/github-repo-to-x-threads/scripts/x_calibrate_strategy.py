#!/usr/bin/env python3
"""Update local strategy memory from x_metrics_snapshot.json and post_eval.json."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from record_post_outcome import compute_score, infer_strategy, read_json, update_profile, append_jsonl, write_json, utc_now  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_run_dir")
    parser.add_argument("--memory-root", default=str(Path.cwd() / "repo-to-x-workspace" / "strategy-memory"))
    parser.add_argument("--manual-quality", type=float, help="0.0-1.0 human taste score; overrides metrics score when present")
    parser.add_argument("--lesson", action="append", default=[])
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    repo_run_dir = Path(args.repo_run_dir).expanduser().resolve()
    metrics_snapshot = read_json(repo_run_dir / "x_metrics_snapshot.json")
    if not metrics_snapshot:
        raise SystemExit("x_metrics_snapshot.json missing. Run x_collect_metrics.py first.")
    metrics = metrics_snapshot.get("aggregate_metrics") or {}
    if args.manual_quality is not None:
        metrics = dict(metrics)
        metrics["manual_quality"] = max(0.0, min(1.0, float(args.manual_quality)))
    post_eval = read_json(repo_run_dir / "post_eval.json")
    strategy_id, decision = infer_strategy(repo_run_dir, "")
    score = compute_score(metrics)
    outcome = {
        "schema_version": 1,
        "created_at": utc_now(),
        "repo_run_dir": str(repo_run_dir),
        "strategy_id": strategy_id,
        "score": score,
        "metrics": metrics,
        "lessons": args.lesson,
        "note": args.note,
        "pre_publish_eval": {
            "final_score": post_eval.get("final_score"),
            "decision": post_eval.get("decision"),
            "scores": post_eval.get("scores", {}),
        },
        "tweet_ids": metrics_snapshot.get("tweet_ids", []),
        "strategy_decision_loaded": bool(decision),
    }
    memory_root = Path(args.memory_root).expanduser().resolve()
    append_jsonl(memory_root / "outcomes.jsonl", outcome)
    update_profile(memory_root / "strategy_profile.json", outcome)
    write_json(repo_run_dir / "post_outcome.json", outcome)
    print(f"Calibrated strategy={strategy_id}, score={score:.4f}")
    print(f"Updated: {memory_root / 'strategy_profile.json'}")
    print(f"Wrote: {repo_run_dir / 'post_outcome.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
