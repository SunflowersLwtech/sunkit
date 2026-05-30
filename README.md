# searchpo

## Search Sources

| Priority | Source | What It Finds | Method | Endpoint |
| --- | --- | --- | --- | --- |
| P0 | GitHub Trending | fresh OSS repos and repo metrics | HTML + optional Search API fallback | `https://github.com/trending` |
| P0 | Hacker News Algolia | developer discussion, objections, early adoption | JSON API | `https://hn.algolia.com/api/v1/search_by_date` |
| P0 | Product Hunt | new AI/SaaS/tool launches | Atom feed | `https://www.producthunt.com/feed` |
| P0 | Hugging Face | models, datasets, Spaces | JSON API | `https://huggingface.co/api/models` |
| P0 | arXiv AI / ML / CL | fresh research papers | Atom API | `https://export.arxiv.org/api/query` |
| P1 | V2EX | Chinese developer pain and reactions | JSON API | `https://www.v2ex.com/api/topics/hot.json` |
| P1 | 36Kr | Chinese tech/business context | RSS feed | `https://36kr.com/feed` |

Backlog sources: Juejin, Zhihu, Bilibili, Linux.do, WaytoAGI, X/Twitter. Reddit is paused until API access is approved.

## Purpose

`searchpo` is the data-prep layer for an OSS / AI-tool radar. The first useful output is a daily shortlist of score-ready candidates, not a generic news digest.

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
- `agent_harness/stages.py`: main/impl agent flow over shortlist loading, candidate selection, task planning, optional provider stages, render payloads, publishing package, and release gates.
- `agent_harness/run_agent_loop.py`: CLI entrypoint for the tracked local harness over the shortlist; emits render, post, board, and review artifacts.
- `scripts/deepseek_polish.py`: DeepSeek copy-polish adapter. Fails fast on missing key/provider error; no placeholder output.
- `scripts/gemini_tts.py`: Gemini TTS adapter that writes `voiceover.wav` plus a manifest.
- `scripts/gemini_visual_audit.py`: Gemini MP4 visual-audit adapter. Its `pass` verdict is required before publish.
- `openclaw.plugin.json`: plugin-style bundle manifest for agent hosts.
- `INSTALL_FOR_AGENTS.md`: concise install and verification protocol for agent hosts.
- `skills/`: project-level agent skills that are the source of truth for both Claude Code and Codex.
- `.claude/skills/`, `.claude/agents/`, and `.codex/skills/`: generated/project bridge surfaces for the main/impl runtime split.
- `src/`: Remotion vertical video composition using tracked fixture defaults plus run-scoped props.
- `render/prepare_remotion_input.py`: writes `runtime/.../remotion_input_props.json` and ignored `public/generated/` assets; it does not mutate tracked fixtures.
- `scripts/run_e2e.sh`: profile-driven E2E from source probes through render and Douyin checks.
- `docs/`: production structure, claim governance, runbooks, and env ownership.
- `contracts/schemas/`: JSON contracts for generated payloads and post manifests.

`runtime/` is ignored local runtime state. It currently contains historical `oss_agent_layer`, `multica`, and `social-auto-upload` checkouts/runs. Treat it as operational evidence, not tracked source. The tracked harness now lives under `agent_harness/`; `runtime/oss_agent_layer` remains a historical multi-agent prototype, not the current source of truth.

## Commands

Probe current source availability:

```bash
./data_prep/scripts/probe_sources.py
```

Run the safe local E2E. This is the default production contract check: no DeepSeek/Gemini provider calls, no AWS/S3/Lambda, and no live Douyin upload.

```bash
npm install
npm run e2e
```

This does:

1. `.env` coverage audit without printing secret values.
2. live source probe and source fetch.
3. raw/normalized/dedupe/filter/shortlist artifacts under `runtime/artifacts/YYYY-MM-DD/<run_id>/`.
4. local contract-mode harness with explicit task board and gates.
5. run-scoped Remotion props under the run directory.
6. local Remotion render to `out/searchpo-radar.mp4`.
7. manifest-level Douyin contract check with `SEARCHPO_DOUYIN_LIVE=0`.

Explicit higher-side-effect tiers:

```bash
npm run e2e:provider  # DeepSeek + Gemini provider calls, local render, adapter preflight
npm run e2e:lambda    # provider calls plus S3/Lambda render
npm run e2e:live      # provider calls plus S3/Lambda render plus live Douyin upload
```

Run individual stages:

```bash
python3 data_prep/scripts/run_pipeline.py
SEARCHPO_AGENT_MODE=contract python3 agent_harness/run_agent_loop.py
python3 render/prepare_remotion_input.py
npm run render:run
python3 scripts/gemini_visual_audit.py "$(cat runtime/latest_run.txt)" --video out/searchpo-radar.mp4
npm run douyin:check
```

Run with an operator-specified topic instead of the daily source radar selecting a candidate:

```bash
SEARCHPO_TOPIC="Claude Code 多代理工作流怎么拆分职责" npm run e2e:topic
```

Optional boundaries:

```bash
SEARCHPO_TOPIC="某个你指定的主题" \
SEARCHPO_TOPIC_SUMMARY="你希望它重点分析的上下文" \
SEARCHPO_TOPIC_URL="https://example.com/source-or-brief" \
npm run e2e:topic
```

