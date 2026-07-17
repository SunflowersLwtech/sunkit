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
from agent_harness.artifact_index import write_run_index
from agent_harness.core import Artifact, Gate, TaskBoard, read_json, write_json
from agent_harness.runtime_contracts import MAIN_AGENT, RELEASE_GATE_FILENAME, write_release_gate
from agent_harness.service_artifacts import write_delivery_package
from agent_harness.side_effect_tiers import side_effect_axes
from scripts.gemini_visual_audit import audit_contract_errors

NATIVE_GEMINI_VIDEO_INPUT_MODES = {"file_api", "inline_video", "agent_platform"}
MIN_DETERMINISTIC_AUDIT_SCHEMA_VERSION = 2


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


def _expected_orientation(run_dir: Path) -> str:
    render_payload = _maybe_json(run_dir / "render_payload.json")
    profile = render_payload.get("videoProfile") if isinstance(render_payload.get("videoProfile"), dict) else {}
    orientation = str(render_payload.get("orientation") or profile.get("orientation") or "vertical").lower()
    return "horizontal" if orientation == "horizontal" else "vertical"


def _gemini_release_errors(gemini_audit: dict[str, Any], *, expected_orientation: str = "vertical") -> list[str]:
    errors: list[str] = []
    input_mode = str(gemini_audit.get("video_input_mode") or "")
    if input_mode not in NATIVE_GEMINI_VIDEO_INPUT_MODES:
        errors.append(f"Gemini visual audit did not record native video input mode: {input_mode or 'missing'}")
    if not gemini_audit.get("video_sha256"):
        errors.append("Gemini visual audit missing audited video_sha256")
    contract_errors = [str(item) for item in gemini_audit.get("audit_contract_errors") or [] if str(item).strip()]
    audit = gemini_audit.get("audit") if isinstance(gemini_audit.get("audit"), dict) else {}
    recomputed_contract_errors = audit_contract_errors(audit, expected_orientation=expected_orientation)
    for item in recomputed_contract_errors:
        if item not in contract_errors:
            contract_errors.append(item)
    if contract_errors:
        errors.append("Gemini visual audit contract errors: " + "; ".join(contract_errors))
    timeline_reviews = audit.get("timeline_reviews") if isinstance(audit.get("timeline_reviews"), list) else []
    if len(timeline_reviews) < 3:
        errors.append("Gemini visual audit missing native-video timeline_reviews evidence")
    return errors


