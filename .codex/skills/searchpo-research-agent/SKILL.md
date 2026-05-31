---
name: searchpo-research-agent
description: Use when collecting Searchpo source evidence, running AnySearch enrichment or DeepWiki repo-context research, building FactBank/TopicBrief artifacts, and strengthening cross-check before copy generation or publishing.
version: 1.0.0
triggers:
  - "research"
  - "AnySearch"
  - "fact bank"
  - "TopicBrief"
  - "cross-check"
  - "fixed link"
  - "operator topic"
  - "DeepWiki"
  - "repo architecture"
  - "发布前收集信息"
  - "信息采集"
tools:
  - shell
  - filesystem
  - mcp__deepwiki.read_wiki_structure
  - mcp__deepwiki.read_wiki_contents
  - mcp__deepwiki.ask_question
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

You collect source evidence before Searchpo content generation. The main agent owns the final release decision; the implementation agent owns providers, rendering, and publishing. Your job is the evidence layer for operator-supplied topics or links.

## AnySearch Runtime

Use the project-vendored AnySearch skill:

```bash
python3 vendor/anysearch-skill/scripts/anysearch_cli.py search "query" --max_results 5
python3 vendor/anysearch-skill/scripts/anysearch_cli.py extract "https://example.com/page"
```

Fallback order is Python 3, Python, Node.js, then Bash. `ANYSEARCH_API_KEY` is optional and must come from environment or local `.env`; never print or commit it.

For topic-only inputs, treat the operator topic as a research seed, not external evidence. Run widesearch queries first, extract independent sources, build `fact_bank.json` and `topic_brief.json`, then let `cross_check_review.json` decide what claims are supported. For fixed links, start with canonical URL detail. For GitHub repo inputs, add GitHub API/README evidence. Also use `skills/searchpo-deepwiki-research/SKILL.md` when DeepWiki MCP is available, but only as supporting repo context after the AnySearch-first evidence path has started. Run `python3 scripts/agent_capabilities.py --profile research --format text` to inspect research keys and MCP status without exposing values. DeepWiki can guide repo understanding, but canonical URL/API/README evidence plus AnySearch supplements remain mandatory.

## Required Artifacts

- `research/anysearch_raw/*.txt` for raw AnySearch search and extract output.
- `widesearch_strategy.json` for selected source buckets, subject kind, query plan, provider hints, and docs probing ladder.
- `anysearch_research.json` for commands, selected URLs, dropped URL reasons, extract errors, source counts, and independent hosts.
- `source_map.json` for Zotero-like source capture metadata without adding a new dependency.
- `fact_bank.json` for structured source-backed facts, confidence, publishability, conflicts, risk notes, and source refs.
- `topic_brief.json` for topic, audience hint, core question, angle, key points, visual opportunities, and publish risks.
- `research_brief.json` as the compatibility view of `topic_brief.json`.
- Enriched `evidence_bundle.json` and `cross_check_review.json`.

## Strong Evidence Gate

- Every run type requires either a canonical primary URL or an operator topic seed, plus at least two independent supplemental extracted sources.
- GitHub repositories additionally require GitHub repo API and README evidence.
- AnySearch search/extract is the supplemental research source of truth; DeepWiki-only notes never satisfy the supplemental source gate.
- Search strategy must be explicit: classify topic/link as operator topic, GitHub repo, API docs, paper, security/package, or generic link; then choose source buckets before extraction.
- For docs/API topics, use the cheap ground-API ladder first: `llms-full.txt`, `llms.txt`, robots-discovered sitemap, root links/Jina, then Firecrawl only as fallback.
- DeepWiki findings can guide source questions, but they are not sufficient evidence for adoption, benchmark, production-readiness, funding, or release claims.
- `cross_check_review.json` must include `research_sufficient`, `supplemental_source_count`, `independent_source_hosts`, and `fact_bank_status`.
- If AnySearch is unavailable or enough independent sources cannot be extracted, fail before DeepSeek, TTS, render, or publish steps.

Do not fabricate sources, facts, extracts, or cross-check results.
