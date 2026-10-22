#!/usr/bin/env python3
"""Audit local env coverage without printing secret values."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_harness.side_effect_tiers import resolve_side_effect_tier  # noqa: E402
from scripts.provider_modes import DOUYIN_UPLOADERS, TTS_PROVIDERS, VISUAL_AUDIT_MODES  # noqa: E402


REQUIRED_GROUPS = {
    "data_optional": ["GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN", "HUGGINGFACE_TOKEN"],
    "research_optional": ["ANYSEARCH_API_KEY"],
    "research_required": ["ANYSEARCH_API_KEY"],
    "agent_llm_optional": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"],
    "script_agents_required": ["DEEPSEEK_API_KEY", "GOOGLE_AGENT_PLATFORM_API", "GOOGLE_API_KEY"],
    "remotion_lambda_required": [
        "REMOTION_AWS_ACCESS_KEY_ID",
        "REMOTION_AWS_SECRET_ACCESS_KEY",
        "REMOTION_AWS_REGION",
        "REMOTION_LAMBDA_REGION",
        "REMOTION_LAMBDA_FUNCTION_NAME",
        "REMOTION_LAMBDA_BUCKET_NAME",
    ],
    "douyin_upload_optional": [
        "SOCIAL_AUTO_UPLOAD_ROOT",
        "SOCIAL_AUTO_UPLOAD_CLI",
        "SOCIAL_AUTO_UPLOAD_PYTHON",
        "DOUYIN_ACCOUNT_NAME",
        "SOCIAL_UPLOAD_ACCOUNT_NAME",
    ],
    "x_app_read_optional": ["X_BEARER_TOKEN", "TWITTERAPI_IO_API_KEY", "XAI_API_KEY"],
    "llm_gateway_optional": ["SEARCHPO_LLM_URL", "SEARCHPO_LLM_API_KEY", "SEARCHPO_LLM_MODEL", "SEARCHPO_LLM_SCORER_MODEL"],
    "cartesia_tts_optional": ["CARTESIA_API_KEY", "SEARCHPO_CARTESIA_VOICE"],
    "douyin_ego_optional": ["SEARCHPO_EGO_PUBLISHER"],
}


def provider_switches(values: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Resolve the provider switches; each defaults to the original provider."""
    switches = {
        "llm": "gateway" if values.get("SEARCHPO_LLM_URL") else "native",
        "tts_provider": (values.get("SEARCHPO_TTS_PROVIDER") or TTS_PROVIDERS[0]).lower(),
        "visual_audit": (values.get("SEARCHPO_VISUAL_AUDIT") or VISUAL_AUDIT_MODES[0]).lower(),
        "douyin_uploader": (values.get("SEARCHPO_DOUYIN_UPLOADER") or DOUYIN_UPLOADERS[0]).lower(),
    }
    invalid = []
    for key, name, choices in [
        ("tts_provider", "SEARCHPO_TTS_PROVIDER", TTS_PROVIDERS),
        ("visual_audit", "SEARCHPO_VISUAL_AUDIT", VISUAL_AUDIT_MODES),
        ("douyin_uploader", "SEARCHPO_DOUYIN_UPLOADER", DOUYIN_UPLOADERS),
    ]:
        if switches[key] not in choices:
            invalid.append(f"{name} must be one of {', '.join(choices)}")
    return switches, invalid


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def effective_values(path: Path) -> dict[str, str]:
    values = load_env(path)
    for key in set(values) | set(os.environ):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--profile",
        default=os.environ.get("SEARCHPO_E2E_PROFILE", "contract"),
        choices=["contract", "provider", "lambda", "live"],
        help="Command tier to validate.",
    )
    args = parser.parse_args()
    side_effect_tier = resolve_side_effect_tier(args.profile)

    env_path = Path(args.env_file).expanduser().resolve()
    values = effective_values(env_path)
    repo_root = env_path.parent
    social_root = Path(values.get("SOCIAL_AUTO_UPLOAD_ROOT") or repo_root / "runtime" / "social-auto-upload").expanduser()
    if not social_root.is_absolute():
        social_root = repo_root / social_root
    social_cli = Path(values.get("SOCIAL_AUTO_UPLOAD_CLI") or social_root / ".venv" / "bin" / "sau").expanduser()
    if not social_cli.is_absolute():
        social_cli = repo_root / social_cli
    groups = {}
    for group, keys in REQUIRED_GROUPS.items():
        groups[group] = {
            "keys": keys,
            "set": [key for key in keys if values.get(key)],
            "missing": [key for key in keys if not values.get(key)],
        }
    google_key_set = bool(values.get("GOOGLE_AGENT_PLATFORM_API") or values.get("GOOGLE_API_KEY"))
    switches, invalid_switches = provider_switches(values)
    script_required_missing = list(invalid_switches)
    if switches["llm"] == "gateway":
        script_required_missing.extend(key for key in ["SEARCHPO_LLM_API_KEY", "SEARCHPO_LLM_MODEL"] if not values.get(key))
    elif not values.get("DEEPSEEK_API_KEY"):
        script_required_missing.append("DEEPSEEK_API_KEY")
    # Gemini is needed for scoring without a gateway, Gemini TTS, and the Gemini visual audit.
    gemini_needed = switches["llm"] != "gateway" or switches["tts_provider"] == "gemini" or switches["visual_audit"] == "gemini"
    if gemini_needed and not google_key_set:
        script_required_missing.append("GOOGLE_AGENT_PLATFORM_API or GOOGLE_API_KEY")
    if switches["tts_provider"] == "cartesia":
        script_required_missing.extend(key for key in ["CARTESIA_API_KEY", "SEARCHPO_CARTESIA_VOICE"] if not values.get(key))
    groups["script_agents_required"]["missing_effective"] = script_required_missing
    research_required_missing = groups["research_required"]["missing"]
    social_auto_upload = {
        "root": str(social_root),
        "exists": social_root.exists(),
        "cli": str(social_root / "sau_cli.py"),
        "cli_exists": (social_root / "sau_cli.py").is_file(),
        "cli_entrypoint": str(social_cli),
        "cli_entrypoint_exists": social_cli.is_file(),
        "douyin_contract": str(social_root / "skills" / "douyin-upload" / "references" / "cli-contract.md"),
        "douyin_contract_exists": (social_root / "skills" / "douyin-upload" / "references" / "cli-contract.md").is_file(),
        "account_name_set": bool(values.get("DOUYIN_ACCOUNT_NAME") or values.get("SOCIAL_UPLOAD_ACCOUNT_NAME")),
    }
    ego_publisher = values.get("SEARCHPO_EGO_PUBLISHER") or ""
    ego = {
        "selected": switches["douyin_uploader"] == "ego",
        "publisher_set": bool(ego_publisher),
        "publisher_exists": bool(ego_publisher) and Path(ego_publisher).expanduser().is_file(),
        "visibility": values.get("SEARCHPO_DOUYIN_VISIBILITY") or "self_only",
    }
    result = {
        "env_file": str(env_path),
        "exists": env_path.exists(),
        "profile": args.profile,
        "side_effect_tier": side_effect_tier.to_dict(),
        "groups": groups,
        "provider_switches": switches,
        "social_auto_upload": social_auto_upload,
        "douyin_ego_publisher": ego,
        "publish_safety": {
            "searchpo_douyin_live": values.get("SEARCHPO_DOUYIN_LIVE") or "0",
            "douyin_check_level": values.get("SEARCHPO_DOUYIN_CHECK_LEVEL") or "adapter",
        },
        "notes": [
            "Secret values are intentionally omitted.",
            "Default contract E2E does not require provider, AWS, or Douyin account secrets.",
            "Adapter publishing validation targets Douyin via dreammis/social-auto-upload.",
            "Provider video runs require AnySearch enrichment because research_barrier/cross_check requires independent supplemental sources.",
            "DeepSeek polish, Gemini TTS, and Gemini visual audit are real script adapters; missing provider keys fail E2E.",
            "SEARCHPO_LLM_URL, SEARCHPO_TTS_PROVIDER, SEARCHPO_VISUAL_AUDIT, and SEARCHPO_DOUYIN_UPLOADER switch providers; unset keeps the defaults.",
            "Live Douyin upload is gated by SEARCHPO_DOUYIN_LIVE=1 plus DOUYIN_ACCOUNT_NAME or SOCIAL_UPLOAD_ACCOUNT_NAME.",
            "X/Twitter keys remain optional read-source inputs only; they are not the default publishing path.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if values.get("SEARCHPO_DOUYIN_LIVE") == "1" and args.profile != "live":
        return 1
    if args.profile == "contract":
        return 0
    if args.profile == "provider":
        return 1 if script_required_missing or research_required_missing else 0
    if args.profile == "lambda":
        missing_lambda = groups["remotion_lambda_required"]["missing"]
        return 1 if missing_lambda or script_required_missing or research_required_missing else 0
    if args.profile == "live":
        missing_lambda = groups["remotion_lambda_required"]["missing"]
        if ego["selected"]:
            missing_account = not ego["publisher_exists"]
        else:
            missing_account = not social_auto_upload["account_name_set"]
        return 1 if missing_lambda or script_required_missing or research_required_missing or missing_account else 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
