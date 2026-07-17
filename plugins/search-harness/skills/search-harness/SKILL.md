---
name: search-harness
description: Domain knowledge for designing a search harness for coding agents — search API landscape, ground-API pipeline/strategy, CLI + skills architecture, and roadmap. Use when discussing search agent infrastructure, choosing search APIs for agents, designing search pipelines, or reviewing the search-harness project direction.
---

# Search Harness — Domain Knowledge Pack

This skill packages the scoping and research documents for a search harness for
coding agents (CLI + skills design). No code yet — this is the reference layer
for decisions, reviews, and onboarding.

## How to use these documents

Read the file that matches the question, in this order of relevance:

| Question | File |
|----------|------|
| What is this domain? Terms, players, accumulated conclusions | `domain-knowledge.md` |
| What are we building and in what order? | `roadmap.md` |
| Which sources/APIs are in scope? | `sources.md` |
| How do we wrap a ground-truth search API? | `ground-api-pipeline.md` |
| Why that strategy? | `ground-api-strategy.md` |
| Raw API documentation for candidate sources | `api-docs/` |

## Ground rules carried over from the project

- Domain knowledge is a reference manual: consult it before re-deriving
  conclusions that are already recorded.
- The roadmap's top priority is "equip every source" — check `roadmap.md`
  before proposing new scope.
