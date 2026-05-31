# searchpo

## Search Sources

| Priority | Source | What It Finds | Method | Endpoint |
| --- | --- | --- | --- | --- |
| P0 | GitHub Trending | fresh OSS repos and repo metrics | HTML + optional Search API secondary source | `https://github.com/trending` |
| P0 | Hacker News Algolia | developer discussion, objections, early adoption | JSON API | `https://hn.algolia.com/api/v1/search_by_date` |
| P0 | Product Hunt | new AI/SaaS/tool launches | Atom feed | `https://www.producthunt.com/feed` |
| P0 | Hugging Face | models, datasets, Spaces | JSON API | `https://huggingface.co/api/models` |
| P0 | arXiv AI / ML / CL | fresh research papers | Atom API | `https://export.arxiv.org/api/query` |
| P1 | V2EX | Chinese developer pain and reactions | JSON API | `https://www.v2ex.com/api/topics/hot.json` |
| P1 | 36Kr | Chinese tech/business context | RSS feed | `https://36kr.com/feed` |

Backlog sources: Juejin, Zhihu, Bilibili, Linux.do, WaytoAGI, X/Twitter. Reddit is paused until API access is approved.

## Purpose

`searchpo` is a topic/link-driven research-to-video pipeline. The normal useful output starts from an operator-supplied topic or URL, runs widesearch and cross-check, then produces source-bounded content; autonomous daily shortlist selection is currently legacy/opt-in only.

The target candidate has:

- a fresh signal;
- a visible demo or code path;
- a concrete workflow or buyer pain;
- enough evidence for public claims;
- low ad/spam risk.

## Repository Shape

- `data_prep/DATA_PREP.md`: compact source, search, and preprocessing plan.
- `data_prep/source_registry.json`: machine-readable source registry.
- `config/searchpo_policy.json`: central keyword, scoring, claim-safety, and copy policy used by prep, harness, and provider prompts.
- `data_prep/schemas/`: raw item and normalized candidate contracts.
- `data_prep/scripts/probe_sources.py`: endpoint reachability probe.
- `data_prep/scripts/run_pipeline.py`: live source fetch, raw JSONL, normalize, dedupe, and shortlist.
- `agent_harness/core.py`: tracked harness core with SQLite tasks, events, artifacts, and gates.
- `agent_harness/stages.py`: main/research/impl agent flow over shortlist loading, candidate selection, research enrichment, task planning, optional provider stages, render payloads, publishing package, and release gates.
- `agent_harness/research.py`: AnySearch enrichment, FactBank, TopicBrief, and enriched cross-check generation.
- `agent_harness/service_artifacts.py`: local service artifact contracts for TopicBrief, FactBank, Script, ScenePlan, VideoSpec, DeliveryPackage, source maps, environment manifests, and optional analytics feedback.
- `agent_harness/run_agent_loop.py`: CLI entrypoint for the tracked local harness over the shortlist; emits render, post, board, and review artifacts.
- `scripts/deepseek_polish.py`: DeepSeek copy-polish and adaptive-storyboard adapter. Fails fast on missing key/provider error; no placeholder output.
- `scripts/content_scorer.py`: Gemini content evaluator. `improve` now feeds revision attempts instead of being a publish warning.
- `scripts/gemini_tts.py`: Gemini TTS adapter that writes `voiceover.wav` plus a manifest.
- `scripts/video_quality_loop.py`: render/audit/improve loop that retries repairable video issues and only binds a passing attempt.
- `scripts/gemini_visual_audit.py`: Gemini MP4 visual-audit adapter. Its `pass` verdict is required before publish.
- `INSTALL_FOR_AGENTS.md`: concise install and verification protocol for agent hosts.
- `skills/`: project-level agent skills that are the source of truth for both Claude Code and Codex.
- `agents/`: source definitions for the three-agent Claude/Codex team.
- `docs/agent-team-alignment.md`: Claude/Codex agent-team mechanism mapping and Searchpo alignment rules.
- `.claude/skills/`, `.claude/agents/`, `.codex/skills/`, and `.codex/agents/`: generated/project bridge surfaces for the main/research/impl runtime split.
- `agent_harness/storyboard.py` and `src/storyboard.ts`: shared storyboard contract/timing rules for adaptive scene graphs.
- `src/`: Remotion vertical video composition using validated storyboard scenes plus run-scoped props.
- `render/prepare_remotion_input.py`: writes `runtime/.../remotion_input_props.json`, validates/synthesizes `storyboard`, and writes ignored `public/generated/` assets; it does not mutate tracked fixtures.
- `scripts/run_e2e.sh`: profile-driven E2E from source probes through render and Douyin checks.
- `docs/`: production structure, claim governance, runbooks, and env ownership.
- `contracts/schemas/`: JSON contracts for generated payloads and post manifests.

