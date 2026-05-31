#!/usr/bin/env python3
"""Record review/publish outcomes so strategy selection improves over time."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_metrics(args: argparse.Namespace) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for name in (
        "impressions",
        "likes",
        "reposts",
        "replies",
        "bookmarks",
        "profile_clicks",
        "engagements",
        "manual_quality",
    ):
        value = getattr(args, name)
        if value is not None:
            metrics[name] = float(value)
    if args.metrics_json:
        metrics.update({key: float(value) for key, value in read_json(Path(args.metrics_json).expanduser()).items()})
    return metrics


def compute_score(metrics: dict[str, float]) -> float:
    if "manual_quality" in metrics:
        return max(0.0, min(1.0, metrics["manual_quality"]))
    impressions = max(metrics.get("impressions", 0.0), 1.0)
    weighted = (
        metrics.get("likes", 0.0)
        + 2.0 * metrics.get("reposts", 0.0)
        + 1.5 * metrics.get("replies", 0.0)
        + 1.5 * metrics.get("bookmarks", 0.0)
        + metrics.get("profile_clicks", 0.0)
    )
    return max(0.0, min(1.0, weighted / impressions))


def count_ready_posts(posting_pack: Path) -> int:
    if not posting_pack.exists():
        return 0
    text = posting_pack.read_text(encoding="utf-8")
    return text.count("\n(") + (1 if text.startswith("(") else 0)


def infer_strategy(repo_run_dir: Path, explicit: str) -> tuple[str, dict[str, Any]]:
    if explicit:
        return explicit, {}
    for parent in [repo_run_dir, *repo_run_dir.parents]:
        decision_path = parent / "strategy_decision.json"
        if decision_path.exists():
            decision = read_json(decision_path)
            strategy_id = (
                decision.get("recommended_strategy", {}).get("strategy_id")
                or decision.get("recommended_strategy", {}).get("strategy_name")
                or "unknown"
            )
            return str(strategy_id), decision
    context = read_json(repo_run_dir / "repo_context.json") or read_json(repo_run_dir / "source_context.json")
    source_kind = str(context.get("source_kind") or context.get("kind") or "").lower()
    if source_kind == "paper":
        return "paper_to_system", {}
    if source_kind in {"github_repo", "local_repo", "local_directory"}:
        return "independent_technical_share", {}
    if source_kind == "web_url":
        return "research_then_post", {}
    return "unknown", {}


def update_profile(profile_path: Path, outcome: dict[str, Any]) -> dict[str, Any]:
    profile = read_json(profile_path)
    if not profile:
        profile = {
            "schema_version": 1,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "strategies": {},
            "global_lessons": [],
        }
    strategies = profile.setdefault("strategies", {})
    strategy_id = outcome["strategy_id"]
    item = strategies.setdefault(strategy_id, {"runs": 0, "avg_score": 0.0, "last_score": 0.0, "lessons": []})
    runs = int(item.get("runs", 0))
    score = float(outcome["score"])
    item["avg_score"] = ((float(item.get("avg_score", 0.0)) * runs) + score) / (runs + 1)
    item["runs"] = runs + 1
    item["last_score"] = score
    item["last_outcome_at"] = outcome["created_at"]
    for lesson in outcome.get("lessons", []):
        if lesson and lesson not in item["lessons"]:
            item["lessons"].append(lesson)
    item["lessons"] = item["lessons"][-12:]
    profile["updated_at"] = utc_now()
    write_json(profile_path, profile)
    return profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_run_dir", help="Run source directory containing posting_pack.md / x_publish_log.json")
    parser.add_argument("--memory-root", default=str(Path.cwd() / "repo-to-x-workspace" / "strategy-memory"))
    parser.add_argument("--strategy-id", default="")
    parser.add_argument("--metrics-json")
    parser.add_argument("--impressions", type=float)
    parser.add_argument("--likes", type=float)
    parser.add_argument("--reposts", type=float)
    parser.add_argument("--replies", type=float)
    parser.add_argument("--bookmarks", type=float)
    parser.add_argument("--profile-clicks", type=float)
    parser.add_argument("--engagements", type=float)
    parser.add_argument("--manual-quality", type=float, help="0.0-1.0 human quality score when X metrics are unavailable")
    parser.add_argument("--lesson", action="append", default=[], help="Reusable lesson from this run")
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    repo_run_dir = Path(args.repo_run_dir).expanduser().resolve()
    memory_root = Path(args.memory_root).expanduser().resolve()
    strategy_id, decision = infer_strategy(repo_run_dir, args.strategy_id)
    metrics = parse_metrics(args)
    score = compute_score(metrics)
    publish_log = read_json(repo_run_dir / "x_publish_log.json")
    images_manifest = read_json(repo_run_dir / "images_manifest.json")
    cross_check = (repo_run_dir / "cross_check_review.md").read_text(encoding="utf-8") if (repo_run_dir / "cross_check_review.md").exists() else ""
    outcome = {
        "schema_version": 1,
        "created_at": utc_now(),
        "repo_run_dir": str(repo_run_dir),
        "strategy_id": strategy_id,
        "source_kind": read_json(repo_run_dir / "repo_context.json").get("source_kind", ""),
        "score": score,
        "metrics": metrics,
        "lessons": args.lesson,
        "note": args.note,
        "post_count": count_ready_posts(repo_run_dir / "posting_pack.md"),
        "image_count": len(images_manifest.get("images", [])),
        "image_models": sorted({str(image.get("model", "")) for image in images_manifest.get("images", []) if image.get("model")}),
        "cross_check_pass": "status: pass" in cross_check.lower(),
        "published": bool(publish_log and not publish_log.get("dry_run") and publish_log.get("posts")),
        "tweet_ids": [post.get("tweet_id") for post in publish_log.get("posts", []) if post.get("tweet_id")],
        "strategy_decision_loaded": bool(decision),
    }
    append_jsonl(memory_root / "outcomes.jsonl", outcome)
    update_profile(memory_root / "strategy_profile.json", outcome)
    write_json(repo_run_dir / "post_outcome.json", outcome)
    print(f"Recorded outcome: {memory_root / 'outcomes.jsonl'}")
    print(f"Updated profile: {memory_root / 'strategy_profile.json'}")
    print(f"Score: {score:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
