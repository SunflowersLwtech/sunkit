#!/usr/bin/env python3
"""Score polished content quality via Gemini for searchpo quality gate."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

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
        raise SystemExit("runtime/latest_run.txt is missing")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip()).resolve()


def score_content(api_key: str, model: str, polish: dict[str, Any], candidate: dict[str, Any], timeout: float, env_file: Path) -> dict[str, Any]:
    url = generate_content_url(model, api_key, env_file)
    prompt = json.dumps({
        "task": "Score this short-video content package for Douyin quality. Return JSON only.",
        "scoring_dimensions": {
            "hook_strength": "1-10: Does the title/opening grab attention in first 2 seconds?",
            "information_density": "1-10: Is the voiceover packed with useful info, no filler?",
            "emotional_tension": "1-10: Does it create curiosity, surprise, or urgency?",
            "claim_safety": "1-10: Are claims properly bounded? No hype without evidence?",
            "douyin_algorithm_fit": "1-10: Title/tags optimized for Douyin recommendation engine?",
        },
        "required_output": {
            "scores": {"hook_strength": "int", "information_density": "int", "emotional_tension": "int", "claim_safety": "int", "douyin_algorithm_fit": "int"},
            "overall": "float (weighted average, hook=0.3, density=0.25, emotion=0.2, safety=0.15, algo=0.1)",
            "suggestions": ["1-3 specific improvement suggestions"],
            "verdict": "pass (overall >= 6.0) or improve (overall < 6.0)",
        },
        "content": {
            "polished_title": polish.get("polished_title"),
            "voiceover_text": polish.get("voiceover_text"),
            "douyin_title": polish.get("douyin_title"),
            "douyin_desc": polish.get("douyin_desc"),
            "tags": polish.get("tags"),
            "cards": polish.get("cards"),
        },
        "candidate_context": {
            "title": candidate.get("title"),
            "source_ids": candidate.get("source_ids"),
            "candidate_score": candidate.get("candidate_score"),
        },
    }, ensure_ascii=False)

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
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
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
            if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(3.0 * (2 ** attempt))
                last_exc = RuntimeError(f"Gemini scorer HTTP {exc.code}: {detail}")
                continue
            raise RuntimeError(f"Gemini scorer HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                time.sleep(3.0 * (2 ** attempt))
                last_exc = RuntimeError(f"Gemini scorer network: {exc}")
                continue
            raise RuntimeError(f"Gemini scorer network: {exc}") from exc
    else:
        raise last_exc or RuntimeError("Gemini scorer exhausted retries")

    text = ""
    for c in payload.get("candidates") or []:
        for part in ((c.get("content") or {}).get("parts") or []):
            text += part.get("text") or ""
    if not text:
        raise RuntimeError("Gemini scorer returned no text")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    env_file = Path(args.env_file).resolve()
    api_key = first_env(["GOOGLE_API_KEY", "GOOGLE_AGENT_PLATFORM_API"], env_file)
    if not api_key:
        raise SystemExit("GOOGLE_API_KEY or GOOGLE_AGENT_PLATFORM_API is required")
    model = env_value("SEARCHPO_GEMINI_SCORER_MODEL", env_file, "gemini-3.5-flash")

    polish_path = run_dir / "deepseek_polish.json"
    candidate_path = run_dir / "selected_candidate.json"
    if not polish_path.exists() or not candidate_path.exists():
        raise SystemExit("deepseek_polish.json and selected_candidate.json required")

    polish = read_json(polish_path)
    candidate = read_json(candidate_path)
    result = score_content(api_key, model, polish, candidate, args.timeout, env_file)

    output = {
        "schema_version": 1,
        "created_at": utc_now(),
        "provider": "gemini",
        "model": model,
        "scores": result.get("scores") or {},
        "overall": result.get("overall") or 0,
        "suggestions": result.get("suggestions") or [],
        "verdict": result.get("verdict") or "improve",
    }
    output_path = run_dir / "content_score.json"
    write_json(output_path, output)
    print(json.dumps({"content_score": str(output_path), "overall": output["overall"], "verdict": output["verdict"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
