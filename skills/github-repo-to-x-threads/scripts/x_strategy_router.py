#!/usr/bin/env python3
"""Classify arbitrary X-post inputs and recommend a governed posting strategy."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from brand_profile import BRAND_PROFILE, brand_contract_lines, classify_brand_input


GITHUB_RE = re.compile(r"^(?:https?://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:/.*)?$")
URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug[:80] or "input"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def classify_source(source: str) -> dict[str, Any]:
    value = source.strip()
    path = Path(value).expanduser()
    parsed = urlparse(value) if URL_RE.match(value) else None
    lower = value.lower()

    if path.exists():
        if path.is_dir():
            if (path / "posting_pack.md").exists() and (path / "images_manifest.json").exists():
                return {
                    "source": value,
                    "kind": "existing_posting_pack",
                    "evidence_mode": "reuse_existing_run",
                    "source_id": safe_slug(path.name),
                    "notes": ["Existing governed posting pack directory."],
                }
            if (path / ".git").exists() or any((path / name).exists() for name in ("README.md", "pyproject.toml", "package.json", "Cargo.toml", "go.mod")):
                return {
                    "source": value,
                    "kind": "local_repo",
                    "evidence_mode": "read_local_repo",
                    "source_id": safe_slug(f"local-{path.name}"),
                    "notes": ["Local directory looks like a repository or source tree."],
                }
            return {
                "source": value,
                "kind": "local_directory",
                "evidence_mode": "inspect_local_files",
                "source_id": safe_slug(f"dir-{path.name}"),
                "notes": ["Local directory exists but is not clearly a git repo."],
            }
        return {
            "source": value,
            "kind": "local_file",
            "evidence_mode": "read_local_file",
            "source_id": safe_slug(path.stem),
            "notes": [f"Local file suffix: {path.suffix or '<none>'}"],
        }

    if parsed:
        host = (parsed.netloc or "").lower()
        if host == "github.com":
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2:
                return {
                    "source": value,
                    "kind": "github_repo",
                    "owner_repo": f"{parts[0]}/{parts[1]}",
                    "evidence_mode": "clone_and_live_github_metadata",
                    "source_id": safe_slug(f"{parts[0]}__{parts[1]}"),
                    "notes": ["GitHub repository URL."],
                }
        if host.endswith("arxiv.org") or host.endswith("alphaxiv.org"):
            arxiv_id = parsed.path.rstrip("/").split("/")[-1]
            return {
                "source": value,
                "kind": "paper",
                "paper_id": arxiv_id,
                "evidence_mode": "paper_metadata_and_pdf",
                "source_id": safe_slug(f"paper-{arxiv_id}"),
                "notes": ["arXiv/alphaXiv-style paper URL."],
            }
        return {
            "source": value,
            "kind": "web_url",
            "host": host,
            "evidence_mode": "web_page_and_linked_sources",
            "source_id": safe_slug(host + parsed.path),
            "notes": ["General web URL."],
        }

    match = GITHUB_RE.match(value)
    if match and "/" in value and " " not in value:
        owner_repo = f"{match.group(1)}/{match.group(2)}"
        return {
            "source": value,
            "kind": "github_repo",
            "owner_repo": owner_repo,
            "evidence_mode": "clone_and_live_github_metadata",
            "source_id": safe_slug(owner_repo.replace("/", "__")),
            "notes": ["owner/repo-style GitHub handle."],
        }

    return {
        "source": value,
        "kind": "raw_idea",
        "evidence_mode": "user_prompt_plus_requested_research",
        "source_id": safe_slug(value[:48]),
        "notes": ["Free-form idea or prompt; facts need external evidence before posting."],
    }


def prompt_flags(prompt: str) -> dict[str, bool]:
    text = prompt.lower()
    return {
        "asks_publish": any(word in text for word in ("上传", "发布", "publish", "post live", "发 x", "发x")),
        "asks_launch": any(word in text for word in ("launch", "发布版", "我做的", "i built", "we built", "released", "ship")),
        "asks_compare": any(word in text for word in ("compare", "对比", "比较", "roundup", "候选池", "多个", "5 个")),
        "asks_article": any(word in text for word in ("article", "长文", "x article", "文章")),
        "asks_builder_notes": any(word in text for word in ("我试了", "tested", "demo", "踩坑", "build notes", "build-in-public", "building in public", "mcp creator", "debug memory", "复盘")),
        "asks_profile": any(word in text for word in ("bio", "profile", "置顶", "pinned", "账号定位", "定位", "主页")),
        "asks_no_images": any(word in text for word in ("text-only", "no image", "不要配图", "不要图片", "prompts-only")),
        "asks_images": any(word in text for word in ("配图", "image2", "gpt image", "image 2", "生成图", "actual images")),
    }


def learned_notes(profile: dict[str, Any], strategy_id: str) -> list[str]:
    strategies = profile.get("strategies") or {}
    item = strategies.get(strategy_id) or {}
    notes = []
    guidance = profile.get("evolution_guidance") if isinstance(profile.get("evolution_guidance"), dict) else {}
    for rule in guidance.get("active_rules") or []:
        if rule:
            notes.append(f"Skill evolution guidance: {rule}")
    if item.get("runs"):
        notes.append(
            f"Local strategy memory: {strategy_id} has {item.get('runs')} recorded run(s), "
            f"average score {item.get('avg_score', 0):.3f}."
        )
    lessons = item.get("lessons") or []
    notes.extend(str(lesson) for lesson in lessons[-3:])
    global_lessons = profile.get("global_lessons") or []
    notes.extend(str(lesson) for lesson in global_lessons[-2:])
    return notes


def choose_strategy(classifications: list[dict[str, Any]], prompt: str, profile: dict[str, Any]) -> dict[str, Any]:
    flags = prompt_flags(prompt)
    kinds = {item["kind"] for item in classifications}
    source_count = len(classifications)
    brand_fit = classify_brand_input(
        "\n".join([prompt, *[str(item.get("source", "")) for item in classifications]]),
        kinds,
    )

    if flags["asks_profile"]:
        strategy_id = "profile_positioning"
        strategy_name = "Profile positioning / pinned post"
    elif brand_fit["content_lane"] == "professional_bug_report":
        strategy_id = "professional_bug_report"
        strategy_name = "Professional bug report rewrite"
    elif brand_fit["content_lane"] == "off_main_account_or_agent_link_required":
        strategy_id = "off_main_filter"
        strategy_name = "Off-main-account filter or Agent-link rewrite"
    elif flags["asks_publish"] and "existing_posting_pack" in kinds:
        strategy_id = "publish_existing_pack"
        strategy_name = "Publish approved governed pack"
    elif flags["asks_compare"] or source_count > 1:
        strategy_id = "comparison_or_roundup"
        strategy_name = "Comparison / roundup candidate pool"
    elif flags["asks_launch"]:
        strategy_id = "launch_thread"
        strategy_name = "Launch thread"
    elif "paper" in kinds:
        strategy_id = "paper_to_system"
        strategy_name = "Paper-to-system engineering thread"
    elif flags["asks_article"]:
        strategy_id = "x_article"
        strategy_name = "X Article / long-form post"
    elif flags["asks_builder_notes"]:
        strategy_id = "builder_notes"
        strategy_name = "Builder notes"
    elif kinds & {"github_repo", "local_repo", "local_directory"}:
        strategy_id = "independent_technical_share"
        strategy_name = "Independent technical share"
    else:
        strategy_id = "research_then_post"
        strategy_name = "Research-backed post from arbitrary input"

    if flags["asks_no_images"]:
        image_policy = "user_opted_out"
        image_count = 0
    elif flags["asks_images"]:
        image_policy = "actual_gpt_image_required"
        image_count = 3 if source_count > 1 or strategy_id in {"x_article", "comparison_or_roundup"} else 2
    elif strategy_id == "professional_bug_report":
        image_policy = "manual_evidence_screenshots_preferred"
        image_count = 0
    elif strategy_id in {"profile_positioning", "off_main_filter"}:
        image_policy = "text_only_default"
        image_count = 0
    else:
        image_policy = "actual_gpt_image_default"
        image_count = 1 if strategy_id in {"publish_existing_pack"} else 2

    evidence_plan = []
    for item in classifications:
        if item["kind"] == "github_repo":
            evidence_plan.append("Clone/read repo, inspect README/docs/package files, and fetch live GitHub metadata.")
        elif item["kind"] == "local_repo":
            evidence_plan.append("Read local repo tree, resolve origin remote if present, and fetch live metadata when available.")
        elif item["kind"] == "paper":
            evidence_plan.append("Read paper metadata and PDF text; search for official code before claiming code availability.")
        elif item["kind"] == "web_url":
            evidence_plan.append("Open the page, collect direct quotes sparingly, and distinguish page facts from inference.")
        elif item["kind"] == "existing_posting_pack":
            evidence_plan.append("Re-run cross-check and image gates before any live publish.")
        else:
            evidence_plan.append("Turn the raw input into research questions; do not post factual claims until sourced.")

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "publish_mode": "manual-safe unless the user explicitly approves official-api-publish",
        "image_policy": image_policy,
        "recommended_image_count": image_count,
        "thread_shape": {
            "default_posts": "adaptive",
            "short": "1 post or 4-6 thread items for simple inputs",
            "standard": "6-10 thread items for repo shares or paper-to-system posts",
            "long": "10-15+ only when comparison, caveats, or evidence need space",
        },
        "evidence_plan": list(dict.fromkeys(evidence_plan)),
        "claim_policy": [
            "Every public factual claim maps to source evidence or is removed.",
            "User vision is labeled as personal vision.",
            "Unknowns are converted into caveats, not confident claims.",
        ],
        "brand_profile": {
            "positioning": BRAND_PROFILE["positioning"],
            "tagline": BRAND_PROFILE["tagline"],
            "pillar": brand_fit["pillar"],
            "content_lane": brand_fit["content_lane"],
            "account_fit": brand_fit["account_fit"],
            "emotion_risk": brand_fit["emotion_risk"],
            "routing_note": brand_fit["routing_note"],
            "requires_reusable_asset": True,
            "requires_discussion_question": True,
            "acceptable_assets": brand_fit["required_asset_types"],
            "contract": brand_contract_lines(),
        },
        "learned_notes": learned_notes(profile, strategy_id),
    }


def build_decision(sources: list[str], prompt: str, memory_root: Path) -> dict[str, Any]:
    profile = read_json(memory_root / "strategy_profile.json")
    classifications = [classify_source(source) for source in sources]
    strategy = choose_strategy(classifications, prompt, profile)
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "prompt": prompt,
        "sources": sources,
        "classifications": classifications,
        "recommended_strategy": strategy,
        "memory": {
            "profile_path": str(memory_root / "strategy_profile.json"),
            "outcomes_path": str(memory_root / "outcomes.jsonl"),
            "profile_loaded": bool(profile),
        },
        "next_steps": [
            "Create or reuse a governed run workspace.",
            "Collect source-specific evidence before drafting.",
            "Apply the Agent engineering brand gate before writing public copy.",
            "Fill claims_ledger.json and cross_check_review.md.",
            "Add one reusable asset and one concrete discussion question.",
            "Follow the selected image policy; generate/register GPT Image 2 assets only when the strategy requires generated visuals.",
            "After publish or review, run record_post_outcome.py to evolve local strategy memory.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*", help="Any source: repo, paper URL, web URL, local path, posting pack, profile prompt, support complaint, or raw idea")
    parser.add_argument("--prompt", default="", help="Full user request or angle")
    parser.add_argument("--source-file", help="Optional file containing one source per line")
    parser.add_argument("--memory-root", default=str(Path.cwd() / "repo-to-x-workspace" / "strategy-memory"))
    parser.add_argument("--out", help="Optional path to write strategy_decision.json")
    args = parser.parse_args()

    sources = list(args.sources)
    if args.source_file:
        for line in Path(args.source_file).expanduser().read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if value and not value.startswith("#"):
                sources.append(value)
    if not sources:
        sources = [args.prompt or "raw idea"]

    memory_root = Path(args.memory_root).expanduser().resolve()
    decision = build_decision(sources, args.prompt, memory_root)
    text = json.dumps(decision, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"Wrote strategy decision: {out}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
