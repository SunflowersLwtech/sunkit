# show-me

Delivery discipline for anything you show another person — diagrams, illustrated pages,
write-ups, reports. The information lives on the canvas; prose only carries what the
diagram cannot. Part of [sunkit](../../README.md).

The skill is written in Chinese (its trigger words included); it fires on asks like
「画个图」「画一下这个系统的架构」「把这个整理成材料给团队看」 as well as "show me".

## What it enforces

- **The test**: cover the prose — can the reader answer the page's question from the
  diagrams alone? If not, fix the diagram, not the prose.
- **Decide the one question first**, then the shape (structure / sequence / state machine
  / layered / comparison matrix / data chart). More than 9 nodes is usually two diagrams.
- **Numbers, states and constraints live on the canvas** — on edges and nodes, encoded
  through visual channels, not described in paragraphs.
- **Hard prose budgets**: a ≤3-sentence lead, a 1-sentence caption plus at most 3
  sentences of what the diagram cannot show per figure, table cells hold phrases not
  sentences.
- **Multi-diagram pages stay self-contained**: one set of identifiers across overview and
  detail diagrams, every required number somewhere on a canvas, everything inlined in
  one file.
- **Before delivery**: render the page and look at it (a green validation script is not a
  geometry check), hunt down dangling references, keep implementation identifiers away
  from non-engineering readers, and ship no agent fingerprints.

## Renderers (all optional)

| Reader | Use | Output |
|---|---|---|
| One-page explainer of a complex question | [answer-me-with-html](https://github.com/QingYunA/answer-me-with-html) ("am") | offline single-file HTML |
| A picture for chat / docs / mobile (default) | [diagram-design](https://github.com/cathrynlavery/diagram-design) | PNG, or SVG embedded in the page |
| System diagrams explored on a desktop (architecture, dataflow, sequence, workflow, state machine, ER, timeline) | [archify](https://github.com/tt-a1i/archify) | interactive HTML **plus** a static fallback page assembled by `scripts/archify-page.mjs` |
| Unsure, chart-type data, or neither of the above installed | diagram-design; with neither installed, hand-write the SVG/HTML — the skill's rules still govern what goes on the canvas | — |

## Install

```
/plugin marketplace add SunflowersLwtech/sunkit
/plugin install show-me@sunkit
```

The skill works on its own: with none of the renderers installed it still governs what a
diagram must carry, and degrades to hand-written SVG/HTML plus PNG export through any
available headless Chromium.

The renderers are optional companions. `archify` and `answer-me-with-html` come from this
same marketplace and install **disabled** (`defaultEnabled: false`) — on purpose: they
should never surface as `/archify:*` or `/answer-me-with-html:*` slash commands. show-me
is the single entry point and drives them by reading their `SKILL.md` at the installed
path. `diagram-design` comes from its own marketplace:

```
/plugin marketplace add cathrynlavery/diagram-design
/plugin install diagram-design@diagram-design
/plugin install archify@sunkit
/plugin install answer-me-with-html@sunkit
```

Agent-facing details on all three handoffs, PNG export, CJK fonts and the pitfalls of
each renderer: [skills/show-me/references/tooling.md](skills/show-me/references/tooling.md).

## Scripts

| File | What it does |
|---|---|
| `scripts/archify-env.sh` | Locates the installed `archify@sunkit` plugin, builds an `ARCHIFY_CHROME` wrapper that runs the cached `chrome-headless-shell` with `--use-mock-keychain --password-store=basic` (no macOS keychain prompts), and disables archify's update check |
| `scripts/amwh-env.sh` | Locates the installed `answer-me-with-html@sunkit` skill and disables its update check and auto-open |
| `scripts/archify-page.mjs` | Assembles one or more archify interactive HTML files into one page (each diagram = full-size SVG + cards + a fullscreen button for the interactive version); drives Chrome over the DevTools protocol, no playwright needed |

## Requirements

- Node.js ≥ 20 for the scripts and both `sunkit` companion plugins; `archify-page.mjs`
  wants Node ≥ 22 (built-in `WebSocket`).
- PNG export needs a Playwright Chromium; a `chrome-headless-shell` already in the
  Playwright cache is enough. The tooling notes walk the whole dependency chain and its
  fallbacks.
