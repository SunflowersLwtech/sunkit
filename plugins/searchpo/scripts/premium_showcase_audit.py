#!/usr/bin/env python3
"""Audit a rendered MP4 against the premium Remotion/Keynote showcase bar."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from env_utils import first_env, env_value
from gemini_api import default_gemini_mode
from gemini_visual_audit import generated_json, normalize_audit_object

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"

REQUIRED_SHOWCASE_CHECKS = {
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

REQUIRED_SCORE_KEYS = {
    "visual_premium",
    "topic_specificity",
    "knowledge_value",
    "motion_polish",
    "overall",
}
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


def latest_run_dir() -> Path:
    if not LATEST_RUN_PATH.exists():
        raise SystemExit("runtime/latest_run.txt is missing")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip()).resolve()


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


VIDEO_REFERENCE_SUFFIXES = {".mp4", ".mov", ".m4v"}


def candidate_references(raw_refs: list[str], max_reference_bytes: int, *, include_oversized: bool = True) -> list[Path]:
    refs: list[Path] = []
    for raw in raw_refs:
        path = resolve_path(raw)
        if path.is_file() and path.suffix.lower() in VIDEO_REFERENCE_SUFFIXES and (include_oversized or path.stat().st_size <= max_reference_bytes):
            refs.append(path)
    return refs[:2]


def reference_paths_from_dir(
    raw_dir: str | None,
    max_reference_bytes: int,
    *,
    limit: int = 2,
    recursive: bool = False,
    include_oversized: bool = False,
) -> list[Path]:
    if not raw_dir:
        return []
    root = resolve_path(raw_dir)
    if not root.is_dir():
        return []
    refs: list[Path] = []
    candidates = root.rglob("*") if recursive else root.iterdir()
    for path in sorted(candidates, key=lambda item: str(item).lower()):
        if len(refs) >= limit:
            break
        if not path.is_file() or path.suffix.lower() not in VIDEO_REFERENCE_SUFFIXES:
            continue
        if include_oversized or path.stat().st_size <= max_reference_bytes:
            refs.append(path)
    return refs


def audit_video_path(video_path: Path, run_dir: Path, max_bytes: int, proxy_dir: Path | None = None, *, proxy_name: str = "premium_showcase_audit_proxy.mp4") -> tuple[Path, dict[str, Any]]:
    size = video_path.stat().st_size
    if size <= max_bytes:
        return video_path, {"mode": "original", "original_video_path": str(video_path), "original_size_bytes": size}
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit(f"Rendered video is above inline Gemini audit limit and ffmpeg is unavailable: {size} > {max_bytes}")
    proxy_root = proxy_dir or run_dir
    proxy_root.mkdir(parents=True, exist_ok=True)
    proxy = proxy_root / proxy_name
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            "scale='min(1280,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "34",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(proxy),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0 or not proxy.is_file():
        raise SystemExit(f"Could not create premium showcase audit proxy: {proc.stderr[-1200:]}")
    proxy_size = proxy.stat().st_size
    if proxy_size > max_bytes:
        raise SystemExit(f"Premium showcase audit proxy remains above inline limit: {proxy_size} > {max_bytes}")
    return proxy, {
        "mode": "proxy",
        "original_video_path": str(video_path),
        "original_size_bytes": size,
        "audited_video_path": str(proxy),
        "audited_size_bytes": proxy_size,
        "ffmpeg_stderr_tail": proc.stderr[-1200:],
    }


def build_prompt(run_dir: Path, video_path: Path, references: list[Path]) -> str:
    render_payload = read_json(run_dir / "render_payload.json") if (run_dir / "render_payload.json").exists() else {}
    polish = read_json(run_dir / "deepseek_polish.json") if (run_dir / "deepseek_polish.json").exists() else {}
    video_spec = read_json(run_dir / "video_spec.json") if (run_dir / "video_spec.json").exists() else {}
    premium_spec = (
        render_payload.get("premiumDirectorSpec")
        or render_payload.get("premium_director_spec")
        or polish.get("premium_director_spec")
        or video_spec.get("premium_director_spec")
        or {}
    )
    return json.dumps(
        {
            "task": "Audit whether this generated Searchpo MP4 meets the Director-Led Premium Remotion Compiler bar.",
            "bar": {
                "visual": "Apple Keynote / Remotion showcase level: composed, topic-specific, high information design, cinematic but comfortable motion, no generic dashboard/radar/card-template feel.",
                "content": "Useful knowledge sharing: mechanism explanation, architecture position, practical fit, failure boundary, and judgment framework. Do not reward copy that shifts burden to the viewer.",
                "artifact_truth": "Judge the actual MP4, not the intent alone. Use director spec only to check whether the render followed the topic-specific plan.",
            },
            "required_output": {
                "verdict": "pass or fail",
                "summary": "one sentence",
                "checks": {
                    "premium_visual_language": "boolean; true only if composition, typography, depth, and motion feel like a premium showcase rather than a utilitarian dashboard",
                    "topic_specific_scene_design": "boolean; true when visuals are clearly generated for this topic and its source objects",
                    "not_generic_radar_or_cards": "boolean; true when it does not rely on the old Searchpo Radar/card/storyboard look as the primary visual",
                    "not_ppt_or_slide_deck": "boolean; true only when the MP4 feels like a programmatic cinematic explainer, not a sequence of static PPT/keynote slides, cards, or screenshot panels with mild fades",
                    "cinematic_motion_depth": "boolean; true only when there are visible camera moves, parallax/depth layers, mask reveals, or equivalent full-canvas choreography",
                    "information_motion_primitives": "boolean; true only when knowledge objects animate meaningfully through path drawing, counters, morphing, typewriter/code motion, architecture-flow build-up, or decision-matrix focus",
                    "knowledge_sharing_content": "boolean; true when it teaches mechanism, architecture position, fit, failure boundary, and judgment framework",
                    "motion_comfort": "boolean; true when motion is polished and frame-driven without strobe, glitch, shake, orbiting labels, or distracting sweeps",
                    "readability_and_safe_area": "boolean; true when text is readable, not overlapped, and not clipped by frame/safe areas",
                    "reference_level_depth_or_clear_gap": "boolean; true when it is competitive with supplied reference clips, or when no references are supplied, when it independently reaches the premium bar",
                },
                "scores": {
                    "visual_premium": "1-10",
                    "topic_specificity": "1-10",
                    "knowledge_value": "1-10",
                    "motion_polish": "1-10",
                    "overall": "1-10",
                },
                "issues": ["specific blocking issues; empty if pass"],
                "repair_brief": "specific next repair instruction if fail or if any score is below 8",
            },
            "scoring_rule": "A score below 8 means the video is not yet at the requested heavily-invested Apple Keynote / premium Remotion showcase bar. If any score is below 8, include concrete issues and a repair_brief even if the boolean checks are true.",
            "fail_if": [
                "The video could have been made from a generic Searchpo Radar/card template.",
                "The video feels like PPT or a static slide deck rather than a programmatic Remotion visual system.",
                "The visual design is mostly static cards, dashboards, stock-like panels, or decorative gradients without topic-specific objects.",
                "The animation is limited to slide/card fade-ins without visible camera/depth, mask/path, counter/morph, code/typewriter, or object-choreography primitives.",
                "The content tells viewers to verify, wait, observe, try it themselves, or otherwise shifts the knowledge burden to the viewer.",
                "The content lacks mechanism explanation, architecture position, practical fit, failure boundary, or a judgment framework.",
                "Motion includes strobe, glitch, shake, rotating labels, high-frequency dash sweeps, pure black frames, or unreadable transitions.",
                "Important text overlaps, clips, or fights the captions/safe area.",
            ],
            "render_payload_summary": {
                "title": render_payload.get("title"),
                "summary": render_payload.get("summary"),
                "videoProfile": render_payload.get("videoProfile"),
                "agentVisual": {
                    "enabled": (render_payload.get("agentVisual") or {}).get("enabled"),
                    "source": (render_payload.get("agentVisual") or {}).get("source"),
                    "description": (render_payload.get("agentVisual") or {}).get("description"),
                },
            },
            "premium_director_spec": premium_spec,
            "deepseek_polish": {
                "polished_title": polish.get("polished_title"),
                "voiceover_text": polish.get("voiceover_text"),
                "douyin_desc": polish.get("douyin_desc"),
            },
            "video_path": str(video_path),
            "reference_paths": [str(path) for path in references],
        },
        ensure_ascii=False,
    )


def inline_video_part(path: Path, label: str) -> dict[str, Any]:
    del label
    mime_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"inlineData": {"mimeType": mime_type, "data": data}}


def numeric_score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def decide_showcase_status(audit: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    verdict = str(audit.get("verdict") or "").lower()
    checks = audit.get("checks") if isinstance(audit.get("checks"), dict) else {}
    scores = audit.get("scores") if isinstance(audit.get("scores"), dict) else {}
    issues = [str(item).strip() for item in (audit.get("issues") or []) if str(item).strip()]
    missing_checks = sorted(REQUIRED_SHOWCASE_CHECKS - set(str(key) for key in checks.keys()))
    failed_checks = [str(key) for key, value in checks.items() if not bool(value)]
    failed_checks = sorted({*failed_checks, *missing_checks})
    score_values = {key: numeric_score(scores.get(key)) for key in REQUIRED_SCORE_KEYS}
    missing_scores = sorted(key for key in REQUIRED_SCORE_KEYS if key not in scores)
    low_scores = sorted(key for key, value in score_values.items() if value < MIN_PREMIUM_SCORE)
    overall = score_values.get("overall", 0.0)
    all_checks_pass = bool(checks) and not failed_checks
    strict_score_pass = not missing_scores and not low_scores
    status = "pass" if verdict == "pass" and all_checks_pass and not issues and strict_score_pass else "fail"
    reason = {
        "verdict": verdict,
        "overall": overall,
        "score_values": score_values,
        "minimum_required_score": MIN_PREMIUM_SCORE,
        "missing_scores": missing_scores,
        "low_scores": low_scores,
        "strict_score_pass": strict_score_pass,
        "failed_checks": failed_checks,
        "missing_required_checks": missing_checks,
        "issue_count": len(issues),
        "rule": "pass_verdict_all_required_checks_no_issues_all_scores_at_least_8",
    }
    return status, reason


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    parser.add_argument("--video", required=True, help="Rendered MP4 path.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--reference", action="append", default=[], help="Optional reference MP4. May be repeated.")
    parser.add_argument("--reference-dir", help="Directory containing optional reference MP4/MOV files.")
    parser.add_argument("--output", help="Output JSON path. Defaults to run_dir/premium_showcase_audit.json.")
    parser.add_argument("--prompt-output", help="Prompt artifact path. Defaults to run_dir/premium_showcase_audit_prompt.json.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    env_file = Path(args.env_file).resolve()
    api_key = first_env(["GOOGLE_API_KEY", "GOOGLE_AGENT_PLATFORM_API"], env_file)
    if not api_key:
        raise SystemExit("GOOGLE_API_KEY or GOOGLE_AGENT_PLATFORM_API is required for scripts/premium_showcase_audit.py")
    model = env_value("SEARCHPO_GEMINI_SHOWCASE_AUDIT_MODEL", env_file, env_value("SEARCHPO_GEMINI_AUDIT_MODEL", env_file, "gemini-3.5-flash"))
    max_generated_bytes = int(env_value("SEARCHPO_GEMINI_INLINE_VIDEO_MAX_BYTES", env_file, str(18 * 1024 * 1024)))
    max_reference_bytes = int(env_value("SEARCHPO_GEMINI_REFERENCE_VIDEO_MAX_BYTES", env_file, str(12 * 1024 * 1024)))
    video_path = resolve_path(args.video)
    if not video_path.is_file():
        raise SystemExit(f"Rendered video missing: {video_path}")
    output_path = Path(args.output).resolve() if args.output else run_dir / "premium_showcase_audit.json"
    audit_path, audit_media = audit_video_path(video_path, run_dir, max_generated_bytes, proxy_dir=output_path.parent)
    reference_dir = args.reference_dir or env_value(
        "SEARCHPO_PREMIUM_REFERENCE_DIR",
        env_file,
        "",
    )
    references = candidate_references(args.reference, max_reference_bytes, include_oversized=True)
    if len(references) < 2:
        seen = {str(path.resolve()) for path in references}
        for reference in reference_paths_from_dir(
            reference_dir,
            max_reference_bytes,
            limit=2 - len(references),
            recursive=True,
            include_oversized=True,
        ):
            key = str(reference.resolve())
            if key not in seen:
                seen.add(key)
                references.append(reference)
    reference_root = resolve_path(reference_dir) if reference_dir else None
    reference_gap_report = None
    if not references:
        reference_gap_report = {
            "status": "gap",
            "reason": "No reference MP4/MOV/M4V files were available for comparative showcase audit.",
            "expected_reference_dir": str(reference_root) if reference_root else "",
            "expected_reference_dir_exists": bool(reference_root and reference_root.is_dir()),
            "action": "Mount or provide one or more reference MP4s under SEARCHPO_PREMIUM_REFERENCE_DIR, or pass --reference explicitly.",
        }
    audited_references: list[dict[str, Any]] = []
    for index, reference in enumerate(references, start=1):
        audited_reference_path, reference_media = audit_video_path(
            reference,
            run_dir,
            max_reference_bytes,
            proxy_dir=output_path.parent,
            proxy_name=f"premium_showcase_reference_{index:02d}_proxy.mp4",
        )
        audited_references.append(
            {
                "path": reference,
                "audit_path": audited_reference_path,
                "audit_media": reference_media,
            }
        )
    prompt = build_prompt(run_dir, video_path, references)
    prompt_path = Path(args.prompt_output).resolve() if args.prompt_output else run_dir / "premium_showcase_audit_prompt.json"
    write_json(
        prompt_path,
        {
            "schema_version": 1,
            "created_at": utc_now(),
            "model": model,
            "video_path": str(video_path),
            "video_sha256": sha256_file(video_path),
            "audit_media": audit_media,
            "reference_dir": str(resolve_path(reference_dir)) if reference_dir else "",
            "references": [
                {
                    "path": str(item["path"]),
                    "sha256": sha256_file(item["path"]),
                    "bytes": item["path"].stat().st_size,
                    "audit_media": item["audit_media"],
                }
                for item in audited_references
            ],
            "prompt": prompt,
        },
    )
    parts: list[dict[str, Any]] = [
        {"text": prompt},
        {"text": "Generated Searchpo video to audit:"},
        inline_video_part(audit_path, "generated_searchpo_video"),
    ]
    for index, item in enumerate(audited_references, start=1):
        reference = item["path"]
        audited_reference_path = item["audit_path"]
        parts.append({"text": f"Reference video {index}: use only as aesthetic/depth benchmark, not as source facts."})
        parts.append(inline_video_part(audited_reference_path, f"reference_{index}"))
    audit = normalize_audit_object(generated_json(model, api_key, parts, args.timeout, env_file))
    checks = audit.get("checks") if isinstance(audit.get("checks"), dict) else {}
    scores = audit.get("scores") if isinstance(audit.get("scores"), dict) else {}
    issues = [str(item).strip() for item in (audit.get("issues") or []) if str(item).strip()]
    status, status_reason = decide_showcase_status(audit)
    derived_repair_hint = audit.get("repair_brief") or "; ".join(issues)
    if not derived_repair_hint and status != "pass":
        low_scores = status_reason.get("low_scores") if isinstance(status_reason.get("low_scores"), list) else []
        missing_checks = status_reason.get("missing_required_checks") if isinstance(status_reason.get("missing_required_checks"), list) else []
        hint_parts: list[str] = []
        if low_scores:
            hint_parts.append(f"Raise premium showcase scores to >= {MIN_PREMIUM_SCORE}: {', '.join(str(item) for item in low_scores)}")
        if missing_checks:
            hint_parts.append(f"Return and satisfy required checks: {', '.join(str(item) for item in missing_checks)}")
        derived_repair_hint = "; ".join(hint_parts)
    result = {
        "schema_version": 1,
        "created_at": utc_now(),
        "provider": "gemini",
        "model": model,
        "api_mode": default_gemini_mode(env_file),
        "status": status,
        "video_path": str(video_path),
        "video_sha256": sha256_file(video_path),
        "video_size_bytes": video_path.stat().st_size,
        "audit_media": audit_media,
        "reference_status": "included" if references else "no_reference_available",
        "reference_dir": str(resolve_path(reference_dir)) if reference_dir else "",
        "reference_gap_report": reference_gap_report,
        "references": [
            {
                "path": str(item["path"]),
                "sha256": sha256_file(item["path"]),
                "bytes": item["path"].stat().st_size,
                "audit_media": item["audit_media"],
            }
            for item in audited_references
        ],
        "prompt_artifact": str(prompt_path),
        "audit": audit,
        "verdict": audit.get("verdict"),
        "summary": audit.get("summary"),
        "checks": checks,
        "scores": scores,
        "issues": issues,
        "repair_brief": audit.get("repair_brief"),
        "status_reason": status_reason,
        "failed_checks": status_reason["failed_checks"] if isinstance(status_reason.get("failed_checks"), list) else [str(key) for key, value in checks.items() if not bool(value)],
        "repair_hint": derived_repair_hint,
    }
    write_json(output_path, result)
    print(json.dumps({"premium_showcase_audit": str(output_path), "status": status}, ensure_ascii=False, indent=2))
    if status != "pass":
        raise SystemExit(f"Premium showcase audit failed: {audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
