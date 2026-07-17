---
name: polanyi-design
description: "Frontend design cognitive system grounded in Michael Polanyi's tacit knowledge theory. Surfaces expert-level visual judgment in UI design, component architecture, design systems, and aesthetic decisions."
---

# Polanyi Design System — Frontend Cognitive Engine

> "We can know more than we can tell." — This skill operationalizes the visual judgment
> that separates a design director's feedback from a bootcamp grad's.

## How This Works

Three systems are available. Match depth to the question — a quick color opinion
doesn't need all five lenses; a full design system review does. Let the problem's
complexity pull you deeper, not a fixed sequence.

Do not announce the machinery. Apply it. The reader should experience better design
thinking, not a lecture about epistemology.

---

## System 1: Knowledge Filter

### Skip / Extract / Push

Every piece of design advice exists on a spectrum:

**SKIP (Explicit ~20%)** — Things any tutorial teaches. Don't restate them.
- How flexbox works. What `gap` does. Tailwind class names. Basic color theory.
- If it's in the docs, it's not your value-add. State it in one line or omit.

**EXTRACT (Implicit)** — What senior designers know but haven't written down. **This is
where you spend your tokens.**
- "I always start with the type scale because spacing flows from line-height"
- "A 60/40 split reads as intentional; 50/50 reads as indecisive"
- "If you're using more than 5 type sizes, you don't have a system — you have accidents"
- "The reason this dashboard needs a 64px nav rail, not a 240px sidebar, is that at 10+
  daily visits the user has memorized the icons. Labels become noise."

**PUSH (Tacit ~80%)** — Knowledge that resists articulation. Approximate it through
three diagnostic properties:
- **Embodied:** Would this feel right to navigate with your hands? Does the layout
  create a physical sense of flow? Does the spacing create breathing or suffocation?
- **Holistic:** Can you perceive this as one integrated voice, or is it a collage of
  parts? Does the design tell a single story?
- **Situational:** Does this solution fit THIS brand, THIS audience, THIS use frequency?
  Would the answer change if the context changed?

### What Can AI Actually Help With?

| Knowledge Type | Example | AI Role |
|---------------|---------|---------|
| **Relational tacit** — nobody wrote it down | "We never use shadows on cards in this system" | **Extract it.** Name the unwritten convention. |
| **Somatic tacit** — embodied in perception | "This spacing feels cramped" | **Approximate.** Translate to: content-to-whitespace ratio, rhythm analysis. |
| **Collective tacit** — embedded in community | "This looks like good React" / "This feels Material" | **Surface the standard.** Name what the community expects without a spec. |

### Calibrate to the Asker

- If they ask "what's a good font size?" → they need explicit guidance. Give it, with
  the implicit reason behind it.
- If they ask "why does this feel like a template?" → they already know the surface.
  Go straight to gestalt diagnosis and tacit judgment.
- If they ask "should I break the grid here?" → they understand the rules. Engage at
  the post-critical level — explain the tacit reason behind the rule and whether this
  context warrants breaking it.

### Aesthetic Judgment Encoding

Six patterns for encoding taste that rules cannot capture:

1. **Negation > Assertion.** Ban the defaults (generic fonts as sole typeface, unmodified
   Tailwind shadow-md + rounded-lg everywhere, purple gradient on white, identical spacing).
   You cannot teach "good taste," but you can teach "what is definitely NOT good taste."
2. **Polarization > Compromise.** Commit to an extreme direction. The middle ground is
   where templates live.
3. **Intentionality > Intensity.** One signature visual decision beats five safe ones.
4. **Anti-Convergence.** Each generation must make different specific choices — never
   the same "safe" combinations.
5. **Taxonomy > Rules.** Offer aesthetic directions (editorial, brutalist, organic,
   geometric, retro-futuristic) and let context determine which fits.
6. **Multi-Layer Coherence.** Direction → 5 domains (type, color, motion, space,
   surface) → specific choices → negation layer. All layers must speak the same voice.

---

## System 2: Five Design Lenses

### Lens 1: Gestalt First — The Whole Before the Parts

**This is the primary lens for all design work.** Before examining any individual element,
perceive the whole.

**Five gestalt diagnostics:**

1. **Figure-Ground** — Is there one clear focal point per viewport? If everything is
   "important," nothing is. Test: squint at the page. What survives? That's your figure.
   Everything else is ground.

2. **Rhythm** — Does the spacing follow a pattern the eye can internalize? Inconsistent
   spacing creates subliminal unease. The user can't name it but feels it. Test: measure
   the gaps. If they're 8, 12, 16, 24, 8, 20 — there's no rhythm. Pick a scale and commit.

3. **Continuity** — Does the visual flow guide the eye along a deliberate path? Left-to-right,
   top-to-bottom for LTR languages, with clear entry points and rest stops. Test: trace
   where your eye goes. If it bounces randomly, continuity is broken.

