# OSS Radar Phase 1 Data Prep

Date: 2026-05-28  
Source spec: `../oss_radar_eval.agent.final/oss_radar_channel_tech_spec.md`

## Objective

Prepare the first runnable data layer for an OSS / AI-tool radar channel before building the full agent runtime. This phase should produce normalized, deduplicated, score-ready candidates from 5-7 stable sources.

The goal is not to summarize news. The goal is to find daily video candidates with:

- a fresh signal;
- a concrete demo path;
- a clear buyer or workflow pain;
- low factual risk;
- enough source evidence to survive public publishing.

## MVP Source Set

| Priority | Source | Role | Fetch Method | Auth | Current Probe |
| --- | --- | --- | --- | --- | --- |
| P0 | GitHub Trending | OSS project discovery | HTML trending page + GitHub Search API fallback | optional token | reachable |
| P0 | Hacker News | developer discussion and early adoption | Algolia Search API | none | reachable |
| P0 | Product Hunt | new product launches | Atom feed; GraphQL later | none for feed | reachable |
| P0 | Hugging Face | models, datasets, Spaces | public REST API | none for MVP | reachable |
| P0 | arXiv AI / ML / CL | paper-to-product signals | arXiv Atom API | none | reachable |
| P1 | V2EX | Chinese developer discussion | public hot topics JSON API | none | reachable |
| P1 | 36Kr | Chinese tech/business signal | RSS feed | none | reachable |

P0 sources should run every daily scan. P1 sources are included when the target is Chinese-market relevance or when P0 returns fewer than 30 candidates.

## Deliverables In This Folder

- `source_registry.json`: machine-readable source plan for fetcher implementation.
- `search_methods.md`: query strategy, expansion rules, and fallback order.
- `preprocessing_contract.md`: raw-to-normalized pipeline and filtering rules.
- `endpoint_probe_2026-05-28.md`: current endpoint reachability evidence.
- `schemas/raw_item.schema.json`: raw fetcher output contract.
- `schemas/normalized_candidate.schema.json`: downstream candidate contract.
- `scripts/probe_sources.py`: no-dependency source reachability probe.

## Phase 1 Exit Criteria

- Collect at least 30 raw candidates from 5+ sources in one run.
- Normalize every item into `normalized_candidate`.
- Preserve raw source payload paths for audit.
- Dedupe by canonical URL, source-native ID, repository/model/paper ID, and fuzzy title similarity.
- Produce a top-20 score-ready candidate list with source evidence and risk flags.
- Do not send every raw item to an LLM. Only Stage 1 survivors enter semantic scoring.

## Implementation Order

1. Implement raw fetchers from `source_registry.json`.
2. Write raw JSONL per source under `runtime/artifacts/YYYY-MM-DD/<run_id>/raw/`.
3. Normalize into `normalized_candidates.jsonl`.
4. Run exact and fuzzy dedupe.
5. Add Stage 1 heuristic filters: recency, demo signal, source reliability, commercial relevance.
6. Emit `candidate_shortlist.json` for five-dimensional scoring.

## First Practical Rule

Keep data collection deterministic and auditable. LLM judgment starts after normalization, dedupe, and cheap heuristic filtering.

## Useful Command

```bash
./phase1_data_prep/scripts/probe_sources.py
```
