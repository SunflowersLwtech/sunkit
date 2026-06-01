# Content Quality Gates

Use this when a post is safe but still feels generic, smooth, or low-value.
These gates adapt content-diagnosis patterns for technical X posts, but the
rules here are repo-to-X specific.

## 0. Agent Engineering Brand Gate

The main account is `Agent 工程实战派`: Agent 工程如何从 demo 变成可靠系统.
Before writing, classify the input into one lane:

- `main_account`: agent reliability, build-in-public, paper-to-system, or
  embodied AI watch.
- `professional_bug_report`: KYC/support/platform complaint rewritten as repro,
  impact, expected behavior, evidence, and next action.
- `off_main_account_or_agent_link_required`: life/media/mood content that has no
  concrete Agent engineering mechanism.

Do not polish off-topic material into a main-account post. Either move it off
the main account or rewrite it around a concrete Agent failure mode.

## 1. Source Material Gate

Do not optimize a hook before the content has enough material. A publishable
technical post needs at least three of these:

- a concrete inspectable artifact: file path, function, config, command, API,
  benchmark table, paper figure, commit, or issue;
- a number or bounded comparison that is actually sourced;
- a before/after, failure mode, or rejected alternative;
- a reader pain or workflow constraint;
- a caveat that changes how the claim should be interpreted;
- a maintainer/source boundary that prevents hidden affiliation.

If the source only gives a repo name, README tagline, and star count, keep
screening text-only and collect more evidence before drafting.

## 2. Hook Independence Gate

Post 1 must work without a title, card, image, or prior context. It should make
three things legible fast:

- topic: what is being discussed;
- reason to read: the conflict, curiosity gap, risk, or workflow constraint;
- credibility: why this claim is grounded in evidence rather than vibe.

Use psychological triggers only when evidence supports them:

- cognitive conflict: "not X, but Y" when the source really changes a
  workflow assumption;
- curiosity gap: ask the unresolved technical question without hiding basic
  attribution;
- loss/risk: warn only about a real footgun or caveat;
- identity: name the technical reader who should care;
- numeric anchor: use sourced counts, scores, files, or timings.

Avoid giving the whole answer away in the hook. The first post should make the
reader want the mechanism, not merely nod at the conclusion.

## 3. Plain-Language Concept Gate

Every high-level concept must be reducible to plain technical language.

Bad shape:

- "This changes the future of agents."
- "A new paradigm for agent evolution."

Better shape:

- "The skill document becomes the state being trained; the model weights stay
  fixed."
- "Rejected edits become negative feedback instead of hidden prompt drift."

When a draft uses words like `paradigm`, `future`, `revolutionary`,
`framework`, `ecosystem`, `agentic`, or `self-evolving`, force one concrete
mechanism next to it.

## 4. Anti-Smoothness Gate

AI-looking copy is often too even: every paragraph closes neatly, every claim is
balanced, and no sentence admits uncertainty. Technical X copy can be clean
without being plastic.

Before publish:

- keep one real caveat or unresolved edge;
- do not repeat the same "not X, but Y" turn more than once unless each turn
  adds a distinct mechanism;
- cut ritual transitions such as "值得注意的是", "更重要的是", "总之",
  "in conclusion", and "it is important to note";
- prefer one sharp sentence and one concrete example over three polished
  summary sentences;
- use the user's language consistently; English should carry exact technical
  names, not filler.

## 5. X-Specific Shape

X is a text-first thinking surface. Links and images help, but they cannot carry
the post.

- Put the link after the reader already knows why it matters.
- If the first post has a link, make the thesis strong enough that the URL does
  not become the only reason to click.
- Do not make every post a feature list. Sequence should be thesis -> mechanism
  -> example -> caveat -> link or implication.
- A short post is acceptable only when it adds a new thought. Short filler is
  worse than no post.
- Every thread should leave the reader with one reusable asset: checklist,
  flowchart, issue template, prompt snippet, before/after table, or failure-mode
  map.
- End with one concrete technical question, not a vague "thoughts?".

## 6. Creator Pattern Gate

Use `creator-style-patterns.md` when a draft is safe but still feels like a
generic summary. Select one primary mode before rewriting:

- `engineering_mentor`: turn updates into engineering judgment, practical
  rules, product critique, and caveats.
- `demo_first_tool`: show how a tool is used, what was tested, what media proves
  it, and where it breaks.
- `test_catalog`: keep news/previews/leaks short, visual, source-aware, and
  explicit about tested vs untested status.
- `builder_resource_log`: make build-in-public posts artifact-first, numbered,
  saveable, and connected to a next validation or community loop.
- `product_translator_longform`: turn papers, podcasts, English sources, tools,
  and product cases into Chinese explanations with source boundaries, product
  implications, and saveable resource links.

Pattern fit changes the draft:

- Hook: mentor posts lead with conflict; demo posts lead with pain/result; news
  posts lead with what changed; build logs lead with artifact/progress; product
  translation posts lead with a counter-intuitive product question or trend
  judgment.
- Evidence: demo/test claims need real test details or a clear "not tested"
  boundary; translation posts must separate original-source facts from
  interpretation and user vision.
- Media: tool posts should prefer screenshots/video when available; generated
  images are conceptual and cannot fake UI evidence.
- Asset: choose the saveable object that matches the mode, such as a quick test
  checklist, integration steps, status table, progress log template, or reading
  path.
- Depth: thin updates can stay short, but paper-to-system,
  product-translator, and rich repo+vision drafts usually need 8-12 substantive
  posts. Several posts under 150 characters in a rich explainer are a revise
  signal, not a ready signal.
- Question: ask for a concrete test result, workflow comparison, design
  tradeoff, or beta/use-case feedback.

Do not imitate a specific creator's identity, catchphrases, emoji habits, or
community nicknames. Absorb the structural pattern, then write in the user's own
Agent engineering voice.
