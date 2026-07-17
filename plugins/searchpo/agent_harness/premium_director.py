from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

from agent_harness.content_guard import dismissive_verification_hits, scrub_dismissive_verification_text


PREMIUM_SCENE_TYPES = {
    "HeroProblemScene",
    "MechanismExplodedView",
    "RepoFileTreeReveal",
    "ArchitectureFlowScene",
    "MetricComparisonScene",
    "DecisionMatrixScene",
    "TimelineBuildScene",
    "CodeOrTerminalScene",
    "KnowledgeTakeawayScene",
}

MOTION_TYPES = {
    "reveal",
    "build",
    "pan",
    "camera_push",
    "camera_pan",
    "parallax",
    "mask_reveal",
    "morph",
    "path_draw",
    "metric_count",
    "typewriter",
    "object_focus",
    "dwell",
}

SCENE_MOTION_GRAMMAR = {
    "HeroProblemScene": ["reveal", "camera_push", "parallax", "object_focus", "dwell"],
    "MechanismExplodedView": ["mask_reveal", "path_draw", "parallax", "object_focus", "dwell"],
    "RepoFileTreeReveal": ["mask_reveal", "build", "camera_pan", "object_focus", "dwell"],
    "ArchitectureFlowScene": ["path_draw", "camera_pan", "parallax", "object_focus", "dwell"],
    "CodeOrTerminalScene": ["typewriter", "mask_reveal", "object_focus", "dwell"],
    "MetricComparisonScene": ["metric_count", "morph", "object_focus", "dwell"],
    "DecisionMatrixScene": ["mask_reveal", "object_focus", "dwell"],
    "TimelineBuildScene": ["path_draw", "build", "camera_pan", "dwell"],
    "KnowledgeTakeawayScene": ["reveal", "camera_push", "object_focus", "dwell"],
}

CORE_GLOBAL_MOTION_BEATS = [
    {"type": "camera_push", "target": "hero_problem", "intensity": "restrained"},
    {"type": "parallax", "target": "topic_object_layers", "intensity": "restrained"},
    {"type": "mask_reveal", "target": "mechanism_exploded_view", "intensity": "medium"},
    {"type": "path_draw", "target": "architecture_flow", "intensity": "restrained"},
    {"type": "metric_count", "target": "comparison_panel", "intensity": "restrained"},
    {"type": "morph", "target": "tradeoff_axes", "intensity": "restrained"},
    {"type": "typewriter", "target": "code_or_terminal_scene", "intensity": "restrained"},
    {"type": "object_focus", "target": "decision_matrix", "intensity": "medium"},
    {"type": "dwell", "target": "knowledge_takeaway", "intensity": "calm"},
]


