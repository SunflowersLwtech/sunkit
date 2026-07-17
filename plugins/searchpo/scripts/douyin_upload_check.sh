#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_DIR="${1:-$(cat runtime/latest_run.txt)}"
ENV_FILE="${SEARCHPO_ENV_FILE:-.env}"
CHECK_JSON="$RUN_DIR/post/douyin_upload_check.json"
LIVE="${SEARCHPO_DOUYIN_LIVE:-0}"
CHECK_LEVEL="${SEARCHPO_DOUYIN_CHECK_LEVEL:-adapter}"

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
RENDERED_COVER="$(env_value SEARCHPO_RENDERED_COVER)"
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

if [[ "$LIVE" == "1" && "$CHECK_LEVEL" != "adapter" ]]; then
  echo "Live Douyin upload requires SEARCHPO_DOUYIN_CHECK_LEVEL=adapter" >&2
  exit 2
fi

python3 - "$ROOT" "$RUN_DIR" "$SOCIAL_ROOT" "$SOCIAL_PYTHON" "$SOCIAL_CLI" "$ACCOUNT_NAME" "$RENDERED_VIDEO" "$RENDERED_COVER" "$SOCIAL_UPLOAD_HEADED" "$LIVE" "$CHECK_JSON" "$CHECK_LEVEL" <<'PY'
from __future__ import annotations

import json
import hashlib
import html as html_lib
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


root = Path(sys.argv[1])
run_dir = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(root))
from agent_harness.artifact_identity import validate_upload_identity  # noqa: E402
from scripts.cover_health import analyze_cover  # noqa: E402

social_root = Path(sys.argv[3]).expanduser()
social_python = sys.argv[4]
social_cli = sys.argv[5]
account_name = sys.argv[6]
rendered_video = sys.argv[7]
rendered_cover = sys.argv[8]
upload_headed = sys.argv[9] == "1"
live = sys.argv[10] == "1"
check_json = Path(sys.argv[11])
check_level = sys.argv[12]

post_dir = run_dir / "post"
manifest_path = post_dir / "douyin_upload_manifest.json"
if not rendered_video:
    raise SystemExit("SEARCHPO_RENDERED_VIDEO is required")
configured_video_path = Path(rendered_video).expanduser()
video_path = configured_video_path if configured_video_path.is_absolute() else root / configured_video_path
configured_cover_path = Path(rendered_cover).expanduser() if rendered_cover else None
cover_path = configured_cover_path if configured_cover_path and configured_cover_path.is_absolute() else (root / configured_cover_path if configured_cover_path else None)
contract_path = social_root / "skills" / "douyin-upload" / "references" / "cli-contract.md"
cli_path = social_root / "sau_cli.py"
pyproject_path = social_root / "pyproject.toml"
cli_entrypoint_path = Path(social_cli) if social_cli and social_cli != "sau" else None
command_timeout = int(os.environ.get("SEARCHPO_SOCIAL_UPLOAD_TIMEOUT") or (600 if live else 120))

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
    if cover_path and cover_path.is_file():
        args.extend(["--thumbnail", str(cover_path)])
    if upload_headed:
        args.append("--headed")
    return args


def sau_command(args: list[str]) -> list[str]:
    if social_cli:
        return [social_cli, *args]
    return [social_python, "sau_cli.py", *args]


def sau_cwd() -> Path:
    # The installed `sau` entrypoint must not run from the source checkout:
    # that makes Python import runtime/social-auto-upload/conf.py and use a
    # different cookie home from the installed CLI package.
    return root if social_cli else social_root


