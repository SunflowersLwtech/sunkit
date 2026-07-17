from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_harness.premium_director import (
    MOTION_TYPES,
    PREMIUM_SCENE_TYPES,
    build_premium_director_spec,
    normalize_premium_director_spec,
)


@dataclass(frozen=True)
class VisualScene:
    id: str
    kind: str
    title: str
    objective: str
    teaching_beats: list[str] = field(default_factory=list)
    object_refs: list[str] = field(default_factory=list)
    layout: str = "full_canvas_keynote"
    motion_beats: list[str] = field(default_factory=lambda: ["reveal", "object_focus", "dwell"])
    dwell_frames: int = 36

    @classmethod
    def from_director_scene(cls, value: dict[str, Any], *, index: int) -> "VisualScene":
        raw_kind = str(value.get("kind") or value.get("scene_type") or value.get("type") or "")
        kind = raw_kind if raw_kind in PREMIUM_SCENE_TYPES else "MechanismExplodedView"
        raw_motion = value.get("motion_beats") if isinstance(value.get("motion_beats"), list) else []
        motion = [str(item) for item in raw_motion if str(item) in MOTION_TYPES]
        return cls(
            id=str(value.get("id") or f"premium_{index}"),
            kind=kind,
            title=str(value.get("title") or ""),
            objective=str(value.get("objective") or value.get("intent") or ""),
            teaching_beats=[str(item) for item in (value.get("teaching_beats") or [])[:4]],
            object_refs=[str(item) for item in (value.get("object_refs") or [])[:4]],
            layout=str(value.get("layout") or "full_canvas_keynote"),
            motion_beats=motion or ["reveal", "object_focus", "dwell"],
            dwell_frames=int(value.get("dwell_frames") or 36),
        )

    def to_director_scene(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scene_type": self.kind,
            "title": self.title,
            "objective": self.objective,
            "teaching_beats": self.teaching_beats,
            "object_refs": self.object_refs,
            "layout": self.layout,
            "motion_beats": self.motion_beats,
            "dwell_frames": self.dwell_frames,
        }


@dataclass(frozen=True)
class DirectorSpec:
    profile: dict[str, Any]
    knowledge_arc: dict[str, str]
    topic_objects: list[dict[str, Any]]
    visual_scenes: list[VisualScene]
    motion_beats: list[dict[str, Any]]
    content_constraints: dict[str, Any]
    schema_version: int = 1
    source: str = "typed_director_spec"

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "DirectorSpec":
        normalized = normalize_premium_director_spec(value)
        scenes = [
            VisualScene.from_director_scene(scene, index=index)
            for index, scene in enumerate(normalized.get("visual_scenes") or [], start=1)
            if isinstance(scene, dict)
        ]
        return cls(
            schema_version=int(normalized.get("schema_version") or 1),
            source=str(normalized.get("source") or "typed_director_spec"),
            profile=dict(normalized.get("profile") or {}),
            knowledge_arc={str(key): str(value) for key, value in (normalized.get("knowledge_arc") or {}).items()},
            topic_objects=[dict(item) for item in (normalized.get("topic_objects") or []) if isinstance(item, dict)],
            visual_scenes=scenes,
            motion_beats=[dict(item) for item in (normalized.get("motion_beats") or []) if isinstance(item, dict)],
            content_constraints=dict(normalized.get("content_constraints") or {}),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "profile": self.profile,
            "knowledge_arc": self.knowledge_arc,
            "scene_types": sorted({scene.kind for scene in self.visual_scenes}),
            "topic_objects": self.topic_objects,
            "visual_scenes": [scene.to_director_scene() for scene in self.visual_scenes],
            "motion_beats": self.motion_beats,
            "content_constraints": self.content_constraints,
        }


def validate_director_spec(value: dict[str, Any]) -> dict[str, Any]:
    return normalize_premium_director_spec(value)


def from_runtime_inputs(
    candidate: dict[str, Any] | None = None,
    content_plan: dict[str, Any] | None = None,
    polish: dict[str, Any] | None = None,
    video_profile: dict[str, Any] | None = None,
) -> DirectorSpec:
    return DirectorSpec.from_mapping(build_premium_director_spec(candidate, content_plan, polish, video_profile))
