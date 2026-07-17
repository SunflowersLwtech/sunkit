from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_harness.core import utc_now


def _maybe_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _rel(path: str | Path | None, run_dir: Path) -> str:
    if not path:
        return ""
    value = Path(str(path))
    try:
        return str(value.resolve().relative_to(run_dir.resolve()))
    except ValueError:
        return str(value)


def _line(label: str, path: str | Path | None, run_dir: Path) -> str:
    value = _rel(path, run_dir)
    return f"- {label}: `{value}`" if value else f"- {label}: missing"


def write_run_index(
    run_dir: Path,
    *,
    final: dict[str, Any] | None = None,
    artifact_manifest: dict[str, Any] | None = None,
    delivery_package: dict[str, Any] | None = None,
    release_gate: dict[str, Any] | None = None,
) -> Path:
    """Write a compact human-readable index for the run directory."""
    run_dir = run_dir.resolve()
    artifact_manifest = artifact_manifest or _maybe_json(run_dir / "artifact_manifest.json")
    delivery_package = delivery_package or _maybe_json(run_dir / "delivery_package.json")
    release_gate = release_gate or _maybe_json(run_dir / "release_gate.json")
    final = final or _maybe_json(run_dir / "run_final.json")
    selected_title = (
        artifact_manifest.get("selected_candidate_title")
        or (delivery_package.get("metadata") or {}).get("title")
        or final.get("selected_candidate_id")
        or run_dir.name
    )
    status = final.get("status") or release_gate.get("status") or delivery_package.get("status") or "unknown"
    publish_status = final.get("publish_status") or release_gate.get("publish_status") or delivery_package.get("publish_status") or "unknown"
    errors = final.get("errors") or release_gate.get("errors") or delivery_package.get("errors") or []
    if not isinstance(errors, list):
        errors = [str(errors)]

    lines = [
        f"# Searchpo Run {run_dir.name}",
        "",
        f"- generated_at: `{utc_now()}`",
        f"- status: `{status}`",
        f"- publish_status: `{publish_status}`",
        f"- execution_profile: `{artifact_manifest.get('execution_profile') or final.get('execution_profile') or 'unknown'}`",
        f"- render_mode: `{artifact_manifest.get('render_mode') or final.get('render_mode') or 'unknown'}`",
        f"- publish_mode: `{artifact_manifest.get('publish_mode') or final.get('publish_mode') or 'unknown'}`",
        f"- title: {selected_title}",
        f"- source: {artifact_manifest.get('selected_candidate_url') or 'manual-topic-or-missing'}",
        "",
        "## Open First",
        "",
        _line("Final decision", run_dir / "run_final.json", run_dir),
        _line("Release gate", run_dir / "release_gate.json", run_dir),
        _line("Delivery package", run_dir / "delivery_package.json", run_dir),
        _line("Artifact manifest", run_dir / "artifact_manifest.json", run_dir),
        _line("Final video", artifact_manifest.get("final_video_path"), run_dir),
        _line("Final cover", artifact_manifest.get("cover_path"), run_dir),
        "",
        "## Evidence Chain",
        "",
        _line("Research barrier", run_dir / "research_barrier.json", run_dir),
        _line("Runtime contract", run_dir / "runtime_contract.json", run_dir),
        _line("Topic brief", run_dir / "topic_brief.json", run_dir),
        _line("Fact bank", run_dir / "fact_bank.json", run_dir),
        _line("Source map", run_dir / "source_map.json", run_dir),
        _line("Cross-check review", run_dir / "cross_check_review.json", run_dir),
        "",
        "## Implementation Chain",
        "",
        _line("Implementation loop", run_dir / "implementation_loop.json", run_dir),
        _line("Content optimization", run_dir / "content_optimization_loop.json", run_dir),
        _line("Script", run_dir / "script.json", run_dir),
        _line("Scene plan", run_dir / "scene_plan.json", run_dir),
        _line("Video spec", run_dir / "video_spec.json", run_dir),
        _line("Render payload", run_dir / "render_payload.json", run_dir),
        _line("Video optimization loop", run_dir / "video_optimization_loop.json", run_dir),
        "",
        "## Audit And Publish",
        "",
        _line("Render metadata", run_dir / "render_metadata_check.json", run_dir),
        _line("Deterministic visual audit", run_dir / "visual_audit_deterministic.json", run_dir),
        _line("Gemini visual audit", run_dir / "gemini_visual_audit.json", run_dir),
        _line("Douyin upload check", run_dir / "post" / "douyin_upload_check.json", run_dir),
        _line("Post-publish verification", run_dir / "post" / "post_publish_verification.json", run_dir),
        "",
        "## Preview Scratch",
        "",
        _line("Preview video used for binding", artifact_manifest.get("preview_video_path"), run_dir),
        _line("Preview cover used for binding", artifact_manifest.get("preview_cover_path"), run_dir),
        "- Note: preview paths under `out/previews/` are scratch outputs; publish input must be `video/final.mp4` and `cover/final.jpg`.",
    ]
    if errors:
        lines.extend(["", "## Blocking Errors", ""])
        lines.extend(f"- {str(error)}" for error in errors)
    index_path = run_dir / "RUN.md"
    index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return index_path
