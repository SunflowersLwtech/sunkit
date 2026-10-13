import type { MiddlewareHandler } from 'hono'
import type { Db } from '../db/db.ts'
import { hashToken, timingSafeEqual } from './hash.ts'

export type Tier = 'human' | 'admin'

export interface TokenRecord {
  id: string
  human_id: string
  tier: Tier
  label: string
}

export interface HumanRecord {
  id: string
  team_id: string
  handle: string
  display_name: string
}

export interface AuthContext {
  token: TokenRecord
  human: HumanRecord
  team_id: string
}

interface AuthRow {
  token_id: string
  human_id: string
  tier: Tier
  label: string
  token_hash: Buffer
  revoked_at: string | null
  team_id: string
  handle: string
  display_name: string
  disabled_at: string | null
}

export function bearerAuth(
  db: Db,
  opts: { requireTier: Tier }
): MiddlewareHandler<{ Variables: AuthContext }> {
  const stmt = db.prepare(`
    SELECT t.id AS token_id, t.human_id, t.tier, t.label, t.token_hash, t.revoked_at,
           h.team_id, h.handle, h.display_name, h.disabled_at
    FROM token t JOIN human h ON h.id = t.human_id
    WHERE t.token_hash = ?
  `)

  return async (c, next) => {
    const header = c.req.header('authorization') ?? ''
    const m = /^Bearer ([A-Za-z0-9_-]{43})$/.exec(header)
    if (!m) return c.json({ error: 'unauthorized' }, 401)

    const raw = m[1]!
    const hash = hashToken(raw)

    const row = stmt.get(hash) as AuthRow | undefined
    if (!row) return c.json({ error: 'unauthorized' }, 401)
    // Defense-in-depth: timing-safe compare even after the indexed lookup.
    if (!timingSafeEqual(row.token_hash, hash)) {
      return c.json({ error: 'unauthorized' }, 401)
    }
    if (row.revoked_at !== null) return c.json({ error: 'unauthorized' }, 401)
    if (row.disabled_at !== null) return c.json({ error: 'unauthorized' }, 401)
    // Tier is a capability hierarchy: admin ⊇ human. An admin token can
    // satisfy a human-tier gate (send messages, list peers, etc.), but a
    // human token never reaches admin-only routes.
    const rank: Record<Tier, number> = { human: 0, admin: 1 }
    if (rank[row.tier] < rank[opts.requireTier]) return c.json({ error: 'unauthorized' }, 401)

    // Stamp last_active_at for every authenticated request. Drives the
    // inactivity sweep (see startServer). Cheap single-row UPDATE; no need
    // to throttle at this volume.
    db.prepare('UPDATE human SET last_active_at=? WHERE id=?')
      .run(new Date().toISOString(), row.human_id)

    c.set('token', { id: row.token_id, human_id: row.human_id, tier: row.tier, label: row.label })
    c.set('human', {
      id: row.human_id,
      team_id: row.team_id,
      handle: row.handle,
      display_name: row.display_name,
    })
    c.set('team_id', row.team_id)
    return next()
  }
}
