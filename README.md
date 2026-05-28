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

Backlog sources: Juejin, Zhihu, Bilibili, Linux.do, WaytoAGI, Reddit, X/Twitter.

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

Current MVP sources can run without required API keys.

Open first:

- `GITHUB_TOKEN`: recommended for GitHub Search API quota and repo expansion.

Open later only when needed:

- `PRODUCTHUNT_API_TOKEN`: Product Hunt GraphQL metrics beyond the public feed.
- `HUGGINGFACE_TOKEN`: higher API quota or gated/private model access.
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`: Reddit backlog source.
- `X_BEARER_TOKEN`: X/Twitter backlog source.
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`: LLM scoring/review layer.
