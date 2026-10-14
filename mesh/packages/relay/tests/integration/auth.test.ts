import { describe, it, expect, beforeEach } from 'vitest'
import { openDatabase, type Db } from '../../src/db/db.ts'
import { MessageStore } from '../../src/messages/store.ts'
import { Fanout } from '../../src/fanout.ts'
import { PresenceRegistry } from '../../src/presence/registry.ts'
import { buildApp } from '../../src/app.ts'
import { generatePairCode } from '../../src/auth/pair-code.ts'
import { hashToken } from '../../src/auth/hash.ts'

function deps(db: Db) {
  return {
    db,
    store: new MessageStore(db),
    fanout: new Fanout(),
    presence: new PresenceRegistry(),
    now: () => new Date(),
  }
}

function seedPair(db: Db, tier: 'human' | 'admin' = 'human') {
  const now = new Date().toISOString()
  db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)").run('t1','acme',7,now)
  db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)")
    .run('h_bob','t1','bob','Bob', now)
  const code = generatePairCode()
  const expires = new Date(Date.now() + 60_000).toISOString()
  db.prepare("INSERT INTO pair_code(code_hash,human_id,tier,expires_at,created_at) VALUES (?,?,?,?,?)")
    .run(hashToken(code), 'h_bob', tier, expires, now)
  return code
}

describe('POST /v1/auth/pair', () => {
  let db: Db
  let app: ReturnType<typeof buildApp>
  beforeEach(() => { db = openDatabase(':memory:'); app = buildApp(deps(db)) })

  it('redeems valid pair code and returns a bearer token', async () => {
    const code = seedPair(db)
    const res = await app.request('/v1/auth/pair', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pair_code: code, device_label: 'bob-laptop' })
    })
    expect(res.status).toBe(200)
    const j = await res.json() as any
    expect(j.token).toMatch(/^[A-Za-z0-9_-]{43}$/)
    expect(j.human.handle).toBe('bob')
    expect(j.team.name).toBe('acme')
  })

  it('rejects already-consumed code', async () => {
    const code = seedPair(db)
    await app.request('/v1/auth/pair', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pair_code: code, device_label: 'a' })
    })
    const res2 = await app.request('/v1/auth/pair', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pair_code: code, device_label: 'a' })
    })
    expect(res2.status).toBe(400)
  })

  it('rejects expired code', async () => {
    const code = generatePairCode()
    const now = new Date().toISOString()
    db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)").run('t1','acme',7,now)
    db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)").run('h','t1','x','X',now)
    db.prepare("INSERT INTO pair_code(code_hash,human_id,tier,expires_at,created_at) VALUES (?,?,?,?,?)")
      .run(hashToken(code),'h','human', new Date(Date.now()-1000).toISOString(), now)
    const res = await app.request('/v1/auth/pair', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pair_code: code, device_label: 'x' })
    })
    expect(res.status).toBe(400)
  })

  it('rejects malformed code', async () => {
    const res = await app.request('/v1/auth/pair', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pair_code: 'nope', device_label: 'x' })
    })
    expect(res.status).toBe(400)
  })
})

describe('POST /v1/auth/revoke', () => {
  let db: Db
  let app: ReturnType<typeof buildApp>
  beforeEach(() => { db = openDatabase(':memory:'); app = buildApp(deps(db)) })

  it('revokes the caller\'s token', async () => {
    const code = seedPair(db)
    const pair = await (await app.request('/v1/auth/pair', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pair_code: code, device_label: 'laptop' })
    })).json() as any
    const res = await app.request('/v1/auth/revoke', {
      method: 'POST', headers: { authorization: `Bearer ${pair.token}` }
    })
    expect(res.status).toBe(200)
    const check = await app.request('/v1/peers', { headers: { authorization: `Bearer ${pair.token}` } })
    expect(check.status).toBe(401)
  })
})
