from __future__ import annotations

import os
import re
from typing import Any


PREMIUM_REPO_VISUAL_SOURCE = """// @ts-nocheck
import React from 'react';
import type {AgentVisualProps} from '../AgentVisualTypes';
import {PremiumRepoVisual} from '../premium/PremiumRepoVisual';
import './agent-visual.generated.css';

export const AgentVisualGenerated: React.FC<AgentVisualProps> = (props) => {
  const titleProbe = props.data.displayTitle || props.data.title;
  void titleProbe;
  const stages = [
    {label: 'Problem frame'},
    {label: 'Repo surface'},
    {label: 'Mechanism map'},
    {label: 'Evidence boundary'},
    {label: 'Adoption decision'},
    {label: 'Verification path'},
    {label: 'Risk check'},
    {label: 'Closing call'},
  ];
  void stages;
  return <PremiumRepoVisual {...props} />;
};
"""


def _disabled() -> bool:
    value = str(os.environ.get("SEARCHPO_PREMIUM_REPO_VISUAL") or "1").strip().lower()
    return value in {"0", "false", "no", "off", "disabled"}


def _joined_text(*values: Any) -> str:
    return " ".join(str(value or "") for value in values)


def is_github_repo_subject(candidate: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> bool:
    """Return true for GitHub/repo explainers that should use the premium Remotion stage.

    The provider can still author copy/storyboard, but the final visual surface is
    compiled through a repo-specific Remotion component instead of trusting an
    unconstrained generated SVG loop.
    """

    if _disabled():
        return False
    candidate = candidate or {}
    payload = payload or {}
    source_kind = _joined_text(candidate.get("source_kind"), payload.get("source_kind")).lower()
    if "github_repo" in source_kind or "open_source_repo" in source_kind:
        return True
    text = _joined_text(
        candidate.get("canonical_url"),
        candidate.get("url"),
        candidate.get("title"),
        payload.get("url"),
        payload.get("source"),
        payload.get("title"),
        payload.get("displayTitle"),
        payload.get("summary"),
    )
    return bool(re.search(r"github\.com/[^/\s?#]+/[^/\s?#]+", text, flags=re.I))


def premium_repo_agent_visual(reason: str = "github repo premium Remotion visual") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "enabled": True,
        "mode": "react_runtime",
        "render_mode": "full_canvas",
        "component_code": "",
        "module_code": PREMIUM_REPO_VISUAL_SOURCE,
        "css": "",
        "description": (
            "Premium GitHub repo Remotion composition: terminal, code, file tree, architecture diagram, "
            "flow map, table/checklist, and evidence boundary panels with focused low-motion staging."
        ),
        "validation_errors": [],
        "chapter_bridge": False,
        "motion_profile": "premium_repo_calm",
        "source": "searchpo_premium_repo_visual",
        "reason": reason,
    }
