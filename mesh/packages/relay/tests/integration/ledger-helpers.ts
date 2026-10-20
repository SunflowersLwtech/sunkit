import { openDatabase, type Db } from '../../src/db/db.ts'
import { MessageStore } from '../../src/messages/store.ts'
import { Fanout } from '../../src/fanout.ts'
import { PresenceRegistry } from '../../src/presence/registry.ts'
import { SessionRegistry } from '../../src/sessions/registry.ts'
import { buildApp } from '../../src/app.ts'
import { hashToken, generateRawToken } from '../../src/auth/hash.ts'
import { setGrant } from '../../src/grants.ts'
import type { Role } from '@claude-mesh/shared'

export interface TokenSpec {
  id: string
  handle: string
  label: string
  tier?: 'human' | 'admin'
  grant?: { role: Role; workgroup: string; visible?: string[]; machine?: string | null }
}

/** One team, one human per distinct handle, one token per spec. Returns raw tokens by spec id. */
export function seed(db: Db, specs: TokenSpec[]): Record<string, string> {
  const now = new Date().toISOString()
  db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)").run('t1', 'acme', 7, now)
  const raws: Record<string, string> = {}
  for (const handle of new Set(specs.map(s => s.handle))) {
    db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)")
      .run(`h_${handle}`, 't1', handle, handle, now)
  }
  for (const s of specs) {
    const raw = generateRawToken()
    db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)")
      .run(s.id, `h_${s.handle}`, hashToken(raw), s.label, s.tier ?? 'human', now)
    if (s.grant) setGrant(db, s.id, { role: s.grant.role, workgroup: s.grant.workgroup, visible: s.grant.visible ?? [], machine: s.grant.machine ?? null }, now)
    raws[s.id] = raw
  }
  return raws
}

export interface Harness {
  db: Db
  app: ReturnType<typeof buildApp>
  sessions: SessionRegistry
  clock: { now: number }
}

export function harness(specs: TokenSpec[]): Harness & { tok: Record<string, string> } {
  const db = openDatabase(':memory:')
  const tok = seed(db, specs)
  const clock = { now: Date.parse('2026-10-20T02:00:00Z') }
  const sessions = new SessionRegistry(() => clock.now)
  const app = buildApp({
    db, store: new MessageStore(db), fanout: new Fanout(), presence: new PresenceRegistry(),
    sessions, now: () => new Date(clock.now),
  })
  return { db, app, sessions, clock, tok }
}

export function req(app: Harness['app'], token: string, method: string, path: string, body?: unknown, headers: Record<string, string> = {}) {
  return app.request(path, {
    method,
    headers: {
      authorization: `Bearer ${token}`,
      ...(body !== undefined ? { 'content-type': 'application/json' } : {}),
      ...headers,
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
}

/** Opens a session-bound SSE stream and returns the response (keep it to keep the session attached). */
export function openSession(app: Harness['app'], token: string, session: string, name: string, extra = '') {
  return app.request(`/v1/stream?session=${session}&name=${name}${extra}`, { headers: { authorization: `Bearer ${token}` } })
}

export interface SseEvent { event: string; data: string }

/** Reads SSE events of the given names until `n` arrive or the timeout passes. */
export async function readSse(stream: ReadableStream<Uint8Array>, n: number, events: string[] = ['message'], timeoutMs = 600): Promise<SseEvent[]> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  const out: SseEvent[] = []
  let buf = ''
  const deadline = Date.now() + timeoutMs
  while (out.length < n && Date.now() < deadline) {
    const timeout = new Promise<{ value: undefined; done: true }>(r =>
      setTimeout(() => r({ value: undefined, done: true }), Math.max(0, deadline - Date.now())))
    const { value, done } = await Promise.race([reader.read(), timeout])
    if (done) break
    buf += decoder.decode(value)
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? ''
    for (const p of parts) {
      const ev = /^event: (.*)$/m.exec(p)?.[1] ?? 'message'
      const data = p.split('\n').filter(l => l.startsWith('data: ')).map(l => l.slice(6)).join('\n')
      if (events.includes(ev)) out.push({ event: ev, data })
    }
  }
  try { await reader.cancel() } catch { /* ignore */ }
  return out
}

export const S = {
  a1: 's_01hrk7y0000000000000aaaaa1',
  a2: 's_01hrk7y0000000000000aaaaa2',
  b1: 's_01hrk7y0000000000000bbbbb1',
  b2: 's_01hrk7y0000000000000bbbbb2',
  t1: 's_01hrk7y0000000000000ttttt1',
  o1: 's_01hrk7y0000000000000ooooo1',
}
