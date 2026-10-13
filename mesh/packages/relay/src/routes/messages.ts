import { Hono } from 'hono'
import { OutboundMessageSchema, TEAM_BROADCAST_HANDLE, type Envelope } from '@claude-mesh/shared'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import { hashToken } from '../auth/hash.ts'
import { rateLimit } from '../middleware/rate-limit.ts'
import type { Deps } from '../deps.ts'

export function messagesRoute(deps: Deps) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))
  app.use('*', rateLimit({ windowMs: 60_000, max: 120, key: c => `msg:${c.get('token').id}` }))

  app.post('/', async c => {
    const idemKey = c.req.header('idempotency-key')
    const tokenId = c.get('token').id
    if (idemKey) {
      const row = deps.db.prepare(
        "SELECT response_json FROM idempotency_key WHERE key_hash=? AND token_id=?"
      ).get(hashToken(`${tokenId}:${idemKey}`), tokenId) as { response_json: string } | undefined
      if (row) return c.body(row.response_json, 201, { 'content-type': 'application/json' })
    }

    const raw = await c.req.json().catch(() => null)
    const parsed = OutboundMessageSchema.safeParse(raw)
    if (!parsed.success) {
      return c.json({ error: 'invalid_body', issues: parsed.error.issues }, 400)
    }

    // Sender session: optional, but if claimed it must belong to this token.
    let sender: { session: string; name: string } | null = null
    const claimed = c.req.header('x-mesh-session')
    if (claimed !== undefined) {
      const own = deps.sessions!.owned(claimed, tokenId)
      if (!own) return c.json({ error: 'unknown_sender_session' }, 403)
      sender = { session: own.session_id, name: own.name }
    }

    // Session-addressed messages need a live (or reconnecting) target owned by `to`.
    const toSession = parsed.data.to_session
    if (toSession !== undefined) {
      const target = deps.sessions!.get(toSession)
      if (!target || target.team_id !== c.get('team_id') || target.handle !== parsed.data.to) {
        return c.json({ error: 'no_live_session' }, 404)
      }
    }

    let envelope: Envelope
    try {
      envelope = deps.store.insert(c.get('team_id'), c.get('human').handle, parsed.data, sender)
    } catch (err) {
      const message = err instanceof Error ? err.message : ''
      return c.json({ error: 'invalid_message', message }, 400)
    }

    deps.fanout.deliver(envelope)
    const isDelivered = envelope.to === TEAM_BROADCAST_HANDLE
      ? deps.fanout.onlineHandles(envelope.team).some(h => h !== envelope.from)
      : envelope.to_session
        ? deps.fanout.isSessionOnline(envelope.team, envelope.to, envelope.to_session)
        : deps.fanout.isOnline(envelope.team, envelope.to)
    if (isDelivered) {
      deps.store.markDelivered(envelope.id)
      envelope = { ...envelope, delivered_at: deps.now().toISOString() }
    }

    const responseJson = JSON.stringify(envelope)
    if (idemKey) {
      deps.db.prepare(`
        INSERT OR IGNORE INTO idempotency_key(key_hash, token_id, response_json, created_at)
        VALUES (?, ?, ?, ?)
      `).run(hashToken(`${tokenId}:${idemKey}`), tokenId, responseJson, deps.now().toISOString())
    }
    return c.body(responseJson, 201, { 'content-type': 'application/json' })
  })

  return app
}
