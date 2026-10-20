import { Hono } from 'hono'
import { OutboundMessageSchema, SessionNameSchema, type Envelope } from '@claude-mesh/shared'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import { hashToken } from '../auth/hash.ts'
import { rateLimit } from '../middleware/rate-limit.ts'
import type { Deps } from '../deps.ts'
import type { Route } from '../fanout.ts'

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
    let sender: { session?: string; name: string; login?: string } | null = null
    const grant = c.get('grant')
    let senderWg = grant.workgroup
    const claimed = c.req.header('x-mesh-session')
    if (claimed !== undefined) {
      const own = deps.sessions!.owned(claimed, tokenId)
      if (!own) return c.json({ error: 'unknown_sender_session' }, 403)
      sender = { session: own.session_id, name: own.name, ...(own.login ? { login: own.login } : {}) }
      senderWg = own.workgroup
    } else {
      // A send-only sender (a script, a CLI, an agent without a session) may label itself.
      // The label is the account's own choice, like a session name; only the account is verified.
      const label = c.req.header('x-mesh-sender-name')
      if (label !== undefined) {
        const name = SessionNameSchema.safeParse(label)
        if (!name.success) return c.json({ error: 'invalid_sender_name' }, 400)
        sender = { name: name.data }
      }
    }

    // Session-addressed messages need a live (or reconnecting) target owned by `to`.
    const toSession = parsed.data.to_session
    if (toSession !== undefined) {
      const target = deps.sessions!.get(toSession)
      if (!target || target.team_id !== c.get('team_id') || target.handle !== parsed.data.to) {
        return c.json({ error: 'no_live_session' }, 404)
      }
      // A session in a workgroup this token cannot see is unreachable, except to answer a
      // message that session itself sent to this sender.
      if (!grant.visible.includes(target.workgroup)
        && !isReplyTo(parsed.data.in_reply_to ?? null, toSession, c.get('human').handle, sender?.session ?? null)) {
        return c.json({ error: 'cross_workgroup' }, 403)
      }
    }

    const route: Route = { from_wg: senderWg, scope: grant.visible }
    let envelope: Envelope
    try {
      envelope = deps.store.insert(c.get('team_id'), c.get('human').handle, parsed.data, sender, route)
    } catch (err) {
      const message = err instanceof Error ? err.message : ''
      return c.json({ error: 'invalid_message', message }, 400)
    }

    const isDelivered = deps.fanout.deliver(envelope, route) > 0
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

  /** The parent was sent by `fromSession` to this handle (and to this session, when it was session-addressed). */
  function isReplyTo(inReplyTo: string | null, fromSession: string, myHandle: string, mySession: string | null): boolean {
    if (!inReplyTo) return false
    const p = deps.db.prepare('SELECT from_session, to_handle, to_session FROM message WHERE id=?')
      .get(inReplyTo) as { from_session: string | null; to_handle: string; to_session: string | null } | undefined
    return !!p && p.from_session === fromSession && p.to_handle === myHandle && (p.to_session === null || p.to_session === mySession)
  }

  return app
}