def _clean(value: Any, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _compact_list(values: list[Any], fallback: list[str], *, limit: int, max_items: int) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in [*values, *fallback]:
        cleaned = _clean(scrub_dismissive_verification_text(value), limit)
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


def _repo_slug(candidate: dict[str, Any] | None) -> str:
    candidate = candidate or {}
    joined = " ".join(str(candidate.get(key) or "") for key in ("canonical_url", "url", "title", "entity_key"))
    match = re.search(r"github\.com/([^/\s?#]+)/([^/\s?#]+)", joined, re.I)
    if match:
        return _clean(f"{match.group(1)}/{match.group(2).removesuffix('.git')}", 48)
    parsed = urllib.parse.urlparse(str(candidate.get("canonical_url") or ""))
    if parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parsed.netloc.lower().endswith("github.com"):
            return _clean("/".join(parts[:2]), 48)
        if parts:
            return _clean(parts[-1].replace("-", " ").replace("_", " "), 48)
        return _clean(parsed.netloc.replace("www.", ""), 48)
    return _clean(candidate.get("title") or candidate.get("entity_key") or "source topic", 48)


def _fact_texts(content_plan: dict[str, Any] | None, polish: dict[str, Any] | None) -> list[str]:
    content_plan = content_plan or {}
    polish = polish or {}
    fact_bank = content_plan.get("fact_bank") if isinstance(content_plan.get("fact_bank"), dict) else {}
    topic_brief = content_plan.get("topic_brief") if isinstance(content_plan.get("topic_brief"), dict) else {}
    rows: list[Any] = [
        *(fact_bank.get("source_backed_facts") or []),
        *(fact_bank.get("risk_notes") or []),
        *(topic_brief.get("key_points") or []),
        *(topic_brief.get("visual_opportunities") or []),
        polish.get("voiceover_text"),
        polish.get("douyin_desc"),
    ]
    cards = polish.get("cards") if isinstance(polish.get("cards"), list) else []
    for card in cards:
        if isinstance(card, dict):
            rows.extend([card.get("label"), card.get("value"), card.get("detail")])
    return _compact_list(rows, ["机制说明", "架构位置", "适用边界", "失败模式", "判断框架"], limit=92, max_items=12)


def _object_kind(label: str) -> str:
    lowered = label.lower()
    if re.search(r"\.(py|ts|tsx|js|md|json|ya?ml)\b|/|readme|docs|src|tests", lowered):
        return "repo_file"
    if re.search(r"api|sdk|cli|mcp|route|server|client|接口|调用", lowered):
        return "api_surface"
    if re.search(r"metric|score|benchmark|eval|评估|指标|对比", lowered):
        return "metric"
    if re.search(r"风险|失败|边界|限制|tradeoff|risk", lowered):
        return "failure_boundary"
    return "architecture_node"


def _topic_objects(candidate: dict[str, Any] | None, content_plan: dict[str, Any] | None, polish: dict[str, Any] | None) -> list[dict[str, Any]]:
    repo = _repo_slug(candidate)
    facts = _fact_texts(content_plan, polish)
    labels = _compact_list([repo, *facts], ["机制入口", "架构节点", "适用场景", "失败边界"], limit=52, max_items=8)
    return [
        {
            "id": f"obj_{index}",
            "kind": _object_kind(label),
            "label": label,
            "detail": _clean(facts[index - 1] if index - 1 < len(facts) else label, 86),
            "source_ref": "fact_bank" if index > 1 else "selected_candidate",
        }
        for index, label in enumerate(labels[:8], start=1)
    ]


def _knowledge_arc(candidate: dict[str, Any] | None, content_plan: dict[str, Any] | None, polish: dict[str, Any] | None) -> dict[str, str]:
    title = _repo_slug(candidate)
    facts = _fact_texts(content_plan, polish)
    topic_brief = (content_plan or {}).get("topic_brief") if isinstance((content_plan or {}).get("topic_brief"), dict) else {}
    return {
        "hook": _clean((polish or {}).get("polished_title") or f"{title} 真正要解决的问题", 76),
        "mechanism": _clean(facts[0] if facts else f"{title} 的关键机制", 108),
        "architecture_position": _clean((topic_brief or {}).get("core_question") or "放在输入、处理、输出之间看它的架构位置", 108),
        "practical_fit": _clean(facts[1] if len(facts) > 1 else "适合有清晰工作流、能衡量失败样例的场景", 108),
        "tradeoff": _clean(facts[2] if len(facts) > 2 else "收益来自抽象和自动化，代价是调试与边界治理", 108),
        "failure_boundary": _clean(facts[3] if len(facts) > 3 else "失败通常出现在证据不足、接口不稳或评估口径缺失时", 108),
        "judgment_framework": "先看机制是否成立，再看架构位置、适用负载、失败边界和投入成本。",
        "takeaway": _clean((topic_brief or {}).get("angle") or "把它当作一个可评估的系统位置，而不是一个口号。", 108),
    }


def _scene_seed(candidate: dict[str, Any] | None) -> list[str]:
    joined = " ".join(str((candidate or {}).get(key) or "") for key in ("canonical_url", "url", "source_kind", "title")).lower()
    if "github.com/" in joined or "github_repo" in joined:
        return [
            "HeroProblemScene",
            "RepoFileTreeReveal",
            "ArchitectureFlowScene",
            "CodeOrTerminalScene",
            "DecisionMatrixScene",
            "KnowledgeTakeawayScene",
        ]
    if "paper" in joined or "arxiv" in joined:
        return [
            "HeroProblemScene",
            "MechanismExplodedView",
            "MetricComparisonScene",
            "TimelineBuildScene",
            "DecisionMatrixScene",
            "KnowledgeTakeawayScene",
        ]
    return [
        "HeroProblemScene",
        "MechanismExplodedView",
        "ArchitectureFlowScene",
        "MetricComparisonScene",
        "DecisionMatrixScene",
        "KnowledgeTakeawayScene",
    ]


def _scene_title(scene_type: str, arc: dict[str, str], fallback_title: str) -> str:
    titles = {
        "HeroProblemScene": arc["hook"],
        "MechanismExplodedView": "把机制拆成可理解的因果链",
        "RepoFileTreeReveal": "从源码/证据入口看真实结构",
        "ArchitectureFlowScene": "它在系统里的位置",
        "CodeOrTerminalScene": "落到一条实际工作流",
        "MetricComparisonScene": "收益、成本和边界怎么取舍",
        "TimelineBuildScene": "变化顺序和关键拐点",
        "DecisionMatrixScene": "适用场景与失败边界",
        "KnowledgeTakeawayScene": "最后留下一个判断框架",
    }
    return _clean(titles.get(scene_type) or fallback_title, 76)


def _scene_objective(scene_type: str, arc: dict[str, str]) -> str:
    objectives = {
        "HeroProblemScene": f"先把问题讲清楚：{arc['hook']}，并说明为什么不能只看热度或标题。",
        "MechanismExplodedView": f"把机制拆成输入、处理、输出和约束：{arc['mechanism']}",
        "RepoFileTreeReveal": f"把证据入口摊开，说明哪些文件/API/指标支撑这个判断：{arc['mechanism']}",
        "ArchitectureFlowScene": f"放进真实系统位置解释：{arc['architecture_position']}",
        "CodeOrTerminalScene": f"用最小工作流说明实际怎么落地，以及适合什么负载：{arc['practical_fit']}",
        "MetricComparisonScene": f"把收益、成本、调试难度和边界放在同一个取舍坐标里：{arc['tradeoff']}",
        "TimelineBuildScene": f"按时间顺序讲清变化原因、关键拐点和证据边界：{arc['tradeoff']}",
        "DecisionMatrixScene": f"明确适用条件和失败条件：{arc['failure_boundary']}",
        "KnowledgeTakeawayScene": f"给观众一个可复用判断顺序：{arc['judgment_framework']}",
    }
    return _clean(objectives.get(scene_type) or arc["takeaway"], 156)


def _scene_teaching_beats(scene_type: str, arc: dict[str, str]) -> list[str]:
    beats = {
        "HeroProblemScene": ["问题为什么重要", "不要把热度当结论", "先建立判断对象"],
        "MechanismExplodedView": ["输入是什么", "中间机制怎么转化", "输出靠什么约束"],
        "RepoFileTreeReveal": ["证据入口在哪里", "源码/文档支撑哪句话", "哪些能力不能外推"],
        "ArchitectureFlowScene": ["它在系统哪一层", "上游下游分别是什么", "哪里会成为瓶颈"],
        "CodeOrTerminalScene": ["最小工作流怎么跑", "真实使用会碰到什么", "和传统方案怎么分工"],
        "MetricComparisonScene": ["收益来自哪里", "成本出现在哪里", "何时不值得上"],
        "TimelineBuildScene": ["变化顺序", "关键拐点", "边界条件"],
        "DecisionMatrixScene": ["适合谁", "不适合谁", "失败边界是什么"],
        "KnowledgeTakeawayScene": ["先看机制", "再看架构位置", "最后看失败成本"],
    }
    return [_clean(item, 48) for item in beats.get(scene_type, ["机制", "架构位置", "失败边界"])]


def _scene_motion_beats(scene_type: str) -> list[str]:
    return list(SCENE_MOTION_GRAMMAR.get(scene_type, ["reveal", "object_focus", "dwell"]))


def _merge_motion(existing: list[str], required: list[str], *, limit: int = 6) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*existing, *required]:
        if item not in MOTION_TYPES or item in seen:
            continue
        seen.add(item)
        merged.append(item)
        if len(merged) >= limit:
            break
    return merged or ["reveal", "object_focus", "dwell"]


