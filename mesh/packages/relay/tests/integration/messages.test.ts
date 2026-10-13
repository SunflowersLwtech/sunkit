import { describe, it, expect, beforeEach } from 'vitest'
import { openDatabase, type Db } from '../../src/db/db.ts'
import { MessageStore } from '../../src/messages/store.ts'
import { Fanout } from '../../src/fanout.ts'
import { PresenceRegistry } from '../../src/presence/registry.ts'
import { buildApp } from '../../src/app.ts'
import { hashToken, generateRawToken } from '../../src/auth/hash.ts'

function seed(db: Db) {
  const now = new Date().toISOString()
  db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)")
    .run('t1', 'acme', 7, now)
  for (const h of ['alice', 'bob']) {
    db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)")
      .run(`h_${h}`, 't1', h, h, now)
  }
  const raw = generateRawToken()
  db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)")
    .run('tk_alice', 'h_alice', hashToken(raw), 'laptop', 'human', now)
  return raw
}

describe('POST /v1/messages', () => {
  let db: Db
  let app: ReturnType<typeof buildApp>
  let token: string
  beforeEach(() => {
    db = openDatabase(':memory:')
    token = seed(db)
    app = buildApp({ db, store: new MessageStore(db), fanout: new Fanout(), presence: new PresenceRegistry(), now: () => new Date() })
  })

  async function post(body: unknown, headers: Record<string, string> = {}) {
    return app.request('/v1/messages', {
      method: 'POST',
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json', ...headers },
      body: JSON.stringify(body)
    })
  }

  it('201 + full envelope on valid chat', async () => {
    const res = await post({ to: 'bob', kind: 'chat', content: 'hi' })
    expect(res.status).toBe(201)
    const e = await res.json() as any
    expect(e.id).toMatch(/^msg_/)
    expect(e.from).toBe('alice')
  })

  it('400 on unknown kind', async () => {
    const res = await post({ to: 'bob', kind: 'surprise', content: 'x' })
    expect(res.status).toBe(400)
  })

  it('400 on unknown recipient', async () => {
    const res = await post({ to: 'mallory', kind: 'chat', content: 'x' })
    expect(res.status).toBe(400)
  })

  it('401 without bearer', async () => {
    const res = await app.request('/v1/messages', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ to: 'bob', kind: 'chat', content: 'x' })
    })
    expect(res.status).toBe(401)
  })

  it('Idempotency-Key: same key returns same envelope, stores once', async () => {
    const key = 'idem-1'
    const a = await (await post({ to: 'bob', kind: 'chat', content: 'x' }, { 'idempotency-key': key })).json() as any
    const b = await (await post({ to: 'bob', kind: 'chat', content: 'x' }, { 'idempotency-key': key })).json() as any
    expect(a.id).toBe(b.id)
    const count = db.prepare("SELECT COUNT(*) AS c FROM message").get() as { c: number }
    expect(count.c).toBe(1)
  })

  it('413 or 400 on content over MAX_CONTENT_BYTES', async () => {
    const big = 'a'.repeat(70_000)
    const res = await post({ to: 'bob', kind: 'chat', content: big })
    expect([400, 413]).toContain(res.status)
  })
})
