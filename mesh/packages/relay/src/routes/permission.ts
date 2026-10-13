import { Hono } from 'hono'
import { z } from 'zod'
import type { MessageId } from '@claude-mesh/shared'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import type { Deps } from '../deps.ts'

const Body = z.object({
  request_id: z.string().regex(/^[a-km-z]{5}$/i),
  verdict: z.enum(['allow', 'deny']),
  reason: z.string().max(512).optional(),
})

interface RequestRow {
  id: string
  content: string
  from_handle: string
  meta_json: string
}

export function permissionRoute(deps: Deps) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))

  app.post('/respond', async c => {
    const parsed = Body.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)

    const team = c.get('team_id')
    const me = c.get('human').handle

    // to_handle='@team' covers ask_team routing: a broadcast request is
    // answerable by any team human, first verdict wins (spec §5).
    const rows = deps.db.prepare(`
      SELECT id, content, from_handle, meta_json
      FROM message
      WHERE team_id=? AND kind='permission_request' AND to_handle IN (?, '@team')
      ORDER BY id DESC LIMIT 50
    `).all(team, me) as RequestRow[]

    const want = parsed.data.request_id.toLowerCase()
    const req = rows
      .map(r => ({ ...r, meta: JSON.parse(r.meta_json) as Record<string, string> }))
      .find(r => (r.meta.request_id ?? '').toLowerCase() === want)

    if (!req) return c.json({ error: 'request_not_found' }, 404)

    const exp = req.meta.expires_at ? new Date(req.meta.expires_at).getTime() : 0
    if (exp && exp < Date.now()) return c.json({ error: 'request_expired' }, 410)

    const meta: Record<string, string> = {
      request_id: want,
      behavior: parsed.data.verdict,
    }
    if (parsed.data.reason !== undefined) meta.reason = parsed.data.reason

    const verdict = deps.store.insert(team, me, {
      to: req.from_handle,
      kind: 'permission_verdict',
      content: '',
      in_reply_to: req.id as MessageId,
      meta,
    })
    deps.fanout.deliver(verdict)
    const nowIso = deps.now().toISOString()
    deps.db.prepare("UPDATE message SET delivered_at=COALESCE(delivered_at,?) WHERE id=?")
      .run(nowIso, verdict.id)
    deps.db.prepare(
      "INSERT INTO audit_log(team_id,at,actor_human_id,event,detail_json) VALUES (?,?,?,?,?)"
    ).run(
      team, nowIso, c.get('human').id, 'permission.verdict',
      JSON.stringify({ request_id: want, behavior: parsed.data.verdict })
    )

    return c.json({ ok: true, verdict_id: verdict.id })
  })

  return app
}
