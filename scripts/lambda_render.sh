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
FUNCTION_NAME="${SEARCHPO_LAMBDA_FUNCTION_NAME:-${REMOTION_LAMBDA_FUNCTION_NAME:-}}"
BUCKET_NAME="${REMOTION_LAMBDA_BUCKET_NAME:-}"
PRIVACY="${REMOTION_LAMBDA_PRIVACY:-private}"
SITE_NAME="${REMOTION_LAMBDA_SITE_NAME:-searchpo-radar}"
MEMORY_MB="${SEARCHPO_LAMBDA_MEMORY_MB:-${REMOTION_LAMBDA_MEMORY_MB:-2048}}"
TIMEOUT_SEC="${SEARCHPO_LAMBDA_TIMEOUT_SEC:-${REMOTION_LAMBDA_TIMEOUT_SEC:-120}}"
DISK_MB="${SEARCHPO_LAMBDA_DISK_MB:-${REMOTION_LAMBDA_DISK_MB:-10240}}"
# Default to small chunks so each λ finishes within the function timeout. Concurrency-only
# chunking (few large chunks) times out on long/heavy compositions. Override via env if needed.
FRAMES_PER_LAMBDA="${SEARCHPO_LAMBDA_FRAMES_PER_LAMBDA:-200}"
CONCURRENCY="${SEARCHPO_LAMBDA_CONCURRENCY:-${REMOTION_LAMBDA_CONCURRENCY:-4}}"
CONCURRENCY_PER_LAMBDA="${SEARCHPO_LAMBDA_CONCURRENCY_PER_LAMBDA:-1}"
DELETE_AFTER="${REMOTION_LAMBDA_DELETE_AFTER:-}"
CRF="${SEARCHPO_RENDER_CRF:-18}"
AUDIO_BITRATE="${SEARCHPO_RENDER_AUDIO_BITRATE:-192K}"
IMAGE_FORMAT="${SEARCHPO_RENDER_IMAGE_FORMAT:-jpeg}"
JPEG_QUALITY="${SEARCHPO_RENDER_JPEG_QUALITY:-95}"
ACTION="${1:-check}"
RUN_DIR="${SEARCHPO_RUN_DIR:-}"
if [[ -z "$RUN_DIR" && -f runtime/latest_run.txt ]]; then
  RUN_DIR="$(cat runtime/latest_run.txt)"
fi
PROPS_FILE="${SEARCHPO_REMOTION_PROPS:-}"
if [[ -z "$PROPS_FILE" && -n "$RUN_DIR" ]]; then
  PROPS_FILE="$RUN_DIR/remotion_input_props.json"
fi
RUN_ID="${SEARCHPO_RUN_ID:-$(basename "${RUN_DIR:-latest}")}"
RUN_DATE="${SEARCHPO_RUN_DATE:-}"
if [[ -z "$RUN_DATE" && -n "$RUN_DIR" ]]; then
  RUN_DATE="$(basename "$(dirname "$RUN_DIR")")"
