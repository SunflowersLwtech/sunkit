# Codex Goal Prompt: Premium Remotion Keynote System Overhaul

Use this prompt as the full goal brief for a long-running Codex implementation session in:

`/Users/sunfl/Documents/media/searchpo`

## First Message To Codex

Create and pursue this goal until the system is genuinely upgraded end to end:

> Rebuild the Searchpo video generation chain so every provider-rendered topic can become a topic-specific, React/Remotion-programmatic, real MP4 with the visual ambition of a heavily invested Apple Keynote or premium Remotion showcase. The system must stop relying on generic Searchpo Radar/card/storyboard visual structures as the main output. For content, replace "自己验证 / you verify it yourself / 待验证案例继续观察" style endings with meaningful knowledge sharing: mechanism explanation, architecture position, practical fit, failure boundaries, and a useful evaluation or adoption judgment framework. Implement the necessary lower-level pipeline changes, not only prompt edits. Iterate through code, tests, renders, audits, and repairs until the acceptance criteria in `docs/runbooks/premium-remotion-keynote-goal-prompt.md` pass.

Before editing, read:

- `AGENTS.md`
- `skills/remotion-best-practices/SKILL.md`
- `skills/searchpo-impl-agent/SKILL.md`
- `/Users/sunfl/.gemini/antigravity/brain/3f14b72d-b8a0-45f0-9efd-c5154b88dc8b/implementation_plan.md`
- The current implementation surfaces listed below.

Do not live-publish anything unless the user separately and explicitly asks for `post --live`.

## Core Outcome

The final system must make provider videos feel closer to the reference Remotion showcase videos under:

`/Volumes/Sunflowers/T7/mac32/document/study`

The goal is not "a slightly better template." The goal is a pipeline where the generated MP4 is driven by React/Remotion programmatic visuals tailored to the input topic.

Target visual standard:

- Full-canvas React/Remotion composition owns the video.
- Topic-specific visual grammar is generated from the input topic and evidence.
- Scene grammar changes over time instead of stretching one loop, dashboard, orbit, radar, or card stack.
- High-end product/keynote feel: intentional typography, depth layers, parallax/camera movement, mask reveals, SVG/path build-ups, metric morphs, object choreography, and readable data density.
- Motion is comfortable, not noisy: one primary focal action per beat, restrained secondary motion, visible dwell/rest moments, no strobe/shake/glitch, no unreadable rotating labels.
- Horizontal 16:9 is the default for repo/code/architecture/table/timeline/dense technical explainers unless the topic is explicitly phone-native.
- Vertical remains supported for suitable topics, but it must still be full-canvas and topic-specific.

Target content standard:

- Do not end by throwing work back to the audience with "自己验证", "你自己动手验证", "待验证案例继续观察", "不能跳过最小验证", "按证据验证，不急着下结论", "具体细节未知，需要自己去试", or similar dismissive phrasing.
- Preserve evidence boundaries without sounding useless. Replace "go verify it yourself" with knowledge sharing:
  - what the system is doing,
  - why the mechanism matters,
  - where it sits in an architecture,
  - what tradeoff it creates,
  - what failure boundary or adoption judgment framework a viewer should learn.
- The viewer should leave with a useful mental model, not just a caution label.

## Current Plan To Incorporate

Use the latest Antigravity implementation plan as the starting point:

`/Users/sunfl/.gemini/antigravity/brain/3f14b72d-b8a0-45f0-9efd-c5154b88dc8b/implementation_plan.md`

Important ideas from that plan:

- Do not simply remove constraints; that either breaks validators or recreates uncomfortable motion.
- Build a Director-Led Premium Compiler:
  - DeepSeek acts as director and outputs a `premium_director_spec` / `visual_recipe`.
  - Stable React/Remotion premium components compile the recipe into MP4.
- Fix the GitHub repo path where `render/prepare_remotion_input.py` currently overrides provider creativity with `premium_repo_agent_visual`.
- Update content prompts, fallbacks, and scorers so the content becomes meaningful knowledge sharing.
- Add comparative QA against showcase references.

## Required Investigation Surfaces

Inspect these before deciding edits:

- `scripts/deepseek_polish.py`
  - `agent_visual_layout_contract()`
  - fallback storyboards and fallback visuals
  - prompt/user payload construction
  - voiceover shortening / compact fallback paths
  - `source_grounded_agent_visual()` and deterministic repair paths
- `scripts/content_scorer.py`
  - scoring dimensions around verification path, constructive interpretation, open-source explainer value
  - blocking checks that pull content back to "verification path"
