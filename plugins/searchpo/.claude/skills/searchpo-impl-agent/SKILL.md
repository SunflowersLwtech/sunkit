---
name: searchpo-impl-agent
description: Use when implementing or running searchpo provider scripts, Remotion rendering, Gemini visual audit, and Douyin publish/check commands.
version: 1.2.0
triggers:
  - "run searchpo scripts"
  - "provider scripts"
  - "DeepSeek polish"
  - "Gemini TTS"
  - "visual audit"
  - "Remotion render"
  - "Douyin check"
  - "Douyin upload"
  - "resume from"
tools:
  - shell
  - filesystem
mutating: true
writes_to:
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/"
  - "out/"
  - "public/generated/"
---

# Searchpo Implementation Agent

You execute the main agent's assigned provider, render, audit, and publish tasks. The research agent owns source collection, AnySearch enrichment, FactBank, TopicBrief, and cross-check artifacts. Your job is to run scripts and Remotion commands, not to own the release decision. Do not start implementation until the main agent verifies the research barrier.

Before selecting optional provider/render/publish services, run `python3 scripts/agent_capabilities.py --profile implementation --format text`. Report missing key names only; never print `.env` values.

## Provider Models (current defaults)

| Provider | Model ID | Purpose |
|----------|----------|---------|
| DeepSeek | `deepseek-v4-pro` | 口播润色 + 抖音文案 + adaptive storyboard |
| Gemini | `gemini-3.5-flash` | 视频审核 + 内容评分 |
| Gemini TTS | `gemini-3.1-flash-tts-preview` | 语音合成 |

## Commands

Full flow:

```bash
SEARCHPO_TOPIC="指定主题" npm run e2e           # contract: topic/link evidence/text checks only; no providers, media, AWS, or publish checks
SEARCHPO_TOPIC="指定主题" SEARCHPO_TOPIC_URL="https://..." npm run e2e  # contract: fixed canonical URL plus widesearch/cross-check
SEARCHPO_TOPIC="指定主题" npm run e2e:provider  # provider: topic-first widesearch + DeepSeek/Gemini + local render
SEARCHPO_LINK="https://github.com/owner/repo" npm run e2e:provider  # link: 直接给 canonical URL，全链路内容质量 gate
SEARCHPO_TOPIC="指定主题" npm run e2e:lambda    # lambda: provider + AWS Lambda/S3 render; publish_mode=contract-check
SEARCHPO_TOPIC="指定主题" npm run e2e:live      # live: provider + Lambda render + real Douyin upload; publish_mode=live
```

Runtime axes are recorded separately in generated JSON: `execution_profile=contract|provider|lambda|live`, `render_mode=none|local|lambda`, and `publish_mode=none|contract-check|live`.

## Research Barrier

Before provider/live commands, require main-agent confirmation that:

- `research_barrier.json.status == "pass"`;
- `cross_check_review.status == "pass"`;
- `cross_check_review.research_sufficient == true`;
- `widesearch_strategy.json` records the selected source buckets/query plan;
- `anysearch_research.json` includes search and extract commands;
- raw AnySearch search/extract outputs exist under `research/anysearch_raw/` when a run directory exists.

If this is not true, return control to `searchpo-main-agent`; implementation must not run in parallel with research. Implementation progress is recorded in `implementation_loop.json`; it is evidence for the main agent, not a release decision.

## agent_visual quality duty

Provider/lambda/live media must render from a topic-specific, richly animated `agent_visual`. The provider may choose either Douyin vertical `9:16` or horizontal `16:9` when the topic justifies it; do not force every publishable run into the short vertical radar format. Before render or audit work, inspect the run-scoped `render_payload.json` and verify:

- `agentVisual.enabled == true`;
- no `agentVisual.fallback_reason`, `_agent_visual_fallback_applied`, or validation errors are present;
- `videoProfile.orientation`, `aspectRatio`, `width`, and `height` agree: vertical means `9:16`/`1080x1920`, horizontal means `16:9`/`1920x1080`;
- duration is chosen by the model for the current topic; `180s+` is not a default target, it is only the long-form quality threshold once the model chooses that runtime;
- videos at or above 180 seconds have a chaptered storyboard with enough scene beats for the runtime, not 3-7 short scenes stretched over a long narration;
- `agentVisual.description` and `component_code` or `module_code` contain topic-specific visual primitives such as terminal, code, diff, file tree, architecture flow, chart, matrix, timeline, table, graph, product UI, or node flow;
- the code does not rely on `data.cards`, `safeCards`, captions/subtitles, full `data.summary`, or internal evidence metadata as the main visual surface.

Use `skills/remotion-best-practices/SKILL.md` section `Writing Richly Animated agent_visual TSX Components` as the repair template. A good repair regenerates `agent_visual.module_code` or `agent_visual.component_code/css` with four motion layers: spring entrance, staggered child reveals, continuous central idle movement, and audio-reactive emphasis. Prefer `module_code` for ambitious visuals because it can be a complete TSX module with imports and a named `AgentVisualGenerated` export.

If deterministic audit fails for sparse central motion, static central content, opening motion, cards-only visuals, safe-area intrusion, `agent_visual` compile errors, or `agent_visual` layout errors, regenerate the custom TSX/CSS and rerun the video loop. Do not disable `agent_visual`, switch back to storyboard/cards, or treat caption/progress/fade motion as sufficient.

When reporting visual quality work, name the actual evidence:

