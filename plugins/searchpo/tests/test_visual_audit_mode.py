from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import scripts.video_quality_loop as video_loop
from agent_harness.core import Artifact, Gate, TaskBoard, write_json
from scripts.finalize_run import main as finalize_run_main
from tests.test_static_contracts import passing_deterministic_visual_audit, passing_gemini_visual_audit


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def not_used_marker(audit_name: str, video_sha256: str) -> dict[str, Any]:
    return {
        "audit_name": audit_name,
        "provider": "gemini",
        "status": "not-used",
        "visual_audit_mode": "deterministic",
        "video_sha256": video_sha256,
    }


def build_contract_run(
    root: Path,
    *,
    gemini: dict[str, Any] | None,
    premium: dict[str, Any] | None,
    deterministic: dict[str, Any] | None = None,
) -> Path:
    run_dir = root / "run"
    post_dir = run_dir / "post"
    (run_dir / "video").mkdir(parents=True)
    (run_dir / "cover").mkdir()
    post_dir.mkdir()
    (run_dir / "video" / "final.mp4").write_bytes(b"final-video")
    (run_dir / "cover" / "final.jpg").write_bytes(b"cover")
    write_json(
        run_dir / "artifact_manifest.json",
        {
            "execution_profile": "provider",
            "render_mode": "local",
            "publish_mode": "contract-check",
            "selected_candidate_id": "cand-1",
            "final_video_path": str(run_dir / "video" / "final.mp4"),
            "cover_path": str(run_dir / "cover" / "final.jpg"),
        },
    )
    write_json(run_dir / "render_metadata_check.json", {"status": "pass"})
    write_json(run_dir / "visual_audit_deterministic.json", deterministic or passing_deterministic_visual_audit())
    if gemini is not None:
        write_json(run_dir / "gemini_visual_audit.json", gemini)
    if premium is not None:
        write_json(run_dir / "premium_showcase_audit.json", premium)
    write_json(post_dir / "douyin_upload_check.json", {"status": "pass", "publish_mode": "contract-check"})
    board = TaskBoard(run_dir / "harness_board.sqlite3")
    try:
        root_task = board.create_task("root", "root", "test")
        board.set_status(root_task, "running", "test")
        task = board.create_task("douyin_publish", "publish", "test", root_task)
        board.gate(task, Gate("douyin_contract_gate", "pass", "contract only"))
        board.artifact(task, Artifact("douyin_upload_check", post_dir / "douyin_upload_check.json"))
        board.set_status(task, "completed", "test")
        write_json(run_dir / "agent_run.json", {"root_task_id": root_task})
    finally:
        board.close()
    return run_dir


def finalize(run_dir: Path, mode: str | None) -> tuple[int, dict[str, Any]]:
    env = dict(os.environ)
    env.pop("SEARCHPO_VISUAL_AUDIT", None)
    if mode is not None:
        env["SEARCHPO_VISUAL_AUDIT"] = mode
    with patch.dict(os.environ, env, clear=True), patch.object(
        sys, "argv", ["finalize_run.py", str(run_dir), "--publish-mode", "contract-check"]
    ), redirect_stdout(StringIO()):
        code = finalize_run_main()
    return code, json.loads((run_dir / "run_final.json").read_text(encoding="utf-8"))


