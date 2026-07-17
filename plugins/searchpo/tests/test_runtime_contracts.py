from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_harness.core import HarnessContext, StageResult, SyncHarness, TaskBoard, write_json
from agent_harness.runtime_contracts import (
    IMPL_AGENT,
    MAIN_AGENT,
    RESEARCH_AGENT,
    build_main_task_plan,
    build_research_barrier,
)


class RuntimeContractTests(unittest.TestCase):
    def test_main_task_plan_declares_architecture_contracts(self) -> None:
        plan = build_main_task_plan(
            {
                "candidate_id": "cand-1",
                "title": "Demo Tool",
                "canonical_url": "https://example.com/demo",
            },
            include_providers=True,
        )

        self.assertEqual(plan["owner"], MAIN_AGENT)
        self.assertEqual(plan["schema_version"], 2)
        self.assertIn("planning_contract", plan["runtime_contracts"])
        self.assertIn("delegation_contract", plan["runtime_contracts"])
        self.assertIn("verification_contract", plan["runtime_contracts"])
        self.assertIn("recovery_contract", plan["runtime_contracts"])
        owners = {task["owner"] for task in plan["ordered_tasks"]}
        self.assertTrue({MAIN_AGENT, RESEARCH_AGENT, IMPL_AGENT}.issubset(owners))
        self.assertNotIn("claude_main_agent", owners)
        self.assertNotIn("claude_impl_agent", owners)
        delegation = plan["runtime_contracts"]["delegation_contract"]
        self.assertFalse(delegation["owner_labels_are_execution_proof"])
        self.assertEqual(delegation["execution_proof_artifact"], "agent_run.json#delegation")
        self.assertIn("spawned_subagents", delegation["allowed_modes"])
        self.assertIn("--stop-after research_enrichment", delegation["phase_runtime"]["research_phase"])

        manual_plan = build_main_task_plan(
            {"candidate_id": "cand-2", "title": "Manual Flow", "canonical_url": "https://example.com/manual"},
            include_providers=True,
            delegation={"mode": "manual_fallback"},
        )
        self.assertEqual(manual_plan["delegation_mode"], "manual_fallback")
        self.assertEqual(manual_plan["runtime_contracts"]["delegation_contract"]["mode"], "manual_fallback")

    def test_research_barrier_requires_artifact_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            review = {
                "status": "pass",
                "research_sufficient": True,
                "fact_bank_status": "pass",
                "supplemental_source_count": 2,
                "independent_source_hosts": ["docs.example.org", "blog.example.net"],
            }
            for filename in [
                "evidence_bundle.json",
                "widesearch_strategy.json",
                "anysearch_research.json",
                "source_map.json",
                "fact_bank.json",
                "topic_brief.json",
                "research_brief.json",
                "cross_check_review.json",
            ]:
                payload = {"status": "pass"}
                if filename == "anysearch_research.json":
                    payload["commands"] = [{"kind": "search", "query": "demo"}]
                write_json(run_dir / filename, payload)
            raw_dir = run_dir / "research" / "anysearch_raw"
            raw_dir.mkdir(parents=True)
            (raw_dir / "search_01.txt").write_text("https://docs.example.org/demo\n", encoding="utf-8")

            barrier = build_research_barrier(run_dir, review)

            self.assertEqual(barrier["status"], "pass")
            self.assertEqual(barrier["decision"], "implementation_allowed")

    def test_research_barrier_blocks_missing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            barrier = build_research_barrier(
                Path(tmp),
                {"status": "pass", "research_sufficient": True, "commands": [{"kind": "search"}]},
            )

            self.assertEqual(barrier["status"], "fail")
            self.assertEqual(barrier["decision"], "return_to_research")
            self.assertTrue(any("missing research artifacts" in error for error in barrier["errors"]))

    def test_sync_harness_stop_after_reuses_root_task_on_resume(self) -> None:
        class DummyStage:
            def __init__(self, name: str) -> None:
                self.name = name
                self.title = name
                self.owner = MAIN_AGENT

            def run(self, context: HarnessContext) -> StageResult:
                return StageResult(step=self.name, status="completed", details=f"{self.name} done")

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            board = TaskBoard(run_dir / "harness_board.sqlite3")
            try:
                stages = [DummyStage("research_enrichment"), DummyStage("main_task_plan")]
                first = SyncHarness(stages).run(HarnessContext(Path(tmp), run_dir, board), stop_after="research_enrichment")
                state = json.loads((run_dir / "harness_state.json").read_text(encoding="utf-8"))
                self.assertEqual(state["root_task_id"], first.root_task_id)
                self.assertEqual(state["completed_stages"], ["research_enrichment"])

                second = SyncHarness(stages).run(HarnessContext(Path(tmp), run_dir, board), resume_from=1)
                self.assertEqual(second.root_task_id, first.root_task_id)
                snapshot = board.snapshot(first.root_task_id)
                child_kinds = [task["kind"] for task in snapshot["tasks"] if task["parent_id"] == first.root_task_id]
                self.assertEqual(child_kinds, ["research_enrichment", "main_task_plan"])
            finally:
                board.close()


if __name__ == "__main__":
    unittest.main()
