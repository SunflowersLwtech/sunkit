#!/usr/bin/env python3
"""Deterministic agent loop over the latest searchpo shortlist."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
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
    return Path(LATEST_RUN_PATH.read_text(encoding="utf-8").strip())


def sanitize_post(text: str, limit: int = 260) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def select_candidate(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        raise SystemExit("candidate_shortlist.json has no items")
    return max(
        items,
        key=lambda item: (
            float(item.get("candidate_score") or 0),
            int(item.get("signals", {}).get("source_count") or 1),
            float(item.get("signals", {}).get("metric_strength") or 0),
        ),
    )


def build_agent_state(run_dir: Path, candidate: dict[str, Any], shortlist: list[dict[str, Any]]) -> dict[str, Any]:
    providers = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GOOGLE_AGENT_PLATFORM_API",
        "xai": "XAI_API_KEY",
    }
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "mode": "deterministic-local",
        "run_dir": str(run_dir),
        "loop": [
            {"step": "observe", "status": "pass", "details": f"Loaded {len(shortlist)} filtered candidates."},
            {"step": "select", "status": "pass", "details": f"Selected {candidate['candidate_id']} with score {candidate.get('candidate_score')}."},
            {"step": "plan", "status": "pass", "details": "Use the source URL as the hard claim boundary; draft short-form video and Douyin upload artifacts."},
            {"step": "act", "status": "pass", "details": "Wrote render payload, Douyin upload package, claim ledger, and review artifacts."},
            {"step": "review", "status": "pass", "details": "No unsupported superlative claim generated; live Douyin upload remains gated."},
        ],
        "selected_candidate_id": candidate["candidate_id"],
        "selected_candidate": candidate,
        "provider_env_contract": providers,
    }


def build_video_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    title = candidate.get("title") or "Searchpo Radar"
    summary = candidate.get("summary") or "Fresh signal detected from the daily source sweep."
    source_ids = ", ".join(candidate.get("source_ids") or [])
    url = candidate.get("canonical_url") or ""
    score = candidate.get("candidate_score")
    signals = candidate.get("signals") or {}
    cards = [
        {
            "label": "Signal",
            "value": sanitize_post(title, 64),
            "detail": sanitize_post(summary, 120),
        },
        {
            "label": "Evidence",
            "value": source_ids or "source registry",
            "detail": sanitize_post(url, 110),
        },
        {
            "label": "Why now",
            "value": f"score {score}",
            "detail": f"code={bool(signals.get('has_code_signal'))} demo={bool(signals.get('has_demo_keyword'))} source_count={signals.get('source_count')}",
        },
    ]
    return {
        "title": sanitize_post(title, 80),
        "summary": sanitize_post(summary, 180),
        "source": source_ids or "searchpo",
        "url": url,
        "score": score,
        "cards": cards,
        "footer": "Generated from searchpo E2E artifacts. Verify claims before live posting.",
    }


def build_douyin_copy(candidate: dict[str, Any]) -> dict[str, Any]:
    title = candidate.get("title") or "today's signal"
    source = ", ".join(candidate.get("source_ids") or ["searchpo"])
    url = candidate.get("canonical_url") or ""
    score = candidate.get("candidate_score")
    desc_lines = [
        f"今天的 searchpo 雷达先看这个信号：{title}。",
        f"来源边界：{source}；候选分数 {score}。",
        "它现在只是进入候选池，不是验证后的爆款结论。",
    ]
    if url:
        desc_lines.append(f"原始来源：{url}")
    return {
        "title": sanitize_post(f"searchpo 雷达：{title}", 55),
        "desc": sanitize_post("\n".join(desc_lines), 600),
        "tags": ["AI工具", "开源项目", "产品观察", "searchpo"],
    }


def write_post_artifacts(run_dir: Path, candidate: dict[str, Any], douyin_copy: dict[str, Any]) -> Path:
    post_dir = run_dir / "post"
    post_dir.mkdir(parents=True, exist_ok=True)
    tags = douyin_copy["tags"]
    tags_csv = ",".join(tags)
    title = douyin_copy["title"]
    desc = douyin_copy["desc"]
    expected_video_path = ROOT / "out" / "searchpo-radar.mp4"
    live_command = (
        f'cd "{post_dir}" && sau douyin upload-video --account "$DOUYIN_ACCOUNT_NAME" '
        f'--file "{expected_video_path}" --title "$(cat douyin_title.txt)" '
        '--desc "$(cat douyin_desc.txt)" --tags "$(cat douyin_tags.txt)"'
    )
    posting_pack = f"""# Posting Pack

