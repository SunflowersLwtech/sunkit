#!/usr/bin/env python3
"""Write the final Searchpo run truth after render, audit, and publish checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_harness.artifact_identity import publish_conflict_errors, utc_now
from agent_harness.core import Artifact, Gate, TaskBoard, read_json, write_json
from agent_harness.service_artifacts import write_delivery_package
from agent_harness.side_effect_tiers import side_effect_axes


def _maybe_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def _status(path: Path, default: str = "missing") -> str:
    data = _maybe_json(path)
    return str(data.get("status") or default)


def _task_gate_payload(errors: list[str], artifact_status: str, publish_status: str, production_success: bool) -> dict[str, Any]:
    return {
        "artifact_status": artifact_status,
        "publish_status": publish_status,
        "production_success": production_success,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--execution-profile", choices=["provider", "lambda", "live"], help="Side-effect profile for this final media run")
    parser.add_argument("--publish-mode", required=True, choices=["contract-check", "live"])
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    agent_run_path = run_dir / "agent_run.json"
    if not agent_run_path.exists():
        raise SystemExit(f"agent_run.json missing: {agent_run_path}")
    agent_run = read_json(agent_run_path)
    root_task_id = agent_run["root_task_id"]
    board = TaskBoard(run_dir / "harness_board.sqlite3")

    try:
        snapshot_before = board.snapshot(root_task_id)
        artifact_manifest = _maybe_json(run_dir / "artifact_manifest.json")
        execution_profile = args.execution_profile or artifact_manifest.get("execution_profile")
        if not execution_profile:
            if args.publish_mode == "live":
                execution_profile = "live"
            elif artifact_manifest.get("render_mode") == "lambda":
                execution_profile = "lambda"
            else:
                execution_profile = "provider"
        axes = side_effect_axes(str(execution_profile) if execution_profile else None)
        if artifact_manifest.get("render_mode"):
            axes["render_mode"] = str(artifact_manifest.get("render_mode"))
        axes["publish_mode"] = args.publish_mode
        upload_check = _maybe_json(run_dir / "post" / "douyin_upload_check.json")
        post_verify = _maybe_json(run_dir / "post" / "post_publish_verification.json")
        render_metadata_status = _status(run_dir / "render_metadata_check.json")
        deterministic_audit_status = _status(run_dir / "visual_audit_deterministic.json")
        gemini_audit_status = _status(run_dir / "gemini_visual_audit.json", default="missing")
        premium_showcase_audit_status = _status(run_dir / "premium_showcase_audit.json", default="missing")

        errors = publish_conflict_errors(snapshot_before, args.publish_mode)
        required_files = {
            "artifact_manifest": run_dir / "artifact_manifest.json",
            "final_video": Path(str(artifact_manifest.get("final_video_path") or "")),
            "final_cover": Path(str(artifact_manifest.get("cover_path") or "")),
            "douyin_upload_check": run_dir / "post" / "douyin_upload_check.json",
        }
        for name, path in required_files.items():
            if not path.is_file():
                errors.append(f"required final artifact missing: {name} ({path})")
        if render_metadata_status != "pass":
            errors.append(f"render metadata status is {render_metadata_status}")
        if deterministic_audit_status != "pass":
            errors.append(f"deterministic visual audit status is {deterministic_audit_status}")
        if gemini_audit_status != "pass":
            errors.append(f"Gemini visual audit status is {gemini_audit_status}")
        if premium_showcase_audit_status != "pass":
            errors.append(f"premium showcase audit status is {premium_showcase_audit_status}")
        if upload_check.get("publish_mode") != args.publish_mode:
            errors.append(
                f"douyin upload check mode mismatch: {upload_check.get('publish_mode')} != {args.publish_mode}"
            )
        if upload_check.get("status") != "pass":
            errors.append("douyin upload check did not pass")

        production_success = False
        publish_status = "contract-check-pass" if args.publish_mode == "contract-check" and upload_check.get("status") == "pass" else "fail"
        if args.publish_mode == "live":
            production_success = post_verify.get("status") == "pass"
            publish_status = "verified-published" if production_success else "fail"
            if not production_success:
                errors.append("live publish requires post_publish_verification.json status=pass")

        artifact_status = "pass" if not errors else "fail"
        task_id = board.create_task("final_verification", "Final artifact and publish verification", "claude_main_agent", root_task_id)
        board.set_status(task_id, "running", "claude_main_agent", axes)
        for kind, path in required_files.items():
            if path.is_file():
                board.artifact(task_id, Artifact(kind, path))
        board.gate(
            task_id,
            Gate(
                "artifact_release_gate",
                "pass" if artifact_status == "pass" else "fail",
                "Final media, metadata, audit, and identity artifacts are complete"
                if artifact_status == "pass"
                else "Final artifact chain is incomplete",
                _task_gate_payload(errors, artifact_status, publish_status, production_success),
            ),
        )
        board.gate(
            task_id,
            Gate(
                "publish_release_gate",
                "pass" if artifact_status == "pass" else "fail",
                "Contract publish package verified; no live side effect"
                if args.publish_mode == "contract-check"
                else "Live publish verified against remote identity",
                _task_gate_payload(errors, artifact_status, publish_status, production_success),
            ),
        )
        board.set_status(
            task_id,
            "completed" if artifact_status == "pass" else "failed",
            "claude_main_agent",
            _task_gate_payload(errors, artifact_status, publish_status, production_success),
        )
        final_status = "pass" if artifact_status == "pass" else "fail"
        delivery_package = write_delivery_package(
            run_dir,
            artifact_manifest,
            status=final_status,
            publish_status=publish_status,
            errors=errors,
        )
        board.artifact(task_id, Artifact("delivery_package", run_dir / "delivery_package.json", {"status": delivery_package.get("status")}))
        snapshot_after = board.snapshot(root_task_id)
        final = {
            "schema_version": 1,
            "created_at": utc_now(),
            "run_id": run_dir.name,
            "run_dir": str(run_dir),
            "mode": args.publish_mode,
            **axes,
            "status": final_status,
            "production_success": production_success,
            "publish_status": publish_status,
            "selected_candidate_id": artifact_manifest.get("selected_candidate_id"),
            "artifact_manifest": artifact_manifest,
            "render_metadata_status": render_metadata_status,
            "deterministic_visual_audit_status": deterministic_audit_status,
            "gemini_visual_audit_status": gemini_audit_status,
            "premium_showcase_audit_status": premium_showcase_audit_status,
            "douyin_upload_check": upload_check,
            "post_publish_verification": post_verify,
            "errors": errors,
            "board_snapshot": snapshot_after,
        }
        final["delivery_package"] = str(run_dir / "delivery_package.json")
        final["delivery_package_status"] = delivery_package.get("status")
        write_json(run_dir / "run_final.json", final)
        agent_run["board_snapshot"] = snapshot_after
        agent_run["run_final"] = str(run_dir / "run_final.json")
        agent_run_path.write_text(json.dumps(agent_run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"run_final": str(run_dir / "run_final.json"), "status": final["status"], "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if final["status"] == "pass" else 1
    finally:
        board.close()


if __name__ == "__main__":
    raise SystemExit(main())
