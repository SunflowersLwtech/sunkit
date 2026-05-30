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


def candidate_entity_terms(candidate: dict[str, Any]) -> list[str]:
    raw_values = [
        str(candidate.get("title") or ""),
        str(candidate.get("entity_key") or ""),
        str(candidate.get("canonical_url") or "").rstrip("/").rsplit("/", 1)[-1],
    ]
    terms: list[str] = []
    for raw in raw_values:
        for part in re.split(r"[\s/_:.-]+", raw):
            cleaned = part.strip()
            if len(cleaned) >= 4 and cleaned.lower() not in {"github", "repo", "http", "https"}:
                terms.append(cleaned)
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            unique.append(term)
    return unique[:6]


def validate_candidate_reference(candidate: dict[str, Any], polished: dict[str, Any]) -> None:
    terms = candidate_entity_terms(candidate)
    voiceover = str(polished.get("voiceover_text") or "").lower()
    if terms and not any(term.lower() in voiceover for term in terms):
        raise RuntimeError(f"DeepSeek voiceover_text must mention one of: {', '.join(terms)}")


def rendered_polish_text(polished: dict[str, Any]) -> str:
    return " ".join(
        [
            str(polished.get("polished_title") or ""),
            str(polished.get("voiceover_text") or ""),
            str(polished.get("douyin_title") or ""),
            str(polished.get("douyin_desc") or ""),
            json.dumps(polished.get("cards") or [], ensure_ascii=False),
        ]
    )


def unsafe_hits_for(polished: dict[str, Any]) -> list[str]:
    return sorted(set(match.group(0) for match in UNSAFE_RE.finditer(rendered_polish_text(polished))))


def validate_polish(candidate: dict[str, Any], polished: dict[str, Any]) -> None:
    validate_candidate_reference(candidate, polished)
    unsafe_hits = unsafe_hits_for(polished)
    if unsafe_hits:
        raise RuntimeError(f"DeepSeek candidate contains unsupported claim terms: {unsafe_hits}")


