import { describe, it, expect, beforeEach } from 'vitest'
import { openDatabase, type Db } from '../../src/db/db.ts'
import { MessageStore } from '../../src/messages/store.ts'
import { Fanout } from '../../src/fanout.ts'
import { PresenceRegistry } from '../../src/presence/registry.ts'
import { SessionRegistry } from '../../src/sessions/registry.ts'
import { buildApp } from '../../src/app.ts'
import { hashToken, generateRawToken } from '../../src/auth/hash.ts'

const S_ALICE = 's_01hrk7y0000000000000aaaaaa'
const S_BOB1 = 's_01hrk7y0000000000000bbbbb1'
const S_BOB2 = 's_01hrk7y0000000000000bbbbb2'

function seed(db: Db) {
  const now = new Date().toISOString()
  db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)").run('t1', 'acme', 7, now)
  for (const h of ['alice', 'bob']) {
    db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)")
      .run(`h_${h}`, 't1', h, h, now)
  }
  const alice = generateRawToken(); const bob = generateRawToken()
  db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)").run('tk_a', 'h_alice', hashToken(alice), 'mac-a', 'human', now)
  db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)").run('tk_b', 'h_bob', hashToken(bob), 'msi', 'human', now)
  return { alice, bob }
}

async function readEvents(stream: ReadableStream<Uint8Array>, n: number, timeoutMs = 600): Promise<string[]> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  const events: string[] = []
  let buf = ''
  const deadline = Date.now() + timeoutMs
  while (events.length < n && Date.now() < deadline) {
    const timeout = new Promise<{ value: undefined; done: true }>(r =>
      setTimeout(() => r({ value: undefined, done: true }), Math.max(0, deadline - Date.now())))
    const { value, done } = await Promise.race([reader.read(), timeout])
    if (done) break
    buf += decoder.decode(value)
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? ''
    events.push(...parts.filter(p => p.includes('event: message')))
  }
  try { await reader.cancel() } catch { /* ignore */ }
  return events
}

describe('session-level addressing', () => {
  let app: ReturnType<typeof buildApp>
  let sessions: SessionRegistry
  let tok: { alice: string; bob: string }

  const open = (token: string, session: string, name: string) =>
    app.request(`/v1/stream?session=${session}&name=${name}&cwd=/w/${name}`, {
      headers: { authorization: `Bearer ${token}` },
    })
  const post = (token: string, body: unknown, senderSession?: string) =>
    app.request('/v1/messages', {
      method: 'POST',
      headers: {
        authorization: `Bearer ${token}`,
        'content-type': 'application/json',
        ...(senderSession ? { 'x-mesh-session': senderSession } : {}),
      },
      body: JSON.stringify(body),
    })

  beforeEach(() => {
    const db = openDatabase(':memory:')
    tok = seed(db)
    sessions = new SessionRegistry()
    app = buildApp({
      db, store: new MessageStore(db), fanout: new Fanout(),
      presence: new PresenceRegistry(), sessions, now: () => new Date(),
    })
  })

  it('delivers only to the addressed session, not to sibling sessions of the same account', async () => {
    await open(tok.alice, S_ALICE, 'alice-main')
    const bob1 = await open(tok.bob, S_BOB1, 'repo-x')
    const bob2 = await open(tok.bob, S_BOB2, 'repo-y')
    const res = await post(tok.alice, { to: 'bob', to_session: S_BOB1, kind: 'chat', content: 'only you' }, S_ALICE)
    expect(res.status).toBe(201)
    const [got1, got2] = await Promise.all([readEvents(bob1.body!, 1), readEvents(bob2.body!, 1)])
    expect(got1).toHaveLength(1)
    expect(got1[0]).toContain('"content":"only you"')
    expect(got1[0]).toContain(`"from_session":"${S_ALICE}"`)
    expect(got1[0]).toContain('"from_name":"alice-main"')
    expect(got2).toHaveLength(0)
  })

  it('rejects a sender session that belongs to another token (cannot speak as someone else\'s session)', async () => {
    await open(tok.bob, S_BOB1, 'repo-x')
    await open(tok.alice, S_ALICE, 'alice-main')
    const res = await post(tok.alice, { to: 'bob', to_session: S_BOB1, kind: 'chat', content: 'hi' }, S_BOB1)
    expect(res.status).toBe(403)
  })

  it('refuses to attach a stream to a session id owned by another token', async () => {
    await open(tok.bob, S_BOB1, 'repo-x')
    const hijack = await open(tok.alice, S_BOB1, 'evil')
    expect(hijack.status).toBe(409)
    expect(sessions.get(S_BOB1)?.name).toBe('repo-x')
  })

  it('rejects clients that try to set from_session/from_name themselves', async () => {
    const res = await post(tok.alice, { to: 'bob', kind: 'chat', content: 'x', from_session: S_BOB1, from_name: 'repo-x' })
    expect(res.status).toBe(400)
  })

  it('404s when to_session is unknown or belongs to a different account than `to`', async () => {
    await open(tok.alice, S_ALICE, 'alice-main')
    expect((await post(tok.bob, { to: 'bob', to_session: S_BOB2, kind: 'chat', content: 'x' })).status).toBe(404)
    expect((await post(tok.bob, { to: 'bob', to_session: S_ALICE, kind: 'chat', content: 'x' })).status).toBe(404)
  })

  it('lists live sessions with name, ref, account and device', async () => {
    await open(tok.alice, S_ALICE, 'alice-main')
    await open(tok.bob, S_BOB1, 'repo-x')
    const res = await app.request('/v1/sessions', { headers: { authorization: `Bearer ${tok.alice}` } })
    const list = await res.json() as Array<Record<string, string>>
    expect(list.map(s => `${s.name} [${s.ref}] ${s.account}@${s.device}`)).toEqual([
      'alice-main [aaaaaa] alice@mac-a',
      'repo-x [bbbbb1] bob@msi',
    ])
  })

  it('a session message sent while the target is reconnecting is replayed to that session only', async () => {
    sessions.attach({ session_id: S_BOB1, team_id: 't1', handle: 'bob', token_id: 'tk_b', device: 'msi', name: 'repo-x' })
    sessions.detach(S_BOB1) // within grace period: still addressable
    expect((await post(tok.alice, { to: 'bob', to_session: S_BOB1, kind: 'chat', content: 'queued' })).status).toBe(201)
    const sibling = await open(tok.bob, S_BOB2, 'repo-y')
    expect(await readEvents(sibling.body!, 1)).toHaveLength(0)
    const back = await open(tok.bob, S_BOB1, 'repo-x')
    const got = await readEvents(back.body!, 1)
    expect(got).toHaveLength(1)
    expect(got[0]).toContain('"content":"queued"')
  })

  it('only the owning token can rename or change a session\'s status', async () => {
    await open(tok.bob, S_BOB1, 'repo-x')
    const upd = (token: string) => app.request('/v1/sessions/self', {
      method: 'POST',
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
      body: JSON.stringify({ session: S_BOB1, name: 'renamed', status: 'busy' }),
    })
    expect((await upd(tok.alice)).status).toBe(404)
    expect(sessions.get(S_BOB1)?.name).toBe('repo-x')
    expect((await upd(tok.bob)).status).toBe(200)
    expect(sessions.get(S_BOB1)).toMatchObject({ name: 'renamed', status: 'busy' })
  })
})

