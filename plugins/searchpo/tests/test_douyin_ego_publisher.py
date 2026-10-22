from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from agent_harness.core import Gate, TaskBoard, write_json
from scripts.finalize_run import main as finalize_run_main
from tests.test_static_contracts import passing_deterministic_visual_audit

ROOT = Path(__file__).resolve().parents[1]
REMOTE_ID = "7400000000000000001"
LONG_TITLE = "一个明显超过三十个字符的抖音标题用来检查发布脚本会不会按照平台限制截断标题内容"

STUB_PUBLISHER = r'''
import json
import os
import sys

args = sys.argv[1:]
with open(os.environ["STUB_ARGS_OUT"], "w", encoding="utf-8") as handle:
    json.dump(args, handle, ensure_ascii=False)
value = lambda flag: args[args.index(flag) + 1]
mode = os.environ.get("STUB_MODE", "ok")
print("opening the signed-in profile")
if mode == "ok":
    print(json.dumps({
        "ok": True,
        "remote_id": "%s",
        "url": "https://www.douyin.com/video/%s",
        "account": {"id": "test-account", "handle": "test-account"},
        "visibility": value("--visibility"),
        "published_at": "2026-10-22T00:00:00.000Z",
        "screenshots": value("--shots"),
    }))
elif mode == "no-id":
    print(json.dumps({"ok": True, "remote_id": "", "url": "", "visibility": value("--visibility")}))
else:
    print(json.dumps({"ok": False, "error": "signed-in profile expired", "screenshots": value("--shots")}))
    sys.exit(1)
''' % (REMOTE_ID, REMOTE_ID)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_cover(path: Path) -> None:
    from PIL import Image

    image = Image.new("RGB", (720, 1280), (20, 24, 32))
    image.paste((250, 250, 250), (0, 0, 720, 640))
    image.save(path, "JPEG")


def build_live_run(root: Path) -> Path:
    run_dir = root / "artifacts" / "run-ego"
    video = run_dir / "video" / "final.mp4"
    cover = run_dir / "cover" / "final.jpg"
    video.parent.mkdir(parents=True)
    cover.parent.mkdir(parents=True)
    (run_dir / "post").mkdir()
    video.write_bytes(b"final-video-bytes")
    write_cover(cover)
    write_json(
        run_dir / "post" / "douyin_upload_manifest.json",
        {
            "manifest_status": "artifact-bound",
            "publish_mode": "live",
            "execution_profile": "live",
            "render_mode": "lambda",
            "run_id": run_dir.name,
            "selected_candidate_id": "cand-1",
            "expected_video_path": str(video),
            "expected_video_sha256": sha256_file(video),
            "cover_sha256": sha256_file(cover),
            "title": LONG_TITLE,
            "desc": "讲清机制、适用边界和失败场景。",
            "tags": ["AI工具", "开源项目"],
        },
    )
    write_json(
        run_dir / "artifact_manifest.json",
        {
            "execution_profile": "live",
            "render_mode": "lambda",
            "publish_mode": "live",
            "selected_candidate_id": "cand-1",
            "final_video_path": str(video),
            "cover_path": str(cover),
        },
    )
    write_json(run_dir / "render_metadata_check.json", {"status": "pass"})
    write_json(run_dir / "visual_audit_deterministic.json", passing_deterministic_visual_audit())
    for name in ["gemini_visual_audit", "premium_showcase_audit"]:
        write_json(
            run_dir / f"{name}.json",
            {"audit_name": name, "status": "not-used", "visual_audit_mode": "deterministic", "video_sha256": sha256_file(video)},
        )
    return run_dir