def run_sau(args: list[str]) -> dict[str, Any]:
    command = sau_command(args)
    cwd = sau_cwd()
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=command_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "command": " ".join(shlex.quote(part) for part in command),
            "cwd": str(cwd),
            "returncode": -1,
            "timed_out": True,
            "timeout_sec": command_timeout,
            "stdout": ((exc.stdout or "") if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace"))[-1200:],
            "stderr": ((exc.stderr or "") if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace"))[-1200:],
        }
    return {
        "command": " ".join(shlex.quote(part) for part in command),
        "cwd": str(cwd),
        "returncode": proc.returncode,
        "timed_out": False,
        "timeout_sec": command_timeout,
        "stdout": proc.stdout[-1200:],
        "stderr": proc.stderr[-1200:],
    }


def run_sau_until_success(args: list[str], attempts: int = 1, delay_sec: float = 3.0) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for attempt in range(1, max(1, attempts) + 1):
        result = run_sau(args)
        result["attempt"] = attempt
        results.append(result)
        if result["returncode"] == 0:
            result = dict(result)
            if len(results) > 1:
                result["attempts"] = [dict(item) for item in results]
            return result
        if attempt < attempts:
            time.sleep(delay_sec)
    final = dict(results[-1])
    if len(results) > 1:
        final["attempts"] = [dict(item) for item in results]
    return final


def _parse_json_payload(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    for match in re.finditer(r"\{.*?\}", text, re.S):
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def remote_identity_from_upload(upload_result: dict[str, Any]) -> dict[str, Any]:
    combined = f"{upload_result.get('stdout') or ''}\n{upload_result.get('stderr') or ''}"
    parsed = _parse_json_payload(combined)
    remote_id = (
        str(parsed.get("remote_post_id") or parsed.get("post_id") or parsed.get("item_id") or parsed.get("aweme_id") or "").strip()
    )
    permalink = str(parsed.get("permalink") or parsed.get("url") or "").strip()
    if not permalink:
        url_match = re.search(r"https?://[^\s\"']+", combined)
        permalink = url_match.group(0) if url_match else ""
    if not remote_id:
        id_match = re.search(r"(?:post_id|item_id|aweme_id|remote_id)[:=]\s*([A-Za-z0-9_-]{6,})", combined)
        remote_id = id_match.group(1) if id_match else ""
    return {
        "remote_post_id": remote_id,
        "permalink": permalink,
        "title": str(parsed.get("title") or "").strip(),
        "duration_sec": str(parsed.get("duration_sec") or parsed.get("duration") or "").strip(),
        "cover_evidence": str(parsed.get("cover") or parsed.get("thumbnail") or "").strip(),
        "account": account_name,
        "status": str(parsed.get("status") or "").strip(),
        "raw_detection_source": "adapter_output_only",
    }


def creator_manage_remote_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    """Verify a submitted upload against Douyin Creator Center's manage page."""
    title = str(manifest.get("title") or "").strip()
    desc = str(manifest.get("desc") or "").strip()
    tags = [str(tag).strip().lstrip("#") for tag in manifest.get("tags") or [] if str(tag).strip()]
    if not title and not desc:
        return {"status": "", "raw_detection_source": "creator_manage_page", "error": "manifest title/desc missing"}

    verifier = r'''
import asyncio
import json
import re
import sys
import html as html_lib
from pathlib import Path

from patchright.async_api import async_playwright
from sau_cli import resolve_account_file

account_name = sys.argv[1]
expected_title = sys.argv[2]
expected_desc = sys.argv[3]
expected_tags = json.loads(sys.argv[4])
state = resolve_account_file("douyin", account_name)

def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

async def main():
    if not Path(state).exists():
        print(json.dumps({"error": f"account storage state missing: {state}"}, ensure_ascii=False))
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        context = await browser.new_context(storage_state=str(state), viewport={"width": 1440, "height": 1000})
        page = await context.new_page()
        await page.goto("https://creator.douyin.com/creator-micro/content/manage", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(int(__import__("os").environ.get("SEARCHPO_DOUYIN_VERIFY_WAIT_MS", "8000")))
        body_text = await page.locator("body").inner_text(timeout=15000)
        body_compact = norm(body_text)
        title_prefix = expected_title[: max(10, min(18, len(expected_title)))]
        desc_prefix = expected_desc[: max(10, min(24, len(expected_desc)))]
        lines = [norm(line) for line in body_text.splitlines() if norm(line)]
        row_text = ""
        for index, line in enumerate(lines):
            if (title_prefix and title_prefix in line) or (desc_prefix and desc_prefix in line):
                row_text = norm(" ".join(lines[index : index + 12]))
                break
        if not row_text and (title_prefix in body_compact or desc_prefix in body_compact):
            anchor = body_compact.find(title_prefix) if title_prefix in body_compact else body_compact.find(desc_prefix)
            row_text = body_compact[max(0, anchor - 120) : anchor + 800]

        page_html = await page.content()
        cover_evidence = ""
        html_anchor = page_html.find(title_prefix) if title_prefix else -1
        if html_anchor < 0 and desc_prefix:
            html_anchor = page_html.find(desc_prefix)
        if html_anchor >= 0:
            window = page_html[max(0, html_anchor - 4000) : html_anchor + 3000]
            match = re.search(r"background-image:\s*url\(&quot;([^&]+(?:&amp;[^&]+)*)&quot;\)", window)
            if match:
                cover_evidence = html_lib.unescape(match.group(1))

        duration_match = None
        if html_anchor >= 0:
            badge_match = re.search(r'<span class="badge[^"]*">(\d{1,2}):(\d{2})</span>', window)
            if badge_match:
                duration_match = badge_match
        if duration_match is None:
            for candidate in re.finditer(r"\b(\d{1,2}):(\d{2})\b", row_text):
                if int(candidate.group(1)) <= 2:
                    duration_match = candidate
                    break
        duration_sec = ""
        if duration_match:
            duration_sec = str(int(duration_match.group(1)) * 60 + int(duration_match.group(2)))

        status = ""
        for candidate_status in ("已发布", "审核中", "未通过"):
            if candidate_status in row_text:
                status = candidate_status
                break
        tag_hits = [tag for tag in expected_tags if f"#{tag}" in row_text or tag in row_text]
        print(json.dumps({
            "creator_manage_url": page.url,
            "title": row_text,
            "duration_sec": duration_sec,
            "cover_evidence": cover_evidence,
            "account": account_name,
            "status": status,
            "raw_detection_source": "creator_manage_page",
            "row_text": row_text,
            "title_prefix_match": bool(title_prefix and title_prefix in row_text),
            "desc_prefix_match": bool(desc_prefix and desc_prefix in row_text),
            "tag_hits": tag_hits,
        }, ensure_ascii=False))
        await browser.close()

asyncio.run(main())
'''
    try:
        proc = subprocess.run(
            [social_python, "-", account_name, title, desc, json.dumps(tags, ensure_ascii=False)],
            input=verifier,
            text=True,
            capture_output=True,
            timeout=int(os.environ.get("SEARCHPO_DOUYIN_VERIFY_TIMEOUT", "90")),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "", "raw_detection_source": "creator_manage_page", "error": str(exc)}

    if proc.returncode != 0:
        return {
            "status": "",
            "raw_detection_source": "creator_manage_page",
            "error": (proc.stderr or proc.stdout or "").strip()[-800:],
        }
    parsed = _parse_json_payload(proc.stdout)
    if not parsed:
        return {"status": "", "raw_detection_source": "creator_manage_page", "error": "creator verifier returned no JSON"}
    row_text = str(parsed.get("row_text") or "")
    parsed["remote_row_hash"] = hashlib.sha256(row_text.encode("utf-8")).hexdigest() if row_text else ""
    return parsed


def build_post_publish_verification(manifest: dict[str, Any], upload_result: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    remote = remote_identity_from_upload(upload_result)
    if upload_result.get("returncode") == 0 and not (
        remote.get("remote_post_id") and remote.get("status") and remote.get("duration_sec") and remote.get("cover_evidence")
    ):
        creator_remote = creator_manage_remote_identity(manifest)
        if creator_remote.get("raw_detection_source") == "creator_manage_page" and not creator_remote.get("error"):
            remote = {
                **remote,
                **{key: value for key, value in creator_remote.items() if value not in ("", None, [])},
            }
    acceptable_statuses = {"published", "verified-published", "已发布", "审核中"}
    row_text = str(remote.get("row_text") or remote.get("title") or "")
    expected_title = str(manifest.get("title") or "")
    expected_desc = str(manifest.get("desc") or "")
    title_prefix = expected_title[: max(10, min(18, len(expected_title)))] if expected_title else ""
    desc_prefix = expected_desc[: max(10, min(24, len(expected_desc)))] if expected_desc else ""
    title_match = bool(remote["title"]) and (
        remote["title"] == expected_title
        or (bool(title_prefix) and title_prefix in row_text and (not desc_prefix or desc_prefix in row_text))
    )
    checks = {
        "remote_identity_present": bool(remote.get("remote_post_id") or remote.get("permalink") or remote.get("remote_row_hash")),
        "remote_identity_not_adapter_only": remote.get("raw_detection_source") != "adapter_output_only",
        "remote_status_acceptable": remote["status"] in acceptable_statuses,
        "title_match": title_match,
        "remote_duration_present": bool(remote["duration_sec"]),
        "remote_cover_evidence_present": bool(remote["cover_evidence"]),
        "local_hash_bound": bool(manifest.get("expected_video_sha256") and manifest.get("cover_sha256")),
        "submitted_not_final": upload_result.get("status") == "submitted",
    }
    verification_errors = [name for name, ok in checks.items() if name != "submitted_not_final" and not ok]
    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "pass" if not verification_errors else "fail",
        "platform": "douyin",
        "verification_method": "remote_identity_required_after_adapter_submit",
        "remote": remote,
        "local": {
            "run_id": manifest.get("run_id"),
            "selected_candidate_id": manifest.get("selected_candidate_id"),
            "video_sha256": manifest.get("expected_video_sha256"),
            "cover_sha256": manifest.get("cover_sha256"),
            "title": manifest.get("title"),
            "duration_evidence": manifest.get("expected_video_path"),
        },
        "checks": checks,
        "errors": verification_errors,
    }
    return payload, verification_errors


errors: list[str] = []
warnings: list[str] = []
manifest: dict[str, Any] = {}

required_files = {
    "douyin_manifest": manifest_path.is_file(),
    "rendered_video": video_path.is_file(),
}
if check_level == "adapter":
    required_files.update(
        {
            "social_root": social_root.exists(),
            "sau_cli": cli_path.is_file(),
            "sau_entrypoint": not social_cli or social_cli == "sau" or (cli_entrypoint_path is not None and cli_entrypoint_path.is_file()),
            "pyproject": pyproject_path.is_file(),
            "douyin_contract": contract_path.is_file(),
        }
    )
elif check_level == "manifest":
    errors.append("SEARCHPO_DOUYIN_CHECK_LEVEL=manifest is not a release gate; use adapter")
else:
    errors.append(f"Unsupported SEARCHPO_DOUYIN_CHECK_LEVEL: {check_level}")
for name, ok in required_files.items():
    if not ok:
        errors.append(f"Missing required file: {name}")

if manifest_path.is_file():
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("title", "desc", "tags"):
        if not manifest.get(key):
            errors.append(f"douyin_upload_manifest.json missing `{key}`")

identity_errors, identity_checks = validate_upload_identity(
    run_dir,
    video_path=video_path,
    cover_path=cover_path,
    live=live,
)
errors.extend(identity_errors)

if not rendered_cover:
    errors.append("SEARCHPO_RENDERED_COVER is required")
cover_path_value = rendered_cover
cover_present = bool(cover_path and cover_path.is_file())
if not cover_present:
    errors.append(f"Douyin cover image missing: {cover_path_value}")
cover_health = analyze_cover(cover_path) if cover_path else {"status": "fail", "errors": ["cover path missing"]}
if cover_health.get("status") != "pass":
    errors.append("Douyin cover image failed pixel health check: " + ", ".join(cover_health.get("errors") or []))

cli_help: dict[str, Any] | None = None
if check_level == "adapter" and cli_path.is_file():
    cli_help = run_sau(["douyin", "--help"])
    if cli_help["returncode"] != 0:
        warnings.append(
            "social-auto-upload CLI is present but not importable/runnable. "
            "Run `cd runtime/social-auto-upload && uv venv && uv pip install -e .`."
        )

account_check: dict[str, Any] = {"status": "not-required", "reason": "DOUYIN_ACCOUNT_NAME/SOCIAL_UPLOAD_ACCOUNT_NAME not set"}
if check_level != "adapter":
    account_check = {"status": "not-required", "reason": f"SEARCHPO_DOUYIN_CHECK_LEVEL={check_level}"}
elif account_name:
    check_attempts = int(os.environ.get("SEARCHPO_DOUYIN_ACCOUNT_CHECK_ATTEMPTS") or (3 if live else 1))
    result = run_sau_until_success(["douyin", "check", "--account", account_name], attempts=check_attempts)
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
post_publish_verification: dict[str, Any] = {
    "status": "not-required",
    "reason": "contract-check mode does not perform live publish verification",
}
if live:
    if not account_name:
        errors.append("Live Douyin upload requires DOUYIN_ACCOUNT_NAME or SOCIAL_UPLOAD_ACCOUNT_NAME.")
    elif errors:
        upload_result = {"status": "not-run", "reason": "pre-flight errors blocked live upload"}
    elif os.environ.get("SEARCHPO_DOUYIN_REVERIFY_ONLY") == "1":
        existing_check = json.loads(check_json.read_text(encoding="utf-8")) if check_json.is_file() else {}
        previous_upload = existing_check.get("live_upload") or {}
        if previous_upload.get("returncode") != 0:
            errors.append("Douyin reverify requested but no previous successful live_upload result exists.")
            upload_result = {"status": "not-run", "reason": "reverify requires previous successful live_upload"}
        else:
            upload_result = {**previous_upload, "status": previous_upload.get("status") or "submitted"}
            post_publish_verification, verify_errors = build_post_publish_verification(manifest, upload_result)
            (post_dir / "post_publish_verification.json").write_text(
                json.dumps(post_publish_verification, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if verify_errors:
                errors.append("Douyin upload submitted but post-publish verification failed: " + ", ".join(verify_errors))
    elif manifest and video_path.is_file():
        upload_result = run_sau(upload_args(manifest))
        upload_result["status"] = "submitted" if upload_result["returncode"] == 0 else "failed"
        if upload_result["returncode"] != 0:
            errors.append("Douyin upload-video command failed.")
        else:
            post_publish_verification, verify_errors = build_post_publish_verification(manifest, upload_result)
            (post_dir / "post_publish_verification.json").write_text(
                json.dumps(post_publish_verification, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if verify_errors:
                errors.append("Douyin upload submitted but post-publish verification failed: " + ", ".join(verify_errors))

command = sau_command(upload_args(manifest)) if manifest else []
execution_profile = str(
    manifest.get("execution_profile")
    or os.environ.get("SEARCHPO_EXECUTION_PROFILE")
    or ("live" if live else ("lambda" if manifest.get("render_mode") == "lambda" else "provider"))
)
effective_render_mode = str(
    manifest.get("render_mode")
    or os.environ.get("SEARCHPO_EFFECTIVE_RENDER_MODE")
    or ("lambda" if execution_profile in {"lambda", "live"} else "local")
)
effective_publish_mode = "live" if live else "contract-check"
result = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "status": "pass" if not errors else "fail",
    "execution_profile": execution_profile,
    "side_effect_tier": execution_profile,
    "render_mode": effective_render_mode,
    "publish_mode": effective_publish_mode,
    "platform": "douyin",
    "adapter": "dreammis/social-auto-upload",
    "check_level": check_level,
    "run_dir": str(run_dir),
    "rendered_video_path": str(video_path),
    "cover_path": cover_path_value,
    "cover_present": cover_present,
    "cover_health": cover_health,
    "identity_checks": identity_checks,
    "social_auto_upload_root": str(social_root),
    "social_auto_upload_python": social_python,
    "social_auto_upload_cli": social_cli,
    "social_upload_headed": upload_headed,
    "required_files": required_files,
    "cli_help": cli_help,
    "account_check": account_check,
    "live_upload": upload_result,
    "post_publish_verification": post_publish_verification,
    "live_upload_enabled": live,
    "upload_command_preview": " ".join(shlex.quote(part) for part in command) if command else "",
    "warnings": warnings,
    "errors": errors,
}
check_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(json.dumps({"douyin_upload_check": str(check_json), "warnings": warnings, "errors": errors}, ensure_ascii=False, indent=2))
raise SystemExit(1 if errors else 0)
PY
