#!/usr/bin/env python3
"""Unit tests for cc-compactor.py multi-dimensional weighted decision engine & JSONL splicer."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

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

    # ── model chain, rate limits, tail and live guards ──────────────────────

    def _chain_cfg(self, tmp: str) -> dict:
        settings = Path(tmp) / "magpie-settings.json"
        settings.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9"}}), encoding="utf-8")
        return cc.deep_merge(self.cfg, {
            "general": {"magpie_settings_path": str(settings), "state_dir": str(Path(tmp) / "state")},
            "compactors": {"surgical_hybrid": {"byok_chain": ["first-model", "second-model"]}},
        })

    def test_default_chain_has_no_glm_and_starts_on_haiku(self) -> None:
        chain = cc.DEFAULT_CONFIG["compactors"]["surgical_hybrid"]["byok_chain"]
        self.assertEqual(chain[0], "claude-haiku-5-5")
        self.assertFalse([m for m in chain if "glm" in m.lower()], chain)

    def test_byok_chain_falls_through_to_next_model_then_to_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_API_KEY"):
                os.environ.pop(k, None)
            cfg = self._chain_cfg(tmp)
            asked: list[str] = []
            good = json.dumps({"content": [{"type": "text", "text": "S" * 200}]}).encode()

            def first_fails(req, timeout=None):
                model = json.loads(req.data)["model"]
                asked.append(model)
                if model == "first-model":
                    raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
                return io.BytesIO(good)

            tried: list[str] = []
            with mock.patch.object(cc.urllib.request, "urlopen", side_effect=first_fails):
                text, source = cc.distill_with_byok_llm("digest", {"conversation_records": []}, cfg, tried)
            self.assertEqual(asked, ["first-model", "second-model"])
            self.assertEqual(source, "byok:second-model")
            self.assertEqual(text, "S" * 200)
            self.assertEqual(tried, ["first-model: HTTP 429"])

            tried = []
            with mock.patch.object(cc.urllib.request, "urlopen", side_effect=TimeoutError()):
                text, source = cc.distill_with_byok_llm("digest", {"conversation_records": []}, cfg, tried)
            self.assertIsNone(text)
            self.assertEqual(source, "deterministic_fallback")
            self.assertEqual(tried, ["first-model: TimeoutError", "second-model: TimeoutError"])

    def test_rate_limit_cooldown_and_hourly_cap_and_force_still_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = cc.deep_merge(self.cfg, {
                "general": {"state_dir": str(Path(tmp) / "state")},
                "limits": {"min_compaction_cooldown_sec": 180, "max_compactions_per_hour": 3},
            })
            self.assertEqual(cc.check_and_record_rate_limit(cfg), (True, "ok"))
            ok, why = cc.check_and_record_rate_limit(cfg)
            self.assertFalse(ok, "second compaction inside the cooldown was allowed")
            self.assertTrue(why.startswith("cooldown_active"), why)

            rate = Path(tmp) / "state" / "rate_guard.json"
            now = time.time()
            rate.write_text(json.dumps({"timestamps": [now - 3000, now - 2000, now - 1000]}), encoding="utf-8")
            ok, why = cc.check_and_record_rate_limit(cfg)
            self.assertFalse(ok, "a 4th compaction in the hour was allowed")
            self.assertTrue(why.startswith("hourly_cap_reached"), why)

            ok, _ = cc.check_and_record_rate_limit(cfg, force=True)
            self.assertTrue(ok)
            self.assertEqual(len(json.loads(rate.read_text())["timestamps"]), 4)

    def test_preserved_tail_never_starts_on_a_tool_result(self) -> None:
        recs = [
            {"uuid": "u0", "message": {"role": "user", "content": "task"}},
            {"uuid": "a1", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}},
            {"uuid": "u1", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
            {"uuid": "a2", "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}},
        ]
        tail = cc.select_safe_tail_records(recs, 2)
        self.assertEqual([r["uuid"] for r in tail], ["a1", "u1", "a2"])

    def test_compact_refuses_a_live_transcript_unless_allowed(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_API_KEY")}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=True):
            p = Path(tmp) / "live-session.jsonl"
            write_synthetic_jsonl(p)
            cfg_path = Path(tmp) / "cfg.toml"
            cfg_path.write_text(f'[general]\nstate_dir = "{Path(tmp) / "state"}"\nmagpie_settings_path = "{Path(tmp) / "none.json"}"\n', encoding="utf-8")
            before = p.read_text(encoding="utf-8")
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                cc.main(["--config", str(cfg_path), "--session", str(p), "compact", "--deterministic-only"])
            self.assertEqual(json.loads(out.getvalue()).get("status"), "skipped", "a live transcript was spliced")
            self.assertEqual(json.loads(out.getvalue()).get("reason"), "session_live")
            self.assertEqual(p.read_text(encoding="utf-8"), before)

            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                cc.main(["--config", str(cfg_path), "--session", str(p), "compact", "--deterministic-only", "--allow-live"])
            self.assertEqual(json.loads(out.getvalue())["status"], "compacted")
            self.assertIn('"subtype": "compact_boundary"', p.read_text(encoding="utf-8"))

            old = time.time() - 3600
            os.utime(p, (old, old))
            self.assertFalse(cc.session_is_live(p, cc.load_config(str(cfg_path))))


if __name__ == "__main__":
    unittest.main()