`runtime/` is ignored local runtime state. It currently contains historical `oss_agent_layer`, `multica`, and `social-auto-upload` checkouts/runs. Treat it as operational evidence, not tracked source. The tracked harness now lives under `agent_harness/`; `runtime/oss_agent_layer` remains a historical multi-agent prototype, not the current source of truth.

## Commands

Probe current source availability:

```bash
./data_prep/scripts/probe_sources.py
```

Run the no-provider contract path. This is safe for local wiring checks, but it is not publishable and must not fabricate audio, captions, visual evidence, or publish success.

```bash
npm install
SEARCHPO_TOPIC="topic to investigate" npm run e2e
```

For a publishable local render, use the provider tier:

```bash
SEARCHPO_TOPIC="topic to investigate" npm run e2e:provider
```

The full provider/local path does:

1. `.env` coverage audit without printing secret values.
2. operator topic/link intake. The legacy live source probe/shortlist path runs only when `SEARCHPO_ENABLE_DAILY_RADAR=1`.
3. detailed canonical URL evidence fetch or operator topic seed recording under `evidence_bundle.json`.
4. strategy-selected widesearch/cross-check under `widesearch_strategy.json`, `anysearch_research.json`, and `cross_check_review.json`.
5. provider-mode harness with explicit task board and gates.
6. content improvement loop: DeepSeek draft/revision plus Gemini content score until the policy target is met.
7. full-service planning artifacts: `topic_brief.json`, `fact_bank.json`, `source_map.json`, `script.json`, `scene_plan.json`, `video_spec.json`, `environment_manifest.json`, and optional `analytics_feedback.json`.
8. run-scoped Remotion props under the run directory, including a validated `storyboard` compiled from `video_spec.json` into `render_payload.json`.
9. video quality loop: render, metadata check, deterministic audit, Gemini visual audit, repair/backtrack when allowed.
10. final artifact binding to `runtime/artifacts/<date>/<run_id>/video/final.mp4` and `cover/final.jpg` only after a passing video attempt.
11. manifest-level Douyin contract check with `SEARCHPO_DOUYIN_LIVE=0`.
12. `delivery_package.json` is written before final truth; `run_final.json` is written last.

Explicit higher-side-effect tiers:

```bash
SEARCHPO_TOPIC="topic to investigate" npm run e2e:provider  # DeepSeek + Gemini provider calls, local render, deterministic/model audit, adapter preflight
SEARCHPO_TOPIC="topic to investigate" npm run e2e:lambda    # provider calls plus S3/Lambda render
SEARCHPO_TOPIC="topic to investigate" npm run e2e:live      # provider calls plus S3/Lambda render plus live Douyin upload
```

Side-effect matrix:

| Command | execution_profile | render_mode | publish_mode | Allowed effects | Forbidden effects | Success truth |
| --- | --- | --- | --- | --- | --- | --- |
| `npm run e2e` | `contract` | `none` | `none` | Public-source fetch, ignored `runtime/artifacts/...`, evidence/copy preflight | Provider APIs, media render, AWS/S3, Douyin upload | Cross-check and content preflight pass; no final media, `artifact_manifest.json`, publish check, or `run_final.json` |
| `npm run e2e:provider` | `provider` | `local` | `contract-check` | DeepSeek/Gemini, local Remotion MP4/cover, visual audits, Douyin adapter preflight | AWS/S3 render, live Douyin upload | `artifact_manifest.json`, `run_final.json`, final MP4/cover, audits, and Douyin contract gate pass |
| `npm run e2e:lambda` | `lambda` | `lambda` | `contract-check` | Provider APIs plus Remotion Lambda/S3 render with private output and lifecycle cleanup | Live Douyin upload | Same as provider, with `render_mode=lambda` and fresh Lambda site/render evidence |
| `npm run e2e:live` | `live` | `lambda` | `live` | Provider APIs, Lambda/S3 render, live Douyin upload | Unverified final success labels | Remote identity verification passes; `submitted` alone is failure |

All rows above require `SEARCHPO_TOPIC`, `SEARCHPO_LINK`, or `SEARCHPO_TOPIC_URL` unless `SEARCHPO_ENABLE_DAILY_RADAR=1` is set for the legacy source-registry sweep.

Run individual stages:

```bash
SEARCHPO_ENABLE_DAILY_RADAR=1 python3 data_prep/scripts/run_pipeline.py
SEARCHPO_AGENT_MODE=provider python3 agent_harness/run_agent_loop.py --topic "topic to investigate"
python3 scripts/video_quality_loop.py "$(cat runtime/latest_run.txt)" --execution-profile provider --render-mode local --publish-mode contract-check
npm run douyin:check
python3 scripts/finalize_run.py "$(cat runtime/latest_run.txt)" --publish-mode contract-check
```

Run with an operator-specified topic or link:

```bash
SEARCHPO_TOPIC="Claude Code 多代理工作流怎么拆分职责" \
npm run e2e:provider
```

Run directly from a link. This still pulls detailed source evidence and cross-checks it before copy generation:

```bash
SEARCHPO_LINK="https://github.com/owner/repo" npm run e2e:provider
```

Optional boundaries:

```bash
SEARCHPO_TOPIC="某个你指定的主题" \
SEARCHPO_TOPIC_SUMMARY="你希望它重点分析的上下文" \
SEARCHPO_TOPIC_URL="https://example.com/source-or-brief" \
npm run e2e:provider
```

Topic contract mode skips source probing and shortlist generation, writes `subject_request.json`, records the topic as a research seed, runs widesearch/cross-check, and runs the no-provider text preflight/post-package structure checks only. Use `SEARCHPO_TOPIC="..." npm run e2e:provider` for topic-first widesearch, or add `SEARCHPO_TOPIC_URL`/`SEARCHPO_LINK` when you already know the canonical source boundary. Without `SEARCHPO_TOPIC`, `SEARCHPO_LINK`, or `SEARCHPO_TOPIC_URL`, E2E refuses to run unless `SEARCHPO_ENABLE_DAILY_RADAR=1` is explicitly set.

The tracked harness writes these per-run files under `runtime/artifacts/YYYY-MM-DD/<run_id>/`:

- `harness_board.sqlite3`: task board with stage tasks, events, artifacts, and gates.
- `agent_run.json`: harness loop summary plus board snapshot, including `subject_input_mode`.
- `evidence_bundle.json`: fetched source details from the canonical URL plus AnySearch supplemental extracts; GitHub repo runs require repo API and README evidence.
- `widesearch_strategy.json`: selected search strategy, subject kind, source buckets, query plan, provider hints, and docs probing ladder.
- `anysearch_research.json`, `topic_brief.json`, `fact_bank.json`, `source_map.json`, and `research_brief.json`: research enrichment outputs required before content planning; `research_brief.json` is a compatibility view of `topic_brief.json`.
- `cross_check_review.json`: structured source-bound content review, source facts, caveats, constructive angles, and research sufficiency.
- Contract mode writes `selected_candidate.json`, `content_plan.json`, `main_task_plan.json`, `agent_review.json`, `evidence_bundle.json`, `widesearch_strategy.json`, `anysearch_research.json`, `fact_bank.json`, `research_brief.json`, `cross_check_review.json`, and `post/claims_ledger.json`; it does not write final media, `artifact_manifest.json`, or `run_final.json`.
- Provider/live modes write `artifact_manifest.json`: final MP4/cover/render/caption/audio hashes.
- Provider/live modes write `run_final.json`: final source of truth written after render, audit, and publish checks.
- Provider/live modes also write `script.json`, `scene_plan.json`, `video_spec.json`, `render_payload.json`, and `delivery_package.json`; `video_spec.json` is the renderer-neutral contract, `render_payload.json` is the Remotion adapter output, and `cards` remains a compatibility field.
- Provider profiles also write `content_optimization_loop.json`, `deepseek_polish.json`, `content_score.json`, `voiceover_manifest.json`, `caption_audit.json`, `video_optimization_loop.json`, `visual_audit_deterministic.json`, and `gemini_visual_audit.json`.
- `video/final.mp4` and `cover/final.jpg`: the only publishable media paths. `out/` files are previews only.
- `post/`: Douyin contract-check package, claim ledger, and cross-check review.

This is still a synchronous local harness, but the ownership model is explicit: the main agent owns task-plan state and release gates, the research agent owns source enrichment and cross-check evidence, and the implementation agent runs scripts, Remotion, audit, and publish adapters. Project skills under `skills/` encode that split for Claude Code and Codex agent-team runs.

Validate static contracts and safe command wiring:

```bash
npm run ci:static
```

## Agent Skills Runtime

The intended agent-team shape is:

- `searchpo-main-agent`: assigns tasks, owns `main_task_plan.json`, validates gates, and decides whether publish may proceed.
- `searchpo-research-agent`: runs AnySearch enrichment, writes `fact_bank.json` and `research_brief.json`, and strengthens `cross_check_review.json`.
- `searchpo-impl-agent`: runs the content improve loop, `scripts/gemini_tts.py`, `scripts/video_quality_loop.py`, and `scripts/douyin_upload_check.sh`. DeepSeek belongs to this implementation agent.
- `remotion-best-practices`: governs storyboard scene blocks, captions, cover output, render metadata, and video-quality edits.
- `searchpo-plugin-check`: validates the Claude/Codex bridge map, resolver shared deps, skill/command/agent metadata, and bridge sync.

Project instructions live in `AGENTS.md`, `CLAUDE.md`, `INSTALL_FOR_AGENTS.md`, `skills/`, `commands/`, `agents/`, `.claude/skills/`, `.claude/commands/`, `.claude/agents/`, `.codex/skills/`, `.codex/commands/`, and `.codex/agents/`. The durable skill source is `skills/`; the durable slash-command source is `commands/`; the durable agent-team source is `agents/`. Regenerate host bridges with:

```bash
npm run skills:sync
npm run agent-plugin:check
npm run skills:check
```

`skills/RESOLVER.md` is the short dispatcher. `skills/_AGENT_README.md` is the skill-directory contract. Both are copied into the Claude and Codex project bridge directories by `npm run skills:sync`.

From Claude Code or Codex, run:

```text
/searchpo-full-flow
```

Codex skill pickers that do not show slash commands should use the `Searchpo Full Flow` skill, which wraps the same provider/live command contract.

`npm run skills:sync:codex` installs user-level Codex skill symlinks under `~/.codex/skills/searchpo-*`, writes `~/.codex/agents/searchpo-*.toml`, and refreshes `.codex/commands/searchpo-full-flow.md` plus `.codex/agents/searchpo-*.toml` inside this project.

If the user says `发抖音`, `发布`, `live`, or `post --live`, `/searchpo-full-flow` runs `npm run e2e:live`; otherwise it runs `npm run e2e:provider` for a publishable local render. Always pass `SEARCHPO_TOPIC`, `SEARCHPO_LINK`, or `SEARCHPO_TOPIC_URL`; use `npm run e2e` only for no-provider contract wiring checks.

