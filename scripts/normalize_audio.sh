#!/usr/bin/env bash
set -euo pipefail

# Normalize voiceover audio to -16 LUFS for consistent Douyin playback loudness.
# Requires ffmpeg. Skipped gracefully if ffmpeg is not installed.

INPUT="${1:-}"
if [[ -z "$INPUT" || ! -f "$INPUT" ]]; then
  echo "Usage: $0 <voiceover.wav>" >&2
  exit 1
fi

if ! command -v ffmpeg &>/dev/null; then
  echo "ffmpeg not found, skipping audio normalization" >&2
  exit 0
fi

TARGET_LUFS="${SEARCHPO_AUDIO_TARGET_LUFS:--16}"
OUTPUT="${INPUT%.wav}_normalized.wav"

ffmpeg -y -i "$INPUT" \
  -af "loudnorm=I=${TARGET_LUFS}:TP=-1.5:LRA=11:print_format=json" \
  -ar 24000 -ac 1 \
  "$OUTPUT" 2>/dev/null

mv "$OUTPUT" "$INPUT"
echo "Audio normalized to ${TARGET_LUFS} LUFS: $INPUT"
