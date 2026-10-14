import { Hono } from 'hono'
import type { Deps } from '../deps.ts'

export function metricsRoute(deps: Deps) {
  const app = new Hono()
  app.get('/', c => {
    const msgTotal = deps.db.prepare("SELECT COUNT(*) AS c FROM message").get() as { c: number }
    const tokenLive = deps.db.prepare("SELECT COUNT(*) AS c FROM token WHERE revoked_at IS NULL").get() as { c: number }
    const body = [
      '# HELP mesh_messages_total Total messages accepted by this relay',
      '# TYPE mesh_messages_total counter',
      `mesh_messages_total ${msgTotal.c}`,
      '# HELP mesh_tokens_live Count of currently live tokens',
      '# TYPE mesh_tokens_live gauge',
      `mesh_tokens_live ${tokenLive.c}`,
    ].join('\n') + '\n'
    return c.body(body, 200, { 'content-type': 'text/plain; version=0.0.4' })
  })
  return app
}