def run_check(run_dir: Path, tmp: Path, *, mode: str = "ok", uploader: str | None = "ego", live: bool = True) -> subprocess.CompletedProcess[str]:
    stub = tmp / "publisher_stub.py"
    stub.write_text(STUB_PUBLISHER, encoding="utf-8")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("SEARCHPO_", "DOUYIN_", "SOCIAL_"))
    }
    env.update(
        {
            "SEARCHPO_ENV_FILE": str(tmp / "none.env"),
            "SEARCHPO_DOUYIN_LIVE": "1" if live else "0",
            "SEARCHPO_DOUYIN_CHECK_LEVEL": "adapter",
            "SEARCHPO_EGO_PUBLISHER": str(stub),
            "SEARCHPO_NODE_BIN": sys.executable,
            "SEARCHPO_RENDERED_VIDEO": str(run_dir / "video" / "final.mp4"),
            "SEARCHPO_RENDERED_COVER": str(run_dir / "cover" / "final.jpg"),
            "SOCIAL_AUTO_UPLOAD_ROOT": str(tmp / "no-social-auto-upload"),
            "STUB_ARGS_OUT": str(tmp / "publisher_args.json"),
            "STUB_MODE": mode,
        }
    )
    if uploader is not None:
        env["SEARCHPO_DOUYIN_UPLOADER"] = uploader
    return subprocess.run(
        ["bash", "scripts/douyin_upload_check.sh", str(run_dir)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def finalize_live(run_dir: Path) -> tuple[int, dict[str, Any]]:
    board = TaskBoard(run_dir / "harness_board.sqlite3")
    try:
        root_task = board.create_task("root", "root", "test")
        board.set_status(root_task, "running", "test")
        upload_check = json.loads((run_dir / "post" / "douyin_upload_check.json").read_text(encoding="utf-8"))
        gate_status = "pass" if upload_check.get("status") == "pass" else "fail"
        task = board.create_task("douyin_publish", "publish", "test", root_task)
        board.gate(task, Gate("douyin_live_publish_gate", gate_status, "ego publisher result"))
        board.set_status(task, "completed", "test")
        write_json(run_dir / "agent_run.json", {"root_task_id": root_task})
    finally:
        board.close()
    argv = ["finalize_run.py", str(run_dir), "--publish-mode", "live", "--execution-profile", "live"]
    with patch.dict(os.environ, {"SEARCHPO_VISUAL_AUDIT": "deterministic"}), patch.object(sys, "argv", argv), redirect_stdout(StringIO()):
        code = finalize_run_main()
    return code, json.loads((run_dir / "run_final.json").read_text(encoding="utf-8"))


class EgoPublisherTests(unittest.TestCase):
    def test_successful_publish_maps_into_a_passing_release_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            run_dir = build_live_run(tmp)
            proc = run_check(run_dir, tmp)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

            check = json.loads((run_dir / "post" / "douyin_upload_check.json").read_text(encoding="utf-8"))
            self.assertEqual(check["status"], "pass", check["errors"])
            self.assertEqual(check["adapter"], "ego-publisher")
            self.assertEqual(check["publish_mode"], "live")
            self.assertEqual(check["account_check"]["status"], "not-required")
            self.assertEqual(check["live_upload"]["status"], "submitted")
            self.assertIsNone(check["cli_help"])

            verification = json.loads((run_dir / "post" / "post_publish_verification.json").read_text(encoding="utf-8"))
            self.assertEqual(verification["status"], "pass", verification["errors"])
            self.assertEqual(verification["verification_method"], "ego_publisher_remote_id")
            self.assertEqual(verification["remote"]["remote_post_id"], REMOTE_ID)
            self.assertEqual(verification["remote"]["visibility"], "self_only")

            args = json.loads((tmp / "publisher_args.json").read_text(encoding="utf-8"))
            title = args[args.index("--title") + 1]
            self.assertLessEqual(len(title.encode("utf-16-le")) // 2, 30)
            self.assertTrue(LONG_TITLE.startswith(title))
            description = args[args.index("--description") + 1]
            self.assertIn("讲清机制", description)
            self.assertIn("#AI工具", description)
            self.assertEqual(args[args.index("--visibility") + 1], "self_only")
            self.assertEqual(Path(args[args.index("--file") + 1]), run_dir / "video" / "final.mp4")
            self.assertTrue(Path(args[args.index("--shots") + 1]).is_relative_to(run_dir / "post"))

            code, final = finalize_live(run_dir)
            self.assertEqual(code, 0, final["errors"])
            self.assertEqual(final["publish_status"], "verified-published")
            self.assertTrue(final["production_success"])

    def test_failing_publisher_produces_a_failing_release_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            run_dir = build_live_run(tmp)
            proc = run_check(run_dir, tmp, mode="fail")
            self.assertEqual(proc.returncode, 1)

            check = json.loads((run_dir / "post" / "douyin_upload_check.json").read_text(encoding="utf-8"))
            self.assertEqual(check["status"], "fail")
            self.assertEqual(check["live_upload"]["status"], "failed")
            self.assertTrue(any("signed-in profile expired" in error for error in check["errors"]), check["errors"])
            verification = json.loads((run_dir / "post" / "post_publish_verification.json").read_text(encoding="utf-8"))
            self.assertEqual(verification["status"], "fail")

            code, final = finalize_live(run_dir)
            self.assertEqual(code, 1)
            self.assertEqual(final["publish_status"], "fail")
            self.assertIn("douyin upload check did not pass", final["errors"])
            self.assertIn("live publish requires post_publish_verification.json status=pass", final["errors"])

    def test_ok_without_a_remote_id_is_not_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            run_dir = build_live_run(tmp)
            proc = run_check(run_dir, tmp, mode="no-id")
            self.assertEqual(proc.returncode, 1)
            verification = json.loads((run_dir / "post" / "post_publish_verification.json").read_text(encoding="utf-8"))
            self.assertEqual(verification["status"], "fail")
            self.assertIn("remote_identity_present", verification["errors"])
            code, _final = finalize_live(run_dir)
            self.assertEqual(code, 1)

    def test_default_uploader_still_uses_social_auto_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            run_dir = build_live_run(tmp)
            proc = run_check(run_dir, tmp, uploader=None, live=False)
            self.assertEqual(proc.returncode, 1)
            check = json.loads((run_dir / "post" / "douyin_upload_check.json").read_text(encoding="utf-8"))
            self.assertEqual(check["adapter"], "dreammis/social-auto-upload")
            self.assertIn("Missing required file: social_root", check["errors"])
            self.assertIn("douyin upload-video", check["upload_command_preview"])
            self.assertFalse((tmp / "publisher_args.json").exists())


if __name__ == "__main__":
    unittest.main()
