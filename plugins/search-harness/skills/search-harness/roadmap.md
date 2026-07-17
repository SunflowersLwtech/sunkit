# Roadmap

> Drafted: 2026-05-02 · Last revised: 2026-05-03 (rewritten in English; Step 1 = "equip every source" promoted to the top)
>
> This file is forward-looking. Anything not listed under **Step 1** is future-track and does not block the current MVP — only the direction is recorded; the detailed design is written when each track actually starts.

---

## Step 1 — Equip every source in `sources.md` with one skill + one executable

This is the only step that is currently being executed. Everything else on this page is parked.

### 1.1 What "equipped" means

For every entry that appears in [`sources.md`](./sources.md) — the 20 Phase-1 adapters in §1, the 4 co-install tools in §2, and the 3 ground-API tools in §3 — the deliverable is a single bundle:

```
.claude/skills/<source>/
├── SKILL.md                  ~80 lines, ~1.5K tokens, default-loaded into the host context
├── references/               progressive disclosure, only read when the host opens them
│   ├── filter-grammar.md
│   ├── field-schema.md
│   └── footguns.md
└── examples/
    └── typical-queries.md

tools/<source>/
├── <verb-1>.sh               thin shell wrapper: parse args → curl → jq → stdout JSON
├── <verb-2>.sh
└── ...                        (one script per discrete operation; see §1.3)
```

The shape is the one already executed for `01-github` (see [`reference/sources/01-github/`](./reference/sources/01-github/)) — that directory is the canonical template. Every other source copies its layout.

### 1.2 Inventory (= scope of Step 1)

The full target list, taken verbatim from [`sources.md`](./sources.md):

**Phase-1 adapters (20)** — `sources.md` §1
1. GitHub · 2. GitLab (multi-instance) · 3. Stack Exchange (multi-site) · 4. HN Algolia ·
5. Reddit · 6. arXiv · 7. OpenAlex · 8. OpenReview · 9. npm · 10. crates.io ·
11. libraries.io · 12. Hugging Face Hub · 13. CVE / NVD · 14. twitterapi.io · 15. OSV.dev ·
16. deps.dev · 17. Lobste.rs · 18. Bluesky (AT-Protocol) · 19. Sourcegraph stream · 20. Exa

**Co-install tools (4)** — `sources.md` §2
- Context7 CLI · Playwright CLI · DeepWiki MCP · yt-dlp

**Ground-API tools (3)** — `sources.md` §3
- Context7 CLI (already counted above; ground-API skill is a thin pointer back to the §2 skill) · Jina Reader · Firecrawl

That is approximately 26 distinct skill+script bundles. Status is tracked per-source under [`reference/sources/<NN>-<name>/`](./reference/sources/).

### 1.3 The cut between adapter wrapper and skill

The split below is the contract every bundle must respect; it is not negotiable per-source.

| Layer | Owns | Does NOT do |
|---|---|---|
| `tools/<source>/*.sh` | Token resolution, URL-encode, `curl`, `jq` projection, stdout JSON, exit-code mapping. **One script per discrete operation.** | No retry beyond 1, no cross-source synthesis, no auto-backfill, no convenience aliases the official docs do not promise. |
| `.claude/skills/<source>/SKILL.md` | When to reach for this source, the CLI signature, one example output JSON, the top footguns, "when NOT to use → switch to which other skill". | Does not reproduce the upstream docs; does not re-explain auth flows the wrapper has already encapsulated. |
| `references/*.md` | Filter grammar, the trimmed field schema (only fields the wrapper actually projects), failure-mode handling. | Same exclusions as SKILL.md. |
| `examples/typical-queries.md` | 5 templated queries that are conceptually runnable today (no empty `q=`, no qualifiers the API will reject). | No demos that depend on a footgun the wrapper does not handle. |

The four anti-patterns enumerated in [`reference/sources/01-github/audit-2026-05-02.md`](./reference/sources/01-github/audit-2026-05-02.md) — inventing wrapper behavior, inventing convenience features, over-engineering retry policy, shipping un-runnable examples — must NOT recur in any new bundle. That audit file is the reference every distillation pass cites at the end of its prompt.

### 1.4 Standard distillation pass per source (the recipe contributors follow)

Each source goes through three sub-passes. They are sequential because pass-2 reads pass-1's output and pass-3 reads pass-2's:

1. **Adapter README** at `reference/sources/<NN>-<name>/README.md` — pin the 6-or-fewer discrete operations, the auth model, the score signals, the footguns, the function I/O contract. (`01-github/README.md` is the worked example.)
2. **Raw evidence** at `reference/sources/<NN>-<name>/raw/` — two files. `openapi-extracted.md` is the verbatim field schema pulled from the upstream OpenAPI / spec file. `docs-extracted.md` is the verbatim footguns / behaviors / examples pulled from the upstream docs pages. **Every line carries a citation; no synthesis.** (`01-github/raw/` is the worked example.)
3. **Skill + scripts** at `.claude/skills/<source>/` and `tools/<source>/` — built against (1) and (2). Any sentence not derivable from those two artifacts is either cited or flagged as a clarification request. Never shipped as fact.

Each sub-pass is a separate agent run with a separate, narrowly scoped prompt. This is what stops the four anti-patterns above from leaking into the next adapter.

### 1.5 Done criteria for Step 1

Step 1 is complete when, for every entry in `sources.md`:

- The bundle exists at the paths in §1.1.
- The skill description triggers on the use cases listed in `sources.md` §1's "用例" column.
- A smoke run of the example queries in `examples/typical-queries.md` returns a 200 against the live API on a clean machine that only has `$XXX_TOKEN` set.
- The cross-source middleware (separate track, recorded in `domain-knowledge.md` §2.11) can fan-out across all bundles and apply RRF + schema unification without per-source hacks.

