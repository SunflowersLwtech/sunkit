import { describe, it, expect } from 'vitest'
import { harness, openSession, req, S } from './ledger-helpers.ts'
import { MessageStore } from '../../src/messages/store.ts'
import { Fanout } from '../../src/fanout.ts'
import { PresenceRegistry } from '../../src/presence/registry.ts'
import { SessionRegistry } from '../../src/sessions/registry.ts'
import { buildApp } from '../../src/app.ts'

const LIUWEI = { role: 'worker' as const, workgroup: 'liuwei', visible: ['team'] }
const ORCH = { role: 'orchestrator' as const, workgroup: 'liuwei', visible: ['team'] }
const specs = [
  { id: 'tk_m4', handle: 'duocode', label: 'm4', grant: LIUWEI },
  { id: 'tk_aws', handle: 'weiliu', label: 'aws-sin', grant: LIUWEI },
  { id: 'tk_orch', handle: 'weiliu', label: 'orch-feishu', grant: ORCH },
  { id: 'tk_mate', handle: 'jovie', label: 'jovie-laptop' },
  { id: 'tk_admin', handle: 'weiliu', label: 'bootstrap-admin', tier: 'admin' as const },
]

type H = ReturnType<typeof harness>
type Lease = { id: string; name: string; holder: { name: string } | null; ttl_remaining_s: number; expires_at: string }
const acquire = (h: H, tok: string, session: string, body: Record<string, unknown>) =>
  req(h.app, tok, 'POST', '/v1/leases', body, { 'x-mesh-session': session })

async function twoSessions(h: H) {
  await openSession(h.app, h.tok.tk_m4!, S.a1, 'fr-inkrec')
  await openSession(h.app, h.tok.tk_aws!, S.a2, 'fr-deploy')
}

async function ownTask(h: H, tok: string, session: string): Promise<string> {
  const t = await (await req(h.app, tok, 'POST', '/v1/tasks', { title: 'deploy' }, { 'x-mesh-session': session })).json() as { id: string }
  return t.id
}

