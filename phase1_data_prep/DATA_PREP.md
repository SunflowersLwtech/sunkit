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

Run native trend endpoints first. Use keyword expansion only after the cheap native pull.

Core keyword families:

- Agent/workflow: `AI agent`, `coding agent`, `browser agent`, `MCP`, `workflow automation`, `智能体`, `自动化`.
- OSS/infra: `open source AI`, `local LLM`, `RAG`, `evals`, `observability`, `开源`, `本地大模型`, `知识库`.
- Demo signal: `demo`, `playground`, `try it`, `live preview`, `screenshot`, `video`, `演示`, `试用`.
- Buyer pain: `automate`, `replace`, `faster`, `reduce cost`, `self-hosted`, `降本`, `提效`, `私有化`.
- Commercial context: `SaaS`, `API`, `pricing`, `launch`, `beta`, `融资`, `企业服务`.

For Stage 1 survivors, cross-check the same entity in at least one other source family before using strong claims in content.

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
