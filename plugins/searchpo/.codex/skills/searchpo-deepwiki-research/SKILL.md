---
name: searchpo-deepwiki-research
description: Use when a Searchpo task involves GitHub repository understanding, DeepWiki MCP, repo architecture questions, dependency exploration, or source-code context as supporting context after AnySearch-first evidence planning has started.
version: 1.0.0
triggers:
  - "DeepWiki"
  - "deepwiki"
  - "MCP repo research"
  - "repo architecture"
  - "GitHub repository understanding"
  - "source-code context"
  - "代码库理解"
tools:
  - mcp__deepwiki.read_wiki_structure
  - mcp__deepwiki.read_wiki_contents
  - mcp__deepwiki.ask_question
  - shell
  - filesystem
mutating: false
---

# Searchpo DeepWiki Research

Use this skill for repo-focused context collection. DeepWiki is a supporting repository-intelligence surface, not a replacement for Searchpo canonical evidence or AnySearch supplemental research.

## MCP Setup

- Project MCP config lives in `.mcp.json` and declares `deepwiki` as `https://mcp.deepwiki.com/mcp`.
- Codex can use `mcp__deepwiki.read_wiki_structure`, `mcp__deepwiki.read_wiki_contents`, and `mcp__deepwiki.ask_question` when those tools are available.
- Claude Code tool names are usually `mcp__deepwiki__read_wiki_structure`, `mcp__deepwiki__read_wiki_contents`, and `mcp__deepwiki__ask_question`.
- Do not call DeepWiki `generate_wiki` unless the user explicitly asks to generate a wiki.

## Workflow

1. Confirm the input is a GitHub repo URL or `owner/repo`.
2. Confirm `searchpo-research-agent` has started the AnySearch-first evidence path: canonical URL detail, GitHub API/README evidence, and AnySearch search/extract planning. If not, return to `searchpo-research-agent` first.
3. Run `python3 scripts/agent_capabilities.py --profile repo --format text` to verify MCP/key availability without printing secrets.
4. Use DeepWiki in this order:
   - `read_wiki_structure` to find topic areas.
   - `read_wiki_contents` when full repo documentation is useful and concise enough.
   - `ask_question` for targeted questions such as architecture, CLI entrypoint, render path, API boundary, or safety model.
5. If DeepWiki reports that the repository is not indexed or not found, record that and continue with GitHub API/README plus AnySearch. Do not block the run only because DeepWiki lacks a wiki.
6. Cross-check DeepWiki findings against Searchpo evidence requirements:
   - canonical URL detail fetch,
   - GitHub API metadata and README evidence for GitHub repos,
   - at least two independent supplemental AnySearch extracts,
   - `fact_bank.json`, `topic_brief.json`, and `cross_check_review.json`.
7. Store conclusions only in run-scoped artifacts or final analysis; never write `.env` values.

## Claim Boundary

- DeepWiki can explain code structure, likely module responsibilities, and repo-level architecture.
- DeepWiki cannot be the first or only completed research step for a Searchpo full-flow run.
- Do not use DeepWiki alone for adoption, benchmark rank, funding, production maturity, security posture, or release-status claims.
- If DeepWiki conflicts with canonical URL/API/README evidence, prefer the canonical evidence and record the conflict in FactBank risk notes.
