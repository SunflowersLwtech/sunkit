Run the searchpo main/impl flow end to end.

Use the `searchpo-main-agent` skill. Delegate execution to `searchpo-impl-agent` where appropriate.

## Provider Stack

- DeepSeek V4 Pro → 口播润色 (多候选 A/B)
- Gemini 3.5 Flash → 内容评分 + 视频审核
- Gemini 3.1 Flash TTS → 语音合成
- Remotion 4.0 → 合成视频 (动态字幕, CRF 18)
- social-auto-upload → 发布抖音

## Required behavior

1. If the user request includes `发抖音`, `发布`, `live`, or `post --live`, run `npm run e2e:live`; otherwise run `npm run e2e`.
2. Read `runtime/latest_run.txt`.
3. Verify these artifacts in the run directory:
   - `agent_run.json`
   - `main_task_plan.json`
   - `render_payload.json`
   - `render_input_manifest.json`
   - `post/douyin_upload_check.json`
   - In provider/live mode also verify:
     - `deepseek_polish.json` (DeepSeek V4 Pro)
     - `content_score.json` (Gemini 3.5 Flash quality score)
     - `voiceover_manifest.json` (Gemini 3.1 Flash TTS)
     - `gemini_visual_audit.json` (Gemini 3.5 Flash video audit)
4. Report content quality score from `content_score.json` (overall/10 + verdict).
5. Report whether publishing was contract-check or live, based on `post/douyin_upload_check.json`.
6. If any gate failed, report which stage and suggest `--resume-from N`.
7. Do not print secret values.
