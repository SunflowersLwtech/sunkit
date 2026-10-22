#!/usr/bin/env python3
"""Generate a voiceover audio artifact for a searchpo run through Cartesia TTS.

Writes the same voiceover.wav and voiceover_manifest.json as scripts/gemini_tts.py,
so captions and render timing downstream read it unchanged. Selected with
SEARCHPO_TTS_PROVIDER=cartesia. Spending is bounded by a daily character cap
(SEARCHPO_TTS_DAILY_CHARS) kept in a ledger under the ignored runtime/ directory.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from agent_harness.speech_quality import chinese_ratio, has_raw_speech_symbols, normalize_voiceover_text
from build_captions import probe_audio_seconds
from env_utils import env_value
from gemini_tts import (
    DEFAULT_AUDIO_TARGET_LUFS,
    DEFAULT_FPS,
    latest_run_dir,
    parse_numeric_setting,
    read_json,
    resolve_tool,
    sha256_file,
    sha256_text,
    split_tts_chunks,
    utc_now,
    write_json,
)

CARTESIA_TTS_URL = "https://api.cartesia.ai/tts/bytes"
CARTESIA_VERSION = "2026-08-14"
DEFAULT_CARTESIA_MODEL = "sonic-3.6"
CARTESIA_LANGUAGE = "zh"
SAMPLE_RATE_HZ = 44100
SAMPLE_WIDTH_BYTES = 2
CHANNELS = 1
CHUNK_CHARS = 1200
DEFAULT_DAILY_CHARS = 5000
DEFAULT_LEDGER_PATH = ROOT / "runtime" / "tts_usage" / "cartesia_daily_chars.json"
LEDGER_KEEP_DAYS = 31
RETRYABLE_STATUS = (429, 500, 502, 503, 504)
MAX_DURATION_DRIFT_SEC = 0.35


class DailyCapExceeded(RuntimeError):
    pass


def utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class DailyCharLedger:
    """Characters sent to Cartesia per UTC day, shared by every run on this checkout."""

    def __init__(self, path: Path, cap: int, *, today: str | None = None) -> None:
        self.path = path
        self.cap = cap
        self.today = today or utc_date()

    @contextmanager
    def _locked(self) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                data = read_json(self.path) if self.path.is_file() else {}
                if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
                    data = {"schema_version": 1, "provider": "cartesia", "unit": "transcript_characters", "days": {}}
                yield data
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def used(self) -> int:
        with self._locked() as data:
            return int((data["days"].get(self.today) or {}).get("chars") or 0)

    def _refusal(self, used: int, needed: int) -> str:
        return (
            f"Cartesia daily character cap would be exceeded: {used} of {self.cap} characters already used on "
            f"{self.today} (UTC) and this voiceover needs {needed} more. No request was sent. Wait for the next UTC "
            "day or raise SEARCHPO_TTS_DAILY_CHARS deliberately."
        )

    def check(self, needed: int) -> int:
        used = self.used()
        if used + needed > self.cap:
            raise DailyCapExceeded(self._refusal(used, needed))
        return used

    def reserve(self, chars: int) -> int:
        """Count characters against today's cap before a request is sent."""
        with self._locked() as data:
            day = data["days"].setdefault(self.today, {"chars": 0, "requests": 0})
            used = int(day.get("chars") or 0)
            if used + chars > self.cap:
                raise DailyCapExceeded(self._refusal(used, chars))
            day["chars"] = used + chars
            day["requests"] = int(day.get("requests") or 0) + 1
            data["days"] = {key: data["days"][key] for key in sorted(data["days"])[-LEDGER_KEEP_DAYS:]}
            data["cap"] = self.cap
            data["updated_at"] = utc_now()
            write_json(self.path, data)
            return used + chars


def cartesia_request_body(model: str, voice: str, transcript: str) -> dict[str, Any]:
    return {
        "model_id": model,
        "transcript": transcript,
        "voice": {"mode": "id", "id": voice},
        "language": CARTESIA_LANGUAGE,
        "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": SAMPLE_RATE_HZ},
    }


