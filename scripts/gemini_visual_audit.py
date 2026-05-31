#!/usr/bin/env python3
"""Audit a rendered searchpo MP4 through Gemini before publish."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from agent_harness.policy import policy_get, unsupported_terms
from env_utils import first_env, env_value
from gemini_api import default_gemini_mode, generate_content_url

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"


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
        raise SystemExit("runtime/latest_run.txt is missing; run data_prep/scripts/run_pipeline.py first")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip()).resolve()


def generated_json(model: str, api_key: str, parts: list[dict[str, Any]], timeout: float, env_file: Path) -> dict[str, Any]:
    url = generate_content_url(model, api_key, env_file)
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-1200:]
            if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                delay = 4.0 * (2 ** attempt)
                print(f"Gemini audit HTTP {exc.code}, retrying in {delay:.0f}s (attempt {attempt+1}/3)...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"Gemini audit HTTP {exc.code}: {detail}")
                continue
            raise RuntimeError(f"Gemini visual audit HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                delay = 4.0 * (2 ** attempt)
                print(f"Gemini audit network error, retrying in {delay:.0f}s (attempt {attempt+1}/3)...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"Gemini audit network error: {exc}")
                continue
            raise RuntimeError(f"Gemini visual audit network error: {exc}") from exc
    else:
        raise last_exc or RuntimeError("Gemini audit exhausted retries")
    text = ""
    for candidate in payload.get("candidates") or []:
        for part in ((candidate.get("content") or {}).get("parts") or []):
            text += part.get("text") or ""
    if not text:
        raise RuntimeError(f"Gemini visual audit returned no text: {json.dumps(payload, ensure_ascii=False)[:1000]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def build_prompt(run_dir: Path, video_path: Path) -> str:
    selected = read_json(run_dir / "selected_candidate.json")
    render_payload = read_json(run_dir / "render_payload.json")
    polish = read_json(run_dir / "deepseek_polish.json")
    claims_path = run_dir / "post" / "claims_ledger.json"
    claims = read_json(claims_path) if claims_path.exists() else {}
    evidence_path = run_dir / "evidence_bundle.json"
    cross_check_path = run_dir / "cross_check_review.json"
    evidence_bundle = read_json(evidence_path) if evidence_path.exists() else {}
    cross_check_review = read_json(cross_check_path) if cross_check_path.exists() else {}
    return json.dumps(
        {
            "task": "Audit this rendered vertical searchpo video before Douyin publishing.",
            "required_output": {
                "verdict": "pass or fail",
                "summary": "one sentence",
                "checks": {
                    "video_readable": "boolean",
                    "text_not_overlapping": "boolean",
                    "candidate_matches_artifacts": "boolean",
                    "no_unsupported_claims": "boolean",
                    "voiceover_matches_copy": "boolean; true when voiceover and visible copy are consistent, exact wording is not required",
                    "cover_text_safe": "boolean; true when cover title and metric are fully inside the frame and readable",
                    "douyin_safe_area": "boolean; true when captions avoid the lower platform UI obstruction area",
                    "no_internal_terms": "boolean; true when public copy does not expose pipeline terms",
                    "no_hype_without_evidence": "boolean; true when unverified topics are not framed as industry-changing conclusions",
                    "speech_pronunciation_safe": "boolean; true when the voiceover does not read raw slashes, URLs, or symbols",
                    "audio_visual_alignment_safe": "boolean; true when caption/card timing follows the spoken beat",
                    "publish_ready": "boolean",
                    "content_has_constructive_insight": "boolean; true when the video explains problem, mechanism, tradeoff, and verification path from evidence",
                },
                "issues": ["array of concrete issues; empty if pass"],
            },
            "fail_if": policy_get("gemini_visual_audit.fail_if", []),
            "forbidden_claim_terms": unsupported_terms(),
            "enhanced_checks": policy_get("gemini_visual_audit.enhanced_checks", []),
            "important": policy_get("gemini_visual_audit.important", ""),
            "selected_candidate": selected,
            "render_payload": render_payload,
            "evidence_bundle": evidence_bundle,
            "cross_check_review": cross_check_review,
            "deepseek_polish": {
                "polished_title": polish.get("polished_title"),
                "voiceover_text": polish.get("voiceover_text"),
                "douyin_title": polish.get("douyin_title"),
                "douyin_desc": polish.get("douyin_desc"),
            },
            "claims_ledger": claims,
            "video_path": str(video_path),
        },
        ensure_ascii=False,
    )


def classify_audit_result(audit: dict[str, Any], status: str) -> dict[str, Any]:
    checks = audit.get("checks") if isinstance(audit.get("checks"), dict) else {}
    failed_checks = [str(key) for key, value in checks.items() if not bool(value)]
    repairable = set(str(item) for item in policy_get("video_optimization.repairable_checks", []))
    semantic = set(str(item) for item in policy_get("video_optimization.semantic_checks", []))
    hard_fail = set(str(item) for item in policy_get("video_optimization.hard_fail_checks", []))
    issues = [str(item) for item in (audit.get("issues") or []) if str(item).strip()]
    route = "hard_fail"
    if status == "pass":
        route = "none"
    elif any(check in hard_fail for check in failed_checks):
        route = "hard_fail"
    elif any(check in semantic for check in failed_checks):
        route = "content"
    elif "cover_text_safe" in failed_checks:
        route = "cover"
    elif "douyin_safe_area" in failed_checks or "audio_visual_alignment_safe" in failed_checks:
        route = "caption"
    elif any(check in repairable for check in failed_checks):
        route = "storyboard"
    hint_map = policy_get("video_optimization.repair_actions", {})
    hint_value = hint_map.get(route) if isinstance(hint_map, dict) else None
    if isinstance(hint_value, list):
        repair_hint = "; ".join(str(item) for item in hint_value if str(item).strip())
    else:
        repair_hint = str(hint_value or "")
    return {
        "failed_checks": failed_checks,
        "severity": "none" if status == "pass" else "blocking",
        "repair_route": route,
        "repair_hint": repair_hint or "; ".join(issues),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    parser.add_argument("--video", required=True, help="Rendered MP4 path.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output", help="Output JSON path. Defaults to run_dir/gemini_visual_audit.json.")
    parser.add_argument("--prompt-output", help="Prompt artifact path. Defaults to run_dir/gemini_visual_audit_prompt.json.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    env_file = Path(args.env_file).resolve()
    api_key = first_env(["GOOGLE_API_KEY", "GOOGLE_AGENT_PLATFORM_API"], env_file)
    if not api_key:
        raise SystemExit("GOOGLE_API_KEY or GOOGLE_AGENT_PLATFORM_API is required for scripts/gemini_visual_audit.py")
    model = env_value("SEARCHPO_GEMINI_AUDIT_MODEL", env_file, "gemini-3.5-flash")
    max_bytes = int(env_value("SEARCHPO_GEMINI_INLINE_VIDEO_MAX_BYTES", env_file, str(18 * 1024 * 1024)))
    video_path = Path(args.video).expanduser()
    if not video_path.is_absolute():
        video_path = ROOT / video_path
    if not video_path.is_file():
        raise SystemExit(f"Rendered video missing: {video_path}")
    video_size = video_path.stat().st_size
    if video_size > max_bytes:
        raise SystemExit(
            f"Rendered video is {video_size} bytes, above inline Gemini audit limit {max_bytes}. "
            "Lower render size or raise SEARCHPO_GEMINI_INLINE_VIDEO_MAX_BYTES after confirming API limits."
        )
    mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
    prompt = build_prompt(run_dir, video_path)
    prompt_path = Path(args.prompt_output).resolve() if args.prompt_output else run_dir / "gemini_visual_audit_prompt.json"
    write_json(
        prompt_path,
        {
            "schema_version": 1,
            "created_at": utc_now(),
            "model": model,
            "video_path": str(video_path),
            "video_sha256": sha256_file(video_path),
            "prompt": prompt,
        },
    )
    video_data = base64.b64encode(video_path.read_bytes()).decode("ascii")
    audit = generated_json(
        model,
        api_key,
        [
            {"text": prompt},
            {"inlineData": {"mimeType": mime_type, "data": video_data}},
        ],
        args.timeout,
        env_file,
    )
    verdict = str(audit.get("verdict") or "").lower()
    checks = audit.get("checks") if isinstance(audit.get("checks"), dict) else {}
    status = "pass" if verdict == "pass" and all(bool(value) for value in checks.values()) else "fail"
    classification = classify_audit_result(audit, status)
    result = {
        "schema_version": 1,
        "created_at": utc_now(),
        "provider": "gemini",
        "model": model,
        "api_mode": default_gemini_mode(env_file),
        "status": status,
        "video_path": str(video_path),
        "video_sha256": sha256_file(video_path),
        "video_size_bytes": video_size,
        "prompt_artifact": str(prompt_path),
        "deterministic_visual_audit": str(run_dir / "visual_audit_deterministic.json")
        if (run_dir / "visual_audit_deterministic.json").exists()
        else None,
        "audit": audit,
        **classification,
        "elapsed_reference": time.time(),
    }
    output_path = Path(args.output).resolve() if args.output else run_dir / "gemini_visual_audit.json"
    write_json(output_path, result)
    print(json.dumps({"gemini_visual_audit": str(output_path), "status": status}, ensure_ascii=False, indent=2))
    if status != "pass":
        raise SystemExit(f"Gemini visual audit failed: {audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