def _deterministic_release_errors(deterministic_audit: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema_version = deterministic_audit.get("schema_version")
    try:
        schema_version_int = int(schema_version)
    except (TypeError, ValueError):
        schema_version_int = 0
    if schema_version_int < MIN_DETERMINISTIC_AUDIT_SCHEMA_VERSION:
        errors.append(
            "deterministic visual audit is stale; missing Douyin layout and central motion checks "
            f"(schema_version={schema_version or 'missing'})"
        )
    layout_check = deterministic_audit.get("layout_check") if isinstance(deterministic_audit.get("layout_check"), dict) else {}
    if layout_check.get("status") != "pass":
        errors.append("deterministic Douyin layout check did not pass")
    visual_intent_check = deterministic_audit.get("visual_intent_check") if isinstance(deterministic_audit.get("visual_intent_check"), dict) else {}
    if visual_intent_check.get("status") != "pass":
        errors.append("deterministic agent_visual intent check did not pass")
    motion_check = deterministic_audit.get("motion_check") if isinstance(deterministic_audit.get("motion_check"), dict) else {}
    if motion_check.get("status") != "pass":
        errors.append("deterministic central motion check did not pass")
    return errors


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
        manual_visual_review = _maybe_json(run_dir / "manual_visual_review.json")
        render_metadata_status = _status(run_dir / "render_metadata_check.json")
        deterministic_audit_status = _status(run_dir / "visual_audit_deterministic.json")
        gemini_audit_status = _status(run_dir / "gemini_visual_audit.json", default="missing")
        premium_showcase_audit_status = _status(run_dir / "premium_showcase_audit.json", default="missing")

        allow_live_upgrade = (
            args.publish_mode == "live"
            and artifact_manifest.get("publish_mode") == "live"
            and upload_check.get("publish_mode") == "live"
            and upload_check.get("status") == "pass"
            and post_verify.get("status") == "pass"
        )
        errors = publish_conflict_errors(snapshot_before, args.publish_mode, allow_live_upgrade=allow_live_upgrade)
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
        errors.extend(_deterministic_release_errors(_maybe_json(run_dir / "visual_audit_deterministic.json")))
        if gemini_audit_status != "pass":
            errors.append(f"Gemini visual audit status is {gemini_audit_status}")
        if premium_showcase_audit_status != "pass":
            errors.append(f"premium showcase audit status is {premium_showcase_audit_status}")
        errors.extend(
            _gemini_release_errors(
                _maybe_json(run_dir / "gemini_visual_audit.json"),
                expected_orientation=_expected_orientation(run_dir),
            )
        )
        if manual_visual_review and manual_visual_review.get("status") != "pass":
            reason = manual_visual_review.get("reason") or manual_visual_review.get("summary") or "manual visual review failed"
            errors.append(f"manual visual review status is {manual_visual_review.get('status')}: {reason}")
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
        task_id = board.create_task("final_verification", "Final artifact and publish verification", MAIN_AGENT, root_task_id)
        board.set_status(task_id, "running", MAIN_AGENT, axes)
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
            MAIN_AGENT,
            _task_gate_payload(errors, artifact_status, publish_status, production_success),
        )
        final_status = "pass" if artifact_status == "pass" else "fail"
        release_gate = write_release_gate(
            run_dir,
            status=final_status,
            publish_status=publish_status,
            artifact_status=artifact_status,
            production_success=production_success,
            axes=axes,
            errors=errors,
            artifact_manifest=artifact_manifest,
            upload_check=upload_check,
            post_publish_verification=post_verify,
        )
        delivery_package = write_delivery_package(
            run_dir,
            artifact_manifest,
            status=final_status,
            publish_status=publish_status,
            errors=errors,
        )
        board.artifact(task_id, Artifact("release_gate", run_dir / RELEASE_GATE_FILENAME, {"status": release_gate.get("status")}))
        board.artifact(task_id, Artifact("delivery_package", run_dir / "delivery_package.json", {"status": delivery_package.get("status")}))
        snapshot_after = board.snapshot(root_task_id)
        run_index_path = run_dir / "RUN.md"
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
            "artifact_manifest_path": str(run_dir / "artifact_manifest.json"),
            "artifact_manifest": artifact_manifest,
            "final_video": artifact_manifest.get("final_video_path"),
            "final_cover": artifact_manifest.get("cover_path"),
            "preview_video": artifact_manifest.get("preview_video_path"),
            "preview_cover": artifact_manifest.get("preview_cover_path"),
            "render_metadata_status": render_metadata_status,
            "deterministic_visual_audit_status": deterministic_audit_status,
            "gemini_visual_audit_status": gemini_audit_status,
            "premium_showcase_audit_status": premium_showcase_audit_status,
            "manual_visual_review": manual_visual_review,
            "douyin_upload_check": upload_check,
            "post_publish_verification": post_verify,
            "release_gate": str(run_dir / RELEASE_GATE_FILENAME),
            "release_gate_status": release_gate.get("status"),
            "run_index": str(run_index_path),
            "errors": errors,
            "board_snapshot": snapshot_after,
        }
        final["delivery_package"] = str(run_dir / "delivery_package.json")
        final["delivery_package_status"] = delivery_package.get("status")
        write_json(run_dir / "run_final.json", final)
        write_run_index(
            run_dir,
            final=final,
            artifact_manifest=artifact_manifest,
            delivery_package=delivery_package,
            release_gate=release_gate,
        )
        agent_run["board_snapshot"] = snapshot_after
        agent_run["run_final"] = str(run_dir / "run_final.json")
        agent_run_path.write_text(json.dumps(agent_run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"run_final": str(run_dir / "run_final.json"), "status": final["status"], "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if final["status"] == "pass" else 1
    finally:
        board.close()


if __name__ == "__main__":
    raise SystemExit(main())
