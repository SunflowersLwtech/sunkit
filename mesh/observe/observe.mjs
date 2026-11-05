#!/usr/bin/env node
// mesh observe — the mesh as the desk's Mesh page shows it (foldrender.dev/desk/mesh): who is on
// it, where, with which harness and model, busy or idle, and each message's delivery.
//
//   node mesh/observe/observe.mjs                          # what would be sent, as JSON; nothing sent
//   node mesh/observe/observe.mjs --desk-feed              # send it to the desk once
//   node mesh/observe/observe.mjs --desk-feed --every 60   # and again every 60 s, until stopped
//
// Reads the relay with GETs only: /v1/sessions (who is on) and /v1/events (the delivery log, from
// where the last read stopped). Nothing is written to the mesh. Sends the desk one feed snapshot
// (PUT <api>/desk/<desk>/feed/<source>, a desk feed token): a `peer` for each session and a
// `message` for each of the latest messages, with the latency the relay logged. A snapshot
// replaces the last one; one is sent only when the relay answered, so a relay that is down never
// empties the page.
//
// Environment:
//   MESH_HOME                     where config.json and the token are (default ~/.claude-mesh);
//   MESH_RELAY, MESH_TOKEN_FILE   or name the relay and the token file directly
//   FOLDRENDER_DESK_TOKEN_FILE    a file (mode 600) holding the desk's feed token (frdk_…)
//   FOLDRENDER_API                default https://foldrender.dev/artifacts/api
//   FOLDRENDER_DESK               default desk (the token's own desk)
//   MESH_DESK_SOURCE              default mesh (the feed's name on the desk)
//   MESH_DESK_MACHINES            a JSON file {"<device or herdr machine>": "<the desk's name>"}
// Tokens are read from files and sent in request headers only: never on a command line, never
// printed. Each run prints one JSON line a send (counts, statuses), nothing else.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { foldEvents, messages, newState, peers, prune } from './feed.mjs'

const TIMEOUT_MS = 15_000
const EVENT_PAGE = 500
/** Pages of the log read a send at most: a backlog larger than this is caught up over several. */
const EVENT_PAGES = 4

export function config(env = process.env) {
  const home = env.MESH_HOME ?? path.join(os.homedir(), '.claude-mesh')
  let cfg = {}
  try { cfg = JSON.parse(fs.readFileSync(path.join(home, 'config.json'), 'utf8')) } catch { /* env names them */ }
  const relay = String(env.MESH_RELAY ?? cfg.relay_url ?? '').replace(/\/$/, '')
  const tokenFile = env.MESH_TOKEN_FILE ?? cfg.token_path ?? path.join(home, 'token')
  let names = {}
  if (env.MESH_DESK_MACHINES) names = JSON.parse(fs.readFileSync(env.MESH_DESK_MACHINES, 'utf8'))
  return {
    relay,
    meshToken: () => fs.readFileSync(tokenFile, 'utf8').trim(),
    deskToken: () => (env.FOLDRENDER_DESK_TOKEN_FILE ? fs.readFileSync(env.FOLDRENDER_DESK_TOKEN_FILE, 'utf8').trim() : ''),
    api: String(env.FOLDRENDER_API ?? 'https://foldrender.dev/artifacts/api').replace(/\/$/, ''),
    desk: env.FOLDRENDER_DESK ?? 'desk',
    source: env.MESH_DESK_SOURCE ?? 'mesh',
    names,
  }
}

async function relayGet(cfg, p) {
  const r = await fetch(cfg.relay + p, { headers: { authorization: `Bearer ${cfg.meshToken()}` }, signal: AbortSignal.timeout(TIMEOUT_MS) })
  if (!r.ok) throw new Error(`relay ${p.split('?')[0]}: HTTP ${r.status}`)
  return r.json()
}

/** Reads the log from where the fold stopped (the latest page when it has not read any yet). */
export async function readEvents(cfg, state) {
  let n = 0
  for (let i = 0; i < EVENT_PAGES; i++) {
    const q = state.seq === null ? `?limit=${EVENT_PAGE}` : `?since_seq=${state.seq}&limit=${EVENT_PAGE}`
    const page = await relayGet(cfg, `/v1/events${q}`)
    foldEvents(state, page.events ?? [])
    n += (page.events ?? []).length
    const had = state.seq
    state.seq = page.seq
    if (had === null || (page.events ?? []).length < EVENT_PAGE) break
  }
  return n
}