describe('leases', () => {
  it('two sessions race for one name: exactly one wins, the other learns who holds it and for how long', async () => {
    const h = harness(specs)
    await twoSessions(h)
    const [r1, r2] = await Promise.all([
      acquire(h, h.tok.tk_m4!, S.a1, { name: 'repo/foldrender', ttl_s: 1200, note: 'merge #71' }),
      acquire(h, h.tok.tk_aws!, S.a2, { name: 'repo/foldrender', ttl_s: 1200 }),
    ])
    const codes = [r1.status, r2.status].sort()
    expect(codes, `expected 409, got ${codes.join(',')}`).toEqual([201, 409])
    const loser = (r1.status === 409 ? r1 : r2)
    const body = await loser.json() as { error: string; lease: Lease; message: string }
    expect(body.error).toBe('lease_held')
    expect(body.lease.holder?.name).toMatch(/^fr-/)
    expect(body.lease.ttl_remaining_s).toBe(1200)
    expect(body.message).toMatch(/fr-(inkrec|deploy) .* 20 min/)
  })

  it('a teammate is told the name is held but not by whom when the holder is private', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'private-holder')
    await openSession(h.app, h.tok.tk_mate!, S.b1, 'mate')
    await acquire(h, h.tok.tk_m4!, S.a1, { name: 'repo/sunkit', ttl_s: 600 })
    const res = await acquire(h, h.tok.tk_mate!, S.b1, { name: 'repo/sunkit', ttl_s: 600 })
    expect(res.status).toBe(409)
    const body = await res.json() as { lease: Lease }
    expect(body.lease.holder).toBeNull()
    expect(JSON.stringify(body)).not.toContain('private-holder')
    const list = await (await req(h.app, h.tok.tk_mate!, 'GET', '/v1/leases')).json() as Lease[]
    expect(list).toHaveLength(1)
    expect(list[0]!.holder).toBeNull()
  })

  it('deploy/ and cred/ leases need an active task of the holder', async () => {
    const h = harness(specs)
    await twoSessions(h)
    const none = await acquire(h, h.tok.tk_m4!, S.a1, { name: 'deploy/foldrender', ttl_s: 600 })
    expect(none.status).toBe(403)
    expect(await none.json()).toMatchObject({ error: 'lease_needs_task' })
    const other = await ownTask(h, h.tok.tk_aws!, S.a2)
    expect((await acquire(h, h.tok.tk_m4!, S.a1, { name: 'deploy/foldrender', ttl_s: 600, task_id: other })).status).toBe(403)
    const mine = await ownTask(h, h.tok.tk_m4!, S.a1)
    expect((await acquire(h, h.tok.tk_m4!, S.a1, { name: 'cred/infra-creds', ttl_s: 600, task_id: mine })).status).toBe(201)
    await req(h.app, h.tok.tk_m4!, 'PATCH', `/v1/tasks/${mine}`, { state: 'completed' }, { 'x-mesh-session': S.a1 })
    expect((await acquire(h, h.tok.tk_m4!, S.a1, { name: 'deploy/foldrender', ttl_s: 600, task_id: mine })).status).toBe(403)
  })

  it('an expired lease can be taken over, and the takeover is audited as an expiry', async () => {
    const h = harness(specs)
    await twoSessions(h)
    expect((await acquire(h, h.tok.tk_m4!, S.a1, { name: 'build/m4', ttl_s: 60 })).status).toBe(201)
    h.clock.now += 59_000
    expect((await acquire(h, h.tok.tk_aws!, S.a2, { name: 'build/m4', ttl_s: 60 })).status).toBe(409)
    h.clock.now += 2_000
    expect((await acquire(h, h.tok.tk_aws!, S.a2, { name: 'build/m4', ttl_s: 60 })).status).toBe(201)
    const audit = await (await req(h.app, h.tok.tk_admin!, 'GET', '/v1/admin/audit')).json() as Array<{ event: string }>
    expect(audit.map(a => a.event).filter(e => e.startsWith('lease.'))).toEqual(['lease.acquire', 'lease.expire', 'lease.acquire'])
  })

  it('renew extends the holder\'s lease; nobody else can renew it; an expired one cannot be renewed', async () => {
    const h = harness(specs)
    await twoSessions(h)
    const l = await (await acquire(h, h.tok.tk_m4!, S.a1, { name: 'repo/x', ttl_s: 300 })).json() as Lease
    h.clock.now += 200_000
    const rn = await req(h.app, h.tok.tk_m4!, 'POST', `/v1/leases/${l.id}/renew`, { ttl_s: 300 }, { 'x-mesh-session': S.a1 })
    expect(rn.status).toBe(200)
    expect((await rn.json() as Lease).ttl_remaining_s).toBe(300)
    expect((await req(h.app, h.tok.tk_aws!, 'POST', `/v1/leases/${l.id}/renew`, {}, { 'x-mesh-session': S.a2 })).status).toBe(403)
    h.clock.now += 301_000
    expect((await req(h.app, h.tok.tk_m4!, 'POST', `/v1/leases/${l.id}/renew`, {}, { 'x-mesh-session': S.a1 })).status).toBe(409)
  })

  it('caps renewals at two hours per session', async () => {
    const h = harness(specs)
    await twoSessions(h)
    const l = await (await acquire(h, h.tok.tk_m4!, S.a1, { name: 'repo/x', ttl_s: 1800 })).json() as Lease
    const codes: number[] = []
    for (let i = 0; i < 5; i++) {
      h.clock.now += 1_000_000
      codes.push((await req(h.app, h.tok.tk_m4!, 'POST', `/v1/leases/${l.id}/renew`, { ttl_s: 1800 }, { 'x-mesh-session': S.a1 })).status)
    }
    expect(codes).toEqual([200, 200, 200, 200, 429])
  })

  it('holds at most three per session and ttl at most 1800 s', async () => {
    const h = harness(specs)
    await twoSessions(h)
    for (const n of ['repo/a', 'repo/b', 'repo/c']) expect((await acquire(h, h.tok.tk_m4!, S.a1, { name: n, ttl_s: 60 })).status).toBe(201)
    const fourth = await acquire(h, h.tok.tk_m4!, S.a1, { name: 'repo/d', ttl_s: 60 })
    expect(fourth.status).toBe(429)
    expect(await fourth.json()).toMatchObject({ error: 'lease_quota' })
    expect((await acquire(h, h.tok.tk_aws!, S.a2, { name: 'repo/e', ttl_s: 1801 })).status).toBe(400)
  })

  it('release frees the name; a stranger cannot release; an orchestrator can force it, audited', async () => {
    const h = harness(specs)
    await twoSessions(h)
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    const l = await (await acquire(h, h.tok.tk_m4!, S.a1, { name: 'device/fold7', ttl_s: 600 })).json() as Lease
    expect((await req(h.app, h.tok.tk_aws!, 'DELETE', `/v1/leases/${l.id}`, undefined, { 'x-mesh-session': S.a2 })).status).toBe(403)
    expect((await req(h.app, h.tok.tk_orch!, 'DELETE', `/v1/leases/${l.id}`, undefined, { 'x-mesh-session': S.o1 })).status).toBe(200)
    expect((await acquire(h, h.tok.tk_aws!, S.a2, { name: 'device/fold7', ttl_s: 600 })).status).toBe(201)
    const audit = await (await req(h.app, h.tok.tk_admin!, 'GET', '/v1/admin/audit')).json() as Array<{ event: string }>
    expect(audit.map(a => a.event)).toContain('lease.force_release')
  })

  it('a lease needs a session of the calling token', async () => {
    const h = harness(specs)
    await twoSessions(h)
    expect((await req(h.app, h.tok.tk_m4!, 'POST', '/v1/leases', { name: 'repo/x', ttl_s: 60 })).status).toBe(400)
    expect((await acquire(h, h.tok.tk_m4!, S.a2, { name: 'repo/x', ttl_s: 60 })).status).toBe(403)
  })

  it('survives a relay restart: the lease is still held afterwards', async () => {
    const h = harness(specs)
    await twoSessions(h)
    await acquire(h, h.tok.tk_m4!, S.a1, { name: 'deploy-free/x'.replace('deploy-free', 'repo'), ttl_s: 600 })
    const sessions = new SessionRegistry(() => h.clock.now)
    const app2 = buildApp({ db: h.db, store: new MessageStore(h.db), fanout: new Fanout(), presence: new PresenceRegistry(), sessions, now: () => new Date(h.clock.now) })
    await openSession(app2, h.tok.tk_aws!, S.a2, 'after-restart')
    const res = await req(app2, h.tok.tk_aws!, 'POST', '/v1/leases', { name: 'repo/x', ttl_s: 60 }, { 'x-mesh-session': S.a2 })
    expect(res.status).toBe(409)
  })
})
