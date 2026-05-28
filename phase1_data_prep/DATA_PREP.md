# Phase 1 Data Prep

## Search Sources

| Priority | Source | Role | Method | Auth |
| --- | --- | --- | --- | --- |
| P0 | GitHub Trending | OSS project discovery | HTML + optional Search API fallback | optional token |
| P0 | Hacker News Algolia | developer discussion and adoption signal | JSON API | none |
| P0 | Product Hunt | product launch discovery | Atom feed | none for feed |
| P0 | Hugging Face | model, dataset, and Space trends | JSON API | none for MVP |
| P0 | arXiv AI / ML / CL | paper-to-product signals | Atom API | none |
| P1 | V2EX | Chinese developer pain and reactions | JSON API | none |
| P1 | 36Kr | Chinese tech/business context | RSS feed | none |

## Search Method

Run in three passes. The first pass is cheap and deterministic; the second pass expands only where native results are thin; the third pass validates entities that could become publishable claims.

### Pass 1: Native Pull

Always run these first:

- GitHub Trending daily.
- HN Algolia latest stories for core keyword groups.
- Product Hunt feed.
- Hugging Face `sort=likes` and `sort=lastModified`.
- arXiv latest `cs.AI`, `cs.LG`, `cs.CL`, `cs.CV`.
- V2EX hot topics.
- 36Kr feed.

Target: collect 50-100 raw items, then normalize and dedupe before any LLM call.

### Pass 2: Query Expansion

Run expansion only if fewer than 30 normalized candidates survive Pass 1, or if a topic family is missing from the daily pool.

| Family | Queries | Why |
| --- | --- | --- |
| Agent/workflow | `AI agent`, `coding agent`, `browser agent`, `MCP`, `workflow automation`, `智能体`, `自动化` | Finds agent products and automation repos |
| OSS/infra | `open source AI`, `local LLM`, `RAG`, `evals`, `observability`, `开源`, `本地大模型`, `知识库` | Finds buildable infra and developer tools |
| Demo signal | `demo`, `playground`, `try it`, `live preview`, `screenshot`, `video`, `演示`, `试用` | Raises short-video feasibility |
| Buyer pain | `automate`, `replace`, `faster`, `reduce cost`, `self-hosted`, `降本`, `提效`, `私有化` | Finds concrete workflow problems |
| Commercial context | `SaaS`, `API`, `pricing`, `launch`, `beta`, `融资`, `企业服务` | Maps buyer category and ad proximity |

### Source-Specific Expansion

- GitHub: expand by topics `ai`, `agents`, `llm`, `mcp`, `rag`, plus phrase search for `browser agent`, `coding agent`, `workflow automation`; fetch README only for Stage 1 survivors.
- HN: prioritize `Show HN`, `Launch HN`, high-comment discussions, and links that point to GitHub/Product Hunt/Hugging Face.
- Product Hunt: use the feed first; use `PRODUCTHUNT_API_TOKEN` later for GraphQL metrics and category detail.
- Hugging Face: search `agent`, `voice`, `video`, `rag`, `code`, and prefer items with Spaces, examples, model cards, or recent activity.
- arXiv: query latest category feeds first; downrank papers without code, demo, project page, or public model link.
- V2EX: use hot topics as pain/discussion signal; favor questions, complaints, tool replacement, and self-hosting threads.
- 36Kr: use as business/funding context; all funding, customer, and market-size claims require verification.

### Pass 3: Cross-Source Validation

For each Stage 1 survivor, create entity keys and search for corroboration:

- repo: `owner/repo`, repo name, homepage domain;
- product: product name, slug, domain;
- model: `author/model`, model family, linked paper;
- paper: arXiv ID, title noun phrases, project/code link;
- discussion/article: canonical URL domain and title hash.

Before a candidate can enter content scripting, require at least one of:

- official source plus independent discussion;
- source-native metrics plus a demo/code artifact;
- product launch plus public homepage/pricing/docs;
- paper plus code/model/demo link.

Do not use Reddit in Phase 1. It stays paused until approved API access exists.

### Stop Rules

Stop expanding when any one condition is true:

- 100 raw items collected;
- 30 normalized candidates survive cheap filters;
- top 20 shortlist covers at least 4 source families;
- expansion adds fewer than 3 new candidates after a full query family.

## Raw Output

Write raw records before transformation:

```text
runtime/artifacts/YYYY-MM-DD/<run_id>/raw/<source>.jsonl
```

Each raw item must include:

- `source`
- `source_item_id`
- `url`
- `title`
- `summary`
- `published_at`
- `collected_at`
- `metrics`
- `raw`

## Normalization

Normalize raw items into `normalized_candidates.jsonl`.

Required candidate fields:

- `candidate_id`
- `entity_type`
- `entity_key`
- `canonical_url`
- `title`
- `summary`
- `source_ids`
- `evidence`
- `metrics`
- `signals`
- `risk_flags`

Entity keys should be deterministic:

- GitHub: `repo:{owner}/{repo}`
- Hugging Face: `model:{author}/{model}`
- arXiv: `paper:arxiv:{id}`
- Product/site: `product:{domain}`
- Discussion/article: `web:{domain}:{title_hash}`

## Dedupe

Merge exactly on canonical URL, repo full name, model ID, arXiv ID, or source-native stable ID.

Use fuzzy merge only when titles are strongly similar:

- token Jaccard >= `0.82`; or
- character 3-gram Jaccard >= `0.78`; or
- title similarity >= `0.72` and domains match.

Do not merge items that only share generic terms such as `AI agent`, `LLM`, `RAG`, or `open source`.

## Stage 1 Filter

Compute cheap signals before LLM scoring:

- freshness hours;
- demo keyword;
- code or product artifact;
- buyer/pain keyword;
- ad language density;
- source count;
- source-relative engagement.

Reject before LLM scoring when:

- no URL;
- older than 30 days without fresh cross-source validation;
- generic title;
- pure job listing, coupon, press release, or ad copy;
- no demo, code, product, model, paper, or discussion artifact.

Keep but flag when:

- strong metrics but no demo;
- launch copy has no independent discussion;
- funding/customer claims need verification;
- source is community-only;
- login is required.

## Output

Phase 1 should emit:

- `normalized_candidates.jsonl`
- `dedupe_clusters.json`
- `stage1_filter_report.json`
- `candidate_shortlist.json`

The shortlist should contain at most 20 items. Only those items enter five-dimensional scoring.

## Probe

Run:

```bash
./phase1_data_prep/scripts/probe_sources.py
```

Latest local check on 2026-05-28: all seven MVP sources returned `200`.
