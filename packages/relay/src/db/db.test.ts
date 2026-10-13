import { describe, it, expect, beforeEach } from 'vitest'
import { openDatabase, getSchemaVersion, type Db } from './db.ts'

describe('openDatabase', () => {
  let db: Db
  beforeEach(() => { db = openDatabase(':memory:') })

  it('applies schema and reports latest version', () => {
    expect(getSchemaVersion(db)).toBe(3)
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
      'schema_version', 'team', 'token'
    ]))
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
