import { Hono } from 'hono'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import { createLimiter } from '../middleware/rate-limit.ts'
import type { Deps } from '../deps.ts'

/** A page or a pusher reads about once a minute; this leaves room for a few of them per token. */
export const EVENT_READS_PER_MINUTE = 30
const DEFAULT_LIMIT = 200
const MAX_LIMIT = 500

/**
 * GET /v1/events: the delivery log, read-only. Who sent what to whom, when the relay stored it and
 * when a stream took it; never the content. `since_seq` resumes after a row, `limit` caps the page.
 */
export function eventsRoute(deps: Deps) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))
  const reads = createLimiter(60_000, EVENT_READS_PER_MINUTE)

  app.get('/', c => {
    const retry = reads.hit(c.get('token').id)
    if (retry > 0) return c.json({ error: 'rate_limited' }, 429, { 'retry-after': String(retry) })
    const sinceQ = c.req.query('since_seq')
    let sinceSeq: number | undefined
    if (sinceQ !== undefined) {
      sinceSeq = Number(sinceQ)
      if (!/^\d{1,15}$/.test(sinceQ) || !Number.isSafeInteger(sinceSeq)) return c.json({ error: 'invalid_since_seq' }, 400)
    }
    const limitQ = c.req.query('limit')
    const limit = limitQ === undefined ? DEFAULT_LIMIT : Number(limitQ)
    if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) return c.json({ error: 'invalid_limit' }, 400)
    return c.json(deps.store.events(c.get('team_id'), c.get('grant').visible, { ...(sinceSeq !== undefined ? { sinceSeq } : {}), limit }))
  })
  return app
}