def parse_streamed_wav(data: bytes) -> tuple[bytes, dict[str, int]]:
    """Return the PCM payload and format of a streamed WAV.

    A streamed WAV is written before its length is known, so the RIFF and data
    size fields are placeholders. The payload is every byte after the 'data'
    tag and its size field, trimmed to whole sample frames.
    """
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise RuntimeError("Cartesia response is not a RIFF/WAVE stream")
    fmt = {"channels": CHANNELS, "sample_rate": SAMPLE_RATE_HZ, "bits_per_sample": SAMPLE_WIDTH_BYTES * 8}
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        body_start = offset + 8
        if chunk_id == b"data":
            frame_bytes = fmt["channels"] * fmt["bits_per_sample"] // 8
            pcm = data[body_start:]
            pcm = pcm[: len(pcm) - len(pcm) % frame_bytes]
            if not pcm:
                raise RuntimeError("Cartesia WAV stream has an empty data chunk")
            return pcm, fmt
        if body_start + chunk_size > len(data):
            raise RuntimeError(f"Cartesia WAV chunk {chunk_id!r} runs past the end of the stream")
        if chunk_id == b"fmt ":
            audio_format, channels, sample_rate, _byte_rate, _block_align, bits = struct.unpack(
                "<HHIIHH", data[body_start : body_start + 16]
            )
            if audio_format not in (1, 0xFFFE) or bits != 16:
                raise RuntimeError(f"Cartesia WAV is not 16-bit PCM (format={audio_format}, bits={bits})")
            fmt = {"channels": channels, "sample_rate": sample_rate, "bits_per_sample": bits}
        offset = body_start + chunk_size + (chunk_size % 2)
    raise RuntimeError("Cartesia WAV stream has no data chunk")


def pcm_duration_sec(pcm: bytes, fmt: dict[str, int]) -> float:
    frame_bytes = fmt["channels"] * fmt["bits_per_sample"] // 8
    return len(pcm) / frame_bytes / float(fmt["sample_rate"])


