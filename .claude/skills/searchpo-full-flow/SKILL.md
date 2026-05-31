---
name: searchpo-full-flow
description: Run the full Searchpo provider/live flow from input selection through evidence, FactBank, DeepSeek/Gemini, Remotion render, audit, delivery package, and Douyin gate verification. Use when the user asks to run the complete flow, full flow, /searchpo-full-flow, end-to-end publishable render, or live publish.
version: 1.0.0
triggers:
  - "full flow"
  - "complete flow"
  - "/searchpo-full-flow"
  - "end-to-end"
  - "e2e provider"
  - "跑完整flow"
  - "完整流程"
  - "全链路"
  - "发抖音"
  - "发布"
tools:
  - shell
  - filesystem
mutating: true
---

# Searchpo Full Flow

This is the visible skill wrapper for the shared `/searchpo-full-flow` command. Use `searchpo-main-agent` as the lead, keep research with `searchpo-research-agent`, and keep provider/render/publish execution with `searchpo-impl-agent`.

## Agent-Team Requirement

For Codex runs, selecting this skill or writing owner labels into `main_task_plan.json` is not enough to prove delegation. When the current host exposes a subagent or agent-team runtime, explicitly spawn or assign:

```text
Use the searchpo-main-agent as lead. Do not run research and implementation in parallel. First spawn or assign only searchpo-research-agent for AnySearch-first source discovery/extraction, GitHub API/README evidence, FactBank/TopicBrief, cross-check tasks, and only supporting DeepWiki repo context when useful. Wait until the main agent verifies cross_check_review.status == pass and research_sufficient == true, then spawn or assign searchpo-impl-agent for provider, render, audit, and Douyin tasks. The main agent must not run implementation commands itself; it verifies artifacts and makes the final release decision.
```

If the host cannot spawn or assign teammates, say that before running the flow, follow the same ownership split manually, and report the run as `manual fallback`, not as a spawned agent-team run.

## Command Choice

- Topic-only widesearch with publishable local render:

```bash
SEARCHPO_TOPIC="topic to investigate" npm run e2e:provider
```

- Direct link:

```bash
SEARCHPO_LINK="https://github.com/owner/repo" npm run e2e:provider
```

- Topic with canonical evidence URL:

```bash
SEARCHPO_TOPIC="topic" SEARCHPO_TOPIC_URL="https://example.com/source" npm run e2e:provider
```

- Live Douyin publish only after an explicit current-run user request:

```bash
SEARCHPO_TOPIC="topic to investigate" npm run e2e:live
```

Use `npm run e2e` only for no-provider contract wiring checks, and still pass `SEARCHPO_TOPIC`, `SEARCHPO_LINK`, or `SEARCHPO_TOPIC_URL`. The legacy source-registry sweep requires explicit `SEARCHPO_ENABLE_DAILY_RADAR=1`.

## Required Flow

1. Establish the delegation mode: spawned/assigned sequential agent team when the host supports it, otherwise manual fallback with the same ownership split.
2. Inspect capability availability with `python3 scripts/agent_capabilities.py --profile all --format text`; do not print `.env` values.
3. Assign evidence/research to `searchpo-research-agent` only: canonical URL detail, GitHub API/README for GitHub repos, AnySearch-first supplemental search/extract, FactBank, TopicBrief, enriched cross-check, and only supporting DeepWiki repo context when useful. Do not let DeepWiki-only notes count as completed research.
4. Stop at the research barrier. The main agent must verify `widesearch_strategy.json`, `anysearch_research.json`, raw AnySearch search/extract files, `fact_bank.json`, `topic_brief.json`, and `cross_check_review.json` before implementation starts.
5. Only after `cross_check_review.status == "pass"` and `research_sufficient == true`, assign provider/render/publish execution to `searchpo-impl-agent`: DeepSeek, Gemini scoring/TTS/audit, Remotion render, deterministic media audit, final artifact binding, and Douyin adapter/live checks.
6. Main must not run provider/render/publish commands when `searchpo-impl-agent` is available. Main verifies artifacts before declaring success, and includes the actual delegation mode in the final report.

## Verification

After the command finishes, read `runtime/latest_run.txt` and verify the run directory:

- `agent_run.json`
- `main_task_plan.json`
- `evidence_bundle.json`
- `widesearch_strategy.json`
- `anysearch_research.json`
- `fact_bank.json`
- `topic_brief.json`
- `research_brief.json`
- `cross_check_review.json`
- provider/live: `script.json`, `scene_plan.json`, `video_spec.json`, `render_payload.json`, `render_input_manifest.json`
- provider/live: `deepseek_polish.json`, `content_score.json`, `voiceover_manifest.json`, `video_optimization_loop.json`, `visual_audit_deterministic.json`, `gemini_visual_audit.json`
- provider/live: `artifact_manifest.json`, `delivery_package.json`, `run_final.json`, `post/douyin_upload_check.json`
- live: `post/post_publish_verification.json`

`submitted` is not live success. Live success requires remote identity verification.