- `agent_harness/agent_visual.py`
  - validator patterns
  - motion comfort patterns
  - module/component normalization and error behavior
- `render/prepare_remotion_input.py`
  - GitHub repo override path
  - generated `AgentVisual.generated.tsx` write path
  - `agentVisualRequired`
- `scripts/deterministic_visual_audit.py`
  - full-canvas agent visual checks
  - state count checks
  - topic-specific primitive checks
  - overcrowding checks
- `scripts/gemini_visual_audit.py`
  - native-video audit prompt
  - contract errors
  - rubric thresholds and topic visual checks
- `src/Composition.tsx`
  - full-canvas agent visual layering
  - global captions layering
  - default/legacy background and storyboard rendering
- `src/premium/`
  - existing premium components, especially repo visual surfaces
- `contracts/schemas/video_spec.schema.json`
- `contracts/schemas/render_payload.schema.json`
- `agent_harness/storyboard.py`
- `src/storyboard.ts`
- `config/searchpo_policy.json`
- Tests under `tests/`, especially visual/content/pipeline contract tests.

## Architecture Requirements

### 1. Add Or Formalize A Premium Director Spec

Introduce a typed, testable `premium_director_spec` or `visual_recipe` contract that can be stored in `video_spec.json` and `render_payload.json`.

It should describe director intent without requiring the LLM to hand-code every pixel:

- `profile`: orientation, duration, style family, motion comfort level.
- `knowledge_arc`: hook, mechanism, architecture position, tradeoff, judgment framework.
- `visual_scenes`: ordered list of premium scene beats.
- `topic_objects`: concrete source-backed objects: repo files, APIs, modules, architecture nodes, metrics, UI states, comparison axes, timeline events.
- `motion_beats`: frame-driven movement intent: reveal, build, pan, morph, path draw, metric count, object focus, dwell.
- `scene_types`: examples:
  - `HeroProblemScene`
  - `MechanismExplodedView`
  - `RepoFileTreeReveal`
  - `ArchitectureFlowScene`
  - `MetricComparisonScene`
  - `DecisionMatrixScene`
  - `TimelineBuildScene`
  - `CodeOrTerminalScene`
  - `KnowledgeTakeawayScene`
- `content_constraints`: source boundary, banned dismissive phrases, useful knowledge takeaway.

The exact schema can evolve, but it must be explicit, validated, and visible in run artifacts.

### 2. Build A Premium Compiler Instead Of Raw Template Fallback

Implement or strengthen a deterministic premium compiler under `src/premium/` and supporting harness code.

The compiler should accept the `visual_recipe` and render a full-canvas `AgentVisualGenerated` module or equivalent stable React component tree.

Do not make one generic dashboard component. Build a small scene library that can compose a premium keynote:

- Hero scenes with cinematic type and concrete topic object.
- Mechanism scenes with exploded architecture / pipeline / node graph.
- Repo scenes with file tree, module lanes, API surface, or terminal/code details.
- Metric scenes with animated bars, counters, score dials, or comparison tables.
- Decision scenes with judgment frameworks, suitable/not-suitable splits, or tradeoff matrices.
- Takeaway scenes that teach a useful concept, not "go verify yourself."

The generated MP4 must come from React/Remotion programmatic components, not from OCR, screenshots, generic cards, or static markdown-like slides.

### 3. Fix The GitHub Repo Override

Currently, GitHub repo subjects may be forced into a deterministic `premium_repo_agent_visual` in `render/prepare_remotion_input.py`. That blocks director output.

Redesign this path so GitHub repo videos use the new premium director/recipe system.

Acceptable options:

- DeepSeek emits `visual_recipe`, deterministic compiler renders it.
- DeepSeek emits high-level recipe plus optional component hints, deterministic compiler renders it.
- DeepSeek module code is allowed only when it passes validator and is not overridden silently.

Unacceptable:

- Silently ignore provider visual output for GitHub repos.
- Fall back to generic repo dashboard/card visual while claiming premium output.
- Use `data.cards` / `safeCards` as the main visual.

### 4. Layering Contract In Composition

Ensure `AgentVisualGenerated` has full canvas ownership in provider mode.

Rules:

- Full-canvas agent visual should not get cluttered by legacy `HexGrid`, beam, audio wave, topbar, storyboard scenes, or default poster overlays.
- Global captions may remain as a final top-layer subtitle system, but agent visual must not render its own captions or subtitle bars.
- Chapter bridge should be off by default unless explicitly requested by premium director and proven non-cluttering.
- Horizontal and vertical layouts must both reserve caption-safe space.

