#!/usr/bin/env python3
"""Generate a voiceover audio artifact for a searchpo run through Gemini TTS."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from env_utils import first_env, env_value
from gemini_api import default_gemini_mode, generate_content_url

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def generate_tts(api_key: str, model: str, voice: str, text: str, timeout: float, env_file: Path) -> tuple[bytes, str, dict[str, Any]]:
    url = generate_content_url(model, api_key, env_file)
    body = {
        "contents": [{"role": "user", "parts": [{"text": text}]}],
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
    model = env_value("SEARCHPO_GEMINI_TTS_MODEL", env_file, "gemini-3.1-flash-tts-preview")
    voice = env_value("SEARCHPO_GEMINI_TTS_VOICE", env_file, "Kore")
    polish_path = run_dir / "deepseek_polish.json"
    if not polish_path.exists():
        raise SystemExit(f"DeepSeek polish artifact missing: {polish_path}")
    polish = read_json(polish_path)
    text = str(polish.get("voiceover_text") or "").strip()
    if not text:
        raise SystemExit("deepseek_polish.json has no voiceover_text")

    audio_bytes, source_mime_type, response_meta = generate_tts(api_key, model, voice, text, args.timeout, env_file)
    audio_path = run_dir / "voiceover.wav"
    output_mime_type = write_audio(audio_path, audio_bytes, source_mime_type)
    import subprocess as _sp
    _sp.run(["bash", str(ROOT / "scripts" / "normalize_audio.sh"), str(audio_path)],
            cwd=str(ROOT), capture_output=True, timeout=30)
    manifest = {
        "schema_version": 1,
        "created_at": utc_now(),
        "provider": "gemini",
        "model": model,
        "api_mode": default_gemini_mode(env_file),
        "voice": voice,
        "status": "pass",
        "source_mime_type": source_mime_type,
        "output_mime_type": output_mime_type,
        "audio_path": str(audio_path),
        "voiceover_text": text,
        "response_meta": response_meta,
    }
    manifest_path = run_dir / "voiceover_manifest.json"
    write_json(manifest_path, manifest)
    print(json.dumps({"voiceover_manifest": str(manifest_path), "audio_path": str(audio_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
