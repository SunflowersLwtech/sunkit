---
description: Run the Searchpo full provider/live flow with source cross-check, render audit, and Douyin gate verification.
argument-hint: '[link-or-topic] [--live]'
---

# Searchpo Full Flow

Run the Searchpo main/research/impl flow end to end for an operator-supplied topic or link.

Use the `searchpo-main-agent` skill. In Claude/Codex agent-team mode, the main agent must assign source research/cross-check to `searchpo-research-agent`, provider/render/audit/upload execution to `searchpo-impl-agent`, and keep the final release decision itself.

For Codex, selecting this slash command or skill is not enough to prove a real team run. If the host exposes subagent tools, use this exact team shape before running provider/live commands:

```text
Use the searchpo-main-agent as lead. Do not run research and implementation in parallel. First spawn or assign only searchpo-research-agent for AnySearch-first source discovery/extraction, GitHub API/README evidence, FactBank/TopicBrief, cross-check tasks, and only supporting DeepWiki repo context when useful. Wait until the main agent verifies cross_check_review.status == pass and research_sufficient == true, then spawn or assign searchpo-impl-agent for provider, render, audit, and Douyin tasks. The main agent must not run implementation commands itself; it verifies artifacts and makes the final release decision.
```

If subagent tools are not available, say so before execution, follow the same ownership split manually, and report the result as `manual fallback`.

Raw slash-command arguments:

```text
$ARGUMENTS
```

## Preflight

1. Use `npm run e2e:live` only when the current user request explicitly includes `发抖音`, `发布`, `live`, or `post --live`; live mode still requires `SEARCHPO_DOUYIN_LIVE=1`.
2. Establish delegation mode before running the shell command: spawned/assigned agent team when possible, otherwise explicit manual fallback.
3. Research and implementation must be sequential. Do not start `searchpo-impl-agent`, provider commands, render, audit, or publish checks until the main agent verifies the research barrier.
4. Before provider/live execution, the research agent must run or explicitly own widesearch source discovery/extraction; DeepWiki repo notes are supporting context and cannot be the first or only completed research task.
5. Use `SEARCHPO_TOPIC="..." npm run e2e:provider` or `SEARCHPO_LINK="https://..." npm run e2e:provider` by default for a publishable local render, but when `searchpo-impl-agent` is available the implementation agent runs this command, not the main agent.
6. Use `npm run e2e` only for no-provider contract wiring checks, and still pass `SEARCHPO_TOPIC`, `SEARCHPO_LINK`, or `SEARCHPO_TOPIC_URL`.
7. If `$ARGUMENTS` or the user message includes a fixed link, pass it as `SEARCHPO_LINK="https://..."`; if it includes a topic plus canonical URL, pass `SEARCHPO_TOPIC="..." SEARCHPO_TOPIC_URL="https://..."`; if it includes only a topic, pass `SEARCHPO_TOPIC="..."` and require widesearch to find independent evidence before copy generation.
8. Missing operator topic/link input, missing widesearch research enrichment, insufficient independent supplemental sources, missing provider output, missing media tooling, missing visual audit evidence, or missing remote live identity must fail. Do not create mock, placeholder, silent, skipped, or fallback artifacts to make a run pass.

## Provider Stack

- AnySearch vendored CLI -> supplemental source search/extract, FactBank, TopicBrief, and enriched cross-check, owned by `searchpo-research-agent`.
- DeepSeek V4 Pro -> voiceover/copy polish and Gemini-feedback revisions, owned by `searchpo-impl-agent`.
- Gemini 3.5 Flash -> content scoring/revision feedback and video audit/repair routing.
- Gemini 3.1 Flash TTS -> speech synthesis.
- Remotion 4.0 -> 1080x1920 video composition with dynamic captions and CRF 18.
- social-auto-upload -> Douyin publish path.

## Commands

Provider/local render:

```bash
SEARCHPO_TOPIC="topic to investigate" npm run e2e:provider
```

Direct link:

```bash
SEARCHPO_LINK="https://github.com/owner/repo" npm run e2e:provider
```

Topic with canonical URL:

```bash
SEARCHPO_TOPIC="topic" SEARCHPO_TOPIC_URL="https://example.com/source" npm run e2e:provider
```

Live Douyin publish, only after explicit current-run approval:

```bash
SEARCHPO_TOPIC="topic to investigate" npm run e2e:live
```

## Verification

1. Read `runtime/latest_run.txt`.
2. Verify these artifacts in the run directory:
   - `agent_run.json`
   - `main_task_plan.json`
   - `evidence_bundle.json`
   - `widesearch_strategy.json`
   - `anysearch_research.json`
   - `fact_bank.json`
   - `research_brief.json`
   - `cross_check_review.json`
   - `artifact_manifest.json`
   - `run_final.json`
   - `render_payload.json`
   - `render_input_manifest.json`
   - `post/douyin_upload_check.json`
   - In provider/live mode also verify:
     - `content_optimization_loop.json` (DeepSeek/Gemini content improve attempts)
     - `deepseek_polish.json` (DeepSeek V4 Pro)
     - `content_score.json` (Gemini 3.5 Flash quality score)
     - `voiceover_manifest.json` (Gemini 3.1 Flash TTS)
     - `video_optimization_loop.json` (render/audit/improve attempts)
     - `visual_audit_deterministic.json` (ffmpeg/tesseract/caption/media checks)
     - `gemini_visual_audit.json` (Gemini 3.5 Flash video audit)
3. Report content quality score from `content_score.json` (overall/10 + verdict).
4. Report whether the run used sequential spawned/assigned subagents or manual fallback; artifact owner labels alone do not prove real subagent execution.
5. Report the research barrier outcome before implementation: `cross_check_review.status`, `research_sufficient`, `supplemental_source_count`, and `independent_source_hosts`.
6. Report whether publishing was contract-check or live, based on `run_final.json` and `post/douyin_upload_check.json`. Live mode requires `post/post_publish_verification.json`; `submitted` is not success.
7. If any gate failed, report which stage and suggest `--resume-from N`.
8. Do not print secret values.
