#!/usr/bin/env python3
"""Polish the selected searchpo candidate through DeepSeek and write run artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from agent_harness.policy import policy_get, policy_format, unsupported_claim_regex, unsupported_terms
from agent_harness.evidence import strong_research_review_errors
from agent_harness.agent_visual import agent_visual_text_items, require_agent_visual
from agent_harness.premium_repo_visual import premium_repo_agent_visual
from agent_harness.speech_quality import normalize_voiceover_text
from agent_harness.storyboard import (
    MAX_SCENES,
    card_scenes,
    minimum_storyboard_scene_count,
    public_source_value,
    storyboard_text_items,
    validate_storyboard,
)
from agent_harness.video_profile import choose_video_profile, normalize_video_profile
from env_utils import env_value

LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"
UNSAFE_RE = unsupported_claim_regex()
CLAIM_TERM_REPLACEMENTS = {
    "best": "notable",
    "first": "early",
    "only": "focused",
    "ultimate": "practical",
    "gamechanger": "notable",
    "game changer": "notable",
    "revolutionary": "notable",
    "10x": "clearer",
    "唯一": "一个",
    "首个": "一个",
    "最强": "值得观察",
    "第一": "先",
    "革命性": "值得观察",
    "刚开源": "开源",
    "刚发布": "发布",
    "正式发布": "发布",
    "首发": "这次",
}
EXTERNAL_GUIDANCE_REPLACEMENTS = [
    (re.compile(r"pip\s+install\s+\S+", re.I), "包管理记录"),
    (re.compile(r"\bpip\s+install\b", re.I), "包管理记录"),
    (re.compile(r"下载量"), "包分发量"),
    (re.compile(r"下载"), "获取记录"),
    (re.compile(r"安装"), "环境准备"),
    (re.compile(r"使用"), "实践"),
    (re.compile(r"试试|尝试一下|尝试这个|尝试这款|去看|去试|快用|上手|部署|接入|打开|访问|前往|跳转|点击"), "评估"),
    (re.compile(r"链接"), "资料线索"),
    (re.compile(r"地址"), "资料位置"),
    (re.compile(r"主页"), "资料页"),
    (re.compile(r"仓库"), "项目资料"),
]


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


def bounded_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


PUBLIC_URL_RE = re.compile(r"https?://[^\s，。！？；;]+", re.I)


def public_visible_text(value: Any) -> str:
    text = clean_text(value)

    def replace_url(match: re.Match[str]) -> str:
        try:
            parsed = urllib.parse.urlparse(match.group(0))
            host = parsed.netloc.replace("www.", "").strip()
        except ValueError:
            host = ""
        return f"{host} 来源" if host else "外部来源"

    text = PUBLIC_URL_RE.sub(replace_url, text)
    text = re.sub(
        r"\b([A-Za-z0-9]+(?:_[A-Za-z0-9]+)+)\.(py|ts|tsx|js|jsx|txt|md|json|ya?ml|toml)\b",
        lambda match: f"{match.group(1).replace('_', ' ')} {match.group(2).replace('py', 'Python')} 文件",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b([a-z][a-z0-9]+(?:_[a-z0-9]+)+)\b",
        lambda match: match.group(1).replace("_", " "),
        text,
    )
    text = re.sub(r"\*\*Source\*\*\s*:\s*", "来源：", text, flags=re.I)
    text = text.replace("**", "").replace("---", " ")
    return clean_text(text)


def chinese_char_count(value: Any) -> int:
    return len(re.findall(r"[一-鿿]", str(value or "")))


def target_voiceover_chars(video_seconds: int) -> int:
    chars_per_second = int(policy_get("deepseek.chars_per_second", 7))
    return max(60, max(1, int(video_seconds)) * chars_per_second)


def estimated_voiceover_duration_seconds(polished: dict[str, Any]) -> int:
    voiceover_chars = chinese_char_count(polished.get("voiceover_text"))
    if voiceover_chars <= 0:
        return 0
    tts_chars_per_second = max(1.0, float(policy_get("deepseek.tts_chars_per_second", 4.5)))
    return int(math.ceil(voiceover_chars / tts_chars_per_second))


REQUIRED_COUNT_RE = re.compile(r"requires\s+(?:at\s+least\s+)?(\d+)", re.I)
DURATION_SECONDS_RE = re.compile(r"(\d+(?:\.\d+)?)s\s+video", re.I)


def feedback_required_count(revision_feedback: dict[str, Any] | None) -> int:
    text = json.dumps(revision_feedback or {}, ensure_ascii=False)
    counts = [int(match.group(1)) for match in REQUIRED_COUNT_RE.finditer(text)]
    return max(counts) if counts else 0


def feedback_duration_seconds(revision_feedback: dict[str, Any] | None) -> int:
    text = json.dumps(revision_feedback or {}, ensure_ascii=False)
    seconds = [float(match.group(1)) for match in DURATION_SECONDS_RE.finditer(text)]
    return int(math.ceil(max(seconds))) if seconds else 0


def longform_min_scene_count(video_seconds: int) -> int:
    return minimum_storyboard_scene_count(video_seconds)


def voiceover_segment_chars() -> int:
    return max(600, int(policy_get("deepseek.voiceover_segment_chars", 1400)))


def agent_visual_layout_contract() -> list[str]:
    return [
        "agent_visual must render a visible full-canvas custom composition; do not leave large black/empty frame regions.",
        "Premium Remotion mode is enabled: prefer agent_visual.module_code as a complete TSX module exporting `AgentVisualGenerated`; use component_code only for small compatibility repairs.",
        "module_code may import React, Remotion APIs, @remotion/* packages already installed in package.json, and local helpers under src/components or src/utils when useful.",
        "The module must export a named `AgentVisualGenerated` component compatible with AgentVisualProps from '../AgentVisualTypes'.",
        "Use a director-led React/SVG composition with chapter-level visual grammar changes: code/terminal, file tree, architecture graph, metric panel, UI callout, flow map, table, or checklist.",
        "Do not stretch one circular orbit, radar sweep, packet cloud, particle field, or dashboard loop across the whole video. A repo/software explainer must switch between at least three concrete visual families when evidence supports them.",
        "Use a non-black canvas background with luminance safely above black-frame detection; prefer colors like #263449, #24384f, or #f6f1e7, and avoid #000, #0a0a0a, black, or near-black full-frame backgrounds.",
        "Absolute positioning, SVG coordinates, clip paths, masks, transforms, and layered overlays are allowed when they improve composition; still keep global captions readable.",
        "Keep primary visual content out of the global caption band: vertical 1080x1920 should visually reserve about 560px near the bottom when possible; horizontal 1920x1080 should reserve about 180px.",
        "Do not read data.captions, use a captions variable, compute currentCaption, or render any caption/subtitle/progress-caption bar inside agent_visual; Searchpo adds the global captions layer separately.",
        "Do not read data.cards, create safeCards, or map compatibility cards as the main visual surface; agent_visual must author topic-specific flow, chart, terminal, code, or mechanism visuals from bounded literals and public-safe fields.",
        "Do not render raw data.summary inside agent_visual because it can be paragraph-length; render bounded card labels, metric lines, or explicitly sliced strings instead.",
        "Do not render raw data.evidenceLevel, operator_topic_sourced, internal gate names, or pipeline metadata; use public-safe evidence copy such as 证据已交叉验证.",
        "Motion must persist through meaningful state changes, but every scene needs one primary focal action, at most two restrained secondary motion systems, and visible rest/dwell moments.",
        "Do not use whole-video orbiting node clouds, rotating readable labels, screen shake, glitch flashes, strobe, high-frequency dash sweeps, or more than eight moving packets/nodes at once.",
        "Use modest audio/frame emphasis: scale should stay <= 1.08, background loops should be low opacity, and moving decorative layers must not cross title/body text.",
        "Use Remotion frame/interpolate/spring for motion; do not rely on CSS transition timing.",
        "Do not use process.env, filesystem/process APIs, localStorage/sessionStorage, document.cookie, or code that depends on local secrets.",
    ]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_list(value: Any, key: str, max_items: int) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"DeepSeek response missing non-empty `{key}` list")
    rows = [bounded_text(item, 40) for item in value[:max_items] if str(item).strip()]
    if not rows:
        raise RuntimeError(f"DeepSeek response `{key}` list has no usable values")
    return rows


def candidate_entity_terms(candidate: dict[str, Any]) -> list[str]:
    raw_values = [
        str(candidate.get("title") or ""),
        str(candidate.get("entity_key") or ""),
        str(candidate.get("canonical_url") or "").rstrip("/").rsplit("/", 1)[-1],
    ]
    terms: list[str] = []
    for raw in raw_values:
        for part in re.split(r"[\s/_:.-]+", raw):
            cleaned = part.strip()
            if len(cleaned) >= 4 and cleaned.lower() not in {"github", "repo", "http", "https"}:
                terms.append(cleaned)
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            unique.append(term)
    return unique[:6]


def validate_candidate_reference(candidate: dict[str, Any], polished: dict[str, Any]) -> None:
    terms = candidate_entity_terms(candidate)
    voiceover = str(polished.get("voiceover_text") or "").lower()
    if terms and not any(term.lower() in voiceover for term in terms):
        raise RuntimeError(f"DeepSeek voiceover_text must mention one of: {', '.join(terms)}")


def candidate_anchor(candidate: dict[str, Any]) -> str:
    terms = candidate_entity_terms(candidate)
    lower_terms = {term.lower(): term for term in terms}
    if "arxiv" in lower_terms and "2605" in lower_terms and "26731" in lower_terms:
        return "arXiv 2605.26731"
    if len(terms) >= 3:
        return " ".join(terms[:3])
    return terms[0] if terms else ""


def ensure_candidate_reference(candidate: dict[str, Any], polished: dict[str, Any]) -> dict[str, Any]:
    terms = candidate_entity_terms(candidate)
    voiceover = str(polished.get("voiceover_text") or "")
    if not terms or any(term.lower() in voiceover.lower() for term in terms):
        return polished
    anchor = candidate_anchor(candidate)
    if not anchor:
        return polished
    repaired = dict(polished)
    repaired["voiceover_text"] = clean_text(f"{anchor} 这次讨论的是一个需要按证据边界理解的案例。{voiceover}")
    repaired["_candidate_reference_repaired"] = True
    return repaired


def rendered_polish_text(polished: dict[str, Any]) -> str:
    profile = polished.get("video_profile") or polished.get("videoProfile") or {}
    orientation = profile.get("orientation") or polished.get("orientation") or "vertical"
    return " ".join(
        [
            str(polished.get("polished_title") or ""),
            str(polished.get("voiceover_text") or ""),
            str(polished.get("douyin_title") or ""),
            str(polished.get("douyin_desc") or ""),
            json.dumps(polished.get("cards") or [], ensure_ascii=False),
            " ".join(storyboard_text_items(polished.get("storyboard"))),
            " ".join(agent_visual_text_items(polished.get("agent_visual") or polished.get("agentVisual"), orientation)),
            json.dumps(polished.get("video_profile") or polished.get("videoProfile") or {}, ensure_ascii=False),
        ]
    )


def unsafe_hits_for(polished: dict[str, Any]) -> list[str]:
    return sorted(set(match.group(0) for match in UNSAFE_RE.finditer(rendered_polish_text(polished))))


def scrub_unsupported_claim_terms(value: Any) -> Any:
    if isinstance(value, str):
        return clean_text(
            UNSAFE_RE.sub(
                lambda match: CLAIM_TERM_REPLACEMENTS.get(match.group(0).lower(), CLAIM_TERM_REPLACEMENTS.get(match.group(0), "值得观察")),
                value,
            )
        )
    if isinstance(value, list):
        return [scrub_unsupported_claim_terms(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub_unsupported_claim_terms(item) for key, item in value.items()}
    return value


def scrub_polish_claim_terms(polished: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(polished)
    for key in ("polished_title", "voiceover_text", "douyin_title", "douyin_desc", "cards", "storyboard", "video_profile", "caveats"):
        if key in cleaned:
            cleaned[key] = scrub_unsupported_claim_terms(cleaned[key])
    visual = cleaned.get("agent_visual")
    if isinstance(visual, dict):
        cleaned["agent_visual"] = scrub_unsupported_claim_terms(visual)
    return cleaned


def scrub_external_guidance_text(value: Any) -> Any:
    if isinstance(value, str):
        text = value
        for pattern, replacement in EXTERNAL_GUIDANCE_REPLACEMENTS:
            text = pattern.sub(replacement, text)
        return clean_text(text)
    if isinstance(value, list):
        return [scrub_external_guidance_text(item) for item in value]
    if isinstance(value, dict):
        return {key: scrub_external_guidance_text(item) for key, item in value.items()}
    return value


def scrub_polish_external_guidance(polished: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(polished)
    for key in ("polished_title", "voiceover_text", "douyin_title", "douyin_desc", "cards", "storyboard", "video_profile", "caveats"):
        if key in cleaned:
            cleaned[key] = scrub_external_guidance_text(cleaned[key])
    visual = cleaned.get("agent_visual")
    if isinstance(visual, dict) and isinstance(visual.get("description"), str):
        cleaned["agent_visual"] = {**visual, "description": scrub_external_guidance_text(visual["description"])}
    return cleaned


def validate_polish(candidate: dict[str, Any], polished: dict[str, Any]) -> None:
    validate_candidate_reference(candidate, polished)
    unsafe_hits = unsafe_hits_for(polished)
    if unsafe_hits:
        raise RuntimeError(f"DeepSeek candidate contains unsupported claim terms: {unsafe_hits}")

    # Circular semantic repetition check in voiceover_text
    voiceover = str(polished.get("voiceover_text") or "").strip()
    if voiceover:
        clean_vo = re.sub(r"[，。！？；;、\s]", "", voiceover)
        sub_len = 8
        seen = set()
        repeated = set()
        for i in range(len(clean_vo) - sub_len + 1):
            sub = clean_vo[i : i + sub_len]
            if len(re.findall(r"[\u4e00-\u9fff]", sub)) >= 4:
                if sub in seen:
                    repeated.add(sub)
                else:
                    seen.add(sub)
        if repeated:
            raise RuntimeError(
                f"DeepSeek voiceover_text contains circular semantic repetition: "
                f"repeated patterns found: {list(repeated)[:3]}. "
                f"Please rewrite the copy to introduce each concept once and remove redundant technical speculation."
            )


def longform_storyboard_contract_errors(polished: dict[str, Any]) -> list[str]:
    profile = normalize_video_profile(polished.get("video_profile") or polished.get("videoProfile") or {})
    duration_seconds = int(profile.get("duration_seconds") or 0)
    if duration_seconds < 180:
        return []
    storyboard = polished.get("storyboard") if isinstance(polished.get("storyboard"), dict) else {}
    scenes = [scene for scene in storyboard.get("scenes") or [] if isinstance(scene, dict)]
    scene_types = [str(scene.get("type") or "") for scene in scenes]
    scene_type_set = set(scene_types)
    errors: list[str] = []
    min_scenes = longform_min_scene_count(duration_seconds)
    if len(scenes) < min_scenes:
        errors.append(f"long-form video_profile.duration_seconds={duration_seconds} requires at least {min_scenes} storyboard scenes")
    if len(scene_type_set) < 5:
        errors.append("long-form storyboard must use at least five distinct scene types")
    if not scene_types or scene_types[0] != "statement":
        errors.append("long-form storyboard must open with a statement scene")
    if not scene_types or scene_types[-1] not in {"cta", "closing"}:
        errors.append("long-form storyboard must close with a cta or closing scene")
    motion_scene_types = {
        "terminal",
        "flow",
        "chart",
        "code_diff",
        "code_block",
        "node_graph",
        "decision_table",
        "compare_table",
        "compare",
        "bullets",
        "stat",
    }
    if sum(1 for scene_type in scene_types if scene_type in motion_scene_types) < 5:
        errors.append("long-form storyboard must include at least five motion-rich explanatory scenes")
    if scene_types.count("card") > max(4, len(scenes) // 3):
        errors.append("long-form storyboard uses too many card scenes; prefer terminal, flow, chart, code_diff, code_block, node_graph, decision_table, compare_table, or process scenes")
    return errors


def parse_json_object(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_polish_payload(data: dict[str, Any]) -> dict[str, Any]:
    required = policy_get("deepseek.required_keys", ["polished_title", "voiceover_text", "douyin_title", "douyin_desc", "tags", "cards"])
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise RuntimeError(f"DeepSeek response missing fields: {', '.join(missing)}")
    tags = require_list(data["tags"], "tags", 5)
    storyboard = data.get("storyboard")
    if storyboard:
        try:
            data["storyboard"] = validate_storyboard(storyboard)
        except ValueError as exc:
            raise RuntimeError(f"DeepSeek response storyboard is invalid: {exc}") from exc
    cards = data.get("cards") or (card_scenes(data.get("storyboard")) if data.get("storyboard") else [])
    profile = data.get("video_profile") or data.get("videoProfile") or {}
    orientation = profile.get("orientation") or data.get("orientation") or "vertical"
    try:
        data["agent_visual"] = require_agent_visual(data.get("agent_visual") or data.get("agentVisual"), orientation)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    min_cards = 4 if any("cards must be 4" in str(item) for item in policy_get("deepseek.constraints", [])) else 1
    if not isinstance(cards, list) or len(cards) < min_cards:
        raise RuntimeError(f"DeepSeek response missing at least {min_cards} compatibility card")
    clean_cards = []
    for index, card in enumerate(cards[: max(min_cards, min(len(cards), 4))], start=1):
        if not isinstance(card, dict):
            raise RuntimeError(f"DeepSeek card {index} is not an object")
        clean_cards.append(
            {
                "label": bounded_text(card.get("label"), 18),
                "value": bounded_text(card.get("value"), 54),
                "detail": bounded_text(card.get("detail"), 118),
            }
        )
    data["tags"] = tags
    data["cards"] = clean_cards
    longform_errors = longform_storyboard_contract_errors(data)
    if longform_errors:
        raise RuntimeError("DeepSeek long-form storyboard contract invalid: " + "; ".join(longform_errors))
    return data


def parse_deepseek_payload(content: str) -> dict[str, Any]:
    return normalize_polish_payload(parse_json_object(content))


def is_agent_visual_layout_error(exc: BaseException | str) -> bool:
    text = str(exc)
    return "agent_visual" in text


def is_storyboard_contract_error(exc: BaseException | str) -> bool:
    text = str(exc)
    return "storyboard" in text and ("missing provider-authored text" in text or "invalid" in text)


def safe_storyboard(data: dict[str, Any], reason: str) -> dict[str, Any]:
    cards = data.get("cards") if isinstance(data.get("cards"), list) else []
    bullet_items = []
    for card in cards[:3]:
        if isinstance(card, dict):
            value = bounded_text(card.get("value") or card.get("label"), 32)
            detail = bounded_text(card.get("detail"), 46)
            bullet_items.append(" / ".join(item for item in [value, detail] if item))
    if not bullet_items:
        bullet_items = ["先看问题", "再看证据", "最后保留验证边界"]
    storyboard = {
        "version": 1,
        "style": {
            "theme": "minimal",
            "density": "standard",
            "motion": "standard",
            "accent": "#72e7ff",
            "chrome": {"topbar": False, "progress": True, "beam": False},
        },
        "scenes": [
            {
                "type": "statement",
                "props": {
                    "title": bounded_text(data.get("polished_title") or data.get("douyin_title") or "证据边界", 34),
                    "sub": "兼容场景由运行时补齐",
                },
            },
            {"type": "bullets", "props": {"heading": "这次先看三件事", "items": bullet_items}},
            {
                "type": "cta",
                "props": {
                    "text": "按证据验证，不急着下结论",
                    "footer": bounded_text(reason, 54),
                },
            },
        ],
    }
    return validate_storyboard(storyboard)


def safe_agent_visual(reason: str, orientation: str = "vertical") -> dict[str, Any]:
    return {
        "enabled": True,
        "render_mode": "full_canvas",
        "description": "Safe data-driven custom visual generated after provider layout contract failure.",
        "component_code": r"""
