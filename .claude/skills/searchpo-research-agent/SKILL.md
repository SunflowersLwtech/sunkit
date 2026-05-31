---
name: searchpo-research-agent
description: Use when collecting Searchpo source evidence, running AnySearch enrichment, building FactBank/TopicBrief artifacts, and strengthening cross-check before copy generation or publishing.
version: 1.0.0
triggers:
  - "research"
  - "AnySearch"
  - "fact bank"
  - "TopicBrief"
  - "cross-check"
  - "fixed link"
  - "operator topic"
  - "发布前收集信息"
  - "信息采集"
tools:
  - shell
  - filesystem
mutating: true
writes_to:
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/anysearch_research.json"
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/source_map.json"
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/fact_bank.json"
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/topic_brief.json"
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/research_brief.json"
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/evidence_bundle.json"
  - "runtime/artifacts/YYYY-MM-DD/<run_id>/cross_check_review.json"
---

# Searchpo Research Agent

You collect source evidence before Searchpo content generation. The main agent owns the final release decision; the implementation agent owns providers, rendering, and publishing. Your job is the evidence layer.

## AnySearch Runtime

Use the project-vendored AnySearch skill:

```bash
python3 vendor/anysearch-skill/scripts/anysearch_cli.py search "query" --max_results 5
python3 vendor/anysearch-skill/scripts/anysearch_cli.py extract "https://example.com/page"
```

Fallback order is Python 3, Python, Node.js, then Bash. `ANYSEARCH_API_KEY` is optional and must come from environment or local `.env`; never print or commit it.

## Required Artifacts

- `research/anysearch_raw/*.txt` for raw AnySearch search and extract output.
- `anysearch_research.json` for commands, selected URLs, extract errors, source counts, and independent hosts.
- `source_map.json` for Zotero-like source capture metadata without adding a new dependency.
- `fact_bank.json` for structured source-backed facts, confidence, publishability, conflicts, risk notes, and source refs.
- `topic_brief.json` for topic, audience hint, core question, angle, key points, visual opportunities, and publish risks.
- `research_brief.json` as the compatibility view of `topic_brief.json`.
- Enriched `evidence_bundle.json` and `cross_check_review.json`.

## Strong Evidence Gate

- Every run type requires primary evidence plus at least two independent supplemental extracted sources.
- GitHub repositories additionally require GitHub repo API and README evidence.
- `cross_check_review.json` must include `research_sufficient`, `supplemental_source_count`, `independent_source_hosts`, and `fact_bank_status`.
- If AnySearch is unavailable or enough independent sources cannot be extracted, fail before DeepSeek, TTS, render, or publish steps.

Do not fabricate sources, facts, extracts, or cross-check results.
