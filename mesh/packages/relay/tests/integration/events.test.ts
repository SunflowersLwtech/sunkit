import { describe, it, expect, beforeEach } from 'vitest'
import { openDatabase, type Db } from '../../src/db/db.ts'
import { MessageStore, EVENT_RETENTION_DAYS, type DeliveryEventView } from '../../src/messages/store.ts'
import { Fanout } from '../../src/fanout.ts'
import { PresenceRegistry } from '../../src/presence/registry.ts'
import { SessionRegistry } from '../../src/sessions/registry.ts'
import { buildApp } from '../../src/app.ts'
import { hashToken, generateRawToken } from '../../src/auth/hash.ts'
import { setGrant } from '../../src/grants.ts'
import { EVENT_READS_PER_MINUTE } from '../../src/routes/events.ts'

const S_ALICE = 's_01hrk7y0000000000000aaaaaa'
const S_BOB1 = 's_01hrk7y0000000000000bbbbb1'
const CONTENT = '你好 bob, secret-ish words'

function seed(db: Db) {
  const now = new Date().toISOString()
  db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)").run('t1', 'acme', 7, now)
  const raw: Record<string, string> = {}
  for (const [h, label] of [['alice', 'mac-a'], ['bob', 'msi'], ['carol', 'n150']] as const) {
    db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)").run(`h_${h}`, 't1', h, h, now)
    raw[h] = generateRawToken()
    db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)")
      .run(`tk_${h}`, `h_${h}`, hashToken(raw[h]!), label, 'human', now)
  }
  return raw as { alice: string; bob: string; carol: string }
}

/** Reads until `n` message events arrived (this is what drives a stream's backlog), then closes. */
async function drain(res: Response, n: number, timeoutMs = 800): Promise<number> {
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let seen = 0
  const deadline = Date.now() + timeoutMs
  while (seen < n && Date.now() < deadline) {
    const timeout = new Promise<{ value: undefined; done: true }>(r => setTimeout(() => r({ value: undefined, done: true }), Math.max(0, deadline - Date.now())))
    const { value, done } = await Promise.race([reader.read(), timeout])
    if (done) break
    buf += decoder.decode(value)
    seen = buf.split('\n\n').filter(p => p.includes('event: message')).length
  }
  try { await reader.cancel() } catch { /* ignore */ }
  return seen
}

