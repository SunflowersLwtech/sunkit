import { Hono, type Context } from 'hono'
import { streamSSE } from 'hono/streaming'
import { CommandRequestSchema, CommandResultSchema, MachineReportSchema } from '@claude-mesh/shared'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import { createLimiter } from '../middleware/rate-limit.ts'
import { audit } from '../audit.ts'
import type { Command, CommandQueue, MachineRegistry } from '../machines/registry.ts'
import type { Deps } from '../deps.ts'

const PING_INTERVAL_MS = 25_000
type C = Context<{ Variables: AuthContext }>
type MachineDeps = Deps & { machines: MachineRegistry; commands: CommandQueue }

/** The machine an executor token is bound to, or null when the caller is not an executor. */
function executorMachine(c: C): string | null {
  const g = c.get('grant')
  return g.role === 'executor' && g.machine ? g.machine : null
}

export function machinesRoute(deps: MachineDeps) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))
  const reports = createLimiter(5_000, 2)
  const issues = createLimiter(60_000, 60)

  app.get('/', c => c.json(deps.machines.list(c.get('team_id'), c.get('grant').visible)))

  // The machine name comes from the token's grant, never from the body: an executor reports for one machine only.
  app.post('/self', async c => {
    const machine = executorMachine(c)
    if (!machine) return c.json({ error: 'not_an_executor' }, 403)
    const parsed = MachineReportSchema.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    const retry = reports.hit(c.get('token').id)
    if (retry > 0) return c.json({ error: 'rate_limited' }, 429, { 'retry-after': String(retry) })
    deps.machines.report(c.get('team_id'), machine, c.get('grant').workgroup, c.get('token').id, parsed.data)
    return c.json({ ok: true, machine })
  })

  app.get('/self/stream', c => {
    const machine = executorMachine(c)
    if (!machine) return c.json({ error: 'not_an_executor' }, 403)
    const team = c.get('team_id')
    return streamSSE(c, async stream => {
      const queue: Command[] = []
      let notify: (() => void) | null = null
      const { backlog, stop } = deps.commands.listen(team, machine, cmd => { queue.push(cmd); notify?.() })
      queue.push(...backlog)
      deps.machines.attach(team, machine)
      const ping = setInterval(() => {
        stream.writeSSE({ event: 'ping', data: String(Date.now()) }).catch(() => { /* gone */ })
      }, PING_INTERVAL_MS)
      let cleaned = false
      const cleanup = () => {
        if (cleaned) return
        cleaned = true
        stop()
        clearInterval(ping)
        deps.machines.detach(team, machine)
      }
      c.req.raw.signal?.addEventListener('abort', cleanup)
      try {
        while (!c.req.raw.signal?.aborted) {
          if (queue.length === 0) {
            await new Promise<void>(resolve => { notify = () => { notify = null; resolve() } })
            continue
          }
          const cmd = queue.shift()!
          if (deps.commands.get(cmd.id)?.state !== 'queued') continue
          await stream.writeSSE({ event: 'command', data: JSON.stringify({ id: cmd.id, op: cmd.op, args: cmd.args, expires_at: new Date(cmd.expires_at).toISOString() }) })
          deps.commands.markClaimed(cmd)
        }
      } finally {
        cleanup()
      }
    })
  })

  app.post('/:machine/commands', async c => {
    if (c.get('grant').role !== 'orchestrator') return c.json({ error: 'not_a_dispatcher' }, 403)
    const team = c.get('team_id')
    const machine = c.req.param('machine')
    const m = deps.machines.get(team, machine)
    if (!m || !c.get('grant').visible.includes(m.workgroup)) return c.json({ error: 'unknown_machine' }, 404)
    const parsed = CommandRequestSchema.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    const retry = issues.hit(c.get('token').id)
    if (retry > 0) return c.json({ error: 'rate_limited' }, 429, { 'retry-after': String(retry) })
    const claimed = c.req.header('x-mesh-session')
    const own = claimed ? deps.sessions!.owned(claimed, c.get('token').id) : undefined
    if (claimed && !own) return c.json({ error: 'unknown_sender_session' }, 403)
    const cmd = deps.commands.issue(team, machine, parsed.data, {
      token_id: c.get('token').id, human_id: c.get('human').id, session: own?.session_id ?? null, name: own?.name ?? c.get('token').label,
    })
    audit(deps.db, team, c.get('human').id, 'dispatch.issue',
      { cmd_id: cmd.id, op: cmd.op, machine, by: cmd.issuer.name, ...(cmd.op === 'read' ? { pane: cmd.args.pane as string } : {}) },
      new Date(cmd.issued_at).toISOString())
    return c.json(deps.commands.view(cmd), 202)
  })

  return app
}

export function commandsRoute(deps: MachineDeps) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'human' }))

  app.get('/:id', async c => {
    const id = c.req.param('id')
    let cmd = deps.commands.get(id)
    // Only the token that issued it reads it: a read op's output is somebody's screen.
    if (!cmd || cmd.team_id !== c.get('team_id') || cmd.issuer.token_id !== c.get('token').id) return c.json({ error: 'not_found' }, 404)
    const wait = Math.min(25, Math.max(0, Number(c.req.query('wait') ?? 0) || 0))
    if (wait > 0 && (cmd.state === 'queued' || cmd.state === 'claimed')) {
      await deps.commands.wait(id, wait * 1000)
      cmd = deps.commands.get(id) ?? cmd
    }
    return c.json(deps.commands.view(cmd))
  })

  app.post('/:id/result', async c => {
    const machine = executorMachine(c)
    if (!machine) return c.json({ error: 'not_an_executor' }, 403)
    const cmd = deps.commands.get(c.req.param('id'))
    if (!cmd || cmd.team_id !== c.get('team_id')) return c.json({ error: 'not_found' }, 404)
    if (cmd.machine !== machine) return c.json({ error: 'wrong_machine' }, 403)
    const parsed = CommandResultSchema.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    if (!deps.commands.complete(cmd, parsed.data)) return c.json({ error: 'command_final', state: cmd.state }, 409)
    audit(deps.db, cmd.team_id, c.get('human').id, 'dispatch.ack',
      { cmd_id: cmd.id, op: cmd.op, machine, ok: parsed.data.ok }, deps.now().toISOString())
    return c.json({ ok: true, state: cmd.state })
  })

  return app
}
