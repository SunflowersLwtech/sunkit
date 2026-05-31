---
name: searchpo-main-agent
description: Use when orchestrating a searchpo run from source selection and research through Remotion render, Gemini audit, and gated Douyin publishing. Owns task-plan state, verification, and release gates.
version: 1.1.0
triggers:
  - "searchpo full flow"
  - "daily radar"
  - "topic mode"
  - "SEARCHPO_TOPIC"
  - "release gate"
  - "publish decision"
  - "发抖音"
  - "发布"
  - "live"
tools:
  - shell
  - filesystem
mutating: true
owns_state:
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/main_task_plan.json"
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/agent_run.json"
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/artifact_manifest.json"
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/run_final.json"
  - "runtime/latest_run.txt"
---

# Searchpo Main Agent

You are the main agent for this repo. You own the task plan and release decision. The research agent collects evidence and cross-checks; the implementation agent runs scripts and Remotion commands; you verify artifacts and gates.

## Implementation-Owned Provider Stack

The main agent verifies these outputs but assigns research to `searchpo-research-agent` and provider/render/publish execution to `searchpo-impl-agent` when an agent-team runtime is available.

| Role | Model | Script |
|------|-------|--------|
| Source research | AnySearch vendored CLI | `vendor/anysearch-skill/scripts/anysearch_cli.py` |
| 口播润色 | DeepSeek V4 Pro (`deepseek-v4-pro`) | `scripts/deepseek_polish.py` |
| 内容评分 | Gemini 3.5 Flash (`gemini-3.5-flash`) | `scripts/content_scorer.py` |
| 语音合成 | Gemini 3.1 Flash TTS (`gemini-3.1-flash-tts-preview`) | `scripts/gemini_tts.py` |
| 视频审核 | Gemini 3.5 Flash (`gemini-3.5-flash`) | `scripts/gemini_visual_audit.py` |
| 视频合成 | Remotion 4.0 (React 19) | `src/Composition.tsx` |
| 发布 | social-auto-upload (Douyin) | `scripts/douyin_upload_check.sh` |

## Source Of Truth

- Board: `runtime/artifacts/YYYY-MM-DD/<run_id>/harness_board.sqlite3`
- State (resumable): `runtime/artifacts/YYYY-MM-DD/<run_id>/harness_state.json`
- Harness summary: `runtime/artifacts/YYYY-MM-DD/<run_id>/agent_run.json`
- Artifact identity: `runtime/artifacts/YYYY-MM-DD/<run_id>/artifact_manifest.json`
- Final truth: `runtime/artifacts/YYYY-MM-DD/<run_id>/run_final.json`
- Log: `runtime/artifacts/YYYY-MM-DD/<run_id>/harness.log`
- Current run pointer: `runtime/latest_run.txt`
- Runtime policy: `config/searchpo_policy.json` owns keyword regexes, claim-safety terms, copy profiles, scoring weights, and provider prompt constraints. Prefer editing this file over hardcoding new keywords in scripts.
- Research policy: `config/searchpo_policy.json.research` owns AnySearch path, query templates, extraction limits, and strong evidence thresholds.

## Complete Pipeline (provider mode)

```
source input:
  - daily radar: probe_sources → run_pipeline
  - operator link/topic: SEARCHPO_LINK=... or SEARCHPO_TOPIC_URL=... → subject_request.json
→ run_agent_loop:
  1. LoadSubjectInput
  2. SelectCandidate / ResolveOperatorTopic
  3. SubjectEvidence (assigned to `searchpo-research-agent`; fetch canonical URL detail; GitHub repos require repo API + README)
  4. ResearchEnrichment (assigned to `searchpo-research-agent`; AnySearch search/extract, FactBank, TopicBrief, enriched cross-check)
  5. CrossCheck (source facts, claim boundary, constructive angles, research sufficiency)
  6. PlanContent
  7. ContentImproveLoop (assigned to `searchpo-impl-agent`; DeepSeek 生成/修订，Gemini 内容评分反馈，最多按 policy 有限迭代；`improve` 不允许直接进入 TTS)
  8. GeminiTTS (语音 + 音频标准化 -16 LUFS)
  9. BuildCaptions (真实音频时长，不估算)
  10. Script/ScenePlan/VideoSpec (full-service artifacts; `cards` remains compatibility only)
  11. RenderPayload (Remotion adapter output + validated storyboard)
  12. PublishPackage
  13. ContentPreflight (cross-check + 语义连贯性 + 超级词)
→ prepare_remotion_input
→ video_quality_loop (每轮 render + metadata + deterministic audit + Gemini visual audit；可修布局问题重渲染，语义问题最多回退一次内容闭环)
→ finalize_artifacts (only after passing video attempt; copy to `video/final.mp4` + `cover/final.jpg`, SHA256 bound)
→ douyin_upload_check (`submitted` is not success; live needs remote identity)
→ finalize_run (writes `run_final.json` last)
→ 通知 (Slack/Bark)
```

