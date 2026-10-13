import { describe, it, expect, beforeEach } from 'vitest'
import { openDatabase, type Db } from '../../src/db/db.ts'
import { MessageStore } from '../../src/messages/store.ts'
import { Fanout } from '../../src/fanout.ts'
import { PresenceRegistry } from '../../src/presence/registry.ts'
import { buildApp } from '../../src/app.ts'
import { hashToken, generateRawToken } from '../../src/auth/hash.ts'

function seedAdmin(db: Db) {
  const now = new Date().toISOString()
  db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)").run('t1','acme',7,now)
  db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)").run('h_alice','t1','alice','Alice', now)
  const raw = generateRawToken()
  db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)")
    .run('tk_admin','h_alice',hashToken(raw),'admin','admin',now)
  return raw
}

function appFor(db: Db) {
  return buildApp({
    db, store: new MessageStore(db), fanout: new Fanout(),
    presence: new PresenceRegistry(), now: () => new Date(),
  })
}

describe('admin routes', () => {
  let db: Db
  let app: ReturnType<typeof buildApp>
  let adminToken: string
  beforeEach(() => { db = openDatabase(':memory:'); adminToken = seedAdmin(db); app = appFor(db) })

  async function admin(path: string, method: 'GET'|'POST'|'DELETE', body?: unknown) {
    return app.request(`/v1/admin${path}`, {
      method,
      headers: {
        authorization: `Bearer ${adminToken}`,
        ...(body ? { 'content-type': 'application/json' } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    })
  }

  it('creates user and issues pair code', async () => {
    const res = await admin('/users', 'POST', { handle: 'bob', display_name: 'Bob' })
    expect(res.status).toBe(201)
    const j = await res.json() as any
    expect(j.handle).toBe('bob')
    expect(j.pair_code).toMatch(/^MESH-/)
  })

  it('add-device issues another pair code for an existing user without revoking their tokens', async () => {
    await admin('/users', 'POST', { handle: 'bob', display_name: 'Bob' })
    db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)")
      .run('tk_bob_mac', (db.prepare("SELECT id FROM human WHERE handle='bob'").get() as { id: string }).id,
        hashToken(generateRawToken()), 'mac', 'human', new Date().toISOString())
    const res = await admin('/users/bob/devices', 'POST', {})
    expect(res.status).toBe(201)
    const body = await res.json() as { pair_code: string; handle: string }
    expect(body.handle).toBe('bob')
    expect(body.pair_code).toMatch(/^MESH-/)
    const live = db.prepare("SELECT COUNT(*) n FROM token WHERE id='tk_bob_mac' AND revoked_at IS NULL").get() as { n: number }
    expect(live.n).toBe(1)
    const codes = db.prepare("SELECT COUNT(*) n FROM pair_code p JOIN human h ON h.id=p.human_id WHERE h.handle='bob' AND p.consumed_at IS NULL").get() as { n: number }
    expect(codes.n).toBe(2)
  })

  it('add-device 404s for unknown or disabled users', async () => {
    expect((await admin('/users/ghost/devices', 'POST', {})).status).toBe(404)
    await admin('/users', 'POST', { handle: 'carol', display_name: 'Carol' })
    await admin('/users/carol', 'DELETE')
    expect((await admin('/users/carol/devices', 'POST', {})).status).toBe(404)
  })

  it('rejects duplicate handle', async () => {
    await admin('/users', 'POST', { handle: 'bob', display_name: 'Bob' })
    const res2 = await admin('/users', 'POST', { handle: 'bob', display_name: 'Bob2' })
    expect(res2.status).toBe(409)
  })

  it('force=true resets an existing user (same row, new paircode, old tokens revoked)', async () => {
    const r1 = await admin('/users', 'POST', { handle: 'bob', display_name: 'Bob' })
    const firstCode = (await r1.json() as { pair_code: string }).pair_code
    const bobId = (db.prepare("SELECT id FROM human WHERE handle='bob'").get() as { id: string }).id
    db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)")
      .run('tk_bob_old', bobId, hashToken('raw-old-token'), 'bob-laptop', 'human', new Date().toISOString())

    const r2 = await admin('/users', 'POST',
      { handle: 'bob', display_name: 'Bob v2', force: true })
    expect(r2.status).toBe(200)
    const j2 = await r2.json() as { pair_code: string; reset: boolean; display_name: string }
    expect(j2.reset).toBe(true)
    expect(j2.pair_code).not.toBe(firstCode)
    expect(j2.display_name).toBe('Bob v2')

    const row = db.prepare("SELECT id, display_name, disabled_at FROM human WHERE handle='bob'").get() as { id: string; display_name: string; disabled_at: string | null }
    expect(row.id).toBe(bobId)
    expect(row.display_name).toBe('Bob v2')
    expect(row.disabled_at).toBeNull()

    const old = db.prepare("SELECT revoked_at FROM token WHERE id='tk_bob_old'").get() as { revoked_at: string | null }
    expect(old.revoked_at).not.toBeNull()
    const pairCount = (db.prepare("SELECT COUNT(*) AS c FROM pair_code WHERE human_id=?").get(bobId) as { c: number }).c
    expect(pairCount).toBe(1)
  })

  it('force=true re-enables a disabled user', async () => {
    await admin('/users', 'POST', { handle: 'bob', display_name: 'Bob' })
    await admin('/users/bob', 'DELETE')
    const r = await admin('/users', 'POST',
      { handle: 'bob', display_name: 'Bob', force: true })
    expect(r.status).toBe(200)
    const row = db.prepare("SELECT disabled_at FROM human WHERE handle='bob'").get() as { disabled_at: string | null }
    expect(row.disabled_at).toBeNull()
  })

  it('hard-deletes a user with ?hard=true (handle becomes re-addable)', async () => {
    await admin('/users', 'POST', { handle: 'bob', display_name: 'Bob' })
    const bobId = (db.prepare("SELECT id FROM human WHERE handle='bob'").get() as { id: string }).id
    db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)")
      .run('tk_bob', bobId, hashToken('raw'), 'bob-laptop', 'human', new Date().toISOString())

    const res = await app.request('/v1/admin/users/bob?hard=true', {
      method: 'DELETE',
      headers: { authorization: `Bearer ${adminToken}` },
    })
    expect(res.status).toBe(200)
    expect((await res.json() as { hard: boolean }).hard).toBe(true)

    // Row and dependents all gone
    expect(db.prepare("SELECT COUNT(*) AS c FROM human WHERE handle='bob'").get()).toEqual({ c: 0 })
    expect(db.prepare("SELECT COUNT(*) AS c FROM token WHERE id='tk_bob'").get()).toEqual({ c: 0 })
    // Handle is reusable without --force
    const recreate = await admin('/users', 'POST', { handle: 'bob', display_name: 'Bob2' })
    expect(recreate.status).toBe(201)
  })

  it('hard delete returns 404 for unknown handle', async () => {
    const res = await app.request('/v1/admin/users/ghost?hard=true', {
      method: 'DELETE',
      headers: { authorization: `Bearer ${adminToken}` },
    })
    expect(res.status).toBe(404)
  })

  it('purge-inactive hard-deletes users past the cutoff, preserves admin holders', async () => {
    // Seed three users: inactive-human, active-human, inactive-but-admin
    const longAgo = new Date(Date.now() - 60 * 24 * 60 * 60 * 1000).toISOString()
    const now = new Date().toISOString()
    db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at,last_active_at) VALUES (?,?,?,?,?,?)")
      .run('h_old', 't1', 'old', 'Old', longAgo, longAgo)
    db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at,last_active_at) VALUES (?,?,?,?,?,?)")
      .run('h_new', 't1', 'new', 'New', now, now)
    db.prepare("INSERT INTO human(id,team_id,handle,display_name,created_at,last_active_at) VALUES (?,?,?,?,?,?)")
      .run('h_old_admin', 't1', 'oldadm', 'OldAdm', longAgo, longAgo)
    db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)")
      .run('tk_adm', 'h_old_admin', hashToken('raw-admin'), 'adm', 'admin', longAgo)

    const res = await admin('/purge-inactive', 'POST', { days: 30 })
    expect(res.status).toBe(200)
    const j = await res.json() as { purged: string[]; days: number }
    expect(j.purged).toContain('old')
    expect(j.purged).not.toContain('new')      // within cutoff
    expect(j.purged).not.toContain('oldadm')   // active admin token, protected
  })

  it('disables a user', async () => {
    await admin('/users', 'POST', { handle: 'bob', display_name: 'Bob' })
    const res = await admin('/users/bob', 'DELETE')
    expect(res.status).toBe(200)
    const human = db.prepare("SELECT disabled_at FROM human WHERE handle='bob'").get() as any
    expect(human.disabled_at).toBeTruthy()
  })

  it('lists tokens with masked hashes', async () => {
    const res = await admin('/tokens', 'GET')
    expect(res.status).toBe(200)
    const list = await res.json() as any[]
    expect(list[0]).toHaveProperty('id')
    expect(list[0]).not.toHaveProperty('token_hash')
  })

  it('revokes a specific token', async () => {
    const list = await (await admin('/tokens', 'GET')).json() as any[]
    const res = await admin(`/tokens/${list[0].id}`, 'DELETE')
    expect(res.status).toBe(200)
  })

  it('dumps audit log', async () => {
    await admin('/users', 'POST', { handle: 'bob', display_name: 'Bob' })
    const res = await admin('/audit?since=2020-01-01T00:00:00Z', 'GET')
    expect(res.status).toBe(200)
    const rows = await res.json() as any[]
    expect(rows.some(r => r.event === 'user.create')).toBe(true)
  })

  it('rejects human-tier token on admin routes', async () => {
    const now = new Date().toISOString()
    const rawH = generateRawToken()
    db.prepare("INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)")
      .run('tk_h', 'h_alice', hashToken(rawH), 'laptop', 'human', now)
    const res = await app.request('/v1/admin/tokens',
      { headers: { authorization: `Bearer ${rawH}` } })
    expect(res.status).toBe(401)
  })
})