### 5. Motion Contract: Creative But Comfortable

Do not "remove all restrictions." Replace blunt restrictions with a tiered contract.

Allow and encourage:

- Remotion `spring`, `interpolate`, frame-driven motion.
- SVG path drawing and flow lines.
- Mask/clipPath reveals.
- Layered parallax and subtle camera pans.
- Metric morphing and counters.
- File tree and code/terminal transitions.
- Object focus changes with dwell moments.
- Audio-reactive emphasis when it remains restrained.

Continue to reject:

- CSS `animation` / `transition` timing.
- Strobe, glitch, flash, shake.
- Whole-video orbit swarms as the primary system.
- Rotating readable labels.
- High-frequency dash sweeps.
- Pure black full-frame backgrounds that trip black-frame detection.
- Multiple independent motion systems competing at once.
- Secondary captions/subtitles/progress bars inside agent visual.
- local filesystem/process/env/cookie/localStorage/sessionStorage access.

Update `agent_harness/agent_visual.py`, `scripts/deterministic_visual_audit.py`, and Gemini audit prompts so they enforce this director contract instead of suppressing premium visuals.

### 6. Content Contract: Meaningful Knowledge Sharing

Remove dismissive verification language from all generation, fallback, compacting, policy, and scoring paths.

Search and repair at least these classes of phrasing:

- `自己验证`
- `你自己动手验证`
- `待验证案例继续观察`
- `不能跳过最小验证`
- `按证据验证，不急着下结论`
- `不急着下结论`
- `具体细节未知，需要自己去试`
- English equivalents like "verify it yourself" when used as the final value proposition.

Do not remove source boundaries. Reframe them.

Preferred content shape:

- Teach the viewer the mechanism.
- Explain why the topic matters.
- Locate it in a system architecture or workflow.
- Name tradeoffs and failure modes as useful knowledge.
- Provide an adoption judgment framework or evaluation lens.
- When source evidence is insufficient, say what the available evidence teaches, not "go find out yourself."

Update:

- `scripts/deepseek_polish.py`
- `scripts/content_scorer.py`
- `config/searchpo_policy.json`
- relevant fallback/repair code paths
- tests.

The scorer should reward practical evaluation insight and knowledge density, not just "verification path."

### 7. Comparative Showcase Audit

Add a QA artifact that compares generated videos against reference Remotion/showcase videos.

It can be a script such as:

`scripts/premium_showcase_audit.py`

It should accept:

- run dir
- generated MP4
- one or more reference MP4s under `/Volumes/Sunflowers/T7/mac32/document/study`

It should ask Gemini to judge:

- premium keynote aesthetic
- topic-specific visual grammar
- smooth motion comfort
- data density with readability
- scene variation / visual grammar changes
- absence of generic dashboard/card-template feel
- content usefulness / knowledge-sharing quality

It should write a run-scoped artifact, e.g.:

`premium_showcase_audit.json`

This audit must not replace deterministic/Gemini release gates. It is an additional quality bar for the premium overhaul.

## Implementation Milestones

Work in milestones and keep going across failures.

### Milestone 0: Baseline And Contract Map

Before editing:

- Read the latest Antigravity plan.
- Inspect the current code surfaces listed above.
- Summarize the actual current blockers in a short local note or task plan.
- Identify exactly where visual generation is overridden, where fallback visuals are created, and where verification language is injected.

### Milestone 1: Director Spec And Data Flow

Implement a first version of `premium_director_spec` / `visual_recipe`.

Required:

- schema or validation function
- generation/prompt path in DeepSeek payload
- storage in provider output / video spec / render payload
- tests for round-trip validity

### Milestone 2: Premium Compiler

Implement stable premium React/Remotion components and a compiler path.

Required:

- enough scene types to avoid one-template output
- full-canvas agent visual render
- horizontal default for technical topics
- no generic cards as main visual
- tests that confirm GitHub/repo topics do not get silently overridden to a generic visual

### Milestone 3: Content Contract Rewrite

Repair prompts, fallbacks, compacting, scorer, and policy language.

Required:

- banned dismissive phrases do not appear in generated public copy, fallback copy, captions, storyboard text, visual text, or publish metadata.
- source boundaries remain, but as knowledge/adoption insight.
- content scorer target language no longer forces "verification path" as a throwaway ending.

### Milestone 4: Audit And Gate Updates

Update deterministic and Gemini visual audits to check for premium director qualities.

Required:

