#!/usr/bin/env python3
"""Generate a voiceover audio artifact for a searchpo run through Gemini TTS."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from agent_harness.speech_quality import chinese_ratio, has_raw_speech_symbols, normalize_voiceover_text
from env_utils import first_env, env_value
from gemini_api import default_gemini_mode, generate_content_url
from build_captions import probe_audio_seconds

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"

# Gemini TTS can be steered with a natural-language delivery directive prepended
# to the content (it reads this as a style cue, not as spoken text). The old
# pipeline sent bare text, so the strongest TTS model spoke flat and lifeless.
DEFAULT_TTS_STYLE = (
    "请用自然标准普通话朗读后面的中文稿件，不要读出本说明。"
    "声音设定：专业但亲和的抖音知识教育女声，清晰、可信、有活力，"
    "像经验丰富的短视频老师在给普通观众讲有用知识。"
    "整体语气要自信、干净、友好、信息量清楚；不要像新闻主播、商业销售、广播主持、亢奋带货口吻或机器人旁白。"
    "语速中快，适合抖音知识短视频，节奏紧凑但关键点必须清楚。"
    "开头第一句稍微更有好奇感和抓人感。"
    "主体讲解要有自然教学节奏，让问题、解释、例子和结论的结构听得出来；在主要步骤之间留短暂停顿。"
    "数字、关键词、定义、对比、步骤名、因果关系和最后结论要轻微放慢并适度强调。"
    "反问后、重要结论前和大步骤之间可以短暂停顿，但不要长时间空白。"
    "吐字标准清晰，声母利落，句尾干净，不拖尾。"
    "情绪保持投入和理性好奇，但要克制、专业、可信，避免喊叫、夸张网红感、油腻营销腔、过度戏剧化、睡前故事感、单调朗读和机械 TTS 节奏。"
)
DEFAULT_TTS_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_TTS_VOICE = "Aoede"
DEFAULT_TTS_AUDIO_ENCODING = "LINEAR16"
DEFAULT_TTS_SAMPLE_RATE_HZ = 22050
DEFAULT_TTS_SPEED = 1.0
DEFAULT_TTS_VOLUME_GAIN_DB = 0.0
DEFAULT_AUDIO_TARGET_LUFS = -16.0
DEFAULT_FPS = 30


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_numeric_setting(raw: str, default: float, name: str) -> float:
    value = (raw or "").strip()
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be numeric, got {value!r}") from exc
    return parsed


def latest_run_dir() -> Path:
    if not LATEST_RUN_PATH.exists():
        raise SystemExit("runtime/latest_run.txt is missing; run data_prep/scripts/run_pipeline.py first")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip()).resolve()


def find_inline_audio(payload: dict[str, Any]) -> tuple[bytes, str]:
    candidates = payload.get("candidates") or []
    for candidate in candidates:
        parts = ((candidate.get("content") or {}).get("parts") or [])
        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                mime_type = inline_data.get("mimeType") or inline_data.get("mime_type") or "application/octet-stream"
                return base64.b64decode(inline_data["data"]), mime_type
    raise RuntimeError(f"Gemini TTS response did not contain inline audio: {json.dumps(payload, ensure_ascii=False)[:1000]}")


def parse_sample_rate(mime_type: str) -> int:
    for marker in ("rate=", "sample-rate="):
        if marker in mime_type:
            value = mime_type.split(marker, 1)[1].split(";", 1)[0].strip()
            if value.isdigit():
                return int(value)
    return 24000


def write_audio(path: Path, audio_bytes: bytes, mime_type: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lower = mime_type.lower()
    if "wav" in lower:
        path.write_bytes(audio_bytes)
        return mime_type
    if "l16" in lower or "pcm" in lower or "raw" in lower:
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(parse_sample_rate(mime_type))
            wav.writeframes(audio_bytes)
        return f"audio/wav;source={mime_type}"
    path.write_bytes(audio_bytes)
    return mime_type


def build_tts_prompt(text: str, style: str) -> str:
    """Prepend the delivery directive so the voice carries emotion."""
    style = (style or "").strip()
    if not style:
        return text
    return f"{style}：\n{text}"


def generate_tts(api_key: str, model: str, voice: str, text: str, timeout: float, env_file: Path, style: str = "") -> tuple[bytes, str, dict[str, Any]]:
    url = generate_content_url(model, api_key, env_file)
    prompt_text = build_tts_prompt(text, style)
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice,
                    }
                }
            },
        },
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-1200:]
            if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                delay = 3.0 * (2 ** attempt)
                print(f"Gemini TTS HTTP {exc.code}, retrying in {delay:.0f}s (attempt {attempt+1}/3)...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"Gemini TTS HTTP {exc.code}: {detail}")
                continue
            raise RuntimeError(f"Gemini TTS HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                delay = 3.0 * (2 ** attempt)
                print(f"Gemini TTS network error, retrying in {delay:.0f}s (attempt {attempt+1}/3)...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"Gemini TTS network error: {exc}")
                continue
            raise RuntimeError(f"Gemini TTS network error: {exc}") from exc
    else:
        raise last_exc or RuntimeError("Gemini TTS exhausted retries")
    audio_bytes, mime_type = find_inline_audio(payload)
    return audio_bytes, mime_type, {"modelVersion": payload.get("modelVersion"), "usageMetadata": payload.get("usageMetadata")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    env_file = Path(args.env_file).resolve()
    api_key = first_env(["GOOGLE_API_KEY", "GOOGLE_AGENT_PLATFORM_API"], env_file)
    if not api_key:
        raise SystemExit("GOOGLE_API_KEY or GOOGLE_AGENT_PLATFORM_API is required for scripts/gemini_tts.py")
    model = env_value("SEARCHPO_GEMINI_TTS_MODEL", env_file, DEFAULT_TTS_MODEL)
    voice = env_value("SEARCHPO_GEMINI_TTS_VOICE", env_file, DEFAULT_TTS_VOICE)
    style = env_value("SEARCHPO_GEMINI_TTS_STYLE", env_file, DEFAULT_TTS_STYLE)
    audio_encoding = env_value("SEARCHPO_GEMINI_TTS_AUDIO_ENCODING", env_file, DEFAULT_TTS_AUDIO_ENCODING).upper()
    if audio_encoding != "LINEAR16":
        raise SystemExit("SEARCHPO_GEMINI_TTS_AUDIO_ENCODING must be LINEAR16 for the current WAV pipeline")
    try:
        sample_rate_hz = int(env_value("SEARCHPO_GEMINI_TTS_SAMPLE_RATE_HZ", env_file, str(DEFAULT_TTS_SAMPLE_RATE_HZ)))
    except ValueError as exc:
        raise SystemExit("SEARCHPO_GEMINI_TTS_SAMPLE_RATE_HZ must be an integer") from exc
    if sample_rate_hz <= 0:
        raise SystemExit("SEARCHPO_GEMINI_TTS_SAMPLE_RATE_HZ must be greater than 0")
    speed = parse_numeric_setting(
        env_value("SEARCHPO_GEMINI_TTS_SPEED", env_file, str(DEFAULT_TTS_SPEED)),
        DEFAULT_TTS_SPEED,
        "SEARCHPO_GEMINI_TTS_SPEED",
    )
    if speed <= 0:
        raise SystemExit("SEARCHPO_GEMINI_TTS_SPEED must be greater than 0")
    volume_gain_db = parse_numeric_setting(
        env_value("SEARCHPO_GEMINI_TTS_VOLUME_GAIN_DB", env_file, str(DEFAULT_TTS_VOLUME_GAIN_DB)),
        DEFAULT_TTS_VOLUME_GAIN_DB,
        "SEARCHPO_GEMINI_TTS_VOLUME_GAIN_DB",
    )
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

    audio_bytes, source_mime_type, response_meta = generate_tts(api_key, model, voice, text, args.timeout, env_file, style=style)
    audio_path = run_dir / "voiceover.wav"
    output_mime_type = write_audio(audio_path, audio_bytes, source_mime_type)
    import subprocess as _sp
    normalize_env = {
        **os.environ,
        "SEARCHPO_GEMINI_TTS_AUDIO_ENCODING": audio_encoding,
        "SEARCHPO_GEMINI_TTS_SAMPLE_RATE_HZ": str(sample_rate_hz),
        "SEARCHPO_GEMINI_TTS_SPEED": str(speed),
        "SEARCHPO_GEMINI_TTS_VOLUME_GAIN_DB": str(volume_gain_db),
        "SEARCHPO_AUDIO_TARGET_LUFS": str(target_lufs),
    }
    normalize_proc = _sp.run(
        ["bash", str(ROOT / "scripts" / "normalize_audio.sh"), str(audio_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=normalize_env,
    )
    if normalize_proc.returncode != 0:
        raise RuntimeError(
            "audio normalization failed; refusing to continue without normalized real audio\n"
            f"stdout:\n{normalize_proc.stdout[-1000:]}\nstderr:\n{normalize_proc.stderr[-1000:]}"
        )
    output_mime_type = f"audio/wav;codec=pcm_s16le;rate={sample_rate_hz};channels=1"
    # Probe the real (normalized) audio length so captions and video duration can
    # be locked to it instead of a hard-coded frame count.
    audio_duration_sec = probe_audio_seconds(audio_path)
    audio_frames = round(audio_duration_sec * fps) if audio_duration_sec else None
    manifest = {
        "schema_version": 2,
        "created_at": utc_now(),
        "provider": "gemini",
        "model": model,
        "api_mode": default_gemini_mode(env_file),
        "voice": voice,
        "tts_style": style,
        "language": "Chinese, Mandarin (China)",
        "audio_encoding": audio_encoding,
        "sample_rate_hz": sample_rate_hz,
        "speed": speed,
        "volume_gain_db": volume_gain_db,
        "target_lufs": target_lufs,
        "status": "pass",
        "source_mime_type": source_mime_type,
        "output_mime_type": output_mime_type,
        "audio_path": str(audio_path),
        "audio_duration_sec": audio_duration_sec,
        "audio_frames": audio_frames,
        "fps": fps,
        "voiceover_text": text,
        "text_hash": sha256_text(text),
        "source_voiceover_text": source_text,
        "normalized_voiceover_text": text,
        "audio_sha256": sha256_file(audio_path) if audio_path.is_file() else None,
        "retry_history": response_meta.get("retry_history") or [],
        "speech_quality_checks": speech_quality_checks,
        "response_meta": response_meta,
    }
    manifest_path = run_dir / "voiceover_manifest.json"
    write_json(manifest_path, manifest)
    print(json.dumps({"voiceover_manifest": str(manifest_path), "audio_path": str(audio_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
