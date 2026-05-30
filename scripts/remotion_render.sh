#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ACTION="${1:-local}"
RUN_DIR="${SEARCHPO_RUN_DIR:-$(cat runtime/latest_run.txt)}"
PROPS_FILE="${SEARCHPO_REMOTION_PROPS:-$RUN_DIR/remotion_input_props.json}"

if [[ ! -f "$PROPS_FILE" ]]; then
  echo "Missing Remotion props file: $PROPS_FILE" >&2
  echo "Run: python3 render/prepare_remotion_input.py \"$RUN_DIR\"" >&2
  exit 1
fi

CRF="${SEARCHPO_RENDER_CRF:-18}"
AUDIO_BITRATE="${SEARCHPO_RENDER_AUDIO_BITRATE:-192K}"
IMAGE_FORMAT="${SEARCHPO_RENDER_IMAGE_FORMAT:-jpeg}"
JPEG_QUALITY="${SEARCHPO_RENDER_JPEG_QUALITY:-95}"

case "$ACTION" in
  local)
    RENDER_OUT="${SEARCHPO_RENDER_OUTPUT:-out/searchpo-radar.mp4}"
    npx remotion render SearchpoRadar "$RENDER_OUT" \
      --props "$PROPS_FILE" \
      --codec=h264 \
      --pixel-format=yuv420p \
      --crf="$CRF" \
      --audio-bitrate="$AUDIO_BITRATE" \
      --image-format="$IMAGE_FORMAT" \
      --jpeg-quality="$JPEG_QUALITY"
    ;;
  cover)
    COVER_OUT="${SEARCHPO_COVER_OUTPUT:-out/searchpo-cover.jpg}"
    npx remotion still SearchpoCover "$COVER_OUT" \
      --props "$PROPS_FILE" \
      --image-format=jpeg \
      --jpeg-quality="$JPEG_QUALITY"
    ;;
  *)
    echo "Usage: $0 [local|cover]" >&2
    exit 2
    ;;
esac
