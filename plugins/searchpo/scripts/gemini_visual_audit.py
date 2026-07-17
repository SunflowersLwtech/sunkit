#!/usr/bin/env python3
"""Audit the native final/publish Searchpo MP4 through Gemini before publish."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import re
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from agent_harness.policy import policy_get, unsupported_terms
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latest_run_dir() -> Path:
    if not LATEST_RUN_PATH.exists():
        raise SystemExit("runtime/latest_run.txt is missing; run data_prep/scripts/run_pipeline.py first")
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip()).resolve()


def audit_video_path(video_path: Path, run_dir: Path, max_bytes: int, proxy_dir: Path | None = None) -> tuple[Path, dict[str, Any]]:
    size = video_path.stat().st_size
    if size <= max_bytes:
        return video_path, {"mode": "original", "original_video_path": str(video_path), "original_size_bytes": size}
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit(f"Rendered video is {size} bytes, above inline Gemini audit limit {max_bytes}, and ffmpeg is unavailable for proxy generation.")
    proxy_root = proxy_dir or run_dir
    proxy_root.mkdir(parents=True, exist_ok=True)
    proxy = proxy_root / "gemini_visual_audit_proxy.mp4"
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            "scale='min(1280,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "34",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            str(proxy),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0 or not proxy.is_file():
        raise SystemExit(f"Could not create Gemini audit proxy for oversized video: {proc.stderr[-1200:]}")
    proxy_size = proxy.stat().st_size
    if proxy_size > max_bytes:
        raise SystemExit(f"Gemini audit proxy remains above inline limit: {proxy_size} > {max_bytes}")
    return proxy, {
        "mode": "proxy",
        "original_video_path": str(video_path),
        "original_size_bytes": size,
        "audited_video_path": str(proxy),
        "audited_size_bytes": proxy_size,
        "ffmpeg_stderr_tail": proc.stderr[-1200:],
    }


DEVELOPER_BASE_URL = "https://generativelanguage.googleapis.com"


def generated_json(
    model: str,
    api_key: str,
    parts: list[dict[str, Any]],
    timeout: float,
    env_file: Path,
    *,
    url_override: str | None = None,
) -> dict[str, Any]:
    url = url_override or generate_content_url(model, api_key, env_file)
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
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
                delay = 4.0 * (2 ** attempt)
                print(f"Gemini audit HTTP {exc.code}, retrying in {delay:.0f}s (attempt {attempt+1}/3)...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"Gemini audit HTTP {exc.code}: {detail}")
                continue
            raise RuntimeError(f"Gemini visual audit HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 3:
                delay = 4.0 * (2 ** attempt)
                print(f"Gemini audit network error, retrying in {delay:.0f}s (attempt {attempt+1}/3)...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"Gemini audit network error: {exc}")
                continue
            raise RuntimeError(f"Gemini visual audit network error: {exc}") from exc
    else:
        raise last_exc or RuntimeError("Gemini audit exhausted retries")
    text = ""
    for candidate in payload.get("candidates") or []:
        for part in ((candidate.get("content") or {}).get("parts") or []):
            text += part.get("text") or ""
    if not text:
        raise RuntimeError(f"Gemini visual audit returned no text: {json.dumps(payload, ensure_ascii=False)[:1000]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_audit_object(value: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value.get("checks"), dict) or value.get("verdict"):
        return value
    nested = value.get("required_output")
    if isinstance(nested, dict) and (isinstance(nested.get("checks"), dict) or nested.get("verdict")):
        return nested
    return value


def developer_generate_content_url(model: str, api_key: str) -> str:
    quoted_model = urllib.parse.quote(model)
    quoted_key = urllib.parse.quote(api_key)
    return f"{DEVELOPER_BASE_URL}/v1beta/models/{quoted_model}:generateContent?key={quoted_key}"


def _developer_request_json(url: str, api_key: str, *, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 180) -> tuple[dict[str, Any], Any]:
    request = urllib.request.Request(
        url,
        data=data,
        headers={"x-goog-api-key": api_key, **(headers or {})},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return (json.loads(raw) if raw else {}, response.headers)


def upload_video_file_api(video_path: Path, mime_type: str, api_key: str, timeout: float) -> dict[str, Any]:
    video_bytes = video_path.read_bytes()
    display_name = f"searchpo-{video_path.stem}"
    start_payload = json.dumps({"file": {"display_name": display_name}}).encode("utf-8")
    _, headers = _developer_request_json(
        f"{DEVELOPER_BASE_URL}/upload/v1beta/files",
        api_key,
        data=start_payload,
        headers={
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(video_bytes)),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )
    upload_url = headers.get("x-goog-upload-url")
    if not upload_url:
        raise RuntimeError("Gemini Files API did not return x-goog-upload-url")

    file_info, _ = _developer_request_json(
        upload_url,
        api_key,
        data=video_bytes,
        headers={
            "Content-Length": str(len(video_bytes)),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        },
        timeout=timeout,
    )
    file_record = file_info.get("file") or {}
    file_name = str(file_record.get("name") or "")
    if not file_name or not file_record.get("uri"):
        raise RuntimeError(f"Gemini Files API upload returned incomplete file info: {json.dumps(file_info, ensure_ascii=False)[:1000]}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        current, _ = _developer_request_json(f"{DEVELOPER_BASE_URL}/v1beta/{file_name}", api_key, timeout=min(30, timeout))
        current_file = current.get("file") or {}
        state = str(current_file.get("state") or file_record.get("state") or "")
        if state in {"ACTIVE", "SUCCEEDED", ""}:
            file_record.update(current_file)
            break
        if state in {"FAILED", "ERROR"}:
            raise RuntimeError(f"Gemini Files API processing failed: {json.dumps(current, ensure_ascii=False)[:1000]}")
        time.sleep(2)

    return {
        "name": file_record.get("name"),
        "uri": file_record.get("uri"),
        "mime_type": file_record.get("mimeType") or file_record.get("mime_type") or mime_type,
        "state": file_record.get("state"),
        "size_bytes": len(video_bytes),
    }


def choose_video_input_mode(
    env_file: Path,
    configured: str,
    api_mode: str,
    developer_key_available: bool,
    agent_platform_key_available: bool = False,
) -> str:
    requested = configured or env_value("SEARCHPO_GEMINI_VIDEO_INPUT_MODE", env_file, "auto")
    requested = requested.strip().lower()
    if requested in {"file", "files", "file_api", "upload"}:
        return "file_api"
    if requested in {"inline", "inline_video"}:
        return "inline_video"
    if requested in {"agent_platform", "vertex", "vertex_express", "sdk", "google_genai"}:
        return "agent_platform"
    if requested != "auto":
        raise RuntimeError(f"Unsupported Gemini video input mode: {requested}")
    if api_mode == "developer":
        return "file_api" if developer_key_available else "inline_video"
    if api_mode == "vertex_express":
        return "agent_platform"
    if api_mode == "vertex_standard":
        return "vertex_standard"
    if agent_platform_key_available:
        return "agent_platform"
    return "file_api" if developer_key_available else "inline_video"


def _load_google_genai_sdk() -> tuple[Any, Any]:
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Gemini Enterprise Agent Platform / Vertex Express video audit requires the official google-genai SDK. "
            "Install it with `python3 -m pip install google-genai` or run Developer API video audit with "
            "`SEARCHPO_GEMINI_API_MODE=developer --video-input-mode file_api` and a Gemini Developer API key."
        ) from exc
    return genai, types


def _extract_sdk_response_text(response: Any) -> str:
    text_value = getattr(response, "text", None)
    if callable(text_value):
        text_value = text_value()
    if isinstance(text_value, str) and text_value.strip():
        return text_value
    candidates = getattr(response, "candidates", None) or []
    chunks: list[str] = []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                chunks.append(str(part_text))
    if chunks:
        return "".join(chunks)
    if hasattr(response, "to_json"):
        return str(response.to_json())
    return str(response)


def generated_json_agent_platform_sdk(
    model: str,
    api_key: str,
    video_path: Path,
    mime_type: str,
    prompt: str,
    timeout: float,
    video_fps: float | None,
) -> dict[str, Any]:
    genai, types = _load_google_genai_sdk()
    client = genai.Client(vertexai=True, api_key=api_key)
    video_kwargs: dict[str, Any] = {
        "inline_data": types.Blob(data=video_path.read_bytes(), mime_type=mime_type),
    }
    if video_fps and video_fps > 0:
        video_kwargs["video_metadata"] = types.VideoMetadata(fps=video_fps)
    video_part = types.Part(**video_kwargs)
    text_part = types.Part(text=prompt)
    config = types.GenerateContentConfig(
        temperature=0.1,
        response_mime_type="application/json",
    )
    deadline = time.time() + timeout
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=model,
                contents=types.Content(role="user", parts=[video_part, text_part]),
                config=config,
            )
            text = _extract_sdk_response_text(response)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", text, re.S)
                if not match:
                    raise
                return json.loads(match.group(0))
        except Exception as exc:
            if time.time() >= deadline or attempt >= 3:
                raise RuntimeError(f"Gemini Agent Platform SDK visual audit failed: {exc}") from exc
            delay = min(4.0 * (2 ** attempt), max(1.0, deadline - time.time()))
            print(
                f"Gemini Agent Platform SDK audit error, retrying in {delay:.0f}s (attempt {attempt+1}/3)...",
                file=sys.stderr,
            )
            time.sleep(delay)
            last_exc = exc
    raise RuntimeError(f"Gemini Agent Platform SDK audit exhausted retries: {last_exc}")


def build_prompt(run_dir: Path, video_path: Path) -> str:
    selected = read_json(run_dir / "selected_candidate.json")
    render_payload = read_json(run_dir / "render_payload.json")
    polish = read_json(run_dir / "deepseek_polish.json")
    voiceover_manifest_path = run_dir / "voiceover_manifest.json"
    voiceover_manifest = read_json(voiceover_manifest_path) if voiceover_manifest_path.exists() else {}
    evidence_path = run_dir / "evidence_bundle.json"
    cross_check_path = run_dir / "cross_check_review.json"
    evidence_bundle = read_json(evidence_path) if evidence_path.exists() else {}
    cross_check_review = read_json(cross_check_path) if cross_check_path.exists() else {}
    claims_path = run_dir / "post" / "claims_ledger.json"
    claims = read_json(claims_path) if claims_path.exists() else {}
    cards = render_payload.get("cards") if isinstance(render_payload.get("cards"), list) else []
    profile = render_payload.get("videoProfile") if isinstance(render_payload.get("videoProfile"), dict) else {}
    expected_orientation = str(render_payload.get("orientation") or profile.get("orientation") or "vertical")
    expected_aspect_ratio = str(render_payload.get("aspectRatio") or profile.get("aspect_ratio") or ("16:9" if expected_orientation == "horizontal" else "9:16"))
    vertical_contract = expected_orientation != "horizontal"
    required_checks = {
        "video_readable": "boolean",
        "full_native_video_reviewed": "boolean; true only after reviewing the native MP4 across beginning, middle, and end, not screenshots or JSON",
        "native_video_audio_reviewed": "boolean; true only after listening to the native MP4 audio track, including voiceover and background music/mix if present",
        "text_not_overlapping": "boolean",
        "candidate_matches_artifacts": "boolean",
        "no_unsupported_claims": "boolean",
        "voiceover_matches_copy": "boolean; true when voiceover and visible copy are consistent, exact wording is not required",
        "voiceover_visual_same_subject": "boolean; true only when the spoken subject and central visual subject are the same at beginning, middle, and end; adjacent-but-different visuals must fail",
        "captions_match_spoken_audio": "boolean; true when subtitles follow the actual spoken audio, not just the script artifact",
        "background_music_mix_safe": "boolean; true when background music is absent or mixed below voiceover without masking speech",
        "cover_text_safe": "boolean; true when cover title and metric are fully inside the frame and readable",
        "no_internal_terms": "boolean; true when public copy does not expose pipeline terms",
        "no_hype_without_evidence": "boolean; true when unverified topics are not framed as industry-changing conclusions",
        "speech_pronunciation_safe": "boolean; true when the voiceover does not read raw slashes, URLs, or symbols",
        "audio_visual_alignment_safe": "boolean; true when captions, visible emphasis, and central visuals follow the spoken beat and subject",
        "central_motion_not_caption_or_progress_only": "boolean; true only when central visual content changes materially throughout the video; captions, progress bars, text highlights, and fades do not count",
        "topic_specific_visual": "boolean; true only when the visual grammar fits the subject, e.g. code, terminal, diagram, browser, file tree, chart, table, or architecture flow for developer/tool topics",
        "not_cards_only_template": "boolean; true only when the video is not just generic evidence cards/slides with subtitles",
        "composition_not_overcrowded": "boolean; true only when the frame has one clear primary focal action and no dashboard-like clutter",
        "single_primary_focal_action": "boolean; true only when the viewer can identify one dominant visual action at beginning, middle, and end",
        "no_competing_overlays": "boolean; true only when chapter panels, progress rails, captions, sidebars, and fact boxes do not compete with the central visual",
        "topic_visual_not_generic_dashboard": "boolean; true only when the visual system is designed for this exact topic, not a reusable SOURCE FLOW/status-card dashboard",
        "publish_ready": "boolean",
        "content_has_constructive_insight": "boolean; true when the video explains problem, mechanism, architecture position, failure boundary, and judgment framework from evidence",
        "premium_director_visual_fit": "boolean; true when the video looks like a topic-specific premium Remotion/Keynote showcase rather than a generic radar/card template",
    }
    strict_contract = [
        "A pass verdict is invalid unless the native MP4 itself is reviewed, including video frames, voiceover audio, background music or absence of music, captions, and final publish layout.",
        "A pass verdict is invalid if the auditor only validates render_payload, screenshots, OCR, captions.json, provider copy, or a claims ledger.",
        "A pass verdict is invalid without at least three timeline_reviews with concrete timestamped video and audio commentary.",
        "A pass verdict is invalid if any timeline review uses one-word shorthand such as pass/fail instead of concrete caption/progress evidence.",
        "A pass verdict is invalid if any timeline review omits spoken_audio_observation, background_music_observation, visual_subject, spoken_subject, or audio_visual_subject_alignment.",
        "A pass verdict is invalid if the central visual subject is adjacent but not the same as the spoken subject. For example, GUI/VLM/screen/tool-use visuals must fail when the voiceover is about enterprise Bedrock access, IAM/VPC/CloudTrail governance, Native AWS Access, or LLM Gateway.",
        "A pass verdict is invalid when visible movement is only captions, subtitle highlights, progress bars, or simple fade-in/fade-out; central visual content must move or change materially.",
        "A pass verdict is invalid if checks omit full_native_video_reviewed, native_video_audio_reviewed, voiceover_visual_same_subject, captions_match_spoken_audio, background_music_mix_safe, central_motion_not_caption_or_progress_only, topic_specific_visual, or not_cards_only_template.",
        "A pass verdict is invalid for a generic cards-only or slide-deck video; Remotion must be used for topic-specific composition, not just static cards plus subtitles.",
        "A pass verdict is invalid if captions, subtitle bars, character-progress highlights, or provider-rendered caption blocks overlap each other or cover main content.",
        "A pass verdict is invalid when the frame is visually overcrowded, dashboard-like, or has multiple visual systems fighting for attention.",
        "A pass verdict is invalid unless composition_not_overcrowded, single_primary_focal_action, no_competing_overlays, and topic_visual_not_generic_dashboard are all true.",
        "A pass verdict is invalid when motion_assessment.level is static or low.",
        "A pass verdict is invalid without rubric_scores for hook_clarity, scene_pacing, visual_hierarchy, central_animation_richness, topic_visual_fit, caption_safe_area, audio_visual_sync, and evidence_guardrail.",
        f"A pass verdict is invalid if any rubric_scores item is below its configured publish target: {rubric_publish_minimums_text()}.",
        "A pass verdict is invalid without narrative_structure that separately discusses opening, middle, ending, and pacing.",
        "A pass verdict is invalid without animation_diagnostics listing at least three central motion layers and at least two topic-specific visual objects.",
        "Do not count smooth transitions, fades, captions, progress bars, or generic dynamic movement as central motion layers. Name the visible object and action.",
        "Do not treat high information density as quality. If a large title, side metrics, bottom state cards, fact cards, chapter panel, captions, and progress rail are visible together, fail for overcrowding.",
        "Do not infer quality from render_payload, provider copy, or claims ledger. Only visible and audible native-video evidence can justify pass.",
    ]
    if vertical_contract:
        required_checks["douyin_safe_area"] = "boolean; true when the video is vertical Douyin 9:16 output and captions avoid the lower platform UI obstruction area"
        required_checks["douyin_vertical_format"] = "boolean; true only when the native video is vertical 9:16 Douyin format, not horizontal or square"
        strict_contract.insert(3, "A pass verdict is invalid if checks omit douyin_vertical_format.")
        strict_contract.insert(5, "A pass verdict is invalid for horizontal 16:9 output when the expected profile is vertical Douyin 9:16.")
    else:
        required_checks["profile_format_match"] = f"boolean; true only when the native video matches the expected {expected_orientation} {expected_aspect_ratio} profile"
        strict_contract.insert(3, "A pass verdict is invalid if checks omit profile_format_match.")
        strict_contract.insert(5, f"A pass verdict is invalid if the native video does not match the expected {expected_orientation} {expected_aspect_ratio} profile.")
    enhanced_checks = [str(item) for item in policy_get("gemini_visual_audit.enhanced_checks", [])]
    if not vertical_contract:
        enhanced_checks = [
            item
            for item in enhanced_checks
            if "vertical Douyin 9:16" not in item and "lower 300px obstruction zone" not in item
        ]
    voiceover_text = _nonempty_text(
        voiceover_manifest.get("voiceover_text")
        or voiceover_manifest.get("source_voiceover_text")
        or render_payload.get("voiceoverText")
    )
    public_context = {
        "selected_title": selected.get("title"),
        "canonical_url": selected.get("canonical_url"),
        "expected_public_title": render_payload.get("displayTitle") or render_payload.get("title") or polish.get("polished_title"),
        "expected_public_cards": [
            {
                "label": card.get("label"),
                "value": card.get("value"),
                "detail": card.get("detail"),
            }
            for card in cards[:4]
            if isinstance(card, dict)
        ],
        "intended_voiceover_excerpt": voiceover_text[:1200],
        "source_facts": (cross_check_review.get("source_facts") or (evidence_bundle.get("evidence_summary") or {}).get("source_facts") or [])[:8],
        "constructive_angles": (
            cross_check_review.get("constructive_angles")
            or (evidence_bundle.get("evidence_summary") or {}).get("constructive_angles")
            or []
        )[:6],
    }
    return json.dumps(
        {
            "task": "Audit this rendered searchpo video before publishing.",
            "video_first_rule": (
                "Judge the native MP4 input as the final publish candidate. Watch the full video enough to cover beginning, middle, and end; "
                "listen to the actual audio track; compare the spoken subject, subtitles, background music/mix, and central visuals. "
                "The context below is only the intended public subject boundary; it is not proof that the rendered video is readable or publishable."
            ),
            "required_output": {
                "verdict": "pass or fail",
                "summary": "one sentence",
                "checks": required_checks,
                "issues": ["array of concrete issues; empty if pass"],
                "timeline_reviews": [
                    {
                        "timestamp": "MM:SS; cover beginning, middle, and end of the native video input",
                        "commentary": "specific visual observations from this moment in the video, not a restatement of run artifacts",
                        "spoken_audio_observation": "what the voiceover is saying around this timestamp, based on the native MP4 audio",
                        "background_music_observation": "whether background music is present, absent, too loud, or safely below the voiceover around this timestamp",
                        "visual_subject": "the central visual subject actually shown around this timestamp",
                        "spoken_subject": "the subject actually spoken around this timestamp",
                        "audio_visual_subject_alignment": "concrete explanation of whether spoken_subject and visual_subject are the same subject; one-word pass/fail is invalid",
                        "text_readability": "concrete readability evidence; one-word pass/fail is invalid",
                        "caption_progress_alignment": "concrete caption/progress evidence; one-word pass/fail is invalid",
                        "motion_observation": (
                            "specific central visual movement visible around this timestamp, such as moving diagram nodes, flow paths, "
                            "charts, panels, or interface objects; captions/progress/text highlights/fades alone are invalid and must be reported as insufficient"
                        ),
                        "issues": ["timestamp-specific issues; empty only if clean"],
                    }
                ],
                "motion_assessment": {
                    "level": "static, low, adequate, or strong",
                    "commentary": "specific assessment of animation density and whether the video feels alive enough",
                },
                "audio_track_assessment": {
                    "voiceover": "concrete assessment of the native MP4 voiceover clarity and whether it matches captions",
                    "background_music": "concrete assessment of background music presence/absence, loudness, and whether it masks speech",
                    "mix": "concrete assessment of voiceover/music balance and any audible defects",
                    "issues": ["array of audio issues; empty only if clean"],
                },
                "subject_alignment": {
                    "spoken_subject": "one sentence describing the main subject from the voiceover audio",
                    "visual_subject": "one sentence describing the main subject from the central visuals",
                    "matches": "boolean; false if the visual subject is merely adjacent or reusable",
                    "mismatches": ["array of concrete mismatches; empty only if spoken and visual subjects match"],
                    "evidence": "timestamped evidence comparing audio and visuals",
                },
                "rubric_scores": {
                    "hook_clarity": "1-10 integer; whether the opening creates a concrete human reason to keep watching",
                    "scene_pacing": "1-10 integer; whether each scene has enough dwell time and breathing room",
                    "visual_hierarchy": "1-10 integer; whether the eye knows where to look in every section",
                    "central_animation_richness": "1-10 integer; whether central topic objects animate with layered motion, not just fades/progress",
                    "topic_visual_fit": "1-10 integer; whether the middle visuals fit this exact subject instead of a reusable template",
                    "caption_safe_area": "1-10 integer; whether subtitles are readable and do not crowd the main visual",
                    "audio_visual_sync": "1-10 integer; whether visible emphasis follows the spoken beat",
                    "evidence_guardrail": "1-10 integer; whether claims, caveats, and verification boundaries stay source-grounded",
                },
                "narrative_structure": {
                    "opening_hook": "concrete observation of the first hook, including what is visible in the first seconds",
                    "middle_delivery": "concrete observation of whether the middle explains mechanism/tradeoff with visual build-up",
                    "ending_payoff": "concrete observation of whether the ending leaves a usable verification path",
                    "pacing_issue": "specific pacing issue or 'none, with evidence'",
                },
                "animation_diagnostics": {
                    "main_motion_layers": [
                        "array of visible central motion layers with object + action, e.g. VLM orbit packets rotating, terminal cursor typing commands, table rows staggering in, chart bars growing, audio-reactive hub pulsing; smooth transitions/fades/captions/progress bars are invalid"
                    ],
                    "topic_specific_objects": [
                        "array of visible subject-specific objects, e.g. code file, terminal command, chart axis, architecture node, browser panel"
                    ],
                    "weak_motion": ["array of weak or non-counting motion such as captions, progress bars, fades, static card swaps"],
                    "recommended_repair": "one concrete repair instruction if fail; empty only if pass",
                },
                "composition_director": {
                    "primary_focal_target": "the one visual object/action the eye should follow at this moment; generic 'the layout' is invalid",
                    "competing_visual_systems": [
                        "array of visible systems that compete for attention, e.g. large title, central diagram, side metric bars, bottom state cards, fact cards, chapter bridge panel, captions, progress rail"
                    ],
                    "simultaneous_motion_system_count": "integer count of independently moving visual systems visible at the same time; count captions/progress/sidebars even when they are secondary",
                    "clutter_level": "low, medium, high, or overloaded",
                    "hierarchy_issue": "specific hierarchy problem, or 'none' with visual evidence",
                    "overload_issue": "specific overcrowding/competing-overlay problem, or 'none' with visual evidence",
                    "director_verdict": "pass or fail; fail if the whole composition feels confusing even when individual elements are readable",
                },
            },
            "fail_if": [
                *policy_get("gemini_visual_audit.fail_if", []),
                "The video tells viewers to verify, wait, observe, try it themselves, or otherwise shifts the knowledge burden to the viewer instead of teaching a mechanism and judgment framework.",
                "The visual language is mostly generic cards, radar chrome, dashboard panels, or reusable Searchpo template layout rather than a topic-specific premium director scene plan.",
            ],
            "forbidden_claim_terms": unsupported_terms(),
            "enhanced_checks": enhanced_checks,
            "important": policy_get("gemini_visual_audit.important", ""),
            "selected_candidate": selected,
            "render_payload": render_payload,
            "video_profile": render_payload.get("videoProfile") or render_payload.get("video_profile") or {},
            "premium_director_spec": render_payload.get("premiumDirectorSpec")
            or render_payload.get("premium_director_spec")
            or polish.get("premium_director_spec")
            or polish.get("visual_recipe"),
            "evidence_bundle": evidence_bundle,
            "cross_check_review": cross_check_review,
            "deepseek_polish": {
                "polished_title": polish.get("polished_title"),
                "voiceover_text": polish.get("voiceover_text"),
                "douyin_title": polish.get("douyin_title"),
                "douyin_desc": polish.get("douyin_desc"),
            },
            "claims_ledger": claims,
            "strict_contract": strict_contract,
            "expected_video_profile": {"orientation": expected_orientation, "aspect_ratio": expected_aspect_ratio},
            "public_context": public_context,
            "video_path": str(video_path),
        },
        ensure_ascii=False,
    )


def _nonempty_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


STRICT_REQUIRED_CHECKS = {
    "full_native_video_reviewed": "the native MP4 must be reviewed across beginning, middle, and end",
    "native_video_audio_reviewed": "the native MP4 audio track must be reviewed, including voiceover and music/mix if present",
    "central_motion_not_caption_or_progress_only": "movement must come from central visual content, not captions/progress/text highlights alone",
    "topic_specific_visual": "visual grammar must fit the topic instead of a generic card deck",
    "not_cards_only_template": "video must not be a cards-only slideshow/template",
    "voiceover_visual_same_subject": "spoken subject and central visual subject must be the same, not merely adjacent",
    "captions_match_spoken_audio": "captions must follow the actual spoken audio",
    "background_music_mix_safe": "background music must be absent or mixed safely below speech",
    "composition_not_overcrowded": "composition must not be dashboard-like, cluttered, or overloaded",
    "single_primary_focal_action": "viewer must have one dominant visual action to follow",
    "no_competing_overlays": "chapter panels, progress rails, sidebars, captions, and fact boxes must not compete with the central visual",
    "topic_visual_not_generic_dashboard": "topic visual must not be a reusable SOURCE FLOW/status-card dashboard",
}

CENTRAL_VISUAL_TERMS = (
    "diagram",
    "chart",
    "terminal",
    "code",
    "file tree",
    "table",
    "panel",
    "card",
    "graph",
    "flow",
    "matrix",
    "architecture",
    "browser",
    "diff",
    "timeline",
    "map",
    "node",
    "hub",
    "ring",
    "orbit",
    "pipeline",
    "meter",
    "gauge",
    "checklist",
    "decision",
    "list",
)

NON_CENTRAL_MOTION_TERMS = (
    "progress bar",
    "progress indicator",
    "caption",
    "subtitle",
    "text highlight",
    "text highlights",
    "highlighted text",
    "smooth transition",
    "smooth transitions",
    "scene transition",
    "scene transitions",
    "transition",
    "transitions",
    "generic dynamic",
    "generic movement",
    "static background",
    "background gradient",
    "fade in",
    "fade-in",
    "fade out",
    "fade-out",
)

DEFAULT_REQUIRED_RUBRIC_SCORES = {
    "hook_clarity": 7,
    "scene_pacing": 7,
    "visual_hierarchy": 7,
    "central_animation_richness": 7,
    "topic_visual_fit": 7,
    "caption_safe_area": 7,
    "audio_visual_sync": 7,
    "evidence_guardrail": 7,
}


def rubric_publish_minimums() -> dict[str, int]:
    configured = policy_get("gemini_visual_audit.rubric_publish_minimums", {})
    minimums = dict(DEFAULT_REQUIRED_RUBRIC_SCORES)
    if isinstance(configured, dict):
        for key, default in minimums.items():
            raw_value = configured.get(key, default)
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                value = default
            minimums[key] = max(1, min(10, value))
    return minimums


def rubric_publish_minimums_text() -> str:
    return ", ".join(f"{key}>={value}" for key, value in rubric_publish_minimums().items())

REQUIRED_NARRATIVE_FIELDS = (
    "opening_hook",
    "middle_delivery",
    "ending_payoff",
    "pacing_issue",
)

MOTION_LAYER_TERMS = (
    "spring",
    "stagger",
    "reveal",
    "build",
    "build-up",
    "count",
    "counter",
    "tick",
    "increment",
    "decrement",
    "rise",
    "fall",
    "grow",
    "shrink",
    "sweep",
    "fill",
    "meter",
    "readout",
    "gauge",
    "dial",
    "packet",
    "node",
    "beam",
    "flow",
    "connect",
    "line",
    "scan",
    "chart",
    "bar",
    "pulse",
    "puls",
    "rotat",
    "loop",
    "circle",
    "dash",
    "scale",
    "state",
    "highlight",
    "audio",
    "orbit",
    "timeline",
    "type",
    "typing",
    "slide",
    "slid",
    "sliding",
    "transform",
)

TOPIC_OBJECT_TERMS = (
    "terminal",
    "code",
    "file",
    "module",
    "repo",
    "browser",
    "docs",
    "diagram",
    "architecture",
    "node",
    "flow",
    "chart",
    "table",
    "matrix",
    "diff",
    "timeline",
    "api",
    "route",
    "panel",
    "vector",
    "query",
    "benchmark",
    "card",
    "component",
    "token",
    "meter",
    "compress",
    "compressor",
    "cache",
    "router",
    "mcp",
    "ccr",
    "pipeline",
    "checklist",
)

GENERIC_POSITIVE_AUDIT_PHRASES = (
    "pass.",
    "passes.",
    "high contrast and clean layout",
    "clean layout",
    "clear visual hierarchy",
    "smooth animations",
    "balanced composition",
    "looks good",
    "well designed",
    "easy to read",
    "perfectly match",
    "perfectly matches",
)

SPECIFIC_EVIDENCE_TERMS = tuple(
    sorted(
        set(
            CENTRAL_VISUAL_TERMS
            + TOPIC_OBJECT_TERMS
            + (
                "title",
                "label",
                "row",
                "axis",
                "node",
                "line",
                "hub",
                "safe area",
                "chapter",
                "sidebar",
                "bottom",
                "panel",
                "caption",
            )
        )
    )
)

COMPOSITION_NEGATIVE_TERMS = (
    "clutter",
    "cluttered",
    "overcrowded",
    "overloaded",
    "too dense",
    "busy",
    "competing",
    "confusing",
    "unclear",
    "fighting for attention",
    "抢焦点",
    "混乱",
    "拥挤",
    "过密",
)


def _term_count(text: str, terms: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if term in lowered)


def _is_shorthand(value: str) -> bool:
    return value.lower() in {"pass", "fail", "ok", "true", "false", "clean", "yes", "no"}


def _score_value(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else None


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_nonempty_text(item) for item in value if _nonempty_text(item)]


def _count_items_with_terms(items: list[str], terms: tuple[str, ...]) -> int:
    return sum(1 for item in items if _term_count(item.lower(), terms) > 0)


def _looks_generic_positive_evidence(value: str) -> bool:
    text = _nonempty_text(value)
    lowered = text.lower()
    if not text:
        return True
    if lowered.startswith(("pass.", "passes.", "ok.", "true.")):
        return True
    if any(phrase in lowered for phrase in GENERIC_POSITIVE_AUDIT_PHRASES):
        return len(text) < 72 or _term_count(lowered, SPECIFIC_EVIDENCE_TERMS) < 2
    return False


def _has_specific_evidence(*values: str) -> bool:
    text = " ".join(_nonempty_text(value) for value in values).lower()
    return _term_count(text, SPECIFIC_EVIDENCE_TERMS) >= 2


def _strong_visual_pass(checks: dict[str, Any]) -> bool:
    return all(
        checks.get(key) is True
        for key in (
            "central_motion_not_caption_or_progress_only",
            "topic_specific_visual",
            "not_cards_only_template",
            "composition_not_overcrowded",
            "single_primary_focal_action",
            "no_competing_overlays",
            "publish_ready",
        )
    )


def _none_issue(value: str) -> bool:
    lowered = value.lower().strip(" .。")
    return lowered in {"none", "no issue", "no hierarchy issue", "no overload issue"}


def _has_negative_composition_language(value: str) -> bool:
    lowered = value.lower()
    return any(term in lowered for term in COMPOSITION_NEGATIVE_TERMS)


def _alignment_negative(text: str) -> bool:
    lowered = text.lower()
    negative_terms = (
        "mismatch",
        "not match",
        "does not match",
        "different subject",
        "not the same",
        "misaligned",
        "unrelated",
        "adjacent but",
        "不一致",
        "不匹配",
        "不是同一个",
        "偏题",
        "跑题",
        "错题",
    )
    return any(term in lowered for term in negative_terms)


VISUAL_SUBJECT_DRIFT_MARKERS = {
    "gui_agent": ("gui", "gui plugin", "gui 插件", "interface tab", "界面图"),
    "vlm_agent": ("vlm", "vision-language", "multimodal", "多模态", "视觉语义", "vision to ui"),
    "screen_agent": ("screen · code · tool", "screen-code-tool", "screen/code/tool", "screen tool-use"),
}


def _marker_hits(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for term in terms:
        lowered_term = term.lower()
        if re.fullmatch(r"[a-z0-9]{2,6}", lowered_term):
            if re.search(rf"(?<![a-z0-9]){re.escape(lowered_term)}(?![a-z0-9])", lowered):
                hits.append(term)
            continue
        if lowered_term in lowered:
            hits.append(term)
    return hits


def _safe_json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def public_subject_boundary_text(run_dir: Path) -> str:
    """Public topic boundary used to reject visual templates that drift off subject.

    This intentionally excludes render_payload.agentVisual so a bad visual cannot
    whitelist itself by echoing its own VLM/GUI/screen template terms.
    """

    chunks: list[Any] = []
    for name in (
        "selected_candidate.json",
        "deepseek_polish.json",
        "voiceover_manifest.json",
        "fact_bank.json",
        "topic_brief.json",
        "research_brief.json",
        "cross_check_review.json",
        "evidence_bundle.json",
    ):
        payload = _read_json_if_exists(run_dir / name)
        if payload is not None:
            chunks.append(payload)
    render_payload = _read_json_if_exists(run_dir / "render_payload.json")
    if isinstance(render_payload, dict):
        chunks.append(
            {
                key: value
                for key, value in render_payload.items()
                if key
                in {
                    "displayTitle",
                    "title",
                    "speechTitle",
                    "summary",
                    "voiceoverText",
                    "cards",
                    "cta",
                    "source",
                    "sourceMap",
                    "verificationNextStep",
                    "badge",
                    "metricLine",
                    "audienceMetricLine",
                }
            }
        )
    return _safe_json_text(chunks).lower()


def _subject_drift_errors(
    *,
    spoken_subject: str,
    visual_subject: str,
    public_subject_text: str = "",
    label: str,
) -> list[str]:
    boundary = f"{public_subject_text} {spoken_subject}".lower()
    visual = visual_subject.lower()
    marker_summaries: list[str] = []
    for marker_name, terms in VISUAL_SUBJECT_DRIFT_MARKERS.items():
        visual_hits = _marker_hits(visual, terms)
        if not visual_hits:
            continue
        boundary_hits = _marker_hits(boundary, terms)
        if not boundary_hits:
            marker_summaries.append(f"{marker_name}: {visual_hits[:4]}")
    if not marker_summaries:
        return []
    return [
        (
            f"{label} visual subject contains off-boundary visual template markers "
            + "; ".join(marker_summaries)
            + " while spoken/public subject does not"
        )
    ]


def normalize_audit_payload(audit: dict[str, Any]) -> dict[str, Any]:
    nested = audit.get("required_output") if isinstance(audit, dict) else None
    if isinstance(nested, dict) and any(
        key in nested for key in ("verdict", "checks", "timeline_reviews", "rubric_scores", "animation_diagnostics")
    ):
        return nested
    return audit


def audit_contract_errors(
    audit: dict[str, Any],
    *,
    expected_orientation: str = "vertical",
    public_subject_text: str = "",
) -> list[str]:
    audit = normalize_audit_payload(audit)
    errors: list[str] = []
    checks = audit.get("checks") if isinstance(audit.get("checks"), dict) else {}
    if not checks:
        errors.append("Gemini audit missing structured checks object")
    strong_visual_pass = _strong_visual_pass(checks)
    required_rubric_scores = rubric_publish_minimums()
    required_checks = dict(STRICT_REQUIRED_CHECKS)
    if expected_orientation == "horizontal":
        required_checks["profile_format_match"] = "native video must match the expected horizontal 16:9 profile"
    else:
        required_checks["douyin_vertical_format"] = "native video must be vertical 9:16 Douyin format, not horizontal or square"
    for key, description in required_checks.items():
        if key not in checks:
            errors.append(f"Gemini audit missing required check `{key}`: {description}")
        elif checks.get(key) is not True:
            errors.append(f"Gemini audit required check `{key}` did not pass: {description}")
    if audit.get("frame_reviews") and not audit.get("timeline_reviews"):
        errors.append("Gemini audit used frame_reviews; native video audit must return timeline_reviews")
    timeline_motion_evidence: list[str] = []
    timeline_reviews = audit.get("timeline_reviews")
    if not isinstance(timeline_reviews, list) or len(timeline_reviews) < 3:
        errors.append("Gemini audit missing at least three timeline_reviews with concrete video commentary")
    else:
        timestamps: list[str] = []
        for index, review in enumerate(timeline_reviews[:3], start=1):
            if not isinstance(review, dict):
                errors.append(f"timeline_reviews[{index}] is not an object")
                continue
            timestamp = _nonempty_text(review.get("timestamp"))
            if not timestamp:
                errors.append(f"timeline_reviews[{index}] is missing timestamp")
            else:
                timestamps.append(timestamp)
            commentary = _nonempty_text(review.get("commentary") or review.get("notes") or review.get("summary"))
            text_readability = _nonempty_text(review.get("text_readability") or review.get("readability"))
            caption_alignment = _nonempty_text(
                review.get("caption_progress_alignment")
                or review.get("caption_alignment")
                or review.get("subtitle_alignment")
            )
            motion = _nonempty_text(review.get("motion_observation") or review.get("motion"))
            spoken_audio = _nonempty_text(review.get("spoken_audio_observation") or review.get("audio_observation"))
            bgm = _nonempty_text(review.get("background_music_observation") or review.get("music_observation"))
            visual_subject = _nonempty_text(review.get("visual_subject"))
            spoken_subject = _nonempty_text(review.get("spoken_subject"))
            subject_alignment = _nonempty_text(
                review.get("audio_visual_subject_alignment")
                or review.get("subject_alignment")
                or review.get("audio_visual_alignment")
            )
            if motion:
                timeline_motion_evidence.append(motion)
            if len(commentary) < 20:
                errors.append(f"timeline_reviews[{index}] lacks concrete visual commentary")
            if len(spoken_audio) < 20 or _is_shorthand(spoken_audio):
                errors.append(f"timeline_reviews[{index}] lacks native voiceover/audio evidence")
            if len(bgm) < 12 or _is_shorthand(bgm):
                errors.append(f"timeline_reviews[{index}] lacks background music/mix evidence")
            if len(visual_subject) < 8 or _is_shorthand(visual_subject):
                errors.append(f"timeline_reviews[{index}] lacks visual subject evidence")
            if len(spoken_subject) < 8 or _is_shorthand(spoken_subject):
                errors.append(f"timeline_reviews[{index}] lacks spoken subject evidence")
            if len(subject_alignment) < 20 or _is_shorthand(subject_alignment):
                errors.append(f"timeline_reviews[{index}] lacks audio-visual subject alignment evidence")
            elif _looks_generic_positive_evidence(subject_alignment) and not (
                strong_visual_pass
                and (
                    _has_specific_evidence(subject_alignment, visual_subject, spoken_subject, commentary, motion)
                    or (
                        len(visual_subject) >= 8
                        and len(spoken_subject) >= 8
                        and len(commentary) >= 20
                        and len(motion) >= 12
                    )
                )
            ):
                errors.append(f"timeline_reviews[{index}] uses generic audio-visual alignment praise without concrete evidence")
            if _alignment_negative(subject_alignment):
                errors.append(f"timeline_reviews[{index}] reports audio-visual subject mismatch")
            errors.extend(
                _subject_drift_errors(
                    spoken_subject=spoken_subject,
                    visual_subject=" ".join([visual_subject, commentary, motion]),
                    public_subject_text=public_subject_text,
                    label=f"timeline_reviews[{index}]",
                )
            )
            if len(text_readability) < 12 or _is_shorthand(text_readability):
                errors.append(f"timeline_reviews[{index}] lacks text readability evidence")
            elif _looks_generic_positive_evidence(text_readability) and not (
                _has_specific_evidence(text_readability, visual_subject, commentary, motion)
                or (strong_visual_pass and len(visual_subject) >= 8 and len(commentary) >= 20)
            ):
                errors.append(f"timeline_reviews[{index}] uses generic text readability praise without naming visible text/objects")
            if len(caption_alignment) < 12 or _is_shorthand(caption_alignment):
                errors.append(f"timeline_reviews[{index}] lacks caption/progress alignment notes")
            elif _looks_generic_positive_evidence(caption_alignment) and not (
                _has_specific_evidence(caption_alignment, visual_subject, spoken_subject, commentary)
                or (
                    strong_visual_pass
                    and checks.get("captions_match_spoken_audio") is True
                    and checks.get("audio_visual_alignment_safe") is True
                )
            ):
                errors.append(f"timeline_reviews[{index}] uses generic caption/progress praise without layout evidence")
            if len(motion) < 12:
                errors.append(f"timeline_reviews[{index}] lacks motion observation")
            motion_lower = motion.lower()
            central_count = _term_count(motion_lower, CENTRAL_VISUAL_TERMS)
            non_central_count = _term_count(motion_lower, NON_CENTRAL_MOTION_TERMS)
            if motion and non_central_count and central_count == 0:
                errors.append(f"timeline_reviews[{index}] motion is caption/progress/fade-only, not central visual motion")
            if motion and non_central_count > central_count and not (strong_visual_pass and central_count > 0):
                errors.append(f"timeline_reviews[{index}] overweights caption/progress/text-highlight motion")
        if len(set(timestamps)) < min(3, len(timestamps)):
            errors.append("Gemini audit timeline_reviews must cover distinct video timestamps")

    motion_assessment = audit.get("motion_assessment")
    if isinstance(motion_assessment, dict):
        motion_level = _nonempty_text(motion_assessment.get("level")).lower()
        motion_commentary = _nonempty_text(motion_assessment.get("commentary") or motion_assessment.get("notes"))
    else:
        motion_level = ""
        motion_commentary = _nonempty_text(motion_assessment)
    if len(motion_commentary) < 20:
        errors.append("Gemini audit missing concrete motion_assessment commentary")
    if motion_level in {"static", "low", "insufficient", "none"}:
        errors.append(f"Gemini audit motion_assessment.level is {motion_level}")
    motion_commentary_lower = motion_commentary.lower()
    central_count = _term_count(motion_commentary_lower, CENTRAL_VISUAL_TERMS)
    non_central_count = _term_count(motion_commentary_lower, NON_CENTRAL_MOTION_TERMS)
    if non_central_count and central_count == 0:
        errors.append("Gemini audit motion_assessment relies on caption/progress motion instead of central visual motion")
    if non_central_count > central_count and not (strong_visual_pass and central_count > 0):
        errors.append("Gemini audit motion_assessment overweights caption/progress/text-highlight motion")

    audio_track = audit.get("audio_track_assessment")
    if not isinstance(audio_track, dict):
        errors.append("Gemini audit missing audio_track_assessment object")
    else:
        voiceover = _nonempty_text(audio_track.get("voiceover"))
        background_music = _nonempty_text(audio_track.get("background_music") or audio_track.get("music"))
        mix = _nonempty_text(audio_track.get("mix"))
        audio_issues = _string_items(audio_track.get("issues"))
        if len(voiceover) < 24 or _is_shorthand(voiceover):
            errors.append("Gemini audit audio_track_assessment.voiceover lacks concrete native-audio evidence")
        if len(background_music) < 12 or _is_shorthand(background_music):
            errors.append("Gemini audit audio_track_assessment.background_music lacks concrete music/mix evidence")
        if len(mix) < 20 or _is_shorthand(mix):
            errors.append("Gemini audit audio_track_assessment.mix lacks concrete balance evidence")
        if audio_issues and checks.get("background_music_mix_safe") is True:
            errors.append("Gemini audit reports audio issues while background_music_mix_safe is true")

    subject_alignment = audit.get("subject_alignment")
    if not isinstance(subject_alignment, dict):
        errors.append("Gemini audit missing subject_alignment object")
    else:
        spoken_subject = _nonempty_text(subject_alignment.get("spoken_subject"))
        visual_subject = _nonempty_text(subject_alignment.get("visual_subject"))
        evidence = _nonempty_text(subject_alignment.get("evidence"))
        mismatches = _string_items(subject_alignment.get("mismatches"))
        matches = subject_alignment.get("matches")
        if len(spoken_subject) < 20 or _is_shorthand(spoken_subject):
            errors.append("Gemini audit subject_alignment.spoken_subject lacks concrete evidence")
        if len(visual_subject) < 20 or _is_shorthand(visual_subject):
            errors.append("Gemini audit subject_alignment.visual_subject lacks concrete evidence")
        if matches is not True:
            errors.append("Gemini audit subject_alignment.matches is not true")
        if mismatches:
            errors.append("Gemini audit subject_alignment reports mismatches: " + "; ".join(mismatches[:3]))
        has_timeline_markers = isinstance(timeline_reviews, list) and any(
            isinstance(review, dict) and re.search(r"\b\d{1,2}:\d{2}(?:\.\d+)?\b", _nonempty_text(review.get("timestamp")))
            for review in timeline_reviews
        )
        if len(evidence) < 30 or _is_shorthand(evidence):
            errors.append("Gemini audit subject_alignment.evidence lacks timestamped comparison")
        elif not re.search(r"\b\d{1,2}:\d{2}\b", evidence) and not (
            strong_visual_pass and matches is True and has_timeline_markers
        ):
            errors.append("Gemini audit subject_alignment.evidence lacks explicit timestamp markers")
        elif _looks_generic_positive_evidence(evidence):
            errors.append("Gemini audit subject_alignment.evidence uses generic praise instead of timestamped comparison")
        if _alignment_negative(" ".join([spoken_subject, visual_subject, evidence, *mismatches])):
            errors.append("Gemini audit subject_alignment contains mismatch language")
        errors.extend(
            _subject_drift_errors(
                spoken_subject=spoken_subject,
                visual_subject=visual_subject,
                public_subject_text=public_subject_text,
                label="Gemini audit subject_alignment",
            )
        )

    rubric_scores = audit.get("rubric_scores")
    if not isinstance(rubric_scores, dict):
        errors.append("Gemini audit missing rubric_scores object")
    else:
        for key, minimum in required_rubric_scores.items():
            score = _score_value(rubric_scores.get(key))
            if score is None:
                errors.append(f"Gemini audit rubric_scores.{key} is missing or non-numeric")
                continue
            if not 1 <= score <= 10:
                errors.append(f"Gemini audit rubric_scores.{key} must be 1-10, got {score:g}")
            if score < minimum:
                errors.append(f"Gemini audit rubric_scores.{key} is below publish target {minimum}: {score:g}")

    narrative_structure = audit.get("narrative_structure")
    if not isinstance(narrative_structure, dict):
        errors.append("Gemini audit missing narrative_structure object")
    else:
        rubric_scores_for_narrative = audit.get("rubric_scores") if isinstance(audit.get("rubric_scores"), dict) else {}
        pacing_score = _score_value(rubric_scores_for_narrative.get("scene_pacing")) if rubric_scores_for_narrative else None
        for key in REQUIRED_NARRATIVE_FIELDS:
            value = _nonempty_text(narrative_structure.get(key))
            pacing_value = value.lower().strip(" .。")
            if key == "pacing_issue" and (
                pacing_value in {"none", "no issue", "no pacing issue"}
                or pacing_value.startswith("none,")
                or pacing_value.startswith("none with")
            ):
                if pacing_score is not None and pacing_score >= required_rubric_scores["scene_pacing"]:
                    continue
            if len(value) < 20 or _is_shorthand(value):
                errors.append(f"Gemini audit narrative_structure.{key} lacks concrete video evidence")

    animation_diagnostics = audit.get("animation_diagnostics")
    if not isinstance(animation_diagnostics, dict):
        errors.append("Gemini audit missing animation_diagnostics object")
    else:
        layers = _string_items(animation_diagnostics.get("main_motion_layers"))
        objects = _string_items(animation_diagnostics.get("topic_specific_objects"))
        layer_hits = _count_items_with_terms(layers, MOTION_LAYER_TERMS)
        object_hits = _count_items_with_terms(objects, TOPIC_OBJECT_TERMS)
        invalid_layers: list[str] = []
        for layer in layers:
            lower = layer.lower()
            noncentral_hits = _term_count(lower, NON_CENTRAL_MOTION_TERMS)
            central_layer_hits = _term_count(lower, CENTRAL_VISUAL_TERMS + TOPIC_OBJECT_TERMS)
            motion_layer_hits = _term_count(lower, MOTION_LAYER_TERMS)
            if noncentral_hits and not (central_layer_hits > 0 and motion_layer_hits > 0):
                invalid_layers.append(layer)
        if invalid_layers:
            errors.append(
                "Gemini audit animation_diagnostics.main_motion_layers contains non-counting motion: "
                + "; ".join(invalid_layers[:3])
            )
        if len(layers) < 3 or layer_hits < 3 or invalid_layers:
            errors.append("Gemini audit animation_diagnostics must list at least three concrete central motion layers")
        if len(objects) < 2 or object_hits < 2:
            errors.append("Gemini audit animation_diagnostics must list at least two topic-specific visual objects")
        subject_alignment = audit.get("subject_alignment")
        spoken_subject = ""
        if isinstance(subject_alignment, dict):
            spoken_subject = _nonempty_text(subject_alignment.get("spoken_subject"))
        if spoken_subject or public_subject_text:
            errors.extend(
                _subject_drift_errors(
                    spoken_subject=spoken_subject,
                    visual_subject=" ".join(objects),
                    public_subject_text=public_subject_text,
                    label="Gemini audit animation_diagnostics.topic_specific_objects",
                )
            )
        weak_motion = " ".join(_string_items(animation_diagnostics.get("weak_motion"))).lower()
        if weak_motion and _term_count(weak_motion, NON_CENTRAL_MOTION_TERMS) and layer_hits < 3:
            errors.append("Gemini audit animation_diagnostics identifies weak caption/progress/fade motion without enough central motion layers")
    composition = audit.get("composition_director")
    if not isinstance(composition, dict):
        errors.append("Gemini audit missing composition_director object")
    else:
        focal = _nonempty_text(composition.get("primary_focal_target"))
        competing = _string_items(composition.get("competing_visual_systems"))
        clutter = _nonempty_text(composition.get("clutter_level")).lower()
        hierarchy_issue = _nonempty_text(composition.get("hierarchy_issue"))
        overload_issue = _nonempty_text(composition.get("overload_issue"))
        director_verdict = _nonempty_text(composition.get("director_verdict")).lower()
        raw_count = composition.get("simultaneous_motion_system_count")
        try:
            motion_system_count = int(raw_count)
        except (TypeError, ValueError):
            motion_system_count = -1
        if len(focal) < 16 or focal.lower() in {"layout", "composition", "video", "frame"}:
            errors.append("Gemini audit composition_director.primary_focal_target lacks a concrete focal object/action")
        if motion_system_count < 1:
            errors.append("Gemini audit composition_director.simultaneous_motion_system_count is missing or invalid")
        elif motion_system_count > 3:
            errors.append(
                f"Gemini audit composition_director reports too many simultaneous motion systems: {motion_system_count}"
            )
        effective_competing = competing
        if checks.get("no_competing_overlays") is True:
            overlay_terms = ("caption", "subtitle", "subtitles", "progress")
            effective_competing = [
                item for item in competing if not any(term in item.lower() for term in overlay_terms)
            ]
        if len(effective_competing) > 3:
            errors.append(
                "Gemini audit composition_director reports competing visual systems: " + "; ".join(effective_competing[:5])
            )
        if clutter not in {"low", "medium"}:
            errors.append(f"Gemini audit composition_director.clutter_level is {clutter or 'missing'}")
        if director_verdict != "pass":
            errors.append(f"Gemini audit composition_director.director_verdict is {director_verdict or 'missing'}")
        if _none_issue(hierarchy_issue) and director_verdict == "pass" and checks.get("single_primary_focal_action") is True:
            pass
        elif len(hierarchy_issue) < 12 or _is_shorthand(hierarchy_issue):
            errors.append("Gemini audit composition_director.hierarchy_issue lacks concrete hierarchy evidence")
        elif _has_negative_composition_language(hierarchy_issue) and not hierarchy_issue.lower().startswith("none"):
            errors.append("Gemini audit composition_director.hierarchy_issue reports visual hierarchy problems")
        if _none_issue(overload_issue) and director_verdict == "pass" and checks.get("composition_not_overcrowded") is True:
            pass
        elif len(overload_issue) < 12 or _is_shorthand(overload_issue):
            errors.append("Gemini audit composition_director.overload_issue lacks concrete overcrowding evidence")
        elif _has_negative_composition_language(overload_issue) and not overload_issue.lower().startswith("none"):
            errors.append("Gemini audit composition_director.overload_issue reports overcrowding/competing overlays")
    return errors


def classify_audit_result(audit: dict[str, Any], status: str) -> dict[str, Any]:
    audit = normalize_audit_payload(audit)
    checks = audit.get("checks") if isinstance(audit.get("checks"), dict) else {}
    failed_checks = [str(key) for key, value in checks.items() if not bool(value)]
    repairable = set(str(item) for item in policy_get("video_optimization.repairable_checks", []))
    semantic = set(str(item) for item in policy_get("video_optimization.semantic_checks", []))
    hard_fail = set(str(item) for item in policy_get("video_optimization.hard_fail_checks", []))
    issues = [str(item) for item in (audit.get("issues") or []) if str(item).strip()]
    issue_text = " ".join(issues).lower()
    audio_visual_subject_failure = "audio_visual_alignment_safe" in failed_checks and any(
        token in issue_text
        for token in (
            "subject",
            "spoken",
            "visual subject",
            "same subject",
            "mismatch",
            "misaligned",
            "different subject",
            "not the same",
            "跑题",
            "偏题",
            "不一致",
            "不匹配",
            "不是同一个",
        )
    )
    route = "hard_fail"
    if status == "pass":
        route = "none"
    elif any(check in hard_fail for check in failed_checks):
        route = "hard_fail"
    elif any(
        check in semantic
        or check
        in {
            "voiceover_visual_same_subject",
            "topic_specific_visual",
            "content_has_constructive_insight",
            "full_native_video_reviewed",
            "native_video_audio_reviewed",
        }
        for check in failed_checks
    ) or audio_visual_subject_failure:
        route = "content"
    elif "cover_text_safe" in failed_checks:
        route = "cover"
    elif "douyin_safe_area" in failed_checks or "audio_visual_alignment_safe" in failed_checks:
        route = "caption"
    elif any(check in repairable for check in failed_checks):
        route = "storyboard"
    hint_map = policy_get("video_optimization.repair_actions", {})
    hint_value = hint_map.get(route) if isinstance(hint_map, dict) else None
    if isinstance(hint_value, list):
        repair_hint = "; ".join(str(item) for item in hint_value if str(item).strip())
    else:
        repair_hint = str(hint_value or "")
    return {
        "failed_checks": failed_checks,
        "severity": "none" if status == "pass" else "blocking",
        "repair_route": route,
        "repair_hint": repair_hint or "; ".join(issues),
    }


def route_contract_errors(contract_errors: list[str]) -> str:
    joined = " ".join(str(error) for error in contract_errors).lower()
    if any(
        token in joined
        for token in [
            "central visual motion",
            "central_motion_not_caption_or_progress_only",
            "topic_specific_visual",
            "not_cards_only_template",
            "cards-only",
            "generic card",
            "topic-specific",
            "rubric_scores",
            "central_animation_richness",
            "topic_visual_fit",
            "voiceover_visual_same_subject",
            "native_video_audio_reviewed",
            "full_native_video_reviewed",
            "captions_match_spoken_audio",
            "background_music_mix_safe",
            "subject_alignment",
            "audio_track_assessment",
            "spoken subject",
            "visual subject",
            "same subject",
            "audio-visual subject",
            "off-boundary visual template",
            "visual template markers",
            "animation_diagnostics",
            "narrative_structure",
            "scene_pacing",
            "composition_director",
            "composition_not_overcrowded",
            "single_primary_focal_action",
            "no_competing_overlays",
            "topic_visual_not_generic_dashboard",
            "overcrowded",
            "overloaded",
            "competing overlay",
            "generic dashboard",
        ]
    ):
        return "content"
    if any(token in joined for token in ["douyin_safe_area", "caption", "subtitle", "audio_visual_alignment"]):
        return "caption"
    if "cover_text_safe" in joined:
        return "cover"
    return "storyboard"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    parser.add_argument("--video", required=True, help="Rendered MP4 path.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument(
        "--video-input-mode",
        choices=["auto", "file_api", "inline_video", "agent_platform"],
        default="auto",
        help=(
            "Use Gemini Developer Files API, Developer inline native video, or the official "
            "Agent Platform / Vertex Express google-genai SDK path."
        ),
    )
    parser.add_argument("--video-fps", type=float, default=None, help="Optional Gemini videoMetadata FPS for native video analysis.")
    parser.add_argument("--output", help="Output JSON path. Defaults to run_dir/gemini_visual_audit.json.")
    parser.add_argument("--prompt-output", help="Prompt artifact path. Defaults to run_dir/gemini_visual_audit_prompt.json.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    env_file = Path(args.env_file).resolve()
    developer_api_key = first_env(["GEMINI_API_KEY", "GOOGLE_API_KEY"], env_file)
    agent_platform_api_key = first_env(["GOOGLE_AGENT_PLATFORM_API", "GOOGLE_API_KEY"], env_file)
    api_key = first_env(["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_AGENT_PLATFORM_API"], env_file)
    if not api_key:
        raise SystemExit("GEMINI_API_KEY, GOOGLE_API_KEY, or GOOGLE_AGENT_PLATFORM_API is required for scripts/gemini_visual_audit.py")
    model = env_value("SEARCHPO_GEMINI_AUDIT_MODEL", env_file, "gemini-3.5-flash")
    api_mode = default_gemini_mode(env_file)
    video_input_mode = choose_video_input_mode(
        env_file,
        args.video_input_mode,
        api_mode,
        bool(developer_api_key),
        bool(agent_platform_api_key),
    )
    if video_input_mode == "file_api" and not developer_api_key:
        raise SystemExit(
            "Gemini Files API upload requires GEMINI_API_KEY or GOOGLE_API_KEY. "
            f"Current mode is {api_mode} without a developer API key."
        )
    if video_input_mode == "agent_platform" and not agent_platform_api_key:
        raise SystemExit("Agent Platform video audit requires GOOGLE_AGENT_PLATFORM_API or GOOGLE_API_KEY")
    if video_input_mode == "vertex_standard":
        raise SystemExit(
            "Vertex standard video audit requires OAuth/ADC and a project-scoped media URI; "
            "this script only supports Developer API Files/inline or Agent Platform Express SDK native video input."
        )
    if video_input_mode == "inline_video" and api_mode != "developer":
        raise SystemExit(
            "inline_video is only supported through the Gemini Developer API REST path. "
            "For Agent Platform / Vertex Express use --video-input-mode agent_platform."
        )
    request_api_key = (
        developer_api_key
        if video_input_mode in {"file_api", "inline_video"} and developer_api_key
        else agent_platform_api_key
        if video_input_mode == "agent_platform" and agent_platform_api_key
        else api_key
    )
    request_api_mode = "developer" if video_input_mode in {"file_api", "inline_video"} else api_mode
    max_bytes = int(env_value("SEARCHPO_GEMINI_INLINE_VIDEO_MAX_BYTES", env_file, str(18 * 1024 * 1024)))
    video_path = Path(args.video).expanduser()
    if not video_path.is_absolute():
        video_path = ROOT / video_path
    if not video_path.is_file():
        raise SystemExit(f"Rendered video missing: {video_path}")
    output_path = Path(args.output).resolve() if args.output else run_dir / "gemini_visual_audit.json"
    video_size = video_path.stat().st_size
    audit_path = video_path
    audit_media: dict[str, Any] = {
        "mode": "original",
        "original_video_path": str(video_path),
        "original_size_bytes": video_size,
    }
    if video_input_mode == "inline_video":
        audit_path, audit_media = audit_video_path(video_path, run_dir, max_bytes, proxy_dir=output_path.parent)
    mime_type = mimetypes.guess_type(audit_path.name if video_input_mode == "inline_video" else video_path.name)[0] or "video/mp4"
    prompt = build_prompt(run_dir, video_path)
    prompt_path = Path(args.prompt_output).resolve() if args.prompt_output else run_dir / "gemini_visual_audit_prompt.json"
    write_json(
        prompt_path,
        {
            "schema_version": 1,
            "created_at": utc_now(),
            "model": model,
            "video_path": str(video_path),
            "video_sha256": sha256_file(video_path),
            "audit_media": audit_media,
            "video_input_mode": video_input_mode,
            "prompt": prompt,
        },
    )
    uploaded_file: dict[str, Any] | None = None
    if video_input_mode == "file_api":
        uploaded_file = upload_video_file_api(video_path, mime_type, request_api_key, args.timeout)
        parts = [
            {
                "file_data": {
                    "mime_type": str(uploaded_file.get("mime_type") or mime_type),
                    "file_uri": str(uploaded_file.get("uri") or ""),
                }
            },
            {"text": prompt},
        ]
        audit = generated_json(
            model,
            request_api_key,
            parts,
            args.timeout,
            env_file,
            url_override=developer_generate_content_url(model, request_api_key),
        )
    elif video_input_mode == "inline_video":
        video_data = base64.b64encode(audit_path.read_bytes()).decode("ascii")
        video_part: dict[str, Any] = {"inline_data": {"mime_type": mime_type, "data": video_data}}
        video_fps = args.video_fps or float(env_value("SEARCHPO_GEMINI_VIDEO_FPS", env_file, "3"))
        if video_fps > 0:
            video_part["video_metadata"] = {"fps": video_fps}
        audit = generated_json(
            model,
            request_api_key,
            [
                video_part,
                {"text": prompt},
            ],
            args.timeout,
            env_file,
            url_override=developer_generate_content_url(model, request_api_key),
        )
    else:
        video_fps = args.video_fps or float(env_value("SEARCHPO_GEMINI_VIDEO_FPS", env_file, "3"))
        audit = generated_json_agent_platform_sdk(
            model,
            request_api_key,
            video_path,
            mime_type,
            prompt,
            args.timeout,
            video_fps,
        )
    audit = normalize_audit_payload(normalize_audit_object(audit))
    verdict = str(audit.get("verdict") or "").lower()
    checks = audit.get("checks") if isinstance(audit.get("checks"), dict) else {}
    render_payload = read_json(run_dir / "render_payload.json")
    profile = render_payload.get("videoProfile") if isinstance(render_payload.get("videoProfile"), dict) else {}
    expected_orientation = str(render_payload.get("orientation") or profile.get("orientation") or "vertical")
    contract_errors = audit_contract_errors(
        audit,
        expected_orientation=expected_orientation,
        public_subject_text=public_subject_boundary_text(run_dir),
    )
    status_checks = dict(checks)
    if expected_orientation == "horizontal":
        status_checks.pop("douyin_vertical_format", None)
        status_checks.pop("douyin_safe_area", None)
        audit["checks"] = status_checks
        checks = status_checks
    status = "pass" if verdict == "pass" and all(bool(value) for value in status_checks.values()) and not contract_errors else "fail"
    classification = classify_audit_result(audit, status)
    if contract_errors:
        failed = list(dict.fromkeys([*classification.get("failed_checks", []), "audit_contract"]))
        joined_errors = "; ".join(contract_errors)
        classification.update(
            {
                "failed_checks": failed,
                "severity": "blocking",
                "repair_route": route_contract_errors(contract_errors),
                "repair_hint": joined_errors,
            }
        )
    result = {
        "schema_version": 1,
        "created_at": utc_now(),
        "provider": "gemini",
        "model": model,
        "api_mode": request_api_mode,
        "video_input_mode": video_input_mode,
        "uploaded_file": uploaded_file,
        "status": status,
        "video_path": str(video_path),
        "video_sha256": sha256_file(video_path),
        "video_size_bytes": video_size,
        "audit_media": audit_media,
        "prompt_artifact": str(prompt_path),
        "deterministic_visual_audit": str(run_dir / "visual_audit_deterministic.json")
        if (run_dir / "visual_audit_deterministic.json").exists()
        else None,
        "audit": audit,
        "audit_contract_errors": contract_errors,
        **classification,
        "elapsed_reference": time.time(),
    }
    write_json(output_path, result)
    print(json.dumps({"gemini_visual_audit": str(output_path), "status": status}, ensure_ascii=False, indent=2))
    if status != "pass":
        raise SystemExit(f"Gemini visual audit failed: {audit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
