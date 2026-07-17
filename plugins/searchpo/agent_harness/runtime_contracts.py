from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent_harness.core import utc_now, write_json
from agent_harness.side_effect_tiers import side_effect_axes


MAIN_AGENT = "searchpo-main-agent"
RESEARCH_AGENT = "searchpo-research-agent"
IMPL_AGENT = "searchpo-impl-agent"
HARNESS_ACTOR = "searchpo-harness"
DELEGATION_PROOF_ARTIFACT = "agent_run.json#delegation"
DELEGATION_MODES = ("single_harness", "manual_fallback", "spawned_subagents")

LEGACY_OWNER_MAP = {
    "claude_main_agent": MAIN_AGENT,
    "claude_impl_agent": IMPL_AGENT,
    "harness": HARNESS_ACTOR,
}

RUNTIME_CONTRACT_FILENAME = "runtime_contract.json"
RESEARCH_BARRIER_FILENAME = "research_barrier.json"
IMPLEMENTATION_LOOP_FILENAME = "implementation_loop.json"
RELEASE_GATE_FILENAME = "release_gate.json"

CONTRACT_RESEARCH_ARTIFACTS = {
    "evidence_bundle": "evidence_bundle.json",
    "widesearch_strategy": "widesearch_strategy.json",
    "anysearch_research": "anysearch_research.json",
    "source_map": "source_map.json",
    "fact_bank": "fact_bank.json",
    "topic_brief": "topic_brief.json",
    "research_brief": "research_brief.json",
    "cross_check_review": "cross_check_review.json",
}

PROVIDER_ARTIFACTS = {
    "script": "script.json",
    "scene_plan": "scene_plan.json",
    "video_spec": "video_spec.json",
    "render_payload": "render_payload.json",
    "content_optimization_loop": "content_optimization_loop.json",
    "content_score": "content_score.json",
    "voiceover_manifest": "voiceover_manifest.json",
    "captions": "captions.json",
}

FINAL_TRUTH_ARTIFACTS = {
    "artifact_manifest": "artifact_manifest.json",
    "delivery_package": "delivery_package.json",
    "run_final": "run_final.json",
    "video_optimization_loop": "video_optimization_loop.json",
    "douyin_upload_check": "post/douyin_upload_check.json",
}


def canonical_owner(owner: str) -> str:
    return LEGACY_OWNER_MAP.get(owner, owner)


def _is_operator_topic(candidate: dict[str, Any]) -> bool:
    return (
        str(candidate.get("input_mode") or "") == "operator_topic"
        or str(candidate.get("selection_source") or "") == "operator_topic"
        or str(candidate.get("canonical_url") or "").startswith("manual-topic://")
    )


def _has_external_url(candidate: dict[str, Any]) -> bool:
    return str(candidate.get("canonical_url") or "").startswith(("http://", "https://"))


def _task(
    task_id: str,
    *,
    owner: str,
    gate: str,
    contract: str,
    after: tuple[str, ...] = (),
    returns: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": task_id,
        "owner": owner,
        "gate": gate,
        "contract": contract,
        "start_after": list(after),
        "returns": list(returns),
    }