def parse_json_object(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_polish_payload(data: dict[str, Any]) -> dict[str, Any]:
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


def parse_deepseek_payload(content: str) -> dict[str, Any]:
    return normalize_polish_payload(parse_json_object(content))


def parse_deepseek_variants(content: str, expected_count: int) -> list[dict[str, Any]]:
    data = parse_json_object(content)
    variants = data.get("variants")
    if not isinstance(variants, list) or len(variants) != expected_count:
        raise RuntimeError(f"DeepSeek response must include exactly {expected_count} variants")
    clean: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        if not isinstance(variant, dict):
            raise RuntimeError(f"DeepSeek variant {index} is not an object")
        clean.append(normalize_polish_payload(variant))
    return clean


def deepseek_constraints(video_seconds: int, *, variant_count: int = 1) -> list[str]:
    chars_per_second = int(policy_get("deepseek.chars_per_second", 7))
    lo = max(60, video_seconds * chars_per_second - 30)
    hi = video_seconds * chars_per_second + 20
    voiceover_chars_range = f"{lo}-{hi} Chinese characters"
    constraints = [
        policy_format(item, voiceover_chars_range=voiceover_chars_range, video_seconds=video_seconds)
        for item in policy_get("deepseek.constraints", [])
    ]
    if variant_count > 1:
        constraints = [item for item in constraints if "Return exactly these keys" not in item]
        constraints.append(
            f"Return one JSON object with exactly one key `variants`, containing exactly {variant_count} objects."
        )
        constraints.append(
            "Each variants item must contain exactly these keys: polished_title, voiceover_text, douyin_title, douyin_desc, tags, cards, caveats."
        )
    return constraints


def request_deepseek(api_key: str, model: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    api_attempts = int(policy_get("deepseek.api_attempts", 2))
    last_exc: Exception | None = None
    for attempt in range(api_attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
            retryable = exc.code in (429, 500, 502, 503, 504) and attempt < api_attempts - 1
            if retryable:
                delay = 3.0 * (2 ** attempt)
                print(f"DeepSeek HTTP {exc.code}, retrying in {delay:.0f}s (attempt {attempt + 1}/{api_attempts})...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}")
                continue
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < api_attempts - 1:
                delay = 3.0 * (2 ** attempt)
                print(f"DeepSeek network error, retrying in {delay:.0f}s (attempt {attempt + 1}/{api_attempts})...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"DeepSeek network error: {exc}")
                continue
            raise RuntimeError(f"DeepSeek network error: {exc}") from exc
    raise last_exc or RuntimeError("DeepSeek call exhausted retries")


def response_message_content(payload: dict[str, Any]) -> str:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        finish_reason = choice.get("finish_reason")
        message_keys = sorted(str(key) for key in message.keys())
        raise RuntimeError(f"DeepSeek returned empty message content; finish_reason={finish_reason}; message_keys={message_keys}")
    return content.strip()


def deepseek_body(
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    *,
    temperature: float,
    video_seconds: int,
    variant_count: int = 1,
) -> dict[str, Any]:
    system = policy_get("deepseek.system", "Return strict JSON only.")
    user = {
        "task": (
            f"Polish {variant_count} distinct short-form video packages for Douyin and Remotion."
            if variant_count > 1
            else "Polish one short-form video package for Douyin and Remotion."
        ),
        "constraints": deepseek_constraints(video_seconds, variant_count=variant_count),
        "forbidden_claim_terms": unsupported_terms(),
        "required_entity_terms": candidate_entity_terms(candidate),
        "selected_candidate": candidate,
        "content_plan": content_plan,
    }
    if variant_count > 1:
        user["output_schema"] = {
            "variants": [
                {
                    "polished_title": "string",
                    "voiceover_text": "string",
                    "douyin_title": "string",
                    "douyin_desc": "string",
                    "tags": ["string"],
                    "cards": [{"label": "string", "value": "string", "detail": "string"}],
                    "caveats": ["string"],
                }
            ]
        }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": temperature,
        "max_tokens": int(policy_get("deepseek.max_tokens", 1800)),
    }
    thinking_type = str(policy_get("deepseek.thinking_type", "") or "").strip()
    if thinking_type:
        body["thinking"] = {"type": thinking_type}
    if variant_count == 1:
        body["response_format"] = {"type": "json_object"}
    return body


def deepseek_chat(api_key: str, model: str, candidate: dict[str, Any], content_plan: dict[str, Any], timeout: float, temperature: float = 0.4, video_seconds: int = 12) -> dict[str, Any]:
    body = deepseek_body(model, candidate, content_plan, temperature=temperature, video_seconds=video_seconds)
    payload = request_deepseek(api_key, model, body, timeout)
    content = response_message_content(payload)
    parsed = parse_deepseek_payload(content)
    try:
        validate_polish(candidate, parsed)
        parsed["_raw_usage"] = payload.get("usage")
        parsed["_correction_applied"] = False
        return parsed
    except RuntimeError as exc:
        corrected = correct_deepseek_polish(
            api_key,
            model,
            candidate,
            content_plan,
            parsed,
            str(exc),
            timeout,
            video_seconds=video_seconds,
        )
        validate_polish(candidate, corrected)
        corrected["_correction_applied"] = True
        corrected["_initial_error"] = str(exc)
        return corrected


def correct_deepseek_polish(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    rejected: dict[str, Any],
    validation_error: str,
    timeout: float,
    video_seconds: int = 12,
) -> dict[str, Any]:
    body = deepseek_body(model, candidate, content_plan, temperature=0.1, video_seconds=video_seconds)
    user = json.loads(body["messages"][1]["content"])
    user["task"] = "Correct the rejected short-form video JSON so it passes the validation error exactly."
    user["validation_error"] = validation_error
    user["rejected_json"] = rejected
    user["correction_rules"] = [
        "Return a complete replacement JSON object with the required keys only.",
        "Remove every forbidden claim term named in validation_error.",
        "Keep the selected candidate boundary and required_entity_terms reference.",
    ]
    body["messages"][1]["content"] = json.dumps(user, ensure_ascii=False)
    payload = request_deepseek(api_key, model, body, timeout)
    content = response_message_content(payload)
    corrected = parse_deepseek_payload(content)
    corrected["_raw_usage"] = payload.get("usage")
    return corrected


def deepseek_variant_chat(api_key: str, model: str, candidate: dict[str, Any], content_plan: dict[str, Any], timeout: float, video_seconds: int = 12) -> list[dict[str, Any]]:
    variant_count = int(policy_get("deepseek.variant_count", 3))
    body = deepseek_body(
        model,
        candidate,
        content_plan,
        temperature=float(policy_get("deepseek.variant_temperature", 0.5)),
        video_seconds=video_seconds,
        variant_count=variant_count,
    )
    payload = request_deepseek(api_key, model, body, timeout)
    content = response_message_content(payload)
    parsed_variants = parse_deepseek_variants(content, variant_count)
    valid: list[dict[str, Any]] = []
    rejected: list[str] = []
    for index, parsed in enumerate(parsed_variants, start=1):
        try:
            validate_polish(candidate, parsed)
        except RuntimeError as exc:
            rejected.append(f"variant {index}: {exc}")
            continue
        parsed["_raw_usage"] = payload.get("usage")
        valid.append(parsed)
    if not valid:
        raise RuntimeError("DeepSeek returned no valid variants: " + "; ".join(rejected))
    return valid


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
    """Ask the provider for multiple variants in one structured response and pick the highest-scoring valid one."""
    polished_variants = deepseek_variant_chat(api_key, model, candidate, content_plan, timeout, video_seconds=video_seconds)
    variants: list[tuple[float, dict[str, Any]]] = [(_score_polish(polished), polished) for polished in polished_variants]
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
    unsafe_hits = unsafe_hits_for(polished)
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
        "correction_applied": bool(polished.get("_correction_applied")),
        "initial_error": polished.get("_initial_error"),
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
