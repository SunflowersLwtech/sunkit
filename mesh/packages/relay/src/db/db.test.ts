import { describe, it, expect, beforeEach } from 'vitest'
import { openDatabase, getSchemaVersion, type Db } from './db.ts'

describe('openDatabase', () => {
  let db: Db
  beforeEach(() => { db = openDatabase(':memory:') })

  it('applies schema and reports latest version', () => {
    expect(getSchemaVersion(db)).toBe(4)
  })

  it('message table has session addressing columns (v3)', () => {
    const cols = (db.pragma('table_info(message)') as Array<{ name: string }>).map(c => c.name)
    expect(cols).toEqual(expect.arrayContaining(['from_session', 'from_name', 'to_session']))
  })

  it('human table has last_active_at column (v2)', () => {
    const cols = db.pragma('table_info(human)') as Array<{ name: string }>
    expect(cols.some(c => c.name === 'last_active_at')).toBe(true)
  })

  it('has all expected tables', () => {
    const names = db.prepare(
      "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).all().map((r: any) => r.name)
    expect(names).toEqual(expect.arrayContaining([
      'audit_log', 'human', 'idempotency_key', 'message', 'pair_code',
      'schema_version', 'team', 'token', 'token_grant', 'task', 'task_seq', 'lease'
    ]))
  })

  it('keeps v4 additive: an older relay\'s message insert (no routing columns) still works', () => {
    db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)").run('t1', 'acme', 7, new Date().toISOString())
    db.prepare(`
      INSERT INTO message(id,v,team_id,from_handle,to_handle,in_reply_to,thread_root,kind,content,meta_json,sent_at,delivered_at,from_session,from_name,to_session,from_login)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    `).run('msg_01HRK7Y0000000000000000000', 1, 't1', 'alice', 'bob', null, null, 'chat', 'x', '{}', new Date().toISOString(), null, null, null, null, null)
    const row = db.prepare("SELECT from_wg, scope_json FROM message").get() as { from_wg: string | null; scope_json: string | null }
    expect(row).toEqual({ from_wg: null, scope_json: null })
  })

  it('enforces human.handle uniqueness within a team', () => {
    db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)")
      .run('t1', 'acme', 7, new Date().toISOString())
    const ins = db.prepare(
      "INSERT INTO human(id,team_id,handle,display_name,created_at) VALUES (?,?,?,?,?)"
    )
    ins.run('h1', 't1', 'alice', 'Alice', new Date().toISOString())
    expect(() => ins.run('h2', 't1', 'alice', 'Alice2', new Date().toISOString())).toThrow()
  })

  it('rejects message with invalid kind', () => {
    db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES (?,?,?,?)")
      .run('t1', 'acme', 7, new Date().toISOString())
    expect(() => db.prepare(
      "INSERT INTO message(id,v,team_id,from_handle,to_handle,kind,content,sent_at) VALUES (?,?,?,?,?,?,?,?)"
    ).run('msg_x', 1, 't1', 'a', 'b', 'invalid', 'x', new Date().toISOString())).toThrow()
  })
})
