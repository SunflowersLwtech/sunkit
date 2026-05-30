#!/usr/bin/env python3
"""Polish the selected searchpo candidate through DeepSeek and write run artifacts."""

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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from agent_harness.policy import policy_get, policy_format, unsupported_claim_regex, unsupported_terms
from env_utils import env_value

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"
UNSAFE_RE = unsupported_claim_regex()


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


def bounded_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def require_list(value: Any, key: str, max_items: int) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"DeepSeek response missing non-empty `{key}` list")
    rows = [bounded_text(item, 40) for item in value[:max_items] if str(item).strip()]
    if not rows:
        raise RuntimeError(f"DeepSeek response `{key}` list has no usable values")
    return rows


def parse_deepseek_payload(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    required = policy_get("deepseek.required_keys", ["polished_title", "voiceover_text", "douyin_title", "douyin_desc", "tags", "cards"])
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise RuntimeError(f"DeepSeek response missing fields: {', '.join(missing)}")
    tags = require_list(data["tags"], "tags", 5)
    cards = data["cards"]
    if not isinstance(cards, list) or len(cards) < 3:
        raise RuntimeError("DeepSeek response missing at least 3 cards")
    clean_cards = []
    for index, card in enumerate(cards[:3], start=1):
        if not isinstance(card, dict):
            raise RuntimeError(f"DeepSeek card {index} is not an object")
        clean_cards.append(
            {
                "label": bounded_text(card.get("label"), 18),
                "value": bounded_text(card.get("value"), 54),
                "detail": bounded_text(card.get("detail"), 118),
            }
        )
    data["tags"] = tags
    data["cards"] = clean_cards
    return data


def deepseek_chat(api_key: str, model: str, candidate: dict[str, Any], content_plan: dict[str, Any], timeout: float, temperature: float = 0.4, video_seconds: int = 12) -> dict[str, Any]:
    chars_per_second = int(policy_get("deepseek.chars_per_second", 7))
    lo = max(60, video_seconds * chars_per_second - 30)
    hi = video_seconds * chars_per_second + 20
    voiceover_chars_range = f"{lo}-{hi} Chinese characters"
    system = policy_get("deepseek.system", "Return strict JSON only.")
    constraints = [
        policy_format(item, voiceover_chars_range=voiceover_chars_range, video_seconds=video_seconds)
        for item in policy_get("deepseek.constraints", [])
    ]
    user = {
        "task": "Polish one short-form video package for Douyin and Remotion.",
        "constraints": constraints,
        "forbidden_claim_terms": unsupported_terms(),
        "selected_candidate": candidate,
        "content_plan": content_plan,
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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
                delay = 3.0 * (2 ** attempt)
                print(f"DeepSeek HTTP {exc.code}, retrying in {delay:.0f}s (attempt {attempt+1}/3)...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}")
                continue
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                delay = 3.0 * (2 ** attempt)
                print(f"DeepSeek network error, retrying in {delay:.0f}s (attempt {attempt+1}/3)...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"DeepSeek network error: {exc}")
                continue
            raise RuntimeError(f"DeepSeek network error: {exc}") from exc
    else:
        raise last_exc or RuntimeError("DeepSeek call exhausted retries")
    content = payload["choices"][0]["message"]["content"]
    parsed = parse_deepseek_payload(content)
    parsed["_raw_usage"] = payload.get("usage")
    return parsed


def _score_polish(polished: dict[str, Any]) -> float:
    """Heuristic quality score: information density, hook strength, length fit."""
    score = 0.0
    voiceover = str(polished.get("voiceover_text") or "")
    cn_chars = len(re.findall(r"[一-鿿]", voiceover))
    if 60 <= cn_chars <= 600:
        score += 3.0
    elif 40 <= cn_chars <= 700:
        score += 1.5
    title = str(polished.get("polished_title") or "")
    if any(hook in title for hook in policy_get("deepseek.hook_terms", ["为什么", "怎么"])):
        score += 2.0
    cards = polished.get("cards") or []
    if len(cards) >= 3 and all(len(str(c.get("value") or "")) > 4 for c in cards):
        score += 2.0
    if polished.get("caveats"):
        score += 1.0
    return score


def _multi_candidate_polish(api_key: str, model: str, candidate: dict[str, Any], content_plan: dict[str, Any], timeout: float, video_seconds: int = 12) -> dict[str, Any]:
    """Generate 3 variants at different temperatures and pick the highest-scoring one."""
    temperatures = policy_get("deepseek.temperatures", [0.3, 0.5, 0.7])
    variants: list[tuple[float, dict[str, Any]]] = []
    for temp in temperatures:
        try:
            polished = deepseek_chat(api_key, model, candidate, content_plan, timeout, temperature=temp, video_seconds=video_seconds)
            score = _score_polish(polished)
            variants.append((score, polished))
        except RuntimeError:
            continue
    if not variants:
        raise RuntimeError("All multi-candidate polish attempts failed")
    variants.sort(key=lambda x: x[0], reverse=True)
    best = variants[0][1]
    best["_multi_candidate_scores"] = [v[0] for v in variants]
    best["_multi_candidate_count"] = len(variants)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    env_file = Path(args.env_file).resolve()
    api_key = env_value("DEEPSEEK_API_KEY", env_file)
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required for scripts/deepseek_polish.py")
    model = env_value("SEARCHPO_DEEPSEEK_MODEL", env_file, "deepseek-v4-pro")
    candidate_path = run_dir / "selected_candidate.json"
    plan_path = run_dir / "content_plan.json"
    if not candidate_path.exists() or not plan_path.exists():
        raise SystemExit("selected_candidate.json and content_plan.json are required before DeepSeek polish")

    candidate = read_json(candidate_path)
    content_plan = read_json(plan_path)
    duration_frames = int(env_value("SEARCHPO_DURATION_FRAMES", env_file, "360"))
    video_seconds = duration_frames // 30
    multi_candidate = env_value("SEARCHPO_POLISH_MULTI_CANDIDATE", env_file, "0") == "1"
    if multi_candidate:
        polished = _multi_candidate_polish(api_key, model, candidate, content_plan, args.timeout, video_seconds=video_seconds)
    else:
        polished = deepseek_chat(api_key, model, candidate, content_plan, args.timeout, video_seconds=video_seconds)
    rendered_text = " ".join(
        [
            str(polished.get("polished_title") or ""),
            str(polished.get("voiceover_text") or ""),
            str(polished.get("douyin_title") or ""),
            str(polished.get("douyin_desc") or ""),
            json.dumps(polished.get("cards") or [], ensure_ascii=False),
        ]
    )
    unsafe_hits = sorted(set(match.group(0) for match in UNSAFE_RE.finditer(rendered_text)))
    result = {
        "schema_version": 1,
        "created_at": utc_now(),
        "provider": "deepseek",
        "model": model,
        "selected_candidate_id": candidate.get("candidate_id"),
        "status": "pass" if not unsafe_hits else "fail",
        "polished_title": bounded_text(polished["polished_title"], 80),
        "voiceover_text": bounded_text(polished["voiceover_text"], 700),
        "douyin_title": bounded_text(polished["douyin_title"], 55),
        "douyin_desc": bounded_text(polished["douyin_desc"], 600),
        "tags": polished["tags"],
        "cards": polished["cards"],
        "caveats": polished.get("caveats") or [],
        "unsafe_claim_hits": unsafe_hits,
        "usage": polished.get("_raw_usage"),
        "input_files": [str(candidate_path), str(plan_path)],
    }
    output_path = run_dir / "deepseek_polish.json"
    write_json(output_path, result)
    print(json.dumps({"deepseek_polish": str(output_path), "status": result["status"]}, ensure_ascii=False, indent=2))
    if unsafe_hits:
        raise SystemExit(f"DeepSeek polish generated unsupported claim terms: {unsafe_hits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