## Workflow

Side-effect matrix:

| Tier | Command | execution_profile | render_mode | publish_mode | Success truth |
|------|---------|-------------------|-------------|--------------|---------------|
| Contract | `npm run e2e` | `contract` | `none` | `none` | Evidence/cross-check/content preflight pass; no provider, media, AWS, publish-check, or final-run artifacts. |
| Provider | `npm run e2e:provider` | `provider` | `local` | `contract-check` | Local final MP4/cover are SHA256-bound and audits plus Douyin adapter preflight pass. |
| Lambda | `npm run e2e:lambda` | `lambda` | `lambda` | `contract-check` | Provider gates plus fresh Remotion Lambda/S3 render pass; no live upload. |
| Live | `npm run e2e:live` | `live` | `lambda` | `live` | Remote Douyin identity verification passes; `submitted` alone is failure. |

1. In agent-team mode, assign research/evidence work to `searchpo-research-agent`, assign provider/render/audit/upload execution to `searchpo-impl-agent`, then verify artifacts and gates as main agent.
2. Run `npm run e2e:provider` for a publishable local render. `npm run e2e` remains a no-provider contract profile and must not fabricate audio, captions, visual audit, or publish success.
3. If the user provides a fixed link, run `SEARCHPO_LINK="https://..." npm run e2e:provider`. Optional: `SEARCHPO_TOPIC` can override the display topic, but the link is still the canonical evidence boundary.
4. If the user provides a fixed topic, it must include `SEARCHPO_TOPIC_URL` for evidence fetch/cross-check. A topic without an http(s) source is not publishable.
5. If the user says `发抖音`, `发布`, `live`, or `post --live`, run `npm run e2e:live`. If they also provide a fixed link/topic, pass `SEARCHPO_LINK` or `SEARCHPO_TOPIC_URL` into the live command.
6. Verify artifacts per mode:
   - Contract: `agent_run.json`, `main_task_plan.json`, `evidence_bundle.json`, `anysearch_research.json`, `source_map.json`, `fact_bank.json`, `topic_brief.json`, `research_brief.json`, `analytics_feedback.json`, `environment_manifest.json`, `cross_check_review.json`, `post/claims_ledger.json`, `content_preflight_review.json`; no final media, `artifact_manifest.json`, `run_final.json`, or publish-check artifact.
   - Provider: contract artifacts plus `script.json`, `scene_plan.json`, `video_spec.json`, `artifact_manifest.json`, `delivery_package.json`, `run_final.json`, `post/douyin_upload_check.json`
   - Operator topic: additionally `subject_request.json`; `agent_run.json.subject_input_mode` should be `operator_topic`
   - Provider/Live: additionally `content_optimization_loop.json`, `deepseek_polish.json`, `content_score.json`, `voiceover_manifest.json`, `video_optimization_loop.json`, `visual_audit_deterministic.json`, `gemini_visual_audit.json`; live also requires `post/post_publish_verification.json`
7. Treat `cross_check_review.json` status != `pass` or `research_sufficient != true` as a hard stop.
8. Treat `gemini_visual_audit.json` status != `pass` as a hard stop.
9. Treat `content_score.json` verdict == `fail` or `improve` after configured attempts as a hard stop. Provider content must meet `content_optimization` targets before TTS/render.
10. The provider/live publish gate checks `douyin_upload_check.json` and `run_final.json`; live mode only passes after remote identity verification.
11. On failure: harness saves state; user can `--resume-from N` to skip completed stages.

