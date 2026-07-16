#!/usr/bin/env python3
"""Synthesize run outcomes into an auditable skill-evolution report.

This script turns local evals, publish logs, post outcomes, and trending
experiments into a signal ledger plus a proposed patch plan. It intentionally
does not edit SKILL.md or scripts. Use --apply-profile only to write reviewed
guidance into the ignored local strategy profile, where future routing can read
it as a bias.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._") or "skill-evolution"


def default_run_id() -> str:
    return "skill_evolution_" + datetime.now().strftime("%Y%m%d_%H%M%S")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_error": f"invalid json: {path}"}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError:
            rows.append({"_error": f"invalid jsonl row in {path}", "raw": stripped[:500]})
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


def source_label(repo_dir: Path) -> str:
    context = read_json(repo_dir / "repo_context.json") or read_json(repo_dir / "source_context.json")
    return str(
        context.get("owner_repo")
        or context.get("source")
        or context.get("title")
        or repo_dir.name
    )


def publish_summary(repo_dir: Path) -> dict[str, Any]:
    log = read_json(repo_dir / "x_publish_log.json")
    if not log:
        return {"published": False, "post_count": 0, "image_first_post": False}
    posts = log.get("posts") or []
    return {
        "published": bool(posts and not log.get("dry_run")),
        "post_count": len(posts),
        "tweet_ids": [post.get("tweet_id") for post in posts if post.get("tweet_id")],
        "image_first_post": bool(posts and posts[0].get("image_ids")),
    }


def collect_post_eval_signals(runs_root: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(runs_root.rglob("post_eval.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if len(rows) >= limit:
            break
        repo_dir = path.parent
        data = read_json(path)
        scores = data.get("scores") if isinstance(data.get("scores"), dict) else {}
        deterministic = data.get("deterministic") if isinstance(data.get("deterministic"), dict) else {}
        features = deterministic.get("features") if isinstance(deterministic.get("features"), dict) else {}
        images = deterministic.get("images") if isinstance(deterministic.get("images"), dict) else {}
        rows.append(
            {
                "kind": "post_eval",
                "path": str(path),
                "repo_dir": str(repo_dir),
                "source": source_label(repo_dir),
                "decision": data.get("decision"),
                "final_score": data.get("final_score"),
                "semantic_score": data.get("semantic_score"),
                "scores": scores,
                "top_fixes": data.get("top_fixes") or [],
                "features": {
                    key: features.get(key)
                    for key in (
                        "post_count",
                        "max_length",
                        "generic_opener_count",
                        "repo_note_opener_count",
                        "summary_phrase_count",
                        "concrete_marker_count",
                        "example_marker_count",
                        "first_thesis_marker_count",
                        "voice_drift_count",
                    )
                },
                "images": {
                    key: images.get(key)
                    for key in ("actual_count", "approved_count", "missing_file_count", "missing_alt_count")
                },
                "publish": publish_summary(repo_dir),
            }
        )
    return rows


def collect_outcome_signals(memory_root: Path, runs_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in read_jsonl(memory_root / "outcomes.jsonl"):
        rows.append(
            {
                "kind": "recorded_outcome",
                "path": str(memory_root / "outcomes.jsonl"),
                "repo_run_dir": row.get("repo_run_dir"),
                "strategy_id": row.get("strategy_id"),
                "source_kind": row.get("source_kind"),
                "score": row.get("score"),
                "metrics": row.get("metrics") or {},
                "lessons": row.get("lessons") or [],
                "published": row.get("published"),
                "tweet_ids": row.get("tweet_ids") or [],
            }
        )
    for path in sorted(runs_root.rglob("post_outcome.json")):
        row = read_json(path)
        if not row:
            continue
        rows.append(
            {
                "kind": "post_outcome",
                "path": str(path),
                "repo_run_dir": row.get("repo_run_dir") or str(path.parent),
                "strategy_id": row.get("strategy_id"),
                "score": row.get("score"),
                "metrics": row.get("metrics") or {},
                "lessons": row.get("lessons") or [],
                "tweet_ids": row.get("tweet_ids") or [],
            }
        )
    return rows


def collect_experiment_signals(runs_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(runs_root.rglob("trending_experiment_results.json")):
        data = read_json(path)
        results = data.get("results") if isinstance(data.get("results"), list) else []
        rewrite_decisions = [
            decision
            for row in results
            for decision in row.get("rewrite_decisions", [])
            if isinstance(decision, dict)
        ]
        rows.append(
            {
                "kind": "trending_experiment",
                "path": str(path),
                "run_id": data.get("run_id") or path.parent.name,
                "repo_count": len(results),
                "ready_count": sum(1 for row in results if row.get("final_decision") == "ready"),
                "avg_final_score": mean(
                    [float(row.get("final_score") or 0.0) for row in results]
                )
                if results
                else 0.0,
                "common_fixes": data.get("common_fixes") or [],
                "converged_rules": data.get("converged_rules") or [],
                "rewrite_accepts": sum(1 for item in rewrite_decisions if item.get("accepted")),
                "rewrite_rejects": sum(1 for item in rewrite_decisions if not item.get("accepted")),
                "metadata_only": any(
                    "metadata-only" in str(row.get("source_kind", "")).lower()
                    for row in data.get("repos", [])
                    if isinstance(row, dict)
                ),
            }
        )
    return rows


def collect_profile(memory_root: Path) -> dict[str, Any]:
    profile = read_json(memory_root / "strategy_profile.json")
    return profile if isinstance(profile, dict) else {}


def stable_bucket(value: str) -> int:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def split_post_evals(
    post_evals: list[dict[str, Any]],
    selection_percent: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not post_evals:
        return [], []
    selection_percent = max(0, min(90, int(selection_percent)))
    if selection_percent == 0 or len(post_evals) < 3:
        return post_evals, []
    train: list[dict[str, Any]] = []
    selection: list[dict[str, Any]] = []
    for row in post_evals:
        key = str(row.get("path") or row.get("repo_dir") or row.get("source") or "")
        if stable_bucket(key) < selection_percent:
            selection.append(row)
        else:
            train.append(row)
    if not train and selection:
        train.append(selection.pop())
    if not selection and len(train) > 3:
        selection.append(train.pop())
    return train, selection


def score_band(score: Any) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if value >= 0.85:
        return "strong"
    if value >= 0.78:
        return "usable"
    if value >= 0.65:
        return "weak"
    return "poor"


def add_recommendation(
    recommendations: list[dict[str, Any]],
    key: str,
    title: str,
    change: str,
    reason: str,
    evidence: list[str],
    priority: str = "P1",
) -> None:
    if not evidence:
        return
    recommendations.append(
        {
            "key": key,
            "priority": priority,
            "title": title,
            "proposed_change": change,
            "reason": reason,
            "evidence": evidence[:8],
            "status": "proposed_for_human_review",
        }
    )


def aggregate(
    signals: dict[str, Any],
    runs_root: Path,
    memory_root: Path,
    *,
    split_name: str = "train",
) -> dict[str, Any]:
    evals = signals["post_evals"]
    outcomes = signals["outcomes"]
    experiments = signals["experiments"]
    profile = signals["strategy_profile"]

    fixes = Counter()
    dimensions: dict[str, list[float]] = defaultdict(list)
    decisions = Counter()
    source_bands = Counter()
    for row in evals:
        decisions.update([str(row.get("decision") or "unknown")])
        source_bands.update([score_band(row.get("final_score"))])
        fixes.update(str(fix) for fix in row.get("top_fixes", []) if fix)
        for key, value in (row.get("scores") or {}).items():
            if isinstance(value, (int, float)):
                dimensions[key].append(float(value))

    outcome_lessons = Counter()
    for row in outcomes:
        for lesson in row.get("lessons", []):
            if lesson:
                outcome_lessons.update([str(lesson)])

    experiment_fixes = Counter()
    experiment_rules = Counter()
    for row in experiments:
        for item in row.get("common_fixes", []):
            if isinstance(item, list) and item:
                count = int(item[1]) if len(item) > 1 and isinstance(item[1], int) else 1
                experiment_fixes.update({str(item[0]): count})
        for rule in row.get("converged_rules", []):
            if rule:
                experiment_rules.update([str(rule)])

    avg_dimensions = {
        key: sum(values) / len(values)
        for key, values in sorted(dimensions.items())
        if values
    }
    weak_dimensions = {
        key: value
        for key, value in avg_dimensions.items()
        if value < 0.76 and key not in {"media_quality"}
    }

    evidence_by_topic: dict[str, list[str]] = defaultdict(list)
    for fix, count in (fixes + experiment_fixes).most_common():
        lower = fix.lower()
        label = f"{count}x {fix}" if count > 1 else fix
        if re.search(r"hook|opener|thesis|setup", lower):
            evidence_by_topic["hook_thesis"].append(label)
        if re.search(r"example|specific|concrete|density", lower):
            evidence_by_topic["specificity"].append(label)
        if re.search(r"caveat|risk|boundary|limitation", lower):
            evidence_by_topic["caveat"].append(label)
        if re.search(r"voice|language|english|中文|tone", lower):
            evidence_by_topic["voice"].append(label)
        if re.search(r"image|media|alt|visual", lower):
            evidence_by_topic["media"].append(label)
        if re.search(r"brand|account|agent engineering|main account|off-main|定位", lower):
            evidence_by_topic["brand_fit"].append(label)
        if re.search(r"asset|checklist|template|flowchart|prompt|question|cta|讨论|问题", lower):
            evidence_by_topic["asset_cta"].append(label)
        if re.search(r"emotion|complaint|bug report|kyc|support|hashtag|anger|情绪|吐槽", lower):
            evidence_by_topic["emotion_control"].append(label)

    for key, value in weak_dimensions.items():
        if key in {"hook_strength", "angle_freshness"}:
            evidence_by_topic["hook_thesis"].append(f"avg {key}={value:.3f}")
        elif key in {"specificity_density", "bookmark_value"}:
            evidence_by_topic["specificity"].append(f"avg {key}={value:.3f}")
        elif key in {"risk_control", "claim_safety"}:
            evidence_by_topic["caveat"].append(f"avg {key}={value:.3f}")
        elif key == "voice_authenticity":
            evidence_by_topic["voice"].append(f"avg {key}={value:.3f}")
        elif key in {"brand_clarity", "account_fit"}:
            evidence_by_topic["brand_fit"].append(f"avg {key}={value:.3f}")
        elif key in {"asset_value", "cta_specificity"}:
            evidence_by_topic["asset_cta"].append(f"avg {key}={value:.3f}")
        elif key == "emotion_control":
            evidence_by_topic["emotion_control"].append(f"avg {key}={value:.3f}")

    recommendations: list[dict[str, Any]] = []
    add_recommendation(
        recommendations,
        "angle_first_hook_contract",
        "Strengthen the first-post thesis contract",
        "Require post 1 to state a repeatable technical thesis or workflow constraint before any repo metadata.",
        "Weak hooks and repo-note openers are the dominant failure mode in eval and trending experiments.",
        evidence_by_topic["hook_thesis"],
        "P0",
    )
    add_recommendation(
        recommendations,
        "concrete_example_gate",
        "Keep the concrete example gate explicit",
        "Every candidate pack should include one file, command, API, benchmark, before/after, or workflow step that a reader can inspect.",
        "Specificity failures make safe posts feel like README summaries.",
        evidence_by_topic["specificity"],
        "P1",
    )
    add_recommendation(
        recommendations,
        "visible_caveat_gate",
        "Make caveats part of quality, not just safety",
        "Require a visible caveat or boundary in the main thread, especially for metadata-only, early-stage, benchmark, or generated-image claims.",
        "Risk-control and caveat signals prevent high-confidence but brittle posts.",
        evidence_by_topic["caveat"],
        "P1",
    )
    add_recommendation(
        recommendations,
        "coherent_voice_gate",
        "Guard against language drift",
        "Keep Chinese as the default voice for Chinese prompts and reserve English for repo names, commands, APIs, paths, or one deliberate hook.",
        "Mixed-language voice drift weakens the user's preferred high-taste style.",
        evidence_by_topic["voice"],
        "P2",
    )
    add_recommendation(
        recommendations,
        "visual_governance_gate",
        "Preserve actual governed images for publish prep",
        "Generate images only after a candidate survives text screening, then register governed files with alt text and disclosure before live publish.",
        "Media issues should not pollute early text-only screening but must block final publishing if ungoverned.",
        evidence_by_topic["media"] or [
            "Image gates are separate from text-only eval by design.",
        ],
        "P1",
    )
    add_recommendation(
        recommendations,
        "agent_engineering_brand_gate",
        "Keep the account legible as Agent engineering practice",
        "Route every draft through the brand lane: agent reliability, build-in-public, paper-to-system, embodied AI watch, professional bug report, or off-main-account.",
        "Brand clarity and account-fit failures turn strong technical notes into an unmemorable mixed stream.",
        evidence_by_topic["brand_fit"],
        "P0",
    )
    add_recommendation(
        recommendations,
        "asset_and_question_gate",
        "Require one reusable asset and one concrete question",
        "Every final thread should include a saveable checklist/template/flow/prompt/failure map and end with a specific technical discussion question.",
        "Posts with no asset and no question are hard to bookmark or reply to even when they are accurate.",
        evidence_by_topic["asset_cta"],
        "P0",
    )
    add_recommendation(
        recommendations,
        "professional_complaint_gate",
        "Convert support anger into bug-report language",
        "KYC/support/platform complaints should use repro, impact, expected behavior, evidence, and next action; otherwise move them off the main account.",
        "Emotion and complaint-shape failures damage the account more than they help support escalation.",
        evidence_by_topic["emotion_control"],
        "P1",
    )

    if experiments:
        accepted = sum(int(row.get("rewrite_accepts") or 0) for row in experiments)
        rejected = sum(int(row.get("rewrite_rejects") or 0) for row in experiments)
        add_recommendation(
            recommendations,
            "rewrite_acceptance_gate",
            "Keep tournament rewrites score-gated",
            "Accept tournament rewrites only when the candidate improves decision rank or clears a real score improvement threshold.",
            "Tournament rewrites can produce plausible paraphrases that do not improve the actual eval result.",
            [f"accepted={accepted}, rejected={rejected}"],
            "P0",
        )
        add_recommendation(
            recommendations,
            "metadata_first_funnel",
            "Keep metadata-only trending screening as stage one",
            "Use metadata/readme screening before deep clone, image generation, and publish gates for broad Trending runs.",
            "Broad candidate search should spend expensive work only after angle quality survives text-only screening.",
            [f"{row.get('run_id')}: repos={row.get('repo_count')}, ready={row.get('ready_count')}" for row in experiments],
            "P0",
        )

    active_rules = [
        rec["proposed_change"]
        for rec in recommendations
        if rec["priority"] in {"P0", "P1"}
    ][:8]

    strategy_scores = {}
    for strategy_id, item in (profile.get("strategies") or {}).items():
        strategy_scores[strategy_id] = {
            "runs": item.get("runs", 0),
            "avg_score": item.get("avg_score", 0),
            "last_score": item.get("last_score", 0),
            "lessons": item.get("lessons", [])[-5:],
        }

    return {
        "created_at": utc_now(),
        "split_name": split_name,
        "source_roots": {
            "runs_root": str(runs_root),
            "memory_root": str(memory_root),
        },
        "counts": {
            "post_evals": len(evals),
            "outcomes": len(outcomes),
            "experiments": len(experiments),
            "strategies_in_profile": len(strategy_scores),
        },
        "decision_counts": dict(decisions),
        "score_bands": dict(source_bands),
        "average_dimensions": avg_dimensions,
        "weak_dimensions": weak_dimensions,
        "common_fixes": fixes.most_common(20),
        "experiment_fixes": experiment_fixes.most_common(20),
        "experiment_rules": experiment_rules.most_common(20),
        "outcome_lessons": outcome_lessons.most_common(20),
        "strategy_scores": strategy_scores,
        "recommendations": recommendations,
        "active_rules": active_rules,
        "profile_has_existing_guidance": bool(profile.get("evolution_guidance")),
    }


def evidence_support(evidence: list[str]) -> int:
    total = 0
    for item in evidence:
        match = re.match(r"(\d+)x\s+", str(item))
        if match:
            total += int(match.group(1))
        else:
            total += 1
    return total


def apply_selection_gate(
    summary: dict[str, Any],
    selection_summary: dict[str, Any],
    *,
    min_support: int,
) -> None:
    selection_by_key = {
        rec.get("key"): rec
        for rec in selection_summary.get("recommendations", [])
        if rec.get("key")
    }
    experiment_backed = {"rewrite_acceptance_gate", "metadata_first_funnel"}
    for rec in summary.get("recommendations", []):
        key = rec.get("key")
        selection_rec = selection_by_key.get(key)
        if selection_rec:
            support = evidence_support(selection_rec.get("evidence", []))
            accepted = support >= min_support
            rec["selection_gate"] = {
                "status": "accepted" if accepted else "rejected",
                "reason": (
                    f"held-out selection support={support}, threshold={min_support}"
                    if accepted
                    else f"held-out selection support={support} below threshold={min_support}"
                ),
                "support": support,
                "evidence": selection_rec.get("evidence", [])[:6],
            }
        elif key in experiment_backed and rec.get("evidence"):
            rec["selection_gate"] = {
                "status": "accepted",
                "reason": "experiment-level gate; supported by multi-run experiment artifacts rather than post-eval split",
                "support": evidence_support(rec.get("evidence", [])),
                "evidence": rec.get("evidence", [])[:6],
            }
        else:
            rec["selection_gate"] = {
                "status": "rejected",
                "reason": "not reproduced in held-out selection split",
                "support": 0,
                "evidence": [],
            }


def recommendation_sort_key(rec: dict[str, Any]) -> tuple[int, int]:
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    support = int((rec.get("selection_gate") or {}).get("support") or evidence_support(rec.get("evidence", [])))
    return (priority_order.get(str(rec.get("priority")), 9), -support)


def clip_active_rules(summary: dict[str, Any], learning_rate: int) -> None:
    budget = max(1, int(learning_rate))
    accepted = [
        rec
        for rec in summary.get("recommendations", [])
        if (rec.get("selection_gate") or {}).get("status") == "accepted"
    ]
    accepted.sort(key=recommendation_sort_key)
    selected = accepted[:budget]
    summary["textual_learning_rate"] = {
        "mode": "constant",
        "edit_budget": budget,
        "accepted_recommendations": len(accepted),
        "selected_recommendations": len(selected),
        "clipped_recommendations": max(0, len(accepted) - len(selected)),
    }
    selected_keys = {rec.get("key") for rec in selected}
    for rec in summary.get("recommendations", []):
        gate = rec.setdefault("selection_gate", {"status": "not_evaluated"})
        if gate.get("status") != "accepted":
            rec["active_rule_selected"] = False
        elif rec.get("key") in selected_keys:
            rec["active_rule_selected"] = True
        else:
            rec["active_rule_selected"] = False
            rec["selection_gate"] = {
                **gate,
                "status": "clipped",
                "reason": f"accepted by held-out gate but clipped by textual learning rate budget={budget}",
            }
    summary["active_rules"] = [rec["proposed_change"] for rec in selected]


PATCH_TARGETS = {
    "angle_first_hook_contract": {
        "target": "Before locking the draft, do an angle pass:",
        "content": "- Treat post 1 as the selection gate for taste: it must state a repeatable technical thesis or workflow constraint before repo metadata.",
    },
    "concrete_example_gate": {
        "target": "- Find the one thesis a technical reader would remember or repeat.",
        "content": "- Include one concrete inspectable example: a file, command, API, benchmark, before/after, or workflow step.",
    },
    "visible_caveat_gate": {
        "target": "- If the result reads like a paper abstract or README split into numbered posts, it is not ready even if the claims are safe.",
        "content": "- Make one caveat or boundary visible in the main thread when evidence is metadata-only, early-stage, benchmark-like, or generated-image-adjacent.",
    },
    "coherent_voice_gate": {
        "target": "- Use one coherent voice. Chinese is default; English is for repo names, file paths, API names, commands, or one deliberate hook line.",
        "content": "- Keep voice consistent across the thread; do not drift into bilingual filler unless it serves reach or exact technical naming.",
    },
    "visual_governance_gate": {
        "target": "Default rule: a technical final X posting pack includes actual generated images.",
        "content": "Default rule: a technical final X posting pack includes actual generated images, but broad candidate search stays text-only until the candidate survives angle screening.",
    },
    "agent_engineering_brand_gate": {
        "target": "Before locking the draft, do an angle pass:",
        "content": "- Confirm the brand lane before drafting: agent reliability, build-in-public, paper-to-system, embodied AI watch, professional bug report, or off-main-account.",
    },
    "asset_and_question_gate": {
        "target": "- Name the reusable asset before drafting the final thread.",
        "content": "- Keep the reusable asset and final discussion question as publish gates, not optional polish.",
    },
    "professional_complaint_gate": {
        "target": "- KYC/support/platform complaint -> professional bug-report workflow:",
        "content": "- KYC/support/platform complaints must become repro, impact, expected behavior, evidence, and next action; otherwise route them off the main account.",
    },
    "rewrite_acceptance_gate": {
        "target": "- Accept a tournament rewrite only if its eval score improves over the current accepted draft.",
        "content": "- Accept a tournament rewrite only if it improves decision rank or clears the configured score improvement threshold over the current accepted draft.",
    },
    "metadata_first_funnel": {
        "target": "Default to a two-stage funnel:",
        "content": "Default to a two-stage funnel: metadata/readme text screening first, then deep clone, image generation, and publish gates only for selected candidates.",
    },
}


def build_structured_patch(summary: dict[str, Any]) -> dict[str, Any]:
    edits: list[dict[str, Any]] = []
    for rec in summary.get("recommendations", []):
        target = PATCH_TARGETS.get(str(rec.get("key")), {})
        gate = rec.get("selection_gate") or {}
        op = "insert_after"
        if rec.get("key") == "visual_governance_gate":
            op = "replace"
        edit = {
            "op": op,
            "target": target.get("target", ""),
            "content": target.get("content", rec.get("proposed_change", "")),
            "status": "selected" if rec.get("active_rule_selected") else "not_selected",
            "priority": rec.get("priority"),
            "source_key": rec.get("key"),
            "selection_gate": gate,
            "support_count": gate.get("support") or evidence_support(rec.get("evidence", [])),
            "reason": rec.get("reason"),
        }
        edits.append(edit)
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "status": "proposed_for_human_review",
        "update_mode": "patch",
        "textual_learning_rate": summary.get("textual_learning_rate", {}),
        "edits": edits,
        "guardrail": "Do not apply automatically; review targets, run held-out evals, then patch canonical files manually.",
    }


def write_history_and_state(
    out_dir: Path,
    summary: dict[str, Any],
    structured_patch: dict[str, Any],
    *,
    skill_path: Path,
    report_path: Path,
    patch_path: Path,
    structured_patch_path: Path,
) -> None:
    skill_text = skill_path.read_text(encoding="utf-8") if skill_path.exists() else ""
    selected_edits = [edit for edit in structured_patch.get("edits", []) if edit.get("status") == "selected"]
    rejected_edits = [
        edit
        for edit in structured_patch.get("edits", [])
        if (edit.get("selection_gate") or {}).get("status") == "rejected"
    ]
    history = [
        {
            "step": 1,
            "created_at": utc_now(),
            "action": "propose_patch_plan",
            "train_signal_count": summary.get("counts", {}).get("post_evals"),
            "selection_gate": summary.get("selection_gate", {}),
            "selected_edits": len(selected_edits),
            "rejected_edits": len(rejected_edits),
            "textual_learning_rate": summary.get("textual_learning_rate", {}),
            "report_path": str(report_path),
            "patch_plan_path": str(patch_path),
            "structured_patch_path": str(structured_patch_path),
        }
    ]
    write_json(out_dir / "history.json", history)
    write_json(
        out_dir / "runtime_state.json",
        {
            "schema_version": 1,
            "created_at": utc_now(),
            "last_completed_step": 1,
            "current_skill_path": str(skill_path),
            "current_skill_sha256": sha256_text(skill_text) if skill_text else "",
            "best_skill_path": str(out_dir / "best_skill.md"),
            "best_skill_is_snapshot": True,
            "selected_edit_count": len(selected_edits),
            "rejected_edit_count": len(rejected_edits),
            "selection_gate": summary.get("selection_gate", {}),
        },
    )
    if skill_text:
        (out_dir / "best_skill.md").write_text(skill_text, encoding="utf-8")


def update_rejected_buffer(memory_root: Path, structured_patch: dict[str, Any]) -> Path:
    path = memory_root / "rejected_evolution_edits.jsonl"
    for edit in structured_patch.get("edits", []):
        gate = edit.get("selection_gate") or {}
        if gate.get("status") == "rejected":
            append_jsonl(
                path,
                {
                    "created_at": utc_now(),
                    "source_key": edit.get("source_key"),
                    "op": edit.get("op"),
                    "target": edit.get("target"),
                    "content": edit.get("content"),
                    "reason": gate.get("reason"),
                    "support": gate.get("support"),
                },
            )
    return path


def write_report(
    path: Path,
    summary: dict[str, Any],
    ledger_path: Path,
    patch_path: Path,
    structured_patch_path: Path,
) -> None:
    lines = [
        "# Skill Evolution Report",
        "",
        f"- Created at: {summary['created_at']}",
        f"- Runs root: `{summary['source_roots']['runs_root']}`",
        f"- Memory root: `{summary['source_roots']['memory_root']}`",
        f"- Signal ledger: `{ledger_path}`",
        f"- Patch plan: `{patch_path}`",
        f"- Structured patch: `{structured_patch_path}`",
        "",
        "## Signal Counts",
        "",
    ]
    for key, value in summary["counts"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Decisions", ""])
    for key, value in summary.get("decision_counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Weak Dimensions", ""])
    if summary.get("weak_dimensions"):
        for key, value in summary["weak_dimensions"].items():
            lines.append(f"- `{key}`: {value:.3f}")
    else:
        lines.append("- No weak dimension crossed the default threshold.")
    lines.extend(["", "## Top Fixes", ""])
    for fix, count in summary.get("common_fixes", [])[:12]:
        lines.append(f"- {count}x {fix}")
    if not summary.get("common_fixes"):
        lines.append("- No post_eval fixes found.")
    lines.extend(["", "## Recommended Evolution Rules", ""])
    lr = summary.get("textual_learning_rate") or {}
    if lr:
        lines.extend(
            [
                f"- Textual learning rate edit budget: `{lr.get('edit_budget')}`",
                f"- Selected recommendations: `{lr.get('selected_recommendations')}`",
                f"- Clipped recommendations: `{lr.get('clipped_recommendations')}`",
                "",
            ]
        )
    for rec in summary.get("recommendations", []):
        gate = rec.get("selection_gate") or {}
        selected = "selected" if rec.get("active_rule_selected") else "not selected"
        lines.append(f"### {rec['priority']} {rec['title']}")
        lines.append(f"- Gate: `{gate.get('status', 'unknown')}` ({gate.get('reason', 'no reason')}); {selected}")
        lines.append(f"- Change: {rec['proposed_change']}")
        lines.append(f"- Reason: {rec['reason']}")
        lines.append("- Evidence:")
        for item in rec.get("evidence", []):
            lines.append(f"  - {item}")
        lines.append("")
    lines.extend(
        [
            "## Guardrail",
            "",
            "This report is advisory. It may update ignored local strategy memory with `--apply-profile`, but it does not edit canonical skill files or public claims. Human review is required before turning proposed rules into permanent skill instructions.",
            "",
        ]
    )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_patch_plan(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Proposed Skill Patch Plan",
        "",
        "Status: proposed_for_human_review",
        "",
        "Apply these as small reviewed changes. Do not batch unrelated style changes with claim-safety changes.",
        "",
    ]
    if not summary.get("recommendations"):
        lines.append("No recommendations generated from the current signal set.")
    for index, rec in enumerate(summary.get("recommendations", []), start=1):
        lines.extend(
            [
                f"## {index}. {rec['title']}",
                "",
                f"- Priority: {rec['priority']}",
                f"- Target: `{rec['key']}`",
                f"- Selection gate: `{(rec.get('selection_gate') or {}).get('status', 'unknown')}`",
                f"- Active after textual LR: `{bool(rec.get('active_rule_selected'))}`",
                f"- Proposed change: {rec['proposed_change']}",
                f"- Reason: {rec['reason']}",
                "- Suggested surfaces:",
            ]
        )
        if rec["key"] in {"angle_first_hook_contract", "concrete_example_gate", "visible_caveat_gate", "coherent_voice_gate"}:
            lines.extend(
                [
                    "  - `skills/github-repo-to-x-threads/SKILL.md` angle pass / draft rules",
                    "  - `skills/github-repo-to-x-threads/scripts/x_generate_posting_pack.py` generation prompt",
                    "  - `skills/github-repo-to-x-threads/scripts/x_eval_post.py` deterministic features and fixes",
                    "  - `evals/evals.json` regression prompt",
                ]
            )
        elif rec["key"] in {"metadata_first_funnel", "rewrite_acceptance_gate"}:
            lines.extend(
                [
                    "  - `skills/github-repo-to-x-threads/scripts/x_trending_experiment.py`",
                    "  - `skills/github-repo-to-x-threads/references/self-evolving-strategy.md`",
                    "  - `README.md` experiment workflow",
                ]
            )
        elif rec["key"] == "visual_governance_gate":
            lines.extend(
                [
                    "  - `skills/github-repo-to-x-threads/SKILL.md` image governance section",
                    "  - `skills/github-repo-to-x-threads/scripts/check_image_assets.py`",
                    "  - `skills/github-repo-to-x-threads/scripts/x_publish_thread.py`",
                ]
            )
        else:
            lines.append("  - Review manually.")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def apply_profile_guidance(memory_root: Path, summary: dict[str, Any], report_path: Path, patch_path: Path) -> Path:
    profile_path = memory_root / "strategy_profile.json"
    profile = read_json(profile_path)
    if not profile:
        profile = {
            "schema_version": 1,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "strategies": {},
            "global_lessons": [],
        }
    profile["updated_at"] = utc_now()
    profile["evolution_guidance"] = {
        "updated_at": utc_now(),
        "status": "proposed_for_human_review",
        "source_report": str(report_path),
        "source_patch_plan": str(patch_path),
        "active_rules": summary.get("active_rules", []),
        "recommendation_count": len(summary.get("recommendations", [])),
        "guardrail": "Local routing bias only; does not authorize unsupported claims or automatic canonical skill edits.",
    }
    write_json(profile_path, profile)
    return profile_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", default=str(Path.cwd() / "repo-to-x-workspace" / "runs"))
    parser.add_argument("--memory-root", default=str(Path.cwd() / "repo-to-x-workspace" / "strategy-memory"))
    parser.add_argument("--out-root", default=str(Path.cwd() / "repo-to-x-workspace" / "skill-evolution"))
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--max-post-evals", type=int, default=200)
    parser.add_argument(
        "--skill-path",
        default=str(Path(__file__).resolve().parents[1] / "SKILL.md"),
        help="Canonical skill document to snapshot as best_skill.md.",
    )
    parser.add_argument(
        "--selection-percent",
        type=int,
        default=25,
        help="Deterministic held-out percentage of post_eval signals used for selection gate.",
    )
    parser.add_argument(
        "--min-selection-support",
        type=int,
        default=1,
        help="Minimum held-out evidence items required to accept a proposed rule.",
    )
    parser.add_argument(
        "--learning-rate",
        type=int,
        default=4,
        help="Textual learning rate: max accepted evolution rules selected as active guidance.",
    )
    parser.add_argument(
        "--apply-profile",
        action="store_true",
        help="Write proposed guidance into ignored strategy_profile.json for future routing bias.",
    )
    parser.add_argument(
        "--update-rejected-buffer",
        action="store_true",
        help="Append held-out rejected edit proposals into ignored rejected_evolution_edits.jsonl.",
    )
    args = parser.parse_args()

    runs_root = Path(args.runs_root).expanduser().resolve()
    memory_root = Path(args.memory_root).expanduser().resolve()
    out_dir = Path(args.out_root).expanduser().resolve() / safe_slug(args.run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    post_evals = collect_post_eval_signals(runs_root, args.max_post_evals) if runs_root.exists() else []
    train_evals, selection_evals = split_post_evals(post_evals, args.selection_percent)
    rejected_buffer_path = memory_root / "rejected_evolution_edits.jsonl"
    signals = {
        "schema_version": 1,
        "created_at": utc_now(),
        "runs_root": str(runs_root),
        "memory_root": str(memory_root),
        "post_evals": post_evals,
        "train_post_evals": train_evals,
        "selection_post_evals": selection_evals,
        "outcomes": collect_outcome_signals(memory_root, runs_root) if runs_root.exists() or memory_root.exists() else [],
        "experiments": collect_experiment_signals(runs_root) if runs_root.exists() else [],
        "strategy_profile": collect_profile(memory_root),
        "rejected_evolution_edits": read_jsonl(rejected_buffer_path),
        "split_policy": {
            "selection_percent": args.selection_percent,
            "train_count": len(train_evals),
            "selection_count": len(selection_evals),
            "min_selection_support": args.min_selection_support,
        },
    }
    train_signals = {**signals, "post_evals": train_evals}
    selection_signals = {**signals, "post_evals": selection_evals, "experiments": []}
    summary = aggregate(train_signals, runs_root, memory_root, split_name="train")
    selection_summary = aggregate(selection_signals, runs_root, memory_root, split_name="selection")
    summary["selection_split"] = signals["split_policy"]
    summary["selection_summary"] = {
        "counts": selection_summary.get("counts", {}),
        "weak_dimensions": selection_summary.get("weak_dimensions", {}),
        "recommendation_keys": [rec.get("key") for rec in selection_summary.get("recommendations", [])],
    }
    apply_selection_gate(summary, selection_summary, min_support=args.min_selection_support)
    clip_active_rules(summary, args.learning_rate)
    ledger_path = out_dir / "signal_ledger.json"
    summary_path = out_dir / "skill_evolution_summary.json"
    report_path = out_dir / "skill_evolution_report.md"
    patch_path = out_dir / "skill_patch_plan.md"
    structured_patch_path = out_dir / "skill_patch_plan.json"
    structured_patch = build_structured_patch(summary)
    write_json(ledger_path, signals)
    write_json(summary_path, summary)
    write_json(structured_patch_path, structured_patch)
    write_patch_plan(patch_path, summary)
    write_report(report_path, summary, ledger_path, patch_path, structured_patch_path)
    skill_path = Path(args.skill_path).expanduser().resolve()
    write_history_and_state(
        out_dir,
        summary,
        structured_patch,
        skill_path=skill_path,
        report_path=report_path,
        patch_path=patch_path,
        structured_patch_path=structured_patch_path,
    )
    rejected_buffer_written = None
    if args.update_rejected_buffer:
        rejected_buffer_written = update_rejected_buffer(memory_root, structured_patch)
    profile_path = None
    if args.apply_profile:
        profile_path = apply_profile_guidance(memory_root, summary, report_path, patch_path)

    print(f"Wrote signal ledger: {ledger_path}")
    print(f"Wrote summary: {summary_path}")
    print(f"Wrote report: {report_path}")
    print(f"Wrote patch plan: {patch_path}")
    print(f"Wrote structured patch: {structured_patch_path}")
    print(f"Wrote runtime state: {out_dir / 'runtime_state.json'}")
    print(f"Wrote best skill snapshot: {out_dir / 'best_skill.md'}")
    if profile_path:
        print(f"Updated local strategy profile: {profile_path}")
    if rejected_buffer_written:
        print(f"Updated rejected edit buffer: {rejected_buffer_written}")
    print(f"Recommendations: {len(summary.get('recommendations', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
