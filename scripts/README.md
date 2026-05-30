# Scripts

Scripts are thin operational entrypoints. Core state belongs in `data_prep/`, `agent_harness/`, `render/`, and generated `runtime/` artifacts.

| Script | Tier | Purpose |
| --- | --- | --- |
| `run_e2e.sh` | orchestrator | Profile-driven E2E: `contract`, `provider`, `lambda`, or `live`. |
| `check_env.py` | guard | Audits required env coverage for the selected profile without printing values. |
| `remotion_render.sh` | local render | Renders the latest run with run-scoped props. |
| `lambda_render.sh` | AWS explicit | Uploads/renders via Remotion Lambda. |
| `douyin_upload_check.sh` | publish boundary | Manifest check, adapter preflight, or live upload depending on env gates. |
| `deepseek_polish.py`, `gemini_tts.py`, `gemini_visual_audit.py` | provider explicit | Real provider calls; never fabricate output. |
| `validate_static.sh`, `no_live_guard.py` | CI | Static gates and safe-by-default command checks. |
| `apply_social_auto_upload_patches.sh` | third-party patch | Explicit local patch step for ignored uploader checkout. |
