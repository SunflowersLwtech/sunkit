import { describe, it, expect } from 'vitest'
import { harness, openSession, readSse, req, S } from './ledger-helpers.ts'

const LIUWEI = { role: 'worker' as const, workgroup: 'liuwei', visible: ['team'] }
const specs = [
  { id: 'tk_meshd_m4', handle: 'duocode', label: 'meshd-m4', grant: { role: 'executor' as const, workgroup: 'liuwei', machine: 'm4' } },
  { id: 'tk_meshd_aws', handle: 'weiliu', label: 'meshd-aws', grant: { role: 'executor' as const, workgroup: 'liuwei', machine: 'aws-sin' } },
  { id: 'tk_orch', handle: 'weiliu', label: 'orch-feishu', grant: { role: 'orchestrator' as const, workgroup: 'liuwei', visible: ['team'] } },
  { id: 'tk_m4', handle: 'duocode', label: 'm4', grant: LIUWEI },
  { id: 'tk_mate', handle: 'jovie', label: 'jovie-laptop' },
  { id: 'tk_admin', handle: 'weiliu', label: 'bootstrap-admin', tier: 'admin' as const },
]

const report = {
  version: '0.1.0',
  herdr: { ok: true, version: '0.9.5' },
  load: { load1: 1.2, cpus: 8 },
  kinds: [{ kind: 'claude', version: '2.1.300' }],
  seats: [{ email: 'duocodetechu@gmail.com', plan: 'team', five_hour_pct: 40, resets_at: '2026-10-20T05:00:00Z' }],
  active: 1, blocked: 0, max_active: 8,
  agents: [{ name: 'fr-inkrec', agent: 'claude', status: 'idle', pane: 'wC:p54', tab: 'wC:t4Y', workspace: 'wC', cwd: '/Users/sunfl/Developer/products/foldrender' }],
  roots: [{ path: '~/Developer/products', exists: true }],
}

type H = ReturnType<typeof harness>
type Machine = { machine: string; stale: boolean; connected: boolean; age_s: number; report: typeof report }
const machines = async (h: H, tok: string) => (await (await req(h.app, tok, 'GET', '/v1/machines')).json()) as Machine[]

describe('machine reports', () => {
  it('an executor reports for the machine bound to its token; the owner sees it, a teammate does not', async () => {
    const h = harness(specs)
    expect((await req(h.app, h.tok.tk_meshd_m4!, 'POST', '/v1/machines/self', report)).status).toBe(200)
    h.clock.now += 5_000
    const own = await machines(h, h.tok.tk_m4!)
    expect(own).toHaveLength(1)
    expect(own[0]).toMatchObject({ machine: 'm4', stale: false, connected: false, age_s: 5 })
    expect(own[0]!.report.agents[0]).toMatchObject({ name: 'fr-inkrec', status: 'idle' })
    expect(await machines(h, h.tok.tk_mate!)).toEqual([])
  })

  it('only executors report, and only in the fixed shape', async () => {
    const h = harness(specs)
    expect((await req(h.app, h.tok.tk_m4!, 'POST', '/v1/machines/self', report)).status).toBe(403)
    expect((await req(h.app, h.tok.tk_orch!, 'POST', '/v1/machines/self', report)).status).toBe(403)
    expect((await req(h.app, h.tok.tk_meshd_m4!, 'POST', '/v1/machines/self', { ...report, machine: 'aws-sin' })).status).toBe(400)
    expect((await req(h.app, h.tok.tk_meshd_m4!, 'POST', '/v1/machines/self', { ...report, env: { K: 'v' } })).status).toBe(400)
  })

  it('a machine that stops reporting turns stale and its sessions disappear instead of showing idle', async () => {
    const h = harness(specs)
    await req(h.app, h.tok.tk_meshd_m4!, 'POST', '/v1/machines/self', report)
    h.clock.now += 91_000
    const m = (await machines(h, h.tok.tk_m4!))[0]!
    expect(m.stale).toBe(true)
    expect(m.report.agents).toEqual([])
    expect(JSON.stringify(m)).not.toContain('"idle"')
    h.clock.now += 10 * 60_000
    expect(await machines(h, h.tok.tk_m4!)).toEqual([])
  })

  it('an executor stream marks the machine connected', async () => {
    const h = harness(specs)
    await req(h.app, h.tok.tk_meshd_m4!, 'POST', '/v1/machines/self', report)
    const s = await req(h.app, h.tok.tk_meshd_m4!, 'GET', '/v1/machines/self/stream')
    expect(s.status).toBe(200)
    expect((await machines(h, h.tok.tk_m4!))[0]!.connected).toBe(true)
    await s.body!.cancel()
    expect((await req(h.app, h.tok.tk_m4!, 'GET', '/v1/machines/self/stream')).status).toBe(403)
  })
})