fi
if [[ ! "$RUN_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  RUN_DATE="undated"
fi
PREVIEW_DIR="out/previews/$RUN_DATE/$RUN_ID/manual/lambda"
VIDEO_OUTPUT="${SEARCHPO_LAMBDA_RENDER_OUTPUT:-$PREVIEW_DIR/searchpo-radar.mp4}"
VIDEO_OUT_NAME="${SEARCHPO_LAMBDA_RENDER_OUT_NAME:-${RUN_DATE}/${RUN_ID}/manual/searchpo-radar.mp4}"
COVER_OUTPUT="${SEARCHPO_LAMBDA_COVER_OUTPUT:-$PREVIEW_DIR/searchpo-cover.jpg}"
COVER_OUT_NAME="${SEARCHPO_LAMBDA_COVER_OUT_NAME:-${RUN_DATE}/${RUN_ID}/manual/searchpo-cover.jpg}"
SAMPLE_RATE="${SEARCHPO_RENDER_SAMPLE_RATE:-}"
X264_PRESET="${SEARCHPO_RENDER_X264_PRESET:-}"

resolve_node_bin() {
  local candidates=(
    "${SEARCHPO_NODE_BIN:-}"
    "${NODE_BIN:-}"
    "/opt/homebrew/bin/node"
    "/usr/local/bin/node"
    "$(command -v node || true)"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      echo "$candidate"
      return
    fi
  done
}

NODE_RUNTIME="$(resolve_node_bin)"
if command -v npx >/dev/null 2>&1; then
  REMOTION_CMD=(npx remotion)
elif [[ -f node_modules/.bin/remotion && -n "$NODE_RUNTIME" ]]; then
  REMOTION_CMD=("$NODE_RUNTIME" node_modules/.bin/remotion)
else
  echo "Missing Remotion CLI: install npm/npx or keep node_modules/.bin/remotion available." >&2
  exit 1
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
    "${REMOTION_CMD[@]}" lambda functions ls --region "$REGION"
    ;;
  site)
    require BUCKET_NAME
    "${REMOTION_CMD[@]}" lambda sites create src/index.ts \
      --site-name "$SITE_NAME" \
      --region "$REGION" \
      --force-bucket-name "$BUCKET_NAME" \
      --enable-folder-expiry
    ;;
  deploy)
    "${REMOTION_CMD[@]}" lambda functions deploy \
      --region "$REGION" \
      --memory "$MEMORY_MB" \
      --timeout "$TIMEOUT_SEC" \
      --disk "$DISK_MB" \
      --quiet
    ;;
  render)
    require FUNCTION_NAME
    require BUCKET_NAME
    if [[ -z "$RUN_DIR" ]]; then
      echo "Missing run directory; pass SEARCHPO_RUN_DIR or create runtime/latest_run.txt." >&2
      exit 1
    fi
    if [[ -z "$PROPS_FILE" || ! -f "$PROPS_FILE" ]]; then
      echo "Missing Remotion props file: ${PROPS_FILE:-<unset>}" >&2
      echo "Run: python3 render/prepare_remotion_input.py \"${RUN_DIR:-<run_dir>}\"" >&2
      exit 1
    fi
    python3 scripts/verify_remotion_inputs.py "$RUN_DIR" --props "$PROPS_FILE"
    mkdir -p "$(dirname "$VIDEO_OUTPUT")"
    RENDER_CMD=(
      "${REMOTION_CMD[@]}" lambda render "$SITE_NAME" SearchpoRadar "$VIDEO_OUTPUT"
      --region "$REGION"
      --function-name "$FUNCTION_NAME"
      --force-bucket-name "$BUCKET_NAME"
      --props "$PROPS_FILE"
      --privacy "$PRIVACY"
      --concurrency-per-lambda "$CONCURRENCY_PER_LAMBDA"
      --out-name "$VIDEO_OUT_NAME"
      --codec=h264
      --pixel-format=yuv420p
      --crf="$CRF"
      --audio-bitrate="$AUDIO_BITRATE"
      --image-format="$IMAGE_FORMAT"
      --jpeg-quality="$JPEG_QUALITY"
    )
    if [[ -n "$FRAMES_PER_LAMBDA" ]]; then
      RENDER_CMD+=(--frames-per-lambda "$FRAMES_PER_LAMBDA")
    elif [[ -n "$CONCURRENCY" ]]; then
      RENDER_CMD+=(--concurrency "$CONCURRENCY")
    fi
    if [[ -n "$DELETE_AFTER" ]]; then
      RENDER_CMD+=(--delete-after "$DELETE_AFTER")
    fi
    if [[ -n "$SAMPLE_RATE" ]]; then
      RENDER_CMD+=(--sample-rate="$SAMPLE_RATE")
    fi
    if [[ -n "$X264_PRESET" ]]; then
      RENDER_CMD+=(--x264-preset="$X264_PRESET")
    fi
    RENDER_CMD+=(--log=verbose)
    "${RENDER_CMD[@]}"
    ;;
  still|cover)
    require FUNCTION_NAME
    require BUCKET_NAME
    if [[ -z "$PROPS_FILE" || ! -f "$PROPS_FILE" ]]; then
      echo "Missing Remotion props file: ${PROPS_FILE:-<unset>}" >&2
      echo "Run: python3 render/prepare_remotion_input.py \"${RUN_DIR:-<run_dir>}\"" >&2
      exit 1
    fi
    mkdir -p "$(dirname "$COVER_OUTPUT")"
    STILL_CMD=(
      "${REMOTION_CMD[@]}" lambda still "$SITE_NAME" SearchpoCover "$COVER_OUTPUT"
      --region "$REGION"
      --function-name "$FUNCTION_NAME"
      --force-bucket-name "$BUCKET_NAME"
      --props "$PROPS_FILE"
      --privacy "$PRIVACY"
      --out-name "$COVER_OUT_NAME"
      --image-format=jpeg
      --jpeg-quality="$JPEG_QUALITY"
    )
    if [[ -n "$DELETE_AFTER" ]]; then
      STILL_CMD+=(--delete-after "$DELETE_AFTER")
    fi
    STILL_CMD+=(--log=verbose)
    "${STILL_CMD[@]}"
    ;;
  *)
    echo "Usage: $0 [check|site|deploy|render|still]" >&2
    exit 2
    ;;
esac