def _ordered_tasks(candidate: dict[str, Any], include_providers: bool) -> list[dict[str, Any]]:
    operator_topic = _is_operator_topic(candidate)
    seed_only_topic = operator_topic and not _has_external_url(candidate)
    first_task = _task(
        "resolve_operator_topic" if operator_topic else "select_candidate",
        owner=MAIN_AGENT,
        gate="operator_topic_recorded" if operator_topic else "candidate_has_url",
        contract="Intent intake becomes one run-scoped objective and side-effect tier.",
        returns=("subject_request.json",) if operator_topic else ("selected_candidate.json",),
    )
    subject_task = _task(
        "subject_detail_fetch",
        owner=RESEARCH_AGENT,
        gate="subject_seed_recorded" if seed_only_topic else "subject_detail_fetched",
        contract="Research owns source discovery and evidence sufficiency only.",
        after=(first_task["id"],),
        returns=("evidence_bundle.json", "cross_check_review.json"),
    )
    shared = [
        first_task,
        subject_task,
        _task(
            "research_enrichment",
            owner=RESEARCH_AGENT,
            gate="research_enrichment_passed",
            contract="AnySearch supplements, FactBank, TopicBrief, and source map prove the evidence pack.",
            after=("subject_detail_fetch",),
            returns=tuple(CONTRACT_RESEARCH_ARTIFACTS.values()),
        ),
        _task(
            "research_barrier",
            owner=MAIN_AGENT,
            gate="research_barrier",
            contract="Main decides from run artifacts whether implementation may start.",
            after=("research_enrichment",),
            returns=(RESEARCH_BARRIER_FILENAME,),
        ),
        _task(
            "content_plan",
            owner=MAIN_AGENT,
            gate="planning_contract_written",
            contract="Main defines angle, evidence bar, content depth, video ambition, release gates, and recovery.",
            after=("research_barrier",),
            returns=("content_plan.json", RUNTIME_CONTRACT_FILENAME, "main_task_plan.json"),
        ),
    ]
    if not include_providers:
        return [
            *shared,
            _task(
                "publish_package",
                owner=IMPL_AGENT,
                gate="claims_ledger_coverage",
                contract="Implementation writes a text-only Douyin package after research is sufficient.",
                after=("content_plan",),
                returns=("post/claims_ledger.json", "post/douyin_distribution_review.json"),
            ),
            _task(
                "content_preflight",
                owner=MAIN_AGENT,
                gate="content_preflight_gate",
                contract="Main verifies text release safety from artifacts and gates.",
                after=("publish_package",),
                returns=("content_preflight_review.json",),
            ),
        ]
    return [
        *shared,
        _task(
            "content_improvement_loop",
            owner=IMPL_AGENT,
            gate="content_improvement_loop",
            contract="Implementation runs provider content generation until the content target passes or fails explicitly.",
            after=("content_plan",),
            returns=("content_optimization_loop.json", "deepseek_polish.json", "content_score.json", "script.json", "scene_plan.json"),
        ),
        _task(
            "gemini_tts",
            owner=IMPL_AGENT,
            gate="voiceover_generated",
            contract="Implementation must return real provider audio, not silent or mock media.",
            after=("content_improvement_loop",),
            returns=("voiceover.wav", "voiceover_manifest.json"),
        ),
        _task(
            "build_captions",
            owner=IMPL_AGENT,
            gate="captions_built",
            contract="Captions are derived from real audio timing.",
            after=("gemini_tts",),
            returns=("captions.json", "caption_audit.json"),
        ),
        _task(
            "render_payload",
            owner=IMPL_AGENT,
            gate="render_payload_written",
            contract="Implementation converts the approved script and scene plan into renderer-neutral media contracts.",
            after=("build_captions",),
            returns=("video_spec.json", "render_payload.json"),
        ),
        _task(
            "quality_gate",
            owner=MAIN_AGENT,
            gate="quality_gate_passed",
            contract="Main verifies evidence, audio, captions, and copy before publish packaging.",
            after=("render_payload",),
            returns=("quality_gate.json",),
        ),
        _task(
            "publish_package",
            owner=IMPL_AGENT,
            gate="claims_ledger_coverage",
            contract="Implementation prepares delivery evidence without deciding release.",
            after=("quality_gate",),
            returns=("post/claims_ledger.json", "post/douyin_distribution_review.json"),
        ),
        _task(
            "content_preflight",
            owner=MAIN_AGENT,
            gate="content_preflight_gate",
            contract="Main verifies generated text and claims before render side effects continue.",
            after=("publish_package",),
            returns=("content_preflight_review.json",),
        ),
        _task(
            "video_quality_loop",
            owner=IMPL_AGENT,
            gate="video_quality_loop",
            contract="Implementation renders, audits, repairs, and rerenders until media is verified or fails.",
            after=("content_preflight",),
            returns=("video_optimization_loop.json", "artifact_manifest.json"),
        ),
        _task(
            "douyin_publish",
            owner=IMPL_AGENT,
            gate="douyin_contract_or_live_gate",
            contract="Implementation returns adapter or live publish evidence; submitted alone is not final truth.",
            after=("video_quality_loop",),
            returns=("post/douyin_upload_check.json", "post/post_publish_verification.json"),
        ),
        _task(
            "final_verification",
            owner=MAIN_AGENT,
            gate="artifact_release_gate",
            contract="Main makes the release or no-release decision from run artifacts.",
            after=("douyin_publish",),
            returns=(RELEASE_GATE_FILENAME, "delivery_package.json", "run_final.json"),
        ),
    ]


