#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <source-dir> <target-dir>" >&2
  exit 2
fi

source_dir="${1%/}/"
target_dir="${2%/}/"

mkdir -p "$target_dir"

COPYFILE_DISABLE=1 rsync -a --delete \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.env.*' \
  --exclude='repo-to-x-workspace' \
  --exclude='repo-to-x-output' \
  --exclude='repo-to-x-runs' \
  --exclude='.DS_Store' \
  --exclude='._*' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  "$source_dir" "$target_dir"

find "$target_dir" -name '.DS_Store' -delete
find "$target_dir" -name '._*' -delete
find "$target_dir" -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -rf "$target_dir/.git"

if command -v xattr >/dev/null 2>&1; then
  xattr -cr "$target_dir" 2>/dev/null || true
  find "$target_dir" -name '._*' -delete
fi

if command -v dot_clean >/dev/null 2>&1; then
  dot_clean -m "$target_dir" 2>/dev/null || true
  find "$target_dir" -name '._*' -delete
fi

echo "Synced cleanly: $target_dir"
