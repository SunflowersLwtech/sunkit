#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-${REMOTION_AWS_ACCESS_KEY_ID:-}}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-${REMOTION_AWS_SECRET_ACCESS_KEY:-}}"
export AWS_REGION="${AWS_REGION:-${REMOTION_LAMBDA_REGION:-${REMOTION_AWS_REGION:-}}}"

REGION="${REMOTION_LAMBDA_REGION:-${REMOTION_AWS_REGION:-}}"
FUNCTION_NAME="${REMOTION_LAMBDA_FUNCTION_NAME:-}"
BUCKET_NAME="${REMOTION_LAMBDA_BUCKET_NAME:-}"
PRIVACY="${REMOTION_LAMBDA_PRIVACY:-private}"
SITE_NAME="${REMOTION_LAMBDA_SITE_NAME:-searchpo-radar}"
CONCURRENCY="${REMOTION_LAMBDA_CONCURRENCY:-4}"
ACTION="${1:-check}"
RUN_DIR="${SEARCHPO_RUN_DIR:-}"
if [[ -z "$RUN_DIR" && -f runtime/latest_run.txt ]]; then
  RUN_DIR="$(cat runtime/latest_run.txt)"
fi
PROPS_FILE="${SEARCHPO_REMOTION_PROPS:-}"
if [[ -z "$PROPS_FILE" && -n "$RUN_DIR" ]]; then
  PROPS_FILE="$RUN_DIR/remotion_input_props.json"
fi

require() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required env var: $name" >&2
    exit 1
  fi
}

require AWS_ACCESS_KEY_ID
require AWS_SECRET_ACCESS_KEY
require REGION

case "$ACTION" in
  check)
    npx remotion lambda functions ls --region "$REGION"
    ;;
  site)
    require BUCKET_NAME
    npx remotion lambda sites create src/index.ts \
      --site-name "$SITE_NAME" \
      --region "$REGION" \
      --force-bucket-name "$BUCKET_NAME" \
      --enable-folder-expiry
    ;;
  render)
    require FUNCTION_NAME
    require BUCKET_NAME
    if [[ -z "$PROPS_FILE" || ! -f "$PROPS_FILE" ]]; then
      echo "Missing Remotion props file: ${PROPS_FILE:-<unset>}" >&2
      echo "Run: python3 render/prepare_remotion_input.py \"${RUN_DIR:-<run_dir>}\"" >&2
      exit 1
    fi
    npx remotion lambda render "$SITE_NAME" SearchpoRadar out/searchpo-radar-lambda.mp4 \
      --region "$REGION" \
      --function-name "$FUNCTION_NAME" \
      --force-bucket-name "$BUCKET_NAME" \
      --props "$PROPS_FILE" \
      --privacy "$PRIVACY" \
      --concurrency "$CONCURRENCY" \
      --codec=h264 \
      --pixel-format=yuv420p \
      --log=verbose
    ;;
  *)
    echo "Usage: $0 [check|site|render]" >&2
    exit 2
    ;;
esac
