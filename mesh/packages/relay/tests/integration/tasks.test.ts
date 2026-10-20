import { describe, it, expect } from 'vitest'
import { harness, openSession, readSse, req, S } from './ledger-helpers.ts'

const LIUWEI = { role: 'worker' as const, workgroup: 'liuwei', visible: ['team'] }
const ORCH = { role: 'orchestrator' as const, workgroup: 'liuwei', visible: ['team'] }
const specs = [
  { id: 'tk_m4', handle: 'duocode', label: 'm4', grant: LIUWEI },
  { id: 'tk_orch', handle: 'weiliu', label: 'orch-feishu', grant: ORCH },
  { id: 'tk_aws', handle: 'weiliu', label: 'aws-sin', grant: LIUWEI },
  { id: 'tk_mate', handle: 'jovie', label: 'jovie-laptop' },
  { id: 'tk_admin', handle: 'weiliu', label: 'bootstrap-admin', tier: 'admin' as const },
]

type H = ReturnType<typeof harness>
type Task = Record<string, unknown> & { id: string; seq: number; state: string }
const create = (h: H, tok: string, body: Record<string, unknown>, session?: string) =>
  req(h.app, tok, 'POST', '/v1/tasks', body, session ? { 'x-mesh-session': session } : {})
const patch = (h: H, tok: string, id: string, body: Record<string, unknown>, session?: string) =>
  req(h.app, tok, 'PATCH', `/v1/tasks/${id}`, body, session ? { 'x-mesh-session': session } : {})

async function dispatched(h: H) {
  await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
  await openSession(h.app, h.tok.tk_m4!, S.a1, 'fr-inkrec', '&cwd=/w')
  const res = await create(h, h.tok.tk_orch!, { title: 'fix ink P1', assignee: S.a1, prompt_sha256: 'a'.repeat(64) }, S.o1)
  expect(res.status).toBe(201)
  return await res.json() as Task
}

describe('tasks: who may create them', () => {
  it('any session can register a task for itself (depth 0) and then point its card at it', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'manual-work')
    const res = await create(h, h.tok.tk_m4!, { title: 'deploy foldrender by hand' }, S.a1)
    expect(res.status).toBe(201)
    const t = await res.json() as Task
    expect(t).toMatchObject({ state: 'working', depth: 0, workgroup: 'liuwei', assignee: { session: S.a1, name: 'manual-work' } })
    expect((await req(h.app, h.tok.tk_m4!, 'POST', '/v1/sessions/self', { session: S.a1, task_id: t.id })).status).toBe(200)
  })

  it('a worker cannot hand a task to another session', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'w1')
    await openSession(h.app, h.tok.tk_aws!, S.a2, 'w2')
    const res = await create(h, h.tok.tk_m4!, { title: 'x', assignee: S.a2 }, S.a1)
    expect(res.status).toBe(403)
    expect(await res.json()).toMatchObject({ error: 'not_a_dispatcher' })
  })

  it('a worker on the orchestrator\'s machine cannot borrow its session id (role is read from the token)', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    await openSession(h.app, h.tok.tk_aws!, S.a2, 'w2')
    const res = await create(h, h.tok.tk_aws!, { title: 'x', assignee: S.a2 }, S.o1)
    expect(res.status).toBe(403)
  })

  it('an orchestrator dispatches at depth 1, and no deeper', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    expect(t).toMatchObject({ state: 'submitted', depth: 1, dispatcher: { name: 'feishu-assistant' }, assignee: { session: S.a1 } })
    const deeper = await create(h, h.tok.tk_orch!, { title: 'sub', assignee: S.a1, parent_task: t.id }, S.o1)
    expect(deeper.status).toBe(403)
    expect(await deeper.json()).toMatchObject({ error: 'depth_exceeded' })
  })

  it('never stores or returns the prompt, only its hash', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'w')
    expect((await create(h, h.tok.tk_orch!, { title: 'x', assignee: S.a1, prompt: 'secret context' }, S.o1)).status).toBe(400)
    const t = await dispatched(h)
    const got = await (await req(h.app, h.tok.tk_m4!, 'GET', `/v1/tasks/${t.id}`)).json() as Record<string, unknown>
    expect(got.prompt_sha256).toBe('a'.repeat(64))
    expect(Object.keys(got)).not.toContain('prompt')
  })

  it('a teammate cannot see or assign into a private workgroup', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    expect((await req(h.app, h.tok.tk_mate!, 'GET', `/v1/tasks/${t.id}`)).status).toBe(404)
    const all = await (await req(h.app, h.tok.tk_mate!, 'GET', '/v1/tasks')).json() as { tasks: Task[] }
    expect(all.tasks).toEqual([])
  })
})

