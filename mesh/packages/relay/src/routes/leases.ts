import { Hono, type Context } from 'hono'
import { z } from 'zod'
import {
  LeaseAcquireSchema, MAX_LEASE_TTL_S, MIN_LEASE_TTL_S, TASK_BOUND_LEASE_PREFIXES, isTerminalTaskState,
} from '@claude-mesh/shared'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import { createLimiter } from '../middleware/rate-limit.ts'
import { audit } from '../audit.ts'
import type { LeaseRow, LeaseStore } from '../ledger/leases.ts'
import type { TaskStore } from '../ledger/tasks.ts'
import type { SessionEntry } from '../sessions/registry.ts'
import type { Deps } from '../deps.ts'

type C = Context<{ Variables: AuthContext }>
const RenewBody = z.object({ ttl_s: z.number().int().min(MIN_LEASE_TTL_S).max(MAX_LEASE_TTL_S).optional() }).strict()

export function leasesRoute(deps: Deps & { leases: LeaseStore; tasks: TaskStore }) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))
  const writes = createLimiter(60_000, 60)
  const store = deps.leases

  /** A lease is held by a session; the caller names its own with x-mesh-session. */
  function holderSession(c: C): SessionEntry | 'missing' | 'not_owned' {
    const claimed = c.req.header('x-mesh-session')
    if (claimed === undefined) return 'missing'
    return deps.sessions!.owned(claimed, c.get('token').id) ?? 'not_owned'
  }

  function sees(c: C, l: LeaseRow): boolean {
    return c.get('grant').visible.includes(l.workgroup)
  }

  function limited(c: C) {
    const retry = writes.hit(c.get('token').id)
    return retry > 0 ? c.json({ error: 'rate_limited' }, 429, { 'retry-after': String(retry) }) : null
  }

  // Lists only what the caller may see; a lease held elsewhere still shows up as held (holder hidden) on a 409.
  app.get('/', c => {
    const name = c.req.query('name')
    const rows = store.listLive(c.get('team_id')).filter(l => sees(c, l) && (name === undefined || l.name === name))
    return c.json(rows.map(l => store.view(l, true)))
  })

  app.post('/', async c => {
    const parsed = LeaseAcquireSchema.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    const me = holderSession(c)
    if (me === 'missing') return c.json({ error: 'session_required' }, 400)
    if (me === 'not_owned') return c.json({ error: 'unknown_sender_session' }, 403)
    if (c.get('grant').role === 'observer') return c.json({ error: 'read_only' }, 403)
    const body = parsed.data
    const team = c.get('team_id')

    // A task named on a lease must be the holder's own live task (its dispatcher may then force-release it).
    if (body.task_id) {
      const t = deps.tasks.get(team, body.task_id)
      const ok = t && !isTerminalTaskState(t.state) && t.assignee_token === c.get('token').id && t.assignee_session === me.session_id
      if (!ok) return c.json({ error: 'task_not_assigned' }, 403)
    }
    // A deploy or a credential rotation hangs off live work the holder owns, never a free-floating lock.
    if (TASK_BOUND_LEASE_PREFIXES.some(p => body.name.startsWith(p)) && !body.task_id) {
      return c.json({ error: 'lease_needs_task' }, 403)
    }
    const tooMany = limited(c)
    if (tooMany) return tooMany

    const r = store.acquire(team, body.name, body.ttl_s, {
      session: me.session_id, name: me.name, machine: me.card.herdr?.machine ?? me.device, token: c.get('token').id, workgroup: me.workgroup,
    }, { task_id: body.task_id ?? null, note: body.note ?? null })
    const nowIso = deps.now().toISOString()
    if (!r.ok && r.error === 'lease_quota') {
      return c.json({ error: 'lease_quota', max: 3 }, 429)
    }
    if (!r.ok) {
      const view = store.view(r.lease, sees(c, r.lease))
      const mins = Math.ceil(view.ttl_remaining_s / 60)
      const who = view.holder ? `${view.holder.name}${view.holder.machine ? ` on ${view.holder.machine}` : ''}` : 'a session you cannot see'
      return c.json({ error: 'lease_held', lease: view, message: `${body.name} is held by ${who} for another ${mins} min` }, 409)
    }
    if (r.expired) {
      audit(deps.db, team, null, 'lease.expire', { lease_id: r.expired.id, name: r.expired.name, holder: r.expired.holder_name }, nowIso)
    }
    audit(deps.db, team, c.get('human').id, 'lease.acquire',
      { lease_id: r.lease.id, name: r.lease.name, holder: r.lease.holder_name, machine: r.lease.holder_machine, ttl_s: r.lease.ttl_s, task_id: r.lease.task_id }, nowIso)
    return c.json(store.view(r.lease, true), 201)
  })

  app.post('/:id/renew', async c => {
    const lease = store.get(c.get('team_id'), c.req.param('id'))
    if (!lease || !sees(c, lease)) return c.json({ error: 'not_found' }, 404)
    const parsed = RenewBody.safeParse(await c.req.json().catch(() => ({})))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    const me = holderSession(c)
    if (typeof me === 'string' || lease.holder_token !== c.get('token').id || lease.holder_session !== me.session_id) {
      return c.json({ error: 'not_holder' }, 403)
    }
    const r = store.renew(c.get('team_id'), lease.id, parsed.data.ttl_s ?? lease.ttl_s)
    if (!r.ok) return c.json({ error: r.error }, r.error === 'lease_quota' ? 429 : 409)
    return c.json(store.view(r.lease, true))
  })

  app.delete('/:id', c => {
    const lease = store.get(c.get('team_id'), c.req.param('id'))
    if (!lease || !sees(c, lease)) return c.json({ error: 'not_found' }, 404)
    const me = holderSession(c)
    const tokenId = c.get('token').id
    const isHolder = typeof me !== 'string' && lease.holder_token === tokenId && lease.holder_session === me.session_id
    const task = lease.task_id ? deps.tasks.get(c.get('team_id'), lease.task_id) : undefined
    const isDispatcher = task?.dispatcher_token === tokenId
    const canForce = c.get('grant').role === 'orchestrator' || c.get('token').tier === 'admin'
    if (!isHolder && !isDispatcher && !canForce) return c.json({ error: 'not_holder' }, 403)
    const reason = isHolder ? 'release' : 'force'
    if (!store.release(c.get('team_id'), lease.id, reason)) return c.json({ error: 'already_released' }, 409)
    audit(deps.db, c.get('team_id'), c.get('human').id, reason === 'release' ? 'lease.release' : 'lease.force_release',
      { lease_id: lease.id, name: lease.name, holder: lease.holder_name }, deps.now().toISOString())
    return c.json({ ok: true })
  })

  return app
}
