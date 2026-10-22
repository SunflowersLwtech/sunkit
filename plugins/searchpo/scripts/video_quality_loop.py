#!/usr/bin/env python3
"""Run render/audit/improve attempts before Searchpo publish checks."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
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

from agent_harness.artifact_paths import preview_output_paths
from agent_harness.policy import policy_get
from agent_harness.runtime_contracts import IMPL_AGENT, write_implementation_loop
from scripts.provider_modes import AUDIT_NOT_USED, visual_audit_mode


GENERATED_SOURCE_LOCK = ROOT / "runtime" / "locks" / "remotion-generated-source.lock"
REQUIRED_PREMIUM_SHOWCASE_CHECKS = {
    "premium_visual_language",
    "topic_specific_scene_design",
    "not_generic_radar_or_cards",
    "not_ppt_or_slide_deck",
    "cinematic_motion_depth",
    "information_motion_primitives",
    "knowledge_sharing_content",
    "motion_comfort",
    "readability_and_safe_area",
    "reference_level_depth_or_clear_gap",
}
PREMIUM_VISUAL_CHECKS = REQUIRED_PREMIUM_SHOWCASE_CHECKS - {"knowledge_sharing_content"}
PREMIUM_VISUAL_SCORE_KEYS = {"visual_premium", "motion_polish", "topic_specificity", "overall"}
PREMIUM_KNOWLEDGE_SCORE_KEYS = {"knowledge_value"}
MIN_PREMIUM_SCORE = 8.0


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


@contextmanager
def generated_source_render_lock(run_dir: Path, attempt: int):
    GENERATED_SOURCE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with GENERATED_SOURCE_LOCK.open("a+", encoding="utf-8") as handle:
        handle.write(f"{utc_now()} waiting run={run_dir.name} attempt={attempt}\n")
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(f"{utc_now()} acquired run={run_dir.name} attempt={attempt}\n")
        handle.flush()
        try:
            yield
        finally:
            handle.write(f"{utc_now()} released run={run_dir.name} attempt={attempt}\n")
            handle.flush()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def record_stage(
    run_dir: Path,
    *,
    name: str,
    title: str,
    owner: str = IMPL_AGENT,
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
            caption_rebuild = run_command([sys.executable, "scripts/build_captions.py", str(run_dir)], timeout=240)
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
    elif (
        "central content motion" in joined
        or "central content remains static" in joined
        or "central visual movement" in joined
        or "active_ratio" in joined
    ):
        route = "content"
    elif "agent_visual" in joined or "cards-only" in joined or "topic-specific" in joined or "compatibility cards" in joined:
        route = "content"
    elif "caption" in joined:
        route = "caption"
    elif "ocr" in joined or "text" in joined:
        route = "storyboard"
    else:
        route = "hard_fail"
    return {"status": "fail", "repair_route": route, "failed_checks": errors, "repair_hint": "; ".join(errors)}


def agent_visual_enabled(run_dir: Path) -> bool:
    payload_path = run_dir / "render_payload.json"
    if not payload_path.exists():
        return False
    try:
        payload = read_json(payload_path)
    except Exception:
        return False
    visual = payload.get("agentVisual") or payload.get("agent_visual") or {}
    return bool(payload.get("agentVisualRequired") and isinstance(visual, dict) and visual.get("enabled"))


def reroute_agent_visual_failures(run_dir: Path, decision: dict[str, Any]) -> dict[str, Any]:
    if not agent_visual_enabled(run_dir) or decision.get("status") == "pass":
        return decision
    route = str(decision.get("repair_route") or "hard_fail")
    hint = str(decision.get("repair_hint") or "").lower()
    failed = " ".join(str(item) for item in decision.get("failed_checks") or []).lower()
    agent_visual_compile_failure = any(
        token in hint or token in failed
        for token in [
            "agent_visual",
            "agentvisual",
            "agentvisualgenerated",
            "component_code",
            "prepare_remotion_input.py",
            "tsx",
            "esbuild",
            "transform failed",
            "symbol",
            "has already been declared",
        ]
    )
    infra_dependency_failure = any(
        token in hint or token in failed
        for token in [
            "ffmpeg",
            "tesseract",
            "silence",
            "codec broken",
            "render_metadata",
        ]
    )
    lambda_dependency_failure = any(
        token in hint or token in failed
        for token in [
            "lambda",
            "timeout",
            "timed out",
        ]
    )
    dependency_failure = (infra_dependency_failure or lambda_dependency_failure) and not agent_visual_compile_failure
    visual_content_failure = any(
        token in hint or token in failed
        for token in [
            "central visual motion",
            "central content motion",
            "central content remains static",
            "central visual movement",
            "active_ratio",
            "caption/progress/fade-only",
            "central_motion_not_caption_or_progress_only",
            "topic_specific_visual",
            "not_cards_only_template",
            "cards-only",
            "topic-specific",
        ]
    )
    agent_visual_failure = (
        agent_visual_compile_failure
        or (route in {"storyboard", "caption"} and visual_content_failure)
        or route == "storyboard"
        or "video_attempt_exception" in failed
        or "blank" in hint
        or "black frame" in hint
        or "overlap" in hint
    )
    if agent_visual_failure and not dependency_failure:
        updated = dict(decision)
        updated["repair_route"] = "hard_fail"
        updated["repair_domain"] = "agent_visual_compiler"
        updated["repair_hint"] = (
            f"{decision.get('repair_hint') or 'agent_visual render failed'} "
            "Repair premium_director_spec/compiler layout and rerun the render loop; do not switch to storyboard or content-only backtrack."
        )
        return updated
    return decision


def semantic_feedback_from_audit(run_dir: Path, audit_path: Path, attempt: int, decision: dict[str, Any] | None = None) -> Path:
    audit = read_json(audit_path) if audit_path.exists() else {"audit": {}, "failed_checks": (decision or {}).get("failed_checks") or []}
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
        "suggestions": [str(item) for item in issues if str(item).strip()] or [str((decision or audit).get("repair_hint") or "Improve semantic fit.")],
        "revision_brief": {
            "source": "gemini_visual_audit",
            "video_attempt": attempt,
            "failed_checks": failed_checks,
            "repair_hint": (decision or audit).get("repair_hint"),
            "instruction": (
                "Revise content and regenerate premium_director_spec so the compiled Remotion video has source-grounded constructive insight, "
                "matches run artifacts, and shows central visual motion in every major segment. Progress bars, caption highlights, "
                "and fades alone do not satisfy the motion requirement. If the failure mentions central_animation_richness, add "
                "multiple visible central motion layers through director scenes such as spring entrance, staggered reveals, moving packets, "
                "camera pans, path draws, metric counts, audio-reactive emphasis, scanner sweeps, and animated state transitions."
            ),
        },
    }
    pending = run_dir / "optimization" / "video" / "pending_content_feedback.json"
    write_json(pending, feedback)
    return pending


def numeric_score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def premium_showcase_evidence_fields(premium: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str] | None, str]:
    audit = premium.get("audit") if isinstance(premium.get("audit"), dict) else {}
    checks = premium.get("checks")
    if not isinstance(checks, dict):
        checks = audit.get("checks")
    scores = premium.get("scores")
    if not isinstance(scores, dict):
        scores = audit.get("scores")
    issues = premium.get("issues")
    if not isinstance(issues, list):
        issues = audit.get("issues")
    clean_issues = [str(item).strip() for item in issues if str(item).strip()] if isinstance(issues, list) else None
    repair_hint = str(
        premium.get("repair_hint")
        or premium.get("repair_brief")
        or audit.get("repair_hint")
        or audit.get("repair_brief")
        or ""
    ).strip()
    return (
        checks if isinstance(checks, dict) else None,
        scores if isinstance(scores, dict) else None,
        clean_issues,
        repair_hint,
    )


def enrich_premium_showcase_audit(premium: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(premium)
    checks, scores, issues, repair_hint = premium_showcase_evidence_fields(enriched)
    if checks is not None:
        enriched["checks"] = checks
    if scores is not None:
        enriched["scores"] = scores
    if issues is not None:
        enriched["issues"] = issues
    if repair_hint:
        enriched["repair_hint"] = repair_hint
    return enriched


def preserve_premium_showcase_failure_evidence(
    run_dir: Path,
    premium_path: Path,
    premium_prompt_path: Path,
    premium: dict[str, Any],
    *,
    repair_route: str,
    repair_domain: str,
    repair_hint: str,
) -> dict[str, Any]:
    enriched = enrich_premium_showcase_audit(premium)
    enriched.setdefault("status", "fail")
    enriched["repair_route"] = repair_route
    enriched["repair_domain"] = repair_domain
    if not enriched.get("repair_hint"):
        enriched["repair_hint"] = repair_hint
    write_json(premium_path, enriched)
    root_path = run_dir / "premium_showcase_audit.json"
    if premium_path.resolve() != root_path.resolve():
        copy_artifact(premium_path, root_path)
    if premium_prompt_path.exists():
        root_prompt_path = run_dir / "premium_showcase_audit_prompt.json"
        if premium_prompt_path.resolve() != root_prompt_path.resolve():
            copy_artifact(premium_prompt_path, root_prompt_path)
    return enriched


def premium_showcase_repair_route(premium: dict[str, Any]) -> tuple[str, str, str]:
    status_reason = premium.get("status_reason") if isinstance(premium.get("status_reason"), dict) else {}
    checks, scores, _issues, _repair_hint = premium_showcase_evidence_fields(premium)
    failed = set(str(item) for item in (premium.get("failed_checks") or status_reason.get("failed_checks") or []))
    if checks:
        failed.update(str(key) for key, value in checks.items() if not bool(value))
    missing_required = set(str(item) for item in (status_reason.get("missing_required_checks") or []))
    if checks:
        missing_required.update(REQUIRED_PREMIUM_SHOWCASE_CHECKS - set(str(key) for key in checks.keys()))
    low_scores = set(str(item) for item in (status_reason.get("low_scores") or []))
    if scores:
        low_scores.update(str(key) for key, value in scores.items() if key in PREMIUM_VISUAL_SCORE_KEYS | PREMIUM_KNOWLEDGE_SCORE_KEYS and numeric_score(value) < MIN_PREMIUM_SCORE)
    reference_gap = isinstance(premium.get("reference_gap_report"), dict) and str((premium.get("reference_gap_report") or {}).get("status") or "") == "gap"
    visual_or_motion_gap = bool(
        failed
        & (PREMIUM_VISUAL_CHECKS | {"premium_showcase_audit"})
    ) or bool(low_scores & PREMIUM_VISUAL_SCORE_KEYS) or bool(missing_required) or reference_gap
    if visual_or_motion_gap:
        details: list[str] = []
        if low_scores:
            details.append(f"low premium scores: {sorted(low_scores)}")
        if missing_required:
            details.append(f"missing showcase checks: {sorted(missing_required)}")
        if reference_gap:
            details.append("reference showcase videos unavailable")
        if failed:
            details.append(f"failed showcase checks: {sorted(failed)}")
        return (
            "hard_fail",
            "premium_visual_compiler",
            "Premium showcase audit failed at the visual/compiler bar; " + "; ".join(details),
        )
    if failed == {"knowledge_sharing_content"} or low_scores == {"knowledge_value"}:
        return (
            "content",
            "knowledge_sharing_content",
            "Premium showcase audit failed only on knowledge-sharing content.",
        )
    return (
        "hard_fail",
        "premium_showcase_audit",
        "Premium showcase audit failed; inspect premium_showcase_audit.json for the gap.",
    )


def delegation_args_from_env() -> list[str]:
    mode = str(os.environ.get("SEARCHPO_DELEGATION_MODE") or "").strip()
    agent = str(os.environ.get("SEARCHPO_DELEGATION_AGENT") or "").strip()
    proof = str(os.environ.get("SEARCHPO_DELEGATION_PROOF") or "").strip()
    args: list[str] = []
    if mode:
        args.extend(["--delegation-mode", mode])
    if agent:
        args.extend(["--delegation-agent", agent])
    if proof:
        args.extend(["--delegation-proof", proof])
    return args


def run_content_backtrack(run_dir: Path, audit_path: Path, attempt: int, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    feedback_path = semantic_feedback_from_audit(run_dir, audit_path, attempt, decision)
    return run_command(
        [
            sys.executable,
            "agent_harness/run_agent_loop.py",
            str(run_dir),
            "--mode",
            "provider",
            "--resume-from",
            "4",
            *delegation_args_from_env(),
        ],
        env={"SEARCHPO_VIDEO_FEEDBACK": str(feedback_path)},
        timeout=1800,
    )


def render_attempt(run_dir: Path, attempt_dir: Path, attempt: int, render_mode: str, publish_mode: str = "contract-check") -> dict[str, Any]:
    with generated_source_render_lock(run_dir, attempt):
        result = _render_attempt_unlocked(run_dir, attempt_dir, attempt, render_mode, publish_mode)
    result["generated_source_lock"] = str(GENERATED_SOURCE_LOCK)
    return result


def _render_attempt_unlocked(
    run_dir: Path,
    attempt_dir: Path,
    attempt: int,
    render_mode: str,
    publish_mode: str = "contract-check",
) -> dict[str, Any]:
    run_id = run_dir.name
    prepare = run_command([sys.executable, "render/prepare_remotion_input.py", str(run_dir)], timeout=240)
    props = run_dir / "remotion_input_props.json"
    manifest = run_dir / "render_input_manifest.json"
    copy_artifact(props, attempt_dir / "remotion_input_props.json")
    if manifest.exists():
        copy_artifact(manifest, attempt_dir / "render_input_manifest.json")
    generated_visual = ROOT / "src" / "generated" / "AgentVisual.generated.tsx"
    generated_visual_css = ROOT / "src" / "generated" / "agent-visual.generated.css"
    if generated_visual.exists():
        copy_artifact(generated_visual, attempt_dir / "AgentVisual.generated.tsx")
    if generated_visual_css.exists():
        copy_artifact(generated_visual_css, attempt_dir / "agent-visual.generated.css")
    record_stage(
        run_dir,
        name=f"remotion_input_attempt_{attempt:02d}",
        title=f"Prepare Remotion props attempt {attempt}",
        artifacts={"render_input_manifest": manifest},
        gates=[("remotion_input_prepared", "pass", f"attempt {attempt} props ready")],
    )

    site = None
    render_backend = render_mode
    lambda_fallback = None

    def _write_preview_manifest(
        *,
        backend: str,
        video_out: Path,
        cover_out: Path,
        attempt_video: Path,
        attempt_cover: Path,
    ) -> Path:
        manifest_path = video_out.parent / "preview_manifest.json"
        write_json(
            manifest_path,
            {
                "schema_version": 1,
                "created_at": utc_now(),
                "run_id": run_id,
                "run_dir": str(run_dir),
                "attempt": attempt,
                "backend": backend,
                "preview_dir": str(video_out.parent),
                "preview_video": str(video_out),
                "preview_cover": str(cover_out),
                "attempt_video": str(attempt_video),
                "attempt_cover": str(attempt_cover),
                "publishable_video_after_pass": str(run_dir / "video" / "final.mp4"),
                "publishable_cover_after_pass": str(run_dir / "cover" / "final.jpg"),
            },
        )
        return manifest_path

    def _render_local():
        local_video, local_cover = preview_output_paths(ROOT, run_dir, backend="local", attempt=attempt)
        local_video_result = run_command(
            ["bash", "scripts/remotion_render.sh", "local"],
            env={"SEARCHPO_RUN_DIR": str(run_dir), "SEARCHPO_RENDER_OUTPUT": str(local_video.relative_to(ROOT))},
            timeout=2400,
        )
        local_cover_result = run_command(
            ["bash", "scripts/remotion_render.sh", "cover"],
            env={"SEARCHPO_RUN_DIR": str(run_dir), "SEARCHPO_COVER_OUTPUT": str(local_cover.relative_to(ROOT))},
            timeout=900,
        )
        return local_video, local_cover, local_video_result, local_cover_result

    if render_mode == "lambda":
        site = run_command(["bash", "scripts/lambda_render.sh", "site"], env={"SEARCHPO_RUN_DIR": str(run_dir)}, timeout=900)
        video_out, cover_out = preview_output_paths(ROOT, run_dir, backend="lambda", attempt=attempt)
        remote_prefix = f"{run_dir.parent.name}/{run_id}/attempt-{attempt:02d}"
        try:
            video = run_command(
                ["bash", "scripts/lambda_render.sh", "render"],
                env={
                    "SEARCHPO_RUN_DIR": str(run_dir),
                    "SEARCHPO_LAMBDA_RENDER_OUTPUT": str(video_out.relative_to(ROOT)),
                    "SEARCHPO_LAMBDA_RENDER_OUT_NAME": f"{remote_prefix}/searchpo-radar.mp4",
                },
                timeout=3600,
            )
            cover = run_command(
                ["bash", "scripts/lambda_render.sh", "still"],
                env={
                    "SEARCHPO_RUN_DIR": str(run_dir),
                    "SEARCHPO_LAMBDA_COVER_OUTPUT": str(cover_out.relative_to(ROOT)),
                    "SEARCHPO_LAMBDA_COVER_OUT_NAME": f"{remote_prefix}/searchpo-cover.jpg",
                },
                timeout=1200,
            )
            if int(video.get("returncode", 1)) != 0 or not video_out.exists() or not cover_out.exists():
                raise RuntimeError("lambda render did not produce expected video/cover artifacts")
        except RuntimeError as exc:
            if publish_mode == "live" or os.environ.get("SEARCHPO_ALLOW_LAMBDA_LOCAL_FALLBACK") != "1":
                record_stage(
                    run_dir,
                    name=f"lambda_render_attempt_{attempt:02d}",
                    title=f"Lambda render attempt {attempt}",
                    artifacts={},
                    gates=[("lambda_rendered", "fail", f"lambda render failed: {str(exc)[:400]}")],
                )
                raise
            lambda_fallback = {"reason": "lambda_render_failed", "error": str(exc)[:2000], "site": site}
            render_backend = "local"
            video_out, cover_out, video, cover = _render_local()
    else:
        render_backend = "local"
        video_out, cover_out, video, cover = _render_local()
    attempt_video = attempt_dir / "rendered_video.mp4"
    attempt_cover = attempt_dir / "rendered_cover.jpg"
    copy_artifact(video_out, attempt_video)
    copy_artifact(cover_out, attempt_cover)
    preview_manifest = _write_preview_manifest(
        backend=render_backend,
        video_out=video_out,
        cover_out=cover_out,
        attempt_video=attempt_video,
        attempt_cover=attempt_cover,
    )
    copy_artifact(preview_manifest, attempt_dir / "preview_manifest.json")
    record_stage(
        run_dir,
        name=f"remotion_render_attempt_{attempt:02d}",
        title=f"Render MP4 attempt {attempt}",
        artifacts={
            "rendered_video_preview": attempt_video,
            "rendered_cover": attempt_cover,
            "preview_manifest": attempt_dir / "preview_manifest.json",
        },
        gates=[("remotion_rendered", "pass", f"attempt {attempt} video and cover rendered")],
    )
    return {
        "prepare": prepare,
        "site": site,
        "render_backend": render_backend,
        "lambda_fallback": lambda_fallback,
        "video": video,
        "cover": cover,
        "video_path": str(attempt_video),
        "cover_path": str(attempt_cover),
        "raw_preview_video_path": str(video_out),
        "raw_preview_cover_path": str(cover_out),
        "preview_manifest": str(preview_manifest),
        "props_sha256": sha256_file(props),
        "video_sha256": sha256_file(attempt_video),
        "cover_sha256": sha256_file(attempt_cover),
    }


def not_used_model_audit(audit_name: str, video_path: Path, deterministic_path: Path) -> dict[str, Any]:
    """Record that a model audit did not run; release gates accept this only in deterministic mode."""
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "audit_name": audit_name,
        "provider": "gemini",
        "status": AUDIT_NOT_USED,
        "visual_audit_mode": "deterministic",
        "reason": "SEARCHPO_VISUAL_AUDIT=deterministic: the visual gate is decided by the deterministic audit alone; no model audit ran.",
        "video_path": str(video_path),
        "video_sha256": sha256_file(video_path),
        "deterministic_audit_path": str(deterministic_path),
        "deterministic_audit_status": "pass",
    }


def audit_attempt(run_dir: Path, attempt_dir: Path, attempt: int, video_path: Path) -> dict[str, Any]:
    metadata_path = attempt_dir / "render_metadata_check.json"
    deterministic_path = attempt_dir / "visual_audit_deterministic.json"
    gemini_path = attempt_dir / "gemini_visual_audit.json"
    gemini_prompt_path = attempt_dir / "gemini_visual_audit_prompt.json"
    premium_path = attempt_dir / "premium_showcase_audit.json"
    premium_prompt_path = attempt_dir / "premium_showcase_audit_prompt.json"
    for stale_path in [
        metadata_path,
        deterministic_path,
        gemini_path,
        gemini_prompt_path,
        premium_path,
        premium_prompt_path,
    ]:
        if stale_path.exists():
            stale_path.unlink()
    try:
        metadata_meta = run_command(
            [sys.executable, "scripts/check_render_metadata.py", str(run_dir), "--video", str(video_path), "--output", str(metadata_path)],
            timeout=180,
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
            timeout=900,
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

    if visual_audit_mode() == "deterministic":
        gemini = not_used_model_audit("gemini_visual_audit", video_path, deterministic_path)
        premium = not_used_model_audit("premium_showcase_audit", video_path, deterministic_path)
        write_json(gemini_path, gemini)
        write_json(premium_path, premium)
        return {
            "status": "pass",
            "repair_route": "none",
            "repair_hint": "",
            "failed_checks": [],
            "visual_audit_mode": "deterministic",
            "metadata": metadata,
            "metadata_command": metadata_meta,
            "deterministic": deterministic,
            "deterministic_command": deterministic_meta,
            "gemini": gemini,
            "premium_showcase_not_used": premium,
        }

    try:
        gemini_timeout = int(os.environ.get("SEARCHPO_GEMINI_VISUAL_AUDIT_TIMEOUT", "600"))
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
                "--timeout",
                str(gemini_timeout),
            ],
            timeout=gemini_timeout + 120,
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
    if decision["status"] != "pass":
        return decision

    try:
        premium_meta = run_command(
            [
                sys.executable,
                "scripts/premium_showcase_audit.py",
                str(run_dir),
                "--video",
                str(video_path),
                "--output",
                str(premium_path),
                "--prompt-output",
                str(premium_prompt_path),
            ],
            timeout=360,
        )
    except RuntimeError:
        premium = read_json(premium_path) if premium_path.exists() else {"status": "fail", "failed_checks": ["premium_showcase_audit"], "repair_hint": "Premium showcase audit crashed"}
        premium_route, premium_domain, premium_hint = premium_showcase_repair_route(premium)
        premium = preserve_premium_showcase_failure_evidence(
            run_dir,
            premium_path,
            premium_prompt_path,
            premium,
            repair_route=premium_route,
            repair_domain=premium_domain,
            repair_hint=premium_hint,
        )
        decision.update(
            {
                "status": "fail",
                "repair_route": premium_route,
                "repair_domain": premium_domain,
                "repair_hint": premium.get("repair_hint") or premium_hint,
                "failed_checks": premium.get("failed_checks") or ["premium_showcase_audit"],
                "premium_showcase": premium,
                "feedback_audit_path": str(premium_path),
            }
        )
        return decision
    premium = read_json(premium_path)
    decision.update({"premium_showcase": premium, "premium_showcase_command": premium_meta})
    if premium.get("status") != "pass":
        premium_route, premium_domain, premium_hint = premium_showcase_repair_route(premium)
        premium = preserve_premium_showcase_failure_evidence(
            run_dir,
            premium_path,
            premium_prompt_path,
            premium,
            repair_route=premium_route,
            repair_domain=premium_domain,
            repair_hint=premium_hint,
        )
        decision.update(
            {
                "status": "fail",
                "repair_route": premium_route,
                "repair_domain": premium_domain,
                "repair_hint": premium.get("repair_hint") or premium_hint,
                "failed_checks": premium.get("failed_checks") or ["premium_showcase_audit"],
                "premium_showcase": premium,
                "feedback_audit_path": str(premium_path),
            }
        )
    return decision


def promote_attempt(run_dir: Path, attempt_dir: Path, render_info: dict[str, Any], args: argparse.Namespace) -> None:
    copy_artifact(attempt_dir / "render_metadata_check.json", run_dir / "render_metadata_check.json")
    copy_artifact(attempt_dir / "visual_audit_deterministic.json", run_dir / "visual_audit_deterministic.json")
    copy_artifact(attempt_dir / "gemini_visual_audit.json", run_dir / "gemini_visual_audit.json")
    copy_artifact(attempt_dir / "premium_showcase_audit.json", run_dir / "premium_showcase_audit.json")
    if (attempt_dir / "gemini_visual_audit_prompt.json").exists():
        copy_artifact(attempt_dir / "gemini_visual_audit_prompt.json", run_dir / "gemini_visual_audit_prompt.json")
    if (attempt_dir / "premium_showcase_audit_prompt.json").exists():
        copy_artifact(attempt_dir / "premium_showcase_audit_prompt.json", run_dir / "premium_showcase_audit_prompt.json")
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
            str(render_info.get("render_backend") or args.render_mode),
            "--publish-mode",
            args.publish_mode,
        ],
        timeout=300,
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
    if visual_audit_mode() == "deterministic":
        record_stage(
            run_dir,
            name="gemini_visual_audit",
            title="Gemini video visual audit (not used)",
            status="skipped",
            artifacts={"gemini_visual_audit": run_dir / "gemini_visual_audit.json"},
            gates=[
                ("visual_audit_passed", "pass", "Deterministic visual audit decided the visual gate (SEARCHPO_VISUAL_AUDIT=deterministic)"),
                ("gemini_visual_audit", AUDIT_NOT_USED, "Gemini visual audit did not run in deterministic visual-audit mode"),
            ],
        )
        record_stage(
            run_dir,
            name="premium_showcase_audit",
            title="Premium Remotion showcase audit (not used)",
            status="skipped",
            artifacts={"premium_showcase_audit": run_dir / "premium_showcase_audit.json"},
            gates=[("premium_showcase_audit_passed", AUDIT_NOT_USED, "Model showcase audit did not run in deterministic visual-audit mode")],
        )
        return
    record_stage(
        run_dir,
        name="gemini_visual_audit",
        title="Gemini video visual audit",
        artifacts={"gemini_visual_audit": run_dir / "gemini_visual_audit.json"},
        gates=[("visual_audit_passed", "pass", "Gemini visual audit passed before publish")],
    )
    record_stage(
        run_dir,
        name="premium_showcase_audit",
        title="Premium Remotion showcase audit",
        artifacts={"premium_showcase_audit": run_dir / "premium_showcase_audit.json"},
        gates=[("premium_showcase_audit_passed", "pass", "Generated MP4 reached the premium director visual bar")],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir")
    parser.add_argument("--execution-profile", required=True, choices=["provider", "lambda", "live"])
    parser.add_argument("--render-mode", required=True, choices=["local", "lambda"])
    parser.add_argument("--publish-mode", required=True, choices=["contract-check", "live"])
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    visual_mode = visual_audit_mode()
    max_attempts = max(1, int(policy_get("video_optimization.max_video_attempts", 3)))
    max_semantic_backtracks = max(0, int(policy_get("video_optimization.max_semantic_backtracks", 1)))
    semantic_backtracks = 0
    attempts: list[dict[str, Any]] = []
    optimization_root = run_dir / "optimization" / "video"
    optimization_root.mkdir(parents=True, exist_ok=True)

    status = "fail"
    failure_reason = ""
    for attempt in range(1, max_attempts + 1):
        attempt_dir = optimization_root / f"attempt-{attempt:02d}"
        if attempt_dir.exists():
            shutil.rmtree(attempt_dir)
        attempt_dir.mkdir(parents=True, exist_ok=True)
        try:
            render_info = render_attempt(run_dir, attempt_dir, attempt, args.render_mode, args.publish_mode)
            decision = audit_attempt(run_dir, attempt_dir, attempt, Path(render_info["video_path"]))
        except Exception as exc:
            render_info = {}
            decision = {"status": "fail", "repair_route": "hard_fail", "repair_hint": str(exc)[:1000], "failed_checks": ["video_attempt_exception"]}
        decision = reroute_agent_visual_failures(run_dir, decision)
        if not decision.get("repair_domain") and isinstance(decision.get("premium_showcase"), dict):
            premium_route, premium_domain, premium_hint = premium_showcase_repair_route(decision["premium_showcase"])
            decision["repair_domain"] = premium_domain
            decision.setdefault("repair_hint", premium_hint)
            if not decision.get("repair_route"):
                decision["repair_route"] = premium_route
        route = str(decision.get("repair_route") or decision.get("route") or "hard_fail")
        repair_domain = decision.get("repair_domain")
        decision["repair_route"] = route
        decision["route"] = route

        decision_path = attempt_dir / "video_revision_decision.json"
        write_json(
            decision_path,
            {
                "schema_version": 1,
                "created_at": utc_now(),
                "attempt": attempt,
                "status": decision.get("status"),
                "route": route,
                "repair_route": decision.get("repair_route"),
                "repair_domain": repair_domain,
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

        if route == "content" and semantic_backtracks < max_semantic_backtracks and attempt < max_attempts:
            semantic_backtracks += 1
            backtrack_meta = run_content_backtrack(
                run_dir,
                Path(decision.get("feedback_audit_path") or attempt_dir / "gemini_visual_audit.json"),
                attempt,
                decision,
            )
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
        "visual_audit_mode": visual_mode,
        "max_attempts": max_attempts,
        "attempt_count": len(attempts),
        "semantic_backtracks": semantic_backtracks,
        "attempts": attempts,
        "failure_reason": failure_reason,
    }
    summary_path = run_dir / "video_optimization_loop.json"
    write_json(summary_path, summary)
    write_implementation_loop(
        run_dir,
        phase="video_quality_loop",
        status="completed" if status == "pass" else "failed",
        owner=IMPL_AGENT,
        artifacts={
            "video_optimization_loop": str(summary_path),
            "artifact_manifest": str(run_dir / "artifact_manifest.json") if (run_dir / "artifact_manifest.json").exists() else "",
            "final_video": str(run_dir / "video" / "final.mp4") if (run_dir / "video" / "final.mp4").exists() else "",
            "final_cover": str(run_dir / "cover" / "final.jpg") if (run_dir / "cover" / "final.jpg").exists() else "",
        },
        gates={"video_quality_loop": "pass" if status == "pass" else "fail"},
        errors=[failure_reason] if failure_reason else [],
        metadata={"attempt_count": len(attempts), "semantic_backtracks": semantic_backtracks},
    )
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
