# Enhanced Responses (V01 Skill) — Round 1

## A1: State Management for a Collaborative Editor

The focal concern here is not "which library" but the data model that makes collaboration possible. Real-time collaborative editing is fundamentally a distributed systems problem disguised as a frontend question.

**Architecture: CRDT-based document model + event sourcing**

Use Yjs (or Automerge) as your core document CRDT. Non-negotiable for these requirements:

- **Real-time sync**: CRDTs merge concurrent edits deterministically. Yjs provides awareness protocol for cursors/presence. Wire over WebSockets via y-websocket or Hocuspocus.
- **Undo/redo per user**: Yjs `UndoManager` scoped to user origin. Each user's undo stack tracks only their own operations.
- **Offline support**: CRDTs designed for this. Edits queue locally, merge cleanly on reconnect. Persist via y-indexeddb.
- **Optimistic updates**: Inherent. All edits are local-first.

What lives where:

| Concern | Solution |
|---|---|
| Document content | Yjs Y.Doc (shared types) |
| User presence/cursors | Yjs Awareness protocol |
| UI state (panels, modals) | Local React state or Zustand. Never replicate. |
| Document metadata | Server-authoritative, via React Query/SWR |

**The tacit reason** most teams get this wrong: they start with their familiar state manager and try to bolt on collaboration. That inverts the hierarchy. The collaboration model IS the state — React renders a projection of it. You dwell IN the CRDT; React is the subsidiary rendering layer.

Do not abstract over Yjs with a "state management wrapper." You need to think through the CRDT, not about it.

---

## R1: Architecture Smells in UserDashboard

The felt sense: this component is a **control room trying to be a single panel**. It looks functional, but every change forces you to re-understand the entire function. The problem is not any single line — it is a gestalt failure where independent concerns have been flattened into one undifferentiated blob.

Three structural problems:

1. **Four independent data domains fused by a single loading state.** User, posts, notifications, analytics have different lifecycles, cache durations, and error modes. One error kills everything. This is a **from-to boundary violation**: data-access concerns leaking into presentation.

2. **Server state masquerading as component state.** Using useState + useEffect for fetching loses cache invalidation, background refetching, deduplication. Replace with useSuspenseQuery or RSC.

3. **Non-null assertions (user!, analytics!) are a type-system lie.** The isLoading guard does not narrow types. TypeScript cannot verify user is non-null after the early return. This is a subsidiary detail that is actively opaque — it hides potential runtime errors.

The tacit lesson: when you see ten useState calls at the top of a component, that is not "lots of state" — it is missing architecture. State should be distributed to where it is consumed.

---

## U1: Analytics Dashboard Layout

This is a tool used 10+ times daily. The design must become **subsidiary** — invisible through familiarity. That means: zero visual novelty, extreme information density, consistent spatial logic.

Layout: Top bar (48px) + 200px nav sidebar + main canvas. KPI Strip (80px) with 5 metrics + sparklines. Main canvas splits into 2-column grid: Comparison bar chart + Trend chart (top), Mini Calendar + Inbox Feed (bottom).

Spacing: 4px base, 16px panel gaps, 20px card padding, 12px KPI gap, typography scale 12/14/16/20/28 — five sizes only.

Key decisions:
- Inbox feed always visible on Overview page — burying behind nav click means mentions get ignored
- Account color-coding (5 muted, distinct hues) consistent everywhere — this is the **gestalt glue** that lets users read across panels without conscious mapping

---

## V3: Aesthetic Diagnosis

The tacit reaction "looks like a template" means: **every design decision is the default.** The parts are fine individually, but they integrate into a gestalt that says "no human made specific choices here." It is not a quality problem — it is an identity problem.

What's generic:
1. Inter at default weights — most common SaaS font
2. #3B82F6 — literally Tailwind blue-500
3. Uniform corner radii — rounded-lg everywhere
4. Default shadows — shadow-md is recognizable
5. Stock photos — brain registers as "placeholder"

Five interventions:
1. **Typography** — keep Inter for body, add display font for headlines. Vary letter-spacing.
2. **Color** — shift blue by 15 degrees. Add unexpected accent. One "signal" color for CTAs.
3. **Depth and surface** — replace uniform shadows with layered system. Subtle background texture.
4. **Imagery** — illustrations, abstract shapes, actual product screenshots.
5. **Spacing variety** — generous hero whitespace (120px+), tighter feature grids. Rhythm of density creates personality.

Underlying principle: **identity comes from specific, deliberate deviations from defaults.** Three to four strong choices cascade into a distinct feel.

---

## B1: DataTable Component API

The design challenge: serve both "drop it in and it works" and "I need full control." The API should enable **indwelling** — developers think THROUGH the table to their domain, not ABOUT the table's configuration.

MVP: 3 props (columns, data, keyExtractor). Full: controlled/uncontrolled duality (sort vs defaultSort), onStateChange as server-side integration point, toolbar as render prop receiving state.

Key decisions:
- **Controlled/uncontrolled duality** — simple cases use defaultSort; server-side uses sort + onSortChange
- **totalRows presence signals server mode** — no mode enum needed
- **toolbar is a render prop** — respects from-to boundary: table owns display, consumer owns actions
- **Deliberately excluded**: virtualization, DnD rows, inline editing. A table that tries to do everything becomes a table no one can dwell in.