describe('GET /v1/events (delivery log)', () => {
  let db: Db
  let app: ReturnType<typeof buildApp>
  let store: MessageStore
  let tok: { alice: string; bob: string; carol: string }
  let t: number
  const clock = () => new Date(t)

  const open = (token: string, session: string, name: string, since?: string) =>
    app.request(`/v1/stream?session=${session}&name=${name}${since ? `&since=${since}` : ''}`, { headers: { authorization: `Bearer ${token}` } })
  const post = (token: string, body: unknown, senderSession?: string) =>
    app.request('/v1/messages', {
      method: 'POST',
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json', ...(senderSession ? { 'x-mesh-session': senderSession } : {}) },
      body: JSON.stringify(body),
    })
  const events = async (token: string, query = ''): Promise<{ status: number; text: string; body: { events: DeliveryEventView[]; seq: number } }> => {
    const res = await app.request(`/v1/events${query}`, { headers: { authorization: `Bearer ${token}` } })
    const text = await res.text()
    return { status: res.status, text, body: res.status === 200 ? JSON.parse(text) : null }
  }

  beforeEach(() => {
    db = openDatabase(':memory:')
    tok = seed(db)
    t = Date.parse('2026-11-03T05:00:00.000Z')
    store = new MessageStore(db, clock)
    app = buildApp({ db, store, fanout: new Fanout(), presence: new PresenceRegistry(), sessions: new SessionRegistry(), now: clock })
  })

  it('logs a live delivery as sent then delivered, with names, refs and devices, and never the content', async () => {
    await open(tok.alice, S_ALICE, 'alice-main')
    await open(tok.bob, S_BOB1, 'repo-x')
    const sent = await post(tok.alice, { to: 'bob', to_session: S_BOB1, kind: 'chat', content: CONTENT }, S_ALICE)
    expect(sent.status).toBe(201)
    const id = (await sent.json() as { id: string }).id

    const r = await events(tok.alice)
    expect(r.status).toBe(200)
    expect(r.text).not.toContain('secret-ish')
    expect(r.text).not.toContain('你好')
    const at = new Date(t).toISOString()
    const party = {
      from: { account: 'alice', name: 'alice-main', ref: 'aaaaaa', device: 'mac-a' },
      to: { account: 'bob', name: 'repo-x', ref: 'bbbbb1', device: 'msi' },
    }
    expect(r.body.events).toEqual([
      { seq: expect.any(Number), at, msg_id: id, state: 'sent', ...party, bytes: Buffer.byteLength(CONTENT), sent_at: at },
      { seq: expect.any(Number), at, msg_id: id, state: 'delivered', ...party, bytes: Buffer.byteLength(CONTENT), sent_at: at, latency_ms: 0, via: 'live' },
    ])
    expect(r.body.events[0]!.seq).toBeLessThan(r.body.events[1]!.seq)
    expect(r.body.seq).toBe(r.body.events[1]!.seq)
  })

  it('a message nobody was online for stays sent; the stream that later takes it logs the wait as latency', async () => {
    const sent = await post(tok.alice, { to: 'bob', kind: 'chat', content: 'later' })
    const id = (await sent.json() as { id: string }).id
    let r = await events(tok.bob)
    expect(r.body.events.map(e => [e.msg_id, e.state])).toEqual([[id, 'sent']])
    expect(r.body.events[0]!.to).toEqual({ account: 'bob' })

    t += 1_500
    expect(await drain(await open(tok.bob, S_BOB1, 'repo-x'), 1)).toBe(1)
    r = await events(tok.bob)
    const d = r.body.events.find(e => e.state === 'delivered')!
    expect(d).toMatchObject({ msg_id: id, via: 'backlog', latency_ms: 1_500, to: { account: 'bob', name: 'repo-x', device: 'msi' } })
    expect(d.at).toBe(new Date(t).toISOString())
  })

  it('logs the first delivery only: a replay to a reconnecting stream adds nothing', async () => {
    const first = await post(tok.alice, { to: 'bob', kind: 'chat', content: 'once' })
    const id = (await first.json() as { id: string }).id
    expect(await drain(await open(tok.bob, S_BOB1, 'repo-x'), 1)).toBe(1)
    t += 60_000
    // since= an id before it replays the message to the new stream
    expect(await drain(await open(tok.bob, S_BOB1, 'repo-x', 'msg_00000000000000000000000000'), 1)).toBe(1)
    const r = await events(tok.bob)
    expect(r.body.events.filter(e => e.msg_id === id).map(e => e.state)).toEqual(['sent', 'delivered'])
    expect(r.body.events.find(e => e.state === 'delivered')!.latency_ms).toBe(0)
  })

  it('pages: tail without since_seq, in order with it, and resumes where it stopped', async () => {
    const ids: string[] = []
    for (const content of ['a', 'b', 'c']) {
      t += 1_000
      ids.push((await (await post(tok.alice, { to: 'bob', kind: 'chat', content })).json() as { id: string }).id)
    }
    const tail = await events(tok.alice, '?limit=2')
    expect(tail.body.events.map(e => e.msg_id)).toEqual([ids[1], ids[2]])
    const p1 = await events(tok.alice, '?since_seq=0&limit=2')
    expect(p1.body.events.map(e => e.msg_id)).toEqual([ids[0], ids[1]])
    expect(p1.body.seq).toBe(p1.body.events[1]!.seq)
    const p2 = await events(tok.alice, `?since_seq=${p1.body.seq}&limit=2`)
    expect(p2.body.events.map(e => e.msg_id)).toEqual([ids[2]])
    const p3 = await events(tok.alice, `?since_seq=${p2.body.seq}`)
    expect(p3.body.events).toEqual([])
    expect(p3.body.seq).toBe(p2.body.seq)
    for (const bad of ['?since_seq=-1', '?since_seq=x', '?limit=0', '?limit=501', '?limit=2.5']) {
      expect((await events(tok.alice, bad)).status).toBe(400)
    }
  })

  it('shows a row only to readers who may see the sender\'s workgroup and the addressed session\'s', async () => {
    const at = new Date().toISOString()
    setGrant(db, 'tk_alice', { role: 'worker', workgroup: 'team', visible: ['team', 'bobwg'], machine: null }, at)
    setGrant(db, 'tk_bob', { role: 'worker', workgroup: 'bobwg', visible: ['bobwg', 'team'], machine: null }, at)
    await open(tok.bob, S_BOB1, 'repo-x')
    const toBobWg = await post(tok.alice, { to: 'bob', to_session: S_BOB1, kind: 'chat', content: 'x' })
    expect(toBobWg.status).toBe(201)
    const idA = (await toBobWg.json() as { id: string }).id
    // carol sees team only: the sender is in team, the addressed session is not
    expect((await events(tok.carol)).body.events).toEqual([])
    expect((await events(tok.alice)).body.events.map(e => e.msg_id)).toEqual([idA, idA])

    setGrant(db, 'tk_alice', { role: 'worker', workgroup: 'priv', visible: ['priv'], machine: null }, at)
    const fromPriv = await post(tok.alice, { to: 'carol', kind: 'chat', content: 'y' })
    const idB = (await fromPriv.json() as { id: string }).id
    expect((await events(tok.carol)).body.events.map(e => e.msg_id)).not.toContain(idB)
    expect((await events(tok.alice)).body.events.map(e => e.msg_id)).toEqual([idB])
  })

  it('does not log presence or permission traffic', async () => {
    store.insert('t1', 'alice', { to: '@team', kind: 'presence_update', content: '{}' })
    expect((await events(tok.alice)).body.events).toEqual([])
  })

  it('rate-limits reads per token', async () => {
    for (let i = 0; i < EVENT_READS_PER_MINUTE; i++) expect((await events(tok.alice)).status).toBe(200)
    const over = await events(tok.alice)
    expect(over.status).toBe(429)
    expect((await events(tok.bob)).status).toBe(200)
  })

  it('needs a token', async () => {
    expect((await app.request('/v1/events')).status).toBe(401)
  })

  it('drops rows past the retention', async () => {
    await post(tok.alice, { to: 'bob', kind: 'chat', content: 'old' })
    t += (EVENT_RETENTION_DAYS - 1) * 86_400_000
    expect(store.sweepEvents()).toBe(0)
    t += 2 * 86_400_000
    expect(store.sweepEvents()).toBe(1)
    expect((await events(tok.alice)).body.events).toEqual([])
  })
})