Project MCP config lives in `.mcp.json`. DeepWiki is registered there for repository-intelligence work and is wrapped by `skills/searchpo-deepwiki-research/SKILL.md`. Use it to understand GitHub repos, but keep canonical URL/API/README evidence plus AnySearch supplements as the publishable proof chain.

Agents can inspect available providers and keys without exposing secret values:

```bash
npm run agent:capabilities
npm run agent:capabilities:check
```

## API Keys

Current source fetching can run without required API keys. Use existing keys when present:

- GitHub private/public repo access: `GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_PERSONAL_ACCESS_TOKEN`.
- GitLab repo access: `GITLAB_PERSONAL_ACCESS_TOKEN_MAC0107` or `GITLAB_TOKEN`.
- Repository/context services: DeepWiki MCP via `.mcp.json`, plus `SOURCEGRAPH_PAT` and `CONTEXT7_API_KEY` when a workflow needs them.
- Research expansion: `ANYSEARCH_API_KEY`, `EXA_API_KEY`, `FIRECRAWL_API_KEY`, `TINYFISH_API_KEY`, `LIBRARIES_IO_API_KEY`, `PRODUCTHUNT_API_KEY`, `PRODUCTHUNT_API_SECRET`, `PRODUCTHUNT_API_TOKEN`, `HUGGINGFACE_TOKEN`, `REDDIT_CLIENT_ID`, and `REDDIT_CLIENT_SECRET`.
- Gemini calls: use `GOOGLE_AGENT_PLATFORM_API` as the source value and export it as `GOOGLE_API_KEY` for Google AI Platform requests.
- LLM scoring/review: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `XAI_API_KEY`, `GROK_API_KEY`, `KIMI_API_KEY`, `KIMI_CODE_API_KEY`, and `AWS_BEDROCK_API_KEY`.
- Script agents: `DEEPSEEK_API_KEY` for polish, and `GOOGLE_AGENT_PLATFORM_API` or `GOOGLE_API_KEY` for Gemini TTS and visual audit.
- Gemini API mode: `SEARCHPO_GEMINI_API_MODE=vertex_express` for Agent Platform / Vertex keys on `aiplatform.googleapis.com`; use `developer` only for AI Studio keys that can call `generativelanguage.googleapis.com`.
- Social source/distribution keys: `X_CONSUMER_KEY`, `X_CONSUMER_SECRET`, `X_BEARER_TOKEN`, `TWITTERAPI_IO_USER_ID`, `TWITTERAPI_IO_API_KEY`, `BLUESKY_HANDLE`, and `BLUESKY_APP_PASSWORD`.
- Notifications: `SEARCHPO_SLACK_WEBHOOK` and `SEARCHPO_BARK_URL`.

Still optional / only needed later:

- `PRODUCTHUNT_API_TOKEN`: Product Hunt GraphQL metrics beyond the public feed.
- `HUGGINGFACE_TOKEN`: higher Hugging Face quota or gated/private model access.
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`: paused; only use after Reddit API approval.
- `X_BEARER_TOKEN`: X/Twitter backlog source if not using the existing Twitter API provider keys.
- Douyin publishing: `SOCIAL_AUTO_UPLOAD_ROOT`, `SOCIAL_AUTO_UPLOAD_CLI`, `SOCIAL_AUTO_UPLOAD_PYTHON`, and `DOUYIN_ACCOUNT_NAME` or `SOCIAL_UPLOAD_ACCOUNT_NAME`.

For Gemini shell calls:

```bash
export GOOGLE_API_KEY="$GOOGLE_AGENT_PLATFORM_API"
```

The scripts default to the Vertex/Agent Platform host when `GOOGLE_AGENT_PLATFORM_API` is the available key, because some local keys are blocked from the regular Gemini Developer API host.

For images or screenshots, do not give Gemini a private browser URL and expect it to fetch it. Download or capture the image locally, then send bytes as base64 `inline_data`. Private GitHub repo contents require a GitHub token first; Gemini only receives the extracted text/image evidence.

## Remotion Lambda

Recommended production baseline:

- Region: `ap-southeast-1`
- Runtime: `nodejs24.x`
- Memory: `2048MB`
- Ephemeral disk: `10240MB`
- Timeout: `120s`
- CloudWatch log retention: `14 days`
- S3 bucket: one Remotion bucket in the same region
- S3 lifecycle: folder expiry enabled
- Render privacy: default to `private`
- Render cleanup: default `deleteAfter=7-days`

Local `.env` contains the actual Remotion AWS access key, region, Lambda function name, bucket name, privacy, and cleanup defaults.

The Remotion Lambda concurrency quota increase request should target `5000` concurrent executions in the active region.

Lambda commands are explicit because they touch AWS:

```bash
npm run lambda:check   # list deployed Remotion Lambda functions
npm run lambda:site    # upload/update the Remotion site bundle in S3
npm run lambda:render  # invoke Lambda render and download out/searchpo-radar-lambda.mp4
```

The Lambda path maps local `REMOTION_AWS_*` keys to the AWS SDK env names before invoking the official Remotion CLI. The site name defaults to `REMOTION_LAMBDA_SITE_NAME` or `searchpo-radar`, and render commands use the run-scoped props recorded by `render/prepare_remotion_input.py`.
`REMOTION_LAMBDA_CONCURRENCY` defaults to `4` to avoid account-level Lambda rate limits during small E2E renders. Set `SEARCHPO_LAMBDA_FRAMES_PER_LAMBDA` only when you intentionally want frame-count based partitioning; otherwise the Lambda wrapper passes concurrency. `REMOTION_LAMBDA_DELETE_AFTER` is forwarded to both video and cover still renders, and requires folder expiry to be enabled on the bucket.

## Publishing Boundaries

The default publishing path is Douyin via `dreammis/social-auto-upload`, using the ignored local checkout at `runtime/social-auto-upload`. This project only writes the upload package and runs safe preflight checks by default.

`social-auto-upload` has no dry-run upload mode. Its Douyin `upload-video` and `upload-note` commands submit content to Douyin; no `--schedule` means immediate publish, while `--schedule "YYYY-MM-DD HH:MM"` submits scheduled content.

Safe default checks:

```bash
npm run douyin:check
```

This verifies the local checkout, Douyin CLI contract, run-scoped final MP4/cover hashes, upload manifest, and optionally runs `sau douyin check --account <name>` through `SOCIAL_AUTO_UPLOAD_CLI` when `DOUYIN_ACCOUNT_NAME` or `SOCIAL_UPLOAD_ACCOUNT_NAME` is set.

Install or refresh the uploader runtime:

```bash
cd runtime/social-auto-upload
uv venv --python 3.12
uv pip install .
PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright" patchright install chromium
cd ../..
scripts/apply_social_auto_upload_patches.sh
```

Prepare a Douyin account cookie:

```bash
cd runtime/social-auto-upload
.venv/bin/sau douyin login --account <account_name> --headed
.venv/bin/sau douyin check --account <account_name>
```

Live upload is intentionally gated:

```bash
DOUYIN_ACCOUNT_NAME=<account_name> SEARCHPO_DOUYIN_LIVE=1 npm run douyin:upload
```

Run one full live publish from source fetch through Lambda/S3 render and Douyin submit:

```bash
DOUYIN_ACCOUNT_NAME=<account_name> SEARCHPO_TOPIC="topic to investigate" npm run e2e:live
```

Live Douyin upload defaults to headed browser mode so password or risk-control prompts can be handled during submit. Set `SOCIAL_UPLOAD_HEADED=0` only when you know headless publishing works for the account.

`submitted` is only an intermediate adapter result. A live run does not pass until `post/post_publish_verification.json` records remote item identity, status, title, duration, cover evidence, and the local video/cover hashes.

X/Twitter keys remain optional read-source inputs only. They are not the default publishing path.
