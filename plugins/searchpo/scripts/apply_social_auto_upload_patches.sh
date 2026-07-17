#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${SEARCHPO_ENV_FILE:-.env}"

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

TARGET="$SOCIAL_ROOT/uploader/douyin_uploader/main.py"
PATCH="$ROOT/scripts/patches/social-auto-upload-douyin-timeout.patch"

if [[ ! -f "$TARGET" ]]; then
  echo "Missing social-auto-upload Douyin uploader: $TARGET" >&2
  exit 1
fi

if rg -q 'wait_until="domcontentloaded"' "$TARGET"; then
  echo "social-auto-upload Douyin timeout patch already applied."
else
  (cd "$SOCIAL_ROOT" && patch -p1 < "$PATCH")
  echo "Applied social-auto-upload Douyin timeout patch."
fi

if ! rg -q 'content/upload", timeout=90000' "$TARGET"; then
  python3 - "$TARGET" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace(
    'await page.wait_for_url("https://creator.douyin.com/creator-micro/content/upload")',
    'await page.wait_for_url("https://creator.douyin.com/creator-micro/content/upload", timeout=90000)',
)
path.write_text(text, encoding="utf-8")
PY
  echo "Applied social-auto-upload Douyin wait_for_url timeout patch."
fi

if [[ -x "$SOCIAL_ROOT/.venv/bin/uv" ]]; then
  (cd "$SOCIAL_ROOT" && .venv/bin/uv pip install --force-reinstall .)
elif command -v uv >/dev/null 2>&1; then
  (cd "$SOCIAL_ROOT" && uv pip install --force-reinstall .)
elif [[ -x "$SOCIAL_ROOT/.venv/bin/pip" ]]; then
  (cd "$SOCIAL_ROOT" && .venv/bin/pip install --force-reinstall .)
else
  echo "Patch applied, but no uv or .venv/bin/pip found to reinstall social-auto-upload." >&2
fi