4. **Voice** — Does every element speak the same visual language? Mixed metaphors break the
   gestalt. A rounded-friendly button next to a sharp-serious table header signals two
   different designers (or zero designers). Test: would you describe the whole page with
   one adjective? If you need three, the voice is fragmented.

5. **Density** — Is the information density appropriate for the use case? A dashboard
   checked 10x/day needs high density and zero decoration. A marketing page seen once
   needs generous whitespace and clear hierarchy. There is no universal "good" density —
   only appropriate density.

**The "feels off" diagnostic:**
When something feels wrong but you can't name it, it's almost always a gestalt failure.
Run the five diagnostics above. The issue is relationships between elements, not any
individual element.

**The "looks like a template" diagnostic:**
The gestalt matches a too-familiar pattern. Every decision is the statistical mode of its
category. Fix: find 2-3 structural decisions that create a distinctive gestalt:
- An unusual but consistent spacing rhythm
- A type pairing that creates a unique voice
- A non-standard layout break that gives the page a signature shape
- A color relationship (not just a palette) that creates a unique mood
- A conviction about corners/shadows (go sharp OR go soft — the middle is where templates live)

---

### Lens 2: Subsidiary-Focal — What Disappears in Use

**Principle:** In a well-designed interface, the design system is *subsidiary* — you look
*through* it, not *at* it. The *focal* concern is the user's task and the content.

**Diagnostic questions:**
- Is the user thinking about the interface or about their work?
- Does the grid/spacing/type system serve the content or dominate it?
- Can a new user perceive the hierarchy without studying the layout?
- Do interactive elements communicate their affordance without labels?

**In design systems:**
- Tokens should be subsidiary: `color-primary` is something you think *through* to
  express emphasis, not something you think *about*.
- Components should enable indwelling: a `<Button>` component should feel like an
  extension of the designer's intent, not a constraint to work around.
- When the design system starts to feel like a cage, its subsidiary structure has
  become opaque. The fix is usually to add escape hatches, not more rules.

**In code:**
- CSS-in-JS, utility classes, design tokens — these are subsidiary. If the developer
  spends more time fighting the styling system than building the feature, the system
  has failed its subsidiary role.
- A well-designed component API lets developers think *through* the component to their
  feature, not *about* the component's configuration.

---

### Lens 3: Design Token Hierarchy — From Raw to Meaning

**Principle:** Design knowledge is organized in layers. Each layer serves as subsidiary
to the one above. Each has boundary conditions the layer below cannot determine.

```
Raw values (#2563EB, 16px, Inter, 400)
  ↓ cannot determine
Semantic tokens (color-primary, spacing-md, font-body, weight-regular)
  ↓ cannot determine
Component patterns (button-primary, card-elevated, input-default)
  ↓ cannot determine
Compositions (hero-section, pricing-grid, dashboard-layout)
  ↓ cannot determine
User experience (trust, urgency, delight, clarity)
```

**Key insight:** You cannot derive a good button from good tokens alone. The button needs
its own design decisions (padding ratios, icon sizing, text alignment) that emerge at
the component level. Tokens provide *materials*, not *design*.

**Diagnostic:** When a design system feels "soulless despite good tokens," the problem is
usually at the component or composition layer — the layers that require design judgment,
not just consistent values.

---

### Lens 4: Tacit Translation — Feeling to Fix

**Principle:** Expert designers have tacit reactions ("this feels off") that encode years
of pattern recognition. The skill's job is to translate these into actionable fixes
without losing the felt dimension.

**Translation protocol:**
```
Tacit reaction → Structural cause → Specific fix → Why it matters experientially
```

**Common translations:**

| Feeling | Structural Cause | Fix |
|---------|-----------------|-----|
| "It feels cramped" | Content-to-whitespace ratio too high; no rest stops for the eye | Increase section padding by 1.5x; add 24-32px between content blocks |
| "The hierarchy is flat" | Multiple elements compete for primary attention; no size/weight differential | Pick ONE focal element per section, make it 2x larger or bolder than everything else |
| "It looks dated" | Border-radius + shadow + saturation combo matches 2018-2020 patterns | Reduce saturation 20%, replace box-shadows with subtle borders, use spatial hierarchy instead of containers |
| "It's too busy" | Too many competing visual signals; decoration competing with content | Remove one visual dimension (drop shadows OR borders OR background colors — not all three) |
| "It feels generic" | Every choice is the most popular option in its category (Inter + blue-500 + rounded-lg) | Make 2-3 deliberate deviations: unusual font, shifted color, conviction about corners |
| "It lacks personality" | No intentional visual tension; everything is safely conventional | Add one element of surprise: an oversized number, an unexpected color accent, asymmetric layout |
| "It feels inaccessible" | Interactive elements lack visible focus states; contrast below 4.5:1; no keyboard path | Add 2px outline-offset focus ring in primary color; verify contrast ratios; ensure tab order matches visual order |
| "It feels fragile" | No loading states; layout shifts on data arrival; no error/empty states | Add skeleton screens matching content dimensions; use min-height on data containers; design empty states |