def write_wav(path: Path, pcm: bytes, fmt: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(fmt["channels"])
        wav.setsampwidth(fmt["bits_per_sample"] // 8)
        wav.setframerate(fmt["sample_rate"])
        wav.writeframes(pcm)


def read_wav(path: Path) -> tuple[bytes, dict[str, int]]:
    with wave.open(str(path), "rb") as wav:
        fmt = {"channels": wav.getnchannels(), "sample_rate": wav.getframerate(), "bits_per_sample": wav.getsampwidth() * 8}
        return wav.readframes(wav.getnframes()), fmt


def concat_wavs(paths: list[Path], output_path: Path) -> dict[str, Any]:
    if not paths:
        raise RuntimeError("no TTS chunks to concatenate")
    pcm_parts: list[bytes] = []
    first_fmt: dict[str, int] | None = None
    for path in paths:
        pcm, fmt = read_wav(path)
        if first_fmt is None:
            first_fmt = fmt
        elif fmt != first_fmt:
            raise RuntimeError(f"TTS chunk format mismatch: {path.name} is {fmt}, expected {first_fmt}")
        pcm_parts.append(pcm)
    assert first_fmt is not None
    write_wav(output_path, b"".join(pcm_parts), first_fmt)
    return {"status": "single_chunk" if len(paths) == 1 else "concatenated", "chunk_count": len(paths)}


def reusable_chunk(path: Path, *, text_hash: str, index: int, previous_manifest: dict[str, Any], model: str, voice: str) -> bool:
    """Reuse a chunk only when the same Cartesia model and voice spoke the same text."""
    if previous_manifest.get("provider") != "cartesia" or previous_manifest.get("model") != model or previous_manifest.get("voice") != voice:
        return False
    chunks = ((previous_manifest.get("tts_chunking") or {}).get("chunks") or [])
    record = next((item for item in chunks if int(item.get("index") or 0) == index), None)
    if not record or str(record.get("text_hash") or "") != text_hash or not path.is_file():
        return False
    if str(record.get("audio_sha256") or "") != sha256_file(path):
        return False
    try:
        pcm, _fmt = read_wav(path)
    except (wave.Error, OSError, EOFError):
        return False
    return bool(pcm)


def synthesize(
    api_key: str,
    model: str,
    voice: str,
    transcript: str,
    timeout: float,
    ledger: DailyCharLedger,
    *,
    attempts: int = 3,
) -> tuple[bytes, dict[str, Any]]:
    body = json.dumps(cartesia_request_body(model, voice, transcript), ensure_ascii=False).encode("utf-8")
    retry_history: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        # Characters are counted before every request, retries included, so the cap bounds spend.
        ledger.reserve(len(transcript))
        request = urllib.request.Request(
            CARTESIA_TTS_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Cartesia-Version": CARTESIA_VERSION,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                audio = response.read()
                content_type = response.headers.get("Content-Type", "")
            return audio, {"attempts": attempt, "content_type": content_type, "bytes": len(audio), "retry_history": retry_history}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:].replace(api_key, "[redacted]")
            if exc.code in RETRYABLE_STATUS and attempt < attempts:
                delay = 3.0 * (2 ** (attempt - 1))
                print(f"Cartesia TTS HTTP {exc.code}, retrying in {delay:.0f}s (attempt {attempt}/{attempts})...", file=sys.stderr)
                retry_history.append({"attempt": attempt, "http_status": exc.code})
                time.sleep(delay)
                continue
            raise RuntimeError(f"Cartesia TTS HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < attempts:
                delay = 3.0 * (2 ** (attempt - 1))
                print(f"Cartesia TTS network error, retrying in {delay:.0f}s (attempt {attempt}/{attempts})...", file=sys.stderr)
                retry_history.append({"attempt": attempt, "network_error": str(exc)[:200]})
                time.sleep(delay)
                continue
            raise RuntimeError(f"Cartesia TTS network error: {exc}") from exc
    raise RuntimeError("Cartesia TTS exhausted retries")


def normalize_audio(audio_path: Path, sample_rate_hz: int, target_lufs: float) -> None:
    ffmpeg_bin = resolve_tool("ffmpeg")
    # normalize_audio.sh reads the Gemini-named knobs; pin them so Gemini settings never reshape Cartesia audio.
    normalize_env = {
        **os.environ,
        "SEARCHPO_GEMINI_TTS_AUDIO_ENCODING": "LINEAR16",
        "SEARCHPO_GEMINI_TTS_SAMPLE_RATE_HZ": str(sample_rate_hz),
        "SEARCHPO_GEMINI_TTS_SPEED": "1",
        "SEARCHPO_GEMINI_TTS_VOLUME_GAIN_DB": "0",
        "SEARCHPO_AUDIO_TARGET_LUFS": str(target_lufs),
        "FFMPEG_BIN": ffmpeg_bin,
        "PATH": os.pathsep.join([str(Path(ffmpeg_bin).parent), os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin"]),
    }
    proc = subprocess.run(
        ["bash", str(ROOT / "scripts" / "normalize_audio.sh"), str(audio_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=normalize_env,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "audio normalization failed; refusing to continue without normalized real audio\n"
            f"stdout:\n{proc.stdout[-1000:]}\nstderr:\n{proc.stderr[-1000:]}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER_PATH), help="Daily character ledger JSON path.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    env_file = Path(args.env_file).resolve()
    api_key = env_value("CARTESIA_API_KEY", env_file)
    if not api_key:
        raise SystemExit("CARTESIA_API_KEY is required for scripts/cartesia_tts.py")
    voice = env_value("SEARCHPO_CARTESIA_VOICE", env_file).strip()
    if not voice:
        raise SystemExit("SEARCHPO_CARTESIA_VOICE (a Cartesia voice id) is required for scripts/cartesia_tts.py")
    model = env_value("SEARCHPO_CARTESIA_MODEL", env_file, DEFAULT_CARTESIA_MODEL).strip() or DEFAULT_CARTESIA_MODEL
    try:
        daily_cap = int(env_value("SEARCHPO_TTS_DAILY_CHARS", env_file, str(DEFAULT_DAILY_CHARS)))
    except ValueError as exc:
        raise SystemExit("SEARCHPO_TTS_DAILY_CHARS must be an integer") from exc
    if daily_cap < 0:
        raise SystemExit("SEARCHPO_TTS_DAILY_CHARS must not be negative")
    target_lufs = parse_numeric_setting(
        env_value("SEARCHPO_AUDIO_TARGET_LUFS", env_file, str(DEFAULT_AUDIO_TARGET_LUFS)),
        DEFAULT_AUDIO_TARGET_LUFS,
        "SEARCHPO_AUDIO_TARGET_LUFS",
    )
    try:
        fps = int(env_value("SEARCHPO_VIDEO_FPS", env_file, str(DEFAULT_FPS)))
    except ValueError:
        fps = DEFAULT_FPS

    polish_path = run_dir / "deepseek_polish.json"
    if not polish_path.exists():
        raise SystemExit(f"DeepSeek polish artifact missing: {polish_path}")
    polish = read_json(polish_path)
    previous_manifest = read_json(run_dir / "voiceover_manifest.json") if (run_dir / "voiceover_manifest.json").exists() else {}
    source_text = str(polish.get("voiceover_text") or "").strip()
    if not source_text:
        raise SystemExit("deepseek_polish.json has no voiceover_text")
    text = normalize_voiceover_text(source_text)
    speech_quality_checks = {
        "voiceover_chinese_ratio": round(chinese_ratio(text), 3),
        "raw_symbol_pronunciation_safe": not has_raw_speech_symbols(text),
        "normalizer": "agent_harness.speech_quality.normalize_voiceover_text",
    }
    if speech_quality_checks["voiceover_chinese_ratio"] < 0.22:
        raise SystemExit(
            f"normalized voiceover is not Mandarin-ready: Chinese ratio {speech_quality_checks['voiceover_chinese_ratio']}"
        )
    if not speech_quality_checks["raw_symbol_pronunciation_safe"]:
        raise SystemExit("normalized voiceover still contains raw slash, URL, or symbol pronunciation risk")

    text_chunks = split_tts_chunks(text, CHUNK_CHARS)
    if not text_chunks:
        raise SystemExit("normalized voiceover_text produced no TTS chunks")
    chunk_dir = run_dir / "audio_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    planned = []
    for index, chunk_text in enumerate(text_chunks, start=1):
        chunk_path = chunk_dir / f"voiceover_part_{index:03d}.wav"
        text_hash = sha256_text(chunk_text)
        reuse = reusable_chunk(chunk_path, text_hash=text_hash, index=index, previous_manifest=previous_manifest, model=model, voice=voice)
        planned.append((index, chunk_text, chunk_path, text_hash, reuse))

    ledger = DailyCharLedger(Path(args.ledger).expanduser().resolve(), daily_cap)
    chars_needed = sum(len(chunk_text) for _index, chunk_text, _path, _hash, reuse in planned if not reuse)
    try:
        used_before = ledger.check(chars_needed)
    except DailyCapExceeded as exc:
        raise SystemExit(str(exc)) from exc

    chunk_paths: list[Path] = []
    chunk_records: list[dict[str, Any]] = []
    retry_history: list[dict[str, Any]] = []
    stream_duration_sec = 0.0
    for index, chunk_text, chunk_path, text_hash, reuse in planned:
        if reuse:
            pcm, fmt = read_wav(chunk_path)
            chunk_meta: dict[str, Any] = {"reused_existing_chunk": True}
            source_mime_type = "audio/wav;source=reused-cartesia-tts-chunk"
        else:
            try:
                audio, chunk_meta = synthesize(api_key, model, voice, chunk_text, args.timeout, ledger)
            except DailyCapExceeded as exc:
                raise SystemExit(str(exc)) from exc
            pcm, fmt = parse_streamed_wav(audio)
            if fmt["sample_rate"] != SAMPLE_RATE_HZ:
                raise RuntimeError(f"Cartesia returned {fmt['sample_rate']} Hz audio; requested {SAMPLE_RATE_HZ} Hz")
            write_wav(chunk_path, pcm, fmt)
            retry_history.extend({"chunk": index, **item} for item in chunk_meta.pop("retry_history", []))
            source_mime_type = f"audio/wav;codec=pcm_s16le;rate={fmt['sample_rate']};channels={fmt['channels']};source=cartesia-tts-bytes"
        chunk_seconds = pcm_duration_sec(pcm, fmt)
        stream_duration_sec += chunk_seconds
        chunk_paths.append(chunk_path)
        chunk_records.append(
            {
                "index": index,
                "text_hash": text_hash,
                "char_count": len(chunk_text),
                "audio_path": str(chunk_path),
                "audio_sha256": sha256_file(chunk_path),
                "data_chunk_bytes": len(pcm),
                "data_chunk_duration_sec": round(chunk_seconds, 3),
                "source_mime_type": source_mime_type,
                "response_meta": chunk_meta,
            }
        )

    audio_path = run_dir / "voiceover.wav"
    concat = concat_wavs(chunk_paths, audio_path)
    normalize_audio(audio_path, SAMPLE_RATE_HZ, target_lufs)
    audio_duration_sec = probe_audio_seconds(audio_path)
    if not audio_duration_sec:
        raise RuntimeError(f"could not probe normalized voiceover duration: {audio_path}")
    if abs(audio_duration_sec - stream_duration_sec) > MAX_DURATION_DRIFT_SEC:
        raise RuntimeError(
            f"normalized voiceover length {audio_duration_sec:.3f}s drifted from the streamed audio "
            f"{stream_duration_sec:.3f}s; refusing to publish mismatched audio"
        )
    audio_frames = round(audio_duration_sec * fps)
    source_mime_types = {record["source_mime_type"] for record in chunk_records}
    manifest = {
        "schema_version": 2,
        "created_at": utc_now(),
        "provider": "cartesia",
        "model": model,
        "api_mode": "tts_bytes",
        "voice": voice,
        "tts_style": "",
        "language": CARTESIA_LANGUAGE,
        "audio_encoding": "LINEAR16",
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "speed": 1.0,
        "volume_gain_db": 0.0,
        "target_lufs": target_lufs,
        "status": "pass",
        "source_mime_type": source_mime_types.pop() if len(source_mime_types) == 1 else "audio/wav;source=segmented-cartesia-tts",
        "output_mime_type": f"audio/wav;codec=pcm_s16le;rate={SAMPLE_RATE_HZ};channels={CHANNELS}",
        "audio_path": str(audio_path),
        "audio_duration_sec": audio_duration_sec,
        "audio_frames": audio_frames,
        "fps": fps,
        "voiceover_text": text,
        "text_hash": sha256_text(text),
        "source_voiceover_text": source_text,
        "normalized_voiceover_text": text,
        "audio_sha256": sha256_file(audio_path),
        "retry_history": retry_history,
        "tts_chunking": {
            "strategy": "sentence_chunks",
            "chunk_chars": CHUNK_CHARS,
            "chunk_count": len(text_chunks),
            "chunks": chunk_records,
        },
        "speech_quality_checks": speech_quality_checks,
        "response_meta": {
            "chunk_count": len(text_chunks),
            "chunk_chars": CHUNK_CHARS,
            "chunks": chunk_records,
            "concat": concat,
            "cartesia_version": CARTESIA_VERSION,
            "stream_data_duration_sec": round(stream_duration_sec, 3),
        },
        "daily_char_cap": {
            "utc_date": ledger.today,
            "cap": daily_cap,
            "used_before_run": used_before,
            "chars_requested": chars_needed,
            "ledger_path": str(ledger.path),
        },
    }
    manifest_path = run_dir / "voiceover_manifest.json"
    write_json(manifest_path, manifest)
    print(json.dumps({"voiceover_manifest": str(manifest_path), "audio_path": str(audio_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
