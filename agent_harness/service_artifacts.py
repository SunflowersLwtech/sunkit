from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agent_harness.core import utc_now, write_json
from agent_harness.policy import policy_get


SERVICE_BOUNDARIES = [
    "topic_intake",
    "research",
    "content",
    "visual_planning",
    "asset",
    "render",
    "qa",
    "delivery",
    "analytics_feedback",
]

PLANNING_SCENE_TYPES = {
    "hook",
    "context",
    "problem",
    "explanation",
    "evidence",
    "process",
    "timeline",
    "chart",
    "comparison",
    "quote",
    "summary",
    "cta",
}

RENDER_TO_PLANNING_TYPE = {
    "statement": "hook",
    "context": "context",
    "stat": "chart",
    "bullets": "process",
    "card": "evidence",
    "compare": "comparison",
    "compare_table": "comparison",
    "terminal": "process",
    "flow": "explanation",
    "chart": "chart",
    "code_diff": "explanation",
    "quote": "quote",
    "cta": "cta",
}

REQUIRED_FIELDS = {
    "topic_brief": ["schema_version", "topic", "core_question", "angle", "key_points", "risk_notes"],
    "fact_bank": ["schema_version", "facts", "source_backed_facts", "source_map", "risk_notes"],
    "script": ["schema_version", "title", "structure", "voiceover_segments"],
    "scene_plan": ["schema_version", "scenes", "allowed_planning_scene_types"],
    "video_spec": ["schema_version", "id", "title", "fps", "width", "height", "scenes", "assets"],
    "delivery_package": ["schema_version", "status", "platform_target", "files", "metadata", "artifact_hashes"],
    "analytics_feedback": ["schema_version", "status", "required"],
    "source_map": ["schema_version", "sources"],
    "environment_manifest": ["schema_version", "service_boundaries", "python", "platform", "command"],
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounded_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _host(url: Any) -> str:
    return urlparse(str(url or "")).netloc.lower().removeprefix("www.")


def _source_text(source: dict[str, Any]) -> str:
    if source.get("title"):
        return str(source.get("title"))
    if source.get("description"):
        return str(source.get("description"))
    if source.get("excerpt"):
        return str(source.get("excerpt"))
    if source.get("json") is not None:
        return json.dumps(source.get("json"), ensure_ascii=False)
    return str(source.get("url") or source.get("id") or "")


def build_source_map_artifact(evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    sources = []
    for source in evidence_bundle.get("sources") or []:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("id") or f"source_{len(sources) + 1:03d}")
        sources.append(
            {
                "id": source_id,
                "type": str(source.get("type") or "source"),
                "url": source.get("url"),
                "host": source.get("host") or _host(source.get("url")),
                "title": bounded_text(_source_text(source), 180),
                "sha256": source.get("sha256"),
                "text_chars": int(source.get("text_chars") or 0),
            }
        )
    return validate_service_artifact(
        "source_map",
        {
            "schema_version": 1,
            "created_at": utc_now(),
            "service": "research",
            "sources": sources,
        },
    )


def write_source_map(run_dir: Path, evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    source_map = build_source_map_artifact(evidence_bundle)
    write_json(run_dir / "source_map.json", source_map)
    return source_map


def build_fact_bank_artifact(
    candidate: dict[str, Any],
    evidence_bundle: dict[str, Any],
    supplemental: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    supplemental = supplemental or []
    source_map = build_source_map_artifact(evidence_bundle)["sources"]
    source_ids = [str(source.get("id")) for source in source_map if source.get("id")]
    existing_facts = [str(item) for item in (evidence_bundle.get("evidence_summary") or {}).get("source_facts") or []]
    supplemental_facts = [
        f"{source.get('host') or _host(source.get('url'))}: {bounded_text(_source_text(source), 180)}"
        for source in supplemental
        if source.get("excerpt") or source.get("title") or source.get("url")
    ]
    claims: list[str] = []
    for claim in [*existing_facts, *supplemental_facts]:
        claim = bounded_text(claim, 260)
        if claim and claim not in claims:
            claims.append(claim)
    risk_notes = [
        "Treat supplemental search results as context, not proof of adoption, benchmark rank, funding, or production maturity.",
        "Only claims visible in primary or supplemental extracted text may be used in public copy.",
    ]
    for flag in candidate.get("risk_flags") or []:
        flag_text = str(flag).strip()
        if flag_text and flag_text not in risk_notes:
            risk_notes.append(flag_text)
    facts = []
    for index, claim in enumerate(claims[:16], start=1):
        source_ref = source_ids[min(index - 1, len(source_ids) - 1)] if source_ids else "primary_url"
        confidence = 0.78 if index <= len(existing_facts) else 0.62
        facts.append(
            {
                "id": f"fact_{index:03d}",
                "claim": claim,
                "source_refs": [source_ref],
                "confidence": confidence,
                "risk_flags": [],
                "publishable": True,
            }
        )
    return validate_service_artifact(
        "fact_bank",
        {
            "schema_version": 2,
            "created_at": utc_now(),
            "service": "research",
            "selected_candidate_id": candidate.get("candidate_id"),
            "facts": facts,
            "source_backed_facts": [fact["claim"] for fact in facts],
            "conflicts": [],
            "risk_notes": risk_notes,
            "source_map": source_map,
        },
    )


def build_topic_brief_artifact(
    candidate: dict[str, Any],
    fact_bank: dict[str, Any],
    supplemental: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    supplemental = supplemental or []
    title = bounded_text(candidate.get("title") or "Searchpo topic", 160)
    facts = [str(item) for item in fact_bank.get("source_backed_facts") or []]
    risk_notes = [str(item) for item in fact_bank.get("risk_notes") or []]
    supplemental_hosts = sorted({str(source.get("host") or _host(source.get("url"))) for source in supplemental if source.get("url") or source.get("host")})
    brief = {
        "schema_version": 1,
        "created_at": utc_now(),
        "service": "topic_intake",
        "selected_candidate_id": candidate.get("candidate_id"),
        "topic": title,
        "audience": "Developers, creators, and operators evaluating whether this signal is worth attention.",
        "audience_hint": "Developers, creators, and operators evaluating whether this signal is worth attention.",
        "core_question": f"What concrete problem does {title} appear to address, and what evidence supports that interpretation?",
        "angle": "Lead with the problem, mechanism, architecture position, tradeoff, failure boundary, and judgment framework instead of a generic source summary.",
        "key_points": facts[:5],
        "visual_opportunities": [
            "Show primary source, supplemental sources, and open questions as separate evidence layers.",
            "Use a problem -> mechanism -> architecture position -> failure boundary -> judgment framework scene sequence.",
            "Convert source hosts into a compact source-map card instead of showing raw URLs.",
        ],
        "risk_notes": risk_notes[:8],
        "publish_risks": risk_notes[:8],
        "supplemental_hosts": supplemental_hosts,
    }
    return validate_service_artifact("topic_brief", brief)


def _sentence_segments(text: str) -> list[str]:
    parts = [bounded_text(part, 220) for part in re.split(r"(?<=[。！？!?])\s*", text.strip()) if part.strip()]
    return parts or ([bounded_text(text, 220)] if text.strip() else [])


def build_script_artifact(
    candidate: dict[str, Any],
    polish: dict[str, Any],
    topic_brief: dict[str, Any],
    fact_bank: dict[str, Any],
) -> dict[str, Any]:
    title = bounded_text(polish.get("polished_title") or candidate.get("title"), 90)
    voiceover = bounded_text(polish.get("voiceover_text"), 1100)
    segments = []
    roles = ["hook", "context", "conflict", "explanation", "evidence", "takeaway", "cta"]
    facts = fact_bank.get("facts") or []
    for index, text in enumerate(_sentence_segments(voiceover), start=1):
        role = roles[min(index - 1, len(roles) - 1)]
        source_refs = []
        if facts:
            source_refs = list(facts[min(index - 1, len(facts) - 1)].get("source_refs") or [])
        segments.append({"id": f"v{index}", "role": role, "text": text, "source_refs": source_refs})
    structure = {
        "hook": segments[0]["text"] if segments else "",
        "context": topic_brief.get("core_question") or "",
        "conflict": "What is directly evidenced versus where the mechanism, fit, or failure boundary remains uncertain.",
        "evidence": [fact.get("id") for fact in facts[:5]],
        "takeaway": topic_brief.get("angle") or "",
        "cta": bounded_text(polish.get("douyin_desc") or "", 160),
    }
    return validate_service_artifact(
        "script",
        {
            "schema_version": 1,
            "created_at": utc_now(),
            "service": "content",
            "selected_candidate_id": candidate.get("candidate_id"),
            "title": title,
            "language": "zh-CN",
            "structure": structure,
            "voiceover_text": voiceover,
            "voiceover_segments": segments,
            "source_fact_ids": [fact.get("id") for fact in facts[:8]],
            "video_profile": polish.get("video_profile") or {},
        },
    )


def _scene_text(scene: dict[str, Any]) -> dict[str, Any]:
    props = scene.get("props") if isinstance(scene.get("props"), dict) else {}
    text_values = []
    for value in props.values():
        if isinstance(value, list):
            text_values.extend(str(item) for item in value if str(item).strip())
        elif str(value or "").strip():
            text_values.append(str(value))
    headline = bounded_text(text_values[0] if text_values else scene.get("type"), 80)
    body = bounded_text(" ".join(text_values[1:]), 180)
    return {"headline": headline, "body": body}


def build_scene_plan_artifact(
    candidate: dict[str, Any],
    polish: dict[str, Any],
    script: dict[str, Any],
    fact_bank: dict[str, Any],
) -> dict[str, Any]:
    storyboard = polish.get("storyboard") or {}
    scenes_in = storyboard.get("scenes") if isinstance(storyboard, dict) else []
    voice_segments = script.get("voiceover_segments") or []
    facts = fact_bank.get("facts") or []
    scenes = []
    for index, scene in enumerate(scenes_in or [], start=1):
        if not isinstance(scene, dict):
            continue
        render_type = str(scene.get("type") or "card")
        planning_type = RENDER_TO_PLANNING_TYPE.get(render_type, "summary")
        text = _scene_text(scene)
        voice_ref = voice_segments[min(index - 1, len(voice_segments) - 1)]["id"] if voice_segments else None
        fact_ref = facts[min(index - 1, len(facts) - 1)]["id"] if facts else None
        scenes.append(
            {
                "id": f"s{index}",
                "planning_type": planning_type,
                "render_type": render_type,
                "voiceover_ref": voice_ref,
                "visual_intent": visual_intent_for(planning_type),
                "on_screen_text": text,
                "evidence_refs": [fact_ref] if fact_ref else [],
                "timing_hint": {"weight": scene.get("weight"), "emphasis": scene.get("emphasis") or "normal"},
            }
        )
    if not scenes:
        scenes.append(
            {
                "id": "s1",
                "planning_type": "summary",
                "render_type": "card",
                "voiceover_ref": voice_segments[0]["id"] if voice_segments else None,
                "visual_intent": visual_intent_for("summary"),
                "on_screen_text": {"headline": bounded_text(candidate.get("title"), 80), "body": ""},
                "evidence_refs": [facts[0]["id"]] if facts else [],
                "timing_hint": {"weight": 1.0, "emphasis": "normal"},
            }
        )
    return validate_service_artifact(
        "scene_plan",
        {
            "schema_version": 1,
            "created_at": utc_now(),
            "service": "visual_planning",
            "selected_candidate_id": candidate.get("candidate_id"),
            "allowed_planning_scene_types": sorted(PLANNING_SCENE_TYPES),
            "scenes": scenes[:8],
        },
    )


def visual_intent_for(planning_type: str) -> str:
    return {
        "hook": "Open with a strong statement and visible motion.",
        "context": "Frame why the topic matters without exposing raw URLs.",
        "problem": "Show the viewer pain or adoption risk.",
        "explanation": "Turn the mechanism into a simple readable structure.",
        "evidence": "Show source-backed facts and uncertainty boundaries.",
        "process": "Use step-by-step cards for evaluation or workflow paths.",
        "timeline": "Use sequence markers for change over time.",
        "chart": "Use one prominent number or compact chart-like signal.",
        "comparison": "Separate known facts from open questions.",
        "quote": "Expose a short source-backed quote or paraphrase.",
        "summary": "Compress the key point into a readable scene.",
        "cta": "End with a bounded judgment framework or practical adoption lens.",
    }.get(planning_type, "Use a readable evidence-bounded scene.")


def _scene_frames(total_frames: int, scenes: list[dict[str, Any]]) -> list[int]:
    weights = []
    for scene in scenes:
        raw_weight = (scene.get("timing_hint") or {}).get("weight")
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            weight = 1.0
        weights.append(weight if weight > 0 else 1.0)
    total_weight = sum(weights) or 1.0
    raw = [(weight / total_weight) * total_frames for weight in weights]
    frames = [max(1, int(value)) for value in raw]
    remainder = total_frames - sum(frames)
    index = 0
    while remainder > 0 and frames:
        frames[index % len(frames)] += 1
        remainder -= 1
        index += 1
    while remainder < 0 and len(frames) > 1:
        target = max(range(len(frames)), key=lambda i: frames[i])
        if frames[target] <= 1:
            break
        frames[target] -= 1
        remainder += 1
    return frames


def build_video_spec_artifact(
    run_dir: Path,
    candidate: dict[str, Any],
    render_payload: dict[str, Any],
    scene_plan: dict[str, Any] | None = None,
    source_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    duration = int(render_payload.get("durationInFrames") or 1)
    fps = int(render_payload.get("fps") or 30)
    width = int(render_payload.get("width") or 1080)
    height = int(render_payload.get("height") or 1920)
    aspect_ratio = str(render_payload.get("aspectRatio") or render_payload.get("aspect_ratio") or "9:16")
    orientation = str(render_payload.get("orientation") or ("horizontal" if width > height else "vertical"))
    scenes_in = (scene_plan or {}).get("scenes") or []
    if not scenes_in:
        scenes_in = [
            {
                "id": f"s{index}",
                "planning_type": RENDER_TO_PLANNING_TYPE.get(str(scene.get("type") or ""), "summary"),
                "render_type": scene.get("type"),
                "on_screen_text": _scene_text(scene),
                "evidence_refs": [],
                "timing_hint": {"weight": scene.get("weight")},
            }
            for index, scene in enumerate((render_payload.get("storyboard") or {}).get("scenes") or [], start=1)
            if isinstance(scene, dict)
        ]
    frames = _scene_frames(duration, scenes_in)
    start = 0
    scenes = []
    for scene, frame_count in zip(scenes_in, frames):
        scenes.append(
            {
                **scene,
                "startFrame": start,
                "durationInFrames": frame_count,
            }
        )
        start += frame_count
    assets = [
        {"id": "voiceover", "type": "audio", "path": str(run_dir / "voiceover.wav"), "required": True},
        {"id": "captions", "type": "captions", "path": str(run_dir / "captions.json"), "required": True},
    ]
    spec = {
        "schema_version": 1,
        "created_at": utc_now(),
        "service": "render",
        "id": run_dir.name,
        "selected_candidate_id": candidate.get("candidate_id"),
        "title": render_payload.get("title") or candidate.get("title"),
        "platform_target": "douyin",
        "aspect_ratio": aspect_ratio,
        "orientation": orientation,
        "width": width,
        "height": height,
        "fps": fps,
        "durationInFrames": duration,
        "duration_sec": round(duration / fps, 3) if fps else None,
        "renderer": {"engine": "remotion", "composition": "SearchpoRadar"},
        "storyboard": render_payload.get("storyboard"),
        "agent_visual": {
            "enabled": bool((render_payload.get("agentVisual") or {}).get("enabled")),
            "mode": (render_payload.get("agentVisual") or {}).get("mode"),
            "render_mode": (render_payload.get("agentVisual") or {}).get("render_mode"),
            "description": (render_payload.get("agentVisual") or {}).get("description"),
            "source": (render_payload.get("agentVisual") or {}).get("source"),
            "recipe_scene_count": (render_payload.get("agentVisual") or {}).get("recipe_scene_count"),
        },
        "premium_director_spec": render_payload.get("premiumDirectorSpec")
        or render_payload.get("premium_director_spec")
        or render_payload.get("visualRecipe")
        or render_payload.get("visual_recipe"),
        "video_profile": render_payload.get("videoProfile") or render_payload.get("video_profile") or {},
        "scenes": scenes,
        "assets": assets,
        "source_map_refs": [source.get("id") for source in (source_map or {}).get("sources", [])],
    }
    return validate_service_artifact("video_spec", spec)


def write_environment_manifest(root_dir: Path, run_dir: Path, command: list[str] | None = None) -> dict[str, Any]:
    git_head = ""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root_dir,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        git_head = proc.stdout.strip() if proc.returncode == 0 else ""
    except Exception:
        git_head = ""
    env_keys = [
        "SEARCHPO_E2E_PROFILE",
        "SEARCHPO_AGENT_MODE",
        "SEARCHPO_REMOTION_RENDER_MODE",
        "SEARCHPO_DOUYIN_CHECK_LEVEL",
        "SEARCHPO_DOUYIN_LIVE",
        "ANYSEARCH_API_KEY",
        "DEEPSEEK_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_AGENT_PLATFORM_API",
    ]
    manifest = validate_service_artifact(
        "environment_manifest",
        {
            "schema_version": 1,
            "created_at": utc_now(),
            "service": "runtime_reproducibility",
            "service_boundaries": SERVICE_BOUNDARIES,
            "root_dir": str(root_dir),
            "run_dir": str(run_dir),
            "git": {"head": git_head, "dirty": None},
            "python": {"executable": sys.executable, "version": sys.version.split()[0]},
            "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
            "command": command or sys.argv,
            "env_presence": {key: bool(os.environ.get(key)) for key in env_keys},
        },
    )
    write_json(run_dir / "environment_manifest.json", manifest)
    return manifest


def write_optional_analytics_feedback(run_dir: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    path = run_dir / "analytics_feedback.json"
    if path.exists():
        data = read_json(path)
        return validate_service_artifact("analytics_feedback", data)
    feedback = validate_service_artifact(
        "analytics_feedback",
        {
            "schema_version": 1,
            "created_at": utc_now(),
            "service": "analytics_feedback",
            "selected_candidate_id": candidate.get("candidate_id"),
            "status": "not-collected",
            "required": False,
            "metrics": {},
            "notes": "Optional input for future topic/template optimization; never required for first publish.",
        },
    )
    write_json(path, feedback)
    return feedback


def build_delivery_package_artifact(
    run_dir: Path,
    artifact_manifest: dict[str, Any],
    *,
    status: str,
    publish_status: str,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    errors = errors or []
    files = {
        "video": {
            "path": artifact_manifest.get("final_video_path"),
            "sha256": artifact_manifest.get("final_video_sha256"),
            "bytes": artifact_manifest.get("final_video_bytes"),
        },
        "thumbnail": {
            "path": artifact_manifest.get("cover_path"),
            "sha256": artifact_manifest.get("cover_sha256"),
            "bytes": artifact_manifest.get("cover_bytes"),
        },
        "captions": {"path": str(run_dir / "captions.json"), "sha256": sha256_json_file(run_dir / "captions.json")},
        "source_map": {"path": str(run_dir / "source_map.json"), "sha256": sha256_json_file(run_dir / "source_map.json")},
        "metadata": {"path": str(run_dir / "post" / "douyin_upload_manifest.json"), "sha256": sha256_json_file(run_dir / "post" / "douyin_upload_manifest.json")},
        "render_log": {"path": str(run_dir / "render_input_manifest.json"), "sha256": sha256_json_file(run_dir / "render_input_manifest.json")},
    }
    package = {
        "schema_version": 1,
        "created_at": utc_now(),
        "service": "delivery",
        "run_id": run_dir.name,
        "status": status,
        "publish_status": publish_status,
        "platform_target": "douyin",
        "files": files,
        "metadata": {
            "title": artifact_manifest.get("selected_candidate_title"),
            "selected_candidate_id": artifact_manifest.get("selected_candidate_id"),
            "execution_profile": artifact_manifest.get("execution_profile"),
            "render_mode": artifact_manifest.get("render_mode"),
            "publish_mode": artifact_manifest.get("publish_mode"),
        },
        "artifact_hashes": {
            "artifact_manifest": sha256_json_file(run_dir / "artifact_manifest.json"),
            "topic_brief": sha256_json_file(run_dir / "topic_brief.json"),
            "fact_bank": sha256_json_file(run_dir / "fact_bank.json"),
            "script": sha256_json_file(run_dir / "script.json"),
            "scene_plan": sha256_json_file(run_dir / "scene_plan.json"),
            "video_spec": sha256_json_file(run_dir / "video_spec.json"),
            "render_payload": sha256_json_file(run_dir / "render_payload.json"),
            "environment_manifest": sha256_json_file(run_dir / "environment_manifest.json"),
        },
        "errors": errors,
    }
    return validate_service_artifact("delivery_package", package)


def write_delivery_package(
    run_dir: Path,
    artifact_manifest: dict[str, Any],
    *,
    status: str,
    publish_status: str,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    package = build_delivery_package_artifact(run_dir, artifact_manifest, status=status, publish_status=publish_status, errors=errors)
    write_json(run_dir / "delivery_package.json", package)
    return package


def validate_service_artifact(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_FIELDS.get(kind, []) if field not in data]
    if missing:
        raise ValueError(f"{kind} artifact missing required fields: {', '.join(missing)}")
    if kind == "fact_bank" and not isinstance(data.get("facts"), list):
        raise ValueError("fact_bank.facts must be an array")
    if kind == "scene_plan":
        for scene in data.get("scenes") or []:
            planning_type = str(scene.get("planning_type") or "")
            if planning_type not in PLANNING_SCENE_TYPES:
                raise ValueError(f"scene_plan has unsupported planning_type: {planning_type}")
    if kind == "video_spec" and not data.get("scenes"):
        raise ValueError("video_spec requires at least one scene")
    return data