def _upgrade_scene_motion_grammar(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    upgraded: list[dict[str, Any]] = []
    for scene in scenes:
        scene_type = str(scene.get("scene_type") or "")
        current = [str(beat) for beat in (scene.get("motion_beats") or []) if str(beat) in MOTION_TYPES]
        updated = dict(scene)
        updated["motion_beats"] = _merge_motion(current, _scene_motion_beats(scene_type))
        updated["layout"] = "full_canvas_keynote"
        upgraded.append(updated)
    return upgraded


def _upgrade_global_motion_beats(motion_beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    upgraded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*motion_beats, *CORE_GLOBAL_MOTION_BEATS]:
        if not isinstance(item, dict):
            continue
        motion_type = str(item.get("type") or item.get("motion") or "")
        if motion_type not in MOTION_TYPES or motion_type in seen:
            continue
        seen.add(motion_type)
        upgraded.append(
            {
                "type": motion_type,
                "target": _clean(item.get("target") or motion_type, 48),
                "intensity": _clean(item.get("intensity") or "restrained", 32),
            }
        )
    return upgraded[:12]


def _director_scene(scene_type: str, index: int, arc: dict[str, str], objects: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": f"premium_{index}",
        "scene_type": scene_type,
        "title": _scene_title(scene_type, arc, arc["takeaway"]),
        "objective": _scene_objective(scene_type, arc),
        "teaching_beats": _scene_teaching_beats(scene_type, arc),
        "object_refs": [item["id"] for item in objects[max(0, index - 2) : max(0, index - 2) + 3]],
        "layout": "full_canvas_keynote",
        "motion_beats": _scene_motion_beats(scene_type),
        "dwell_frames": 36,
    }


def _ensure_scene_coverage(
    scenes: list[dict[str, Any]],
    *,
    candidate: dict[str, Any] | None,
    arc: dict[str, str],
    objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    required_order = _scene_seed(candidate)
    scene_types = {str(scene.get("scene_type") or "") for scene in scenes}
    object_kinds = " ".join(str(item.get("kind") or "") for item in objects).lower()
    if "RepoFileTreeReveal" in scene_types or re.search(r"repo|file|api|source|module|code", object_kinds):
        required_order = [
            "HeroProblemScene",
            "RepoFileTreeReveal",
            "ArchitectureFlowScene",
            "CodeOrTerminalScene",
            "DecisionMatrixScene",
            "KnowledgeTakeawayScene",
        ]
    by_type: dict[str, dict[str, Any]] = {}
    overflow: list[dict[str, Any]] = []
    for scene in scenes:
        scene_type = str(scene.get("scene_type") or "")
        if scene_type in required_order and scene_type not in by_type:
            by_type[scene_type] = scene
        else:
            overflow.append(scene)
    ordered: list[dict[str, Any]] = []
    for scene_type in required_order:
        ordered.append(by_type.get(scene_type) or _director_scene(scene_type, len(ordered) + 1, arc, objects))
    seen = {str(scene.get("scene_type") or "") for scene in ordered}
    for scene in overflow:
        scene_type = str(scene.get("scene_type") or "")
        if scene_type and scene_type not in seen:
            ordered.append(scene)
            seen.add(scene_type)
        if len(ordered) >= 9:
            break
    return ordered


def build_premium_director_spec(
    candidate: dict[str, Any] | None = None,
    content_plan: dict[str, Any] | None = None,
    polish: dict[str, Any] | None = None,
    video_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = video_profile or (polish or {}).get("video_profile") or {}
    orientation = str(profile.get("orientation") or "horizontal")
    aspect_ratio = str(profile.get("aspect_ratio") or ("16:9" if orientation == "horizontal" else "9:16"))
    duration_seconds = int(float(profile.get("duration_seconds") or 72))
    objects = _topic_objects(candidate, content_plan, polish)
    arc = _knowledge_arc(candidate, content_plan, polish)
    scene_types = _scene_seed(candidate)
    visual_scenes = []
    for index, scene_type in enumerate(scene_types, start=1):
        visual_scenes.append(_director_scene(scene_type, index, arc, objects))
    return normalize_premium_director_spec(
        {
            "schema_version": 1,
            "source": "deterministic_director_compiler",
            "profile": {
                "orientation": orientation,
                "aspect_ratio": aspect_ratio,
                "duration_seconds": duration_seconds,
                "style_family": "apple_keynote_showcase",
                "motion_comfort": "comfortable",
                "safe_space_px": 180 if orientation == "horizontal" else 560,
            },
            "knowledge_arc": arc,
            "topic_objects": objects,
            "visual_scenes": visual_scenes,
            "motion_beats": CORE_GLOBAL_MOTION_BEATS,
            "content_constraints": {
                "source_boundary": "Claims stay inside selected evidence and cross-check artifacts.",
                "knowledge_takeaway_required": True,
                "forbid_dismissive_verification_language": True,
            },
        },
        candidate=candidate,
        content_plan=content_plan,
        polish=polish,
        video_profile=profile,
    )


def normalize_premium_director_spec(
    value: Any,
    *,
    candidate: dict[str, Any] | None = None,
    content_plan: dict[str, Any] | None = None,
    polish: dict[str, Any] | None = None,
    video_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return build_premium_director_spec(candidate, content_plan, polish, video_profile)
    data = scrub_dismissive_verification_text(dict(value))
    profile_in = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    profile_source = video_profile or (polish or {}).get("video_profile") or {}
    orientation = str(profile_in.get("orientation") or profile_source.get("orientation") or "horizontal")
    if orientation not in {"vertical", "horizontal"}:
        orientation = "horizontal"
    aspect_ratio = str(profile_in.get("aspect_ratio") or profile_in.get("aspectRatio") or profile_source.get("aspect_ratio") or ("16:9" if orientation == "horizontal" else "9:16"))
    if aspect_ratio not in {"9:16", "16:9"}:
        aspect_ratio = "16:9" if orientation == "horizontal" else "9:16"
    try:
        duration_seconds = int(float(profile_in.get("duration_seconds") or profile_source.get("duration_seconds") or 72))
    except (TypeError, ValueError):
        duration_seconds = 72
    profile = {
        "orientation": orientation,
        "aspect_ratio": aspect_ratio,
        "duration_seconds": max(18, duration_seconds),
        "style_family": _clean(profile_in.get("style_family") or "apple_keynote_showcase", 42),
        "motion_comfort": _clean(profile_in.get("motion_comfort") or "comfortable", 42),
        "safe_space_px": int(profile_in.get("safe_space_px") or (180 if orientation == "horizontal" else 560)),
    }
    fallback_arc = _knowledge_arc(candidate, content_plan, polish)
    arc_in = data.get("knowledge_arc") if isinstance(data.get("knowledge_arc"), dict) else {}
    knowledge_arc = {key: _clean(arc_in.get(key) or fallback, 132) for key, fallback in fallback_arc.items()}
    objects_in = data.get("topic_objects") if isinstance(data.get("topic_objects"), list) else []
    objects: list[dict[str, Any]] = []
    for index, item in enumerate(objects_in, start=1):
        if not isinstance(item, dict):
            continue
        label = _clean(item.get("label") or item.get("name") or item.get("title"), 58)
        if not label:
            continue
        objects.append(
            {
                "id": _clean(item.get("id") or f"obj_{index}", 32),
                "kind": _clean(item.get("kind") or _object_kind(label), 32),
                "label": label,
                "detail": _clean(item.get("detail") or label, 96),
                "source_ref": _clean(item.get("source_ref") or "evidence", 42),
            }
        )
    if len(objects) < 3:
        objects = _topic_objects(candidate, content_plan, polish)
    scenes_in = data.get("visual_scenes") or data.get("scenes") or data.get("scene_plan")
    scenes_in = scenes_in if isinstance(scenes_in, list) else []
    scenes: list[dict[str, Any]] = []
    for index, item in enumerate(scenes_in, start=1):
        if not isinstance(item, dict):
            continue
        scene_type = _clean(item.get("scene_type") or item.get("type"), 40)
        if scene_type not in PREMIUM_SCENE_TYPES:
            scene_type = _scene_seed(candidate)[(index - 1) % len(_scene_seed(candidate))]
        scene_motion = item.get("motion_beats") if isinstance(item.get("motion_beats"), list) else []
        motion = [beat for beat in (_clean(beat, 32) for beat in scene_motion) if beat in MOTION_TYPES]
        scenes.append(
            {
                "id": _clean(item.get("id") or f"premium_{index}", 32),
                "scene_type": scene_type,
                "title": _clean(item.get("title") or knowledge_arc["hook"], 76),
                "objective": _clean(item.get("objective") or item.get("intent") or knowledge_arc["takeaway"], 132),
                "teaching_beats": _compact_list(
                    item.get("teaching_beats") if isinstance(item.get("teaching_beats"), list) else [],
                    _scene_teaching_beats(scene_type, knowledge_arc),
                    limit=48,
                    max_items=4,
                ),
                "object_refs": [str(ref) for ref in (item.get("object_refs") or [])[:4]],
                "layout": _clean(item.get("layout") or "full_canvas_keynote", 42),
                "motion_beats": motion or _scene_motion_beats(scene_type),
                "dwell_frames": int(item.get("dwell_frames") or 36),
            }
        )
    scenes = _ensure_scene_coverage(scenes, candidate=candidate, arc=knowledge_arc, objects=objects)
    if len(scenes) < 5 or len({scene["scene_type"] for scene in scenes}) < 4:
        return build_premium_director_spec(candidate, content_plan, polish, profile)
    motion_in = data.get("motion_beats") if isinstance(data.get("motion_beats"), list) else []
    motion_beats: list[dict[str, Any]] = []
    for index, item in enumerate(motion_in, start=1):
        if not isinstance(item, dict):
            continue
        motion_type = _clean(item.get("type") or item.get("motion") or "reveal", 32)
        if motion_type not in MOTION_TYPES:
            motion_type = "reveal"
        motion_beats.append(
            {
                "type": motion_type,
                "target": _clean(item.get("target") or f"scene_{index}", 48),
                "intensity": _clean(item.get("intensity") or "restrained", 32),
            }
        )
    scenes = _upgrade_scene_motion_grammar(scenes)
    motion_beats = _upgrade_global_motion_beats(motion_beats)
    constraints_in = data.get("content_constraints") if isinstance(data.get("content_constraints"), dict) else {}
    spec = {
        "schema_version": 1,
        "source": _clean(data.get("source") or "provider_director_spec", 60),
        "profile": profile,
        "knowledge_arc": knowledge_arc,
        "scene_types": sorted({scene["scene_type"] for scene in scenes}),
        "topic_objects": objects[:10],
        "visual_scenes": scenes[:12],
        "motion_beats": motion_beats[:12],
        "content_constraints": {
            "source_boundary": _clean(constraints_in.get("source_boundary") or "Claims stay inside selected evidence and cross-check artifacts.", 140),
            "knowledge_takeaway_required": bool(constraints_in.get("knowledge_takeaway_required", True)),
            "forbid_dismissive_verification_language": True,
        },
    }
    hits = dismissive_verification_hits(
        {
            "knowledge_arc": spec["knowledge_arc"],
            "topic_objects": spec["topic_objects"],
            "visual_scenes": spec["visual_scenes"],
        }
    )
    if hits:
        raise ValueError(f"premium_director_spec contains banned dismissive verification phrasing: {hits}")
    return spec


def compile_premium_agent_visual(spec: dict[str, Any], *, reason: str = "premium director compiler") -> dict[str, Any]:
    normalized = normalize_premium_director_spec(spec)
    visual_scenes = normalized.get("visual_scenes") or []
    module = """// @ts-nocheck
import React from 'react';
import type {AgentVisualProps} from '../AgentVisualTypes';
import {PremiumDirectorVisual} from '../premium/PremiumDirectorVisual';
import './agent-visual.generated.css';

const visualScenes = __VISUAL_SCENES__;
const premiumDirectorSpec = __PREMIUM_DIRECTOR_SPEC__;

export const AgentVisualGenerated: React.FC<AgentVisualProps> = (props) => {
  const topicTitle = props.data.displayTitle || props.data.title;
  void topicTitle;
  return <PremiumDirectorVisual {...props} spec={premiumDirectorSpec} visualScenes={visualScenes} />;
};
"""
    module = module.replace("__VISUAL_SCENES__", json.dumps(visual_scenes, ensure_ascii=False))
    module = module.replace("__PREMIUM_DIRECTOR_SPEC__", json.dumps(normalized, ensure_ascii=False))
    scene_types = ", ".join(normalized.get("scene_types") or [])
    object_labels = ", ".join(item.get("label") or "" for item in (normalized.get("topic_objects") or [])[:4])
    return {
        "schema_version": 1,
        "enabled": True,
        "mode": "react_runtime",
        "render_mode": "full_canvas",
        "component_code": "",
        "module_code": module,
        "css": "",
        "description": _clean(
            f"Premium director compiler visual using {scene_types}; topic objects: {object_labels}",
            400,
        ),
        "validation_errors": [],
        "chapter_bridge": False,
        "motion_profile": "premium_director_comfortable",
        "source": "premium_director_compiler",
        "reason": reason,
        "recipe_scene_count": len(visual_scenes),
    }