describe('self-reported Claude login', () => {
  it('is listed, stamped on sent messages from the registry, and cannot be set by the sender body', async () => {
    const db = openDatabase(':memory:')
    const tok = seed(db)
    const sessions = new SessionRegistry()
    const app = buildApp({ db, store: new MessageStore(db), fanout: new Fanout(), presence: new PresenceRegistry(), sessions, now: () => new Date() })
    await app.request(`/v1/stream?session=${S_ALICE}&name=a&login=alice%40gmail.com`, { headers: { authorization: `Bearer ${tok.alice}` } })
    const bob = await app.request(`/v1/stream?session=${S_BOB1}&name=b`, { headers: { authorization: `Bearer ${tok.bob}` } })
    const list = await (await app.request('/v1/sessions', { headers: { authorization: `Bearer ${tok.bob}` } })).json() as Array<Record<string, string>>
    expect(list.find(s => s.name === 'a')?.login).toBe('alice@gmail.com')
    expect(list.find(s => s.name === 'b')).not.toHaveProperty('login')
    const forged = await app.request('/v1/messages', {
      method: 'POST', headers: { authorization: `Bearer ${tok.alice}`, 'content-type': 'application/json', 'x-mesh-session': S_ALICE },
      body: JSON.stringify({ to: 'bob', to_session: S_BOB1, kind: 'chat', content: 'x', from_login: 'ceo@corp.com' }),
    })
    expect(forged.status).toBe(400)
    await app.request('/v1/sessions/self', {
      method: 'POST', headers: { authorization: `Bearer ${tok.alice}`, 'content-type': 'application/json' },
      body: JSON.stringify({ session: S_ALICE, login: 'alice@work.com' }),
    })
    const ok = await app.request('/v1/messages', {
      method: 'POST', headers: { authorization: `Bearer ${tok.alice}`, 'content-type': 'application/json', 'x-mesh-session': S_ALICE },
      body: JSON.stringify({ to: 'bob', to_session: S_BOB1, kind: 'chat', content: 'after /login' }),
    })
    expect(((await ok.json()) as { from_login: string }).from_login).toBe('alice@work.com')
    const got = await readEvents(bob.body!, 1)
    expect(got[0]).toContain('"from_login":"alice@work.com"')
  })

  it('ignores a malformed login on attach', async () => {
    const db = openDatabase(':memory:')
    const tok = seed(db)
    const sessions = new SessionRegistry()
    const app = buildApp({ db, store: new MessageStore(db), fanout: new Fanout(), presence: new PresenceRegistry(), sessions, now: () => new Date() })
    await app.request(`/v1/stream?session=${S_ALICE}&name=a&login=${encodeURIComponent('<b>x</b>')}`, { headers: { authorization: `Bearer ${tok.alice}` } })
    expect(sessions.get(S_ALICE)?.login).toBeUndefined()
  })
})

describe('POST /v1/auth/pair rate limit', () => {
  it('returns 429 after 10 attempts per minute from one address', async () => {
    const db = openDatabase(':memory:')
    seed(db)
    const app = buildApp({ db, store: new MessageStore(db), fanout: new Fanout(), presence: new PresenceRegistry(), now: () => new Date() })
    const statuses: number[] = []
    for (let i = 0; i < 11; i++) {
      const res = await app.request('/v1/auth/pair', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ pair_code: 'm_pair_AAAAAAAA', device_label: 'x' }),
      })
      statuses.push(res.status)
    }
    expect(statuses.slice(0, 10).every(s => s === 400)).toBe(true)
    expect(statuses[10]).toBe(429)
  })
})
