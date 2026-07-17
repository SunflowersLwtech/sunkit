from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "searchpo_policy.json"


@lru_cache(maxsize=4)
def load_policy(path: str | None = None) -> dict[str, Any]:
    policy_path = Path(path).resolve() if path else POLICY_PATH
    return json.loads(policy_path.read_text(encoding="utf-8"))


def policy_get(path: str, default: Any = None) -> Any:
    value: Any = load_policy()
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def policy_format(template: str, **values: Any) -> str:
    class SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return ""

    return template.format_map(SafeDict({key: "" if value is None else value for key, value in values.items()}))


def compile_policy_regex(path: str, flags: int = re.I) -> re.Pattern[str]:
    pattern = policy_get(path)
    if not pattern:
        raise KeyError(f"missing regex policy: {path}")
    return re.compile(str(pattern), flags)


def unsupported_terms() -> list[str]:
    return list(policy_get("claims.unsupported_terms", []))


def unsupported_claim_regex(flags: int = re.I) -> re.Pattern[str]:
    terms = unsupported_terms()
    english: list[str] = []
    other: list[str] = []
    for term in terms:
        if re.fullmatch(r"[A-Za-z0-9?.*+|()\\-]+", term):
            english.append(term)
        else:
            other.append(re.escape(term))
    parts = []
    if english:
        parts.append(r"\b(" + "|".join(english) + r")\b")
    if other:
        parts.append("|".join(other))
    return re.compile("|".join(parts) or r"$^", flags)


def content_profile(candidate: dict[str, Any]) -> dict[str, Any]:
    input_mode = candidate.get("input_mode")
    selection_source = candidate.get("selection_source")
    profile_name = "operator_topic" if input_mode == "operator_topic" or selection_source == "operator_topic" else "daily_radar"
    profile = policy_get(f"content.profiles.{profile_name}", {})
    return dict(profile) if isinstance(profile, dict) else {}


def operator_topic_policy() -> dict[str, Any]:
    policy = policy_get("subject_inputs.operator_topic", {})
    return dict(policy) if isinstance(policy, dict) else {}
