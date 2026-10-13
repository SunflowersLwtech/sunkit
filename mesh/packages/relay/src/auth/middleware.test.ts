import { describe, it, expect, beforeEach } from 'vitest'
import { Hono } from 'hono'
import { openDatabase, type Db } from '../db/db.ts'
import { hashToken, generateRawToken } from './hash.ts'
import { bearerAuth, type AuthContext } from './middleware.ts'

function seedTeamAndToken(db: Db, tier: 'human' | 'admin' = 'human') {
  const now = new Date().toISOString()
  db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)")
    .run('t1', 'acme', 7, now)
  db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)")
    .run('h1', 't1', 'alice', 'Alice', now)
  const raw = generateRawToken()
  db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)")
    .run('tk1', 'h1', hashToken(raw), 'laptop', tier, now)
  return raw
}

describe('bearerAuth middleware', () => {
  let db: Db
  let app: Hono<{ Variables: AuthContext }>
  beforeEach(() => {
    db = openDatabase(':memory:')
    app = new Hono<{ Variables: AuthContext }>()
    app.use('*', bearerAuth(db, { requireTier: 'human' }))
    app.get('/ok', c => c.json({ from: c.get('human').handle, tier: c.get('token').tier }))
  })

  it('accepts a valid human token', async () => {
    const raw = seedTeamAndToken(db)
    const res = await app.request('/ok', { headers: { authorization: `Bearer ${raw}` } })
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ from: 'alice', tier: 'human' })
  })

  it('rejects missing Authorization header with 401', async () => {
    const res = await app.request('/ok')
    expect(res.status).toBe(401)
  })

  it('rejects malformed Authorization header with 401', async () => {
    const res = await app.request('/ok', { headers: { authorization: 'Basic xxx' } })
    expect(res.status).toBe(401)
  })

  it('rejects unknown token with 401', async () => {
    seedTeamAndToken(db)
    const res = await app.request('/ok', { headers: { authorization: `Bearer ${generateRawToken()}` } })
    expect(res.status).toBe(401)
  })

  it('rejects revoked token with 401', async () => {
    const raw = seedTeamAndToken(db)
    db.prepare("UPDATE token SET revoked_at=? WHERE id=?").run(new Date().toISOString(), 'tk1')
    const res = await app.request('/ok', { headers: { authorization: `Bearer ${raw}` } })
    expect(res.status).toBe(401)
  })

  it('rejects disabled human with 401', async () => {
    const raw = seedTeamAndToken(db)
    db.prepare("UPDATE human SET disabled_at=? WHERE id=?").run(new Date().toISOString(), 'h1')
    const res = await app.request('/ok', { headers: { authorization: `Bearer ${raw}` } })
    expect(res.status).toBe(401)
  })

  it('accepts admin token on human-tier route (admin ⊇ human)', async () => {
    const raw = seedTeamAndToken(db, 'admin')
    const res = await app.request('/ok', { headers: { authorization: `Bearer ${raw}` } })
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ from: 'alice', tier: 'admin' })
  })

  it('rejects human token on admin-tier route with 401', async () => {
    const raw = seedTeamAndToken(db, 'human')
    const adminApp = new Hono<{ Variables: AuthContext }>()
    adminApp.use('*', bearerAuth(db, { requireTier: 'admin' }))
    adminApp.get('/ok', c => c.json({ tier: c.get('token').tier }))
    const res = await adminApp.request('/ok', { headers: { authorization: `Bearer ${raw}` } })
    expect(res.status).toBe(401)
  })

  it('401 response never echoes the token or indicates team existence', async () => {
    const res = await app.request('/ok', { headers: { authorization: 'Bearer leaked-token-value' } })
    const text = await res.text()
    expect(text).not.toContain('leaked-token-value')
    expect(text).not.toContain('team')
  })
})
