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
- `data_prep/schemas/`: raw item and normalized candidate contracts.
- `data_prep/scripts/probe_sources.py`: endpoint reachability probe.
- `data_prep/scripts/run_pipeline.py`: live source fetch, raw JSONL, normalize, dedupe, and shortlist.
- `agent_harness/run_agent_loop.py`: deterministic local agent loop over the shortlist; emits render and post artifacts.
- `src/`: Remotion vertical video composition driven by `public/searchpo-content.json`.
- `scripts/run_e2e.sh`: no-side-effect E2E from source probes through Douyin upload contract checks.

`runtime/` is ignored local runtime state. It currently contains historical `oss_agent_layer`, `multica`, and `social-auto-upload` checkouts/runs. Treat it as operational evidence, not tracked source.

## Commands

Probe current source availability:

```bash
./data_prep/scripts/probe_sources.py
```

Run the full E2E. By default this uses Remotion Lambda + S3 for rendering and keeps Douyin upload in preflight mode:

```bash
npm install
npm run e2e
```

This does:

1. `.env` coverage audit without printing secret values.
2. live source probe and source fetch.
3. raw/normalized/dedupe/filter/shortlist artifacts under `runtime/artifacts/YYYY-MM-DD/<run_id>/`.
4. local deterministic agent loop.
5. Remotion site upload to S3 and AWS Lambda render download to `out/searchpo-radar-lambda.mp4`.
6. Douyin publishing preflight through `runtime/social-auto-upload` without live upload.

Run individual stages:

```bash
python3 data_prep/scripts/run_pipeline.py
python3 agent_harness/run_agent_loop.py
python3 render/prepare_remotion_input.py
npm run render
npm run douyin:check
```

Use local Remotion rendering only for smoke tests:

```bash
SEARCHPO_REMOTION_RENDER_MODE=local npm run e2e
```

Validate JSON files:

```bash
jq empty data_prep/source_registry.json data_prep/schemas/*.json
```

## API Keys

Current source fetching can run without required API keys. Use existing keys when present:

- GitHub private/public repo access: `GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_PERSONAL_ACCESS_TOKEN`.
- Gemini calls: use `GOOGLE_AGENT_PLATFORM_API` as the source value and export it as `GOOGLE_API_KEY` for Google AI Platform requests.
- LLM scoring/review: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, or Gemini via `GOOGLE_AGENT_PLATFORM_API`.

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

The Lambda path maps local `REMOTION_AWS_*` keys to the AWS SDK env names before invoking the official Remotion CLI. The site name defaults to `REMOTION_LAMBDA_SITE_NAME` or `searchpo-radar`.
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
DOUYIN_ACCOUNT_NAME=<account_name> SEARCHPO_DOUYIN_LIVE=1 npm run e2e
```

Live Douyin upload defaults to headed browser mode so password or risk-control prompts can be handled during submit. Set `SOCIAL_UPLOAD_HEADED=0` only when you know headless publishing works for the account.

X/Twitter keys remain optional read-source inputs only. They are not the default publishing path.
