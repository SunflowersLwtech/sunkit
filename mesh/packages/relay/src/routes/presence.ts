import { Hono } from 'hono'
import { z } from 'zod'
import { TEAM_BROADCAST_HANDLE } from '@claude-mesh/shared'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import { rateLimit } from '../middleware/rate-limit.ts'
import type { Deps } from '../deps.ts'

const PresenceBody = z.object({
  summary: z.string().max(200),
  cwd: z.string().max(1024).optional(),
  branch: z.string().max(256).optional(),
  repo: z.string().max(256).optional(),
})

export function presenceRoute(deps: Deps) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))
  app.use('*', rateLimit({ windowMs: 1_000, max: 1, key: c => `pres:${c.get('token').id}` }))
  app.post('/', async c => {
    const parsed = PresenceBody.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    const team = c.get('team_id')
    const handle = c.get('human').handle
    const label = c.get('token').label
    deps.presence.set(team, handle, label, parsed.data)

    const meta: Record<string, string> = { label }
    if (parsed.data.cwd !== undefined) meta.cwd = parsed.data.cwd
    if (parsed.data.branch !== undefined) meta.branch = parsed.data.branch
    if (parsed.data.repo !== undefined) meta.repo = parsed.data.repo

    const envelope = deps.store.insert(team, handle, {
      to: TEAM_BROADCAST_HANDLE,
      kind: 'presence_update',
      content: parsed.data.summary,
      meta,
    })
    deps.fanout.deliver(envelope)
    return c.json({ ok: true })
  })
  return app
}
