import { Hono } from 'hono'
import { streamSSE } from 'hono/streaming'
import { isValidMessageId, SessionIdSchema, SessionNameSchema, LoginSchema, type Envelope } from '@claude-mesh/shared'
import { SessionOwnershipError, type SessionStatus } from '../sessions/registry.ts'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import type { Deps } from '../deps.ts'
import type { Subscriber } from '../fanout.ts'

const PING_INTERVAL_MS = 25_000

export function streamRoute(deps: Deps) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))

  app.get('/', c => {
    const since = c.req.query('since')
    if (since !== undefined && !isValidMessageId(since)) {
      return c.json({ error: 'invalid_since' }, 400)
    }

    // Optional session binding: a peer-agent serving one Claude Code session.
    const sessionParam = c.req.query('session')
    let session: string | null = null
    if (sessionParam !== undefined) {
      const sid = SessionIdSchema.safeParse(sessionParam)
      const name = SessionNameSchema.safeParse(c.req.query('name'))
      if (!sid.success || !name.success) return c.json({ error: 'invalid_session' }, 400)
      const statusQ = c.req.query('status')
      const status: SessionStatus | undefined =
        statusQ === 'busy' || statusQ === 'idle' ? statusQ : undefined
      try {
        deps.sessions!.attach({
          session_id: sid.data,
          team_id: c.get('team_id'),
          handle: c.get('human').handle,
          token_id: c.get('token').id,
          device: c.get('token').label,
          name: name.data,
          cwd: c.req.query('cwd')?.slice(0, 1024),
          login: LoginSchema.safeParse(c.req.query('login')).data,
          status,
        })
      } catch (err) {
        if (err instanceof SessionOwnershipError) return c.json({ error: 'session_owned_elsewhere' }, 409)
        throw err
      }
      session = sid.data
    }

    return streamSSE(c, async stream => {
      const team_id = c.get('team_id')
      const handle = c.get('human').handle

      const backlog = since
        ? deps.store.fetchSince(team_id, handle, since, session)
        : deps.store.fetchPendingFor(team_id, handle, session)
      for (const e of backlog) {
        await stream.writeSSE({ event: 'message', data: JSON.stringify(e) })
        deps.store.markDelivered(e.id)
      }

      const queue: string[] = []
      let notify: (() => void) | null = null
      const sub: Subscriber = {
        handle,
        team_id,
        ...(session ? { session } : {}),
        deliver: (e: Envelope) => {
          queue.push(JSON.stringify(e))
          notify?.()
        }
      }
      deps.fanout.subscribe(sub)

      const pingTimer = setInterval(() => {
        stream.writeSSE({ event: 'ping', data: String(Date.now()) }).catch(() => { /* client gone */ })
      }, PING_INTERVAL_MS)

      let cleaned = false
      const cleanup = () => {
        if (cleaned) return
        cleaned = true
        deps.fanout.unsubscribe(sub)
        clearInterval(pingTimer)
        if (session) deps.sessions!.detach(session)
      }
      c.req.raw.signal?.addEventListener('abort', cleanup)

      try {
        while (!c.req.raw.signal?.aborted) {
          if (queue.length === 0) {
            await new Promise<void>(resolve => {
              notify = () => { notify = null; resolve() }
            })
            continue
          }
          const payload = queue.shift()!
          await stream.writeSSE({ event: 'message', data: payload })
          const parsed = JSON.parse(payload) as Envelope
          deps.store.markDelivered(parsed.id)
        }
      } finally {
        cleanup()
      }
    })
  })
  return app
}