describe('tasks: the state machine', () => {
  it('runs submitted -> working -> completed, with the relay assigning seq and auditing each step', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    const w = await patch(h, h.tok.tk_m4!, t.id, { state: 'working', progress: 'R30-R33 green' }, S.a1)
    expect(w.status).toBe(200)
    const tw = await w.json() as Task
    expect(tw.seq).toBeGreaterThan(t.seq)
    const done = await patch(h, h.tok.tk_orch!, t.id, { state: 'completed' }, S.o1)
    expect(done.status).toBe(200)
    expect((await done.json() as Task).state).toBe('completed')
    const audit = await (await req(h.app, h.tok.tk_admin!, 'GET', '/v1/admin/audit')).json() as Array<{ event: string; detail: Record<string, unknown> }>
    const steps = audit.filter(a => a.event.startsWith('task.')).map(a => `${a.event}:${a.detail.to ?? ''}`)
    expect(steps).toEqual(['task.create:submitted', 'task.transition:working', 'task.transition:completed'])
    expect(JSON.stringify(audit)).not.toContain('R30-R33')
  })

  it('a terminal state is final: a late working update is refused and audited', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    await patch(h, h.tok.tk_orch!, t.id, { state: 'completed' }, S.o1)
    const late = await patch(h, h.tok.tk_m4!, t.id, { state: 'working' }, S.a1)
    expect(late.status).toBe(409)
    expect(await late.json()).toMatchObject({ error: 'task_terminal', state: 'completed' })
    const audit = await (await req(h.app, h.tok.tk_admin!, 'GET', '/v1/admin/audit')).json() as Array<{ event: string }>
    expect(audit.map(a => a.event)).toContain('task.transition.reject')
  })

  it('if_seq is an optimistic lock', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    await patch(h, h.tok.tk_m4!, t.id, { state: 'working' }, S.a1)
    const stale = await patch(h, h.tok.tk_m4!, t.id, { progress: 'x', if_seq: t.seq }, S.a1)
    expect(stale.status).toBe(409)
    expect(await stale.json()).toMatchObject({ error: 'task_conflict' })
  })

  it('blocked states return to working', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    for (const s of ['working', 'input_required', 'working', 'auth_required', 'working']) {
      expect((await patch(h, h.tok.tk_m4!, t.id, { state: s }, S.a1)).status).toBe(200)
    }
  })

  it('only the dispatcher cancels or rejects; nobody goes back to submitted', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    expect((await patch(h, h.tok.tk_m4!, t.id, { state: 'canceled' }, S.a1)).status).toBe(403)
    expect((await patch(h, h.tok.tk_m4!, t.id, { state: 'submitted' }, S.a1)).status).toBe(409)
    expect((await patch(h, h.tok.tk_orch!, t.id, { state: 'rejected', reason: 'no slot' }, S.o1)).status).toBe(200)
  })

  it('the assignee is the assigned session: a sibling session on the same token, or another token, cannot update it', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    await openSession(h.app, h.tok.tk_m4!, S.a2, 'sibling')
    expect((await patch(h, h.tok.tk_m4!, t.id, { state: 'working' }, S.a2)).status).toBe(403)
    expect((await patch(h, h.tok.tk_aws!, t.id, { state: 'working' })).status).toBe(403)
  })

  it('a client cannot write seq or any server field', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    expect((await patch(h, h.tok.tk_m4!, t.id, { seq: 999 }, S.a1)).status).toBe(400)
    expect((await patch(h, h.tok.tk_m4!, t.id, { depth: 0 }, S.a1)).status).toBe(400)
  })
})

