# Baseline Responses (No Skill) — Round 1

## A1: State Management Decision

**Recommended architecture: CRDT-based state with event sourcing.**

Core: Use Yjs (or Automerge) as CRDT layer. CRDTs give automatic conflict resolution without a central authority, solving real-time sync and offline support simultaneously.

Architecture stack:
1. **Document model:** Yjs `Y.Doc` — shared data structure, edits merge automatically
2. **Sync transport:** `y-websocket` for real-time sync with server relay. Offline edits accumulate locally, merge cleanly on reconnect
3. **Undo/redo:** `Y.UndoManager` tracks stacks per-origin. Each user gets independent undo/redo
4. **React binding:** Subscribe to `Y.Doc.on('update', ...)`. CRDT is source of truth, not useState
5. **Optimistic updates:** Inherent — edits apply locally to CRDT instantly
6. **Persistence:** Periodically snapshot Y.Doc to backend

Why not Redux/Zustand? You'd reimagine conflict resolution from scratch. Why not Liveblocks/Replicache? Valid managed alternatives, but less control.

Key risk: CRDT document size growth. Plan for garbage collection and state compaction.

---

## R1: Architecture Smells in UserDashboard

1. **God Component** — owns user data, posts, notifications, analytics, UI state, all rendering. When any piece changes, entire tree re-renders.
2. **All-or-nothing loading** — Promise.all means slow fetchAnalytics blocks showing the user header. If any request fails, everything fails.
3. **No data refetching/cache** — Navigating away and back re-fetches everything. No stale-while-revalidate.
4. **Non-null assertions (user!, analytics!)** — crash waiting to happen if loading/error gates change.
5. **Fetching invisible data** — Analytics fetched even if user stays on "posts" tab.

Refactored approach: Split into focused components with colocated data. Each child owns its own fetching, loading/error states, and local UI state. Independent Suspense boundaries allow progressive rendering.

---

## U1: Analytics Dashboard Layout

Layout: 240px fixed sidebar + 1200px main content. Sidebar has account switcher, nav, quick account status. Main has top bar (filters), metrics strip (4 KPI cards), 2-column grid (60/40 split): Performance Chart + Content Calendar on top, Account Comparison + Mentions Inbox on bottom.

Spacing: 4px base unit. Sidebar padding 16px. Grid gap 16px. Card padding 20px. Metrics strip gap 12px.

Power user features: unread count on sidebar, today highlighted in calendar, trend arrows and sparklines in metrics.

---

## V3: Aesthetic Diagnosis

Diagnosis: **zero visual decisions that are uniquely yours.** Every choice is a default or most popular option.

- Inter = most-used SaaS font
- #3B82F6 = literally Tailwind blue-500
- Default shadows/radii = on millions of sites
- Unsplash stock = recognizable aesthetic

Fixes:
1. Typography — replace Inter with Instrument Sans, General Sans, or Satoshi
2. Color — shift off defaults (teal-blue, indigo, or warm periwinkle). Add one tension accent.
3. Replace stock photos with illustration or abstract shapes/gradients
4. Break grid subtly — off-center hero, oversized numbers, mixed radii
5. Micro-interactions — hover transitions, scroll reveals

Cheapest combo: New typeface + shifted color + replace hero photo. Two hours, completely different feel.

---

## B1: Component API Design

**Minimum Viable:**
```typescript
interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  keyExtractor: (row: T) => string;
}
```

**Full-featured:** Controlled state pattern throughout (sort, pagination, selection, filters all follow value + onChange). totalCount signals server-side mode. Column-level render for cell customization. Set<string> for selection (O(1) lookup).

Design decisions: Controlled state makes server-side and client-side identical. keyExtractor over rowKey for flexibility. render on Column not renderRow for composability.
