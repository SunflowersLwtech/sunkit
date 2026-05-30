#!/usr/bin/env python3
"""Audit a rendered searchpo MP4 through Gemini before publish."""

from __future__ import annotations

import argparse
import base64
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
                    "publish_ready": "boolean",
                },
                "issues": ["array of concrete issues; empty if pass"],
            },
            "fail_if": policy_get("gemini_visual_audit.fail_if", []),
            "forbidden_claim_terms": unsupported_terms(),
            "enhanced_checks": policy_get("gemini_visual_audit.enhanced_checks", []),
            "important": policy_get("gemini_visual_audit.important", ""),
            "selected_candidate": selected,
            "render_payload": render_payload,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    parser.add_argument("--video", default="", help="Rendered MP4 path. Defaults to lambda output, then local output.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    env_file = Path(args.env_file).resolve()
    api_key = first_env(["GOOGLE_API_KEY", "GOOGLE_AGENT_PLATFORM_API"], env_file)
    if not api_key:
        raise SystemExit("GOOGLE_API_KEY or GOOGLE_AGENT_PLATFORM_API is required for scripts/gemini_visual_audit.py")
    model = env_value("SEARCHPO_GEMINI_AUDIT_MODEL", env_file, "gemini-3.5-flash")
    max_bytes = int(env_value("SEARCHPO_GEMINI_INLINE_VIDEO_MAX_BYTES", env_file, str(18 * 1024 * 1024)))
    if args.video:
        video_path = Path(args.video).expanduser()
        if not video_path.is_absolute():
            video_path = ROOT / video_path
    else:
        lambda_path = ROOT / "out" / "searchpo-radar-lambda.mp4"
        local_path = ROOT / "out" / "searchpo-radar.mp4"
        video_path = lambda_path if lambda_path.exists() else local_path
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
    result = {
        "schema_version": 1,
        "created_at": utc_now(),
        "provider": "gemini",
        "model": model,
        "api_mode": default_gemini_mode(env_file),
        "status": status,
        "video_path": str(video_path),
        "video_size_bytes": video_size,
        "audit": audit,
        "elapsed_reference": time.time(),
    }
    output_path = run_dir / "gemini_visual_audit.json"
    write_json(output_path, result)
    print(json.dumps({"gemini_visual_audit": str(output_path), "status": status}, ensure_ascii=False, indent=2))
    if status != "pass":
        raise SystemExit(f"Gemini visual audit failed: {audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
