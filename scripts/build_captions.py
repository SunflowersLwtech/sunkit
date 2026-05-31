#!/usr/bin/env python3
"""Build frame-accurate caption timing from the voiceover text + real audio length.

The previous ``src/Captions.tsx`` chopped the voiceover into fixed 8-character
groups and spread them *evenly* across ``durationInFrames - startFrame - 30`` —
a span that had nothing to do with how long the TTS audio actually was. So the
words drifted out of sync the moment the speaking rate varied or the audio was
shorter/longer than the hard-coded 360-frame video.

This script ties captions to the generated audio:

1. Read the real audio duration (seconds) from ``voiceover_manifest.json``.
2. Split the voiceover into phrases at natural punctuation pauses (and cap very
   long phrases for readability), keeping latin words intact.
3. Allocate each phrase a slice of the real audio span weighted by character
   count plus a small extra "pause" weight after terminal punctuation — the
   places a TTS voice actually slows down.

The result, ``captions.json``, carries explicit ``start_frame``/``end_frame`` per
segment, which ``src/Captions.tsx`` renders verbatim instead of re-guessing.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"

from agent_harness.policy import policy_get
from agent_harness.speech_quality import normalize_voiceover_text

# Punctuation that ends a phrase. Terminal marks imply a longer spoken pause.
_TERMINAL = "。！？!?…"
_MINOR = "，、,；;：:"
_BREAKERS = _TERMINAL + _MINOR + "\n\r"

DEFAULT_FPS = 30
DEFAULT_LEAD_SEC = 0.12
DEFAULT_TAIL_SEC = 0.18
# A vertical caption bar wraps to ~2 lines; keep a phrase under this spoken
# weight before we sub-split a long, punctuation-free run.
DEFAULT_MAX_SEG_CHARS = 24.0
DEFAULT_MAX_DISPLAY_CHARS = 36
_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'/-]*")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0xF900 <= code <= 0xFAFF
        or 0xAC00 <= code <= 0xD7A3  # Hangul, treated like CJK width
    )


def _is_latin_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _cjk_count(text: str) -> int:
    return sum(1 for ch in text if _is_cjk(ch))


def orphan_caption_texts(segments: list[dict[str, Any]], punch_words: set[str]) -> list[str]:
    """Return caption snippets that are too isolated to be readable."""
    orphan_segments: list[str] = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text or text in punch_words:
            continue
        compact = re.sub(r"\s+", "", text)
        cjk_chars = _cjk_count(compact)
        if 0 < cjk_chars <= 2 and len(compact) <= 2:
            orphan_segments.append(text)
            continue
        latin_words = _LATIN_WORD_RE.findall(text)
        if cjk_chars == 0 and latin_words and len(latin_words) <= 2 and len(compact) <= 24:
            orphan_segments.append(text)
    return orphan_segments


def char_weight(ch: str) -> float:
    """Approximate spoken duration weight of a single character."""
    if _is_cjk(ch):
        return 1.0
    if _is_latin_alnum(ch):
        return 0.5
    if ch == " ":
        return 0.2
    return 0.3


def _pause_weight(punct: str) -> float:
    if not punct:
        return 0.0
    if punct in _TERMINAL:
        return 2.4
    if punct in "；;：:":
        return 1.6
    return 1.0  # comma / minor


def _text_weight(text: str) -> float:
    return sum(char_weight(c) for c in text)


def _safe_display_cut(text: str, max_display_chars: int) -> int:
    """Find a readable cut point that respects latin words when possible."""
    limit = min(len(text), max_display_chars)
    safe = 0
    for index in range(1, limit + 1):
        prev = text[index - 1]
        nxt = text[index] if index < len(text) else ""
        if not (_is_latin_alnum(prev) and _is_latin_alnum(nxt)):
            safe = index
    return safe or limit


def _enforce_display_limit(chunks: list[str], max_display_chars: int) -> list[str]:
    bounded: list[str] = []
    for chunk in chunks:
        remaining = chunk.strip()
        while len(remaining) > max_display_chars:
            cut = _safe_display_cut(remaining, max_display_chars)
            head = remaining[:cut].strip()
            if head:
                bounded.append(head)
            remaining = remaining[cut:].strip()
        if remaining:
            bounded.append(remaining)
    return bounded


def _chunk_overlong(text: str, max_seg_chars: float, max_display_chars: int = DEFAULT_MAX_DISPLAY_CHARS) -> list[str]:
    """Split one long, punctuation-free run into near-equal chunks (no orphans).

    Breaks only at safe boundaries (never inside a latin word) so we avoid
    awkward single-character tails.
    """
    total = _text_weight(text)
    if total <= max_seg_chars and len(text) <= max_display_chars:
        return [text]
    parts = max(2, round(max(total / max_seg_chars, len(text) / max_display_chars) + 0.4999))
    target = total / parts
    target_chars = max(1, len(text) / parts)
    chunks: list[str] = []
    buf: list[str] = []
    weight = 0.0
    chars = list(text)
    for i, ch in enumerate(chars):
        buf.append(ch)
        weight += char_weight(ch)
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        safe_boundary = not (_is_latin_alnum(ch) and _is_latin_alnum(nxt))
        display_len = len("".join(buf).strip())
        if (weight >= target or display_len >= target_chars) and safe_boundary and len(chunks) < parts - 1:
            chunks.append("".join(buf).strip())
            buf = []
            weight = 0.0
    tail = "".join(buf).strip()
    if tail:
        chunks.append(tail)
    return _enforce_display_limit([c for c in chunks if c], max_display_chars)


def split_phrases(
    text: str,
    max_seg_chars: float = DEFAULT_MAX_SEG_CHARS,
    max_display_chars: int = DEFAULT_MAX_DISPLAY_CHARS,
) -> list[dict[str, Any]]:
    """Split text into display phrases, recording the trailing punctuation.

    Phrases break first at natural punctuation pauses (so caption changes land on
    the beats where the TTS voice actually pauses). A long punctuation-free run is
    then sub-split into near-equal chunks for readability without leaving orphans.
    """
    raw: list[dict[str, Any]] = []
    buf: list[str] = []

    def flush(punct: str = "") -> None:
        nonlocal buf
        display = "".join(buf).strip()
        if display:
            raw.append({"text": display, "punct": punct})
        buf = []

    for ch in text or "":
        if ch in _BREAKERS:
            flush(ch if ch not in "\n\r" else "")
            continue
        buf.append(ch)
    flush("")

    phrases: list[dict[str, Any]] = []
    for phrase in raw:
        chunks = _chunk_overlong(phrase["text"], max_seg_chars, max_display_chars=max_display_chars)
        for j, chunk in enumerate(chunks):
            # Only the final chunk carries the natural trailing punctuation pause.
            phrases.append({"text": chunk, "punct": phrase["punct"] if j == len(chunks) - 1 else ""})
    return phrases


def phrase_weight(phrase: dict[str, Any]) -> float:
    body = sum(char_weight(c) for c in phrase["text"])
    return max(0.5, body) + _pause_weight(phrase.get("punct") or "")


def build_caption_segments(
    text: str,
    audio_sec: float | None,
    fps: int = DEFAULT_FPS,
    lead_sec: float = DEFAULT_LEAD_SEC,
    tail_sec: float = DEFAULT_TAIL_SEC,
    max_seg_chars: float = DEFAULT_MAX_SEG_CHARS,
    max_display_chars: int = DEFAULT_MAX_DISPLAY_CHARS,
) -> list[dict[str, Any]]:
    phrases = split_phrases(text, max_seg_chars=max_seg_chars, max_display_chars=max_display_chars)
    if not phrases:
        return []
    if not audio_sec or audio_sec <= 0:
        raise ValueError("audio_sec is required to build captions; estimated caption timing is disabled")
    total_frames = max(1, round(audio_sec * fps))
    lead = max(0, round(lead_sec * fps))
    tail = max(0, round(tail_sec * fps))
    span = max(len(phrases), total_frames - lead - tail)
    weights = [phrase_weight(p) for p in phrases]
    wsum = sum(weights) or 1.0

    segments: list[dict[str, Any]] = []
    acc = 0.0
    cursor = lead
    for index, (phrase, w) in enumerate(zip(phrases, weights)):
        acc += w
        end = lead + round(span * acc / wsum)
        start = cursor
        if end <= start:
            end = start + 1
        segments.append(
            {
                "index": index,
                "text": phrase["text"],
                "start_frame": int(start),
                "end_frame": int(end),
                "chars": len(phrase["text"]),
            }
        )
        cursor = end
    return segments


def probe_audio_seconds(audio_path: Path) -> float | None:
    """Return audio duration in seconds, preferring ffprobe, falling back to wave."""
    if not audio_path.exists():
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        value = proc.stdout.strip()
        if proc.returncode == 0 and value:
            return float(value)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        with wave.open(str(audio_path), "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate() or 1
            return frames / float(rate)
    except (wave.Error, OSError):
        return None


def latest_run_dir() -> Path:
    if not LATEST_RUN_PATH.exists():
        raise SystemExit("runtime/latest_run.txt is missing; run the pipeline first")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip()).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--text", help="Override voiceover text for local debugging.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    manifest_path = run_dir / "voiceover_manifest.json"
    manifest: dict[str, Any] = {}
    audio_sec: float | None = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        audio_sec = manifest.get("audio_duration_sec")
    if not audio_sec:
        raise SystemExit("voiceover_manifest.json missing audio_duration_sec")
    if args.text is not None:
        text = args.text
    else:
        text = str(
            manifest.get("normalized_voiceover_text")
            or manifest.get("voiceover_text")
            or ""
        ).strip()
        if not text:
            polish_path = run_dir / "deepseek_polish.json"
            if not polish_path.exists():
                raise SystemExit(f"deepseek_polish.json missing: {polish_path}")
            text = str(json.loads(polish_path.read_text(encoding="utf-8")).get("voiceover_text") or "").strip()
    text = normalize_voiceover_text(text)
    if not text:
        raise SystemExit("no voiceover_text available to build captions")

    max_display_chars = int(policy_get("quality_gate.max_caption_chars", DEFAULT_MAX_DISPLAY_CHARS))
    segments = build_caption_segments(text, audio_sec, fps=args.fps, max_display_chars=max_display_chars)
    end_frame = segments[-1]["end_frame"] if segments else 0
    punch_words = {str(item).strip() for item in policy_get("visual_audit.punch_words", [])}
    orphan_segments = orphan_caption_texts(segments, punch_words)
    invalid_ranges = [
        segment
        for segment in segments
        if segment["start_frame"] < 0 or segment["end_frame"] <= segment["start_frame"]
    ]
    audit = {
        "schema_version": 1,
        "created_at": utc_now(),
        "status": "pass" if not orphan_segments and not invalid_ranges else "fail",
        "segment_count": len(segments),
        "audio_duration_sec": audio_sec,
        "fps": args.fps,
        "orphan_segments": orphan_segments,
        "invalid_ranges": invalid_ranges,
        "max_segment_chars": max([len(segment["text"]) for segment in segments] or [0]),
    }
    payload = {
        "schema_version": 1,
        "created_at": utc_now(),
        "fps": args.fps,
        "audio_duration_sec": audio_sec,
        "source": "voiceover_manifest_or_probe",
        "segment_count": len(segments),
        "end_frame": end_frame,
        "segments": segments,
    }
    out_path = run_dir / "captions.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit_path = run_dir / "caption_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"captions": str(out_path), "caption_audit": str(audit_path), "segment_count": len(segments), "end_frame": end_frame, "audio_duration_sec": audio_sec}, ensure_ascii=False, indent=2))
    return 0 if audit["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
