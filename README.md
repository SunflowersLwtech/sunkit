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

- `phase1_data_prep/DATA_PREP.md`: compact source, search, and preprocessing plan.
- `phase1_data_prep/source_registry.json`: machine-readable source registry.
- `phase1_data_prep/schemas/`: raw item and normalized candidate contracts.
- `phase1_data_prep/scripts/probe_sources.py`: endpoint reachability probe.

## Commands

Probe current source availability:

```bash
./phase1_data_prep/scripts/probe_sources.py
```

Validate JSON files:

```bash
jq empty phase1_data_prep/source_registry.json phase1_data_prep/schemas/*.json
```

## API Keys

Current MVP source fetching can run without required API keys. Use existing keys when present:

- GitHub private/public repo access: `GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_PERSONAL_ACCESS_TOKEN`.
- Gemini calls: use `GOOGLE_AGENT_PLATFORM_API` as the source value and export it as `GOOGLE_API_KEY` for Google AI Platform requests.
- LLM scoring/review: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, or Gemini via `GOOGLE_AGENT_PLATFORM_API`.

Still optional / only needed later:

- `PRODUCTHUNT_API_TOKEN`: Product Hunt GraphQL metrics beyond the public feed.
- `HUGGINGFACE_TOKEN`: higher Hugging Face quota or gated/private model access.
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`: paused; only use after Reddit API approval.
- `X_BEARER_TOKEN`: X/Twitter backlog source if not using the existing Twitter API provider keys.

For Gemini shell calls:

```bash
export GOOGLE_API_KEY="$GOOGLE_AGENT_PLATFORM_API"
```

For images or screenshots, do not give Gemini a private browser URL and expect it to fetch it. Download or capture the image locally, then send bytes as base64 `inline_data`. Private GitHub repo contents require a GitHub token first; Gemini only receives the extracted text/image evidence.

## Remotion Lambda

Provisioned in AWS account `248108944666`, region `us-east-1`:

- IAM policy: `remotion-lambda-policy`
- IAM role: `remotion-lambda-role`
- IAM user: `remotion-user`
- Lambda function: `remotion-render-4-0-468-mem2048mb-disk2048mb-120sec`
- Runtime: `nodejs24.x`
- Memory: `2048MB`
- Ephemeral disk: `2048MB`
- Timeout: `120s`
- CloudWatch log retention: `14 days`

Local `.env` contains `REMOTION_AWS_ACCESS_KEY_ID`, `REMOTION_AWS_SECRET_ACCESS_KEY`, and `REMOTION_AWS_REGION`.

The Remotion Lambda concurrency quota increase request is open for `5000` concurrent executions.
