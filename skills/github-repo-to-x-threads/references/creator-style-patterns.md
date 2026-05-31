# Creator Style Patterns

Use this reference when improving content quality, taste, cadence, or account
voice. The goal is to absorb proven content patterns without impersonating any
creator, copying catchphrases, or weakening claim safety.

## Pattern Sources

The observed high-performing AI/X accounts converge on five reusable patterns:

- `engineering_mentor`: timely AI/Agent updates turned into engineering
  judgment, practical rules, and future-facing product critique.
- `demo_first_tool`: AI tools explained through real demos, screenshots,
  short videos, usage steps, and Chinese user pain.
- `test_catalog`: fast AI news/testing updates with availability status,
  preview/leak boundaries, visual evidence, and a direct test question.
- `builder_resource_log`: build-in-public progress, short sentences, numbered
  resources, open-source/community loops, and one saveable list.
- `product_translator_longform`: product-manager translation of papers,
  podcasts, English sources, tools, and open-source projects into Chinese
  long-form explanations with product implications and resource links.

These are content modes, not identities. Select the mode that fits the source;
do not mimic a specific person's personal life, catchphrases, emoji habits, or
community nicknames.

## Pattern Selector

| Input | Primary Pattern | Required Artifact |
| --- | --- | --- |
| Agent/Coding/LLM product update | `engineering_mentor` | judgment rule, caveat, practical next action |
| Tool, app, workflow, UI, integration | `demo_first_tool` | tested step, screenshot/video plan, use case boundary |
| New model, preview, ranking, rumor, leak | `test_catalog` | source status, tested/untested boundary, reader test question |
| User's own project or weekly resource share | `builder_resource_log` | progress note, numbered resource list, next validation/community loop |
| English paper, podcast, product case, or open-source project needing Chinese explanation | `product_translator_longform` | translated thesis, product implication, resource links |
| Paper or repo with system implications | `engineering_mentor` + `builder_resource_log` | mechanism, checklist/flow, caveat |
| Complaint or support issue | not a creator pattern first | cold bug report, evidence, impact, expected behavior |

## Universal Quality Moves

- Lead with one of: what changed, why it matters, how to use it, or what can go
  wrong.
- Attach a concrete inspection surface: screenshot, video, command, config,
  API, diff, benchmark caveat, issue, PR, or file path.
- Add "I tested" only when there is real test evidence. If not tested, say
  "my read", "from the docs", or "worth testing".
- Keep Chinese natural and compact. Use English for exact terms such as
  `Agent`, `Skill`, `CLI`, `MCP`, `GUI`, `Codex`, and file/API names.
- Prefer short paragraphs, numbered lists, and one useful asset over polished
  explanatory prose.
- Let personality show through practical judgment: a light sentence is fine,
  but the post must still teach a workflow, risk, or decision.
- Use visuals as evidence or teaching aids. Generated images are conceptual;
  real tool demos should use real screenshots/video when available.
- End with a question someone can answer from experience, such as "你会把这个放
  在 coding agent 的哪个环节测试？"

## Pattern Contracts

### Engineering Mentor

Use when the source needs judgment more than a feature tour.

Shape:

1. technical conflict or risk;
2. what changed;
3. why the mechanism matters;
4. one concrete example;
5. caveat or rejected alternative;
6. practical rule or checklist;
7. discussion question.

Good signals:

- clear "not X, but Y" only once, tied to a mechanism;
- product critique plus a better design direction;
- engineering-management view: cost, reliability, token budget, evals, UI/CLI
  boundary, ownership, or operational path.

Avoid:

- pure prediction without evidence;
- sounding like generic AI news;
- overusing "未来", "范式", or "革命性" without a concrete workflow.

### Demo-First Tool

Use when the source is a tool, app, integration, or workflow that people can
try.

Shape:

1. user pain or visible result;
2. tested path or demo plan;
3. steps/features that matter;
4. who should try it;
5. limitation;
6. screenshot/video/image placement;
7. "what would you use this for?" style question.

Good signals:

- real UI, screenshot, screen recording, or before/after result;
- "能用在哪里" rather than only "它支持什么";
- local Chinese workflow pain, such as IM/file preview/mobile/office tasks, when
  relevant.

Avoid:

- fake demo claims;
- generated fake UI evidence;
- a feature list with no use case.

### Test Catalog

Use for fast updates, model releases, preview features, rankings, leaks, and
rumors.

Shape:

1. what is newly available or observed;
2. where it was seen/tested;
3. one visual or comparison;
4. verified vs rumor/preview boundary;
5. link or source;
6. short question: "Have you tested it?" / "你测到同样结果了吗？"

Good signals:

- availability status is precise;
- leak/rumor/test/release are not mixed;
- visual evidence is current and clearly labeled.

Avoid:

- treating leaks as official releases;
- hiding uncertainty to make a teaser stronger;
- using "tested" without test details.

### Builder Resource Log

Use for build-in-public, personal tools, weekly resource drops, and community
work.

Shape:

1. what changed today/this week;
2. one concrete artifact;
3. numbered resources or lessons;
4. what is open-source, planned, or still broken;
5. how others can follow/test/discuss;
6. next validation.

Good signals:

- short sentences with clear nouns and verbs;
- resource links or checklists people can save;
- community loop: comments, group, issue template, beta tester, or next demo.

Avoid:

- vague progress without artifact;
- over-marketing the user's project;
- asking for community action before the value is clear.

### Product Translator Longform

Use when the source is a paper, podcast, English post, product case, open-source
project, or AI trend that needs to become a Chinese reader's working model.

Shape:

1. counter-intuitive title or product question;
2. source context and claim boundary;
3. translation of the core idea into plain Chinese;
4. product/workflow implication;
5. concrete tool, command, GitHub repo, paper, or case;
6. caveat: source vs interpretation vs user vision;
7. resource links and a saveable summary.

Good signals:

- turns "what happened" into "what product/building decision changes";
- uses analogies only to clarify mechanisms, not to replace evidence;
- explains why non-specialists should care without erasing technical detail;
- gives readers links, commands, papers, repos, or a reading path they can save.

Avoid:

- treating secondary interpretation as original-source fact;
- making a trend prediction sound like certainty;
- writing a long article when the source only supports a short note;
- translating everything into abstraction without one runnable or inspectable
  artifact.

## Rewrite Diagnostics

If a draft is safe but weak, ask:

- Which creator pattern is this using?
- Is there real tested/demo evidence or only a polished claim?
- If this is translation/longform, are original facts, interpretation, and user
  vision separated?
- Does the first post work without the link card or image?
- Does the thread give one action the reader can take today?
- Is the visual doing evidence/teaching work, or just decoration?
- Is there a community loop: a concrete question, beta ask, issue template, or
  test comparison?
- Are news, rumor, inference, and user vision separated?

## Scoring Preference

Raise quality when the draft has:

- creator pattern fit: one coherent mode rather than mixed news/demo/build-log/
  longform fragments;
- demo evidence: real screenshot/video/test/command or a truthful "not tested"
  boundary;
- translation value: a complex paper/podcast/source becomes a usable product or
  workflow decision;
- practical next action: try, test, compare, inspect, save, or adapt;
- community loop: a concrete question that invites useful replies;
- human voice: concise, warm, and technical without copying another creator.
