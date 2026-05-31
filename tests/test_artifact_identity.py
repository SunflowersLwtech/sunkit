from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_harness.artifact_identity import (
    create_or_update_artifact_manifest,
    publish_conflict_errors,
    sha256_file,
    validate_upload_identity,
    write_json,
)


class ArtifactIdentityTests(unittest.TestCase):
    def test_final_artifacts_are_copied_and_upload_manifest_is_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "runtime" / "artifacts" / "2026-05-31" / "run-abc"
            post_dir = run_dir / "post"
            post_dir.mkdir(parents=True)
            video_preview = root / "out" / "run-abc-searchpo-radar.mp4"
            cover_preview = root / "out" / "run-abc-searchpo-cover.jpg"
            video_preview.parent.mkdir()
            video_preview.write_bytes(b"video-bytes")
            cover_preview.write_bytes(b"cover-bytes")
            write_json(run_dir / "selected_candidate.json", {"candidate_id": "cand-1", "title": "Demo", "canonical_url": "https://example.com"})
            write_json(run_dir / "remotion_input_props.json", {"title": "Demo"})
            write_json(run_dir / "render_payload.json", {"title": "Demo"})
            write_json(run_dir / "topic_brief.json", {"topic": "Demo"})
            write_json(run_dir / "fact_bank.json", {"facts": []})
            write_json(run_dir / "source_map.json", {"sources": []})
            write_json(run_dir / "script.json", {"title": "Demo"})
            write_json(run_dir / "scene_plan.json", {"scenes": []})
            write_json(run_dir / "video_spec.json", {"title": "Demo"})
            write_json(run_dir / "environment_manifest.json", {"service_boundaries": []})
            write_json(post_dir / "douyin_upload_manifest.json", {"title": "Demo", "desc": "Desc", "tags": ["AI"]})

            manifest = create_or_update_artifact_manifest(
                run_dir,
                rendered_video=video_preview,
                rendered_cover=cover_preview,
                render_mode="local",
                publish_mode="contract-check",
            )

            final_video = run_dir / "video" / "final.mp4"
            final_cover = run_dir / "cover" / "final.jpg"
            self.assertTrue(final_video.is_file())
            self.assertTrue(final_cover.is_file())
            self.assertEqual(manifest["final_video_sha256"], sha256_file(final_video))
            self.assertEqual(manifest["candidate_id"], "cand-1")
            self.assertEqual(manifest["execution_profile"], "provider")
            self.assertEqual(manifest["side_effect_tier"], "provider")
            self.assertEqual(manifest["render_mode"], "local")
            self.assertEqual(manifest["publish_mode"], "contract-check")
            self.assertEqual(manifest["mp4_hash"], manifest["final_video_sha256"])
            self.assertEqual(manifest["cover_hash"], manifest["cover_sha256"])
            self.assertEqual(manifest["render_props_hash"], manifest["render_props_sha256"])
            self.assertTrue(manifest["topic_brief_sha256"])
            self.assertTrue(manifest["fact_bank_sha256"])
            self.assertTrue(manifest["scene_plan_sha256"])
            self.assertTrue(manifest["video_spec_sha256"])
            self.assertTrue(manifest["publish_hash"])
            upload_manifest = __import__("json").loads((post_dir / "douyin_upload_manifest.json").read_text())
            self.assertEqual(upload_manifest["manifest_status"], "artifact-bound")
            self.assertEqual(upload_manifest["execution_profile"], "provider")
            self.assertEqual(upload_manifest["render_mode"], "local")
            self.assertEqual(upload_manifest["publish_mode"], "contract-check")
            self.assertEqual(Path(upload_manifest["expected_video_path"]).resolve(), final_video.resolve())
            self.assertEqual(upload_manifest["publish_hash"], manifest["publish_hash"])
            self.assertEqual(upload_manifest["video_spec_sha256"], manifest["video_spec_sha256"])
            errors, checks = validate_upload_identity(run_dir, video_path=final_video, cover_path=final_cover, live=False)
            self.assertEqual(errors, [], checks)

    def test_generic_or_stale_upload_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "runtime" / "artifacts" / "2026-05-31" / "run-abc"
            post_dir = run_dir / "post"
            post_dir.mkdir(parents=True)
            final_video = run_dir / "video" / "final.mp4"
            final_cover = run_dir / "cover" / "final.jpg"
            final_video.parent.mkdir(parents=True)
            final_cover.parent.mkdir(parents=True)
            final_video.write_bytes(b"video")
            final_cover.write_bytes(b"cover")
            stale = root / "out" / "searchpo-radar.mp4"
            stale.parent.mkdir()
            stale.write_bytes(b"stale")
            write_json(
                post_dir / "douyin_upload_manifest.json",
                {
                    "manifest_status": "artifact-bound",
                    "run_id": run_dir.name,
                    "publish_mode": "contract-check",
                    "expected_video_path": str(final_video),
                    "expected_video_sha256": sha256_file(final_video),
                    "cover_path": str(final_cover),
                    "cover_sha256": sha256_file(final_cover),
                },
            )

            errors, _ = validate_upload_identity(run_dir, video_path=stale, cover_path=final_cover, live=False)
            self.assertTrue(any("run-scoped" in error or "expected path" in error for error in errors))

    def test_contract_live_gate_conflict_is_detected(self) -> None:
        snapshot = {
            "gates": [
                {"name": "douyin_contract_gate"},
                {"name": "douyin_live_publish_gate"},
            ]
        }
        self.assertTrue(publish_conflict_errors(snapshot, "contract-check"))


if __name__ == "__main__":
    unittest.main()
