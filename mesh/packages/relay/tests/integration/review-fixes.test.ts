import { describe, it, expect } from 'vitest'
import { harness, openSession, readSse, req, S } from './ledger-helpers.ts'
import { purgeInactive } from '../../src/purge.ts'

const LIUWEI = { role: 'worker' as const, workgroup: 'liuwei', visible: ['team'] }
const ORCH = { role: 'orchestrator' as const, workgroup: 'liuwei', visible: ['team'] }
const specs = [
  { id: 'tk_m4', handle: 'duocode', label: 'm4', grant: LIUWEI },
  { id: 'tk_aws', handle: 'weiliu', label: 'aws-sin', grant: LIUWEI },
  { id: 'tk_orch', handle: 'weiliu', label: 'orch-feishu', grant: ORCH },
  { id: 'tk_orch2', handle: 'weiliu', label: 'orch-backup', grant: ORCH },
  { id: 'tk_obs', handle: 'weiliu', label: 'probe', grant: { role: 'observer' as const, workgroup: 'liuwei', visible: ['team'] } },
  { id: 'tk_mate', handle: 'jovie', label: 'jovie-laptop' },
  { id: 'tk_admin', handle: 'admin', label: 'bootstrap-admin', tier: 'admin' as const },
]
type H = ReturnType<typeof harness>
const hdr = (s: string) => ({ 'x-mesh-session': s })

describe('grants never block deleting tokens', () => {
  it('purges an inactive human whose tokens have grants', () => {
    const h = harness(specs)
    h.db.prepare("UPDATE human SET last_active_at='2020-01-01T00:00:00Z' WHERE handle='duocode'").run()
    expect(purgeInactive(h.db, 't1', '2021-01-01T00:00:00Z', null, new Date().toISOString()).handles).toContain('duocode')
    expect(h.db.prepare("SELECT COUNT(*) AS n FROM token_grant WHERE token_id='tk_m4'").get()).toEqual({ n: 0 })
  })

  it('hard-deletes a granted user', async () => {
    const h = harness(specs)
    expect((await req(h.app, h.tok.tk_admin!, 'DELETE', '/v1/admin/users/duocode?hard=true')).status).toBe(200)
  })

  it('lets an older relay (no grant awareness) delete a granted token', () => {
    const h = harness(specs)
    expect(() => h.db.prepare("DELETE FROM token WHERE human_id='h_duocode'").run()).not.toThrow()
  })
})

