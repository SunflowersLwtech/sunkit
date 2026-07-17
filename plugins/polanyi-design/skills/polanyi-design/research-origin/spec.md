# Polanyi Enhanced Skill — Live Specification

> Last updated: 2026-04-06
> Status: **Phase 2 — Iterating (target exceeded)**
> Current iteration: **v03 (+39.0% over baseline)**

---

## Mission

Transform enzyme2013's Polanyi role-playing skill into a **cognitive operating system** that produces measurable improvements in AI-assisted:
- Code generation & architecture
- Frontend UI design & layout
- Visual aesthetics & design systems
- Code review & quality judgment

The skill should NOT simulate "what Polanyi would say" — it should encode Polanyi's cognitive patterns as **operational principles** that improve AI output.

## Core Thesis

Polanyi's framework maps directly onto expert software/design practice:

| Polanyi Concept | Software/Design Application |
|-----------------|---------------------------|
| **Subsidiary-Focal Awareness** | Expert developers shift attention between boilerplate (subsidiary) and business logic (focal). Great designers see hierarchy without counting pixels. |
| **From-To Structure** | Architecture is a stack of from-to integrations: from data layer → to domain model → to UI. Each layer is "subsidiary" to the one above. |
| **Indwelling** | Designers "dwell in" design systems — they don't think about spacing values, they feel rhythm. Developers "dwell in" frameworks. |
| **Tacit Pattern Recognition** | "Code smell" = tacit knowledge. "This UI feels off" = tacit gestalt judgment. The skill should articulate the tacit. |
| **Post-Critical Philosophy** | Don't blindly follow best practices (that's "critical" thinking Polanyi rejected). Understand the tacit reasons behind conventions, know when to break them. |
| **Gestalt Integration** | Polanyi drew from Gestalt psychology. UI/UX IS gestalt — figure/ground, proximity, continuity, closure. |

## Folder Structure

```
tacitknowledge/
├── spec.md                 # THIS FILE — Live Specification
├── README.md               # Project index
├── research/               # Background research (completed)
│   ├── 01-bibliography.md
│   ├── 02-intellectual-map.md
│   ├── 03-ai-debate.md
│   ├── 04-web-resources.md
│   └── 05-polanyi-skill-analysis.md
├── polanyi-skill/          # Original repo (reference only)
├── skill/                  # OUR enhanced skill (evolving)
│   ├── SKILL.md            # Main skill definition
│   └── references/         # Supporting material
├── eval/                   # Evaluation framework
│   ├── prompts/            # Test prompts per domain
│   ├── results/            # Per-iteration results
│   └── rubrics/            # Scoring criteria
└── iterations/             # Iteration changelogs
    ├── v01.md
    ├── v02.md
    └── ...
```

## Evaluation Methodology

### Test Domains (5 categories, 3 prompts each = 15 total)

1. **Code Architecture** — System design, abstraction layers, state management
2. **Code Review** — Identify issues, suggest improvements, explain "why"
3. **UI Layout** — Dashboard, landing page, form design
4. **Visual Design** — Color systems, typography, spacing, aesthetics
5. **Design-Code Bridge** — Component API design, design system tokens, responsive strategy

### Scoring Rubric (0-10 per dimension)

| Dimension | Description |
|-----------|-------------|
| **Technical Correctness** | Is the output functionally correct? |
| **Design Quality** | Visual/structural elegance, balance, hierarchy |
| **Depth of Reasoning** | Does it explain the "why" not just "what"? |
| **Actionability** | Can someone directly implement this? |
| **Tacit Articulation** | Does it surface insights an expert "feels" but rarely explains? |

**Total possible per prompt: 50 points**
**Total possible per eval round: 750 points (15 prompts × 50)**

### Eval Process

For each iteration:
1. Sub-agent A (Baseline): responds to all 15 prompts WITHOUT the skill
2. Sub-agent B (Enhanced): responds to all 15 prompts WITH the skill
3. Sub-agent C (Evaluator): scores both A and B blindly
4. Delta = Enhanced score − Baseline score
5. **Target: sustained +15% improvement across all domains**

## Iteration Log

| Version | Date | Focus | Δ Score | Key Change |
|---------|------|-------|---------|------------|
| v00 | 2026-04-06 | Baseline measurement | — | No skill |
| v01 | 2026-04-06 | Core framework (6 lenses) | +9.3% | DR+1.8, TA+2.2, but AC-1.2 |
| v02 | 2026-04-06 | Fix AC regression + calibration | **+22.9%** | AC fixed (+2.6 swing), all dims ≥+1.0 |
| v03 | 2026-04-06 | Knowledge Layer Engine + successors | **+39.0%** | DR+3.0, TA+4.0, first TA=10 |
| ... | ... | ... | ... | ... |

## Completion Criteria

The skill is ready for delivery when:
1. **Sustained +15% improvement** over baseline across all 5 domains
2. **No regression** in technical correctness
3. **Qualitative breakthrough** — at least 3 prompts where the enhanced version produces insights the baseline completely misses
4. **Clean, installable** — single SKILL.md file, no external dependencies
