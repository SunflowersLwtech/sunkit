# Scripts

Scripts are thin operational entrypoints. Core state belongs in `data_prep/`, `agent_harness/`, `render/`, and generated `runtime/` artifacts.

| Script | Tier | Purpose |
| --- | --- | --- |
| `run_e2e.sh` | orchestrator | Profile-driven E2E: `contract`, `provider`, `lambda`, or `live`. |
| `check_env.py` | guard | Audits required env coverage for the selected profile without printing values. |
| `agent_harness/evidence.py` | content evidence | Fetches canonical URL details and writes `evidence_bundle.json` plus `cross_check_review.json` before copy generation. |
| `agent_harness/service_artifacts.py` | local service contracts | Writes TopicBrief, FactBank, Script, ScenePlan, VideoSpec, DeliveryPackage, source map, environment, and analytics-feedback artifacts. |
| `remotion_render.sh` | local render | Renders the latest run with run-scoped props. |
| `lambda_render.sh` | AWS explicit | Uploads/renders via Remotion Lambda. |
| `finalize_artifacts.py`, `finalize_run.py` | release truth | Binds final media by SHA256 and writes `run_final.json` last. |
| `cover_health.py`, `backfill_douyin_covers.py` | cover integrity | Rejects black/blank covers and repairs run-scoped cover/video bindings for older runs. |
| `video_quality_loop.py` | media improve loop | Runs render/audit attempts, applies layout repairs or content backtracks, and only binds the passing attempt. |
| `deterministic_visual_audit.py` | media QA | Requires ffmpeg/tesseract; fails on invalid captions, black frames, or silent provider audio. |
| `douyin_upload_check.sh` | publish boundary | Manifest check, adapter preflight, or live upload depending on env gates. |
| `deepseek_polish.py`, `gemini_tts.py`, `gemini_visual_audit.py` | provider explicit | Real provider calls; never fabricate output. |
| `scan_secrets.py`, `redact_trace_export.py` | security | Redacted trace export and secret-shaped string scanning. |
| `validate_static.sh`, `no_live_guard.py` | CI | Static gates and safe-by-default command checks. |

`run_e2e.sh` resolves each command into three explicit axes:

| Profile | render_mode | publish_mode |
| --- | --- | --- |
| `contract` | `none` | `none` |
| `provider` | `local` | `contract-check` |
| `lambda` | `lambda` | `contract-check` |
| `live` | `lambda` | `live` |

Only `live` may set `SEARCHPO_DOUYIN_LIVE=1`. Lambda renders use private output, bucket folder expiry, `REMOTION_LAMBDA_DELETE_AFTER`, and default `REMOTION_LAMBDA_CONCURRENCY=4` unless `SEARCHPO_LAMBDA_FRAMES_PER_LAMBDA` is explicitly set.
| `apply_social_auto_upload_patches.sh` | third-party patch | Explicit local patch step for ignored uploader checkout. |