- `visual_audit_deterministic.json.motion_check.active_pair_ratio`;
- `visual_audit_deterministic.json.motion_check.max_static_seconds`;
- `visual_audit_deterministic.json.motion_check.opening_active`;
- `render_payload.json.agentVisual.description`.

Stage commands:

```bash
python3 agent_harness/run_agent_loop.py --topic "指定主题" --topic-url "https://..." --topic-summary "可选上下文" --stop-after research_enrichment
python3 agent_harness/run_agent_loop.py "<run_dir>" --mode provider --resume-from 4 --stop-after main_task_plan
python3 agent_harness/run_agent_loop.py "<run_dir>" --mode provider --resume-from 5
SEARCHPO_ENABLE_DAILY_RADAR=1 python3 data_prep/scripts/run_pipeline.py  # legacy source-registry candidate sweep only
python3 agent_harness/run_agent_loop.py --mode provider  # requires explicit run_dir unless SEARCHPO_ENABLE_DAILY_RADAR=1
# DeepSeek/content scoring are normally run by ContentImproveLoopStage.
# The video loop owns render, cover, metadata, deterministic audit, Gemini audit, and final artifact promotion.
python3 scripts/video_quality_loop.py "$(cat runtime/latest_run.txt)" --execution-profile provider --render-mode local --publish-mode contract-check
bash scripts/douyin_upload_check.sh "$(cat runtime/latest_run.txt)"
python3 scripts/finalize_run.py "$(cat runtime/latest_run.txt)" --publish-mode contract-check
```

When the current host actually spawned this implementation agent, pass `--delegation-mode spawned_subagents --delegation-agent searchpo-impl-agent --delegation-proof "<host-subagent-id>"`. If not, leave the default `single_harness` or use `manual_fallback` and report that honestly.

Policy source:

- `config/searchpo_policy.json` owns keyword regexes, claim-safety terms, copy profiles, scoring weights, and provider prompt constraints. Do not add new keyword lists directly inside Python scripts unless the policy loader cannot support the case.
- Storyboard source: `agent_harness/storyboard.py` validates provider/contract storyboards; `src/storyboard.ts` mirrors renderer timing and style-token rules. Keep both in sync when adding scene types.

Resume from failure:

```bash
python3 agent_harness/run_agent_loop.py --mode provider --resume-from 4
```

## Pipeline Stages (provider mode)

1. **LoadSubjectInput** — 加载候选列表或 operator topic
2. **SelectCandidate / ResolveOperatorTopic** — 选择最高分候选或固定用户主题
3. **SubjectEvidence** — owned by `searchpo-research-agent`; 抓取 canonical URL 详情；GitHub repo 必须有 repo API + README
4. **ResearchEnrichment/CrossCheck** — owned by `searchpo-research-agent`; AnySearch supplement、`fact_bank.json`、`research_brief.json`、enriched `evidence_bundle.json` 和 `cross_check_review.json`
5. **PlanContent** — 基于证据摘要生成内容计划
6. **ContentImproveLoop** — DeepSeek V4 Pro 初稿/修订 + Gemini 3.5 Flash 内容评分反馈，直到达到 `content_optimization` target 或明确失败
7. **GeminiTTS** — Gemini 3.1 Flash TTS 语音生成 + 音频标准化
8. **BuildCaptions** — 基于真实音频生成字幕段
9. **Script/ScenePlan** — 从最终 DeepSeek 内容生成 `script.json` 和 `scene_plan.json`
10. **VideoSpec/RenderPayload** — 构建 renderer-neutral `video_spec.json`，再编译 Remotion `render_payload.json`；provider storyboard 优先，否则从兼容 cards 合成默认 storyboard
11. **PublishPackage** — 生成抖音发布包
12. **ContentPreflight** — cross-check + 安全词 + 语义连贯性审查
13. **VideoQualityLoop** — 每轮 render + metadata + deterministic audit + Gemini visual audit；只 promotion 通过的 attempt
14. **FinalizeRun** — main agent 写入 `release_gate.json` 和 `delivery_package.json`，再写 `run_final.json` 作为最终 truth

## Rules

- Do not print secrets from `.env`.
- Do not fabricate evidence bundles or cross-check results. Missing URL, unreadable canonical URL, missing GitHub README/API evidence, or failed cross-check means fail.
- Do not fabricate DeepSeek or Gemini outputs.
- Do not fabricate audio, captions, visual audit evidence, remote publish identity, or media-tool results. Missing dependency means fail.
- If a provider fails, the retry mechanism (3× exponential backoff) will handle transient errors. Hard failures are preserved in run artifacts.
- In provider/lambda/live profiles, `content_score.json` with `verdict=improve` must feed a DeepSeek revision attempt through `content_optimization_loop.json`; do not proceed to TTS/render until the configured target is met.
- Contract runs have `render_mode=none` and must stop before media. Use local render only when `SEARCHPO_REMOTION_RENDER_MODE=local` is set in provider mode; otherwise follow the Lambda path.
- Do not set `SEARCHPO_DOUYIN_LIVE=1` unless the user explicitly requested a live publish for the current run; prefer `npm run e2e:live`.
- After render, `scripts/video_quality_loop.py` must keep failed attempts under `optimization/video/attempt-XX/`; only a passing attempt may call `scripts/finalize_artifacts.py` to bind `video/final.mp4` and `cover/final.jpg`.
- In the video loop, deterministic audit runs before Gemini audit and must fail on missing ffmpeg/tesseract, invalid captions, black frames, or silent provider audio.
- The publish gate verifies the actual upload result JSON; live mode treats `submitted` as intermediate and requires remote identity in `post_publish_verification.json`.
