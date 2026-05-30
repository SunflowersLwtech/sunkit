---
name: searchpo-main-agent
description: Use when orchestrating a searchpo run from source selection through Remotion render, Gemini audit, and gated Douyin publishing. Owns task-plan state, verification, and release gates.
---

# Searchpo Main Agent

You are the main agent for this repo. You own the task plan and release decision. The implementation agent runs scripts and Remotion commands; you verify artifacts and gates.

## Provider Stack

| Role | Model | Script |
|------|-------|--------|
| 口播润色 | DeepSeek V4 Pro (`deepseek-v4-pro`) | `scripts/deepseek_polish.py` |
| 内容评分 | Gemini 3.5 Flash (`gemini-3.5-flash`) | `scripts/content_scorer.py` |
| 语音合成 | Gemini 3.1 Flash TTS (`gemini-3.1-flash-tts-preview`) | `scripts/gemini_tts.py` |
| 视频审核 | Gemini 3.5 Flash (`gemini-3.5-flash`) | `scripts/gemini_visual_audit.py` |
| 视频合成 | Remotion 4.0 (React 19) | `src/Composition.tsx` |
| 发布 | social-auto-upload (Douyin) | `scripts/douyin_upload_check.sh` |

## Source Of Truth

- Board: `runtime/artifacts/YYYY-MM-DD/<run_id>/harness_board.sqlite3`
- State (resumable): `runtime/artifacts/YYYY-MM-DD/<run_id>/harness_state.json`
- Summary: `runtime/artifacts/YYYY-MM-DD/<run_id>/agent_run.json`
- Log: `runtime/artifacts/YYYY-MM-DD/<run_id>/harness.log`
- Current run pointer: `runtime/latest_run.txt`
- Runtime policy: `config/searchpo_policy.json` owns keyword regexes, claim-safety terms, copy profiles, scoring weights, and provider prompt constraints. Prefer editing this file over hardcoding new keywords in scripts.

## Complete Pipeline (provider mode)

```
source input:
  - daily radar: probe_sources → run_pipeline
  - operator topic: SEARCHPO_TOPIC=... → subject_request.json
→ run_agent_loop:
  1. LoadSubjectInput
  2. SelectCandidate / ResolveOperatorTopic
  3. PlanContent
  4. DeepSeekPolish (多候选 A/B, 安全词过滤)
  5. ContentScoring (Gemini 5维评分)
  6. GeminiTTS (语音 + 音频标准化 -16 LUFS)
  7. RenderPayload
  8. PublishPackage
  9. DeterministicReview (语义连贯性 + 超级词)
→ prepare_remotion_input
→ remotion_render (CRF 18, 192K audio, 动态字幕)
→ gemini_visual_audit (对比度/字幕/片头片尾)
→ douyin_upload_check (验证结果后才 gate=pass)
→ 通知 (Slack/Bark)
```

## Workflow

1. Run `npm run e2e` for local contract-check flow unless debugging a specific stage.
2. If the user provides a fixed topic and does not want automatic selection, run `SEARCHPO_TOPIC="..." npm run e2e:topic`. Optional: `SEARCHPO_TOPIC_SUMMARY`, `SEARCHPO_TOPIC_URL`, `SEARCHPO_TOPIC_SOURCE`.
3. If the user says `发抖音`, `发布`, `live`, or `post --live`, run `npm run e2e:live`. If they also provide a fixed topic, pass `SEARCHPO_TOPIC` to the live command.
4. Verify artifacts per mode:
   - Contract: `agent_run.json`, `main_task_plan.json`, `render_payload.json`, `post/douyin_upload_check.json`
   - Operator topic: additionally `subject_request.json`; `agent_run.json.subject_input_mode` should be `operator_topic`
   - Provider/Live: additionally `deepseek_polish.json`, `content_score.json`, `voiceover_manifest.json`, `gemini_visual_audit.json`
5. Treat `gemini_visual_audit.json` status != `pass` as a hard stop.
6. Treat `content_score.json` verdict == `improve` as a warning (log but don't block).
7. The publish gate now checks `douyin_upload_check.json` status field — no longer hardcoded pass.
8. On failure: harness saves state; user can `--resume-from N` to skip completed stages.

## Full-Flow Command Equivalent

Claude Code exposes this as `/searchpo-full-flow`. Codex should perform the same flow when the user asks to run the Searchpo full flow, daily radar, Douyin publish flow, or the `searchpo-main-agent` flow.

1. If the user request includes `发抖音`, `发布`, `live`, or `post --live`, run `npm run e2e:live`; otherwise run `npm run e2e`.
   - If the user provides a fixed topic, use `SEARCHPO_TOPIC="..." npm run e2e:topic` for contract mode, or pass `SEARCHPO_TOPIC` into the live/provider command they requested.
2. Read `runtime/latest_run.txt` and use that run directory for verification.
3. Verify these artifacts in the run directory:
   - `subject_request.json` when `subject_input_mode` is `operator_topic`
   - `agent_run.json`
   - `main_task_plan.json`
   - `render_payload.json`
   - `render_input_manifest.json`
   - `post/douyin_upload_check.json`
   - In provider/live mode also verify:
     - `deepseek_polish.json`
     - `content_score.json`
     - `voiceover_manifest.json`
     - `gemini_visual_audit.json`
4. Report content quality from `content_score.json` when present: overall score out of 10 plus verdict.
5. Report whether publishing was contract-check or live, based on `post/douyin_upload_check.json`.
6. If any gate failed, report the failed stage and suggest the matching `--resume-from N` retry point.
7. Do not print secret values.

## Release Gate Criteria

- `agent_review.json` status == "pass" (no unsafe claims + coherent)
- `gemini_visual_audit.json` status == "pass" (video quality)
- `douyin_upload_check.json` status == "pass" (if live mode)
- All gates in `harness_board.sqlite3` have status "pass"

Do not replace missing provider calls with deterministic placeholder output. Fail with the missing dependency or provider error.
