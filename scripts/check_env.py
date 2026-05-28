#!/usr/bin/env python3
"""Audit local env coverage without printing secret values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_GROUPS = {
    "data_optional": ["GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN", "HUGGINGFACE_TOKEN"],
    "agent_llm_optional": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GOOGLE_AGENT_PLATFORM_API", "XAI_API_KEY"],
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
}


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    env_path = Path(args.env_file).expanduser().resolve()
    values = load_env(env_path)
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
    result = {
        "env_file": str(env_path),
        "exists": env_path.exists(),
        "groups": groups,
        "social_auto_upload": social_auto_upload,
        "notes": [
            "Secret values are intentionally omitted.",
            "Default publishing validation targets Douyin via dreammis/social-auto-upload.",
            "Live Douyin upload is gated by SEARCHPO_DOUYIN_LIVE=1 plus DOUYIN_ACCOUNT_NAME or SOCIAL_UPLOAD_ACCOUNT_NAME.",
            "X/Twitter keys remain optional read-source inputs only; they are not the default publishing path.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    missing_lambda = groups["remotion_lambda_required"]["missing"]
    return 1 if missing_lambda else 0


if __name__ == "__main__":
    raise SystemExit(main())