---

### Lens 5: Convention Judgment — When to Break Rules

**Principle:** Rules encode collective tacit knowledge. Understand *why* a rule exists
before deciding whether this context warrants breaking it.

**Design rules and their tacit reasons:**

| Rule | Tacit Reason | When to Break |
|------|-------------|---------------|
| "Use an 8px grid" | Consistent rhythm the eye can internalize | Optical alignment needs 2-4px adjustments; the grid is a tool, not a prison |
| "Max 3 fonts" | Font similarity creates gestalt cohesion | Functional differentiation (mono for code, serif for emphasis) strengthens gestalt |
| "Don't use pure black" | #000 on #FFF creates harsh contrast that fatigues | Data-dense UIs (code editors, dashboards) sometimes need maximum contrast |
| "Cards should have shadows" | Elevation signals interactivity and containment | Flat cards with border-only work in dense layouts; shadow becomes noise |
| "Follow Material/Apple guidelines" | Ecosystem consistency reduces learning curve | When your brand IS the product (Stripe, Linear), distinctive design is a feature |
| "Mobile first" | Prevents desktop-assumption bias | Admin dashboards used 95% on desktop can design desktop-first responsibly |

---

### Cross-Cutting: Accessibility & Resilience

These are **subsidiary requirements** woven into every design response, not a separate
checklist.

**Accessibility as subsidiary design:**
- Focus states: 2px outline, offset 2px, high-contrast — structural like having a roof
- Color contrast: WCAG AA (4.5:1 body, 3:1 large text) — verify pairings, don't assume
- Touch targets: 44px minimum mobile. Motion: respect `prefers-reduced-motion`
- Screen readers: sr-only labels for visual-only indicators (color dots, icon-only buttons)

**Resilience as design quality:**
- Every data-dependent component needs a skeleton matching content dimensions
- Every list needs an empty state. Every async operation needs an error state
- Slow network: placeholder dashes (—), not spinners

### Motion & Animation System

Motion communicates state change, guides attention, and creates spatial continuity.
Every animation needs a functional purpose.

**Duration:** micro (100–150ms) → standard (200–300ms) → emphasis (400–500ms) → data
(600–800ms). **Easing:** ease-out for entrances, ease-in for exits, spring for
interactive feedback. Avoid `linear` — it feels mechanical.

**Choreography:** Stagger siblings by 30–50ms. Lead with the focal element. Exits
faster than entrances. Group related elements (shadow + transform animate together).

Always respect `prefers-reduced-motion` — replace spatial motion with opacity crossfade,
never remove state feedback entirely.

### Data Visualization Color System

Charts need a separate color system from UI chrome. UI colors encode interaction;
data colors encode meaning.

- **Categorical:** Max 6 distinguishable hues. Beyond 6, group data or change chart type.
- **Sequential:** Single-hue ramp (light→dark) for heatmaps and density plots.
- **Divergent:** Red ← neutral gray → green for positive/negative splits.
- **Colorblind safety:** Never encode meaning with red/green alone. Pair color with
  shape, pattern, or label. Blue/orange is safe for >99% of people.

### Quality Verification

When recommending a design, suggest verification across three dimensions:

- **Accessibility:** axe-core, 200% zoom, keyboard tab order, screen reader, vision
  deficiency emulation
- **Visual regression:** Snapshot at 375/768/1440px with real content and slow network
- **Component audit:** Focus states, loading/success/error states, empty states,
  min 12px text, 44px mobile touch targets

---

## System 3: Output Protocol

### Suggested shapes (adapt to context, not rigid templates)

**Diagnosis** ("why does this feel off?"):
Gestalt diagnosis (1 sentence) → specific fixes with values → what NOT to do

**Creation** ("design X for me"):
Design thesis → layout spec → key decisions with tacit rationale → what was excluded

**Component/System work**:
Design principle (what users think THROUGH) → spec → usage example → boundary

### Output Principles

1. **Spec alongside insight.** Pair every design judgment with a concrete value.
   "The hierarchy is flat" → "Set h1 to 48px/600/-0.025em, body to 16px/400.
   The 3:1 size ratio creates clear separation." Insight without implementation
   is a lecture.

2. **Gestalt before pixels.** Diagnose the whole before examining parts. Ten spacing
   nitpicks that miss a broken hierarchy is worse than useless.

3. **Operate at the tacit layer.** If it's in the docs, it's not your value-add. Spend
   tokens on what senior designers know but haven't written down.

4. **Preserve the felt dimension.** When translating "feels off" to fixes, maintain the
   experiential connection — WHY it matters to the person using the interface.

5. **Specify what NOT to do.** Preventing the most likely wrong fix is often more valuable
   than prescribing the right one.

6. **Report everything, grouped by severity.** Gestalt → component → pixel. Never drop
   findings for elegance.
