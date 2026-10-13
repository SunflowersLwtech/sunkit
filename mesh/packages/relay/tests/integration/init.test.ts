import { describe, it, expect, beforeEach } from 'vitest'
import { openDatabase, type Db } from '../../src/db/db.ts'
import { initTeam } from '../../src/cli/init.ts'

let db: Db
beforeEach(() => { db = openDatabase(':memory:') })

describe('initTeam', () => {
  const base = { team_id: 'team_t1', team_name: 'acme', admin_display_name: 'Pouria' }

  it('succeeds for a valid lowercase handle', () => {
    const r = initTeam(db, { ...base, admin_handle: 'pouria' })
    expect(r.admin_token).toBeTruthy()
    expect(r.admin_token.length).toBeGreaterThan(16)
    expect(r.human_pair_code).toMatch(/^MESH-/)
  })

  it('rejects an uppercase handle (would fail envelope validation at send time)', () => {
    expect(() => initTeam(db, { ...base, admin_handle: 'Pouria' })).toThrow(/invalid handle/)
  })

  it('rejects a handle starting with a digit', () => {
    expect(() => initTeam(db, { ...base, admin_handle: '1pouria' })).toThrow(/invalid handle/)
  })

  it('rejects an empty handle', () => {
    expect(() => initTeam(db, { ...base, admin_handle: '' })).toThrow(/invalid handle/)
  })

  it('rejects handles with spaces or uppercase in the middle', () => {
    expect(() => initTeam(db, { ...base, admin_handle: 'mesh Admin' })).toThrow(/invalid handle/)
    expect(() => initTeam(db, { ...base, admin_handle: 'meshAdmin' })).toThrow(/invalid handle/)
  })
})
