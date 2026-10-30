#!/usr/bin/env python3
"""Unit tests for cc-compactor.py multi-dimensional weighted decision engine & JSONL splicer."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "cc-compactor.py"
spec = importlib.util.spec_from_file_location("cc_compactor", MODULE_PATH)
assert spec and spec.loader
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)


def write_synthetic_jsonl(path: Path, context_tokens: int = 245000, now_iso: str = "2026-10-30T10:15:00Z") -> None:
    lines = [
        {
            "parentUuid": None,
            "isSidechain": False,
            "type": "user",
            "uuid": "uuid-user-1",
            "timestamp": "2026-10-30T09:50:00Z",
            "sessionId": "test-session-001",
            "cwd": "/tmp/demo-repo",
            "version": "2.1.310",
            "gitBranch": "feat/context-budget",
            "slug": "demo-slug",
            "message": {
                "role": "user",
                "content": "Build the weighted multi-seat compactor and verify the fallback window limits.",
            },
        },
        {
            "parentUuid": "uuid-user-1",
            "isSidechain": False,
            "type": "assistant",
            "uuid": "uuid-asst-1",
            "timestamp": "2026-10-30T10:10:00Z",
            "sessionId": "test-session-001",
            "cwd": "/tmp/demo-repo",
            "version": "2.1.310",
            "gitBranch": "feat/context-budget",
            "slug": "demo-slug",
            "message": {
                "role": "assistant",
                "usage": {
                    "input_tokens": 1200,
                    "cache_creation_input_tokens": 24000,
                    "cache_read_input_tokens": context_tokens - 26000,
                    "output_tokens": 800,
                },
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_edit_1",
                        "name": "Edit",
                        "input": {
                            "file_path": "/tmp/demo-repo/src/router.py",
                            "old_string": "a",
                            "new_string": "b",
                        },
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_bash_1",
                        "name": "Bash",
                        "input": {"command": "pytest tests/test_router.py -q"},
                    },
                ],
            },
        },
        {
            "parentUuid": "uuid-asst-1",
            "isSidechain": False,
            "type": "user",
            "uuid": "uuid-user-2",
            "timestamp": now_iso,
            "sessionId": "test-session-001",
            "cwd": "/tmp/demo-repo",
            "version": "2.1.310",
            "gitBranch": "feat/context-budget",
            "slug": "demo-slug",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_edit_1",
                        "content": "Updated /tmp/demo-repo/src/router.py successfully.",
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_bash_1",
                        "is_error": True,
                        "content": "output log\n" * 1800
                        + "\nAssertionError: expected window <= 200000 in tests/test_router.py:42",
                    },
                ],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in lines) + "\n", encoding="utf-8")


class TestCcCompactor(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = cc.load_config()

    def test_analyze_transcript_extracts_tokens_files_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test-session-001.jsonl"
            now_ts = cc.parse_iso_ts("2026-10-30T10:20:00Z")
            write_synthetic_jsonl(p, context_tokens=245000)

            state = cc.analyze_transcript(p, now_ts=now_ts)
            self.assertGreaterEqual(state["context_tokens"], 245000)
            self.assertGreater(state["r_tool"], 0.5)
            self.assertEqual(state["touched_files"].get("/tmp/demo-repo/src/router.py"), "MODIFIED")
            self.assertTrue(any("pytest tests/test_router.py" in c for c in state["commands_run"]))
            self.assertTrue(any("AssertionError" in e for e in state["errors_and_failures"]))
            self.assertIn("Bash", state["discovered_tools"])
            self.assertIn("Edit", state["discovered_tools"])

    def test_5d_engine_selects_byok_jsonl_splice_when_claude_seats_exhausted_and_245k_overflows_zcode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test-session-001.jsonl"
            now_ts = cc.parse_iso_ts("2026-10-30T10:20:00Z")
            write_synthetic_jsonl(p, context_tokens=245000)
            t_state = cc.analyze_transcript(p, now_ts=now_ts)

            # All Claude seats at 99-100% (just like live llm-gateway under heavy load)
            mock_quotas = {
                "data": [
                    {
                        "provider": "claude",
                        "plan": "team",
                        "user": "weiliu@duocodetech.com",
                        "lastServedAt": "2026-10-30T10:18:00Z",
                        "windows": [
                            {"name": "5 hours", "used": 100, "remaining": 0, "resetsAt": "2026-10-30T11:30:00Z"},
                            {"name": "7 days", "used": 62, "remaining": 38, "resetsAt": "2026-11-04T00:00:00Z"},
                        ],
                    }
                ]
            }
            q_state = cc.fetch_magpie_quotas(self.cfg, now_ts=now_ts, mock_payload=mock_quotas)
            self.assertEqual(q_state["healthy_claude_seat_count"], 0)

            decision = cc.evaluate_actions(t_state, q_state, self.cfg, profile_name="balanced")
            self.assertTrue(decision["overflows_zcode_200k"])
            self.assertEqual(decision["recommended_action"], "BYOK_JSONL_SPLICE")

    def test_5d_engine_selects_stay_noop_when_seat_healthy_and_context_small(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test-session-002.jsonl"
            now_ts = cc.parse_iso_ts("2026-10-30T10:20:00Z")
            write_synthetic_jsonl(p, context_tokens=52000)
            t_state = cc.analyze_transcript(p, now_ts=now_ts)

            mock_quotas = {
                "data": [
                    {
                        "provider": "claude",
                        "plan": "team",
                        "user": "duocodetechu@gmail.com",
                        "lastServedAt": "2026-10-30T10:19:00Z",
                        "windows": [
                            {"name": "5 hours", "used": 32, "remaining": 68, "resetsAt": "2026-10-30T13:30:00Z"},
                            {"name": "7 days", "used": 40, "remaining": 60, "resetsAt": "2026-11-04T00:00:00Z"},
                        ],
                    }
                ]
            }
            q_state = cc.fetch_magpie_quotas(self.cfg, now_ts=now_ts, mock_payload=mock_quotas)
            decision = cc.evaluate_actions(t_state, q_state, self.cfg, profile_name="balanced")
            self.assertEqual(decision["recommended_action"], "STAY_NOOP")

    def test_splice_compact_boundary_writes_valid_claude_code_v2_schema_and_resets_active_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test-session-003.jsonl"
            now_ts = cc.parse_iso_ts("2026-10-30T10:20:00Z")
            write_synthetic_jsonl(p, context_tokens=245000)

            cfg = cc.deep_merge(self.cfg, {"general": {"state_dir": str(Path(tmp) / "state")}})
            t_state_before = cc.analyze_transcript(p, now_ts=now_ts)
            digest = cc.build_deterministic_digest(t_state_before, {"status_short": "M src/router.py", "diff_stat": ""})

            res = cc.splice_compact_boundary(
                jsonl_path=p,
                transcript_state=t_state_before,
                summary_markdown=digest,
                compactor_source="deterministic_test",
                cfg=cfg,
                duration_ms=120,
            )

            self.assertTrue(Path(res["backup_path"]).is_file())
            self.assertLess(res["post_tokens"], 20000)

            # Re-analyze transcript after splice: active segment now starts AFTER compact_boundary!
            t_state_after = cc.analyze_transcript(p, now_ts=now_ts)
            self.assertGreaterEqual(t_state_after["last_boundary_idx"], 0)
            self.assertEqual(t_state_after["active_records_count"], 1)
            self.assertLess(t_state_after["context_tokens"], 5000)


if __name__ == "__main__":
    unittest.main()
