import { Hono } from 'hono'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import type { Deps } from '../deps.ts'

const TTL_MS = 2_000

interface HumanRow {
  id: string
  handle: string
  display_name: string
}

export function peersRoute(deps: Deps) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))

  let cached: { at: number; key: string; body: string } | null = null

  app.get('/', c => {
    const team = c.get('team_id')
    // Handles stay listed for everyone (the sender roster needs them); presence detail is
    // filtered by workgroup, so the cache is per (team, visible set).
    const visible = c.get('grant').visible
    const key = `${team}|${[...visible].sort().join(',')}`
    if (cached && cached.key === key && Date.now() - cached.at < TTL_MS) {
      return c.body(cached.body, 200, { 'content-type': 'application/json' })
    }
    const humans = deps.db.prepare(
      "SELECT id, handle, display_name FROM human WHERE team_id=? AND disabled_at IS NULL"
    ).all(team) as HumanRow[]

    const list = humans.map(h => {
      const snap = deps.presence.get(team, h.handle, visible)
      return {
        handle: h.handle,
        display_name: h.display_name,
        online: Boolean(snap),
        summary: snap?.summary ?? '',
        last_seen: snap?.last_seen ?? null,
        sessions: snap?.sessions ?? [],
      }
    })
    const body = JSON.stringify(list)
    cached = { at: Date.now(), key, body }
    return c.body(body, 200, { 'content-type': 'application/json' })
  })
  return app
}
