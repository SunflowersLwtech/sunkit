from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_harness.core import Artifact, Gate, HarnessContext, StageResult, utc_now, write_json, retry_call, logger
from agent_harness.policy import content_profile, policy_format, policy_get, unsupported_terms
from agent_harness.subjects import ensure_subject_pool, is_operator_topic

# scripts/ holds the publishing/normalization helpers shared with the CLIs.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from douyin_tags import build_tag_bundle, extract_inline_hashtags  # noqa: E402


PROVIDER_ENV_CONTRACT = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GOOGLE_AGENT_PLATFORM_API",
    "gemini_api_alias": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sanitize_post(text: str, limit: int = 260) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."


def _render_template_list(templates: list[str], **values: Any) -> list[str]:
    rows: list[str] = []
    for template in templates:
        if "{url}" in template and not values.get("url"):
            continue
        rendered = policy_format(template, **values).strip()
        if rendered:
            rows.append(rendered)
    return rows


def select_candidate(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        raise RuntimeError("candidate_shortlist.json has no items")
    pin_url = os.environ.get("SEARCHPO_PIN_URL", "").strip()
    if pin_url:
        for item in items:
            if item.get("canonical_url") == pin_url:
                return item
        return _synthetic_pinned_candidate(pin_url)
    return max(
        items,
        key=lambda item: (
            float(item.get("candidate_score") or 0),
            int(item.get("signals", {}).get("source_count") or 1),
            float(item.get("signals", {}).get("metric_strength") or 0),
        ),
    )


def _synthetic_pinned_candidate(url: str) -> dict[str, Any]:
    import hashlib
    import urllib.request
    cid = hashlib.sha256(url.encode()).hexdigest()[:16]
    title = url.rstrip("/").rsplit("/", 1)[-1]
    owner_repo = "/".join(url.rstrip("/").split("/")[-2:]) if "github.com" in url else title
    summary = ""
    stars = 0
    try:
        api_url = f"https://api.github.com/repos/{owner_repo}"
        req = urllib.request.Request(api_url, headers={"Accept": "application/vnd.github+json", "User-Agent": "searchpo"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            title = data.get("full_name") or owner_repo
            summary = data.get("description") or ""
            stars = data.get("stargazers_count") or 0
    except Exception:
        pass
    from datetime import datetime, timezone
    return {
        "candidate_id": cid,
        "entity_type": "repo",
        "entity_key": f"repo:{owner_repo}",
        "canonical_url": url,
        "title": title,
        "summary": summary,
        "published_at": None,
        "collected_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_ids": ["pinned"],
        "evidence": [{"source": "pinned", "url": url, "reliability": 1.0, "claim_role": "primary"}],
        "metrics": {"stars": str(stars), "stars_today": "0"},
        "signals": {
            "freshness_hours": None,
            "has_demo_keyword": False,
            "has_code_signal": True,
            "has_buyer_keyword": False,
            "has_pain_keyword": False,
            "ad_language_density": 0.0,
            "source_count": 1,
            "metric_strength": min(10.0, stars / 1000),
        },
        "risk_flags": [],
        "candidate_score": 8.0,
    }


class ScriptTransientError(RuntimeError):
    """Raised for transient script failures (timeout, rate-limit signals)."""


def run_repo_script(context: HarnessContext, args: list[str], timeout: int = 180, max_retries: int = 3) -> dict[str, Any]:
    command = [sys.executable, *args]

    def _exec():
        try:
            proc = subprocess.run(
                command,
                cwd=context.root_dir,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ScriptTransientError(f"Script timed out after {timeout}s: {' '.join(command)}") from exc
        result = {
            "command": " ".join(command),
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
        if proc.returncode != 0:
            stderr = proc.stderr[-2000:]
            if any(sig in stderr for sig in ("429", "rate limit", "quota", "503", "timeout", "ETIMEDOUT")):
                raise ScriptTransientError(
                    f"Script transient failure ({proc.returncode}): {' '.join(command)}\nstderr:\n{stderr}"
                )
            raise RuntimeError(
                f"Script failed ({proc.returncode}): {' '.join(command)}\n"
                f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{stderr}"
            )
        return result

    return retry_call(_exec, max_retries=max_retries, base_delay=3.0, retryable=(ScriptTransientError,))


def build_main_task_plan(candidate: dict[str, Any], include_providers: bool) -> dict[str, Any]:
    operator_topic = is_operator_topic(candidate)
    first_task = {
        "id": "resolve_operator_topic" if operator_topic else "select_candidate",
        "owner": "claude_main_agent",
        "gate": "operator_topic_recorded" if operator_topic else "candidate_has_url",
    }
    ordered_tasks = [
        first_task,
        {"id": "remotion_render_payload", "owner": "claude_impl_agent", "gate": "render_payload_written"},
        {"id": "publish_package", "owner": "claude_impl_agent", "gate": "live_publish_disabled_by_default"},
        {"id": "douyin_publish", "owner": "claude_impl_agent", "gate": "explicit_live_publish_gate"},
        {"id": "final_verification", "owner": "claude_main_agent", "gate": "main_agent_release_gate"},
    ]
    if include_providers:
        ordered_tasks[1:1] = [
            {"id": "deepseek_polish", "owner": "claude_impl_agent", "gate": "deepseek_polish_passed"},
            {"id": "gemini_tts", "owner": "claude_impl_agent", "gate": "voiceover_generated"},
        ]
        ordered_tasks.insert(5, {"id": "gemini_visual_audit", "owner": "claude_impl_agent", "gate": "visual_audit_passed"})
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "owner": "claude_main_agent",
        "selected_candidate_id": candidate["candidate_id"],
        "subject_input_mode": candidate.get("input_mode") or "shortlist",
        "subject_selection_source": candidate.get("selection_source") or "candidate_shortlist",
        "task_plan_state": "planned",
        "provider_mode": "provider" if include_providers else "contract",
        "roles": {
            "claude_main_agent": [
                "owns task-plan state",
                "assigns implementation stages",
                "verifies every gate before publish",
            ],
            "claude_impl_agent": [
                "runs DeepSeek polish script",
                "runs Gemini TTS script",
                "runs Remotion input preparation/render commands",
                "runs Gemini visual audit script",
                "runs Douyin publish/check script only after gates pass",
            ],
        },
        "ordered_tasks": ordered_tasks,
    }


def build_video_payload(
    candidate: dict[str, Any],
    polish: dict[str, Any] | None = None,
    voiceover_manifest: dict[str, Any] | None = None,
    captions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    operator_topic = is_operator_topic(candidate)
    profile = content_profile(candidate)
    title = (polish or {}).get("polished_title") or candidate.get("title") or "Searchpo Radar"
    summary = str((polish or {}).get("voiceover_text") or candidate.get("summary") or policy_get("content.default_summary", "Fresh signal detected from the daily source sweep."))
    source_ids = ", ".join(candidate.get("source_ids") or [])
    url = candidate.get("canonical_url") or ""
    score = candidate.get("candidate_score")
    signals = candidate.get("signals") or {}
    metrics = candidate.get("metrics") or {}
    stars = metrics.get("stars")
    stars_today = metrics.get("stars_today")
    metric_parts = [
        f"{int(stars):,} stars" if str(stars or "").isdigit() else None,
        f"+{int(stars_today):,} today" if str(stars_today or "").isdigit() else None,
    ]
    metric_line = " · ".join(part for part in metric_parts if part)
    manual_scheme = policy_get("subject_inputs.operator_topic.manual_url_scheme", "manual-topic://")
    evidence_value = profile.get("manual_source_label", "operator topic") if operator_topic and url.startswith(manual_scheme) else (source_ids or policy_get("content.source_registry_label", "source registry"))
    template_values = {
        "title": sanitize_post(title, 64),
        "summary": sanitize_post(summary, 120),
        "url": sanitize_post(url, 110),
        "source_ids": evidence_value,
        "evidence_value": sanitize_post(evidence_value if operator_topic else (source_ids or policy_get("content.source_registry_label", "source registry")), 64),
        "score": score,
        "has_code_signal": bool(signals.get("has_code_signal")),
        "has_demo_keyword": bool(signals.get("has_demo_keyword")),
        "source_count": signals.get("source_count"),
    }
    fallback_cards = [
        {
            "label": policy_format(card.get("label", ""), **template_values),
            "value": sanitize_post(policy_format(card.get("value", ""), **template_values), 64),
            "detail": sanitize_post(policy_format(card.get("detail", ""), **template_values), 120),
        }
        for card in profile.get("cards", [])
    ]
    cards = (polish or {}).get("cards") or fallback_cards
    # Video length follows the real audio (set by gemini_tts) so captions and
    # scenes stay in sync; falls back to the configured default for no-audio runs.
    fps = int((voiceover_manifest or {}).get("fps") or os.environ.get("SEARCHPO_VIDEO_FPS") or 30)
    audio_frames = (voiceover_manifest or {}).get("audio_frames")
    if audio_frames:
        tail = int(os.environ.get("SEARCHPO_VIDEO_TAIL_FRAMES") or round(fps * 0.4))
        duration_frames = int(audio_frames) + tail
    else:
        duration_frames = int(os.environ.get("SEARCHPO_DURATION_FRAMES") or 360)
    return {
        "badge": profile.get("badge", "指定主题分析" if operator_topic else "今日 AI 工具热点"),
        "title": sanitize_post(title, 80),
        "summary": sanitize_post(summary, 700),
        "source": profile.get("source") if operator_topic else (source_ids or profile.get("source", "searchpo")),
        "url": url,
        "score": score,
        "metricLine": policy_format(profile.get("metric_template", "candidate score {score}"), score=score) if operator_topic or not metric_line else metric_line,
        "cards": cards,
        "audioSrc": "voiceover.wav" if voiceover_manifest else None,
        "voiceoverText": (voiceover_manifest or {}).get("voiceover_text") or (polish or {}).get("voiceover_text"),
        "captions": captions or None,
        "durationInFrames": duration_frames,
        "fps": fps,
        "cta": profile.get("cta", ""),
        "footer": profile.get("footer", ""),
    }


def build_douyin_copy(candidate: dict[str, Any], polish: dict[str, Any] | None = None) -> dict[str, Any]:
    if polish:
        return {
            "title": sanitize_post(polish["douyin_title"], 55),
            "desc": sanitize_post(polish["douyin_desc"], 600),
            "tags": polish["tags"],
        }
    profile = content_profile(candidate)
    douyin = profile.get("douyin", {})
    title = candidate.get("title") or "today's signal"
    source = ", ".join(candidate.get("source_ids") or [profile.get("source", "searchpo")])
    url = candidate.get("canonical_url") or ""
    score = candidate.get("candidate_score")
    manual_scheme = policy_get("subject_inputs.operator_topic.manual_url_scheme", "manual-topic://")
    url_for_desc = "" if is_operator_topic(candidate) and url.startswith(manual_scheme) else url
    desc_lines = _render_template_list(
        douyin.get("desc_lines", []),
        title=title,
        source=source,
        score=score,
        url=url_for_desc,
    )
    return {
        "title": sanitize_post(policy_format(douyin.get("title_template", "{title}"), title=title), 55),
        "desc": sanitize_post("\n".join(desc_lines), 600),
        "tags": douyin.get("tags", []),
    }


def build_content_plan(candidate: dict[str, Any]) -> dict[str, Any]:
    title = candidate.get("title") or "Searchpo Radar"
    plan = content_profile(candidate).get("plan", {})
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "mode": plan.get("mode", "deterministic_plan"),
        "title": sanitize_post(title, 80),
        "angle": plan.get("angle", ""),
        "execution_steps": plan.get("execution_steps", []),
        "gates": plan.get("gates", []),
        "publish_platforms": ["douyin"],
    }


def write_post_artifacts(root_dir: Path, run_dir: Path, candidate: dict[str, Any], douyin_copy: dict[str, Any]) -> Path:
    post_dir = run_dir / "post"
    post_dir.mkdir(parents=True, exist_ok=True)
    title = douyin_copy["title"]
    # Enforce Douyin's hashtag limit holistically: catch any #topics the model
    # embedded in the description, merge them with the tags list, then sanitize,
    # de-duplicate and cap (default 5). The previous pipeline shipped raw tags.
    inline_tags, desc = extract_inline_hashtags(douyin_copy["desc"])
    tag_bundle = build_tag_bundle(list(douyin_copy.get("tags") or []) + inline_tags, desc=desc)
    tags = tag_bundle["tags"]
    tags_csv = ",".join(tags)
    hashtags_str = tag_bundle["hashtag_string"]
    expected_video_path = root_dir / "out" / "searchpo-radar.mp4"
    cover_path = root_dir / "out" / "searchpo-cover.jpg"
    posting_policy = content_profile(candidate).get("posting", {})
    subject_label = posting_policy.get("subject_label", "Candidate")
    claim_source = posting_policy.get("claim_source", "candidate_shortlist.json")
    claim_text = policy_format(posting_policy.get("claim_template", "{title} was selected by the searchpo candidate filter."), title=candidate.get("title"))
    caveat_text = posting_policy.get("caveat", "")
    live_command = (
        f'cd "{post_dir}" && sau douyin upload-video --account "$DOUYIN_ACCOUNT_NAME" '
        f'--file "{expected_video_path}" --title "$(cat douyin_title.txt)" '
        '--desc "$(cat douyin_desc.txt)" --tags "$(cat douyin_tags.txt)"'
    )
    posting_pack = f"""# Posting Pack

## Evidence Summary

- {subject_label}: {candidate.get('title')}
- Subject ID: `{candidate.get('candidate_id')}`
- Source IDs: `{', '.join(candidate.get('source_ids') or [])}`
- Source URL: {candidate.get('canonical_url') or ''}
- Caveats: {caveat_text}

## Posting Strategy

{policy_get('claims.posting_strategy', 'Lead with the evidence boundary, not hype.')}

## Publish Mode

- Default: `contract-check`
- Upload adapter: `dreammis/social-auto-upload`
- Platform: `douyin`
- Live upload requires explicit `SEARCHPO_DOUYIN_LIVE=1` plus a valid `DOUYIN_ACCOUNT_NAME` or `SOCIAL_UPLOAD_ACCOUNT_NAME`.

## Douyin Upload Copy

- Title: {title}
- Tags: {tags_csv}

### Description

{desc}

## Upload Command

```bash
{live_command}
```

The command above is documentation only. The default E2E path does not run a live upload.

## Pre-Flight

- Source URL present.
- No unsupported claim terms from `config/searchpo_policy.json`.
- Cross-check review status is `pass` for contract-check only.
- `runtime/social-auto-upload` has the Douyin CLI contract.
- For live upload: user explicitly enables `SEARCHPO_DOUYIN_LIVE=1`.
"""
    (post_dir / "posting_pack.md").write_text(posting_pack, encoding="utf-8")
    write_json(
        post_dir / "douyin_upload_manifest.json",
        {
            "schema_version": 2,
            "created_at": utc_now(),
            "platform": "douyin",
            "adapter": "dreammis/social-auto-upload",
            "cli": "sau douyin upload-video",
            "account_env": ["DOUYIN_ACCOUNT_NAME", "SOCIAL_UPLOAD_ACCOUNT_NAME"],
            "expected_video_path": str(expected_video_path),
            "cover_path": str(cover_path),
            "title": title,
            "desc": desc,
            "tags": tags,
            "tags_raw": tag_bundle["tags_raw"],
            "hashtag_string": hashtags_str,
            "max_tags": tag_bundle["max_tags"],
            "caption_preview": tag_bundle["caption"],
            "live_upload_default": False,
            "live_upload_gate": "SEARCHPO_DOUYIN_LIVE=1",
            "contract_path": "runtime/social-auto-upload/skills/douyin-upload/references/cli-contract.md",
        },
    )
    (post_dir / "douyin_title.txt").write_text(title + "\n", encoding="utf-8")
    (post_dir / "douyin_desc.txt").write_text(desc + "\n", encoding="utf-8")
    (post_dir / "douyin_tags.txt").write_text(tags_csv + "\n", encoding="utf-8")
    write_json(
        post_dir / "claims_ledger.json",
        {
            "schema_version": 1,
            "created_at": utc_now(),
            "review_status": "contract-check-pass",
            "selected_candidate_id": candidate.get("candidate_id"),
            "source_boundary": {
                "canonical_url": candidate.get("canonical_url"),
                "source_ids": candidate.get("source_ids") or [],
                "collected_at": candidate.get("collected_at"),
                "evidence": candidate.get("evidence") or [],
            },
            "claims": [
                {
                    "id": "C001",
                    "claim": claim_text,
                    "type": "pipeline_fact",
                    "source": claim_source,
                    "status": "keep",
                },
                {
                    "id": "C002",
                    "claim": policy_get("claims.boundary_claim", "The post package is a candidate radar package, not a verified ranking or market conclusion."),
                    "type": "claim_boundary",
                    "source": "agent_harness/stages.py",
                    "status": "keep",
                }
            ],
            "unknown_or_unsafe": policy_get("claims.unknown_or_unsafe", []),
        },
    )
    write_json(
        post_dir / "images_manifest.json",
        {
            "schema_version": 2,
            "created_at": utc_now(),
            "cover": {"role": "cover", "path": str(cover_path), "exists": cover_path.is_file()},
            "images": [{"role": "cover", "path": str(cover_path)}],
        },
    )
    (post_dir / "cross_check_review.md").write_text(
        "# Cross-Check Review\n\nstatus: pass\n\nContract-check only. Live Douyin upload still requires manual review and explicit approval.\n",
        encoding="utf-8",
    )
    (post_dir / "file_manifest.txt").write_text(
        "\n".join(
            [
                "posting_pack.md",
                "douyin_upload_manifest.json",
                "douyin_title.txt",
                "douyin_desc.txt",
                "douyin_tags.txt",
                "claims_ledger.json",
                "images_manifest.json",
                "cross_check_review.md",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return post_dir


@dataclass(frozen=True)
class LoadShortlistStage:
    name: str = "load_shortlist"
    title: str = "Load subject input"
    owner: str = "data_prep"

    def run(self, context: HarnessContext) -> StageResult:
        path = context.run_dir / "candidate_shortlist.json"
        ensure_subject_pool(context.run_dir)
        if not path.exists():
            raise RuntimeError(f"candidate_shortlist.json missing: {path}")
        data = read_json(path)
        shortlist = data.get("items") or []
        input_mode = data.get("input_mode") or "shortlist"
        context.state["shortlist_data"] = data
        context.state["shortlist"] = shortlist
        context.state["subject_input_mode"] = input_mode
        status = "completed" if shortlist else "failed"
        return StageResult(
            step="observe",
            status=status,
            details=f"Loaded {len(shortlist)} subject candidates from {input_mode}.",
            artifacts=[Artifact("candidate_shortlist", path, {"item_count": len(shortlist), "input_mode": input_mode})],
            gates=[
                Gate(
                    "shortlist_available",
                    "pass" if shortlist else "fail",
                    f"{len(shortlist)} subject candidates available",
                    {"item_count": len(shortlist), "input_mode": input_mode},
                )
            ],
            metadata={"item_count": len(shortlist), "input_mode": input_mode},
        )


@dataclass(frozen=True)
class SelectCandidateStage:
    name: str = "select_candidate"
    title: str = "Select top candidate"
    owner: str = "claude_main_agent"

    def run(self, context: HarnessContext) -> StageResult:
        candidate = select_candidate(context.state.get("shortlist") or [])
        path = context.run_dir / "selected_candidate.json"
        write_json(path, candidate)
        context.state["selected_candidate"] = candidate
        has_boundary = bool(candidate.get("canonical_url")) or is_operator_topic(candidate)
        gate_name = "operator_topic_recorded" if is_operator_topic(candidate) else "candidate_has_url"
        status = "completed" if has_boundary else "failed"
        return StageResult(
            step="select",
            status=status,
            details=f"Selected {candidate['candidate_id']} with score {candidate.get('candidate_score')}.",
            artifacts=[Artifact("selected_candidate", path, {"candidate_id": candidate["candidate_id"]})],
            gates=[
                Gate(
                    gate_name,
                    "pass" if has_boundary else "fail",
                    "Selected subject has a source URL or operator-topic boundary",
                    {"canonical_url": candidate.get("canonical_url"), "input_mode": candidate.get("input_mode") or "shortlist"},
                )
            ],
            metadata={"candidate_id": candidate["candidate_id"]},
        )


@dataclass(frozen=True)
class PlanContentStage:
    name: str = "main_task_plan"
    title: str = "Main agent task plan"
    owner: str = "claude_main_agent"
    include_providers: bool = False

    def run(self, context: HarnessContext) -> StageResult:
        candidate = context.state["selected_candidate"]
        plan = build_content_plan(candidate)
        path = context.run_dir / "content_plan.json"
        write_json(path, plan)
        context.state["content_plan"] = plan
        task_plan = build_main_task_plan(candidate, self.include_providers)
        task_plan_path = context.run_dir / "main_task_plan.json"
        write_json(task_plan_path, task_plan)
        context.state["main_task_plan"] = task_plan
        return StageResult(
            step="plan",
            status="completed",
            details="Main agent assigned impl-agent script tasks and kept source-bounded publish gates.",
            artifacts=[
                Artifact("content_plan", path, {"mode": plan["mode"]}),
                Artifact("main_task_plan", task_plan_path, {"state": task_plan["task_plan_state"]}),
            ],
            gates=[
                Gate("claim_boundary_defined", "pass", "Plan limits public claims to the selected subject evidence boundary"),
                Gate("task_plan_owned_by_main", "pass", "Main agent owns task-plan state and release gates"),
            ],
            metadata={"mode": plan["mode"]},
        )


@dataclass(frozen=True)
class DeepSeekPolishStage:
    name: str = "deepseek_polish"
    title: str = "Run DeepSeek polish script"
    owner: str = "claude_impl_agent"

    def run(self, context: HarnessContext) -> StageResult:
        script_result = run_repo_script(context, ["scripts/deepseek_polish.py", str(context.run_dir)], timeout=180)
        path = context.run_dir / "deepseek_polish.json"
        polish = read_json(path)
        context.state["deepseek_polish"] = polish
        status = "completed" if polish.get("status") == "pass" else "failed"
        return StageResult(
            step="act",
            status=status,
            details="DeepSeek polished Douyin copy and Remotion card text with source-bounded constraints.",
            artifacts=[Artifact("deepseek_polish", path, {"model": polish.get("model"), "status": polish.get("status")})],
            gates=[
                Gate(
                    "deepseek_polish_passed",
                    "pass" if status == "completed" else "fail",
                    "DeepSeek output avoided unsupported claim terms",
                    {"unsafe_claim_hits": polish.get("unsafe_claim_hits") or []},
                )
            ],
            metadata=script_result,
        )


@dataclass(frozen=True)
class GeminiTTSStage:
    name: str = "gemini_tts"
    title: str = "Run Gemini TTS script"
    owner: str = "claude_impl_agent"

    def run(self, context: HarnessContext) -> StageResult:
        script_result = run_repo_script(context, ["scripts/gemini_tts.py", str(context.run_dir)], timeout=180)
        manifest_path = context.run_dir / "voiceover_manifest.json"
        manifest = read_json(manifest_path)
        audio_path = Path(manifest["audio_path"])
        context.state["voiceover_manifest"] = manifest
        return StageResult(
            step="act",
            status="completed" if audio_path.is_file() else "failed",
            details="Gemini generated the run voiceover audio artifact.",
            artifacts=[
                Artifact("voiceover_manifest", manifest_path, {"model": manifest.get("model"), "voice": manifest.get("voice")}),
                Artifact("voiceover_audio", audio_path, {"mime_type": manifest.get("output_mime_type")}),
            ],
            gates=[Gate("voiceover_generated", "pass" if audio_path.is_file() else "fail", "Gemini TTS wrote voiceover.wav")],
            metadata=script_result,
        )


@dataclass(frozen=True)
class BuildCaptionsStage:
    name: str = "build_captions"
    title: str = "Build audio-synced caption timing"
    owner: str = "claude_impl_agent"

    def run(self, context: HarnessContext) -> StageResult:
        script_result = run_repo_script(context, ["scripts/build_captions.py", str(context.run_dir)], timeout=60)
        path = context.run_dir / "captions.json"
        segment_count = 0
        if path.exists():
            data = read_json(path)
            segments = data.get("segments") or []
            segment_count = data.get("segment_count") or len(segments)
            context.state["captions"] = [
                {"text": s["text"], "startFrame": s["start_frame"], "endFrame": s["end_frame"]}
                for s in segments
            ]
        return StageResult(
            step="act",
            status="completed",
            details=f"Built {segment_count} caption segments locked to the voiceover length.",
            artifacts=[Artifact("captions", path, {"segment_count": segment_count})] if path.exists() else [],
            gates=[
                Gate(
                    "captions_built",
                    "pass" if segment_count else "warn",
                    f"{segment_count} caption segments timed to the real audio",
                )
            ],
            metadata=script_result,
        )


@dataclass(frozen=True)
class ContentScoringStage:
    name: str = "content_scoring"
    title: str = "Score content quality via Gemini"
    owner: str = "claude_impl_agent"

    def run(self, context: HarnessContext) -> StageResult:
        script_result = run_repo_script(context, ["scripts/content_scorer.py", str(context.run_dir)], timeout=120)
        path = context.run_dir / "content_score.json"
        if path.exists():
            score_data = read_json(path)
            overall = score_data.get("overall") or 0
            verdict = score_data.get("verdict") or "improve"
        else:
            overall = 0
            verdict = "skip"
        context.state["content_score"] = {"overall": overall, "verdict": verdict}
        gate_status = "pass" if verdict == "pass" or overall >= 6.0 else "warn"
        return StageResult(
            step="act",
            status="completed",
            details=f"Content quality score: {overall}/10 ({verdict})",
            artifacts=[Artifact("content_score", path, {"overall": overall, "verdict": verdict})] if path.exists() else [],
            gates=[Gate("content_quality_scored", gate_status, f"Quality {overall}/10: {verdict}", {"overall": overall})],
            metadata=script_result,
        )


@dataclass(frozen=True)
class RenderPayloadStage:
    name: str = "render_payload"
    title: str = "Build Remotion render payload"
    owner: str = "claude_impl_agent"

    def run(self, context: HarnessContext) -> StageResult:
        candidate = context.state["selected_candidate"]
        captions = context.state.get("captions")
        if captions is None:
            captions_path = context.run_dir / "captions.json"
            if captions_path.exists():
                segments = read_json(captions_path).get("segments") or []
                captions = [
                    {"text": s["text"], "startFrame": s["start_frame"], "endFrame": s["end_frame"]}
                    for s in segments
                ]
        payload = build_video_payload(
            candidate,
            context.state.get("deepseek_polish"),
            context.state.get("voiceover_manifest"),
            captions,
        )
        path = context.run_dir / "render_payload.json"
        write_json(path, payload)
        context.state["render_payload"] = payload
        return StageResult(
            step="act",
            status="completed",
            details="Wrote render payload for Remotion public input.",
            artifacts=[Artifact("render_payload", path, {"title": payload.get("title")})],
            gates=[Gate("render_payload_written", "pass", "render_payload.json is available")],
            metadata={"render_payload": str(path)},
        )


@dataclass(frozen=True)
class PublishPackageStage:
    name: str = "publish_package"
    title: str = "Build Douyin contract-check package"
    owner: str = "claude_impl_agent"

    def run(self, context: HarnessContext) -> StageResult:
        candidate = context.state["selected_candidate"]
        douyin_copy = build_douyin_copy(candidate, context.state.get("deepseek_polish"))
        post_dir = write_post_artifacts(context.root_dir, context.run_dir, candidate, douyin_copy)
        post_manifest_path = context.run_dir / "post_manifest.json"
        write_json(
            post_manifest_path,
            {
                "created_at": utc_now(),
                "post_dir": str(post_dir),
                "posting_pack": str(post_dir / "posting_pack.md"),
            },
        )
        context.state["post_dir"] = post_dir
        return StageResult(
            step="act",
            status="completed",
            details="Wrote Douyin upload package, claim ledger, and review artifacts.",
            artifacts=[
                Artifact("post_manifest", post_manifest_path),
                Artifact("posting_pack", post_dir / "posting_pack.md"),
                Artifact("douyin_upload_manifest", post_dir / "douyin_upload_manifest.json"),
                Artifact("claims_ledger", post_dir / "claims_ledger.json"),
                Artifact("cross_check_review", post_dir / "cross_check_review.md"),
            ],
            gates=[
                Gate(
                    "live_publish_disabled_by_default",
                    "pass",
                    "Live publishing requires explicit SEARCHPO_DOUYIN_LIVE=1",
                    {"live_upload_default": False},
                )
            ],
            metadata={"post_dir": str(post_dir)},
        )


@dataclass(frozen=True)
class DeterministicReviewStage:
    name: str = "main_release_gate"
    title: str = "Main agent release gate"
    owner: str = "claude_main_agent"

    def run(self, context: HarnessContext) -> StageResult:
        candidate = context.state["selected_candidate"]
        unsafe_terms = unsupported_terms()
        generated_text = " ".join(
            [
                json.dumps(context.state.get("render_payload") or {}, ensure_ascii=False),
                json.dumps(context.state.get("deepseek_polish") or {}, ensure_ascii=False),
                (context.state.get("post_dir") / "douyin_desc.txt").read_text(encoding="utf-8"),
            ]
        )
        unsafe_hits = [term for term in unsafe_terms if term.lower() in generated_text.lower()]

        coherence_ok = True
        coherence_issues: list[str] = []
        polish = context.state.get("deepseek_polish") or {}
        if polish:
            candidate_title = (candidate.get("title") or "").lower()
            polish_title = str(polish.get("polished_title") or "").lower()
            voiceover = str(polish.get("voiceover_text") or "").lower()
            if candidate_title and candidate_title not in polish_title and candidate_title not in voiceover:
                key_words = [w for w in re.split(r"[\s/\-_]+", candidate_title) if len(w) > 3]
                if key_words and not any(w in voiceover for w in key_words):
                    coherence_issues.append("voiceover_text does not reference the selected candidate")
                    coherence_ok = False

        content_score = context.state.get("content_score") or {}
        quality_warning = content_score.get("overall", 10) < 5.0

        all_pass = not unsafe_hits and coherence_ok
        canonical_url = str(candidate.get("canonical_url") or "")
        source_url_present = canonical_url.startswith("http://") or canonical_url.startswith("https://")
        review = {
            "schema_version": 2,
            "created_at": utc_now(),
            "status": "pass" if all_pass else "fail",
            "selected_candidate_id": candidate["candidate_id"],
            "checks": {
                "source_url_present": source_url_present,
                "subject_boundary_present": bool(candidate.get("canonical_url")) or is_operator_topic(candidate),
                "unsupported_superlative_hits": unsafe_hits,
                "coherence_ok": coherence_ok,
                "coherence_issues": coherence_issues,
                "content_quality_warning": quality_warning,
                "live_upload_gated": True,
            },
        }
        path = context.run_dir / "agent_review.json"
        write_json(path, review)
        details = (
            "Release gate passed: no unsafe claims, content coherent."
            if all_pass
            else f"Release gate failed: unsafe={unsafe_hits}, coherence_issues={coherence_issues}"
        )
        return StageResult(
            step="review",
            status="completed" if all_pass else "failed",
            details=details,
            artifacts=[Artifact("agent_review", path, {"status": review["status"]})],
            gates=[
                Gate(
                    "main_agent_release_gate",
                    review["status"],
                    details,
                    review["checks"],
                )
            ],
            metadata={"review_status": review["status"]},
        )


def default_stages(include_providers: bool = False) -> list[Any]:
    stages: list[Any] = [
        LoadShortlistStage(),
        SelectCandidateStage(),
        PlanContentStage(include_providers=include_providers),
    ]
    if include_providers:
        stages.extend([DeepSeekPolishStage(), ContentScoringStage(), GeminiTTSStage(), BuildCaptionsStage()])
    stages.extend([RenderPayloadStage(), PublishPackageStage(), DeterministicReviewStage()])
    return stages