/** One snapshot from the relay: {items, peers, messages, events}. Throws when the relay does not answer. */
export async function snapshot(cfg, state, now = Date.now()) {
  // The sessions must come; the log may not (an older relay has none, or it said 429): then the
  // messages are what was read before, and the next send reads on from there.
  const [sessions, events] = await Promise.all([relayGet(cfg, '/v1/sessions'), readEvents(cfg, state).catch((err) => ({ error: String(err?.message ?? err) }))])
  prune(state, now)
  const p = peers(sessions, cfg.names)
  const m = messages(state, cfg.names, { now })
  return { items: [...p, ...m], peers: p.length, messages: m.length, events: typeof events === 'number' ? events : undefined, events_error: events?.error }
}

/**
 * Sends a snapshot to the desk. A thing the desk refuses (400/422 naming its key: a name that
 * looks like a secret, say) is left out and the rest sent again, three times at most.
 */
export async function send(cfg, items, every) {
  let left = items
  const dropped = []
  for (let i = 0; i < 4; i++) {
    const r = await fetch(`${cfg.api}/desk/${encodeURIComponent(cfg.desk)}/feed/${encodeURIComponent(cfg.source)}`, {
      method: 'PUT',
      headers: { authorization: `Bearer ${cfg.deskToken()}`, 'content-type': 'application/json', 'foldrender-api': '2', 'user-agent': 'mesh-observe' },
      body: JSON.stringify({ every_s: every, items: left }),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    })
    const out = await r.json().catch(() => null)
    const prefix = `${cfg.source}/`
    const bad = (r.status === 400 || r.status === 422) && out?.key ? String(out.key).startsWith(prefix) ? String(out.key).slice(prefix.length) : String(out.key) : null
    if (!bad) return { status: r.status, changed: out?.changed, removed: out?.removed, error: r.ok ? undefined : out?.error, dropped }
    dropped.push({ key: bad, error: out.error, field: out.field })
    left = left.filter((it) => it.key !== bad)
    // Everything was refused: an empty replace would wipe the page and read as success.
    if (i === 3 || left.length === 0) return { status: r.status, error: out?.error ?? 'every thing was refused', dropped }
  }
  return { status: 0, dropped }
}

async function once(cfg, state, every) {
  const at = new Date().toISOString()
  let snap
  try {
    snap = await snapshot(cfg, state)
  } catch (err) {
    console.log(JSON.stringify({ at, relay: 'failed', error: String(err?.message ?? err).slice(0, 200), sent: false }))
    return false
  }
  try {
    const r = await send(cfg, snap.items, every)
    console.log(JSON.stringify({ at, peers: snap.peers, messages: snap.messages, events: snap.events, events_error: snap.events_error, desk: r.status, changed: r.changed, removed: r.removed, error: r.error, dropped: r.dropped.length ? r.dropped : undefined }))
    return r.status === 200
  } catch (err) {
    console.log(JSON.stringify({ at, peers: snap.peers, messages: snap.messages, desk: 'failed', error: String(err?.message ?? err).slice(0, 200) }))
    return false
  }
}

async function main(argv) {
  const cfg = config()
  if (!cfg.relay) throw new Error('no relay: set MESH_RELAY or MESH_HOME (config.json relay_url)')
  const state = newState()
  if (!argv.includes('--desk-feed')) {
    const snap = await snapshot(cfg, state)
    console.log(JSON.stringify(snap, null, 2))
    return
  }
  if (!cfg.deskToken()) throw new Error('no desk token: set FOLDRENDER_DESK_TOKEN_FILE to a file holding the feed token')
  const i = argv.indexOf('--every')
  const every = i >= 0 ? Number(argv[i + 1]) : 0
  if (i >= 0 && !(Number.isInteger(every) && every >= 15 && every <= 3600)) throw new Error('--every is 15 to 3600 seconds')
  if (!every) {
    process.exitCode = (await once(cfg, state, 60)) ? 0 : 1
    return
  }
  let stop = false
  for (const sig of ['SIGTERM', 'SIGINT']) process.on(sig, () => { stop = true })
  while (!stop) {
    const t = Date.now()
    await once(cfg, state, every)
    // Sleep in short steps so a stop is quick.
    while (!stop && Date.now() - t < every * 1000) await new Promise((r) => setTimeout(r, 500))
  }
}

const invoked = process.argv[1] && import.meta.url === new URL(`file://${path.resolve(process.argv[1])}`).href
if (invoked) {
  main(process.argv.slice(2)).catch((err) => {
    console.error(`mesh-observe: ${err?.message ?? err}`)
    process.exit(1)
  })
}