Topic mode skips source probing and shortlist generation, writes `subject_request.json`, then reuses the same harness, Remotion, visual-audit, and Douyin gate path. Without `SEARCHPO_TOPIC_URL`, the claim ledger marks the run as an operator-topic analysis and keeps factual claims conditional.

The tracked harness writes these per-run files under `runtime/artifacts/YYYY-MM-DD/<run_id>/`:

- `harness_board.sqlite3`: task board with stage tasks, events, artifacts, and gates.
- `agent_run.json`: run summary plus board snapshot, including `subject_input_mode`.
- `selected_candidate.json`, `content_plan.json`, `main_task_plan.json`, `render_payload.json`, `agent_review.json`.
- Provider profiles also write `deepseek_polish.json`, `voiceover_manifest.json`, and `gemini_visual_audit.json`.
- `post/`: Douyin contract-check package, claim ledger, and cross-check review.

This is still a synchronous local harness, but the ownership model is explicit: the main agent owns task-plan state and release gates, while the implementation agent runs scripts, Remotion, audit, and publish adapters. Project skills under `skills/` encode that split for Claude Code and Codex agent-team runs.

Validate static contracts and safe command wiring:

```bash
npm run ci:static
```

## Agent Skills Runtime

The intended agent-team shape is:

- `searchpo-main-agent`: assigns tasks, owns `main_task_plan.json`, validates gates, and decides whether publish may proceed.
- `searchpo-impl-agent`: runs `scripts/deepseek_polish.py`, `scripts/gemini_tts.py`, Remotion render commands, `scripts/gemini_visual_audit.py`, and `scripts/douyin_upload_check.sh`.
- `remotion-best-practices`: governs Remotion composition, captions, cover output, render metadata, and video-quality edits.
- `searchpo-plugin-check`: validates the plugin manifest, resolver shared deps, skill metadata, and bridge sync.

Project instructions live in `AGENTS.md`, `CLAUDE.md`, `openclaw.plugin.json`, `INSTALL_FOR_AGENTS.md`, `skills/`, `.claude/skills/`, `.codex/skills/`, and `.claude/agents/searchpo-impl-agent.md`. The durable skill source is `skills/`; regenerate host bridges with:

```bash
npm run skills:sync
npm run agent-plugin:check
npm run skills:check
```

`skills/RESOLVER.md` is the short dispatcher. `skills/_AGENT_README.md` is the skill-directory contract. Both are copied into the Claude and Codex project bridge directories by `npm run skills:sync`.

From Claude Code, run:

```text
/searchpo-full-flow
```

From Codex, ask for the `searchpo-main-agent` flow or open `skills/searchpo-main-agent/SKILL.md` if the active session has not loaded the project skill registry yet. `npm run skills:sync:codex` installs user-level Codex symlinks under `~/.codex/skills/searchpo-*` for future sessions.

If the user says `发抖音`, `发布`, `live`, or `post --live`, the Claude Code flow should run `npm run e2e:live`; otherwise it stays in contract-check mode.

## API Keys

Current source fetching can run without required API keys. Use existing keys when present:

- GitHub private/public repo access: `GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_PERSONAL_ACCESS_TOKEN`.
- Gemini calls: use `GOOGLE_AGENT_PLATFORM_API` as the source value and export it as `GOOGLE_API_KEY` for Google AI Platform requests.
- LLM scoring/review: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `XAI_API_KEY`.
- Script agents: `DEEPSEEK_API_KEY` for polish, and `GOOGLE_AGENT_PLATFORM_API` or `GOOGLE_API_KEY` for Gemini TTS and visual audit.
- Gemini API mode: `SEARCHPO_GEMINI_API_MODE=vertex_express` for Agent Platform / Vertex keys on `aiplatform.googleapis.com`; use `developer` only for AI Studio keys that can call `generativelanguage.googleapis.com`.

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
`REMOTION_LAMBDA_CONCURRENCY` defaults to `4` to avoid account-level Lambda rate limits during small E2E renders.

## Publishing Boundaries

The default publishing path is Douyin via `dreammis/social-auto-upload`, using the ignored local checkout at `runtime/social-auto-upload`. This project only writes the upload package and runs safe preflight checks by default.

`social-auto-upload` has no dry-run upload mode. Its Douyin `upload-video` and `upload-note` commands submit content to Douyin; no `--schedule` means immediate publish, while `--schedule "YYYY-MM-DD HH:MM"` submits scheduled content.

Safe default checks:

```bash
npm run douyin:check
```

This verifies the local checkout, Douyin CLI contract, rendered MP4, upload manifest, and optionally runs `sau douyin check --account <name>` through `SOCIAL_AUTO_UPLOAD_CLI` when `DOUYIN_ACCOUNT_NAME` or `SOCIAL_UPLOAD_ACCOUNT_NAME` is set.

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
DOUYIN_ACCOUNT_NAME=<account_name> npm run e2e:live
```

Live Douyin upload defaults to headed browser mode so password or risk-control prompts can be handled during submit. Set `SOCIAL_UPLOAD_HEADED=0` only when you know headless publishing works for the account.

X/Twitter keys remain optional read-source inputs only. They are not the default publishing path.