describe('tasks under concurrency and depth', () => {
  async function dispatched(h: H) {
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'w')
    return await (await req(h.app, h.tok.tk_orch!, 'POST', '/v1/tasks', { title: 'x', assignee: S.a1 }, hdr(S.o1))).json() as { id: string }
  }

  it('a cancel racing a progress update never leaves the task reopened', async () => {
    for (let i = 0; i < 5; i++) {
      const h = harness(specs)
      const t = await dispatched(h)
      await req(h.app, h.tok.tk_m4!, 'PATCH', `/v1/tasks/${t.id}`, { state: 'working' }, hdr(S.a1))
      await Promise.all([
        req(h.app, h.tok.tk_orch!, 'PATCH', `/v1/tasks/${t.id}`, { state: 'canceled' }, hdr(S.o1)),
        req(h.app, h.tok.tk_m4!, 'PATCH', `/v1/tasks/${t.id}`, { state: 'working', progress: 'still going' }, hdr(S.a1)),
      ])
      const got = await (await req(h.app, h.tok.tk_orch!, 'GET', `/v1/tasks/${t.id}`)).json() as { state: string }
      expect(got.state).toBe('canceled')
    }
  })

  it('an orchestrator session working on a dispatched task cannot dispatch again by leaving out the parent', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    await openSession(h.app, h.tok.tk_orch2!, S.t1, 'feishu-assistant-backup')
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'w')
    const t = await req(h.app, h.tok.tk_orch!, 'POST', '/v1/tasks', { title: 'help me', assignee: S.t1 }, hdr(S.o1))
    expect(t.status).toBe(201)
    const deeper = await req(h.app, h.tok.tk_orch2!, 'POST', '/v1/tasks', { title: 'sub', assignee: S.a1 }, hdr(S.t1))
    expect(deeper.status).toBe(403)
    expect(await deeper.json()).toMatchObject({ error: 'depth_exceeded' })
  })

  it('rebind does not let a live sibling session take a task over', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    await openSession(h.app, h.tok.tk_m4!, S.a2, 'sibling')
    const res = await req(h.app, h.tok.tk_m4!, 'POST', `/v1/tasks/${t.id}/rebind`, {}, hdr(S.a2))
    expect(res.status).toBe(409)
    expect(await res.json()).toMatchObject({ error: 'assignee_live' })
  })

  it('an observer token writes nothing to the ledger', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_obs!, S.b2, 'probe')
    expect((await req(h.app, h.tok.tk_obs!, 'POST', '/v1/tasks', { title: 'x' }, hdr(S.b2))).status).toBe(403)
    expect((await req(h.app, h.tok.tk_obs!, 'POST', '/v1/leases', { name: 'repo/x', ttl_s: 60 }, hdr(S.b2))).status).toBe(403)
    expect((await req(h.app, h.tok.tk_obs!, 'GET', '/v1/tasks')).status).toBe(200)
  })

  it('shows dispatched_by only to viewers who may see the task', async () => {
    const h = harness(specs)
    const t = await dispatched(h)
    await req(h.app, h.tok.tk_m4!, 'POST', '/v1/sessions/self', { session: S.a1, task_id: t.id, workgroup: 'team' })
    const mate = await (await req(h.app, h.tok.tk_mate!, 'GET', '/v1/sessions')).json() as Array<Record<string, unknown>>
    expect(mate.find(r => r.session_id === S.a1)).not.toHaveProperty('dispatched_by')
    const own = await (await req(h.app, h.tok.tk_aws!, 'GET', '/v1/sessions')).json() as Array<Record<string, unknown>>
    expect(own.find(r => r.session_id === S.a1)).toHaveProperty('dispatched_by', 'feishu-assistant')
  })
})

describe('leases after review', () => {
  it('releasing and re-acquiring does not reset the renewal budget', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'w')
    let renewed = 0
    for (let round = 0; round < 3; round++) {
      const l = await (await req(h.app, h.tok.tk_m4!, 'POST', '/v1/leases', { name: 'repo/x', ttl_s: 1800 }, hdr(S.a1))).json() as { id: string }
      for (let i = 0; i < 3; i++) {
        if ((await req(h.app, h.tok.tk_m4!, 'POST', `/v1/leases/${l.id}/renew`, { ttl_s: 1800 }, hdr(S.a1))).status === 200) renewed += 1800
      }
      await req(h.app, h.tok.tk_m4!, 'DELETE', `/v1/leases/${l.id}`, undefined, hdr(S.a1))
    }
    expect(renewed).toBe(7200)
  })

  it('a teammate\'s lease list leaves out leases held in workgroups it cannot see', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'w')
    await req(h.app, h.tok.tk_m4!, 'POST', '/v1/leases', { name: 'repo/secret-product', ttl_s: 600 }, hdr(S.a1))
    expect(await (await req(h.app, h.tok.tk_mate!, 'GET', '/v1/leases')).json()).toEqual([])
  })

  it('a task_id on any lease must be the holder\'s own live task', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'w')
    await openSession(h.app, h.tok.tk_aws!, S.a2, 'other')
    const other = await (await req(h.app, h.tok.tk_aws!, 'POST', '/v1/tasks', { title: 'theirs' }, hdr(S.a2))).json() as { id: string }
    const res = await req(h.app, h.tok.tk_m4!, 'POST', '/v1/leases', { name: 'repo/x', ttl_s: 60, task_id: other.id }, hdr(S.a1))
    expect(res.status).toBe(403)
    expect(await res.json()).toMatchObject({ error: 'task_not_assigned' })
  })
})