describe('tasks: snapshot, events, artifacts, rebind', () => {
  it('GET since_seq returns only what changed after it', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    const w = await (await patch(h, h.tok.tk_m4!, t.id, { state: 'working' }, S.a1)).json() as Task
    const res = await (await req(h.app, h.tok.tk_orch!, 'GET', `/v1/tasks?since_seq=${t.seq}`)).json() as { tasks: Task[]; seq: number }
    expect(res.tasks.map(x => x.seq)).toEqual([w.seq])
    expect(res.seq).toBe(w.seq)
    const none = await (await req(h.app, h.tok.tk_orch!, 'GET', `/v1/tasks?since_seq=${w.seq}`)).json() as { tasks: Task[] }
    expect(none.tasks).toEqual([])
  })

  it('pushes event: task to streams that may see the workgroup, never as event: message', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'w')
    const own = await openSession(h.app, h.tok.tk_aws!, S.a2, 'watcher')
    const mate = await openSession(h.app, h.tok.tk_mate!, S.b1, 'mate')
    await create(h, h.tok.tk_orch!, { title: 'x', assignee: S.a1 }, S.o1)
    const [seen, hidden] = await Promise.all([readSse(own.body!, 1, ['task', 'message']), readSse(mate.body!, 1, ['task', 'message'])])
    expect(seen.map(e => e.event)).toEqual(['task'])
    expect(JSON.parse(seen[0]!.data)).toMatchObject({ type: 'task', task: { title: 'x', state: 'submitted' } })
    expect(hidden).toEqual([])
  })

  it('records artifacts and rejects unsafe refs', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    const ok = await req(h.app, h.tok.tk_m4!, 'POST', `/v1/tasks/${t.id}/artifacts`, { type: 'pr', ref: 'https://github.com/o/r/pull/71' }, { 'x-mesh-session': S.a1 })
    expect(ok.status).toBe(200)
    expect((await ok.json() as { artifacts: unknown[] }).artifacts).toHaveLength(1)
    const bad = await req(h.app, h.tok.tk_m4!, 'POST', `/v1/tasks/${t.id}/artifacts`, { type: 'url', ref: 'https://u:p@x.com' }, { 'x-mesh-session': S.a1 })
    expect(bad.status).toBe(400)
    expect((await req(h.app, h.tok.tk_mate!, 'POST', `/v1/tasks/${t.id}/artifacts`, { type: 'pr', ref: 'https://github.com/o/r/pull/1' })).status).toBe(404)
  })

  it('rebinds a task to a new session of the same token after a restart, and only that token', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    await openSession(h.app, h.tok.tk_m4!, S.a2, 'fr-inkrec')
    const rb = await req(h.app, h.tok.tk_m4!, 'POST', `/v1/tasks/${t.id}/rebind`, {}, { 'x-mesh-session': S.a2 })
    expect(rb.status).toBe(200)
    expect((await rb.json() as Task).assignee).toMatchObject({ session: S.a2 })
    await openSession(h.app, h.tok.tk_aws!, S.b2, 'thief')
    expect((await req(h.app, h.tok.tk_aws!, 'POST', `/v1/tasks/${t.id}/rebind`, {}, { 'x-mesh-session': S.b2 })).status).toBe(403)
  })

  it('marks a non-terminal task stale after 15 quiet minutes (derived, not a state)', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    h.clock.now += 16 * 60_000
    const got = await (await req(h.app, h.tok.tk_orch!, 'GET', `/v1/tasks/${t.id}`)).json() as Task
    expect(got).toMatchObject({ state: 'submitted', stale: true })
    expect(got.age_s).toBeGreaterThanOrEqual(960)
  })
})
