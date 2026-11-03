// What the desk's Mesh page is sent (foldrender.dev/desk/mesh): pure functions, no I/O, so the
// pusher (observe.mjs) and its tests (observe.test.mjs) share them.
//
//   peers(sessions, names)           one `peer` thing per session on the relay (GET /v1/sessions)
//   foldEvents(state, events)        the delivery log (GET /v1/events) folded into one row a message
//   messages(state, names, opts)     the newest of those rows as `message` things
//
// A thing is what a desk feed takes (PUT <api>/desk/<id>/feed/<source>): {key, kind, title,
// state, body}. Nothing here carries a message's words, a token or an address. A body holds only
// what changes with its state (no ages, no last-seen times): each changed thing is a row the desk
// counts against its writes for the day.

/** At most this many messages go in a snapshot (the desk holds 200), and none older than a day. */
export const MESSAGES_KEPT = 200
export const MESSAGES_MAX_AGE_MS = 24 * 3600_000
/** The desk holds 100 peers. */
export const PEERS_KEPT = 100

const PEER_STATE = { busy: 'busy', idle: 'idle', reconnecting: 'away', unknown: 'unknown' }

/** The desk's name for a device or a herdr machine; a name not in `names` is kept as it is. */
export function machineName(names, ...candidates) {
  for (const c of candidates) {
    if (!c) continue
    const k = String(c)
    if (names[k] !== undefined) return names[k]
    if (names[k.toLowerCase()] !== undefined) return names[k.toLowerCase()]
  }
  return candidates.find(Boolean) ?? null
}

const baseName = (p) => {
  const parts = String(p || '').split(/[\\/]+/).filter(Boolean)
  return parts.length ? parts[parts.length - 1] : null
}
const clip = (s, n) => (s == null ? undefined : String(s).slice(0, n))
const drop = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== ''))

/** The relay's sessions as `peer` things, keyed by their ref. */
export function peers(sessions, names = {}) {
  const out = []
  const seen = new Set()
  for (const s of sessions) {
    if (!s || !s.ref || seen.has(s.ref)) continue
    seen.add(s.ref)
    out.push({
      key: s.ref,
      kind: 'peer',
      title: clip(s.name || s.account || s.ref, 120),
      state: PEER_STATE[s.status] ?? 'unknown',
      body: drop({
        machine: clip(machineName(names, s.herdr?.machine, s.device), 40),
        account: clip(s.account, 40),
        ref: s.ref,
        harness: clip(s.agent, 24),
        model: clip(s.model, 60),
        mode: s.mode === 'pull' ? 'pull' : 'push',
        where: clip(s.repo || baseName(s.cwd), 60),
      }),
    })
    if (out.length >= PEERS_KEPT) break
  }
  return out
}

/** A fresh fold: the cursor in the log and one row a message seen. */
export function newState() {
  return { seq: null, byId: new Map() }
}

/**
 * Folds rows of the delivery log into one row a message: a `sent` row says who to whom and when;
 * a `delivered` row adds when, how long (the relay's own latency_ms, as logged) and how.
 */
export function foldEvents(state, events) {
  for (const e of events) {
    if (!e || !e.msg_id) continue
    const m = state.byId.get(e.msg_id) ?? { msg_id: e.msg_id }
    m.from = { ...(m.from ?? {}), ...(e.from ?? {}) }
    // A delivered row names the session whose stream took it: that is who it went to.
    m.to = { ...(m.to ?? {}), ...(e.to ?? {}) }
    m.sent_at = e.sent_at ?? m.sent_at
    if (typeof e.bytes === 'number') m.bytes = e.bytes
    if (e.state === 'delivered') {
      m.state = 'delivered'
      m.at = e.at
      if (typeof e.latency_ms === 'number') m.latency_ms = e.latency_ms
      if (e.via) m.via = e.via
    } else if (!m.state) {
      m.state = 'sent'
    }
    state.byId.set(e.msg_id, m)
  }
  return state
}

/** Drops what is too old to send, so the fold does not grow without end. */
export function prune(state, now = Date.now()) {
  for (const [id, m] of state.byId) {
    if (now - Date.parse(m.sent_at || '') > MESSAGES_MAX_AGE_MS) state.byId.delete(id)
  }
  const rest = [...state.byId.values()].sort((a, b) => Date.parse(b.sent_at) - Date.parse(a.sent_at))
  for (const m of rest.slice(MESSAGES_KEPT * 2)) state.byId.delete(m.msg_id)
  return state
}

function party(p, names) {
  return drop({
    name: clip(p?.name || p?.account || '?', 120),
    machine: clip(machineName(names, p?.device), 40),
    account: clip(p?.account, 40),
    ref: p?.ref,
  })
}

/** The newest messages of the fold as `message` things, keyed by their id. */
export function messages(state, names = {}, { now = Date.now() } = {}) {
  return [...state.byId.values()]
    .filter((m) => m.sent_at && now - Date.parse(m.sent_at) <= MESSAGES_MAX_AGE_MS)
    .sort((a, b) => Date.parse(b.sent_at) - Date.parse(a.sent_at))
    .slice(0, MESSAGES_KEPT)
    .map((m) => {
      const from = party(m.from, names)
      const to = party(m.to, names)
      return {
        key: m.msg_id,
        kind: 'message',
        title: `${from.name} → ${to.name}`.slice(0, 200),
        state: m.state === 'delivered' ? 'delivered' : 'sent',
        body: drop({
          system: 'mesh',
          msg_id: m.msg_id,
          from,
          to,
          sent_at: m.sent_at,
          at: m.state === 'delivered' ? m.at : undefined,
          latency_ms: m.state === 'delivered' ? m.latency_ms : undefined,
          via: m.state === 'delivered' ? m.via : undefined,
          bytes: m.bytes,
        }),
      }
    })
}
