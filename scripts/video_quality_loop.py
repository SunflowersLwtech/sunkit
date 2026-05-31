#!/usr/bin/env python3
"""Run render/audit/improve attempts before Searchpo publish checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_harness.policy import policy_get


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 900) -> dict[str, Any]:
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    result = {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-2400:],
        "stderr_tail": proc.stderr[-3000:],
    }
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-2000:]}")
    return result


def record_stage(
    run_dir: Path,
    *,
    name: str,
    title: str,
    owner: str = "claude_impl_agent",
    status: str = "completed",
    artifacts: dict[str, Path] | None = None,
    gates: list[tuple[str, str, str]] | None = None,
    details: str = "",
) -> None:
    if not (run_dir / "agent_run.json").exists():
        return
    cmd = [
        sys.executable,
        "agent_harness/record_runtime_stage.py",
        str(run_dir),
        "--name",
        name,
        "--title",
        title,
        "--owner",
        owner,
        "--status",
        status,
        "--details",
        details,
    ]
    for kind, path in (artifacts or {}).items():
        cmd.extend(["--artifact", f"{kind}={path}"])
    for gate_name, gate_status, summary in gates or []:
        cmd.extend(["--gate", f"{gate_name}:{gate_status}:{summary}"])
    run_command(cmd, timeout=60)


def copy_artifact(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)


def bounded_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def shorten_nested_text(value: Any, limit: int = 72) -> Any:
    if isinstance(value, str):
        return bounded_text(value, limit)
    if isinstance(value, list):
        return [shorten_nested_text(item, max(36, limit - 8)) for item in value[:4]]
    if isinstance(value, dict):
        return {key: shorten_nested_text(item, 54 if key in {"title", "heading", "value"} else limit) for key, item in value.items()}
    return value


def apply_video_repair(run_dir: Path, route: str, attempt: int, decision: dict[str, Any]) -> dict[str, Any]:
    payload_path = run_dir / "render_payload.json"
    if not payload_path.exists():
        return {"status": "skipped", "reason": "render_payload.json missing"}
    payload = read_json(payload_path)
    storyboard = payload.get("storyboard") if isinstance(payload.get("storyboard"), dict) else {}
    style = storyboard.get("style") if isinstance(storyboard.get("style"), dict) else {}
    if route in {"storyboard", "caption", "cover"}:
        style.update({"density": "minimal", "motion": "calm", "chrome": {"topbar": False, "progress": True, "beam": False}})
        storyboard["style"] = style
        scenes = storyboard.get("scenes") if isinstance(storyboard.get("scenes"), list) else []
        for scene in scenes:
            if isinstance(scene, dict) and isinstance(scene.get("props"), dict):
                scene["props"] = shorten_nested_text(scene["props"], 72)
        payload["storyboard"] = storyboard
    if route == "cover":
        short_title = bounded_text(payload.get("displayTitle") or payload.get("title"), 42)
        payload["displayTitle"] = short_title
        payload["title"] = short_title
    write_json(payload_path, payload)
    caption_rebuild = None
    if route == "caption":
        try:
            caption_rebuild = run_command([sys.executable, "scripts/build_captions.py", str(run_dir)], timeout=120)
        except RuntimeError as exc:
            caption_rebuild = {"error": str(exc)[:1000]}
    patch_report = {
        "schema_version": 1,
        "created_at": utc_now(),
        "attempt": attempt,
        "route": route,
        "status": "applied",
        "decision": decision,
        "render_payload": str(payload_path),
        "caption_rebuild": caption_rebuild,
    }
    patch_path = run_dir / "optimization" / "video" / f"repair-after-attempt-{attempt:02d}.json"
    write_json(patch_path, patch_report)
    return patch_report


def deterministic_decision(report: dict[str, Any]) -> dict[str, Any]:
    errors = [str(item) for item in report.get("errors") or []]
    if report.get("status") == "pass":
        return {"status": "pass", "repair_route": "none", "failed_checks": [], "repair_hint": ""}
    joined = " ".join(errors).lower()
    if "ffmpeg" in joined or "tesseract" in joined or "black frame" in joined or "silence" in joined or "video missing" in joined:
        route = "hard_fail"
    elif "caption" in joined:
        route = "caption"
    elif "ocr" in joined or "text" in joined:
        route = "storyboard"
    else:
        route = "hard_fail"
    return {"status": "fail", "repair_route": route, "failed_checks": errors, "repair_hint": "; ".join(errors)}


def semantic_feedback_from_audit(run_dir: Path, audit_path: Path, attempt: int) -> Path:
    audit = read_json(audit_path)
    issues = (audit.get("audit") or {}).get("issues") or []
    failed_checks = audit.get("failed_checks") or []
    feedback = {
        "schema_version": 1,
        "created_at": utc_now(),
        "provider": "gemini",
        "verdict": "improve",
        "overall": 0,
        "scores": {},
        "failed_dimensions": {str(check): 0 for check in failed_checks},
        "suggestions": [str(item) for item in issues if str(item).strip()] or [str(audit.get("repair_hint") or "Improve semantic fit.")],
        "revision_brief": {
            "source": "gemini_visual_audit",
            "video_attempt": attempt,
            "failed_checks": failed_checks,
            "repair_hint": audit.get("repair_hint"),
            "instruction": "Revise content so the rendered video has source-grounded constructive insight and matches run artifacts.",
        },
    }
    pending = run_dir / "optimization" / "video" / "pending_content_feedback.json"
    write_json(pending, feedback)
    return pending


def run_content_backtrack(run_dir: Path, audit_path: Path, attempt: int) -> dict[str, Any]:
    feedback_path = semantic_feedback_from_audit(run_dir, audit_path, attempt)
    return run_command(
        [sys.executable, "agent_harness/run_agent_loop.py", str(run_dir), "--mode", "provider", "--resume-from", "4"],
        env={"SEARCHPO_VIDEO_FEEDBACK": str(feedback_path)},
        timeout=900,
    )


def render_attempt(run_dir: Path, attempt_dir: Path, attempt: int, render_mode: str) -> dict[str, Any]:
    run_id = run_dir.name
    prepare = run_command([sys.executable, "render/prepare_remotion_input.py", str(run_dir)], timeout=120)
    props = run_dir / "remotion_input_props.json"
    manifest = run_dir / "render_input_manifest.json"
    copy_artifact(props, attempt_dir / "remotion_input_props.json")
    if manifest.exists():
        copy_artifact(manifest, attempt_dir / "render_input_manifest.json")
    record_stage(
        run_dir,
        name=f"remotion_input_attempt_{attempt:02d}",
        title=f"Prepare Remotion props attempt {attempt}",
        artifacts={"render_input_manifest": manifest},
        gates=[("remotion_input_prepared", "pass", f"attempt {attempt} props ready")],
    )

    if render_mode == "lambda":
        video_out = ROOT / "out" / f"{run_id}-searchpo-radar-lambda-attempt-{attempt:02d}.mp4"
        cover_out = ROOT / "out" / f"{run_id}-searchpo-cover-lambda-attempt-{attempt:02d}.jpg"
        video = run_command(
            ["bash", "scripts/lambda_render.sh", "render"],
            env={
                "SEARCHPO_RUN_DIR": str(run_dir),
                "SEARCHPO_LAMBDA_RENDER_OUTPUT": str(video_out.relative_to(ROOT)),
                "SEARCHPO_LAMBDA_RENDER_OUT_NAME": f"{run_id}/attempt-{attempt:02d}/searchpo-radar.mp4",
            },
            timeout=1800,
        )
        cover = run_command(
            ["bash", "scripts/lambda_render.sh", "still"],
            env={
                "SEARCHPO_RUN_DIR": str(run_dir),
                "SEARCHPO_LAMBDA_COVER_OUTPUT": str(cover_out.relative_to(ROOT)),
                "SEARCHPO_LAMBDA_COVER_OUT_NAME": f"{run_id}/attempt-{attempt:02d}/searchpo-cover.jpg",
            },
            timeout=900,
        )
    else:
        video_out = ROOT / "out" / f"{run_id}-searchpo-radar-attempt-{attempt:02d}.mp4"
        cover_out = ROOT / "out" / f"{run_id}-searchpo-cover-attempt-{attempt:02d}.jpg"
        video = run_command(
            ["bash", "scripts/remotion_render.sh", "local"],
            env={"SEARCHPO_RUN_DIR": str(run_dir), "SEARCHPO_RENDER_OUTPUT": str(video_out.relative_to(ROOT))},
            timeout=1200,
        )
        cover = run_command(
            ["bash", "scripts/remotion_render.sh", "cover"],
            env={"SEARCHPO_RUN_DIR": str(run_dir), "SEARCHPO_COVER_OUTPUT": str(cover_out.relative_to(ROOT))},
            timeout=600,
        )
    attempt_video = attempt_dir / "rendered_video.mp4"
    attempt_cover = attempt_dir / "rendered_cover.jpg"
    copy_artifact(video_out, attempt_video)
    copy_artifact(cover_out, attempt_cover)
    record_stage(
        run_dir,
        name=f"remotion_render_attempt_{attempt:02d}",
        title=f"Render MP4 attempt {attempt}",
        artifacts={"rendered_video_preview": attempt_video, "rendered_cover": attempt_cover},
        gates=[("remotion_rendered", "pass", f"attempt {attempt} video and cover rendered")],
    )
    return {
        "prepare": prepare,
        "video": video,
        "cover": cover,
        "video_path": str(attempt_video),
        "cover_path": str(attempt_cover),
        "props_sha256": sha256_file(props),
        "video_sha256": sha256_file(attempt_video),
        "cover_sha256": sha256_file(attempt_cover),
    }


def audit_attempt(run_dir: Path, attempt_dir: Path, attempt: int, video_path: Path) -> dict[str, Any]:
    metadata_path = attempt_dir / "render_metadata_check.json"
    deterministic_path = attempt_dir / "visual_audit_deterministic.json"
    gemini_path = attempt_dir / "gemini_visual_audit.json"
    gemini_prompt_path = attempt_dir / "gemini_visual_audit_prompt.json"
    try:
        metadata_meta = run_command(
            [sys.executable, "scripts/check_render_metadata.py", str(run_dir), "--video", str(video_path), "--output", str(metadata_path)],
            timeout=90,
        )
    except RuntimeError as exc:
        return {"status": "fail", "repair_route": "hard_fail", "repair_hint": str(exc)[:1000], "failed_checks": ["render_metadata"], "metadata_error": str(exc)[:1000]}
    metadata = read_json(metadata_path)
    if metadata.get("status") != "pass":
        return {"status": "fail", "repair_route": "hard_fail", "repair_hint": "; ".join(metadata.get("errors") or []), "failed_checks": ["render_metadata"], "metadata": metadata, "metadata_command": metadata_meta}

    try:
        deterministic_meta = run_command(
            [
                sys.executable,
                "scripts/deterministic_visual_audit.py",
                str(run_dir),
                "--video",
                str(video_path),
                "--output",
                str(deterministic_path),
            ],
            timeout=180,
        )
    except RuntimeError:
        deterministic = read_json(deterministic_path) if deterministic_path.exists() else {"status": "fail", "errors": ["deterministic audit crashed"]}
        decision = deterministic_decision(deterministic)
        decision.update({"deterministic": deterministic, "metadata": metadata, "metadata_command": metadata_meta})
        return decision
    deterministic = read_json(deterministic_path)
    if deterministic.get("status") != "pass":
        decision = deterministic_decision(deterministic)
        decision.update({"deterministic": deterministic, "deterministic_command": deterministic_meta, "metadata": metadata, "metadata_command": metadata_meta})
        return decision

    try:
        gemini_meta = run_command(
            [
                sys.executable,
                "scripts/gemini_visual_audit.py",
                str(run_dir),
                "--video",
                str(video_path),
                "--output",
                str(gemini_path),
                "--prompt-output",
                str(gemini_prompt_path),
            ],
            timeout=300,
        )
    except RuntimeError:
        gemini = read_json(gemini_path) if gemini_path.exists() else {"status": "fail", "repair_route": "hard_fail", "failed_checks": ["gemini_visual_audit"], "repair_hint": "Gemini visual audit crashed"}
    else:
        gemini = read_json(gemini_path)
    decision = {
        "status": gemini.get("status") or "fail",
        "repair_route": gemini.get("repair_route") or "hard_fail",
        "repair_hint": gemini.get("repair_hint") or "",
        "failed_checks": gemini.get("failed_checks") or [],
        "metadata": metadata,
        "metadata_command": metadata_meta,
        "deterministic": deterministic,
        "deterministic_command": deterministic_meta,
        "gemini": gemini,
        "gemini_command": locals().get("gemini_meta"),
    }
    return decision


def promote_attempt(run_dir: Path, attempt_dir: Path, render_info: dict[str, Any], args: argparse.Namespace) -> None:
    copy_artifact(attempt_dir / "render_metadata_check.json", run_dir / "render_metadata_check.json")
    copy_artifact(attempt_dir / "visual_audit_deterministic.json", run_dir / "visual_audit_deterministic.json")
    copy_artifact(attempt_dir / "gemini_visual_audit.json", run_dir / "gemini_visual_audit.json")
    if (attempt_dir / "gemini_visual_audit_prompt.json").exists():
        copy_artifact(attempt_dir / "gemini_visual_audit_prompt.json", run_dir / "gemini_visual_audit_prompt.json")
    run_command(
        [
            sys.executable,
            "scripts/finalize_artifacts.py",
            str(run_dir),
            "--video",
            str(render_info["video_path"]),
            "--cover",
            str(render_info["cover_path"]),
            "--execution-profile",
            args.execution_profile,
            "--render-mode",
            args.render_mode,
            "--publish-mode",
            args.publish_mode,
        ],
        timeout=120,
    )
    record_stage(
        run_dir,
        name="artifact_identity",
        title="Bind run-scoped media artifacts",
        artifacts={
            "artifact_manifest": run_dir / "artifact_manifest.json",
            "final_video": run_dir / "video" / "final.mp4",
            "final_cover": run_dir / "cover" / "final.jpg",
        },
        gates=[("artifact_identity_bound", "pass", "Final media is run scoped and content hash bound")],
    )
    record_stage(
        run_dir,
        name="render_metadata_check",
        title="Verify rendered MP4 metadata",
        artifacts={"render_metadata_check": run_dir / "render_metadata_check.json"},
        gates=[("render_metadata_verified", "pass", "Rendered MP4 matches Douyin codec requirements")],
    )
    record_stage(
        run_dir,
        name="deterministic_visual_audit",
        title="Deterministic video quality audit",
        artifacts={"visual_audit_deterministic": run_dir / "visual_audit_deterministic.json"},
        gates=[("deterministic_visual_audit_passed", "pass", "Frame caption black-frame and audio checks passed")],
    )
    record_stage(
        run_dir,
        name="gemini_visual_audit",
        title="Gemini video visual audit",
        artifacts={"gemini_visual_audit": run_dir / "gemini_visual_audit.json"},
        gates=[("visual_audit_passed", "pass", "Gemini visual audit passed before publish")],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--execution-profile", required=True, choices=["provider", "lambda", "live"])
    parser.add_argument("--render-mode", required=True, choices=["local", "lambda"])
    parser.add_argument("--publish-mode", required=True, choices=["contract-check", "live"])
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    max_attempts = max(1, int(policy_get("video_optimization.max_video_attempts", 3)))
    max_semantic_backtracks = max(0, int(policy_get("video_optimization.max_semantic_backtracks", 1)))
    semantic_backtracks = 0
    attempts: list[dict[str, Any]] = []
    optimization_root = run_dir / "optimization" / "video"
    optimization_root.mkdir(parents=True, exist_ok=True)

    if args.render_mode == "lambda":
        run_command(["bash", "scripts/lambda_render.sh", "site"], env={"SEARCHPO_RUN_DIR": str(run_dir)}, timeout=900)

    status = "fail"
    failure_reason = ""
    for attempt in range(1, max_attempts + 1):
        attempt_dir = optimization_root / f"attempt-{attempt:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        try:
            render_info = render_attempt(run_dir, attempt_dir, attempt, args.render_mode)
            decision = audit_attempt(run_dir, attempt_dir, attempt, Path(render_info["video_path"]))
        except Exception as exc:
            render_info = {}
            decision = {"status": "fail", "repair_route": "hard_fail", "repair_hint": str(exc)[:1000], "failed_checks": ["video_attempt_exception"]}

        decision_path = attempt_dir / "video_revision_decision.json"
        write_json(
            decision_path,
            {
                "schema_version": 1,
                "created_at": utc_now(),
                "attempt": attempt,
                "status": decision.get("status"),
                "repair_route": decision.get("repair_route"),
                "repair_hint": decision.get("repair_hint"),
                "failed_checks": decision.get("failed_checks") or [],
                "semantic_backtracks_used": semantic_backtracks,
                "render": render_info,
                "decision": decision,
            },
        )
        attempts.append(read_json(decision_path))

        if decision.get("status") == "pass":
            promote_attempt(run_dir, attempt_dir, render_info, args)
            status = "pass"
            break

        route = str(decision.get("repair_route") or "hard_fail")
        if route == "content" and semantic_backtracks < max_semantic_backtracks and attempt < max_attempts:
            semantic_backtracks += 1
            backtrack_meta = run_content_backtrack(run_dir, attempt_dir / "gemini_visual_audit.json", attempt)
            attempts[-1]["content_backtrack"] = backtrack_meta
            write_json(decision_path, attempts[-1])
            continue
        if route in {"storyboard", "caption", "cover"} and attempt < max_attempts:
            repair_report = apply_video_repair(run_dir, route, attempt, decision)
            attempts[-1]["repair"] = repair_report
            write_json(decision_path, attempts[-1])
            continue
        failure_reason = decision.get("repair_hint") or f"video attempt {attempt} failed with route={route}"
        break

    summary = {
        "schema_version": 1,
        "created_at": utc_now(),
        "status": status,
        "max_attempts": max_attempts,
        "attempt_count": len(attempts),
        "semantic_backtracks": semantic_backtracks,
        "attempts": attempts,
        "failure_reason": failure_reason,
    }
    summary_path = run_dir / "video_optimization_loop.json"
    write_json(summary_path, summary)
    record_stage(
        run_dir,
        name="video_quality_loop",
        title="Video eval improve loop",
        status="completed" if status == "pass" else "failed",
        artifacts={"video_optimization_loop": summary_path},
        gates=[("video_quality_loop", "pass" if status == "pass" else "fail", failure_reason or "video quality loop passed")],
    )
    print(json.dumps({"video_optimization_loop": str(summary_path), "status": status}, ensure_ascii=False, indent=2))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
