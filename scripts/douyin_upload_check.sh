#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_DIR="${1:-$(cat runtime/latest_run.txt)}"
ENV_FILE="${SEARCHPO_ENV_FILE:-.env}"
CHECK_JSON="$RUN_DIR/post/douyin_upload_check.json"
LIVE="${SEARCHPO_DOUYIN_LIVE:-0}"

env_value() {
  local key="$1"
  python3 - "$ENV_FILE" "$key" <<'PY'
import os
import sys
from pathlib import Path

env_file = Path(sys.argv[1])
key = sys.argv[2]
value = os.environ.get(key, "")
if not value and env_file.exists():
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        env_key, env_value = line.split("=", 1)
        if env_key.strip() == key:
            value = env_value.strip().strip('"').strip("'")
            break
print(value)
PY
}

SOCIAL_ROOT="$(env_value SOCIAL_AUTO_UPLOAD_ROOT)"
if [[ -z "$SOCIAL_ROOT" ]]; then
  SOCIAL_ROOT="$ROOT/runtime/social-auto-upload"
fi
case "$SOCIAL_ROOT" in
  /*) ;;
  *) SOCIAL_ROOT="$ROOT/$SOCIAL_ROOT" ;;
esac

ACCOUNT_NAME="$(env_value DOUYIN_ACCOUNT_NAME)"
if [[ -z "$ACCOUNT_NAME" ]]; then
  ACCOUNT_NAME="$(env_value SOCIAL_UPLOAD_ACCOUNT_NAME)"
fi
RENDERED_VIDEO="$(env_value SEARCHPO_RENDERED_VIDEO)"
SOCIAL_UPLOAD_HEADED="$(env_value SOCIAL_UPLOAD_HEADED)"
if [[ -z "$SOCIAL_UPLOAD_HEADED" && "$LIVE" == "1" ]]; then
  SOCIAL_UPLOAD_HEADED="1"
fi

SOCIAL_PYTHON="$(env_value SOCIAL_AUTO_UPLOAD_PYTHON)"
if [[ -z "$SOCIAL_PYTHON" && -x "$SOCIAL_ROOT/.venv/bin/python" ]]; then
  SOCIAL_PYTHON="$SOCIAL_ROOT/.venv/bin/python"
fi
if [[ -z "$SOCIAL_PYTHON" ]]; then
  SOCIAL_PYTHON="python3"
fi
case "$SOCIAL_PYTHON" in
  /*|python3|python|uv) ;;
  *) SOCIAL_PYTHON="$ROOT/$SOCIAL_PYTHON" ;;
esac

SOCIAL_CLI="$(env_value SOCIAL_AUTO_UPLOAD_CLI)"
if [[ -z "$SOCIAL_CLI" && -x "$SOCIAL_ROOT/.venv/bin/sau" ]]; then
  SOCIAL_CLI="$SOCIAL_ROOT/.venv/bin/sau"
fi
case "$SOCIAL_CLI" in
  ""|/*|sau) ;;
  *) SOCIAL_CLI="$ROOT/$SOCIAL_CLI" ;;
esac

mkdir -p "$RUN_DIR/post"

python3 - "$ROOT" "$RUN_DIR" "$SOCIAL_ROOT" "$SOCIAL_PYTHON" "$SOCIAL_CLI" "$ACCOUNT_NAME" "$RENDERED_VIDEO" "$SOCIAL_UPLOAD_HEADED" "$LIVE" "$CHECK_JSON" <<'PY'
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


root = Path(sys.argv[1])
run_dir = Path(sys.argv[2]).resolve()
social_root = Path(sys.argv[3]).expanduser()
social_python = sys.argv[4]
social_cli = sys.argv[5]
account_name = sys.argv[6]
rendered_video = sys.argv[7]
upload_headed = sys.argv[8] == "1"
live = sys.argv[9] == "1"
check_json = Path(sys.argv[10])

post_dir = run_dir / "post"
manifest_path = post_dir / "douyin_upload_manifest.json"
if rendered_video:
    configured_video_path = Path(rendered_video).expanduser()
    video_path = configured_video_path if configured_video_path.is_absolute() else root / configured_video_path
else:
    lambda_video_path = root / "out" / "searchpo-radar-lambda.mp4"
    local_video_path = root / "out" / "searchpo-radar.mp4"
    video_path = lambda_video_path if lambda_video_path.is_file() else local_video_path
contract_path = social_root / "skills" / "douyin-upload" / "references" / "cli-contract.md"
cli_path = social_root / "sau_cli.py"
pyproject_path = social_root / "pyproject.toml"
cli_entrypoint_path = Path(social_cli) if social_cli and social_cli != "sau" else None

def upload_args(manifest: dict[str, Any]) -> list[str]:
    args = [
        "douyin",
        "upload-video",
        "--account",
        account_name or "<DOUYIN_ACCOUNT_NAME>",
        "--file",
        str(video_path),
        "--title",
        manifest["title"],
        "--desc",
        manifest["desc"],
        "--tags",
        ",".join(manifest["tags"]),
    ]
    if upload_headed:
        args.append("--headed")
    return args


def sau_command(args: list[str]) -> list[str]:
    if social_cli:
        return [social_cli, *args]
    return [social_python, "sau_cli.py", *args]


def run_sau(args: list[str]) -> dict[str, Any]:
    command = sau_command(args)
    proc = subprocess.run(
        command,
        cwd=social_root,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    return {
        "command": " ".join(shlex.quote(part) for part in command),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-1200:],
        "stderr": proc.stderr[-1200:],
    }


errors: list[str] = []
warnings: list[str] = []
manifest: dict[str, Any] = {}

required_files = {
    "social_root": social_root.exists(),
    "sau_cli": cli_path.is_file(),
    "sau_entrypoint": not social_cli or social_cli == "sau" or (cli_entrypoint_path is not None and cli_entrypoint_path.is_file()),
    "pyproject": pyproject_path.is_file(),
    "douyin_contract": contract_path.is_file(),
    "douyin_manifest": manifest_path.is_file(),
    "rendered_video": video_path.is_file(),
}
for name, ok in required_files.items():
    if not ok:
        errors.append(f"Missing required file: {name}")

if manifest_path.is_file():
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("title", "desc", "tags"):
        if not manifest.get(key):
            errors.append(f"douyin_upload_manifest.json missing `{key}`")

cli_help: dict[str, Any] | None = None
if cli_path.is_file():
    cli_help = run_sau(["douyin", "--help"])
    if cli_help["returncode"] != 0:
        warnings.append(
            "social-auto-upload CLI is present but not importable/runnable. "
            "Run `cd runtime/social-auto-upload && uv venv && uv pip install -e .`."
        )

account_check: dict[str, Any] = {"status": "skipped", "reason": "DOUYIN_ACCOUNT_NAME/SOCIAL_UPLOAD_ACCOUNT_NAME not set"}
if account_name:
    result = run_sau(["douyin", "check", "--account", account_name])
    account_check = {"status": "valid" if result["returncode"] == 0 else "invalid", **result}
    if result["returncode"] != 0:
        if live:
            errors.append("Douyin account check failed; refusing live upload.")
        else:
            warnings.append("Douyin account check failed; live upload would be blocked.")

upload_result: dict[str, Any] = {
    "status": "not-run",
    "reason": "SEARCHPO_DOUYIN_LIVE is not 1",
}
if live:
    if not account_name:
        errors.append("Live Douyin upload requires DOUYIN_ACCOUNT_NAME or SOCIAL_UPLOAD_ACCOUNT_NAME.")
    elif manifest and video_path.is_file():
        upload_result = run_sau(upload_args(manifest))
        upload_result["status"] = "submitted" if upload_result["returncode"] == 0 else "failed"
        if upload_result["returncode"] != 0:
            errors.append("Douyin upload-video command failed.")

command = sau_command(upload_args(manifest)) if manifest else []
result = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "platform": "douyin",
    "adapter": "dreammis/social-auto-upload",
    "run_dir": str(run_dir),
    "rendered_video_path": str(video_path),
    "social_auto_upload_root": str(social_root),
    "social_auto_upload_python": social_python,
    "social_auto_upload_cli": social_cli,
    "social_upload_headed": upload_headed,
    "required_files": required_files,
    "cli_help": cli_help,
    "account_check": account_check,
    "live_upload": upload_result,
    "live_upload_enabled": live,
    "upload_command_preview": " ".join(shlex.quote(part) for part in command) if command else "",
    "warnings": warnings,
    "errors": errors,
}
check_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(json.dumps({"douyin_upload_check": str(check_json), "warnings": warnings, "errors": errors}, ensure_ascii=False, indent=2))
raise SystemExit(1 if errors else 0)
PY
