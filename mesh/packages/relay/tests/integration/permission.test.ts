import { describe, it, expect, beforeEach } from 'vitest'
import { openDatabase, type Db } from '../../src/db/db.ts'
import { MessageStore } from '../../src/messages/store.ts'
import { Fanout } from '../../src/fanout.ts'
import { PresenceRegistry } from '../../src/presence/registry.ts'
import { buildApp } from '../../src/app.ts'
import { generateRawToken, hashToken } from '../../src/auth/hash.ts'

function seed(db: Db) {
  const now = new Date().toISOString()
  db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)").run('t1','acme',7,now)
  for (const h of ['alice','bob']) {
    db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)")
      .run(`h_${h}`, 't1', h, h, now)
  }
  const a = generateRawToken(); const b = generateRawToken()
  db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)").run('tk_a','h_alice',hashToken(a),'laptop','human',now)
  db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)").run('tk_b','h_bob',hashToken(b),'laptop','human',now)
  return { a, b }
}

function appFor(db: Db) {
  return buildApp({
    db, store: new MessageStore(db), fanout: new Fanout(),
    presence: new PresenceRegistry(), now: () => new Date(),
  })
}

describe('POST /v1/permission/respond', () => {
  let db: Db
  let app: ReturnType<typeof buildApp>
  let t: { a: string; b: string }
  beforeEach(() => { db = openDatabase(':memory:'); t = seed(db); app = appFor(db) })

  async function post(path: string, token: string, body: unknown) {
    return app.request(path, {
      method: 'POST',
      headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
      body: JSON.stringify(body)
    })
  }

  it('404 when no matching open permission_request', async () => {
    const res = await post('/v1/permission/respond', t.b,
      { request_id: 'abcde', verdict: 'allow' })
    expect(res.status).toBe(404)
  })

  it('synthesizes verdict envelope when matching request exists', async () => {
    await post('/v1/messages', t.a, {
      to: 'bob', kind: 'permission_request', content: 'delete build output',
      meta: { request_id: 'abcde', tool_name: 'Bash', input_preview: 'rm -rf dist/',
              requester: 'alice', expires_at: new Date(Date.now()+60_000).toISOString() }
    })
    const res = await post('/v1/permission/respond', t.b,
      { request_id: 'abcde', verdict: 'allow', reason: 'looked at diff' })
    expect(res.status).toBe(200)
    const verdict = db.prepare(
      "SELECT * FROM message WHERE kind='permission_verdict'"
    ).get() as any
    expect(verdict.to_handle).toBe('alice')
    expect(verdict.from_handle).toBe('bob')
    expect(JSON.parse(verdict.meta_json).behavior).toBe('allow')
    expect(JSON.parse(verdict.meta_json).reason).toBe('looked at diff')
  })

  it('lets any team human answer an @team-broadcast request (ask_team routing)', async () => {
    await post('/v1/messages', t.a, {
      to: '@team', kind: 'permission_request', content: 'delete build output',
      meta: { request_id: 'abcde', tool_name: 'Bash', input_preview: 'rm -rf dist/',
              requester: 'alice', expires_at: new Date(Date.now()+60_000).toISOString() }
    })
    const res = await post('/v1/permission/respond', t.b,
      { request_id: 'abcde', verdict: 'deny', reason: 'not during release' })
    expect(res.status).toBe(200)
    const verdict = db.prepare(
      "SELECT * FROM message WHERE kind='permission_verdict'"
    ).get() as any
    expect(verdict.to_handle).toBe('alice')
    expect(verdict.from_handle).toBe('bob')
    expect(JSON.parse(verdict.meta_json).behavior).toBe('deny')
  })

  it('rejects expired request', async () => {
    await post('/v1/messages', t.a, {
      to: 'bob', kind: 'permission_request', content: 'x',
      meta: { request_id: 'abcde', tool_name: 'Bash', input_preview: 'x',
              requester: 'alice', expires_at: new Date(Date.now()-1000).toISOString() }
    })
    const res = await post('/v1/permission/respond', t.b,
      { request_id: 'abcde', verdict: 'allow' })
    expect(res.status).toBe(410)
  })
})
