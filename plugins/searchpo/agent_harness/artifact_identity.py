from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_harness.side_effect_tiers import side_effect_axes


FINAL_VIDEO_REL = Path("video/final.mp4")
FINAL_COVER_REL = Path("cover/final.jpg")


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


def sha256_json_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _copy_artifact(src: Path, dst: Path) -> dict[str, Any]:
    if not src.is_file():
        raise FileNotFoundError(f"artifact source missing: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return {
        "path": str(dst),
        "sha256": sha256_file(dst),
        "bytes": dst.stat().st_size,
    }


def _maybe_read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def _relative_display(path: Path, run_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(run_dir.resolve()))
    except ValueError:
        return str(path)


def _selected_candidate(run_dir: Path) -> dict[str, Any]:
    return _maybe_read(run_dir / "selected_candidate.json")


def _source_url(candidate: dict[str, Any]) -> str:
    url = str(candidate.get("canonical_url") or "")
    return "" if url.startswith("manual-topic://") else url


def create_or_update_artifact_manifest(
    run_dir: Path,
    *,
    rendered_video: Path,
    rendered_cover: Path,
    render_mode: str,
    publish_mode: str,
    execution_profile: str | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    inferred_profile = execution_profile
    if inferred_profile is None:
        if publish_mode == "live":
            inferred_profile = "live"
        elif render_mode == "lambda":
            inferred_profile = "lambda"
        elif render_mode == "local" and publish_mode == "contract-check":
            inferred_profile = "provider"
    axes = side_effect_axes(inferred_profile)
    if render_mode != axes["render_mode"]:
        axes = {**axes, "render_mode": render_mode}
    if publish_mode != axes["publish_mode"]:
        axes = {**axes, "publish_mode": publish_mode}
    video = _copy_artifact(rendered_video.resolve(), run_dir / FINAL_VIDEO_REL)
    cover = _copy_artifact(rendered_cover.resolve(), run_dir / FINAL_COVER_REL)
    candidate = _selected_candidate(run_dir)
    render_input_manifest = _maybe_read(run_dir / "render_input_manifest.json")
    render_payload_path = run_dir / "render_payload.json"
    captions_path = run_dir / "captions.json"
    voiceover_manifest_path = run_dir / "voiceover_manifest.json"
    voiceover_manifest = _maybe_read(voiceover_manifest_path)
    voiceover_path = Path(str(voiceover_manifest.get("audio_path") or run_dir / "voiceover.wav"))
    if not voiceover_path.is_absolute():
        voiceover_path = run_dir / voiceover_path

    manifest = {
        "schema_version": 1,
        "created_at": utc_now(),
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        **axes,
        "selected_candidate_id": candidate.get("candidate_id"),
        "candidate_id": candidate.get("candidate_id"),
        "selected_candidate_title": candidate.get("title"),
        "selected_candidate_url": _source_url(candidate),
        "render_props_path": render_input_manifest.get("props") or str(run_dir / "remotion_input_props.json"),
        "render_props_sha256": render_input_manifest.get("props_sha256")
        or sha256_json_file(run_dir / "remotion_input_props.json"),
        "render_props_hash": render_input_manifest.get("props_sha256")
        or sha256_json_file(run_dir / "remotion_input_props.json"),
        "render_payload_sha256": sha256_json_file(render_payload_path),
        "topic_brief_sha256": sha256_json_file(run_dir / "topic_brief.json"),
        "fact_bank_sha256": sha256_json_file(run_dir / "fact_bank.json"),
        "source_map_sha256": sha256_json_file(run_dir / "source_map.json"),
        "script_sha256": sha256_json_file(run_dir / "script.json"),
        "scene_plan_sha256": sha256_json_file(run_dir / "scene_plan.json"),
        "video_spec_sha256": sha256_json_file(run_dir / "video_spec.json"),
        "environment_manifest_sha256": sha256_json_file(run_dir / "environment_manifest.json"),
        "captions_sha256": sha256_json_file(captions_path),
        "voiceover_manifest_sha256": sha256_json_file(voiceover_manifest_path),
        "voiceover_sha256": sha256_file(voiceover_path) if voiceover_path.is_file() else None,
        "final_video_path": video["path"],
        "final_video_sha256": video["sha256"],
        "mp4_hash": video["sha256"],
        "final_video_bytes": video["bytes"],
        "cover_path": cover["path"],
        "cover_sha256": cover["sha256"],
        "cover_hash": cover["sha256"],
        "cover_bytes": cover["bytes"],
        "preview_video_path": str(rendered_video.resolve()),
        "preview_cover_path": str(rendered_cover.resolve()),
        "artifact_layout": {
            "publishable": {
                "video": str(FINAL_VIDEO_REL),
                "cover": str(FINAL_COVER_REL),
                "manifest": "artifact_manifest.json",
                "delivery": "delivery_package.json",
                "final_truth": "run_final.json",
            },
            "preview": {
                "video": _relative_display(rendered_video, run_dir),
                "cover": _relative_display(rendered_cover, run_dir),
                "policy": "preview files are scratch inputs for artifact binding; publish adapters must use publishable paths",
            },
            "optimization": {
                "video_attempts": "optimization/video/attempt-XX/",
                "content_attempts": "optimization/content/attempt-XX/",
            },
            "post": {
                "douyin_manifest": "post/douyin_upload_manifest.json",
                "douyin_check": "post/douyin_upload_check.json",
                "post_publish_verification": "post/post_publish_verification.json",
            },
        },
    }
    manifest["publish_hash"] = sha256_text(
        json.dumps(
            {
                "run_id": manifest["run_id"],
                "candidate_id": manifest["candidate_id"],
                "execution_profile": axes["execution_profile"],
                "render_mode": axes["render_mode"],
                "publish_mode": axes["publish_mode"],
                "mp4_hash": manifest["mp4_hash"],
                "cover_hash": manifest["cover_hash"],
                "render_props_hash": manifest["render_props_hash"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    write_json(run_dir / "artifact_manifest.json", manifest)
    update_douyin_upload_manifest(run_dir, manifest)
    return manifest


def update_douyin_upload_manifest(run_dir: Path, artifact_manifest: dict[str, Any]) -> dict[str, Any]:
    path = run_dir / "post" / "douyin_upload_manifest.json"
    manifest = _maybe_read(path)
    manifest.update(
        {
            "schema_version": max(int(manifest.get("schema_version") or 1), 3),
            "artifact_bound_at": utc_now(),
            "manifest_status": "artifact-bound",
            "run_id": artifact_manifest.get("run_id"),
            "selected_candidate_id": artifact_manifest.get("selected_candidate_id"),
            "execution_profile": artifact_manifest.get("execution_profile"),
            "side_effect_tier": artifact_manifest.get("side_effect_tier"),
            "expected_video_path": artifact_manifest.get("final_video_path"),
            "expected_video_sha256": artifact_manifest.get("final_video_sha256"),
            "expected_video_bytes": artifact_manifest.get("final_video_bytes"),
            "cover_path": artifact_manifest.get("cover_path"),
            "cover_sha256": artifact_manifest.get("cover_sha256"),
            "render_mode": artifact_manifest.get("render_mode"),
            "publish_mode": artifact_manifest.get("publish_mode"),
            "render_props_sha256": artifact_manifest.get("render_props_sha256"),
            "render_props_hash": artifact_manifest.get("render_props_hash"),
            "render_payload_sha256": artifact_manifest.get("render_payload_sha256"),
            "topic_brief_sha256": artifact_manifest.get("topic_brief_sha256"),
            "fact_bank_sha256": artifact_manifest.get("fact_bank_sha256"),
            "source_map_sha256": artifact_manifest.get("source_map_sha256"),
            "script_sha256": artifact_manifest.get("script_sha256"),
            "scene_plan_sha256": artifact_manifest.get("scene_plan_sha256"),
            "video_spec_sha256": artifact_manifest.get("video_spec_sha256"),
            "environment_manifest_sha256": artifact_manifest.get("environment_manifest_sha256"),
            "voiceover_sha256": artifact_manifest.get("voiceover_sha256"),
            "captions_sha256": artifact_manifest.get("captions_sha256"),
            "mp4_hash": artifact_manifest.get("mp4_hash"),
            "cover_hash": artifact_manifest.get("cover_hash"),
            "publish_hash": artifact_manifest.get("publish_hash"),
            "artifact_manifest": str(run_dir / "artifact_manifest.json"),
        }
    )
    write_json(path, manifest)
    return manifest


def validate_upload_identity(
    run_dir: Path,
    *,
    video_path: Path,
    cover_path: Path | None,
    live: bool,
) -> tuple[list[str], dict[str, Any]]:
    manifest_path = run_dir / "post" / "douyin_upload_manifest.json"
    manifest = _maybe_read(manifest_path)
    errors: list[str] = []
    checks: dict[str, Any] = {
        "manifest_path": str(manifest_path),
        "video_path": str(video_path),
        "cover_path": str(cover_path) if cover_path else "",
        "video_inside_run_dir": is_relative_to(video_path, run_dir),
        "cover_inside_run_dir": is_relative_to(cover_path, run_dir) if cover_path else False,
    }
    if not manifest:
        errors.append(f"douyin upload manifest missing: {manifest_path}")
        return errors, checks
    if manifest.get("manifest_status") != "artifact-bound":
        errors.append("douyin_upload_manifest.json is not artifact-bound; run finalize_artifacts first")
    expected_mode = "live" if live else "contract-check"
    if manifest.get("publish_mode") != expected_mode:
        errors.append(f"publish mode mismatch: manifest={manifest.get('publish_mode')} expected={expected_mode}")
    if manifest.get("run_id") != run_dir.name:
        errors.append(f"run id mismatch: manifest={manifest.get('run_id')} run_dir={run_dir.name}")
    expected_video = Path(str(manifest.get("expected_video_path") or "")).expanduser()
    if not expected_video.is_absolute():
        expected_video = run_dir / expected_video
    if expected_video.resolve() != video_path.resolve():
        errors.append(f"upload video path does not match manifest expected path: {video_path} != {expected_video}")
    if not is_relative_to(video_path, run_dir):
        errors.append(f"upload video must be run-scoped, got: {video_path}")
    if not video_path.is_file():
        errors.append(f"upload video missing: {video_path}")
    else:
        actual_hash = sha256_file(video_path)
        checks["actual_video_sha256"] = actual_hash
        checks["expected_video_sha256"] = manifest.get("expected_video_sha256")
        if actual_hash != manifest.get("expected_video_sha256"):
            errors.append("upload video sha256 does not match douyin_upload_manifest.json")
    if cover_path is None or not cover_path.is_file():
        errors.append(f"upload cover missing: {cover_path}")
    else:
        actual_cover_hash = sha256_file(cover_path)
        checks["actual_cover_sha256"] = actual_cover_hash
        checks["expected_cover_sha256"] = manifest.get("cover_sha256")
        if actual_cover_hash != manifest.get("cover_sha256"):
            errors.append("upload cover sha256 does not match douyin_upload_manifest.json")
    return errors, checks


def publish_conflict_errors(
    board_snapshot: dict[str, Any],
    publish_mode: str,
    *,
    allow_live_upgrade: bool = False,
) -> list[str]:
    gates = board_snapshot.get("gates") or []
    gate_names = {str(gate.get("name") or "") for gate in gates}
    errors: list[str] = []
    contract_names = {"douyin_contract_check_passed", "douyin_contract_gate"}
    live_names = {"explicit_live_publish_gate", "douyin_live_publish_gate"}
    if allow_live_upgrade and publish_mode == "live" and gate_names & live_names:
        return errors
    if gate_names & contract_names and gate_names & live_names:
        errors.append("same run contains both contract and live publish gates")
    if publish_mode == "contract-check" and gate_names & live_names:
        errors.append("contract run contains live publish gate")
    if publish_mode == "live" and gate_names & contract_names:
        errors.append("live run contains contract publish gate")
    return errors
