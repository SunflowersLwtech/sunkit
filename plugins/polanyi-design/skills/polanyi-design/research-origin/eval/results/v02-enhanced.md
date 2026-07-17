# V02 Enhanced Responses — Round 2

## A1: State Management
Lead: "The collaboration model IS the state — so build around a CRDT document, not React state that you sync."
Architecture: Yjs Y.Doc + y-indexeddb + y-websocket + Y.UndoManager per user + useSyncExternalStore.
Key insight: "Do NOT useState for document content. Use useSyncExternalStore."
What NOT to do: Don't put Yjs in React Context/Redux (two sources of truth). Don't serialize to JSON (use Y.encodeStateAsUpdate). Don't useEffect to "sync" (flow is one-directional).
Tacit principle: "When your domain IS distributed mutation, your state primitive must be a convergent data type."

## R1: Code Review
Lead: "This component has one focal problem: it treats four independent data lifecycles as one monolithic fetch."
Five issues ALL enumerated:
1. Promise.all couples unrelated data domains into one loading boundary (focal fix)
2. Non-null assertions lying to TypeScript
3. Search/filter/sort state belongs with PostsTab, not dashboard
4. Single error string collapses four failure modes
5. Missing userId change cleanup / stale response risk
Concrete refactored code provided.
What NOT to do: "Do not reach for global state — this is a data-fetching decomposition problem."

## U1: Dashboard Layout
Lead: "This is a monitoring cockpit — layout must minimize scan-time for the 10x/daily glance pattern."
Full ASCII layout with pixel values (960px left + 440px right).
Spacing: 16px base, 8/16/24/32 multiples. Column gutter 32px.
Component hierarchy with concrete props.
Tacit rationale: Action feed at right-top because it's the only panel demanding behavioral response. Calendar below because scheduling is planning, not monitoring.

## V3: Aesthetic Diagnosis
Lead: "Your landing page integrates into a generic gestalt because every visual decision defaults to the same Tailwind starter kit."
Five interventions with specific values:
1. Typography: heading typeface only (Instrument Serif, Space Grotesk, Cabinet Grotesk)
2. Color: shift hue 15-20 degrees, domain-appropriate
3. Shadow hierarchy: most surfaces flat, shadow only for floating elements, two corner radii
4. Replace stock with illustration/gradient/product screenshot
5. Micro-typography: 56-72px hero, -0.02em letter-spacing, 1.7 line-height body
What NOT to do: "Do not add more colors, animations, or dark mode. Identity comes from constraint."

## B1: Component API
Lead: "A table API must let the common case be one line and the complex case be possible."
MVP: 2 props (columns, data). Full: data vs fetchData (infers mode from prop presence).
rowId required only when selectable=true.
FilterConfig type system with text/select/date-range/number-range.
Controlled vs uncontrolled pattern throughout.
What NOT to include: Virtualization (belongs in wrapper or opt-in boolean with dynamic import).
