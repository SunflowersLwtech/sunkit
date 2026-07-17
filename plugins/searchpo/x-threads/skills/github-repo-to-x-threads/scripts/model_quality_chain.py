"""Model-intelligence quality chain for Agent-engineering X content."""

from __future__ import annotations

from typing import Any


QUALITY_CHAIN: list[dict[str, Any]] = [
    {
        "id": "source_grounding",
        "name": "Source grounding",
        "contract": "Extract inspectable facts before drafting; claims without evidence are removed or labeled as unknown.",
        "output": "evidence inventory with source paths/URLs and unsafe claims",
    },
    {
        "id": "brand_lane",
        "name": "Brand lane selection",
        "contract": "Select main-account pillar or off-main/professional bug-report lane before copywriting.",
        "output": "pillar, account fit, noise risk, and routing note",
    },
    {
        "id": "angle_tournament",
        "name": "Angle tournament",
        "contract": "Generate materially different theses, not surface rewrites of one summary.",
        "output": "3-5 angles with reader pain, mechanism, concrete example, caveat, and claim risk",
    },
    {
        "id": "creator_pattern",
        "name": "Creator pattern selection",
        "contract": "Select a coherent content mode without impersonation: engineering mentor, demo-first tool, test catalog, builder resource log, or product translator longform.",
        "output": "primary pattern, optional secondary pattern, hook/media/asset/question implications",
    },
    {
        "id": "asset_design",
        "name": "Reusable asset design",
        "contract": "Name the saveable asset before drafting the final thread.",
        "output": "checklist, flowchart, issue template, prompt snippet, before/after table, or failure map",
    },
    {
        "id": "draft_synthesis",
        "name": "Draft synthesis",
        "contract": "Draft from thesis -> mechanism -> example -> caveat -> attribution/question.",
        "output": "numbered posts that fit X length and preserve claim boundaries",
    },
    {
        "id": "adversarial_review",
        "name": "Adversarial review",
        "contract": "Attack the draft for unsupported claims, weak hook, generic voice, emotion leakage, missing asset, and missing question.",
        "output": "blocking issues and required revisions",
    },
    {
        "id": "final_gate",
        "name": "Final gate",
        "contract": "Only mark ready when claim, brand, asset, CTA, image, and publish gates pass.",
        "output": "ready/revise/block decision with exact reason",
    },
]


def quality_chain_prompt_lines() -> list[str]:
    return [
        f"{index}. {item['name']}: {item['contract']} Output: {item['output']}."
        for index, item in enumerate(QUALITY_CHAIN, start=1)
    ]


def quality_chain_schema() -> dict[str, Any]:
    return {
        item["id"]: {
            "status": "pass|revise|block",
            "evidence": "short concrete evidence for this stage",
            "decision": "what changed because of this stage",
        }
        for item in QUALITY_CHAIN
    }


def quality_chain_markdown(result: dict[str, Any]) -> list[str]:
    chain = result.get("model_quality_chain") if isinstance(result.get("model_quality_chain"), dict) else {}
    lines = ["## Model Quality Chain", ""]
    for item in QUALITY_CHAIN:
        stage = chain.get(item["id"]) if isinstance(chain.get(item["id"]), dict) else {}
        lines.append(f"- `{item['id']}` {item['name']}: {stage.get('status', 'not_returned')}")
        if stage.get("evidence"):
            lines.append(f"  Evidence: {stage.get('evidence')}")
        if stage.get("decision"):
            lines.append(f"  Decision: {stage.get('decision')}")
    return lines