- reject generic dashboard/card-only layouts.
- reward or require scene grammar changes.
- keep motion comfort hard rules.
- add comparative showcase audit artifact.

### Milestone 5: Real Render Proof

Run at least one full provider/local render through the new chain.

Use a GitHub repo topic first because it is the main target class.

Required proof:

- real MP4 generated
- Remotion local render pass
- `render_metadata_check.json` pass
- `visual_audit_deterministic.json` pass
- `gemini_visual_audit.json` pass
- `premium_showcase_audit.json` present and not fail
- final video visually uses premium director scenes, not legacy cards/radar/dashboard
- public copy contains no banned dismissive verification phrasing

### Milestone 6: Multi-Topic QA

Run provider/local render or the closest practical equivalent across at least five topic categories:

1. GitHub repo
2. AI paper or model release
3. Developer tool
4. Product launch
5. Tech controversy or comparison

For each, record:

- run dir
- topic/link
- final MP4 path
- render metadata status
- deterministic visual audit status
- Gemini visual audit status
- premium showcase audit status
- whether banned content phrases were absent
- one sentence describing the premium visual grammar used.

Do not claim completion with only unit tests.

## Acceptance Criteria

The goal is complete only when all are true:

- A topic-specific premium director/recipe contract exists and is validated.
- Provider pipeline emits or compiles that contract into Remotion props.
- GitHub repo topics are not silently overridden by a generic deterministic visual.
- Full-canvas agent visual owns the video surface.
- Legacy cards/storyboard/radar visuals are compatibility only and not the main provider output.
- React/Remotion programmatic visuals render a real MP4 locally.
- Motion contract allows premium cinematic movement while preventing uncomfortable output.
- Public content no longer uses "自己验证 / 待验证案例继续观察 / 按证据验证，不急着下结论" style endings.
- Content gives meaningful knowledge sharing: mechanism, architecture, fit, tradeoff, judgment framework.
- Deterministic audit and Gemini audit pass for at least one end-to-end provider render.
- Premium showcase comparative audit exists and passes or gives a clear, actionable gap report.
- Multi-topic QA has at least five recorded attempts, with failures repaired or clearly listed as remaining blockers.
- Tests cover the new director spec, compiler path, GitHub override behavior, content phrase bans, and audit contract.

## Commands And Verification Guidance

Start with targeted tests, then broaden.

Likely useful commands:

```bash
python3 scripts/agent_capabilities.py --profile implementation --format text
python3 -m unittest tests.test_improve_loops tests.test_static_contracts tests.test_storyboard_contract tests.test_remotion_inputs
npm run lint
```

For provider/local render, use the repo's current supported flow. Prefer a fixed GitHub link for the first proof:

```bash
SEARCHPO_LINK="https://github.com/<owner>/<repo>" npm run e2e:provider
```

If local render mode must be explicit, inspect existing scripts and policy first; do not invent bypasses.

After each render, verify run-scoped artifacts:

```bash
RUN_DIR="$(cat runtime/latest_run.txt)"
jq '.status' "$RUN_DIR/render_metadata_check.json"
jq '.status' "$RUN_DIR/visual_audit_deterministic.json"
jq '.status' "$RUN_DIR/gemini_visual_audit.json"
```

Do not use `npm run e2e` alone as proof of video quality; contract mode is not enough.

Do not use live publishing as proof. No `SEARCHPO_DOUYIN_LIVE=1` unless the user explicitly asks to publish.

## Non-Negotiables

- Do not fabricate provider, audit, render, or publish artifacts.
- Do not print `.env` secrets.
- Do not use mock audio, silent media, fake visual audit, or placeholder provider output.
- Do not hand-edit runtime artifacts to make a gate pass.
- Do not revert unrelated user changes in this dirty worktree.
- Do not delete safety validators wholesale. Refactor them into premium-friendly contracts.
- Do not let captions/progress bars count as primary central motion.
- Do not let cards, safeCards, raw summaries, source URLs, or internal metadata become the main visual.
- Do not end with a plan only. Implement, render, audit, and report artifact truth.

## Reporting Requirements

When reporting progress, include concrete artifact truth:

- files changed
- tests run and result
- run dir(s)
- MP4 path(s)
- render metadata status
- deterministic audit metrics such as `active_pair_ratio` and `max_static_seconds`
- Gemini visual audit status
- premium showcase audit status
- explicit statement on whether banned dismissive phrases are absent
- remaining blockers if any

The final answer should say whether the system is genuinely upgraded or still partially complete.

If the work cannot complete in one turn, keep iterating under the same goal. Use context compaction only after persisting the current state and next steps.