describe('read-only commands', () => {
  async function connected(h: H) {
    await req(h.app, h.tok.tk_meshd_m4!, 'POST', '/v1/machines/self', report)
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    return await req(h.app, h.tok.tk_meshd_m4!, 'GET', '/v1/machines/self/stream')
  }
  const issue = (h: H, tok: string, body: unknown, machine = 'm4') =>
    req(h.app, tok, 'POST', `/v1/machines/${machine}/commands`, body, { 'x-mesh-session': S.o1 })

  it('an orchestrator asks m4 to read a pane; only m4\'s executor gets it and only the orchestrator gets the answer', async () => {
    const h = harness(specs)
    const stream = await connected(h)
    const res = await issue(h, h.tok.tk_orch!, { op: 'read', args: { pane: 'wC:p54', lines: 40 } })
    expect(res.status).toBe(202)
    const cmd = await res.json() as { id: string; state: string }
    const got = await readSse(stream.body!, 1, ['command'])
    expect(JSON.parse(got[0]!.data)).toMatchObject({ id: cmd.id, op: 'read', args: { pane: 'wC:p54', lines: 40 } })

    expect((await req(h.app, h.tok.tk_meshd_aws!, 'POST', `/v1/commands/${cmd.id}/result`, { ok: true, output: 'forged' })).status).toBe(403)
    expect((await req(h.app, h.tok.tk_meshd_m4!, 'POST', `/v1/commands/${cmd.id}/result`, { ok: true, output: 'screen text' })).status).toBe(200)
    expect((await req(h.app, h.tok.tk_meshd_m4!, 'POST', `/v1/commands/${cmd.id}/result`, { ok: true, output: 'again' })).status).toBe(409)

    const done = await (await req(h.app, h.tok.tk_orch!, 'GET', `/v1/commands/${cmd.id}`)).json() as Record<string, unknown>
    expect(done).toMatchObject({ state: 'done', result: { ok: true, output: 'screen text' } })
    expect((await req(h.app, h.tok.tk_m4!, 'GET', `/v1/commands/${cmd.id}`)).status).toBe(404)
    const audit = JSON.stringify(await (await req(h.app, h.tok.tk_admin!, 'GET', '/v1/admin/audit')).json())
    expect(audit).toContain('dispatch.issue')
    expect(audit).toContain('dispatch.ack')
    expect(audit).not.toContain('screen text')
  })

  it('a worker cannot issue commands; spawn is not a P1 op', async () => {
    const h = harness(specs)
    await connected(h)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'w')
    const w = await req(h.app, h.tok.tk_m4!, 'POST', '/v1/machines/m4/commands', { op: 'probe' }, { 'x-mesh-session': S.a1 })
    expect(w.status).toBe(403)
    expect(await w.json()).toMatchObject({ error: 'not_a_dispatcher' })
    expect((await issue(h, h.tok.tk_orch!, { op: 'spawn', args: { prompt: 'x' } })).status).toBe(400)
  })

  it('a command queued while the executor is away is delivered when it connects', async () => {
    const h = harness(specs)
    await req(h.app, h.tok.tk_meshd_m4!, 'POST', '/v1/machines/self', report)
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    const cmd = await (await issue(h, h.tok.tk_orch!, { op: 'probe' })).json() as { id: string }
    const stream = await req(h.app, h.tok.tk_meshd_m4!, 'GET', '/v1/machines/self/stream')
    const got = await readSse(stream.body!, 1, ['command'])
    expect(JSON.parse(got[0]!.data).id).toBe(cmd.id)
  })

  it('a command nobody answers within 60 s fails as no_ack and is never retried silently', async () => {
    const h = harness(specs)
    await req(h.app, h.tok.tk_meshd_m4!, 'POST', '/v1/machines/self', report)
    await openSession(h.app, h.tok.tk_orch!, S.o1, 'feishu-assistant')
    const cmd = await (await issue(h, h.tok.tk_orch!, { op: 'probe' })).json() as { id: string }
    h.clock.now += 61_000
    const got = await (await req(h.app, h.tok.tk_orch!, 'GET', `/v1/commands/${cmd.id}`)).json() as Record<string, unknown>
    expect(got).toMatchObject({ state: 'failed', reason: 'no_ack' })
    const stream = await req(h.app, h.tok.tk_meshd_m4!, 'GET', '/v1/machines/self/stream')
    expect(await readSse(stream.body!, 1, ['command'], 300)).toEqual([])
    const audit = JSON.stringify(await (await req(h.app, h.tok.tk_admin!, 'GET', '/v1/admin/audit')).json())
    expect(audit).toContain('dispatch.fail')
  })

  it('unknown or invisible machines are 404', async () => {
    const h = harness(specs)
    await connected(h)
    expect((await issue(h, h.tok.tk_orch!, { op: 'probe' }, 'msi-wsl')).status).toBe(404)
  })

  it('wait= long-polls until the result lands', async () => {
    const h = harness(specs)
    await connected(h)
    const cmd = await (await issue(h, h.tok.tk_orch!, { op: 'probe' })).json() as { id: string }
    const pending = req(h.app, h.tok.tk_orch!, 'GET', `/v1/commands/${cmd.id}?wait=5`)
    await new Promise(r => setTimeout(r, 50))
    await req(h.app, h.tok.tk_meshd_m4!, 'POST', `/v1/commands/${cmd.id}/result`, { ok: true, output: 'probe ok' })
    expect(await (await pending).json()).toMatchObject({ state: 'done', result: { output: 'probe ok' } })
  })
})
