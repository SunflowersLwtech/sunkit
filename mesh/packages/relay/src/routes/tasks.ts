import { Hono, type Context } from 'hono'
import {
  ArtifactSchema, TaskCreateSchema, TaskUpdateSchema, isTerminalTaskState, type TaskState,
} from '@claude-mesh/shared'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import { createLimiter } from '../middleware/rate-limit.ts'
import { audit } from '../audit.ts'
import { checkTransition, type TaskRow, type TaskStore } from '../ledger/tasks.ts'
import type { SessionEntry } from '../sessions/registry.ts'
import type { Deps } from '../deps.ts'

/** Orchestrator-dispatched tasks are depth 1; a task under one of those would be depth 2, which is refused. */
export const MAX_DISPATCH_DEPTH = 1

type C = Context<{ Variables: AuthContext }>

export function tasksRoute(deps: Deps & { tasks: TaskStore }) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))
  const creates = createLimiter(60 * 60_000, 60)
  const writes = createLimiter(60_000, 60)
  const store = deps.tasks

  /** The caller's own session, when it names one; it must belong to the calling token. */
  function callerSession(c: C): { ok: true; entry: SessionEntry | null } | { ok: false } {
    const claimed = c.req.header('x-mesh-session')
    if (claimed === undefined) return { ok: true, entry: null }
    const own = deps.sessions!.owned(claimed, c.get('token').id)
    return own ? { ok: true, entry: own } : { ok: false }
  }

  function visibleRow(c: C, id: string): TaskRow | undefined {
    const row = store.get(c.get('team_id'), id)
    return row && c.get('grant').visible.includes(row.workgroup) ? row : undefined
  }

  function actorOf(c: C, row: TaskRow, me: SessionEntry | null) {
    const tokenId = c.get('token').id
    return {
      dispatcher: row.dispatcher_token === tokenId,
      // A session-assigned task is updated by that session, not by its siblings behind the same token.
      assignee: row.assignee_token === tokenId && (row.assignee_session === null || me?.session_id === row.assignee_session),
    }
  }

  function publish(c: C, row: TaskRow) {
    deps.fanout.deliverEvent(c.get('team_id'), row.workgroup, 'task', JSON.stringify({ type: 'task', task: store.view(row) }))
  }

  function limited(c: C, limiter: ReturnType<typeof createLimiter>) {
    const retry = limiter.hit(c.get('token').id)
    return retry > 0 ? c.json({ error: 'rate_limited' }, 429, { 'retry-after': String(retry) }) : null
  }

  app.get('/', c => {
    const raw = Number(c.req.query('since_seq') ?? 0)
    const since = Number.isInteger(raw) && raw >= 0 ? raw : 0
    const limit = 500
    const rows = store.list(c.get('team_id'), c.get('grant').visible, since, limit)
    // A full page resumes from its last row; otherwise from the team's current counter.
    const seq = rows.length === limit ? rows[rows.length - 1]!.seq : Math.max(since, store.currentSeq(c.get('team_id')))
    return c.json({ tasks: rows.map(r => store.view(r)), seq })
  })

  app.get('/:id', c => {
    const row = visibleRow(c, c.req.param('id'))
    return row ? c.json(store.view(row)) : c.json({ error: 'not_found' }, 404)
  })

  app.post('/', async c => {
    const parsed = TaskCreateSchema.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    const caller = callerSession(c)
    if (!caller.ok) return c.json({ error: 'unknown_sender_session' }, 403)
    const me = caller.entry
    const grant = c.get('grant')
    const token = c.get('token')
    const body = parsed.data

    let parent: TaskRow | undefined
    if (body.parent_task) {
      parent = visibleRow(c, body.parent_task)
      if (!parent) return c.json({ error: 'unknown_parent' }, 404)
    }

    let assignee: SessionEntry
    let depth: number
    let state: TaskState
    if (!body.assignee || body.assignee === me?.session_id) {
      // Bookkeeping for one's own work (a person started this session): nothing is dispatched.
      if (!me) return c.json({ error: 'session_required' }, 400)
      assignee = me
      depth = 0
      state = 'working'
    } else {
      // Role is read from the calling token. A worker sharing a machine (and so a token file
      // path) with the orchestrator cannot borrow it by naming the orchestrator's session.
      if (grant.role !== 'orchestrator') return c.json({ error: 'not_a_dispatcher' }, 403)
      const target = deps.sessions!.get(body.assignee)
      if (!target || target.team_id !== c.get('team_id')) return c.json({ error: 'no_live_session' }, 404)
      if (!grant.visible.includes(target.workgroup)) return c.json({ error: 'cross_workgroup' }, 403)
      depth = parent ? parent.depth + 1 : 1
      if (depth > MAX_DISPATCH_DEPTH) return c.json({ error: 'depth_exceeded', max: MAX_DISPATCH_DEPTH }, 403)
      assignee = target
      state = 'submitted'
    }
    const tooMany = limited(c, creates)
    if (tooMany) return tooMany

    const row = store.create({
      team_id: c.get('team_id'),
      workgroup: assignee.workgroup,
      title: body.title,
      state,
      assignee: { session: assignee.session_id, name: assignee.name, machine: assignee.card.herdr?.machine ?? assignee.device, token: assignee.token_id },
      dispatcher: { session: me?.session_id ?? null, name: me?.name ?? token.label, token: token.id },
      parent_task: parent?.id ?? null,
      depth,
      prompt_sha256: body.prompt_sha256 ?? null,
      deadline: body.deadline ?? null,
    })
    audit(deps.db, c.get('team_id'), c.get('human').id, 'task.create',
      { task_id: row.id, to: row.state, assignee: row.assignee_name, machine: row.assignee_machine, depth: row.depth }, row.created_at)
    publish(c, row)
    return c.json(store.view(row), 201)
  })

  app.patch('/:id', async c => {
    const row = visibleRow(c, c.req.param('id'))
    if (!row) return c.json({ error: 'not_found' }, 404)
    const parsed = TaskUpdateSchema.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    const caller = callerSession(c)
    if (!caller.ok) return c.json({ error: 'unknown_sender_session' }, 403)
    const actor = actorOf(c, row, caller.entry)
    if (!actor.assignee && !actor.dispatcher) return c.json({ error: 'not_allowed' }, 403)
    const to = parsed.data.state
    const nowIso = deps.now().toISOString()

    if (isTerminalTaskState(row.state)) {
      // A late or reordered update must never reopen a finished task.
      audit(deps.db, c.get('team_id'), c.get('human').id, 'task.transition.reject',
        { task_id: row.id, from: row.state, to: to ?? null, reason: 'terminal' }, nowIso)
      return c.json({ error: 'task_terminal', state: row.state }, 409)
    }
    if (to !== undefined) {
      const check = checkTransition(row.state, to, actor)
      if (!check.ok) return c.json({ error: check.error, state: row.state }, check.status)
    }
    const tooMany = limited(c, writes)
    if (tooMany) return tooMany

    const r = store.update(c.get('team_id'), row.id, {
      ...(to !== undefined ? { state: to } : {}),
      ...(parsed.data.progress !== undefined ? { progress: parsed.data.progress } : {}),
      ...(parsed.data.reason !== undefined ? { reason: parsed.data.reason } : {}),
    }, parsed.data.if_seq)
    if (!r.ok) return c.json({ error: 'task_conflict', seq: r.seq }, 409)
    if (to !== undefined && to !== row.state) {
      audit(deps.db, c.get('team_id'), c.get('human').id, 'task.transition',
        { task_id: row.id, from: row.state, to, by: actor.dispatcher ? 'dispatcher' : 'assignee' }, nowIso)
    }
    publish(c, r.row)
    return c.json(store.view(r.row))
  })

  app.post('/:id/artifacts', async c => {
    const row = visibleRow(c, c.req.param('id'))
    if (!row) return c.json({ error: 'not_found' }, 404)
    const parsed = ArtifactSchema.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    const caller = callerSession(c)
    if (!caller.ok) return c.json({ error: 'unknown_sender_session' }, 403)
    const actor = actorOf(c, row, caller.entry)
    if (!actor.assignee && !actor.dispatcher) return c.json({ error: 'not_allowed' }, 403)
    const tooMany = limited(c, writes)
    if (tooMany) return tooMany
    const updated = store.addArtifact(c.get('team_id'), row.id, parsed.data)
    if (updated === 'full') return c.json({ error: 'artifacts_full' }, 409)
    audit(deps.db, c.get('team_id'), c.get('human').id, 'task.artifact', { task_id: row.id, type: parsed.data.type }, updated.updated_at)
    publish(c, updated)
    return c.json(store.view(updated))
  })

  // After a restart or --resume the host gets a new session id; the same token may move its task over.
  app.post('/:id/rebind', c => {
    const row = visibleRow(c, c.req.param('id'))
    if (!row) return c.json({ error: 'not_found' }, 404)
    const caller = callerSession(c)
    if (!caller.ok || !caller.entry) return c.json({ error: 'session_required' }, 400)
    if (row.assignee_token !== c.get('token').id) return c.json({ error: 'not_allowed' }, 403)
    if (isTerminalTaskState(row.state)) return c.json({ error: 'task_terminal', state: row.state }, 409)
    const me = caller.entry
    const updated = store.rebind(c.get('team_id'), row.id, { session: me.session_id, name: me.name, machine: me.card.herdr?.machine ?? me.device })
    deps.db.prepare(`
      UPDATE lease SET holder_session=?, holder_name=? WHERE team_id=? AND task_id=? AND holder_token=? AND released_at IS NULL
    `).run(me.session_id, me.name, c.get('team_id'), row.id, c.get('token').id)
    audit(deps.db, c.get('team_id'), c.get('human').id, 'task.rebind',
      { task_id: row.id, from: row.assignee_session, to_session: me.session_id }, updated.updated_at)
    publish(c, updated)
    return c.json(store.view(updated))
  })

  return app
}