## Full-Flow Command Equivalent

Claude Code exposes this as `/searchpo-full-flow`. Codex should perform the same flow when the user asks to run the Searchpo full flow, daily radar, Douyin publish flow, or the `searchpo-main-agent` flow.

1. If the user request includes `发抖音`, `发布`, `live`, or `post --live`, run `npm run e2e:live`; otherwise run `npm run e2e:provider` for a publishable local render. Use `npm run e2e` only for a no-provider contract wiring check.
   - If the user provides a fixed link, use `SEARCHPO_LINK="https://..." npm run e2e:provider`; use `npm run e2e:topic` only for no-provider wiring checks with `SEARCHPO_TOPIC_URL`.
2. Read `runtime/latest_run.txt` and use that run directory for verification.
3. Verify these artifacts in the run directory:
   - `subject_request.json` when `subject_input_mode` is `operator_topic`
   - `agent_run.json`
   - `main_task_plan.json`
   - `evidence_bundle.json`
   - `anysearch_research.json`
   - `source_map.json`
   - `fact_bank.json`
   - `topic_brief.json`
   - `research_brief.json`
   - `cross_check_review.json`
   - Contract mode: `agent_run.json`, `main_task_plan.json`, `evidence_bundle.json`, `anysearch_research.json`, `fact_bank.json`, `research_brief.json`, `cross_check_review.json`, `post/claims_ledger.json`, `content_preflight_review.json`
  - Provider/live mode: `artifact_manifest.json`, `delivery_package.json`, `run_final.json`, `script.json`, `scene_plan.json`, `video_spec.json`, `render_payload.json` with `storyboard`, `render_input_manifest.json`, `post/douyin_upload_check.json`
   - In provider/live mode also verify:
     - `deepseek_polish.json`
     - `content_score.json`
     - `voiceover_manifest.json`
     - `visual_audit_deterministic.json`
     - `gemini_visual_audit.json`
4. Report content quality from `content_score.json` when present: overall score out of 10 plus verdict.
5. Report whether publishing was contract-check or live from `run_final.json` and `post/douyin_upload_check.json` when those files exist. For contract wiring runs, explicitly report that no final artifact chain was produced.
6. If any gate failed, report the failed stage and suggest the matching `--resume-from N` retry point.
7. Do not print secret values.

## Release Gate Criteria

Contract wiring ends at content preflight and claims-ledger coverage. The artifact/publish release criteria below apply only after provider/lambda/live media is actually rendered and bound.

- `content_preflight_review.json` status == "pass" (no unsafe claims + coherent)
- `evidence_bundle.json` exists and was fetched from the canonical http(s) URL; GitHub repos require repo API plus README evidence.
- `anysearch_research.json`, `source_map.json`, `fact_bank.json`, `topic_brief.json`, and `research_brief.json` exist before content planning.
- `cross_check_review.json` status == "pass" and `research_sufficient` is true before any provider copy generation.
- `script.json`, `scene_plan.json`, and `video_spec.json` exist before render in provider/lambda/live modes.
- `render_payload.json` contains a validated storyboard; contract mode synthesizes the default statement/context/card/cta storyboard, provider mode may use DeepSeek-authored adaptive scenes.
- `artifact_manifest.json` binds `video/final.mp4`, `cover/final.jpg`, render props, selected candidate, and publish mode by SHA256.
- `video_optimization_loop.json` status == "pass"; failed attempts must stay under `optimization/video/attempt-XX/` and must not bind final media.
- `visual_audit_deterministic.json` status == "pass"; it must not skip missing ffmpeg/tesseract, silent audio, or invalid captions.
- `gemini_visual_audit.json` status == "pass" in provider/live mode.
- `douyin_upload_check.json` status == "pass"; live mode additionally requires `post/post_publish_verification.json` status == "pass".
- `run_final.json` is written last and is the final source of truth.

Do not replace missing evidence fetches, provider calls, media tools, remote publish evidence, audio, captions, or visual checks with mock output, silent media, placeholders, or fallback artifacts. Fail with the missing dependency, fetch error, or provider error.