describe('streams follow grant changes', () => {
  it('a stream stops receiving a workgroup shortly after the token loses it', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'private')
    const watcher = await openSession(h.app, h.tok.tk_aws!, S.a2, 'watcher')
    await req(h.app, h.tok.tk_admin!, 'PUT', '/v1/admin/tokens/tk_aws/grant', { role: 'worker', workgroup: 'team' })
    h.clock.now += 6_000
    await req(h.app, h.tok.tk_m4!, 'POST', '/v1/messages', { to: '@team', kind: 'chat', content: 'private news' }, hdr(S.a1))
    expect(await readSse(watcher.body!, 1)).toEqual([])
  })
})

describe('review round 2', () => {
  it('a grant change applies to live sessions right away, not only after they reconnect', async () => {
    const h = harness([
      { id: 'tk_owner', handle: 'weiliu', label: 'm4' },
      { id: 'tk_mate', handle: 'jovie', label: 'jovie-laptop' },
      { id: 'tk_admin', handle: 'admin', label: 'bootstrap-admin', tier: 'admin' as const },
    ])
    await openSession(h.app, h.tok.tk_owner!, S.a1, 'private-work')
    await openSession(h.app, h.tok.tk_owner!, S.a2, 'moved-to-team')
    expect((await (await req(h.app, h.tok.tk_mate!, 'GET', '/v1/sessions')).json() as unknown[]).length).toBe(2)
    await req(h.app, h.tok.tk_admin!, 'PUT', '/v1/admin/tokens/tk_owner/grant', { role: 'worker', workgroup: 'liuwei', visible: ['team'] })
    await req(h.app, h.tok.tk_owner!, 'POST', '/v1/sessions/self', { session: S.a2, workgroup: 'team' })
    const mate = await (await req(h.app, h.tok.tk_mate!, 'GET', '/v1/sessions')).json() as Array<{ session_id: string }>
    expect(mate.map(r => r.session_id)).toEqual([S.a2])
    expect((await req(h.app, h.tok.tk_mate!, 'POST', '/v1/messages', { to: 'weiliu', to_session: S.a1, kind: 'chat', content: 'x' })).status).toBe(403)
  })

  it('depth is per session: one session holding a dispatched task does not stop its sibling dispatching', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    await openSession(h.app, h.tok.tk_orch!, S.t1, 'orch-sibling')
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'w')
    expect((await req(h.app, h.tok.tk_orch!, 'POST', '/v1/tasks', { title: 'to sibling', assignee: S.t1 }, hdr(S.o1))).status).toBe(201)
    expect((await req(h.app, h.tok.tk_orch!, 'POST', '/v1/tasks', { title: 'unrelated', assignee: S.a1 }, hdr(S.o1))).status).toBe(201)
    const deeper = await req(h.app, h.tok.tk_orch!, 'POST', '/v1/tasks', { title: 'sub', assignee: S.a1 }, hdr(S.t1))
    expect(deeper.status).toBe(403)
  })

  it('observers cannot rebind, and nobody can hand a task to an observer\'s session', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    await openSession(h.app, h.tok.tk_obs!, S.b2, 'probe')
    const toObs = await req(h.app, h.tok.tk_orch!, 'POST', '/v1/tasks', { title: 'x', assignee: S.b2 }, hdr(S.o1))
    expect(toObs.status).toBe(403)
    expect(await toObs.json()).toMatchObject({ error: 'assignee_read_only' })
    const t = await (await req(h.app, h.tok.tk_orch!, 'POST', '/v1/tasks', { title: 'mine' }, hdr(S.o1))).json() as { id: string }
    expect((await req(h.app, h.tok.tk_obs!, 'POST', `/v1/tasks/${t.id}/rebind`, {}, hdr(S.b2))).status).toBe(403)
  })
})
