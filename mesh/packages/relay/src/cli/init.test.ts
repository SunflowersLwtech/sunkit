import { describe, it, expect } from 'vitest'
import { initTeam } from './init.ts'
import { openDatabase } from '../db/db.ts'

describe('initTeam', () => {
  it('creates team + admin human + admin token + human pair code', () => {
    const db = openDatabase(':memory:')
    const result = initTeam(db, {
      team_id: 't1', team_name: 'acme',
      admin_handle: 'alice', admin_display_name: 'Alice'
    })
    expect(result.admin_token).toMatch(/^[A-Za-z0-9_-]{43}$/)
    expect(result.human_pair_code).toMatch(/^MESH-/)

    const team = db.prepare("SELECT name FROM team").get() as any
    expect(team.name).toBe('acme')
    const tokens = db.prepare("SELECT tier FROM token").all() as any[]
    expect(tokens.map(t => t.tier)).toEqual(['admin'])
    const codes = db.prepare("SELECT tier FROM pair_code").all() as any[]
    expect(codes.map(c => c.tier)).toEqual(['human'])
  })

  it('is idempotent: refuses to init a non-empty db', () => {
    const db = openDatabase(':memory:')
    initTeam(db, { team_id: 't1', team_name: 'x', admin_handle: 'a', admin_display_name: 'A' })
    expect(() => initTeam(db, { team_id: 't1', team_name: 'y', admin_handle: 'b', admin_display_name: 'B' }))
      .toThrow(/already initialized/)
  })
})
