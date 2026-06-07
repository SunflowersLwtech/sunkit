#!/usr/bin/env bash
set -euo pipefail

# Normalize voiceover audio to -16 LUFS for consistent Douyin playback loudness.
# Requires ffmpeg. Missing ffmpeg is a hard failure.

INPUT="${1:-}"
if [[ -z "$INPUT" || ! -f "$INPUT" ]]; then
  echo "Usage: $0 <voiceover.wav>" >&2
  exit 1
fi

FFMPEG_BIN="${FFMPEG_BIN:-}"
if [[ -z "$FFMPEG_BIN" ]]; then
  if command -v ffmpeg &>/dev/null; then
    FFMPEG_BIN="$(command -v ffmpeg)"
  elif [[ -x /opt/homebrew/bin/ffmpeg ]]; then
    FFMPEG_BIN="/opt/homebrew/bin/ffmpeg"
  elif [[ -x /usr/local/bin/ffmpeg ]]; then
    FFMPEG_BIN="/usr/local/bin/ffmpeg"
  fi
fi

if [[ -z "$FFMPEG_BIN" || ! -x "$FFMPEG_BIN" ]]; then
  echo "ffmpeg not found; audio normalization is required" >&2
  exit 1
fi

TARGET_LUFS="${SEARCHPO_AUDIO_TARGET_LUFS:--16}"
TARGET_SAMPLE_RATE="${SEARCHPO_GEMINI_TTS_SAMPLE_RATE_HZ:-22050}"
TTS_AUDIO_ENCODING="${SEARCHPO_GEMINI_TTS_AUDIO_ENCODING:-LINEAR16}"
TTS_SPEED="${SEARCHPO_GEMINI_TTS_SPEED:-1}"
TTS_VOLUME_GAIN_DB="${SEARCHPO_GEMINI_TTS_VOLUME_GAIN_DB:-0}"
OUTPUT="${INPUT%.wav}_normalized.wav"

if [[ "$TTS_AUDIO_ENCODING" != "LINEAR16" ]]; then
  echo "unsupported TTS audio encoding: $TTS_AUDIO_ENCODING" >&2
  exit 1
fi

if [[ ! "$TARGET_SAMPLE_RATE" =~ ^[0-9]+$ ]]; then
  echo "SEARCHPO_GEMINI_TTS_SAMPLE_RATE_HZ must be an integer" >&2
  exit 1
fi

if [[ ! "$TTS_SPEED" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "SEARCHPO_GEMINI_TTS_SPEED must be numeric" >&2
  exit 1
fi

if [[ ! "$TTS_VOLUME_GAIN_DB" =~ ^-?[0-9]+([.][0-9]+)?$ ]]; then
  echo "SEARCHPO_GEMINI_TTS_VOLUME_GAIN_DB must be numeric" >&2
  exit 1
fi

FILTERS=("loudnorm=I=${TARGET_LUFS}:TP=-1.5:LRA=11:print_format=json")
if [[ "$TTS_SPEED" != "1" && "$TTS_SPEED" != "1.0" ]]; then
  FILTERS+=("atempo=${TTS_SPEED}")
fi
if [[ "$TTS_VOLUME_GAIN_DB" != "0" && "$TTS_VOLUME_GAIN_DB" != "0.0" ]]; then
  FILTERS+=("volume=${TTS_VOLUME_GAIN_DB}dB")
fi
FILTER_CHAIN="$(IFS=,; echo "${FILTERS[*]}")"

"$FFMPEG_BIN" -y -i "$INPUT" \
  -af "$FILTER_CHAIN" \
  -ar "$TARGET_SAMPLE_RATE" -ac 1 -c:a pcm_s16le \
  "$OUTPUT" 2>/dev/null

mv "$OUTPUT" "$INPUT"
echo "Audio normalized to ${TARGET_LUFS} LUFS, ${TARGET_SAMPLE_RATE} Hz ${TTS_AUDIO_ENCODING}: $INPUT"
