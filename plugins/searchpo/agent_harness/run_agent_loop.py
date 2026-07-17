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
from agent_harness.runtime_contracts import HARNESS_ACTOR, IMPL_AGENT, MAIN_AGENT, RESEARCH_AGENT
from agent_harness.side_effect_tiers import side_effect_axes
from agent_harness.stages import PROVIDER_ENV_CONTRACT, default_stages
from agent_harness.subjects import write_operator_topic_run

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"
DELEGATION_MODES = ("single_harness", "manual_fallback", "spawned_subagents")
DELEGATION_AGENTS = (HARNESS_ACTOR, MAIN_AGENT, RESEARCH_AGENT, IMPL_AGENT)
OPERATOR_INPUT_MESSAGE = """Searchpo now expects an operator-supplied topic or link.
Pass --topic "..." for widesearch from a topic, or SEARCHPO_LINK/SEARCHPO_TOPIC_URL through scripts/run_e2e.sh for a canonical source boundary.
Set SEARCHPO_ENABLE_DAILY_RADAR=1 only when you explicitly want the legacy source-registry candidate sweep."""


def latest_run_dir() -> Path:
    if not LATEST_RUN_PATH.exists():
        raise SystemExit("runtime/latest_run.txt is missing; run data_prep/scripts/run_pipeline.py first")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip())


def _is_http_url(value: str | None) -> bool:
    return bool(value and value.startswith(("http://", "https://")))


def build_agent_state(
    run_dir: Path,
    board: TaskBoard,
    root_task_id: str,
    stage_results: list[StageResult],
    selected_candidate: dict[str, Any],
    mode: str,
    delegation: dict[str, Any],
    *,
    resume_from: int,
    stop_after: str | None,
) -> dict[str, Any]:
    env_profile = os.environ.get("SEARCHPO_EXECUTION_PROFILE") or os.environ.get("SEARCHPO_E2E_PROFILE")
    default_profile = "provider" if mode.startswith("searchpo-provider") else "contract"
    axes = side_effect_axes(env_profile or default_profile)
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "mode": mode,
        **axes,
        "run_dir": str(run_dir),
        "board_db": str(board.db_path),
        "root_task_id": root_task_id,
        "main_agent": MAIN_AGENT,
        "research_agent": RESEARCH_AGENT,
        "impl_agent": IMPL_AGENT,
        "delegation": delegation,
        "resume_from": resume_from,
        "stop_after": stop_after,
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


def build_delegation_record(args: argparse.Namespace) -> dict[str, Any]:
    mode = str(args.delegation_mode)
    executor = str(args.delegation_agent or HARNESS_ACTOR)
    proof = str(args.delegation_proof or "").strip()
    if mode == "spawned_subagents" and not proof:
        raise SystemExit("--delegation-proof is required when --delegation-mode=spawned_subagents")
    if mode != "spawned_subagents" and proof:
        raise SystemExit("--delegation-proof is only valid with --delegation-mode=spawned_subagents")
    return {
        "schema_version": 1,
        "mode": mode,
        "executor": executor,
        "proof": proof or None,
        "owner_labels_are_execution_proof": False,
        "proof_artifact": "agent_run.json#delegation",
        "contract": (
            "spawned_subagents requires host subagent proof; manual_fallback and single_harness "
            "must not be reported as real agent-team execution."
        ),
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
    parser.add_argument(
        "--stop-after",
        choices=[stage.name for stage in default_stages(include_providers=True)],
        help="Stop after the named harness stage, preserving harness_state.json for a later --resume-from.",
    )
    parser.add_argument(
        "--delegation-mode",
        choices=DELEGATION_MODES,
        default=os.environ.get("SEARCHPO_DELEGATION_MODE", "single_harness"),
        help="Record how this invocation was executed; owner labels alone never prove spawned subagents.",
    )
    parser.add_argument(
        "--delegation-agent",
        choices=DELEGATION_AGENTS,
        default=os.environ.get("SEARCHPO_DELEGATION_AGENT", HARNESS_ACTOR),
        help="Record the host-side executor for this invocation.",
    )
    parser.add_argument(
        "--delegation-proof",
        default=os.environ.get("SEARCHPO_DELEGATION_PROOF", ""),
        help="Host subagent/thread identifier proving spawned_subagents mode.",
    )
    args = parser.parse_args()
    delegation = build_delegation_record(args)
    os.environ["SEARCHPO_DELEGATION_MODE"] = delegation["mode"]
    if not os.environ.get("SEARCHPO_EXECUTION_PROFILE") and not os.environ.get("SEARCHPO_E2E_PROFILE"):
        os.environ["SEARCHPO_EXECUTION_PROFILE"] = "provider" if args.mode == "provider" else "contract"
    if args.topic_url and not _is_http_url(args.topic_url.strip()):
        print("--topic-url must be an http(s) URL", file=sys.stderr)
        return 2

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
        if not args.run_dir and os.environ.get("SEARCHPO_ENABLE_DAILY_RADAR", "0") != "1":
            print(OPERATOR_INPUT_MESSAGE, file=sys.stderr)
            return 2
        run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    board = TaskBoard(run_dir / "harness_board.sqlite3")
    try:
        context = HarnessContext(root_dir=ROOT, run_dir=run_dir, board=board)
        context.state["delegation"] = delegation
        result = SyncHarness(default_stages(include_providers=args.mode == "provider")).run(
            context,
            resume_from=args.resume_from,
            stop_after=args.stop_after,
        )
        selected_candidate = context.state["selected_candidate"]
        agent_state = build_agent_state(
            run_dir,
            board,
            result.root_task_id,
            result.stage_results,
            selected_candidate,
            f"searchpo-{args.mode}-script-flow",
            delegation,
            resume_from=args.resume_from,
            stop_after=args.stop_after,
        )
        write_json(run_dir / "agent_run.json", agent_state)
        output = {
            "run_dir": str(run_dir),
            "selected_candidate_id": selected_candidate["candidate_id"],
            "board_db": str(board.db_path),
            "agent_run": str(run_dir / "agent_run.json"),
            "delegation_mode": delegation["mode"],
        }
        if context.state.get("post_dir"):
            output["post_dir"] = str(context.state["post_dir"])
        if args.stop_after:
            output["stopped_after"] = args.stop_after
        render_payload_path = run_dir / "render_payload.json"
        if render_payload_path.exists():
            output["render_payload"] = str(render_payload_path)
        for key, filename in [
            ("topic_brief", "topic_brief.json"),
            ("fact_bank", "fact_bank.json"),
            ("source_map", "source_map.json"),
            ("script", "script.json"),
            ("scene_plan", "scene_plan.json"),
            ("video_spec", "video_spec.json"),
            ("delivery_package", "delivery_package.json"),
            ("analytics_feedback", "analytics_feedback.json"),
            ("environment_manifest", "environment_manifest.json"),
            ("main_task_plan", "main_task_plan.json"),
            ("runtime_contract", "runtime_contract.json"),
            ("research_barrier", "research_barrier.json"),
            ("implementation_loop", "implementation_loop.json"),
        ]:
            artifact_path = run_dir / filename
            if artifact_path.exists():
                output[key] = str(artifact_path)
        evidence_bundle_path = run_dir / "evidence_bundle.json"
        cross_check_path = run_dir / "cross_check_review.json"
        if evidence_bundle_path.exists():
            output["evidence_bundle"] = str(evidence_bundle_path)
        if cross_check_path.exists():
            output["cross_check_review"] = str(cross_check_path)
        print(
            json.dumps(
                output,
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        board.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
