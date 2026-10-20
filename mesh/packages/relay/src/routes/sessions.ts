import { Hono } from 'hono'
import { CardPatchSchema, redactUrlCredentials } from '@claude-mesh/shared'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import { createLimiter } from '../middleware/rate-limit.ts'
import type { Deps } from '../deps.ts'

export function sessionsRoute(deps: Deps) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))
  // Keyed by (token, session): one machine's device token serves many sessions, and a busy
  // machine must not starve its own sessions' card writes.
  const limiter = createLimiter(1_000, 5)

  app.get('/', c => {
    const views = deps.sessions!.listTeam(c.get('team_id'), c.get('grant').visible)
    const taskIds = [...new Set(views.map(v => v.task_id).filter((t): t is string => !!t))]
    if (taskIds.length === 0) return c.json(views)
    // dispatched_by is derived from the task, never written by the session.
    const rows = deps.db.prepare(
      `SELECT id, dispatcher_name FROM task WHERE team_id=? AND id IN (${taskIds.map(() => '?').join(',')})`,
    ).all(c.get('team_id'), ...taskIds) as Array<{ id: string; dispatcher_name: string | null }>
    const by = new Map(rows.map(r => [r.id, r.dispatcher_name]))
    return c.json(views.map(v => (v.task_id && by.get(v.task_id) ? { ...v, dispatched_by: by.get(v.task_id) } : v)))
  })

  app.post('/self', async c => {
    const parsed = CardPatchSchema.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    const { session, ...patch } = parsed.data
    const token = c.get('token')
    const retry = limiter.hit(`${token.id}:${session}`)
    if (retry > 0) return c.json({ error: 'rate_limited' }, 429, { 'retry-after': String(retry) })
    if (!deps.sessions!.owned(session, token.id)) return c.json({ error: 'unknown_session' }, 404)

    if (patch.workgroup !== undefined && !c.get('grant').visible.includes(patch.workgroup)) {
      return c.json({ error: 'workgroup_not_granted' }, 403)
    }
    if (patch.task_id !== undefined) {
      const t = deps.db.prepare('SELECT assignee_token, assignee_session FROM task WHERE id=? AND team_id=?')
        .get(patch.task_id, c.get('team_id')) as { assignee_token: string | null; assignee_session: string | null } | undefined
      if (!t || t.assignee_token !== token.id) return c.json({ error: 'task_not_assigned' }, 403)
    }
    if (patch.cwd !== undefined) patch.cwd = redactUrlCredentials(patch.cwd)

    deps.sessions!.update(session, token.id, patch)
    return c.json({ ok: true })
  })
  return app
}
