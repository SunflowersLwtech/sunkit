# Artifact Retention

Generated artifacts may contain source snapshots, provider output, rendered media, and publishing evidence. Treat them as operational records, not source.

| Location | Contents | Default Handling |
| --- | --- | --- |
| `runtime/artifacts/YYYY-MM-DD/<run_id>/` | Raw source rows, shortlist, board DB, gates, post package | Keep latest local runs needed for review; archive or purge older runs manually. |
| `out/` | Rendered MP4s | Ignored; keep only current review outputs. |
| `public/generated/` | Runtime voiceover copied for Remotion static assets | Ignored; regenerated per run. |
| Remotion S3 bucket | Site bundle and Lambda render artifacts | Use configured `deleteAfter` and bucket lifecycle expiry. |
| CloudWatch logs | Lambda execution logs | Retain 14 days unless incident review requires export. |
| `runtime/social-auto-upload` | Uploader checkout, cookies, local browser state | Local only; never commit or share wholesale. |

Before deleting an incident run, save the minimal evidence package: `agent_run.json`, `main_task_plan.json`, `claims_ledger.json`, `gemini_visual_audit.json`, `douyin_upload_check.json`, and the exact rendered MP4 if it was published.
