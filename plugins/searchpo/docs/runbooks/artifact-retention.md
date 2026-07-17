# Artifact Retention

Generated artifacts may contain source snapshots, provider output, rendered media, and publishing evidence. Treat them as operational records, not source.

| Location | Contents | Default Handling |
| --- | --- | --- |
| `runtime/artifacts/YYYY-MM-DD/<run_id>/` | Raw source rows, shortlist, board DB, gates, post package, final media | Keep latest local runs needed for review; archive or purge older runs manually. |
| `runtime/artifacts/YYYY-MM-DD/<run_id>/{topic_brief,fact_bank,source_map,script,scene_plan,video_spec,delivery_package}.json` | Full-service content lineage | Keep with every reviewed or published run. |
| `runtime/artifacts/YYYY-MM-DD/<run_id>/video/final.mp4` | Final uploadable MP4 bound to `artifact_manifest.json` | Keep for every reviewed or published run. |
| `runtime/artifacts/YYYY-MM-DD/<run_id>/cover/final.jpg` | Final uploadable Douyin cover bound to `artifact_manifest.json` | Keep for every reviewed or published run. |
| `runtime/artifacts/YYYY-MM-DD/<run_id>/RUN.md` | Human-readable run index | Regenerate with `python3 scripts/index_run_artifacts.py <run_dir>` if missing. |
| `out/previews/YYYY-MM-DD/<run_id>/attempt-XX/<backend>/` | Render previews only | Ignored; never use as publish input. |
| Flat `out/*.mp4` and `out/*.jpg` | Legacy preview scratch | Archive or delete after confirming final media is bound in the run directory. |
| `public/generated/` | Runtime voiceover copied for Remotion static assets | Ignored; regenerated per run. |
| Remotion S3 bucket | Site bundle and Lambda render artifacts | Use configured `deleteAfter` and bucket lifecycle expiry. |
| CloudWatch logs | Lambda execution logs | Retain 14 days unless incident review requires export. |
| `runtime/social-auto-upload` | Uploader checkout, cookies, local browser state | Local only; never commit or share wholesale. |

Before deleting an incident run, save the minimal evidence package: `run_final.json`, `artifact_manifest.json`, `delivery_package.json`, `topic_brief.json`, `fact_bank.json`, `source_map.json`, `script.json`, `scene_plan.json`, `video_spec.json`, `agent_run.json`, `main_task_plan.json`, `content_optimization_loop.json`, `video_optimization_loop.json`, `claims_ledger.json`, `visual_audit_deterministic.json`, `gemini_visual_audit.json` when present, `douyin_upload_check.json`, `post_publish_verification.json` when present, and `video/final.mp4`.