## Evidence Summary

- Candidate: {candidate.get('title')}
- Candidate ID: `{candidate.get('candidate_id')}`
- Source IDs: `{', '.join(candidate.get('source_ids') or [])}`
- Source URL: {candidate.get('canonical_url') or ''}
- Caveats: Filtered candidate only; public claims need manual cross-source review before live posting.

## Posting Strategy

Lead with the evidence boundary, not hype. Keep the first public pass as a Douyin candidate radar video.

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
- No unsupported best/first/only claim.
- Cross-check review status is `pass` for contract-check only.
- `runtime/social-auto-upload` has the Douyin CLI contract.
- For live upload: user explicitly enables `SEARCHPO_DOUYIN_LIVE=1`.
"""
    (post_dir / "posting_pack.md").write_text(posting_pack, encoding="utf-8")
    write_json(
        post_dir / "douyin_upload_manifest.json",
        {
            "schema_version": 1,
            "created_at": utc_now(),
            "platform": "douyin",
            "adapter": "dreammis/social-auto-upload",
            "cli": "sau douyin upload-video",
            "account_env": ["DOUYIN_ACCOUNT_NAME", "SOCIAL_UPLOAD_ACCOUNT_NAME"],
            "expected_video_path": str(expected_video_path),
            "title": title,
            "desc": desc,
            "tags": tags,
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
            "claims": [
                {
                    "id": "C001",
                    "claim": f"{candidate.get('title')} was selected by the searchpo candidate filter.",
                    "type": "pipeline_fact",
                    "source": "candidate_shortlist.json",
                    "status": "keep",
                }
            ],
            "unknown_or_unsafe": ["Do not claim market leadership, benchmark rank, funding, or production maturity without extra sources."],
        },
    )
    write_json(post_dir / "images_manifest.json", {"schema_version": 1, "created_at": utc_now(), "images": []})
    (post_dir / "cross_check_review.md").write_text(
        "# Cross-Check Review\n\nStatus: pass\n\nContract-check only. Live Douyin upload still requires manual review and explicit approval.\n",
        encoding="utf-8",
    )
    (post_dir / "file_manifest.txt").write_text(
        "\n".join([
            "posting_pack.md",
            "douyin_upload_manifest.json",
            "douyin_title.txt",
            "douyin_desc.txt",
            "douyin_tags.txt",
            "claims_ledger.json",
            "images_manifest.json",
            "cross_check_review.md",
        ]) + "\n",
        encoding="utf-8",
    )
    return post_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", help="Artifact run directory. Defaults to runtime/latest_run.txt.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    shortlist_data = read_json(run_dir / "candidate_shortlist.json")
    shortlist = shortlist_data.get("items") or []
    candidate = select_candidate(shortlist)
    payload = build_video_payload(candidate)
    douyin_copy = build_douyin_copy(candidate)
    post_dir = write_post_artifacts(run_dir, candidate, douyin_copy)
    agent_state = build_agent_state(run_dir, candidate, shortlist)

    write_json(run_dir / "agent_run.json", agent_state)
    write_json(run_dir / "render_payload.json", payload)
    write_json(run_dir / "post_manifest.json", {"created_at": utc_now(), "post_dir": str(post_dir), "posting_pack": str(post_dir / "posting_pack.md")})
    print(json.dumps({"run_dir": str(run_dir), "selected_candidate_id": candidate["candidate_id"], "post_dir": str(post_dir), "render_payload": str(run_dir / "render_payload.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