def build_main_task_plan(
    candidate: dict[str, Any],
    include_providers: bool,
    *,
    axes: dict[str, str] | None = None,
    content_plan: dict[str, Any] | None = None,
    delegation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    axes = axes or side_effect_axes("provider" if include_providers else "contract")
    delegation = delegation or {}
    delegation_mode = str(delegation.get("mode") or "single_harness")
    ordered_tasks = _ordered_tasks(candidate, include_providers)
    objective_title = str(candidate.get("title") or candidate.get("candidate_id") or "Searchpo topic").strip()
    content_plan = content_plan or {}
    return {
        "schema_version": 2,
        "architecture": "searchpo_ideal_agent_runtime",
        "created_at": utc_now(),
        "owner": MAIN_AGENT,
        "selected_candidate_id": candidate.get("candidate_id"),
        "subject_input_mode": candidate.get("input_mode") or "shortlist",
        "subject_selection_source": candidate.get("selection_source") or "candidate_shortlist",
        "task_plan_state": "planned",
        "provider_mode": "provider" if include_providers else "contract",
        "delegation_mode": delegation_mode,
        **axes,
        "intent_intake": {
            "objective": f"Produce a source-bounded Searchpo release package for {objective_title}.",
            "topic_angle": content_plan.get("angle") or "problem -> mechanism -> tradeoff -> verification path",
            "canonical_url": candidate.get("canonical_url"),
            "side_effect_tier": axes.get("side_effect_tier"),
            "success_bar": [
                "research barrier passes from artifacts",
                "implementation starts only after evidence sufficiency",
                "release truth is written only from media, audit, and publish artifacts",
            ],
        },
        "runtime_contracts": {
            "planning_contract": {
                "owner": MAIN_AGENT,
                "must_define": [
                    "topic angle",
                    "evidence bar",
                    "content depth",
                    "video ambition",
                    "release gates",
                    "recovery path",
                ],
                "copy_may_start_after": [RESEARCH_BARRIER_FILENAME],
                "media_may_start_after": ["content_score.json", "voiceover_manifest.json", "captions.json"],
                "publish_may_start_after": ["artifact_manifest.json", "visual audits", "douyin upload identity"],
            },
            "delegation_contract": {
                "sequential": True,
                "mode": delegation_mode,
                "allowed_modes": list(DELEGATION_MODES),
                "main_agent_boundary": "task plan, barriers, verification, release decision",
                "research_agent_boundary": "source discovery, evidence sufficiency, FactBank, TopicBrief, cross-check",
                "implementation_agent_boundary": "providers, Remotion, audits, artifact binding, publish checks",
                "parallel_research_and_implementation_allowed": False,
                "owner_labels_are_execution_proof": False,
                "execution_proof_artifact": DELEGATION_PROOF_ARTIFACT,
                "spawned_subagents_require_host_proof": True,
                "phase_runtime": {
                    "research_phase": "python3 agent_harness/run_agent_loop.py --mode provider --stop-after research_enrichment",
                    "main_barrier_phase": "python3 agent_harness/run_agent_loop.py <run_dir> --mode provider --resume-from 4 --stop-after main_task_plan",
                    "implementation_phase": "python3 agent_harness/run_agent_loop.py <run_dir> --mode provider --resume-from 5",
                },
            },
            "verification_contract": {
                "verdict_source": "run-scoped artifacts and board gates, not agent claims",
                "research_barrier_artifact": RESEARCH_BARRIER_FILENAME,
                "release_gate_artifact": RELEASE_GATE_FILENAME,
                "contract_required_artifacts": CONTRACT_RESEARCH_ARTIFACTS,
                "provider_required_artifacts": PROVIDER_ARTIFACTS,
                "final_truth_artifacts": FINAL_TRUTH_ARTIFACTS,
            },
            "recovery_contract": {
                "failure_artifact": "failure.json",
                "resume_command": "python3 agent_harness/run_agent_loop.py --mode provider --resume-from N",
                "targeted_followups": {
                    "research_barrier": "add source discovery/extract evidence; do not start implementation",
                    "content_improvement_loop": "feed evaluator feedback into DeepSeek revision",
                    "video_quality_loop": "repair storyboard/captions/cover or backtrack once to content",
                    "publish_release_gate": "fix adapter/live identity evidence; do not mark submitted as success",
                },
            },
        },
        "roles": {
            MAIN_AGENT: [
                "owns task-plan state",
                "decides research and release gates",
                "verifies from artifacts",
            ],
            RESEARCH_AGENT: [
                "owns canonical and supplemental evidence discovery",
                "writes fact_bank.json, topic_brief.json, source_map.json, and cross-check artifacts",
                "does not write copy, media, or release decisions",
            ],
            IMPL_AGENT: [
                "runs provider, TTS, Remotion, audit, and publish-check commands",
                "returns artifacts and gate status",
                "does not decide release",
            ],
        },
        "runtime_memory": {
            "task_board": "harness_board.sqlite3",
            "resumable_state": "harness_state.json",
            "evidence_pack": "evidence_bundle.json",
            "media_identity": "artifact_manifest.json",
            "final_truth": "run_final.json",
        },
        "ordered_tasks": ordered_tasks,
        "no_silent_fallbacks": [
            "no mock provider output",
            "no silent media",
            "no skipped visual checks",
            "no publish fallback truth",
            "no implementation before evidence sufficiency",
        ],
    }


def write_runtime_contract(
    run_dir: Path,
    candidate: dict[str, Any],
    include_providers: bool,
    *,
    axes: dict[str, str] | None = None,
    content_plan: dict[str, Any] | None = None,
    delegation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = build_main_task_plan(candidate, include_providers, axes=axes, content_plan=content_plan, delegation=delegation)
    write_json(run_dir / RUNTIME_CONTRACT_FILENAME, contract)
    return contract


def _maybe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _artifact_checks(run_dir: Path, artifact_map: dict[str, str]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for name, rel_path in artifact_map.items():
        path = run_dir / rel_path
        checks[name] = {"path": str(path), "exists": path.is_file()}
    return checks


def build_research_barrier(
    run_dir: Path,
    cross_check_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    review = cross_check_review or _maybe_read_json(run_dir / "cross_check_review.json")
    artifact_checks = _artifact_checks(run_dir, CONTRACT_RESEARCH_ARTIFACTS)
    raw_dir = run_dir / "research" / "anysearch_raw"
    raw_outputs = sorted(str(path) for path in raw_dir.glob("*.txt")) if raw_dir.exists() else []
    errors: list[str] = []
    if review.get("status") != "pass":
        errors.append(f"cross_check_review.status is {review.get('status') or 'missing'}")
    if review.get("research_sufficient") is not True:
        errors.append("cross_check_review.research_sufficient is not true")
    missing = [name for name, check in artifact_checks.items() if not check["exists"]]
    if missing:
        errors.append("missing research artifacts: " + ", ".join(missing))
    if not raw_outputs:
        errors.append("research/anysearch_raw has no captured search/extract output")
    anysearch = _maybe_read_json(run_dir / "anysearch_research.json")
    if not anysearch.get("commands"):
        errors.append("anysearch_research.commands is empty")
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "owner": MAIN_AGENT,
        "status": "pass" if not errors else "fail",
        "decision": "implementation_allowed" if not errors else "return_to_research",
        "research_agent": RESEARCH_AGENT,
        "implementation_agent": IMPL_AGENT,
        "cross_check_status": review.get("status") or "missing",
        "research_sufficient": review.get("research_sufficient") is True,
        "supplemental_source_count": int(review.get("supplemental_source_count") or 0),
        "independent_source_hosts": review.get("independent_source_hosts") or [],
        "fact_bank_status": review.get("fact_bank_status") or "missing",
        "artifact_checks": artifact_checks,
        "anysearch_raw_outputs": raw_outputs,
        "errors": errors,
    }


def write_research_barrier(
    run_dir: Path,
    cross_check_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    barrier = build_research_barrier(run_dir, cross_check_review)
    write_json(run_dir / RESEARCH_BARRIER_FILENAME, barrier)
    return barrier


def write_implementation_loop(
    run_dir: Path,
    *,
    phase: str,
    status: str,
    owner: str = IMPL_AGENT,
    artifacts: dict[str, str] | None = None,
    gates: dict[str, str] | None = None,
    errors: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = run_dir / IMPLEMENTATION_LOOP_FILENAME
    existing = _maybe_read_json(path)
    phases = [phase_record for phase_record in existing.get("phases") or [] if phase_record.get("phase") != phase]
    normalized_status = "pass" if status == "completed" else ("fail" if status == "failed" else status)
    phases.append(
        {
            "phase": phase,
            "owner": canonical_owner(owner),
            "status": normalized_status,
            "recorded_at": utc_now(),
            "artifacts": artifacts or {},
            "gates": gates or {},
            "errors": errors or [],
            "metadata": metadata or {},
        }
    )
    rollup = "fail" if any(record.get("status") == "fail" for record in phases) else "pass"
    payload = {
        "schema_version": 1,
        "created_at": existing.get("created_at") or utc_now(),
        "updated_at": utc_now(),
        "owner": IMPL_AGENT,
        "status": rollup,
        "contract": "Implementation returns artifacts and gate status; main agent owns release decisions.",
        "phases": phases,
    }
    write_json(path, payload)
    return payload


def write_release_gate(
    run_dir: Path,
    *,
    status: str,
    publish_status: str,
    artifact_status: str,
    production_success: bool,
    axes: dict[str, str],
    errors: list[str],
    artifact_manifest: dict[str, Any],
    upload_check: dict[str, Any],
    post_publish_verification: dict[str, Any],
) -> dict[str, Any]:
    artifact_manifest_path = run_dir / "artifact_manifest.json"
    artifact_manifest_sha256 = hashlib.sha256(artifact_manifest_path.read_bytes()).hexdigest() if artifact_manifest_path.exists() else None
    payload = {
        "schema_version": 1,
        "created_at": utc_now(),
        "owner": MAIN_AGENT,
        "status": status,
        "decision": "release" if status == "pass" else "no_release",
        **axes,
        "artifact_status": artifact_status,
        "publish_status": publish_status,
        "production_success": production_success,
        "artifact_manifest_path": str(artifact_manifest_path),
        "douyin_upload_check_path": str(run_dir / "post" / "douyin_upload_check.json"),
        "post_publish_verification_path": str(run_dir / "post" / "post_publish_verification.json"),
        "artifact_manifest_sha256": artifact_manifest_sha256,
        "publish_hash": artifact_manifest.get("publish_hash"),
        "upload_check_status": upload_check.get("status") or "missing",
        "post_publish_verification_status": post_publish_verification.get("status") or "missing",
        "errors": errors,
    }
    write_json(run_dir / RELEASE_GATE_FILENAME, payload)
    return payload
