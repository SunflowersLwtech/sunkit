import { describe, it, expect, beforeEach } from 'vitest'
import { openDatabase, type Db } from '../../src/db/db.ts'
import { MessageStore } from '../../src/messages/store.ts'
import { Fanout } from '../../src/fanout.ts'
import { PresenceRegistry } from '../../src/presence/registry.ts'
import { buildApp } from '../../src/app.ts'
import { hashToken, generateRawToken } from '../../src/auth/hash.ts'

function seed(db: Db) {
  const now = new Date().toISOString()
  db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)").run('t1','acme',7,now)
  for (const h of ['alice','bob']) {
    db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)")
      .run(`h_${h}`, 't1', h, h, now)
  }
  const alice = generateRawToken(); const bob = generateRawToken()
  db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)").run('tk_a','h_alice',hashToken(alice),'laptop','human',now)
  db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)").run('tk_b','h_bob',hashToken(bob),'laptop','human',now)
  return { alice, bob }
}

async function readNEvents(stream: ReadableStream<Uint8Array>, n: number, timeoutMs = 2000): Promise<string[]> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  const events: string[] = []
  let buf = ''
  const deadline = Date.now() + timeoutMs
  while (events.length < n && Date.now() < deadline) {
    const remaining = deadline - Date.now()
    if (remaining <= 0) break
    const timeoutPromise = new Promise<{ value: undefined; done: true }>(resolve =>
      setTimeout(() => resolve({ value: undefined, done: true }), remaining)
    )
    const { value, done } = await Promise.race([reader.read(), timeoutPromise])
    if (done) break
    buf += decoder.decode(value)
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? ''
    events.push(...parts.filter(p => p.trim().length > 0))
  }
  try { await reader.cancel() } catch { /* ignore */ }
  return events
}

describe('GET /v1/stream', () => {
  let db: Db
  let app: ReturnType<typeof buildApp>
  let tok: { alice: string; bob: string }
  beforeEach(() => {
    db = openDatabase(':memory:')
    tok = seed(db)
    app = buildApp({ db, store: new MessageStore(db), fanout: new Fanout(), presence: new PresenceRegistry(), now: () => new Date() })
  })

  it('delivers a posted message to the target\'s open stream', async () => {
    const streamRes = await app.request('/v1/stream', { headers: { authorization: `Bearer ${tok.bob}` } })
    expect(streamRes.status).toBe(200)
    expect(streamRes.headers.get('content-type')).toContain('text/event-stream')

    await app.request('/v1/messages', {
      method: 'POST',
      headers: { authorization: `Bearer ${tok.alice}`, 'content-type': 'application/json' },
      body: JSON.stringify({ to: 'bob', kind: 'chat', content: 'hello' })
    })
    const events = await readNEvents(streamRes.body!, 1)
    const msg = events.find(e => e.includes('event: message'))
    expect(msg).toBeDefined()
    expect(msg!).toContain('"from":"alice"')
    expect(msg!).toContain('"content":"hello"')
  })

  it('?since=<id> replays buffered messages in order', async () => {
    for (const n of ['1','2','3']) {
      await app.request('/v1/messages', {
        method: 'POST',
        headers: { authorization: `Bearer ${tok.alice}`, 'content-type': 'application/json' },
        body: JSON.stringify({ to: 'bob', kind: 'chat', content: n })
      })
    }
    const streamRes = await app.request('/v1/stream?since=msg_00000000000000000000000000',
      { headers: { authorization: `Bearer ${tok.bob}` } })
    const events = await readNEvents(streamRes.body!, 3)
    const msgEvents = events.filter(e => e.includes('event: message'))
    expect(msgEvents).toHaveLength(3)
    expect(msgEvents[0]!).toContain('"content":"1"')
    expect(msgEvents[2]!).toContain('"content":"3"')
  })

  it('401 without auth', async () => {
    const res = await app.request('/v1/stream')
    expect(res.status).toBe(401)
  })
})
