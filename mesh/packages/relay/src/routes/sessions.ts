import { Hono } from 'hono'
import { z } from 'zod'
import { SessionNameSchema, LoginSchema } from '@claude-mesh/shared'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import { rateLimit } from '../middleware/rate-limit.ts'
import type { Deps } from '../deps.ts'

const UpdateBody = z.object({
  session: z.string(),
  name: SessionNameSchema.optional(),
  cwd: z.string().max(1024).optional(),
  login: LoginSchema.optional(),
  status: z.enum(['busy', 'idle', 'unknown']).optional(),
}).strict()

export function sessionsRoute(deps: Deps) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))

  app.get('/', c => c.json(deps.sessions!.listTeam(c.get('team_id'))))

  app.post(
    '/self',
    rateLimit({ windowMs: 1_000, max: 5, key: c => `sess:${c.req.header('authorization') ?? ''}` }),
    async c => {
      const parsed = UpdateBody.safeParse(await c.req.json().catch(() => null))
      if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
      const { session, ...patch } = parsed.data
      const ok = deps.sessions!.update(session, c.get('token').id, patch)
      return ok ? c.json({ ok: true }) : c.json({ error: 'unknown_session' }, 404)
    },
  )
  return app
}