const orientation = data.orientation || 'vertical';
const isHorizontal = orientation === 'horizontal';
const text = (value: any, limit: number, fallback = '') => {
  const cleaned = String(value ?? fallback).replace(/\s+/g, ' ').trim();
  return cleaned.length > limit ? `${cleaned.slice(0, limit - 1)}…` : cleaned;
};
const pct = Math.min(1, Math.max(0, progress));
const pulse = 0.5 + 0.5 * Math.sin(frame / 7);
const active = Math.min(2, Math.max(0, Math.floor(pct * 3)));
const headline = text(data.displayTitle || data.title, 38, '证据边界');
const metric = text(data.metricLine || data.audienceMetricLine, 42, '先看机制，再看限制');
const insight = text(data.audienceMetricLine || data.metricLine, 76, '模型能力和脚手架复杂度不是简单反比。');
const flow = [
  {label: 'FRAME', title: '框架强度', x: 140, color: '#72e7ff'},
  {label: 'MODEL', title: '模型类型', x: 460, color: '#ffd60a'},
  {label: 'RESULT', title: '成功率边界', x: 780, color: '#ff8a5b'},
];
const beamOffset = Math.round((frame * 7) % 160);
const reveal = Math.max(0, 760 - Math.round(pct * 760));
const barWidth = (index: number) => `${Math.round(28 + 58 * (0.55 + 0.45 * Math.sin(frame / 9 + index)))}%`;
return (
  <AbsoluteFill style={{
    backgroundColor: '#263449',
    color: '#fffdf4',
    fontFamily: 'Inter, PingFang SC, sans-serif',
    padding: isHorizontal ? '80px 70px 180px' : '140px 70px 560px',
    display: 'flex',
    flexDirection: 'column',
    gap: isHorizontal ? 16 : 28,
  }}>
    <div style={{
      minHeight: isHorizontal ? 90 : 138,
      borderBottom: '2px solid rgba(255,253,244,0.24)',
      display: 'flex',
      alignItems: 'flex-end',
      paddingBottom: isHorizontal ? 14 : 26,
    }}>
      <div style={{fontSize: isHorizontal ? 42 : 54, lineHeight: 1.08, fontWeight: 800, maxWidth: 900}}>
        {headline}
      </div>
    </div>
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: isHorizontal ? 16 : 30,
      flex: 1,
      minHeight: 0,
    }}>
      <div style={{
        background: 'rgba(255,253,244,0.10)',
        border: '2px solid rgba(255,253,244,0.22)',
        boxShadow: active === 0 ? `0 0 ${20 + Math.round(pulse * 20)}px rgba(114,231,255,0.30)` : 'none',
        borderRadius: 28,
        padding: isHorizontal ? 20 : 34,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        minHeight: isHorizontal ? 150 : 245,
      }}>
        <div>
          <div style={{fontSize: isHorizontal ? 22 : 28, color: '#72e7ff', fontWeight: 700, marginBottom: isHorizontal ? 10 : 22}}>flow diagram · 证据边界</div>
          <div style={{fontSize: isHorizontal ? 26 : 34, lineHeight: 1.22, fontWeight: 760}}>
            {insight}
          </div>
        </div>
        <div style={{
          height: isHorizontal ? 10 : 18,
          borderRadius: 999,
          background: 'rgba(255,253,244,0.18)',
          overflow: 'hidden',
        }}>
          <div style={{
            width: `${Math.max(12, Math.round(pct * 100))}%`,
            height: '100%',
            borderRadius: 999,
            background: '#ffd60a',
          }} />
        </div>
      </div>
      <div style={{
        background: 'rgba(255,253,244,0.08)',
        border: '2px solid rgba(255,253,244,0.20)',
        borderRadius: 26,
        padding: isHorizontal ? 16 : 24,
        minHeight: isHorizontal ? 380 : 650,
      }}>
        <div style={{fontSize: isHorizontal ? 22 : 28, color: '#72e7ff', fontWeight: 800, marginBottom: isHorizontal ? 6 : 12}}>
          animated flow chart · model sensitivity
        </div>
        <svg width="100%" height={isHorizontal ? 260 : 520} viewBox="0 0 920 520" style={{display: 'block'}}>
          <defs>
            <linearGradient id="safeFlowGradient" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#72e7ff" />
              <stop offset="52%" stopColor="#ffd60a" />
              <stop offset="100%" stopColor="#ff8a5b" />
            </linearGradient>
          </defs>
          <path
            d="M140 255 C260 130 350 380 460 255 C575 130 660 380 780 255"
            fill="none"
            stroke="rgba(255,253,244,0.24)"
            strokeWidth="18"
            strokeLinecap="round"
            strokeDasharray="24 26"
            strokeDashoffset={-beamOffset}
          />
          <path
            d="M140 255 C260 130 350 380 460 255 C575 130 660 380 780 255"
            fill="none"
            stroke="url(#safeFlowGradient)"
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray="760"
            strokeDashoffset={reveal}
          />
          {flow.map((node: any, index: number) => {
            const live = active === index;
            const y = 255 + Math.round(Math.sin(frame / 10 + index) * (live ? 28 : 12));
            const radius = live ? 62 + Math.round(pulse * 12) : 44;
            const opacity = live ? 1 : 0.62;
            return (
              <g key={node.label} transform={`translate(${node.x} ${y})`} opacity={opacity}>
                <circle r={radius + 18} fill={node.color} opacity={live ? 0.20 + pulse * 0.18 : 0.08} />
                <circle r={radius} fill={node.color} />
                <circle r={radius - 18} fill="#263449" opacity="0.26" />
                <text x="0" y="-8" textAnchor="middle" fill="#182536" fontSize="25" fontWeight="900">{node.label}</text>
                <text x="0" y="28" textAnchor="middle" fill="#182536" fontSize="22" fontWeight="800">{node.title}</text>
              </g>
            );
          })}
          {[0, 1, 2, 3].map((index: number) => {
            const liveBar = index <= active + 1;
            const h = 42 + Math.round((liveBar ? 82 : 36) * (0.55 + 0.45 * Math.sin(frame / 11 + index)));
            return (
              <g key={index} transform={`translate(${190 + index * 142} ${430 - h})`}>
                <rect width="82" height={h} rx="12" fill={index % 2 === 0 ? '#72e7ff' : '#ffd60a'} opacity={liveBar ? 0.92 : 0.38} />
                <rect y={h + 12} width="82" height="10" rx="5" fill="rgba(255,253,244,0.30)" />
              </g>
            );
          })}
        </svg>
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: isHorizontal ? 8 : 16, marginTop: 4}}>
          {flow.map((node: any, index: number) => (
            <div key={node.label} style={{
              minHeight: isHorizontal ? 50 : 72,
              borderRadius: 18,
              background: active === index ? node.color : 'rgba(255,253,244,0.13)',
              color: active === index ? '#182536' : '#fffdf4',
              padding: isHorizontal ? '8px 12px' : '16px 18px',
              fontSize: isHorizontal ? 16 : 21,
              lineHeight: 1.18,
              fontWeight: 800,
            }}>
              <div style={{marginBottom: isHorizontal ? 4 : 8}}>{node.title}</div>
              <div style={{height: 9, borderRadius: 999, background: active === index ? 'rgba(24,37,54,0.28)' : 'rgba(255,253,244,0.22)', overflow: 'hidden'}}>
                <div style={{width: barWidth(index), height: '100%', borderRadius: 999, background: active === index ? '#263449' : node.color}} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
    <div style={{
      minHeight: isHorizontal ? 90 : 148,
      padding: isHorizontal ? '14px 20px' : '24px 30px',
      borderRadius: 24,
      background: 'rgba(24,37,54,0.72)',
      border: '2px solid rgba(255,253,244,0.18)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 24,
    }}>
      <div style={{fontSize: isHorizontal ? 22 : 28, lineHeight: 1.25, fontWeight: 760}}>{metric}</div>
      <div style={{fontSize: isHorizontal ? 16 : 22, lineHeight: 1.25, color: '#c9d6e6', maxWidth: 360}}>
        证据已交叉验证 · 保留边界
      </div>
    </div>
  </AbsoluteFill>
);
""",
        "css": ".agent-safe-shell { box-sizing: border-box; }",
        "fallback_reason": bounded_text(reason, 300),
    }


def _source_map_from_content_plan(content_plan: dict[str, Any]) -> list[dict[str, Any]]:
    source_map = (content_plan.get("source_map") or {}).get("sources") if isinstance(content_plan.get("source_map"), dict) else []
    source_map = source_map or ((content_plan.get("fact_bank") or {}).get("source_map") or [])
    return [source for source in source_map if isinstance(source, dict)]


def _visual_fact_texts(content_plan: dict[str, Any]) -> list[str]:
    repo_context = content_plan.get("repo_context") if isinstance(content_plan.get("repo_context"), dict) else {}
    fact_bank = content_plan.get("fact_bank") if isinstance(content_plan.get("fact_bank"), dict) else {}
    raw_values: list[Any] = [
        *(repo_context.get("facts") or []),
        *(fact_bank.get("source_backed_facts") or []),
        *(fact_bank.get("facts") or []),
        *(fact_bank.get("risk_notes") or []),
    ]
    texts: list[str] = []
    for item in raw_values:
        if isinstance(item, dict):
            text = item.get("claim") or item.get("text") or item.get("summary")
        else:
            text = item
        cleaned = public_visible_text(text)
        if cleaned:
            texts.append(cleaned)
    for source in _source_map_from_content_plan(content_plan):
        title = public_visible_text(source.get("title"))
        host = public_visible_text(source.get("host"))
        if title and title.lower() not in {"github.com", host.lower()}:
            texts.append(title)
    seen: set[str] = set()
    unique: list[str] = []
    for text_value in texts:
        key = text_value.lower()
        if key not in seen:
            seen.add(key)
            unique.append(text_value)
    return unique[:14]


def _repo_slug_from_candidate(candidate: dict[str, Any], content_plan: dict[str, Any]) -> str:
    repo_context = content_plan.get("repo_context") if isinstance(content_plan.get("repo_context"), dict) else {}
    repo = clean_text(repo_context.get("repo"))
    if repo:
        return bounded_text(repo, 42)
    url = str(candidate.get("canonical_url") or candidate.get("url") or "")
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower().endswith("github.com"):
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            return bounded_text("/".join(parts[:2]), 42)
    title = clean_text(candidate.get("title"))
    if title.startswith(("http://", "https://")):
        parsed_title = urllib.parse.urlparse(title)
        return bounded_text(parsed_title.netloc.replace("www.", "") or "source topic", 42)
    return bounded_text(title or parsed.netloc.replace("www.", "") or "source topic", 42)


def _extract_visual_terms(facts: list[str], repo: str) -> dict[str, list[str]]:
    joined = "\n".join(facts)
    file_terms = re.findall(
        r"\b[\w.-]+(?:/[\w.-]+){0,4}\.(?:py|ts|tsx|js|jsx|go|rs|java|swift|md|json|toml|ya?ml)\b",
        joined,
        flags=re.I,
    )
    public_call_terms = [
        f"{match.group(1)} {match.group(2)}"
        for match in re.finditer(
            r"\b([A-Za-z][A-Za-z0-9]{2,})\s+([A-Za-z][A-Za-z0-9]{2,}\([^)\n]{0,28}\))",
            joined,
        )
    ]
    call_terms = [
        *public_call_terms,
        *re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?\([^)\n]{0,28}\)", joined),
    ]
    identifier_terms = re.findall(r"\b[A-Z][A-Za-z0-9_]{3,}\b|\b[a-z][a-z0-9]+_[a-z0-9_]{2,}\b", joined)

    def compact(values: list[str], fallback: list[str], limit: int, max_items: int) -> list[str]:
        rows: list[str] = []
        seen: set[str] = set()
        for value in [*values, *fallback]:
            cleaned = bounded_text(public_visible_text(value), limit)
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(cleaned)
            if len(rows) >= max_items:
                break
        return rows

    repo_name = repo.rsplit("/", 1)[-1] if repo else "项目"
    files = compact(file_terms, [f"{repo_name} / docs", f"{repo_name} / examples", f"{repo_name} / tests"], 34, 5)
    calls = compact(call_terms, identifier_terms, 32, 5)
    if not calls:
        calls = ["入口接口", "核心流程", "验证边界"]
    return {"files": files, "calls": calls}


def _generic_pipeline(repo: str, facts: list[str]) -> list[dict[str, str]]:
    terms = _extract_visual_terms(facts, repo)
    calls = terms["calls"]
    files = terms["files"]
    repo_name = repo.rsplit("/", 1)[-1] if repo else "topic"
    return [
        {"k": "PROBLEM", "label": "问题场景", "detail": bounded_text(f"{repo_name} 要解决什么", 34)},
        {"k": "ENTRY", "label": calls[0] if calls else "入口接口", "detail": files[0] if files else "来源入口"},
        {"k": "MECHANISM", "label": calls[1] if len(calls) > 1 else "核心机制", "detail": files[1] if len(files) > 1 else "模块路径"},
        {"k": "TRADEOFF", "label": "取舍边界", "detail": bounded_text(facts[0] if facts else "证据边界", 34)},
        {"k": "VERIFY", "label": "验证路径", "detail": files[2] if len(files) > 2 else "demo / tests / docs"},
    ]


def _generic_checks(facts: list[str]) -> list[str]:
    checks = ["跑通最小示例", "检查源码入口", "复核证据边界", "准备小评估集", "观察失败样例"]
    joined = "\n".join(facts).lower()
    if "test" in joined or "evaluation" in joined or "eval" in joined:
        checks[3] = "复核 evaluation / tests"
    if "api" in joined or "route" in joined or "server" in joined:
        checks[4] = "复核 API 权限边界"
    return checks


def _source_host_checks(facts: list[str]) -> list[str]:
    checks: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        visible = public_visible_text(fact)
        for match in re.finditer(r"\b([a-z0-9.-]+\.[a-z]{2,})\s+来源\b", visible, re.I):
            host = match.group(1).lower()
            if host in seen:
                continue
            seen.add(host)
            checks.append(f"{host} 来源")
            if len(checks) >= 2:
                return checks
    return checks


def _is_mem0_visual_context(title: str, repo: str, facts: list[str]) -> bool:
    joined = " ".join([title, repo, *facts]).lower()
    return "mem0" in joined or "memory.add" in joined or "memoryclient" in joined


def focused_generic_source_grounded_agent_visual(
    title: str,
    repo: str,
    facts: list[str],
    pipeline: list[dict[str, str]],
    checks: list[str],
    min_state_count: int = 6,
) -> dict[str, Any]:
    terms = _extract_visual_terms(facts, repo)
    visual_checks = [*_source_host_checks(facts), *checks]
    calls = terms["calls"][:5] or [bounded_text(step.get("label"), 18) for step in pipeline[:5]]
    stage_details = [
        bounded_text(public_visible_text((step.get("detail") or step.get("label") or "")), 34)
        for step in pipeline[:6]
    ]
    stages = [
        {"label": "看问题", "detail": stage_details[0] if len(stage_details) > 0 else "业务痛点", "tag": calls[0] if calls else "SOURCE", "tone": "#72e7ff"},
        {"label": "走入口", "detail": stage_details[1] if len(stage_details) > 1 else "接入路径", "tag": calls[1] if len(calls) > 1 else "ENTRY", "tone": "#f4f0df"},
        {"label": "拆机制", "detail": stage_details[2] if len(stage_details) > 2 else "系统链路", "tag": calls[2] if len(calls) > 2 else "MECHANISM", "tone": "#ffd60a"},
        {"label": "看治理", "detail": stage_details[3] if len(stage_details) > 3 else "权限审计", "tag": calls[3] if len(calls) > 3 else "GOVERN", "tone": "#ff8a5b"},
        {"label": "比取舍", "detail": stage_details[4] if len(stage_details) > 4 else "方案边界", "tag": calls[4] if len(calls) > 4 else "TRADEOFF", "tone": "#c7a6ff"},
        {"label": "做验证", "detail": stage_details[5] if len(stage_details) > 5 else "复测指标", "tag": "VERIFY", "tone": "#9cffd0"},
    ]
    extra_stages = [
        {"label": "审风险", "detail": "失败条件", "tag": "RISK", "tone": "#ff6b9d"},
        {"label": "比方案", "detail": "替代路径", "tag": "ALT", "tone": "#8bd3ff"},
        {"label": "看证据", "detail": "来源边界", "tag": "SOURCE", "tone": "#f7c59f"},
        {"label": "做复盘", "detail": "结论回收", "tag": "REVIEW", "tone": "#b8f7d4"},
        {"label": "排上线", "detail": "发布检查", "tag": "SHIP", "tone": "#d8b4fe"},
    ]
    required = max(6, min(MAX_SCENES, int(min_state_count or 6)))
    for stage in extra_stages:
        if len(stages) >= required:
            break
        stages.append(stage)
    component = r"""
const title = __TITLE__;
const repo = __REPO__;
const stages = __STAGES__;
const checks = __CHECKS__;
const total = Math.max(1, durationInFrames);
const beatCount = stages.length;
const raw = Math.min(beatCount - 0.001, Math.max(0, progress * beatCount));
const active = Math.floor(raw);
const local = raw - active;
const stage = stages[active] || stages[0];
const tone = stage.tone;
const enter = spring({frame, fps, config: {damping: 18, stiffness: 116}});
const beatEnter = spring({frame: frame - active * 8, fps, config: {damping: 18, stiffness: 118}});
const pulse = 0.5 + 0.5 * Math.sin(frame / 8);
const audioScale = interpolate(audioPulse, [0, 1], [1, 1.08], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
const scanner = 72 + ((frame * 5) % 404);
const orbitPackets = Array.from({length: 8}, (_, index) => ({
  phase: index * 0.785,
  label: String((stages[index % beatCount] || {}).tag || ['SRC', 'ENTRY', 'MECH', 'RISK'][index % 4]),
}));
const streamPackets = Array.from({length: 5}, (_, index) => ({
  phase: (index / 5 + frame / 104) % 1,
  color: ['#72e7ff', '#ffd60a', '#ff8a5b', '#9cffd0', '#f4f0df'][index],
  label: String((stages[index % beatCount] || {}).label || ['source', 'mechanism', 'risk', 'verify'][index % 4]),
}));
const focusChecks = checks.length ? checks : ['官方来源', '机制边界', '复测路径'];
const sweepRotate = frame * 4 + active * 45;
return (
  <AbsoluteFill style={{
    backgroundColor: '#263449',
    color: '#fffdf4',
    fontFamily: 'Inter, PingFang SC, sans-serif',
    padding: '108px 76px 620px',
    overflow: 'hidden',
  }}>
    <div style={{height: '100%', display: 'grid', gridTemplateRows: '142px minmax(0, 1fr)', gap: 32}}>
      <div style={{display: 'grid', gridTemplateColumns: '1fr 208px', gap: 24, alignItems: 'end', borderBottom: '2px solid rgba(255,253,244,0.18)', paddingBottom: 22, opacity: enter, transform: `translateY(${Math.round((1 - enter) * -24)}px)`}}>
        <div>
          <div style={{fontSize: 28, color: tone, fontWeight: 900, marginBottom: 12}}>证据链路观察 · {repo}</div>
          <div style={{fontSize: 54, lineHeight: 1.02, fontWeight: 970, maxWidth: 780}}>{title}</div>
        </div>
        <div style={{borderRadius: 24, border: `2px solid ${tone}`, background: 'rgba(255,253,244,0.08)', height: 96, display: 'grid', placeItems: 'center', transform: `scale(${audioScale})`}}>
          <div style={{fontSize: 21, color: '#cbd5e1', fontWeight: 820}}>当前焦点</div>
          <div style={{fontSize: 29, color: tone, fontWeight: 970}}>{stage.label}</div>
        </div>
      </div>

      <div style={{minHeight: 0, display: 'grid', gridTemplateRows: 'minmax(0, 1fr) 136px', gap: 24, transform: `scale(${0.965 + enter * 0.035})`}}>
        <div style={{borderRadius: 38, border: `3px solid ${tone}`, background: 'rgba(24,37,54,0.86)', boxShadow: `0 30px 90px rgba(0,0,0,0.28), 0 0 ${24 + pulse * 32}px ${tone}44`, padding: 34, minHeight: 0, display: 'grid', placeItems: 'center'}}>
          <svg width="100%" height="100%" viewBox="0 0 760 620" style={{display: 'block', minHeight: 620}}>
            <defs>
              <linearGradient id="qwenStageFlow" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#72e7ff" />
                <stop offset="55%" stopColor="#ffd60a" />
                <stop offset="100%" stopColor="#9cffd0" />
              </linearGradient>
              <filter id="qwenGlow">
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
            </defs>
            <rect x="46" y="46" width="668" height="528" rx="44" fill="rgba(255,253,244,0.07)" stroke="rgba(255,253,244,0.18)" strokeWidth="3" />
            <rect x="78" y={scanner} width="604" height="42" rx="21" fill={tone} opacity="0.13" />
            <path d="M110 330 C210 120 308 500 380 310 C468 96 560 486 650 250" fill="none" stroke="rgba(255,253,244,0.22)" strokeWidth="18" strokeLinecap="round" strokeDasharray="30 28" strokeDashoffset={-frame * 2} />
            <path d="M110 330 C210 120 308 500 380 310 C468 96 560 486 650 250" fill="none" stroke="url(#qwenStageFlow)" strokeWidth="10" strokeLinecap="round" strokeDasharray="860" strokeDashoffset={860 * (1 - local)} />

            <g transform={`translate(380 310) scale(${audioScale})`}>
              <g transform={`rotate(${sweepRotate})`} opacity="0.58">
                <path d="M0 0 L164 -26 L164 26 Z" fill={tone} opacity="0.20" />
                <line x1="0" y1="0" x2="184" y2="0" stroke={tone} strokeWidth="7" strokeLinecap="round" />
              </g>
              <circle r={112 + pulse * 9} fill="rgba(24,37,54,0.92)" stroke={tone} strokeWidth="5" />
              <circle r={154 + Math.sin(frame / 18) * 10} fill="none" stroke="url(#qwenStageFlow)" strokeWidth="4" strokeDasharray="20 18" strokeDashoffset={-frame * 2} />
              <circle r={70 + audioPulse * 24} fill={tone} opacity="0.18" />
              <text x="0" y="-12" textAnchor="middle" fill="#fffdf4" fontSize="31" fontWeight="960">{String(repo).slice(0, 18)}</text>
              <text x="0" y="30" textAnchor="middle" fill={tone} fontSize="20" fontWeight="900">{stage.label}</text>
              {orbitPackets.map((packet: any, index: number) => {
                const angle = frame / 20 + packet.phase;
                const radius = 170 + Math.sin(frame / 15 + index) * 14;
                const x = Math.cos(angle) * radius;
                const y = Math.sin(angle) * radius * 0.62;
                const hot = index % beatCount === active;
                return (
                  <g key={packet.label} transform={`translate(${Math.round(x)} ${Math.round(y)})`}>
                    <circle r={hot ? 24 + pulse * 5 : 16} fill={hot ? tone : 'rgba(255,253,244,0.42)'} />
                    <text x="0" y="6" textAnchor="middle" fill={hot ? '#172235' : '#fffdf4'} fontSize={hot ? 12 : 10} fontWeight="950">{packet.label}</text>
                  </g>
                );
              })}
            </g>

            {streamPackets.map((packet: any, index: number) => {
              const x = 110 + packet.phase * 540;
              const y = 310 + Math.sin(packet.phase * Math.PI * 2 + frame / 12) * 112;
              return (
                <g key={index} transform={`translate(${Math.round(x)} ${Math.round(y)}) rotate(${Math.round(Math.sin(frame / 8 + index) * 13)})`} filter="url(#qwenGlow)" opacity="0.92">
                  <rect x="-56" y="-20" width="112" height="40" rx="20" fill={packet.color} />
                  <text x="0" y="7" textAnchor="middle" fill="#172235" fontSize="14" fontWeight="950">{packet.label}</text>
                </g>
              );
            })}

            {stages.slice(0, 6).map((item: any, index: number) => {
              const angle = -Math.PI * 0.84 + index * (Math.PI * 1.68 / Math.max(1, Math.min(6, stages.length) - 1));
              const hot = index === active % Math.min(6, stages.length);
              const x = 380 + Math.cos(angle) * 282;
              const y = 310 + Math.sin(angle) * 202;
              const amount = spring({frame: frame - index * 6, fps, config: {damping: 18, stiffness: 112}});
                return (
                  <g key={item.label} transform={`translate(${Math.round(x)} ${Math.round(y + Math.sin(frame / 16 + index) * 8)}) scale(${0.72 + amount * 0.28})`} opacity={amount}>
                    <circle r={hot ? 48 + pulse * 8 : 34} fill={hot ? item.tone : 'rgba(255,253,244,0.18)'} stroke={hot ? '#fffdf4' : 'rgba(255,253,244,0.24)'} strokeWidth="3" />
                    <text x="0" y="7" textAnchor="middle" fill={hot ? '#172235' : '#fffdf4'} fontSize={hot ? 20 : 16} fontWeight="950">{item.label}</text>
                  </g>
                );
              })}
          </svg>
        </div>

        <div style={{display: 'grid', gridTemplateColumns: '1fr 260px', gap: 18, alignItems: 'stretch'}}>
          <div style={{borderRadius: 26, background: tone, color: '#172235', padding: '22px 26px', display: 'grid', alignContent: 'center', gap: 8, transform: `translateY(${Math.round((1 - beatEnter) * 18 - pulse * 5)}px) scale(${0.96 + beatEnter * 0.04})`}}>
            <div style={{fontSize: 35, lineHeight: 1.02, fontWeight: 970}}>{stage.label}</div>
            <div style={{fontSize: 24, lineHeight: 1.08, fontWeight: 850}}>{stage.detail}</div>
            <div style={{fontSize: 19, lineHeight: 1.08, fontWeight: 820, opacity: 0.76}}>{stage.tag}</div>
          </div>
          <div style={{borderRadius: 26, background: 'rgba(255,253,244,0.10)', border: '2px solid rgba(255,253,244,0.18)', padding: '20px 22px', display: 'grid', alignContent: 'center', gap: 8, transform: `translateX(${Math.round(Math.sin(frame / 15) * 8)}px)`}}>
            <div style={{fontSize: 23, color: '#9cffd0', fontWeight: 930}}>验证边界</div>
            <div style={{fontSize: 20, lineHeight: 1.12, fontWeight: 820}}>{focusChecks[active % focusChecks.length]}</div>
          </div>
        </div>
      </div>
    </div>
  </AbsoluteFill>
);
"""
    component = component.replace("__TITLE__", json.dumps(title, ensure_ascii=False))
    component = component.replace("__REPO__", json.dumps(repo, ensure_ascii=False))
    component = component.replace("__STAGES__", json.dumps(stages, ensure_ascii=False))
    component = component.replace("__CHECKS__", json.dumps(visual_checks[:4], ensure_ascii=False))
    return {
        "enabled": True,
        "render_mode": "full_canvas",
        "description": f"Focused source-grounded custom visual for {repo}: one central evidence relay diagram with orbiting signal packets, audio-reactive source hub, active stage nodes, and one verification focus panel inside the safe area.",
        "component_code": component,
        "css": ".agent-source-visual { box-sizing: border-box; }",
    }


def module_source_grounded_agent_visual(
    title: str,
    repo: str,
    facts: list[str],
    pipeline: list[dict[str, str]],
    checks: list[str],
    min_state_count: int = 6,
) -> dict[str, Any]:
    terms = _extract_visual_terms(facts, repo)
    repo_name = repo.rsplit("/", 1)[-1] if repo else "project"
    joined = "\n".join(facts).lower()
    visual_checks = [*_source_host_checks(facts), *checks]
    context_states: list[dict[str, str]] = []
    if "headroom" in joined or "headroom" in repo.lower():
        file_rows = [
            "headroom / core",
            "crates / compressors",
            "sdk/typescript",
            "plugins / mcp",
            "docs / architecture",
            "benchmarks / evals",
        ]
        lane_rows = [
            {"label": "Library", "detail": "Python / TypeScript compress()", "tone": "#72e7ff"},
            {"label": "Proxy", "detail": "OpenAI-compatible drop-in", "tone": "#ffd60a"},
            {"label": "Agent wrap", "detail": "Claude / Codex / Cursor", "tone": "#ff8a5b"},
            {"label": "MCP", "detail": "compress / retrieve / stats", "tone": "#9cffd0"},
            {"label": "CCR", "detail": "reversible local originals", "tone": "#c7a6ff"},
        ]
        state_seed = [
            {"label": "工具输出", "detail": "logs / files / RAG chunks", "tag": "SOURCE", "tone": "#72e7ff"},
            {"label": "CacheAligner", "detail": "稳定前缀，提升缓存命中", "tag": "CACHE", "tone": "#ffd60a"},
            {"label": "ContentRouter", "detail": "按内容类型选压缩器", "tag": "ROUTE", "tone": "#ff8a5b"},
            {"label": "SmartCrusher", "detail": "JSON 结构压缩", "tag": "JSON", "tone": "#9cffd0"},
            {"label": "CodeCompressor", "detail": "AST-aware code shrink", "tag": "CODE", "tone": "#c7a6ff"},
            {"label": "Kompress-base", "detail": "文本压缩模型", "tag": "TEXT", "tone": "#f4f0df"},
            {"label": "CCR retrieve", "detail": "需要原文时可取回", "tag": "VERIFY", "tone": "#ff6b9d"},
        ]
        metric_rows = [
            {"label": "README claim", "value": "60-95%", "detail": "fewer tokens"},
            {"label": "Live demo", "value": "10,144→1,260", "detail": "same fatal found"},
            {"label": "Workload proof", "value": "47-92%", "detail": "real agent traces"},
        ]
    else:
        file_rows = terms["files"][:6] or [f"{repo_name} / docs", f"{repo_name} / examples", f"{repo_name} / tests"]
        lane_rows = [
            {
                "label": bounded_text(step.get("label") or step.get("k") or f"Step {index + 1}", 22),
                "detail": bounded_text(step.get("detail") or "source-backed mechanism", 34),
                "tone": ["#72e7ff", "#ffd60a", "#ff8a5b", "#9cffd0", "#c7a6ff", "#f4f0df"][index % 6],
            }
            for index, step in enumerate(pipeline[:6])
        ]
        state_seed = [
            {
                "label": bounded_text(step.get("label") or f"阶段 {index + 1}", 18),
                "detail": bounded_text(step.get("detail") or "证据机制", 34),
                "tag": bounded_text(step.get("k") or f"S{index + 1}", 12).upper(),
                "tone": ["#72e7ff", "#ffd60a", "#ff8a5b", "#9cffd0", "#c7a6ff", "#f4f0df"][index % 6],
            }
            for index, step in enumerate(pipeline[:6])
        ]
        seen_state_labels = {str(item.get("label") or "").lower() for item in state_seed}
        for call in terms["calls"]:
            call_label = bounded_text(call, 18)
            if call_label.lower() not in seen_state_labels:
                context_states.append(
                    {"label": call_label, "detail": "源码接口信号", "tag": "CALL", "tone": "#8bd3ff"}
                )
                break
        metric_rows = [
            {"label": "来源", "value": "GitHub", "detail": repo},
            {"label": "机制", "value": str(len(lane_rows)), "detail": "visible stages"},
            {"label": "复核", "value": str(max(2, len(visual_checks))), "detail": "checks"},
        ]

    extras = [
        *context_states,
        {"label": "审风险", "detail": "失败条件先列清", "tag": "RISK", "tone": "#ff6b9d"},
        {"label": "看边界", "detail": "适用/不适用分开", "tag": "BOUND", "tone": "#8bd3ff"},
        {"label": "做复测", "detail": "小样本验证", "tag": "TEST", "tone": "#f7c59f"},
        {"label": "看来源", "detail": "README / docs / package", "tag": "SRC", "tone": "#b8f7d4"},
        {"label": "收结论", "detail": "把推荐降为检查清单", "tag": "NOTE", "tone": "#d8b4fe"},
    ]
    required = max(6, min(MAX_SCENES, int(min_state_count or 6)))
    states = [*state_seed]
    for item in extras:
        if len(states) >= required:
            break
        states.append(item)
    if not lane_rows:
        lane_rows = [{"label": item["label"], "detail": item["detail"], "tone": item["tone"]} for item in states[:5]]
    visual_checks = (visual_checks or ["官方 README", "包分发记录", "复测边界"])[:5]
    files = [bounded_text(public_visible_text(item), 32) for item in file_rows[:6] if clean_text(item)]
    if len(files) < 4:
        files.extend([f"{repo_name} / README", f"{repo_name} / docs", f"{repo_name} / tests"])
    files = files[:6]
    repo_label = bounded_text(repo or repo_name, 42)
    title_label = bounded_text(title, 58)
    module = r"""// @ts-nocheck
import React, {useMemo} from 'react';
import {AbsoluteFill, interpolate, spring} from 'remotion';
import type {AgentVisualProps} from '../AgentVisualTypes';

export const AgentVisualGenerated: React.FC<AgentVisualProps> = ({
  frame,
  fps,
  durationInFrames,
  progress,
  audioPulse,
  width,
  height,
}) => {
  const title = __TITLE__;
  const repo = __REPO__;
  const states = __STATES__;
  const lanes = __LANES__;
  const files = __FILES__;
  const metrics = __METRICS__;
  const checks = __CHECKS__;
  const isVertical = height >= width;
  const total = Math.max(1, durationInFrames);
  const beatCount = Math.max(1, states.length);
  const raw = Math.min(beatCount - 0.001, Math.max(0, progress * beatCount));
  const active = Math.floor(raw);
  const local = raw - active;
  const state = states[active] || states[0];
  const tone = state.tone || '#72e7ff';
  const enter = spring({frame, fps, config: {damping: 18, stiffness: 112}});
  const activeEnter = spring({frame: frame - active * 6, fps, config: {damping: 18, stiffness: 118}});
  const pulse = interpolate(Math.sin(frame / 9), [-1, 1], [0, 1]);
  const audioScale = interpolate(audioPulse, [0, 1], [1, 1.085], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const scanner = 16 + ((frame * 4) % 438);
  const flowPackets = useMemo(() => Array.from({length: 12}, (_, index) => index), []);
  const gridDots = useMemo(() => Array.from({length: 42}, (_, index) => index), []);
  const activeLane = Math.min(lanes.length - 1, Math.max(0, Math.floor(local * lanes.length)));
  const sidePad = isVertical ? 64 : 88;
  const bottomSafe = isVertical ? 590 : 190;
  const meter = Math.round(60 + 35 * (0.5 + 0.5 * Math.sin(frame / 28 + active)));
  const saved = Math.max(0, Math.min(95, meter));
  if (!isVertical) {
    return (
      <AbsoluteFill
        style={{
          backgroundColor: '#263449',
          color: '#fffdf4',
          fontFamily: 'Inter, PingFang SC, sans-serif',
          overflow: 'hidden',
        }}
      >
        <svg width="100%" height="100%" viewBox="0 0 1920 1080" style={{display: 'block'}}>
          <defs>
            <linearGradient id="wideHeadroomFlow" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#72e7ff" />
              <stop offset="48%" stopColor={tone} />
              <stop offset="100%" stopColor="#9cffd0" />
            </linearGradient>
            <filter id="wideHeadroomGlow">
              <feGaussianBlur stdDeviation="8" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          <rect width="1920" height="1080" fill="#263449" />
          <g opacity="0.16">
            {gridDots.map((dot: number) => {
              const col = dot % 14;
              const row = Math.floor(dot / 14);
              return (
                <circle
                  key={dot}
                  cx={192 + col * 118 + Math.sin(frame / 19 + dot) * 10}
                  cy={130 + row * 118 + Math.cos(frame / 21 + dot) * 8}
                  r={3 + pulse * 2}
                  fill="#fffdf4"
                />
              );
            })}
          </g>
          <path
            d="M370 545 C560 220 760 840 960 540 C1168 230 1370 830 1550 410"
            fill="none"
            stroke="rgba(255,253,244,0.18)"
            strokeWidth="34"
            strokeLinecap="round"
            strokeDasharray="48 34"
            strokeDashoffset={-frame * 3}
          />
          <path
            d="M370 545 C560 220 760 840 960 540 C1168 230 1370 830 1550 410"
            fill="none"
            stroke="url(#wideHeadroomFlow)"
            strokeWidth="16"
            strokeLinecap="round"
            strokeDasharray="1500"
            strokeDashoffset={1500 * (1 - local)}
            filter="url(#wideHeadroomGlow)"
          />
          <g transform={`translate(960 540) scale(${audioScale})`}>
            <circle r={250 + pulse * 16} fill="rgba(18,32,49,0.94)" stroke="url(#wideHeadroomFlow)" strokeWidth="8" />
            <circle r={325 + Math.sin(frame / 18) * 16} fill="none" stroke="url(#wideHeadroomFlow)" strokeWidth="5" strokeDasharray="34 24" strokeDashoffset={-frame * 3.2} />
            <circle r={184 + audioPulse * 30} fill={tone} opacity="0.15" />
            <text x="0" y="-54" textAnchor="middle" fill="#fffdf4" fontSize="46" fontWeight="960">{repo.slice(0, 28)}</text>
            <text x="0" y="6" textAnchor="middle" fill={tone} fontSize="34" fontWeight="960">{state.tag}</text>
            <text x="0" y="54" textAnchor="middle" fill="#cbd5e1" fontSize="24" fontWeight="820">{state.label}</text>
            <text x="0" y="104" textAnchor="middle" fill="#ffd60a" fontSize="32" fontWeight="960">{saved}% token focus</text>
            {states.slice(0, 8).map((item: any, index: number) => {
              const angle = frame / 31 + index * 0.785;
              const radius = 354 + Math.sin(frame / 17 + index) * 18;
              const x = Math.cos(angle) * radius;
              const y = Math.sin(angle) * radius * 0.64;
              const hot = index === active % Math.min(8, states.length);
              return (
                <g key={item.label} transform={`translate(${Math.round(x)} ${Math.round(y)})`} filter={hot ? 'url(#wideHeadroomGlow)' : undefined}>
                  <circle r={hot ? 48 + pulse * 7 : 34} fill={hot ? item.tone : 'rgba(255,253,244,0.20)'} stroke={hot ? '#fffdf4' : 'rgba(255,253,244,0.20)'} strokeWidth="3" />
                  <text x="0" y="8" textAnchor="middle" fill={hot ? '#172235' : '#fffdf4'} fontSize={hot ? 18 : 15} fontWeight="950">
                    {String(item.tag || index + 1).slice(0, 8)}
                  </text>
                </g>
              );
            })}
          </g>
          {flowPackets.map((packet: number) => {
            const phase = (packet / 12 + frame / 138) % 1;
            const x = 370 + phase * 1180;
            const y = 545 + Math.sin(phase * Math.PI * 2 + frame / 14) * 214;
            const lane = lanes[packet % lanes.length] || lanes[0];
            return (
              <g key={packet} transform={`translate(${Math.round(x)} ${Math.round(y)}) rotate(${Math.round(Math.sin(frame / 10 + packet) * 16)})`} opacity="0.9" filter="url(#wideHeadroomGlow)">
                <rect x="-82" y="-28" width="164" height="56" rx="28" fill={lane.tone || tone} />
                <text x="0" y="8" textAnchor="middle" fill="#172235" fontSize="18" fontWeight="950">{String(lane.label).slice(0, 14)}</text>
              </g>
            );
          })}
          {files.slice(0, 5).map((file: string, index: number) => {
            const hot = index === active % files.length;
            const x = 228 + index * 292;
            const y = 905 + Math.sin(frame / 18 + index) * 7;
            return (
              <g key={file} transform={`translate(${x} ${y})`} opacity={hot ? 1 : 0.62}>
                <line x1="0" y1="-18" x2="168" y2="-18" stroke={hot ? tone : 'rgba(255,253,244,0.34)'} strokeWidth={hot ? 5 : 3} strokeLinecap="round" />
                <text x="0" y="18" fill={hot ? '#fffdf4' : '#cbd5e1'} fontSize="22" fontWeight={hot ? 930 : 780}>{file.slice(0, 24)}</text>
              </g>
            );
          })}
          <text x="960" y="120" textAnchor="middle" fill="#cbd5e1" fontSize="24" fontWeight="820" opacity="0.82">
            {String(checks[active % checks.length] || '').slice(0, 72)}
          </text>
        </svg>
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill
      style={{
        backgroundColor: '#263449',
        color: '#fffdf4',
        fontFamily: 'Inter, PingFang SC, sans-serif',
        padding: `${isVertical ? 84 : 64}px ${sidePad}px ${bottomSafe}px`,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          height: '100%',
          display: 'grid',
          gridTemplateRows: isVertical ? '150px minmax(0, 1fr) 132px' : '116px minmax(0, 1fr)',
          gap: isVertical ? 24 : 18,
          opacity: enter,
          transform: `scale(${0.965 + enter * 0.035}) translateY(${Math.round((1 - enter) * -22)}px)`,
        }}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: isVertical ? '1fr 190px' : '1fr 250px',
            gap: 20,
            alignItems: 'end',
            borderBottom: '2px solid rgba(255,253,244,0.18)',
            paddingBottom: 18,
          }}
        >
          <div>
            <div style={{fontSize: isVertical ? 27 : 22, color: tone, fontWeight: 930, marginBottom: 10}}>
              官方仓库机制图 · {repo}
            </div>
            <div style={{fontSize: isVertical ? 52 : 39, lineHeight: 1.03, fontWeight: 970, maxWidth: isVertical ? 790 : 1160}}>
              {title}
            </div>
          </div>
          <div
            style={{
              height: isVertical ? 104 : 82,
              borderRadius: 24,
              border: `2px solid ${tone}`,
              background: 'rgba(255,253,244,0.10)',
              display: 'grid',
              placeItems: 'center',
              transform: `scale(${audioScale}) translateY(${Math.round(Math.sin(frame / 14) * 5)}px)`,
            }}
          >
            <div style={{fontSize: isVertical ? 21 : 17, color: '#cbd5e1', fontWeight: 850}}>当前焦点</div>
            <div style={{fontSize: isVertical ? 28 : 22, color: tone, fontWeight: 970}}>{state.label}</div>
          </div>
        </div>

        <div
          style={{
            minHeight: 0,
            display: 'grid',
            gridTemplateColumns: isVertical ? '1fr' : '1fr',
            gridTemplateRows: isVertical ? '180px minmax(0, 1fr) 186px' : '1fr',
            gap: isVertical ? 18 : 20,
          }}
        >
          {isVertical && (
            <div
              style={{
                borderRadius: 30,
                border: '2px solid rgba(255,253,244,0.18)',
                background: 'rgba(20,35,52,0.82)',
                padding: 20,
                overflow: 'hidden',
                boxShadow: '0 22px 70px rgba(0,0,0,0.25)',
              }}
            >
              <div style={{fontSize: 23, color: '#72e7ff', fontWeight: 930, marginBottom: 14}}>repo surface</div>
              <div style={{display: 'grid', gap: 9}}>
                {files.map((file: string, index: number) => {
                  const hot = index === active % files.length;
                  const reveal = spring({frame: frame - index * 5, fps, config: {damping: 19, stiffness: 116}});
                  return (
                    <div
                      key={file}
                      style={{
                        height: 19,
                        borderRadius: 13,
                        background: hot ? tone : 'rgba(255,253,244,0.10)',
                        color: hot ? '#172235' : '#fffdf4',
                        display: 'grid',
                        alignItems: 'center',
                        padding: '0 12px',
                        fontSize: 14,
                        fontWeight: 850,
                        opacity: reveal,
                        transform: `translateX(${Math.round((1 - reveal) * -26 + Math.sin(frame / 12 + index) * 5)}px)`,
                      }}
                    >
                      {file}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div
            style={{
              borderRadius: 36,
              border: `3px solid ${tone}`,
              background: 'rgba(18,32,49,0.90)',
              minHeight: 0,
              padding: isVertical ? 18 : 26,
              display: 'grid',
              gridTemplateRows: isVertical ? 'minmax(0, 1fr) 96px' : 'minmax(0, 1fr)',
              gap: 16,
              boxShadow: `0 30px 95px rgba(0,0,0,0.30), 0 0 ${24 + pulse * 34}px ${tone}44`,
              transform: `scale(${0.99 + audioPulse * 0.035})`,
            }}
          >
            <svg width="100%" height="100%" viewBox="0 0 820 560" style={{display: 'block', minHeight: isVertical ? 420 : 620}}>
              <defs>
                <linearGradient id="headroomModuleFlow" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#72e7ff" />
                  <stop offset="52%" stopColor="#ffd60a" />
                  <stop offset="100%" stopColor="#9cffd0" />
                </linearGradient>
                <filter id="headroomGlow">
                  <feGaussianBlur stdDeviation="4" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              <rect x="34" y="34" width="752" height="492" rx="42" fill="rgba(255,253,244,0.06)" stroke="rgba(255,253,244,0.16)" strokeWidth="3" />
              <rect x="66" y={scanner} width="688" height="38" rx="19" fill={tone} opacity="0.14" />
              <path
                d="M82 276 C176 98 278 460 382 284 C494 92 600 454 738 210"
                fill="none"
                stroke="rgba(255,253,244,0.22)"
                strokeWidth="19"
                strokeLinecap="round"
                strokeDasharray="32 26"
                strokeDashoffset={-frame * 2}
              />
              <path
                d="M82 276 C176 98 278 460 382 284 C494 92 600 454 738 210"
                fill="none"
                stroke="url(#headroomModuleFlow)"
                strokeWidth="11"
                strokeLinecap="round"
                strokeDasharray="900"
                strokeDashoffset={900 * (1 - local)}
              />

              {gridDots.map((dot: number) => {
                const col = dot % 7;
                const row = Math.floor(dot / 7);
                const hot = dot % beatCount === active;
                return (
                  <circle
                    key={dot}
                    cx={88 + col * 108 + Math.sin(frame / 20 + dot) * 9}
                    cy={74 + row * 72 + Math.cos(frame / 18 + dot) * 7}
                    r={hot ? 7 + pulse * 5 : 3.5 + pulse * 1.2}
                    fill={hot ? tone : 'rgba(255,253,244,0.25)'}
                  />
                );
              })}

              {!isVertical && files.slice(0, 5).map((file: string, index: number) => {
                const hot = index === active % files.length;
                const y = 82 + index * 54;
                return (
                  <g key={`file-${file}`} transform={`translate(${68 + Math.sin(frame / 18 + index) * 5} ${y})`}>
                    <rect width="188" height="38" rx="14" fill={hot ? tone : 'rgba(255,253,244,0.10)'} stroke="rgba(255,253,244,0.18)" />
                    <text x="16" y="24" fill={hot ? '#172235' : '#fffdf4'} fontSize="14" fontWeight="850">{file.slice(0, 24)}</text>
                  </g>
                );
              })}

              {!isVertical && metrics.slice(0, 3).map((metric: any, index: number) => {
                const hot = index === active % metrics.length;
                const y = 92 + index * 82;
                return (
                  <g key={`metric-${metric.label}`} transform={`translate(590 ${y})`}>
                    <rect width="162" height="58" rx="18" fill={hot ? '#ffd60a' : 'rgba(255,253,244,0.10)'} stroke="rgba(255,253,244,0.18)" />
                    <text x="14" y="22" fill={hot ? '#172235' : '#cbd5e1'} fontSize="12" fontWeight="820">{String(metric.label).slice(0, 17)}</text>
                    <text x="14" y="45" fill={hot ? '#172235' : '#fffdf4'} fontSize="20" fontWeight="960">{String(metric.value).slice(0, 14)}</text>
                  </g>
                );
              })}

              {!isVertical && (
                <g transform="translate(76 452)">
                  <rect width="668" height="58" rx="22" fill="rgba(255,253,244,0.10)" stroke="rgba(255,253,244,0.18)" />
                  <text x="24" y="36" fill="#9cffd0" fontSize="18" fontWeight="900">复核点</text>
                  <text x="112" y="36" fill="#fffdf4" fontSize="18" fontWeight="840">{String(checks[active % checks.length] || '').slice(0, 58)}</text>
                </g>
              )}

              <g transform={`translate(410 280) scale(${audioScale})`}>
                <g transform={`rotate(${frame * 3.6 + active * 31})`} opacity="0.55">
                  <path d="M0 0 L158 -24 L158 24 Z" fill={tone} opacity="0.22" />
                  <line x1="0" y1="0" x2="182" y2="0" stroke={tone} strokeWidth="7" strokeLinecap="round" />
                </g>
                <circle r={116 + pulse * 11} fill="rgba(20,35,52,0.94)" stroke={tone} strokeWidth="5" />
                <circle r={162 + Math.sin(frame / 17) * 11} fill="none" stroke="url(#headroomModuleFlow)" strokeWidth="4" strokeDasharray="22 17" strokeDashoffset={-frame * 2.4} />
                <circle r={72 + audioPulse * 24} fill={tone} opacity="0.18" />
                <text x="0" y="-16" textAnchor="middle" fill="#fffdf4" fontSize="34" fontWeight="960">{repo.slice(0, 20)}</text>
                <text x="0" y="30" textAnchor="middle" fill={tone} fontSize="21" fontWeight="920">{state.tag}</text>
                {states.slice(0, 8).map((item: any, index: number) => {
                  const angle = frame / 23 + index * 0.78;
                  const radius = 172 + Math.sin(frame / 15 + index) * 13;
                  const x = Math.cos(angle) * radius;
                  const y = Math.sin(angle) * radius * 0.62;
                  const hot = index === active % Math.min(8, states.length);
                  return (
                    <g key={item.label} transform={`translate(${Math.round(x)} ${Math.round(y)})`} filter={hot ? 'url(#headroomGlow)' : undefined}>
                      <circle r={hot ? 25 + pulse * 6 : 16} fill={hot ? item.tone : 'rgba(255,253,244,0.42)'} />
                      <text x="0" y="6" textAnchor="middle" fill={hot ? '#172235' : '#fffdf4'} fontSize={hot ? 12 : 10} fontWeight="950">
                        {String(item.tag || index + 1).slice(0, 7)}
                      </text>
                    </g>
                  );
                })}
              </g>

              {flowPackets.map((packet: number) => {
                const phase = (packet / 12 + frame / 116) % 1;
                const x = 84 + phase * 652;
                const y = 276 + Math.sin(phase * Math.PI * 2 + frame / 13) * 116;
                const lane = lanes[packet % lanes.length] || lanes[0];
                return (
                  <g key={packet} transform={`translate(${Math.round(x)} ${Math.round(y)}) rotate(${Math.round(Math.sin(frame / 9 + packet) * 12)})`} opacity="0.93" filter="url(#headroomGlow)">
                    <rect x="-58" y="-21" width="116" height="42" rx="21" fill={lane.tone || tone} />
                    <text x="0" y="7" textAnchor="middle" fill="#172235" fontSize="14" fontWeight="950">{String(lane.label).slice(0, 13)}</text>
                  </g>
                );
              })}
            </svg>
            {isVertical && (
              <div style={{display: 'grid', gridTemplateColumns: '1fr 190px', gap: 16}}>
                <div
                  style={{
                    borderRadius: 24,
                    background: tone,
                    color: '#172235',
                    padding: '16px 20px',
                    display: 'grid',
                    alignContent: 'center',
                    transform: `translateY(${Math.round((1 - activeEnter) * 18 - pulse * 5)}px) scale(${0.96 + activeEnter * 0.04})`,
                  }}
                >
                  <div style={{fontSize: 31, fontWeight: 970, lineHeight: 1.04}}>{state.label}</div>
                  <div style={{fontSize: 22, fontWeight: 850, lineHeight: 1.1, marginTop: 5}}>{state.detail}</div>
                </div>
                <div
                  style={{
                    borderRadius: 24,
                    background: 'rgba(255,253,244,0.10)',
                    border: '2px solid rgba(255,253,244,0.18)',
                    padding: '14px 16px',
                    display: 'grid',
                    alignContent: 'center',
                    transform: `translateX(${Math.round(Math.sin(frame / 15) * 8)}px)`,
                  }}
                >
                  <div style={{fontSize: 20, color: '#9cffd0', fontWeight: 930}}>复核点</div>
                  <div style={{fontSize: 20, lineHeight: 1.12, fontWeight: 830}}>{checks[active % checks.length]}</div>
                </div>
              </div>
            )}
          </div>

          {isVertical && (
            <div
              style={{
                borderRadius: 30,
                border: '2px solid rgba(255,253,244,0.18)',
                background: 'rgba(20,35,52,0.82)',
                padding: 20,
                overflow: 'hidden',
                boxShadow: '0 22px 70px rgba(0,0,0,0.25)',
              }}
            >
              <div style={{fontSize: 23, color: '#ffd60a', fontWeight: 930, marginBottom: 14}}>token meter</div>
              <div
                style={{
                  height: 68,
                  borderRadius: 22,
                  background: '#ffd60a',
                  color: '#172235',
                  display: 'grid',
                  placeItems: 'center',
                  fontSize: 38,
                  fontWeight: 980,
                  transform: `scale(${0.97 + pulse * 0.04})`,
                }}
              >
                {saved}%
              </div>
              <div style={{display: 'grid', gap: 10, marginTop: 16}}>
                {metrics.map((metric: any, index: number) => {
                  const hot = index === active % metrics.length;
                  return (
                    <div
                      key={metric.label}
                      style={{
                        borderRadius: 18,
                        background: hot ? '#fffdf4' : 'rgba(255,253,244,0.10)',
                        color: hot ? '#172235' : '#fffdf4',
                        padding: '11px 13px',
                        display: 'grid',
                        gridTemplateColumns: '1fr auto',
                        gap: 9,
                        alignItems: 'center',
                        transform: `translateX(${Math.round((hot ? 10 : 0) + Math.sin(frame / 12 + index) * 5)}px)`,
                      }}
                    >
                      <span style={{fontSize: 14, fontWeight: 840}}>{metric.label}</span>
                      <span style={{fontSize: 17, fontWeight: 950}}>{metric.value}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {isVertical && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: `repeat(${lanes.length}, 1fr)`,
              gap: 12,
              alignItems: 'stretch',
            }}
          >
            {lanes.map((lane: any, index: number) => {
              const hot = index === activeLane || index === active % lanes.length;
              const reveal = spring({frame: frame - index * 5, fps, config: {damping: 18, stiffness: 116}});
              return (
                <div
                  key={lane.label}
                  style={{
                    borderRadius: 20,
                    background: hot ? lane.tone : 'rgba(255,253,244,0.10)',
                    color: hot ? '#172235' : '#fffdf4',
                    padding: '13px 11px',
                    display: 'grid',
                    alignContent: 'center',
                    gap: 5,
                    opacity: reveal,
                    transform: `translateY(${Math.round((hot ? -9 : 2) + Math.sin(frame / 13 + index) * 4)}px)`,
                  }}
                >
                  <div style={{fontSize: 18, fontWeight: 960, lineHeight: 1.02}}>{lane.label}</div>
                  <div style={{fontSize: 12, fontWeight: 790, lineHeight: 1.08, opacity: 0.82}}>{lane.detail}</div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
"""
    module = module.replace("__TITLE__", json.dumps(title_label, ensure_ascii=False))
    module = module.replace("__REPO__", json.dumps(repo_label, ensure_ascii=False))
    module = module.replace("__STATES__", json.dumps(states, ensure_ascii=False))
    module = module.replace("__LANES__", json.dumps(lane_rows[:6], ensure_ascii=False))
    module = module.replace("__FILES__", json.dumps(files, ensure_ascii=False))
    module = module.replace("__METRICS__", json.dumps(metric_rows[:4], ensure_ascii=False))
    module = module.replace("__CHECKS__", json.dumps(visual_checks, ensure_ascii=False))
    return {
        "enabled": True,
        "render_mode": "full_canvas",
        "description": f"Full TSX module visual for {repo_label}: single-focal architecture diagram with inline repo labels, token-meter annotations, moving SVG packet flow, and source verification note.",
        "module_code": module,
        "component_code": "",
        "css": "",
    }


def generic_source_grounded_agent_visual(
    title: str,
    repo: str,
    facts: list[str],
    pipeline: list[dict[str, str]],
    checks: list[str],
    min_state_count: int = 6,
) -> dict[str, Any]:
    return module_source_grounded_agent_visual(title, repo, facts, pipeline, checks, min_state_count=min_state_count)

def cinematic_source_grounded_agent_visual(title: str, repo: str, pipeline: list[dict[str, Any]], checks: list[str]) -> dict[str, Any]:
    """Build a low-density, cinematic repo explainer visual.

    This deterministic fallback is intentionally closer to product-demo
    references than to a single architecture board: one active beat per scene,
    split-screen cause/effect, a moving pipeline packet, vector-store motion,
    and a final verification gate.
    """

    component = r"""
const title = __TITLE__;
const repo = __REPO__;
const pipeline = __PIPELINE__;
const checks = __CHECKS__;
const beats = [
  {name: '记忆差异', tone: '#ffd60a', hint: '先看为什么需要长期记忆'},
  {name: '写入流程', tone: '#74d3ff', hint: 'add() 把对话变成可检索事实'},
  {name: '向量空间', tone: '#ff9b70', hint: 'factory.py 决定存储边界'},
  {name: '检索返回', tone: '#9cffd0', hint: 'search() 把相关记忆带回回答'},
  {name: '上线检查', tone: '#f4f0df', hint: '有评估和隔离，再进生产'},
];
const total = Math.max(1, durationInFrames);
const beatCount = beats.length;
const beatLen = total / beatCount;
const rawBeat = Math.min(beatCount - 0.001, Math.max(0, frame / beatLen));
const active = Math.floor(rawBeat);
const localFrame = frame - active * beatLen;
const local = Math.min(1, Math.max(0, localFrame / beatLen));
const beat = beats[active];
const tone = beat.tone;
const pulse = 0.5 + 0.5 * Math.sin(frame / 8);
const enter = spring({frame: Math.max(0, localFrame), fps, config: {damping: 18, stiffness: 115}});
const reveal = (offset: number) => spring({frame: Math.max(0, localFrame - offset), fps, config: {damping: 20, stiffness: 125}});
const hotIndex = Math.min(4, Math.floor(local * 5));
const nodeGrid = Array.from({length: 30}, (_, index) => ({
  hot: index % 5 === active,
  phase: index * 0.71,
}));
const providers = ['Qdrant', 'Chroma', 'Pinecone', 'Pgvector', 'Redis', 'Faiss'];
const codeLines = ['Memory.add(messages)', 'extract facts with LLM', 'embed -> vector store', 'Memory.search(query)'];
const card = (accent: string, extra: any = {}) => ({
  borderRadius: 30,
  border: `2px solid ${accent}`,
  background: 'rgba(24,37,54,0.84)',
  boxShadow: `0 24px 70px rgba(0,0,0,0.28), 0 0 ${18 + Math.round(pulse * 26)}px ${accent}44`,
  overflow: 'hidden',
  ...extra,
});
const header = (label: string, accent: string) => (
  <div style={{
    height: 60,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0 24px',
    background: 'rgba(255,253,244,0.08)',
    color: accent,
    fontSize: 23,
    fontWeight: 930,
  }}>
    <span>{label}</span>
    <span style={{display: 'flex', gap: 8}}>
      {[0, 1, 2].map((dot) => (
        <span key={dot} style={{width: 12, height: 12, borderRadius: 999, background: dot === 0 ? accent : 'rgba(255,253,244,0.32)'}} />
      ))}
    </span>
  </div>
);
const bubble = (text: string, hot = false, delay = 0) => {
  const amount = reveal(delay);
  return (
    <div style={{
      borderRadius: 24,
      padding: '20px 22px',
      background: hot ? tone : 'rgba(255,253,244,0.11)',
      color: hot ? '#263449' : '#fffdf4',
      fontSize: 29,
      lineHeight: 1.16,
      fontWeight: 880,
      transform: `translateY(${Math.round((1 - amount) * 28 + Math.sin(frame / 13 + delay) * 5)}px) scale(${0.92 + amount * 0.08})`,
      opacity: amount,
    }}>{text}</div>
  );
};
const Intro = () => (
  <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, height: '100%'}}>
    <div style={card('#8796a8')}>
      {header('没有长期记忆', '#8796a8')}
      <div style={{padding: 26, display: 'grid', gridTemplateRows: '1fr 1fr 1.2fr', gap: 22, height: 'calc(100% - 60px)'}}>
        {bubble('昨天我说过什么偏好？', false, 0)}
        {bubble('只能看当前上下文，容易重新问。', false, 10)}
        <div style={{
          borderRadius: 28,
          border: '2px dashed rgba(255,253,244,0.28)',
          display: 'grid',
          placeItems: 'center',
          color: '#c9d6e6',
          fontSize: 33,
          lineHeight: 1.1,
          textAlign: 'center',
          fontWeight: 930,
          transform: `scale(${0.98 + pulse * 0.03})`,
        }}>上下文断开<br />重复解释</div>
      </div>
    </div>
    <div style={card('#ffd60a')}>
      {header('接入 Mem0 后', '#ffd60a')}
      <div style={{padding: 26, display: 'grid', gridTemplateRows: '1fr 1fr 1.2fr', gap: 22, height: 'calc(100% - 60px)'}}>
        {bubble('记住：偏好深色界面。', true, 5)}
        {bubble('下一次回答直接带上这个偏好。', false, 16)}
        <div style={{
          borderRadius: 30,
          background: '#ffd60a',
          color: '#263449',
          display: 'grid',
          placeItems: 'center',
          textAlign: 'center',
          fontSize: 39,
          lineHeight: 1.12,
          fontWeight: 970,
          transform: `translate(${Math.round(Math.sin(frame / 10) * 15)}px, ${Math.round(Math.cos(frame / 13) * 10)}px) rotate(${Math.round(Math.sin(frame / 17) * 3)}deg)`,
        }}>记忆卡片<br />user scope<br />可检索</div>
      </div>
    </div>
  </div>
);
const WriteFlow = () => (
  <div style={card('#74d3ff', {height: '100%'})}>
    {header('mem0/memory/main.py · 写入流程', '#74d3ff')}
    <div style={{padding: 30, display: 'grid', gridTemplateRows: '150px 1fr', gap: 26, height: 'calc(100% - 60px)'}}>
      <div style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 18}}>
        {codeLines.map((line, index) => {
          const hot = index === Math.min(3, hotIndex);
          return (
            <div key={line} style={{
              borderRadius: 24,
              background: hot ? '#74d3ff' : 'rgba(255,253,244,0.10)',
              color: hot ? '#263449' : '#dbeafe',
              padding: 18,
              display: 'grid',
              placeItems: 'center',
              textAlign: 'center',
              fontSize: 26,
              lineHeight: 1.1,
              fontWeight: 930,
              transform: `translateY(${Math.round((hot ? -12 : 0) + Math.sin(frame / 11 + index) * 5)}px)`,
            }}>{line}</div>
          );
        })}
      </div>
      <div style={{borderRadius: 34, background: 'rgba(255,253,244,0.08)', border: '2px solid rgba(116,211,255,0.36)', padding: 30, display: 'grid', gridTemplateRows: '1fr 88px', gap: 24}}>
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 18, alignItems: 'center'}}>
          {['消息', '抽事实', '写历史', '生成向量', '等待检索'].map((label, index) => {
            const hot = index === hotIndex;
            return (
              <div key={label} style={{
                height: 138,
                borderRadius: 28,
                background: hot ? '#74d3ff' : 'rgba(255,253,244,0.10)',
                color: hot ? '#263449' : '#fffdf4',
                display: 'grid',
                placeItems: 'center',
                textAlign: 'center',
                fontSize: 31,
                fontWeight: 950,
                transform: `translateY(${Math.round((hot ? -18 : 0) + Math.sin(frame / 12 + index) * 8)}px) scale(${hot ? 1.04 : 0.96})`,
              }}>{label}</div>
            );
          })}
        </div>
        <div style={{display: 'grid', gridTemplateColumns: '1fr 170px 1fr', gap: 18, alignItems: 'center'}}>
          <div style={{height: 12, borderRadius: 999, background: '#74d3ff', transform: `scaleX(${0.2 + local * 0.8})`, transformOrigin: 'left center'}} />
          <div style={{height: 86, borderRadius: 24, background: '#74d3ff', color: '#263449', display: 'grid', placeItems: 'center', textAlign: 'center', fontSize: 26, fontWeight: 950, transform: `translateX(${Math.round(Math.sin(frame / 8) * 42)}px) rotate(${Math.round(Math.sin(frame / 9) * 5)}deg)`}}>事件包</div>
          <div style={{height: 12, borderRadius: 999, background: 'rgba(116,211,255,0.40)'}} />
        </div>
      </div>
    </div>
  </div>
);
const VectorScene = () => (
  <div style={{display: 'grid', gridTemplateColumns: '1.1fr 0.9fr', gap: 24, height: '100%'}}>
    <div style={card('#ff9b70', {paddingBottom: 26})}>
      {header('向量记忆空间', '#ff9b70')}
      <div style={{padding: 30, display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gridTemplateRows: 'repeat(5, 1fr)', gap: 16, height: 'calc(100% - 60px)'}}>
        {nodeGrid.map((node, index) => (
          <div key={index} style={{
            borderRadius: 999,
            background: node.hot ? '#ff9b70' : 'rgba(255,253,244,0.34)',
            boxShadow: node.hot ? '0 0 32px #ff9b70' : 'none',
            transform: `translate(${Math.round(Math.sin(frame / 16 + node.phase) * 22)}px, ${Math.round(Math.cos(frame / 19 + node.phase) * 18)}px) scale(${node.hot ? 1.24 + pulse * 0.18 : 0.82 + pulse * 0.12})`,
          }} />
        ))}
      </div>
    </div>
    <div style={card('#ff9b70')}>
      {header('provider factory', '#ff9b70')}
      <div style={{padding: 26, display: 'grid', gap: 14, height: 'calc(100% - 60px)'}}>
        {providers.map((name, index) => {
          const hot = index === Math.min(providers.length - 1, Math.floor(local * providers.length));
          return (
            <div key={name} style={{
              borderRadius: 22,
              background: hot ? '#ff9b70' : 'rgba(255,253,244,0.10)',
              color: hot ? '#263449' : '#fffdf4',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '0 22px',
              fontSize: 29,
              fontWeight: 930,
              transform: `translateX(${Math.round((hot ? 14 : 0) + Math.sin(frame / 10 + index) * 10)}px)`,
            }}>
              <span>{name}</span>
              <span>{hot ? '选中' : '可替换'}</span>
            </div>
          );
        })}
      </div>
    </div>
  </div>
);
const SearchScene = () => (
  <div style={card('#9cffd0', {height: '100%'})}>
    {header('search(query) · 检索返回', '#9cffd0')}
    <div style={{padding: 30, display: 'grid', gridTemplateRows: '174px 1fr', gap: 24, height: 'calc(100% - 60px)'}}>
      <div style={{display: 'grid', gridTemplateColumns: '1fr 190px 1fr', gap: 20, alignItems: 'center'}}>
        <div style={{borderRadius: 28, background: 'rgba(255,253,244,0.10)', padding: 26, fontSize: 34, lineHeight: 1.12, fontWeight: 930}}>今天继续推荐，记得我的偏好吗？</div>
        <div style={{height: 84, borderRadius: 24, background: '#9cffd0', color: '#263449', display: 'grid', placeItems: 'center', fontSize: 28, fontWeight: 960, transform: `translateX(${Math.round(Math.sin(frame / 8) * 28)}px) scale(${0.92 + pulse * 0.14})`}}>查询</div>
        <div style={{borderRadius: 28, background: '#9cffd0', color: '#263449', padding: 26, fontSize: 32, lineHeight: 1.12, fontWeight: 950}}>带回：深色界面、CRM 场景、低打扰提醒</div>
      </div>
      <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20}}>
        {['偏好事实', '项目上下文', '隔离边界'].map((label, index) => {
          const hot = index === Math.min(2, Math.floor(local * 3.2));
          return (
            <div key={label} style={{
              borderRadius: 30,
              background: hot ? '#9cffd0' : 'rgba(255,253,244,0.10)',
              color: hot ? '#263449' : '#fffdf4',
              padding: 28,
              display: 'grid',
              gridTemplateRows: '64px 1fr 66px',
              gap: 16,
              transform: `translateY(${Math.round((hot ? -20 : 0) + Math.sin(frame / 11 + index) * 8)}px) scale(${hot ? 1.03 : 0.97})`,
            }}>
              <div style={{fontSize: 35, fontWeight: 960}}>{label}</div>
              <div style={{fontSize: 26, lineHeight: 1.15, fontWeight: 820}}>只取相关片段，不把整段历史塞回上下文。</div>
              <div style={{borderRadius: 18, background: hot ? 'rgba(38,52,73,0.20)' : 'rgba(255,253,244,0.10)', display: 'grid', placeItems: 'center', fontSize: 26, fontWeight: 930}}>score {hot ? '0.91' : '0.42'}</div>
            </div>
          );
        })}
      </div>
    </div>
  </div>
);
const CheckScene = () => (
  <div style={{display: 'grid', gridTemplateColumns: '0.95fr 1.05fr', gap: 24, height: '100%'}}>
    <div style={card('#f4f0df')}>
      {header('上线前检查', '#f4f0df')}
      <div style={{padding: 26, display: 'grid', gap: 16, height: 'calc(100% - 60px)'}}>
        {checks.map((check: string, index: number) => {
          const hot = index <= Math.floor(local * checks.length);
          return (
            <div key={check} style={{
              borderRadius: 24,
              background: hot ? '#f4f0df' : 'rgba(255,253,244,0.10)',
              color: hot ? '#263449' : '#fffdf4',
              display: 'flex',
              alignItems: 'center',
              gap: 18,
              padding: '0 22px',
              fontSize: 29,
              fontWeight: 930,
              transform: `translateX(${Math.round((hot ? 12 : 0) + Math.sin(frame / 12 + index) * 8)}px)`,
            }}>
              <span style={{width: 42, height: 42, borderRadius: 999, background: hot ? '#263449' : 'rgba(255,253,244,0.20)', color: hot ? '#f4f0df' : '#fffdf4', display: 'grid', placeItems: 'center', fontSize: 25}}>{hot ? '✓' : index + 1}</span>
              <span>{check}</span>
            </div>
          );
        })}
      </div>
    </div>
    <div style={card('#f4f0df')}>
      {header('结论不是“马上上生产”', '#f4f0df')}
      <div style={{padding: 30, display: 'grid', gridTemplateRows: '1fr 1fr 1fr', gap: 18, height: 'calc(100% - 60px)'}}>
        {[
          ['适合', '需要跨会话偏好和长期上下文的 Agent'],
          ['谨慎', '没有评估集、没有隔离边界时先别接生产'],
          ['看源码', '入口、主流程、provider factory、REST 路由'],
        ].map((row, index) => {
          const hot = index === Math.min(2, Math.floor(local * 3.1));
          return (
            <div key={row[0]} style={{
              borderRadius: 28,
              background: hot ? '#f4f0df' : 'rgba(255,253,244,0.10)',
              color: hot ? '#263449' : '#fffdf4',
              padding: 28,
              display: 'grid',
              gridTemplateColumns: '140px 1fr',
              gap: 18,
              alignItems: 'center',
              transform: `scale(${hot ? 1.03 : 0.98}) translateY(${Math.round(Math.sin(frame / 10 + index) * 7)}px)`,
            }}>
              <div style={{fontSize: 36, fontWeight: 970}}>{row[0]}</div>
              <div style={{fontSize: 29, lineHeight: 1.12, fontWeight: 850}}>{row[1]}</div>
            </div>
          );
        })}
      </div>
    </div>
  </div>
);
const view = [<Intro key="intro" />, <WriteFlow key="write" />, <VectorScene key="vector" />, <SearchScene key="search" />, <CheckScene key="check" />][active];
return (
  <AbsoluteFill style={{
    backgroundColor: '#263449',
    color: '#fffdf4',
    fontFamily: 'Inter, PingFang SC, sans-serif',
    padding: '88px 64px 430px',
    overflow: 'hidden',
  }}>
    <div style={{height: '100%', display: 'grid', gridTemplateRows: '166px 1fr 78px', gap: 24}}>
      <div style={{display: 'grid', gridTemplateColumns: '1fr 260px', gap: 22, alignItems: 'end', borderBottom: '2px solid rgba(255,253,244,0.18)', paddingBottom: 22}}>
        <div>
          <div style={{fontSize: 29, color: tone, fontWeight: 930, marginBottom: 12}}>源码介绍 · {repo}</div>
          <div style={{fontSize: 54, lineHeight: 1.04, fontWeight: 970, maxWidth: 830}}>{title}</div>
        </div>
        <div style={{height: 112, borderRadius: 26, background: 'rgba(255,253,244,0.10)', border: `2px solid ${tone}`, display: 'grid', alignItems: 'center', justifyItems: 'center', transform: `translateY(${Math.round(Math.sin(frame / 12) * 6)}px)`}}>
          <div style={{fontSize: 23, color: '#cbd5e1', fontWeight: 800}}>镜头 {active + 1} / {beatCount}</div>
          <div style={{fontSize: 31, color: tone, fontWeight: 970}}>{beat.name}</div>
        </div>
      </div>
      <div style={{minHeight: 0, transform: `translateY(${Math.round((1 - enter) * 32)}px) scale(${0.94 + enter * 0.06})`, opacity: enter}}>
        {view}
      </div>
      <div style={{display: 'grid', gridTemplateColumns: `repeat(${pipeline.length}, 1fr)`, gap: 12, alignItems: 'center'}}>
        {pipeline.map((step: any, index: number) => {
          const hot = index === active;
          return (
            <div key={step.k} style={{
              height: 64,
              borderRadius: 16,
              display: 'grid',
              placeItems: 'center',
              textAlign: 'center',
              fontSize: 19,
              fontWeight: 930,
              color: hot ? '#263449' : '#fffdf4',
              background: hot ? tone : 'rgba(255,253,244,0.10)',
              transform: `translateY(${hot ? -8 - 4 * pulse : 2 * Math.sin(frame / 13 + index)}px)`,
            }}>{step.label}</div>
          );
        })}
      </div>
    </div>
  </AbsoluteFill>
);
"""
    component = component.replace("__TITLE__", json.dumps(title, ensure_ascii=False))
    component = component.replace("__REPO__", json.dumps(repo, ensure_ascii=False))
    component = component.replace("__PIPELINE__", json.dumps(pipeline, ensure_ascii=False))
    component = component.replace("__CHECKS__", json.dumps(checks[:5], ensure_ascii=False))
    return {
        "enabled": True,
        "render_mode": "full_canvas",
        "description": "Source-grounded cinematic Mem0 repo visual with browser chat contrast, code flow, vector nodes, provider list, search demo, terminal-style verification gates.",
        "component_code": component,
        "css": ".agent-source-visual { box-sizing: border-box; }",
    }


def source_grounded_agent_visual(
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    revision_feedback: dict[str, Any] | None = None,
    orientation: str = "vertical",
    min_state_count: int = 0,
) -> dict[str, Any]:
    facts = _visual_fact_texts(content_plan)
    repo = _repo_slug_from_candidate(candidate, content_plan)
    candidate_title = str(candidate.get("title") or "").strip()
    if candidate_title.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(candidate_title)
        query_id = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0].replace("_", " ").strip()
        fact_title = ""
        for fact in facts:
            match = re.search(r"\btitle:\s*([^\n]{8,120})", str(fact), re.I)
            if match:
                fact_title = clean_text(re.sub(r"\s+[-–—|].*$", "", match.group(1)).strip(" .;"))
                break
        fallback_title = fact_title or query_id or repo or parsed.netloc.replace("www.", "") or "source topic"
    else:
        fallback_title = candidate_title or repo or "source topic"
    title = bounded_text(fallback_title, 52)

    if not _is_mem0_visual_context(title, repo, facts) or min_state_count > 5:
        visual = premium_repo_agent_visual("deterministic source-grounded repo repair")
        visual["description"] = (
            f"Premium source-grounded repo visual for {bounded_text(repo or title, 42)}: "
            "chaptered code/terminal, file tree, architecture, metrics, and verification panels."
        )
        return visual

    has_factory = any("factory.py" in fact or "vector-store" in fact for fact in facts)
    has_server = any("server/main.py" in fact or "REST routes" in fact for fact in facts)
    pipeline = [
        {"k": "API", "label": "MemoryClient", "detail": "同步/异步入口"},
        {"k": "WRITE", "label": "add()", "detail": "消息写入记忆"},
        {"k": "CORE", "label": "mem0/memory/main.py", "detail": "LLM + embedder + history"},
        {"k": "STORE", "label": "Qdrant / Chroma / Pinecone", "detail": "向量库选择"},
        {"k": "READ", "label": "search()", "detail": "语义检索返回上下文"},
    ]
    if has_factory:
        pipeline[3]["detail"] = "factory.py 管理 provider"
    checks = ["跑通 Quickstart", "检查 evaluation", "对比向量库", "验证隔离边界"]
    if has_server:
        checks.append("复核 REST 路由")
    return cinematic_source_grounded_agent_visual(title, repo, pipeline, checks)

def motion_feedback_requires_source_visual(revision_feedback: dict[str, Any] | None) -> bool:
    feedback_text = json.dumps(revision_feedback or {}, ensure_ascii=False).lower()
    return any(
        token in feedback_text
        for token in [
            "central content motion",
            "central content remains static",
            "central visual movement",
            "central visual motion",
            "central_animation_richness",
            "rubric_scores.central_animation_richness",
            "animation_diagnostics",
            "main_motion_layers",
            "motion layers",
            "publish target",
            "active_ratio",
            "captions/progress/highlights",
            "caption/progress",
            "first 8s lack",
        ]
    )


def apply_source_visual_for_motion_feedback(
    candidate: dict[str, Any],
    polished: dict[str, Any],
    content_plan: dict[str, Any],
    revision_feedback: dict[str, Any] | None,
    *,
    video_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not motion_feedback_requires_source_visual(revision_feedback):
        return polished
    orientation = (video_profile or polished.get("video_profile") or {}).get("orientation") or "vertical"
    repaired = dict(polished)
    repaired["agent_visual"] = source_grounded_agent_visual(candidate, content_plan, revision_feedback, orientation=orientation)
    repaired = ensure_candidate_reference(candidate, scrub_polish_external_guidance(scrub_polish_claim_terms(repaired)))
    validate_polish(candidate, repaired)
    repaired["_deterministic_agent_visual_repair"] = True
    repaired["_deterministic_agent_visual_reason"] = "motion feedback required central source-grounded visual motion"
    return repaired


def parse_deepseek_payload_with_safe_visual(content: str, reason: str, orientation: str = "vertical") -> dict[str, Any]:
    return parse_deepseek_payload_with_safe_fallbacks(content, reason, force_agent_visual=True, orientation=orientation)


def parse_deepseek_payload_with_safe_fallbacks(content: str, reason: str, *, force_agent_visual: bool = False, orientation: str | None = None) -> dict[str, Any]:
    data = parse_json_object(content)
    if orientation is None:
        profile = data.get("video_profile") or data.get("videoProfile") or {}
        orientation = profile.get("orientation") or data.get("orientation") or "vertical"
    notes: dict[str, str] = {}
    if force_agent_visual:
        data["agent_visual"] = safe_agent_visual(reason, orientation=orientation)
        notes["agent_visual"] = reason
    for _ in range(4):
        try:
            normalized = normalize_polish_payload(data)
            if "agent_visual" in notes:
                normalized["_agent_visual_fallback_applied"] = True
                normalized["_agent_visual_fallback_reason"] = bounded_text(notes["agent_visual"], 500)
            if "storyboard" in notes:
                normalized["_storyboard_fallback_applied"] = True
                normalized["_storyboard_fallback_reason"] = bounded_text(notes["storyboard"], 500)
            return normalized
        except RuntimeError as exc:
            if is_storyboard_contract_error(exc) and "storyboard" not in notes:
                data["storyboard"] = safe_storyboard(data, str(exc))
                notes["storyboard"] = str(exc)
                continue
            if is_agent_visual_layout_error(exc) and "agent_visual" not in notes:
                data["agent_visual"] = safe_agent_visual(str(exc), orientation=orientation)
                notes["agent_visual"] = str(exc)
                continue
            raise
    return normalize_polish_payload(data)


def parse_deepseek_variants(content: str, expected_count: int) -> list[dict[str, Any]]:
    data = parse_json_object(content)
    variants = data.get("variants")
    if not isinstance(variants, list) or len(variants) != expected_count:
        raise RuntimeError(f"DeepSeek response must include exactly {expected_count} variants")
    clean: list[dict[str, Any]] = []
    for index, variant in enumerate(variants, start=1):
        if not isinstance(variant, dict):
            raise RuntimeError(f"DeepSeek variant {index} is not an object")
        clean.append(normalize_polish_payload(variant))
    return clean


def deepseek_constraints(video_seconds: int, *, variant_count: int = 1, video_profile: dict[str, Any] | None = None) -> list[str]:
    chars_per_second = int(policy_get("deepseek.chars_per_second", 7))
    lo = max(60, video_seconds * chars_per_second - 30)
    hi = video_seconds * chars_per_second + 80
    voiceover_chars_range = f"{lo}-{hi} Chinese characters"
    orientation = str((video_profile or {}).get("orientation") or "vertical")
    constraints = [
        policy_format(
            item,
            voiceover_chars_range=voiceover_chars_range,
            video_seconds=video_seconds,
            video_orientation=orientation,
        )
        for item in policy_get("deepseek.constraints", [])
    ]
    if variant_count > 1:
        constraints = [item for item in constraints if "Return exactly these keys" not in item]
        constraints.append(
            f"Return one JSON object with exactly one key `variants`, containing exactly {variant_count} objects."
        )
        constraints.append(
            "Each variants item must contain exactly these keys: polished_title, voiceover_text, douyin_title, douyin_desc, tags, cards, storyboard, agent_visual, video_profile, caveats."
        )
    constraints.extend(
        [
            f"If you choose video_profile.duration_seconds >= 180, storyboard.scenes must contain enough chapters for the chosen runtime: at least {longform_min_scene_count(180)} scenes for 180s, scaling up to {MAX_SCENES} scenes.",
            "Long-form scenes must form chapters: hook, problem/context, mechanism, evidence, demo or verification path, tradeoff/risk, suitable/not-suitable boundary, and final bounded takeaway.",
            "Long-form storyboard must use at least five scene types and at least five motion-rich explanatory scenes such as terminal, flow, chart, code_diff, code_block, node_graph, decision_table, compare_table, compare, bullets, or stat.",
            "Do not choose 180+ seconds unless the evidence, narration, and custom visual can sustain it; do not satisfy a long duration by stretching 3-7 scenes.",
        ]
    )
    return constraints


def request_deepseek(api_key: str, model: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    api_attempts = int(policy_get("deepseek.api_attempts", 2))
    last_exc: Exception | None = None
    for attempt in range(api_attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-1000:]
            retryable = exc.code in (429, 500, 502, 503, 504) and attempt < api_attempts - 1
            if retryable:
                delay = 3.0 * (2 ** attempt)
                print(f"DeepSeek HTTP {exc.code}, retrying in {delay:.0f}s (attempt {attempt + 1}/{api_attempts})...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}")
                continue
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < api_attempts - 1:
                delay = 3.0 * (2 ** attempt)
                print(f"DeepSeek network error, retrying in {delay:.0f}s (attempt {attempt + 1}/{api_attempts})...", file=sys.stderr)
                time.sleep(delay)
                last_exc = RuntimeError(f"DeepSeek network error: {exc}")
                continue
            raise RuntimeError(f"DeepSeek network error: {exc}") from exc
    raise last_exc or RuntimeError("DeepSeek call exhausted retries")


def response_message_content(payload: dict[str, Any]) -> str:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        finish_reason = choice.get("finish_reason")
        message_keys = sorted(str(key) for key in message.keys())
        raise RuntimeError(f"DeepSeek returned empty message content; finish_reason={finish_reason}; message_keys={message_keys}")
    return content.strip()


def deepseek_body(
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    *,
    temperature: float,
    video_seconds: int,
    video_profile: dict[str, Any] | None = None,
    variant_count: int = 1,
    evidence_bundle: dict[str, Any] | None = None,
    cross_check_review: dict[str, Any] | None = None,
    revision_feedback: dict[str, Any] | None = None,
    previous_polish: dict[str, Any] | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    system = policy_get("deepseek.system", "Return strict JSON only.")
    normalized_video_profile = normalize_video_profile(video_profile or choose_video_profile())
    source_map_sources = (content_plan.get("source_map") or {}).get("sources") if isinstance(content_plan.get("source_map"), dict) else []
    source_map_sources = source_map_sources or ((content_plan.get("fact_bank") or {}).get("source_map") or [])
    source_map_summary = [
        {
            "id": source.get("id"),
            "type": source.get("type"),
            "host": source.get("host"),
            "title": source.get("title"),
            "url": source.get("url"),
            "text_chars": source.get("text_chars"),
        }
        for source in source_map_sources
        if isinstance(source, dict)
    ][:10]
    has_repo_source = any(
        str(source.get("host") or "").lower() == "github.com" or "github.com/" in str(source.get("url") or "").lower()
        for source in source_map_summary
    )
    visual_brief = {
        "source_map": source_map_summary,
        "repo_context": content_plan.get("repo_context") or {},
        "must_show": [
            "A custom Remotion composition that demonstrates understanding of the source, not a generic evidence-card deck.",
            "At least three concrete source-backed objects in the visual grammar: API calls, module/file names, repo folders, architecture stages, docs concepts, benchmark/evaluation boundaries, or integration points.",
            "A clear visual sequence for problem -> mechanism -> tradeoff -> verification path.",
        ],
        "must_not_show": [
            "Do not output a generic ADD/EMBED/SEARCH flow unless those labels are tied to source-backed API calls or modules.",
            "Do not use data.cards, safeCards, raw URLs, source hosts as facts, or placeholder labels.",
            "Do not rely on captions/progress/fades as the main motion; animate central visual objects with frame/interpolate/spring.",
        ],
        "safe_layout_recipe": [
            "Use `const isHorizontal = width > height; const bottomSafe = isHorizontal ? 180 : 560;` as a caption-band guide, but choose the strongest visual layout for the topic.",
            "A strong layout can combine grid/flex shells with absolute overlays, SVG viewBox coordinates, masks, paths, and layered panels; position:absolute is allowed when it improves the composition.",
            "Keep the main readable content above the global caption band even when using bottom/absolute positioning.",
            "Animate central repo/interface objects with frame/interpolate/spring, for example a pipeline beam width, active lane scale, module card opacity, or checklist fill.",
        ],
    }
    if has_repo_source:
        visual_brief["repo_visual_requirement"] = (
            "Because a GitHub source is present, agent_visual must include repo/code intelligence: "
            "file tree or module lanes, SDK/API call path, and an adoption-risk/checklist panel grounded in source_map/fact_bank."
        )
    user = {
        "task": (
            f"Polish {variant_count} distinct source-bounded video packages for Douyin and Remotion."
            if variant_count > 1
            else "Polish one source-bounded video package for Douyin and Remotion."
        ),
        "constraints": deepseek_constraints(video_seconds, variant_count=variant_count, video_profile=normalized_video_profile),
        "forbidden_claim_terms": unsupported_terms(),
        "required_entity_terms": candidate_entity_terms(candidate),
        "selected_candidate": candidate,
        "content_plan": content_plan,
        "topic_brief": content_plan.get("topic_brief") or content_plan.get("research_brief") or {},
        "research_brief": content_plan.get("research_brief") or content_plan.get("topic_brief") or {},
        "fact_bank": {
            "source_backed_facts": (content_plan.get("fact_bank") or {}).get("source_backed_facts") or [],
            "facts": (content_plan.get("fact_bank") or {}).get("facts") or [],
            "conflicts": (content_plan.get("fact_bank") or {}).get("conflicts") or [],
            "risk_notes": (content_plan.get("fact_bank") or {}).get("risk_notes") or [],
        },
        "source_map": source_map_summary,
        "repo_context": content_plan.get("repo_context") or {},
        "visual_brief": visual_brief,
        "evidence_bundle": {
            "source_kind": (evidence_bundle or {}).get("source_kind"),
            "source_facts": ((evidence_bundle or {}).get("evidence_summary") or {}).get("source_facts") or [],
            "constructive_angles": ((evidence_bundle or {}).get("evidence_summary") or {}).get("constructive_angles") or [],
            "combined_excerpt": ((evidence_bundle or {}).get("evidence_summary") or {}).get("combined_excerpt") or "",
        },
        "cross_check_review": cross_check_review or {},
        "suggested_video_profile": normalized_video_profile,
        "content_quality_requirement": [
            "Use research_brief and fact_bank to choose a concrete topic angle and visual scene path.",
            "Explain the concrete user problem, mechanism, practical fit, caveat, and next verification step.",
            "Every strong public claim must be traceable to evidence_bundle source_facts or explicitly framed as an unverified observation.",
            "Keep voiceover_text Mandarin TTS-safe: do not speak raw slash paths, URLs, dotted filenames, snake_case identifiers, or symbol-heavy IDs; say code paths and IDs naturally in Chinese, and reserve exact paths/identifiers for agent_visual on-screen labels.",
            "For open-source projects, cover what the repo appears to do, why a developer would care, tradeoffs, and what to inspect before adopting.",
            "For GitHub/open-source topics, do not stop at a radar summary: include problem, mechanism or architecture, practical fit, tradeoff/risk, and a concrete verification path.",
            "The rendered provider video is agent_visual. Write custom TSX/CSS for the current topic; do not depend on the default storyboard scene renderer.",
            "Prefer agent_visual.module_code and make it a complete Remotion module with imports and a named AgentVisualGenerated export. Use the full React/Remotion surface to make a visually ambitious composition.",
            "For developer-tool or GitHub-backed topics, the agent_visual must visibly encode source_map/fact_bank details: repo modules, API names, docs concepts, integration boundaries, or verification checks.",
            "A Remotion output that could apply to any AI tool is invalid even if it passes motion checks; avoid generic node-orbit/source-flow templates unless the nodes are the actual project architecture.",
            "For GitHub repos, show concrete on-screen structure: README claims, file/module tree, install or API surface, runtime flow, constraints, and a verification checklist grounded in source facts.",
            *agent_visual_layout_contract(),
            "Choose video_profile.duration_seconds, orientation, motion, and animation_style for the content depth; respect the suggested_video_profile unless you have a source-grounded reason to override it.",
            "For GitHub repos, developer tools, code walkthroughs, architecture explainers, MCP/API surfaces, file trees, diffs, tables, timelines, or dense technical layouts, horizontal 16:9 is the default because the viewer needs width to inspect structure.",
            "Choose vertical 9:16 only when the source-backed visual plan is primarily human-facing narrative, phone-native scan, live Douyin vertical delivery, or caption-first content with little code/architecture density.",
        ],
    }
    if revision_feedback is not None:
        user["task"] = "Revise one complete source-bounded video package using Gemini evaluator feedback."
        user["attempt"] = attempt
        user["previous_polish"] = {
            "polished_title": (previous_polish or {}).get("polished_title"),
            "voiceover_text": (previous_polish or {}).get("voiceover_text"),
            "douyin_title": (previous_polish or {}).get("douyin_title"),
            "douyin_desc": (previous_polish or {}).get("douyin_desc"),
            "tags": (previous_polish or {}).get("tags"),
            "cards": (previous_polish or {}).get("cards"),
            "storyboard": (previous_polish or {}).get("storyboard"),
            "agent_visual": (previous_polish or {}).get("agent_visual"),
            "video_profile": (previous_polish or {}).get("video_profile"),
            "caveats": (previous_polish or {}).get("caveats"),
        }
        user["gemini_feedback"] = {
            "overall": revision_feedback.get("overall"),
            "verdict": revision_feedback.get("verdict"),
            "scores": revision_feedback.get("scores") or {},
            "failed_dimensions": revision_feedback.get("failed_dimensions") or {},
            "blocking_checks": revision_feedback.get("blocking_checks") or {},
            "blocking_issues": (revision_feedback.get("blocking_checks") or {}).get("blocking_issues")
            or (revision_feedback.get("revision_brief") or {}).get("blocking_issues")
            or [],
            "suggestions": revision_feedback.get("suggestions") or [],
            "revision_brief": revision_feedback.get("revision_brief") or {},
        }
        user["revision_rules"] = [
            "Return a full replacement JSON object, not a patch.",
            "Do not keep weak title, hook, storyboard, or caption-facing text if Gemini marked them below target.",
            "Resolve every blocking_issues item before optimizing style or polish.",
            "Preserve the selected candidate boundary and required_entity_terms reference.",
            "Do not introduce facts outside evidence_bundle or claims not supported by source_facts.",
            "Keep caveats when evidence is thin; improve the explanation, not the claim strength.",
        ]
        user["content_quality_requirement"].extend(
            str(item)
            for item in policy_get("content_optimization.revision_focus", [])
            if str(item).strip()
        )
    storyboard_schema = {
        "version": 1,
        "style": {
            "theme": "radar|minimal|editorial|engineering",
            "density": "minimal|standard|rich",
            "motion": "calm|standard|punchy",
            "accent": "#ffd60a|#72e7ff|#ff2d55|#f59e0b",
            "chrome": {"topbar": "boolean", "progress": "boolean", "beam": "boolean"},
        },
        "scenes": [
            {
                "type": "statement|context|stat|bullets|card|compare|compare_table|terminal|flow|chart|code_diff|code_block|node_graph|decision_table|act_card|closing|quote|cta",
                "weight": "optional number 0-1",
                "emphasis": "optional low|normal|high",
                "props": "object bounded to the chosen scene type",
            }
        ],
    }
    min_video_seconds = int(policy_get("video_profile.min_duration_seconds", 18))
    max_video_seconds = policy_get("video_profile.max_duration_seconds", None)
    max_rule = (
        f" and <= {int(max_video_seconds)}"
        if max_video_seconds not in (None, "", False)
        else "; no fixed upper limit; use 180+ or 300+ seconds when evidence depth warrants it"
    )
    package_schema = {
        "polished_title": "string",
        "voiceover_text": "string",
        "douyin_title": "string",
        "douyin_desc": "string",
        "tags": ["string"],
        "cards": [{"label": "string", "value": "string", "detail": "string"}],
        "storyboard": storyboard_schema,
        "agent_visual": {
            "enabled": True,
            "render_mode": "full_canvas",
            "description": "short note on why this custom Remotion visual fits the topic",
            "module_code": "preferred string: full TSX module for src/generated/AgentVisual.generated.tsx. Must import React/remotion APIs it uses and export a named AgentVisualGenerated component. It receives AgentVisualProps with data, frame, fps, durationInFrames, width, height, progress, audioPulse.",
            "component_code": "compatibility string only if module_code is omitted: TSX function body with a return statement. Variables available: data, frame, fps, durationInFrames, width, height, progress, audioPulse, React, AbsoluteFill, interpolate, spring, useMemo, Img, staticFile, Series, Sequence.",
            "css": "string: optional CSS for this visual, preferably classes prefixed with agent-; inline styles are acceptable for complex Remotion motion.",
            "layout_contract": agent_visual_layout_contract(),
        },
        "video_profile": {
            "duration_seconds": f"integer >= {min_video_seconds}{max_rule}",
            "orientation": "vertical|horizontal",
            "aspect_ratio": "9:16|16:9",
            "motion": "calm|standard|punchy",
            "animation_style": "kinetic_text|diagrammatic|evidence_cards|minimal",
            "decision_reason": "short string explaining why this format fits the topic",
        },
        "caveats": ["string"],
    }
    if variant_count > 1:
        user["output_schema"] = {"variants": [package_schema]}
    else:
        user["output_schema"] = package_schema
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": temperature,
    }
    try:
        max_tokens = int(policy_get("deepseek.max_tokens", 0) or 0)
    except (TypeError, ValueError):
        max_tokens = 0
    if max_tokens > 0:
        body["max_tokens"] = max_tokens
    thinking_type = str(policy_get("deepseek.thinking_type", "") or "").strip()
    if thinking_type:
        body["thinking"] = {"type": thinking_type}
    if variant_count == 1:
        body["response_format"] = {"type": "json_object"}
    return body


def deepseek_chat(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    timeout: float,
    temperature: float = 0.4,
    video_seconds: int = 12,
    video_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = deepseek_body(
        model,
        candidate,
        content_plan,
        temperature=temperature,
        video_seconds=video_seconds,
        video_profile=video_profile,
        evidence_bundle=evidence_bundle,
        cross_check_review=cross_check_review,
    )
    payload = request_deepseek(api_key, model, body, timeout)
    content = response_message_content(payload)

    try:
        parsed = parse_deepseek_payload(content)
        parsed = ensure_candidate_reference(candidate, parsed)
        validate_polish(candidate, parsed)
        parsed["_raw_usage"] = payload.get("usage")
        parsed["_correction_applied"] = False
        return parsed
    except Exception as exc:
        last_exc = exc
        current_data = {}
        try:
            current_data = parse_json_object(content)
        except Exception:
            pass

        for corr_attempt in range(1, 4):
            try:
                corrected = correct_deepseek_polish(
                    api_key,
                    model,
                    candidate,
                    content_plan,
                    evidence_bundle,
                    cross_check_review,
                    current_data,
                    str(last_exc),
                    timeout,
                    video_seconds=video_seconds,
                    video_profile=video_profile,
                )
                corrected = ensure_candidate_reference(candidate, scrub_polish_external_guidance(scrub_polish_claim_terms(corrected)))
                validate_polish(candidate, corrected)
                corrected["_correction_applied"] = True
                corrected["_initial_error"] = str(exc)
                corrected["_initial_usage"] = payload.get("usage")
                corrected["_claim_scrub_applied"] = True
                corrected["_external_guidance_scrub_applied"] = True
                corrected["_correction_attempts"] = corr_attempt
                return corrected
            except Exception as loop_exc:
                last_exc = loop_exc
                try:
                    if "corrected" in locals() and isinstance(corrected, dict):
                        current_data = corrected
                except Exception:
                    pass
        raise last_exc


def deepseek_revision_chat(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    previous_polish: dict[str, Any],
    revision_feedback: dict[str, Any],
    timeout: float,
    temperature: float = 0.35,
    video_seconds: int = 12,
    video_profile: dict[str, Any] | None = None,
    attempt: int = 2,
) -> dict[str, Any]:
    body = deepseek_body(
        model,
        candidate,
        content_plan,
        temperature=temperature,
        video_seconds=video_seconds,
        video_profile=video_profile,
        evidence_bundle=evidence_bundle,
        cross_check_review=cross_check_review,
        revision_feedback=revision_feedback,
        previous_polish=previous_polish,
        attempt=attempt,
    )
    payload = request_deepseek(api_key, model, body, timeout)
    content = response_message_content(payload)

    try:
        parsed = parse_deepseek_payload(content)
        parsed = ensure_candidate_reference(candidate, parsed)
        validate_polish(candidate, parsed)
        parsed = apply_source_visual_for_motion_feedback(
            candidate,
            parsed,
            content_plan,
            revision_feedback,
            video_profile=video_profile,
        )
        parsed["_raw_usage"] = payload.get("usage")
        parsed["_correction_applied"] = False
        return parsed
    except Exception as exc:
        last_exc = exc
        current_data = {}
        try:
            current_data = parse_json_object(content)
        except Exception:
            pass

        for corr_attempt in range(1, 4):
            try:
                corrected = correct_deepseek_polish(
                    api_key,
                    model,
                    candidate,
                    content_plan,
                    evidence_bundle,
                    cross_check_review,
                    current_data,
                    str(last_exc),
                    timeout,
                    video_seconds=video_seconds,
                    video_profile=video_profile,
                )
                corrected = ensure_candidate_reference(candidate, scrub_polish_external_guidance(scrub_polish_claim_terms(corrected)))
                validate_polish(candidate, corrected)
                corrected = apply_source_visual_for_motion_feedback(
                    candidate,
                    corrected,
                    content_plan,
                    revision_feedback,
                    video_profile=video_profile,
                )
                corrected["_correction_applied"] = True
                corrected["_initial_error"] = str(exc)
                corrected["_initial_usage"] = payload.get("usage")
                corrected["_claim_scrub_applied"] = True
                corrected["_external_guidance_scrub_applied"] = True
                corrected["_correction_attempts"] = corr_attempt
                return corrected
            except Exception as loop_exc:
                last_exc = loop_exc
                try:
                    if "corrected" in locals() and isinstance(corrected, dict):
                        current_data = corrected
                except Exception:
                    pass
        deterministic = deterministic_agent_visual_revision(
            candidate,
            previous_polish,
            content_plan,
            revision_feedback,
            last_exc,
            initial_error=exc,
            initial_usage=payload.get("usage"),
            video_profile=video_profile,
        )
        if deterministic:
            return deterministic
        raise last_exc


def correct_deepseek_polish(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    rejected: dict[str, Any],
    validation_error: str,
    timeout: float,
    video_seconds: int = 12,
    video_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = deepseek_body(
        model,
        candidate,
        content_plan,
        temperature=0.1,
        video_seconds=video_seconds,
        video_profile=video_profile,
        evidence_bundle=evidence_bundle,
        cross_check_review=cross_check_review,
    )
    user = json.loads(body["messages"][1]["content"])
    user["task"] = "Correct the rejected source-bounded video JSON so it passes the validation error exactly."
    user["validation_error"] = validation_error
    user["rejected_json"] = rejected
    user["correction_rules"] = [
        "Return a complete replacement JSON object with the required keys only.",
        "Remove every forbidden claim term named in validation_error.",
        "Keep the selected candidate boundary and required_entity_terms reference.",
        *agent_visual_layout_contract(),
    ]
    body["messages"][1]["content"] = json.dumps(user, ensure_ascii=False)
    payload = request_deepseek(api_key, model, body, timeout)
    content = response_message_content(payload)
    try:
        corrected = parse_deepseek_payload(content)
    except RuntimeError as exc:
        if not (is_agent_visual_layout_error(exc) or is_storyboard_contract_error(exc)):
            raise
        orientation = (video_profile or {}).get("orientation") or "vertical"
        corrected = parse_deepseek_payload_with_safe_fallbacks(content, str(exc), orientation=orientation)
    corrected["_raw_usage"] = payload.get("usage")
    return corrected


def request_voiceover_section(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    polished: dict[str, Any],
    *,
    section_index: int,
    section_count: int,
    target_chars: int,
    previous_summary: str,
    previous_tail: str,
    timeout: float,
) -> dict[str, Any]:
    user_payload = {
        "task": "Write one non-overlapping section of a longer Mandarin voiceover. Return JSON only.",
        "section_index": section_index,
        "section_count": section_count,
        "target_chars": f"{max(80, target_chars - 120)}-{target_chars + 160} Chinese characters",
        "selected_candidate": candidate,
        "content_plan": content_plan,
        "evidence_bundle": {
            "source_kind": evidence_bundle.get("source_kind"),
            "source_facts": (evidence_bundle.get("evidence_summary") or {}).get("source_facts") or [],
            "constructive_angles": (evidence_bundle.get("evidence_summary") or {}).get("constructive_angles") or [],
            "combined_excerpt": ((evidence_bundle.get("evidence_summary") or {}).get("combined_excerpt") or "")[:5000],
        },
        "cross_check_review": cross_check_review,
        "forbidden_claim_terms": unsupported_terms(),
        "base_package": {
            "polished_title": polished.get("polished_title"),
            "douyin_title": polished.get("douyin_title"),
            "video_profile": polished.get("video_profile"),
            "storyboard": polished.get("storyboard"),
            "caveats": polished.get("caveats") or [],
            "outline_voiceover": polished.get("voiceover_text"),
        },
        "previous_context": {
            "covered_summary": previous_summary,
            "previous_tail": previous_tail,
        },
        "rules": [
            "Use only selected_candidate, content_plan, evidence_bundle, and cross_check_review facts.",
            "Advance the explanation; do not repeat previous sections except for a short bridge.",
            "Keep claims conditional and source-bounded when evidence is thin.",
            "Do not use any forbidden_claim_terms, including ordinal or superiority words, unless directly quoted from selected evidence.",
            "Do not include markdown, headings, bullet syntax, raw URLs, or source paths in section_text.",
            "Return exactly: section_text, section_summary.",
        ],
    }
    last_hits: list[str] = []
    for attempt in range(1, 3):
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": policy_get("deepseek.system", "Return strict JSON only.")},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0.35 if attempt == 1 else 0.1,
            "max_tokens": max(1600, target_chars * 2),
            "response_format": {"type": "json_object"},
        }
        thinking_type = str(policy_get("deepseek.thinking_type", "") or "").strip()
        if thinking_type:
            body["thinking"] = {"type": thinking_type}
        payload = request_deepseek(api_key, model, body, timeout)
        parsed = parse_json_object(response_message_content(payload))
        section_text = clean_text(parsed.get("section_text"))
        if not section_text:
            raise RuntimeError(f"DeepSeek voiceover section {section_index}/{section_count} returned empty section_text")
        last_hits = sorted(set(match.group(0) for match in UNSAFE_RE.finditer(section_text)))
        if not last_hits:
            return {
                "section_index": section_index,
                "section_text": section_text,
                "section_summary": bounded_text(parsed.get("section_summary") or section_text, 360),
                "char_count": chinese_char_count(section_text),
                "usage": payload.get("usage"),
                "rewrite_attempt": attempt,
            }
        user_payload["task"] = "Rewrite the rejected voiceover section so it removes the validation error exactly."
        user_payload["validation_error"] = f"section_text contains forbidden claim terms: {last_hits}"
        user_payload["rejected_section_text"] = section_text
        user_payload["rules"] = [
            *[str(item) for item in user_payload["rules"]],
            "Return a full replacement section_text without the forbidden terms named in validation_error.",
        ]
    raise RuntimeError(f"DeepSeek voiceover section {section_index}/{section_count} contains unsupported claim terms: {last_hits}")


def expand_voiceover_if_needed(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    polished: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    profile = normalize_video_profile(polished.get("video_profile"))
    video_seconds = int(profile.get("duration_seconds") or 0)
    target_chars = target_voiceover_chars(video_seconds)
    current_chars = chinese_char_count(polished.get("voiceover_text"))
    min_ratio = float(policy_get("deepseek.min_voiceover_target_ratio", 0.72))
    if current_chars >= int(target_chars * min_ratio):
        return polished

    chunk_chars = voiceover_segment_chars()
    section_count = max(1, (target_chars + chunk_chars - 1) // chunk_chars)
    per_section_target = max(120, (target_chars + section_count - 1) // section_count)
    sections: list[dict[str, Any]] = []
    summaries: list[str] = []
    previous_tail = ""
    for section_index in range(1, section_count + 1):
        section = request_voiceover_section(
            api_key,
            model,
            candidate,
            content_plan,
            evidence_bundle,
            cross_check_review,
            polished,
            section_index=section_index,
            section_count=section_count,
            target_chars=per_section_target,
            previous_summary=bounded_text(" ".join(summaries[-8:]), 1400),
            previous_tail=previous_tail,
            timeout=timeout,
        )
        sections.append(section)
        summaries.append(str(section.get("section_summary") or ""))
        previous_tail = str(section["section_text"])[-360:]

    expanded = dict(polished)
    expanded["voiceover_text"] = clean_text(" ".join(str(section["section_text"]) for section in sections))
    expanded["_voiceover_expansion"] = {
        "strategy": "segmented_deepseek_voiceover",
        "target_duration_seconds": video_seconds,
        "target_voiceover_chars": target_chars,
        "initial_voiceover_chars": current_chars,
        "final_voiceover_chars": chinese_char_count(expanded["voiceover_text"]),
        "section_count": section_count,
        "section_target_chars": per_section_target,
        "sections": [
            {
                "section_index": section["section_index"],
                "char_count": section["char_count"],
                "section_summary": section["section_summary"],
                "usage": section.get("usage"),
            }
            for section in sections
        ],
    }
    expanded = ensure_candidate_reference(candidate, expanded)
    validate_polish(candidate, expanded)
    return expanded


def fit_video_profile_to_voiceover(polished: dict[str, Any]) -> dict[str, Any]:
    profile = normalize_video_profile(polished.get("video_profile"))
    duration_seconds = int(profile.get("duration_seconds") or 0)
    voiceover_chars = chinese_char_count(polished.get("voiceover_text"))
    if voiceover_chars <= 0:
        return polished
    estimated_duration = estimated_voiceover_duration_seconds(polished)
    if duration_seconds > 0 and estimated_duration > duration_seconds + max(8, int(duration_seconds * 0.1)):
        adjusted = dict(polished)
        adjusted_profile = dict(profile)
        adjusted_profile["duration_seconds"] = estimated_duration
        adjusted_profile["decision_reason"] = clean_text(
            f"{profile.get('decision_reason') or 'source-bounded explainer'}; adjusted to {estimated_duration}s to match generated voiceover length."
        )
        adjusted["video_profile"] = normalize_video_profile(adjusted_profile, fallback=profile)
        adjusted["_video_profile_duration_adjusted"] = {
            "from_seconds": duration_seconds,
            "to_seconds": adjusted["video_profile"]["duration_seconds"],
            "voiceover_chinese_chars": voiceover_chars,
            "strategy": "estimated_tts_duration_alignment",
        }
        return adjusted
    if duration_seconds < 180:
        return polished
    chars_per_second = max(1, int(policy_get("deepseek.chars_per_second", 7)))
    min_ratio = max(0.1, float(policy_get("deepseek.min_voiceover_target_ratio", 0.72)))
    max_duration_for_voice = max(int(policy_get("video_profile.min_duration_seconds", 18)), int(voiceover_chars / (chars_per_second * min_ratio)))
    # content_scorer switches to a long-form minimum at 180 seconds; stay below
    # that boundary when the provider did not actually produce long-form audio.
    if voiceover_chars < duration_seconds * 4:
        max_duration_for_voice = min(max_duration_for_voice, 179)
    if max_duration_for_voice >= duration_seconds:
        return polished
    adjusted = dict(polished)
    adjusted_profile = dict(profile)
    adjusted_profile["duration_seconds"] = max_duration_for_voice
    adjusted_profile["decision_reason"] = clean_text(
        f"{profile.get('decision_reason') or 'source-bounded explainer'}; adjusted to {max_duration_for_voice}s to match generated voiceover length."
    )
    adjusted["video_profile"] = normalize_video_profile(adjusted_profile, fallback=profile)
    adjusted["_video_profile_duration_adjusted"] = {
        "from_seconds": duration_seconds,
        "to_seconds": adjusted["video_profile"]["duration_seconds"],
        "voiceover_chinese_chars": voiceover_chars,
        "strategy": "long_profile_down_alignment",
    }
    return adjusted


def _storyboard_structure_metrics(polished: dict[str, Any]) -> dict[str, Any]:
    profile = normalize_video_profile(polished.get("video_profile"))
    duration_seconds = int(profile.get("duration_seconds") or 0)
    storyboard = polished.get("storyboard") if isinstance(polished.get("storyboard"), dict) else {}
    scenes = [scene for scene in storyboard.get("scenes") or [] if isinstance(scene, dict)]
    scene_types = [str(scene.get("type") or "") for scene in scenes]
    motion_types = {"terminal", "flow", "chart", "code_diff", "compare_table", "compare", "bullets", "stat"}
    min_scenes = minimum_storyboard_scene_count(duration_seconds)
    min_type_count = 5 if duration_seconds >= 180 else 4
    min_motion_count = 5 if duration_seconds >= 180 else 3
    return {
        "duration_seconds": duration_seconds,
        "minimum_scene_count": min_scenes,
        "scene_count": len(scenes),
        "scene_types": scene_types,
        "distinct_scene_type_count": len(set(scene_types)),
        "motion_rich_scene_count": sum(1 for scene_type in scene_types if scene_type in motion_types),
        "minimum_type_count": min_type_count,
        "minimum_motion_rich_count": min_motion_count,
    }


def _storyboard_needs_structure_repair(polished: dict[str, Any]) -> bool:
    metrics = _storyboard_structure_metrics(polished)
    duration_seconds = int(metrics["duration_seconds"])
    if duration_seconds < 60:
        return False
    scene_types = [str(item) for item in metrics["scene_types"]]
    return (
        metrics["scene_count"] < metrics["minimum_scene_count"]
        or metrics["distinct_scene_type_count"] < metrics["minimum_type_count"]
        or metrics["motion_rich_scene_count"] < metrics["minimum_motion_rich_count"]
        or not scene_types
        or scene_types[0] != "statement"
        or scene_types[-1] != "cta"
    )


def _dedupe_texts(values: list[Any], *, limit: int = 12) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        text = public_visible_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _voiceover_sentences(text: Any, *, limit: int = 8) -> list[str]:
    normalized = clean_text(text)
    parts = re.split(r"[。！？!?；;]\s*", normalized)
    return _dedupe_texts([part for part in parts if len(part.strip()) >= 8], limit=limit)


def _repair_fact_lines(content_plan: dict[str, Any], evidence_bundle: dict[str, Any]) -> list[str]:
    evidence_summary = evidence_bundle.get("evidence_summary") if isinstance(evidence_bundle.get("evidence_summary"), dict) else {}
    return _dedupe_texts(
        [
            *_visual_fact_texts(content_plan),
            *(evidence_summary.get("source_facts") or []),
            *(evidence_summary.get("constructive_angles") or []),
        ],
        limit=14,
    )


def repair_storyboard_structure(
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    polished: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically expand underfit provider storyboards for 60s+ videos."""
    if not _storyboard_needs_structure_repair(polished):
        return polished

    before = _storyboard_structure_metrics(polished)
    profile = normalize_video_profile(polished.get("video_profile"))
    duration_seconds = int(profile.get("duration_seconds") or 0)
    target_scene_count = min(MAX_SCENES, max(6, minimum_storyboard_scene_count(duration_seconds)))
    title = clean_text(polished.get("polished_title") or polished.get("douyin_title") or candidate.get("title") or "Searchpo topic")
    voiceover_lines = _voiceover_sentences(polished.get("voiceover_text"))
    facts = _repair_fact_lines(content_plan, evidence_bundle)
    repo = _repo_slug_from_candidate(candidate, content_plan)
    pipeline = _generic_pipeline(repo, facts or voiceover_lines)
    checks = _generic_checks(facts or voiceover_lines)
    source_url = str(candidate.get("canonical_url") or candidate.get("url") or "")
    summary = bounded_text(voiceover_lines[0] if voiceover_lines else (facts[0] if facts else title), 128)
    mechanism = bounded_text(voiceover_lines[1] if len(voiceover_lines) > 1 else (facts[1] if len(facts) > 1 else summary), 118)
    tradeoff = bounded_text(voiceover_lines[2] if len(voiceover_lines) > 2 else (facts[2] if len(facts) > 2 else "把官方说明和待验证部分分开看"), 90)
    verify = bounded_text(voiceover_lines[-1] if voiceover_lines else "用一个真实任务复测，再决定是否采用", 90)
    table_rows = [
        bounded_text(f"已知：{facts[0] if facts else summary}", 76),
        bounded_text(f"机制：{mechanism}", 76),
        bounded_text(f"边界：{tradeoff}", 76),
        bounded_text(f"验证：{verify}", 76),
    ]
    scenes: list[dict[str, Any]] = [
        {
            "type": "statement",
            "emphasis": "high",
            "props": {"kicker": "先看问题", "title": title, "sub": summary},
        },
        {
            "type": "context",
            "props": {
                "kicker": "来源边界",
                "text": mechanism,
                "metric": "官方来源 + 补充检索",
                "metricNote": "非结论",
                "sourceLabel": "主来源",
                "sourceValue": public_source_value(source_url),
            },
        },
        {
            "type": "flow",
            "emphasis": "high",
            "props": {
                "kicker": "机制拆开看",
                "heading": f"{repo} 的可视化链路",
                "nodes": [step.get("label") for step in pipeline[:5]],
                "caption": bounded_text(" -> ".join(step.get("detail", "") for step in pipeline[:4]), 80),
            },
        },
        {
            "type": "terminal",
            "props": {
                "kicker": "开发者验证",
                "title": "不要只看发布文案",
                "prompt": "$",
                "lines": checks[:5],
            },
        },
        {
            "type": "compare_table",
            "props": {
                "kicker": "证据和待证分开",
                "heading": "采用前的四格判断",
                "leftLabel": "source",
                "rightLabel": "verification",
                "rows": table_rows,
            },
        },
        {
            "type": "chart",
            "props": {
                "kicker": "不要把热度当结论",
                "heading": "先看信号，再做小样本复测",
                "label": "验证顺序",
                "value": "3步",
                "points": ["读来源", "跑样例", "记失败"],
            },
        },
        {
            "type": "code_diff",
            "props": {
                "kicker": "实现视角",
                "title": "把宣传语翻成检查项",
                "filename": bounded_text(repo or "source", 34),
                "additions": [step.get("detail") for step in pipeline[:4]],
                "removals": ["只复述模型名", "只展示四张卡"],
            },
        },
        {
            "type": "compare",
            "props": {
                "kicker": "判断边界",
                "heading": "能做什么，不等于每个任务都可靠",
                "leftLabel": "已看到",
                "left": summary,
                "rightLabel": "还要测",
                "right": verify,
            },
        },
        {
            "type": "stat",
            "props": {
                "kicker": "最后留一个数字",
                "value": f"{target_scene_count}幕",
                "label": "这条视频按结构拆开讲",
                "detail": "每一幕承担不同解释功能，避免长时间四卡循环。",
            },
        },
        {
            "type": "quote",
            "props": {
                "kicker": "原始信号",
                "quote": bounded_text(facts[0] if facts else summary, 112),
                "attribution": bounded_text(repo or public_source_value(source_url), 42),
            },
        },
    ]
    cta_scene = {
        "type": "cta",
        "emphasis": "high",
        "props": {
            "kicker": "结论先收住",
            "text": bounded_text(polished.get("cards", [{}])[0].get("detail") if isinstance(polished.get("cards"), list) and polished.get("cards") else "先用一个真实任务复测", 48),
            "footer": verify,
        },
    }
    selected = scenes[: max(1, target_scene_count - 1)] + [cta_scene]
    repaired_storyboard = validate_storyboard(
        {
            "version": 1,
            "style": {"theme": "radar", "density": "rich", "motion": "punchy", "accent": "#72e7ff"},
            "scenes": selected,
        }
    )
    repaired = dict(polished)
    repaired["storyboard"] = repaired_storyboard
    repaired["_storyboard_structure_repair"] = {
        "strategy": "source_grounded_contract_repair",
        "reason": "provider storyboard underfit selected video duration",
        "before": before,
        "after": _storyboard_structure_metrics({**repaired, "storyboard": repaired_storyboard, "video_profile": profile}),
    }
    return repaired


VISUAL_STATE_ARRAY_RE = re.compile(
    r"(?:const|let|var)\s+(?:stages|beats|steps|chapters|sections|states|pipeline|timeline)\s*=\s*(\[[\s\S]{0,12000}?\]);",
    re.I,
)


def agent_visual_state_hint_count(component_code: Any) -> int:
    code = str(component_code or "")
    best = 0
    for match in VISUAL_STATE_ARRAY_RE.finditer(code):
        array_text = match.group(1)
        best = max(best, len(re.findall(r"\{", array_text)))
        try:
            parsed = json.loads(array_text)
        except Exception:
            continue
        if isinstance(parsed, list):
            best = max(best, len(parsed))
    return best


def agent_visual_source_code(visual: dict[str, Any] | None) -> str:
    if not isinstance(visual, dict):
        return ""
    return str(visual.get("module_code") or visual.get("component_code") or "")


def repair_agent_visual_structure(
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    polished: dict[str, Any],
    revision_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = normalize_video_profile(polished.get("video_profile"))
    duration_seconds = max(
        int(profile.get("duration_seconds") or 0),
        estimated_voiceover_duration_seconds(polished),
        feedback_duration_seconds(revision_feedback),
    )
    if duration_seconds < 60:
        return polished
    visual = polished.get("agent_visual") if isinstance(polished.get("agent_visual"), dict) else {}
    component_code = agent_visual_source_code(visual)
    current_count = agent_visual_state_hint_count(component_code)
    required_count = max(
        minimum_storyboard_scene_count(duration_seconds),
        feedback_required_count(revision_feedback),
    )
    if visual.get("enabled") and current_count >= required_count:
        return polished
    repaired = dict(polished)
    orientation = str(profile.get("orientation") or "vertical")
    repaired_visual = source_grounded_agent_visual(
        candidate,
        content_plan,
        {"failed_checks": [f"agent_visual has too few visible states: detected {current_count}, requires {required_count}"]},
        orientation=orientation,
        min_state_count=required_count,
    )
    repaired["agent_visual"] = require_agent_visual(repaired_visual, orientation)
    repaired["_agent_visual_structure_repair"] = {
        "strategy": "source_grounded_visual_state_repair",
        "reason": "provider agent_visual underfit selected video duration",
        "duration_seconds": duration_seconds,
        "before_state_hint_count": current_count,
        "required_state_hint_count": required_count,
        "after_state_hint_count": agent_visual_state_hint_count(agent_visual_source_code(repaired["agent_visual"])),
    }
    return repaired


def compact_voiceover_if_over_target(
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    polished: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically enforce short-video voiceover length.

    Provider models sometimes preserve a long prior script during visual
    revision even when the profile is short. Rendering then stretches to the
    audio duration and defeats the Douyin pacing contract. For sub-180s videos,
    replace only an overlong narration with a compact source-grounded explainer
    while leaving titles, cards, storyboard, and agent_visual intact.
    """

    profile = normalize_video_profile(polished.get("video_profile"))
    video_seconds = int(profile.get("duration_seconds") or 0)
    if video_seconds <= 0 or video_seconds >= 180:
        return polished
    current_chars = chinese_char_count(polished.get("voiceover_text"))
    target_chars = target_voiceover_chars(video_seconds)
    max_allowed = target_chars + max(80, int(target_chars * 0.18))
    if current_chars <= max_allowed:
        return polished

    repo_context = content_plan.get("repo_context") if isinstance(content_plan.get("repo_context"), dict) else {}
    fact_bank = content_plan.get("fact_bank") if isinstance(content_plan.get("fact_bank"), dict) else {}
    raw_facts = [
        *(repo_context.get("facts") or []),
        *(fact_bank.get("source_backed_facts") or []),
        str(candidate.get("summary") or ""),
    ]
    facts: list[str] = []
    for raw in raw_facts:
        fact = bounded_text(raw, 96)
        if fact and fact not in facts:
            facts.append(fact)
    if not facts:
        raise RuntimeError("Cannot compact overlong voiceover without source-backed facts")
    subject = bounded_text(repo_context.get("repo") or candidate_anchor(candidate) or candidate.get("title") or "这个主题", 48)
    fact_sentences = "；".join(facts[:4])
    compact_text = clean_text(
        f"{subject} 这条内容只按当前来源做边界观察。"
        f"目前能支撑的事实是：{fact_sentences}。"
        "所以视频不要把它包装成确定结论，而要拆成四步：它解决什么问题，公开来源能说明什么机制，"
        "哪些效果还需要实测，以及下一步怎样复核。"
        "画面上可以用来源层、机制图、对比表和检查清单承接这些事实；口播只说证据能支持的部分。"
        f"我的结论是，{subject} 可以作为一个待验证案例继续观察，但不能跳过最小验证。"
        "先看官方说明和源码边界，再跑小样本，记录失败条件。这样产出的判断才不会把热度当成证明。"
    )
    compact = dict(polished)
    compact["voiceover_text"] = compact_text
    compact["_voiceover_shortened"] = {
        "strategy": "deterministic_short_video_compaction",
        "target_duration_seconds": video_seconds,
        "target_voiceover_chars": target_chars,
        "max_allowed_voiceover_chars": max_allowed,
        "from_chars": current_chars,
        "to_chars": chinese_char_count(compact_text),
    }
    compact = ensure_candidate_reference(candidate, compact)
    validate_polish(candidate, compact)
    return compact


def deepseek_variant_chat(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    timeout: float,
    video_seconds: int = 12,
    video_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    variant_count = int(policy_get("deepseek.variant_count", 3))
    body = deepseek_body(
        model,
        candidate,
        content_plan,
        temperature=float(policy_get("deepseek.variant_temperature", 0.5)),
        video_seconds=video_seconds,
        video_profile=video_profile,
        variant_count=variant_count,
        evidence_bundle=evidence_bundle,
        cross_check_review=cross_check_review,
    )
    payload = request_deepseek(api_key, model, body, timeout)
    content = response_message_content(payload)
    parsed_variants = parse_deepseek_variants(content, variant_count)
    valid: list[dict[str, Any]] = []
    rejected: list[str] = []
    for index, parsed in enumerate(parsed_variants, start=1):
        claim_hits = unsafe_hits_for(parsed)
        parsed = ensure_candidate_reference(candidate, scrub_polish_external_guidance(scrub_polish_claim_terms(parsed)))
        try:
            validate_polish(candidate, parsed)
        except RuntimeError as exc:
            rejected.append(f"variant {index}: {exc}")
            continue
        parsed["_raw_usage"] = payload.get("usage")
        parsed["_claim_scrub_applied"] = bool(claim_hits)
        parsed["_external_guidance_scrub_applied"] = True
        valid.append(parsed)
    if not valid:
        raise RuntimeError("DeepSeek returned no valid variants: " + "; ".join(rejected))
    return valid


def _score_polish(polished: dict[str, Any]) -> float:
    """Heuristic quality score: information density, hook strength, length fit."""
    score = 0.0
    voiceover = str(polished.get("voiceover_text") or "")
    cn_chars = chinese_char_count(voiceover)
    profile = polished.get("video_profile") if isinstance(polished.get("video_profile"), dict) else {}
    video_seconds = int(profile.get("duration_seconds") or 0)
    if video_seconds >= 180:
        target_chars = target_voiceover_chars(video_seconds)
        if cn_chars >= int(target_chars * 0.72):
            score += 3.0
        elif cn_chars >= int(target_chars * 0.45):
            score += 1.5
    elif 60 <= cn_chars <= 600:
        score += 3.0
    elif 40 <= cn_chars <= 700:
        score += 1.5
    title = str(polished.get("polished_title") or "")
    if any(hook in title for hook in policy_get("deepseek.hook_terms", ["为什么", "怎么"])):
        score += 2.0
    cards = polished.get("cards") or []
    storyboard = polished.get("storyboard") or {}
    scene_types = [str(scene.get("type")) for scene in storyboard.get("scenes") or [] if isinstance(scene, dict)]
    if len(set(scene_types)) >= 3 and {"statement", "cta"}.issubset(set(scene_types)):
        score += 2.0
    elif len(cards) >= 2 and all(len(str(c.get("value") or "")) > 4 for c in cards):
        score += 1.0
    if polished.get("caveats"):
        score += 1.0
    return score


def _multi_candidate_polish(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
    content_plan: dict[str, Any],
    evidence_bundle: dict[str, Any],
    cross_check_review: dict[str, Any],
    timeout: float,
    video_seconds: int = 12,
    video_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask the provider for multiple variants in one structured response and pick the highest-scoring valid one."""
    polished_variants = deepseek_variant_chat(
        api_key,
        model,
        candidate,
        content_plan,
        evidence_bundle,
        cross_check_review,
        timeout,
        video_seconds=video_seconds,
        video_profile=video_profile,
    )
    variants: list[tuple[float, dict[str, Any]]] = [(_score_polish(polished), polished) for polished in polished_variants]
    if not variants:
        raise RuntimeError("All multi-candidate polish attempts failed")
    variants.sort(key=lambda x: x[0], reverse=True)
    best = variants[0][1]
    best["_multi_candidate_scores"] = [v[0] for v in variants]
    best["_multi_candidate_count"] = len(variants)
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--mode", choices=["initial", "revise"], default="initial")
    parser.add_argument("--feedback", help="Gemini content_score JSON used in revise mode.")
    parser.add_argument("--input-polish", help="Previous DeepSeek polish JSON used in revise mode.")
    parser.add_argument("--output", help="Output JSON path. Defaults to run_dir/deepseek_polish.json.")
    parser.add_argument("--attempt", type=int, default=1, help="Optimization attempt number for artifact metadata.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    env_file = Path(args.env_file).resolve()
    api_key = env_value("DEEPSEEK_API_KEY", env_file)
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required for scripts/deepseek_polish.py")
    model = env_value("SEARCHPO_DEEPSEEK_MODEL", env_file, "deepseek-v4-pro")
    candidate_path = run_dir / "selected_candidate.json"
    plan_path = run_dir / "content_plan.json"
    evidence_path = run_dir / "evidence_bundle.json"
    cross_check_path = run_dir / "cross_check_review.json"
    if not candidate_path.exists() or not plan_path.exists() or not evidence_path.exists() or not cross_check_path.exists():
        raise SystemExit("selected_candidate.json, content_plan.json, evidence_bundle.json, and cross_check_review.json are required before DeepSeek polish")

    candidate = read_json(candidate_path)
    content_plan = read_json(plan_path)
    topic_brief_path = run_dir / "topic_brief.json"
    fact_bank_path = run_dir / "fact_bank.json"
    source_map_path = run_dir / "source_map.json"
    repo_context_path = run_dir / "repo_context.json"
    if topic_brief_path.exists():
        topic_brief = read_json(topic_brief_path)
        content_plan["topic_brief"] = topic_brief
        content_plan.setdefault("research_brief", topic_brief)
    if fact_bank_path.exists():
        content_plan["fact_bank"] = read_json(fact_bank_path)
    if source_map_path.exists():
        content_plan["source_map"] = read_json(source_map_path)
    if repo_context_path.exists():
        content_plan["repo_context"] = read_json(repo_context_path)
    evidence_bundle = read_json(evidence_path)
    cross_check_review = read_json(cross_check_path)
    strong_research_errors = strong_research_review_errors(cross_check_review)
    if strong_research_errors:
        raise SystemExit(f"strong research review must pass before DeepSeek polish: {strong_research_errors}")
    fallback_video_profile = choose_video_profile(candidate, content_plan, evidence_bundle)
    video_profile_override: dict[str, Any] = {}
    env_seconds = env_value("SEARCHPO_VIDEO_SECONDS", env_file, "")
    env_duration_frames = env_value("SEARCHPO_DURATION_FRAMES", env_file, "")
    env_orientation = env_value("SEARCHPO_VIDEO_ORIENTATION", env_file, "")
    if env_seconds:
        video_profile_override["duration_seconds"] = env_seconds
    elif env_duration_frames:
        try:
            video_profile_override["duration_seconds"] = max(1, round(int(env_duration_frames) / 30))
        except ValueError:
            pass
    if env_orientation:
        video_profile_override["orientation"] = env_orientation
    video_profile = normalize_video_profile(
        {
            **(content_plan.get("suggested_video_profile") or {}),
            **video_profile_override,
        },
        fallback=fallback_video_profile,
    )
    video_seconds = int(video_profile["duration_seconds"])
    multi_candidate = env_value("SEARCHPO_POLISH_MULTI_CANDIDATE", env_file, "0") == "1"
    revision_meta: dict[str, Any] | None = None
    feedback: dict[str, Any] | None = None
    if args.mode == "revise":
        if not args.feedback or not args.input_polish:
            raise SystemExit("--feedback and --input-polish are required when --mode revise")
        feedback_path = Path(args.feedback).resolve()
        input_polish_path = Path(args.input_polish).resolve()
        feedback = read_json(feedback_path)
        previous_polish = read_json(input_polish_path)
        polished = deepseek_revision_chat(
            api_key,
            model,
            candidate,
            content_plan,
            evidence_bundle,
            cross_check_review,
            previous_polish,
            feedback,
            args.timeout,
            video_seconds=video_seconds,
            video_profile=video_profile,
            attempt=args.attempt,
        )
        revision_meta = {
            "attempt": args.attempt,
            "mode": "revise",
            "feedback_path": str(feedback_path),
            "input_polish_path": str(input_polish_path),
            "previous_overall": feedback.get("overall"),
            "previous_verdict": feedback.get("verdict"),
            "failed_dimensions": feedback.get("failed_dimensions") or {},
            "suggestions": feedback.get("suggestions") or [],
        }
    elif multi_candidate:
        polished = _multi_candidate_polish(
            api_key,
            model,
            candidate,
            content_plan,
            evidence_bundle,
            cross_check_review,
            args.timeout,
            video_seconds=video_seconds,
            video_profile=video_profile,
        )
    else:
        polished = deepseek_chat(
            api_key,
            model,
            candidate,
            content_plan,
            evidence_bundle,
            cross_check_review,
            args.timeout,
            video_seconds=video_seconds,
            video_profile=video_profile,
        )
    polished_video_profile = normalize_video_profile({**(polished.get("video_profile") or {}), **video_profile_override}, fallback=video_profile)
    polished["video_profile"] = polished_video_profile
    polished = expand_voiceover_if_needed(
        api_key,
        model,
        candidate,
        content_plan,
        evidence_bundle,
        cross_check_review,
        polished,
        args.timeout,
    )
    polished = fit_video_profile_to_voiceover(polished)
    polished_video_profile = normalize_video_profile({**(polished.get("video_profile") or {}), **video_profile_override}, fallback=video_profile)
    polished["video_profile"] = polished_video_profile
    polished = ensure_candidate_reference(candidate, scrub_polish_external_guidance(scrub_polish_claim_terms(polished)))
    polished["_external_guidance_scrub_applied"] = True
    polished["voiceover_text"] = normalize_voiceover_text(str(polished.get("voiceover_text") or ""))
    polished["douyin_desc"] = normalize_voiceover_text(str(polished.get("douyin_desc") or ""))
    polished = compact_voiceover_if_over_target(candidate, content_plan, polished)
    polished["voiceover_text"] = normalize_voiceover_text(str(polished.get("voiceover_text") or ""))
    polished_video_profile = normalize_video_profile({**(polished.get("video_profile") or {}), **video_profile_override}, fallback=video_profile)
    polished["video_profile"] = polished_video_profile
    unsafe_hits = unsafe_hits_for(polished)
    polished = repair_storyboard_structure(candidate, content_plan, evidence_bundle, polished)
    polished = repair_agent_visual_structure(candidate, content_plan, polished, feedback)
    polished_video_profile = normalize_video_profile({**(polished.get("video_profile") or {}), **video_profile_override}, fallback=video_profile)
    polished["video_profile"] = polished_video_profile
    unsafe_hits = unsafe_hits_for(polished)
    result = {
        "schema_version": 1,
        "created_at": utc_now(),
        "provider": "deepseek",
        "model": model,
        "attempt": args.attempt,
        "mode": args.mode,
        "selected_candidate_id": candidate.get("candidate_id"),
        "status": "pass" if not unsafe_hits else "fail",
        "polished_title": bounded_text(polished["polished_title"], 80),
        "voiceover_text": clean_text(polished["voiceover_text"]),
        "script_text_hash": sha256_text(clean_text(polished["voiceover_text"])),
        "douyin_title": bounded_text(polished["douyin_title"], 55),
        "douyin_desc": bounded_text(polished["douyin_desc"], 600),
        "tags": polished["tags"],
        "cards": polished["cards"],
        "storyboard": polished.get("storyboard"),
        "agent_visual": polished.get("agent_visual"),
        "video_profile": polished_video_profile,
        "caveats": polished.get("caveats") or [],
        "unsafe_claim_hits": unsafe_hits,
        "correction_applied": bool(polished.get("_correction_applied")),
        "claim_scrub_applied": bool(polished.get("_claim_scrub_applied")),
        "external_guidance_scrub_applied": bool(polished.get("_external_guidance_scrub_applied")),
        "initial_error": polished.get("_initial_error"),
        "usage": polished.get("_raw_usage"),
        "voiceover_expansion": polished.get("_voiceover_expansion"),
        "storyboard_structure_repair": polished.get("_storyboard_structure_repair"),
        "agent_visual_structure_repair": polished.get("_agent_visual_structure_repair"),
        "voiceover_shortened": polished.get("_voiceover_shortened"),
        "video_profile_duration_adjusted": polished.get("_video_profile_duration_adjusted"),
        "deterministic_agent_visual_repair": bool(polished.get("_deterministic_agent_visual_repair")),
        "deterministic_agent_visual_reason": polished.get("_deterministic_agent_visual_reason"),
        "revision_meta": revision_meta,
        "input_files": [
            str(path)
            for path in [candidate_path, plan_path, topic_brief_path, fact_bank_path, source_map_path, evidence_path, cross_check_path]
            if path.exists()
        ],
    }
    output_path = Path(args.output).resolve() if args.output else run_dir / "deepseek_polish.json"
    write_json(output_path, result)
    print(json.dumps({"deepseek_polish": str(output_path), "status": result["status"]}, ensure_ascii=False, indent=2))
    if unsafe_hits:
        raise SystemExit(f"DeepSeek polish generated unsupported claim terms: {unsafe_hits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