class FinalizeVisualAuditModeTests(unittest.TestCase):
    final_sha = sha256_bytes(b"final-video")

    def test_deterministic_mode_accepts_not_used_model_audits_bound_to_the_final_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = build_contract_run(
                Path(tmp),
                gemini=not_used_marker("gemini_visual_audit", self.final_sha),
                premium=not_used_marker("premium_showcase_audit", self.final_sha),
            )
            code, final = finalize(run_dir, "deterministic")
        self.assertEqual(code, 0, final["errors"])
        self.assertEqual(final["visual_audit_mode"], "deterministic")
        self.assertEqual(final["gemini_visual_audit_status"], "not-used")
        self.assertEqual(final["premium_showcase_audit_status"], "not-used")

    def test_default_mode_rejects_not_used_model_audits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = build_contract_run(
                Path(tmp),
                gemini=not_used_marker("gemini_visual_audit", self.final_sha),
                premium=not_used_marker("premium_showcase_audit", self.final_sha),
            )
            code, final = finalize(run_dir, None)
        self.assertEqual(code, 1)
        self.assertEqual(final["visual_audit_mode"], "gemini")
        self.assertIn("Gemini visual audit status is not-used", final["errors"])
        self.assertIn("premium showcase audit status is not-used", final["errors"])

    def test_deterministic_mode_does_not_treat_a_missing_gemini_audit_as_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = build_contract_run(Path(tmp), gemini=None, premium=None)
            code, final = finalize(run_dir, "deterministic")
        self.assertEqual(code, 1)
        self.assertIn("Gemini visual audit status is missing", final["errors"])
        self.assertIn("premium showcase audit status is missing", final["errors"])

    def test_deterministic_mode_does_not_override_a_failed_gemini_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = build_contract_run(
                Path(tmp),
                gemini={**passing_gemini_visual_audit(), "status": "fail"},
                premium=not_used_marker("premium_showcase_audit", self.final_sha),
            )
            code, final = finalize(run_dir, "deterministic")
        self.assertEqual(code, 1)
        self.assertIn("Gemini visual audit status is fail", final["errors"])

    def test_not_used_record_for_another_video_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = build_contract_run(
                Path(tmp),
                gemini=not_used_marker("gemini_visual_audit", sha256_bytes(b"some-other-video")),
                premium=not_used_marker("premium_showcase_audit", self.final_sha),
            )
            code, final = finalize(run_dir, "deterministic")
        self.assertEqual(code, 1)
        self.assertTrue(any("different video" in error for error in final["errors"]), final["errors"])

    def test_not_used_record_must_come_from_the_deterministic_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hand_written = {"status": "not-used", "video_sha256": self.final_sha}
            run_dir = build_contract_run(Path(tmp), gemini=hand_written, premium=not_used_marker("premium_showcase_audit", self.final_sha))
            code, final = finalize(run_dir, "deterministic")
        self.assertEqual(code, 1)
        self.assertTrue(any("not recorded by the deterministic" in error for error in final["errors"]), final["errors"])

    def test_deterministic_mode_still_requires_the_deterministic_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            failing = {**passing_deterministic_visual_audit(), "status": "fail", "motion_check": {"status": "fail"}}
            run_dir = build_contract_run(
                Path(tmp),
                gemini=not_used_marker("gemini_visual_audit", self.final_sha),
                premium=not_used_marker("premium_showcase_audit", self.final_sha),
                deterministic=failing,
            )
            code, final = finalize(run_dir, "deterministic")
        self.assertEqual(code, 1)
        self.assertIn("deterministic visual audit status is fail", final["errors"])
        self.assertIn("deterministic central motion check did not pass", final["errors"])


class AuditAttemptModeTests(unittest.TestCase):
    def _audit(self, mode: str) -> tuple[dict[str, Any], list[str], Path]:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        run_dir = Path(tmp) / "run"
        attempt_dir = run_dir / "optimization" / "video" / "attempt-01"
        attempt_dir.mkdir(parents=True)
        video = attempt_dir / "rendered_video.mp4"
        video.write_bytes(b"attempt-video")
        scripts_run: list[str] = []

        def fake_run_command(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 900) -> dict[str, Any]:
            script = cmd[1]
            scripts_run.append(script)
            output = Path(cmd[cmd.index("--output") + 1])
            if script == "scripts/check_render_metadata.py":
                write_json(output, {"status": "pass"})
            elif script == "scripts/deterministic_visual_audit.py":
                write_json(output, passing_deterministic_visual_audit())
            else:
                raise RuntimeError(f"{script} unavailable in this test")
            return {"command": " ".join(cmd), "returncode": 0}

        with patch.dict(os.environ, {"SEARCHPO_VISUAL_AUDIT": mode}), patch.object(video_loop, "run_command", side_effect=fake_run_command):
            decision = video_loop.audit_attempt(run_dir, attempt_dir, 1, video)
        return decision, scripts_run, attempt_dir

    def test_deterministic_mode_never_calls_model_audits_and_records_not_used(self) -> None:
        decision, scripts_run, attempt_dir = self._audit("deterministic")
        self.assertEqual(decision["status"], "pass")
        self.assertEqual(decision["visual_audit_mode"], "deterministic")
        self.assertEqual(scripts_run, ["scripts/check_render_metadata.py", "scripts/deterministic_visual_audit.py"])
        for name in ["gemini_visual_audit.json", "premium_showcase_audit.json"]:
            record = json.loads((attempt_dir / name).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "not-used")
            self.assertNotEqual(record["status"], "pass")
            self.assertEqual(record["video_sha256"], sha256_bytes(b"attempt-video"))

    def test_gemini_mode_fails_when_the_gemini_audit_cannot_run(self) -> None:
        decision, scripts_run, attempt_dir = self._audit("gemini")
        self.assertEqual(decision["status"], "fail")
        self.assertIn("scripts/gemini_visual_audit.py", scripts_run)
        self.assertFalse((attempt_dir / "gemini_visual_audit.json").exists())


if __name__ == "__main__":
    unittest.main()
