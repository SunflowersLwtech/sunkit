import { describe, it, expect } from 'vitest'
import { harness, openSession, req, S } from './ledger-helpers.ts'

const LIUWEI = { role: 'worker' as const, workgroup: 'liuwei', visible: ['team'] }
const specs = [
  { id: 'tk_m4', handle: 'duocode', label: 'm4', grant: LIUWEI },
  { id: 'tk_aws', handle: 'weiliu', label: 'aws-sin', grant: LIUWEI },
  { id: 'tk_mate', handle: 'jovie', label: 'jovie-laptop' },
]

type Row = Record<string, unknown>
const list = async (h: ReturnType<typeof harness>, tok: string) =>
  (await (await req(h.app, tok, 'GET', '/v1/sessions')).json()) as Row[]

describe('session cards (POST /v1/sessions/self)', () => {
  it('stores the five card fields and shows them with server-owned fields', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'fr-inkrec')
    const res = await req(h.app, h.tok.tk_m4!, 'POST', '/v1/sessions/self', {
      session: S.a1, agent: 'claude', model: 'claude-opus-5-5', repo: 'foldrender', branch: 'feat/ink',
      herdr: { machine: 'm4', tab: 'wC:t4Y', pane: 'wC:p54' }, source: 'hook',
    })
    expect(res.status).toBe(200)
    h.clock.now += 7_000
    const row = (await list(h, h.tok.tk_m4!)).find(r => r.session_id === S.a1)!
    expect(row).toMatchObject({
      name: 'fr-inkrec', agent: 'claude', model: 'claude-opus-5-5', repo: 'foldrender', branch: 'feat/ink',
      herdr: { machine: 'm4', tab: 'wC:t4Y', pane: 'wC:p54' }, source: 'hook',
      workgroup: 'liuwei', role: 'worker', age_s: 7,
    })
  })

  it('rejects role and dispatched_by outright, and a workgroup the token was not granted', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_mate!, S.b1, 'mate')
    const base = { session: S.b1 }
    expect((await req(h.app, h.tok.tk_mate!, 'POST', '/v1/sessions/self', { ...base, role: 'orchestrator' })).status).toBe(400)
    expect((await req(h.app, h.tok.tk_mate!, 'POST', '/v1/sessions/self', { ...base, dispatched_by: 'feishu-assistant' })).status).toBe(400)
    const forged = await req(h.app, h.tok.tk_mate!, 'POST', '/v1/sessions/self', { ...base, workgroup: 'liuwei' })
    expect(forged.status).toBe(403)
    expect(await forged.json()).toMatchObject({ error: 'workgroup_not_granted' })
    const row = (await list(h, h.tok.tk_mate!)).find(r => r.session_id === S.b1)!
    expect(row).toMatchObject({ workgroup: 'team', role: 'worker' })
  })

  it('lets a session move into another workgroup its token was granted', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'team-work')
    expect((await req(h.app, h.tok.tk_m4!, 'POST', '/v1/sessions/self', { session: S.a1, workgroup: 'team' })).status).toBe(200)
    expect((await list(h, h.tok.tk_mate!)).map(r => r.session_id)).toContain(S.a1)
  })

  it('on reconnect a session follows its token\'s current grant, unless it moved itself to a workgroup still granted', async () => {
    const h = harness([{ id: 'tk_x', handle: 'weiliu', label: 'x' }, { id: 'tk_admin', handle: 'weiliu', label: 'admin', tier: 'admin' as const }])
    const a = await openSession(h.app, h.tok.tk_x!, S.a1, 'stays')
    const b = await openSession(h.app, h.tok.tk_x!, S.a2, 'moves')
    await req(h.app, h.tok.tk_admin!, 'PUT', '/v1/admin/tokens/tk_x/grant', { role: 'worker', workgroup: 'liuwei', visible: ['team'] })
    expect((await req(h.app, h.tok.tk_x!, 'POST', '/v1/sessions/self', { session: S.a2, workgroup: 'team' })).status).toBe(200)
    await a.body!.cancel(); await b.body!.cancel()
    await openSession(h.app, h.tok.tk_x!, S.a1, 'stays')
    await openSession(h.app, h.tok.tk_x!, S.a2, 'moves')
    const rows = await list(h, h.tok.tk_x!)
    expect(rows.find(r => r.session_id === S.a1)?.workgroup).toBe('liuwei')
    expect(rows.find(r => r.session_id === S.a2)?.workgroup).toBe('team')
  })

  it('refuses a task_id that is not assigned to this token', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'x')
    const res = await req(h.app, h.tok.tk_m4!, 'POST', '/v1/sessions/self', { session: S.a1, task_id: 'task_01HRK7Y0000000000000000000' })
    expect(res.status).toBe(403)
    expect(await res.json()).toMatchObject({ error: 'task_not_assigned' })
  })

  it('strips credentials from a URL-shaped cwd', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'x')
    await req(h.app, h.tok.tk_m4!, 'POST', '/v1/sessions/self', { session: S.a1, cwd: 'https://ghp_secret@github.com/o/r?x=1' })
    const row = (await list(h, h.tok.tk_m4!)).find(r => r.session_id === S.a1)!
    expect(row.cwd).toBe('https://github.com/o/r')
  })

  it('rate-limits per (token, session): eight sessions behind one device token do not starve each other', async () => {
    const h = harness(specs)
    const ids = [S.a1, S.a2, S.b1, S.b2]
    for (const id of ids) await openSession(h.app, h.tok.tk_m4!, id, `s${id.slice(-1)}`)
    const codes: number[] = []
    for (const id of ids) for (let i = 0; i < 5; i++) {
      codes.push((await req(h.app, h.tok.tk_m4!, 'POST', '/v1/sessions/self', { session: id, status: i % 2 ? 'busy' : 'idle' })).status)
    }
    expect(codes.filter(c => c === 429)).toEqual([])
    const sixth = await req(h.app, h.tok.tk_m4!, 'POST', '/v1/sessions/self', { session: S.a1, status: 'idle' })
    expect(sixth.status).toBe(429)
  })
})

describe('workgroup visibility of sessions', () => {
  it('a teammate sees team sessions only; the owner sees both', async () => {
    const h = harness(specs)
    await openSession(h.app, h.tok.tk_m4!, S.a1, 'private-work')
    await openSession(h.app, h.tok.tk_mate!, S.b1, 'mate-work')
    expect((await list(h, h.tok.tk_mate!)).map(r => r.session_id)).toEqual([S.b1])
    expect((await list(h, h.tok.tk_aws!)).map(r => r.session_id).sort()).toEqual([S.a1, S.b1].sort())
  })
})
