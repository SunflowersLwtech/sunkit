from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_harness.core import utc_now, write_json
from agent_harness.policy import operator_topic_policy, policy_format

LATEST_RUN_PATH = Path("runtime/latest_run.txt")


def _stable_hash(*parts: str) -> str:
    joined = "\n".join(part.strip() for part in parts if part and part.strip())
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _bounded_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def is_operator_topic(candidate: dict[str, Any]) -> bool:
    policy = operator_topic_policy()
    mode = policy.get("input_mode", "operator_topic")
    source = policy.get("selection_source", "operator_topic")
    return candidate.get("input_mode") == mode or candidate.get("selection_source") == source


def topic_candidate(
    *,
    topic: str,
    summary: str | None = None,
    url: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    policy = operator_topic_policy()
    mode = policy.get("input_mode", "operator_topic")
    selection_source = policy.get("selection_source", "operator_topic")
    source_id = policy.get("source_id", "operator_topic")
    manual_url_scheme = policy.get("manual_url_scheme", "manual-topic://")
    topic_text = _bounded_text(topic, 160)
    if not topic_text:
        raise ValueError("operator topic cannot be empty")

    summary_template = policy.get("summary_template", "Operator-specified topic for searchpo analysis: {topic}")
    summary_text = _bounded_text(summary, 900) if summary else policy_format(summary_template, topic=topic_text)
    external_url = (url or "").strip()
    digest = _stable_hash(topic_text, summary_text, external_url)
    candidate_id = f"topic_{digest[:12]}"
    boundary_uri = external_url or f"{manual_url_scheme}{candidate_id}"
    collected_at = utc_now()
    evidence_source = source or source_id
    source_ids = [evidence_source] if external_url and evidence_source else [source_id]
    reliability = policy.get("reliability", {})
    evidence = [
        {
            "source": evidence_source,
            "url": boundary_uri,
            "reliability": reliability.get("with_url", 0.7) if external_url else reliability.get("without_url", 0.45),
            "claim_role": "operator_seed" if not external_url else "operator_source",
        }
    ]
    return {
        "candidate_id": candidate_id,
        "input_mode": mode,
        "selection_source": selection_source,
        "entity_type": "topic",
        "entity_key": f"topic:{digest[:16]}",
        "canonical_url": boundary_uri,
        "title": topic_text,
        "summary": summary_text,
        "published_at": None,
        "collected_at": collected_at,
        "source_ids": source_ids,
        "evidence": evidence,
        "metrics": {"operator_topic": "1"},
        "signals": {
            "freshness_hours": None,
            "has_demo_keyword": False,
            "has_code_signal": False,
            "has_buyer_keyword": False,
            "has_pain_keyword": False,
            "ad_language_density": 0.0,
            "source_count": 1,
            "metric_strength": 0.0,
            mode: True,
        },
        "risk_flags": [policy.get("risk_flag_without_url", "operator_topic_requires_source_review")] if not external_url else [],
        "candidate_score": float(policy.get("default_score", 8.0)),
    }


def create_run_dir(root_dir: Path, *, prefix: str, seed: str) -> Path:
    now = datetime.now(timezone.utc)
    date_dir = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    digest = _stable_hash(seed, now.isoformat())[:8]
    run_dir = root_dir / "runtime" / "artifacts" / date_dir / f"{prefix}-{timestamp}-{digest}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def write_latest_run(root_dir: Path, run_dir: Path) -> None:
    latest_path = root_dir / LATEST_RUN_PATH
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(str(run_dir) + "\n", encoding="utf-8")


def write_operator_topic_run(
    root_dir: Path,
    *,
    topic: str,
    summary: str | None = None,
    url: str | None = None,
    source: str | None = None,
    run_dir: Path | None = None,
) -> Path:
    candidate = topic_candidate(topic=topic, summary=summary, url=url, source=source)
    target_run_dir = run_dir or create_run_dir(root_dir, prefix="topic", seed=candidate["candidate_id"])
    target_run_dir.mkdir(parents=True, exist_ok=True)
    request = {
        "schema_version": 1,
        "created_at": utc_now(),
        "input_mode": candidate["input_mode"],
        "topic": candidate["title"],
        "summary": candidate["summary"],
        "url": (url or "").strip() or None,
        "source": source or candidate["selection_source"],
        "candidate_id": candidate["candidate_id"],
        "run_dir": str(target_run_dir),
    }
    write_json(target_run_dir / "subject_request.json", request)
    write_json(
        target_run_dir / "candidate_shortlist.json",
        {
            "schema_version": 2,
            "created_at": utc_now(),
            "run_dir": str(target_run_dir),
            "input_mode": candidate["input_mode"],
            "selection_strategy": "operator_supplied",
            "items": [candidate],
        },
    )
    write_latest_run(root_dir, target_run_dir)
    return target_run_dir


def ensure_subject_pool(run_dir: Path) -> None:
    shortlist_path = run_dir / "candidate_shortlist.json"
    if shortlist_path.exists():
        return
    request_path = run_dir / "subject_request.json"
    if not request_path.exists():
        return

    import json

    request = json.loads(request_path.read_text(encoding="utf-8"))
    policy = operator_topic_policy()
    if request.get("input_mode") != policy.get("input_mode", "operator_topic"):
        return
    candidate = topic_candidate(
        topic=request.get("topic") or "",
        summary=request.get("summary"),
        url=request.get("url"),
        source=request.get("source") or policy.get("source_id", "operator_topic"),
    )
    write_json(
        shortlist_path,
        {
            "schema_version": 2,
            "created_at": utc_now(),
            "run_dir": str(run_dir),
            "input_mode": candidate["input_mode"],
            "selection_strategy": "operator_supplied",
            "items": [candidate],
        },
    )