Step 1 explicitly does NOT include: the cross-source middleware itself (already a separate track), Discussions / Gists (Phase 2), `/search/commits` (Phase 2), GraphQL paths for sources whose REST surface is sufficient.

---

## Contribution model

Outside contributors equip a new source — or close a gap on an existing one — by running the recipe in §1.4 against the upstream's official API documentation. Concretely:

1. Fork the repo, claim the source by opening an issue at `reference/sources/<NN>-<name>/`.
2. Pass 1: write the README using the structure of [`reference/sources/01-github/README.md`](./reference/sources/01-github/README.md). Pin the operations, the auth model, the footguns. Open a PR for review at this stage; do not move on until the README is merged.
3. Pass 2: produce `raw/openapi-extracted.md` and `raw/docs-extracted.md`. Every line cites its source URL and the section title within. No paraphrase, no opinion. The shape and discipline of [`reference/sources/01-github/raw/`](./reference/sources/01-github/raw/) is the standard.
4. Pass 3: build the `SKILL.md`, `references/`, `examples/`, and `tools/<source>/*.sh`. Cite §-numbers from the README the bundle is built against. Report contradictions between the YAML and the prose docs verbatim — do NOT resolve them silently.
5. Read [`reference/sources/01-github/audit-2026-05-02.md`](./reference/sources/01-github/audit-2026-05-02.md) before submitting. Any sentence in your output that makes a claim about wrapper internals, retry budgets, alias logic, or auto-side-effects must either cite the README section it derives from or be flagged in the PR description as a clarification request — never shipped as fact.

The PR is reviewed against (a) the four anti-patterns in the audit file, (b) the contract in §1.3, and (c) the done criteria in §1.5. There is no other contribution path for new sources — adding a wrapper without going through Pass 1 and Pass 2 is the failure mode this recipe exists to prevent.

---

## Long-horizon Track A — agent capabilities (parked)

These three are direction-only. None of them block Step 1 and none of them are scoped yet.

### A1. Local persistence of search results → coding-agent memory + LLM wiki

Persist the valuable search results (snippet + URL + version + metadata) into a local store so the next coding-agent run can reuse them. The same store doubles as long-term memory for the host LLM (relevance-ranked recall) and as a wiki humans can read directly.

**Open**: when to write · who deduplicates · TTL · the boundary between user-private and project-shared content.

### A2. Agent-orchestration skills

When a query is complex enough that it needs grouped fan-out + an intermediate judge + a second pass to backfill, expose orchestration as a **skill the host composes**, not as a graph hard-coded inside the wrapper.

- Take cues from `domain-knowledge.md` §1.1 / §7 (DeerFlow empirical pass).
- The wrapper still owns only single fan-out + RRF + schema unification (the boundary locked in `domain-knowledge.md` §2.11).
- Counter-example to avoid: graph frameworks over-engineered on top of Claude Code (already argued in `domain-knowledge.md` §2.12).

### A3. Native multimodal pass-through plugin

Let the host LLM operate directly on images / video / audio inside search results, instead of falling back to alt-text or transcript-only.

**Hard constraint**: the plugin must NOT lossy-transcode anything before handing it to the host — the wrapper is a pass-through to the host's native vision API. Multimodal signal taxonomy is in `domain-knowledge.md` §2.4.

---

## Long-horizon Track B — large co-install candidates (parked)

Two project-sized engineering efforts. Each is high-value if shipped, but neither is bundled with the MVP. They live as opt-in co-installs.

### B1. Code-level context engine for the user's own repos

Build a semantic + symbol + topology search index over the **user's local / private codebase** — effectively a small self-hosted Sourcegraph.

- Complementary to `sources.md` §1 #19 Sourcegraph: SG only reaches public OSS; B1 is the only way to query the user's own monorepo.
- Tech base: SCIP indexer / zoekt (both OSS, both self-hostable).
- Hard parts: indexer maturity varies wildly per language (`domain-knowledge.md` §9.2.4); incremental indexing + file watcher + IDE integration; the boundary against LSP / tree-sitter / ast-grep.

### B2. Computer-Use Agent for end-to-end test + content acquisition (CLI + Browser + GUI)

Let the search-agent drive OS-level interaction directly to fetch / verify content the API+scraper layer can't reach.

| Layer | Today | Gap |
|---|---|---|
| **CLI** | Partially covered by `sources.md` §2 — Playwright CLI / yt-dlp / `gh` / Context7 CLI. | No coordination skill yet. |
| **Browser** | Playwright / Firecrawl (`sources.md` §1.4) cover scripted flows. | Real CUA = the model directly looking at screenshots and clicking, not predefined scripts. |
| **GUI** | Empty. | OS-native windows, persistent login state, mouse/keyboard interaction with private surfaces (LinkedIn, internal wikis, desktop apps). |

**Core scenarios**: drive an API end-to-end and screenshot-verify it · scrape sites with hard anti-bot · prove an SDK example actually runs.

**Hard parts**: vision + action loop is still slow and expensive (Claude Computer Use / OpenAI Operator are early); the security model is brutal (full OS control = full attack surface); cross-OS / cross-resolution robustness is entirely on the LLM.

---

## Cross-references

- [`domain-knowledge.md`](./domain-knowledge.md) — every locked judgment and empirical result (§1–§9).
- [`sources.md`](./sources.md) — the Phase-1 source inventory (20 ★ adapters + co-install + ground-API).
- [`reference/sources/01-github/`](./reference/sources/01-github/) — the canonical worked example for Step 1's three sub-passes (README → `raw/` → `skill-draft/`).
- [`reference/sources/01-github/audit-2026-05-02.md`](./reference/sources/01-github/audit-2026-05-02.md) — the four anti-patterns every distillation pass must defend against.
