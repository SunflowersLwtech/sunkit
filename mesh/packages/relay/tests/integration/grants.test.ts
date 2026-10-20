import { describe, it, expect } from 'vitest'
import { harness, req } from './ledger-helpers.ts'
import { readGrant } from '../../src/grants.ts'

describe('token grants (role + workgroup are bound to the token, set only by an admin)', () => {
  const specs = [
    { id: 'tk_admin', handle: 'weiliu', label: 'bootstrap-admin', tier: 'admin' as const },
    { id: 'tk_mac', handle: 'weiliu', label: 'm4' },
    { id: 'tk_mate', handle: 'jovie', label: 'aws-sin' },
  ]

  it('an ungranted token is a worker in the default team workgroup and sees only it', () => {
    const h = harness(specs)
    expect(readGrant(h.db, 'tk_mate')).toMatchObject({ role: 'worker', workgroup: 'team', visible: ['team'], machine: null })
  })

  it('admin sets a grant; the token list shows it and the audit log records it', async () => {
    const h = harness(specs)
    const res = await req(h.app, h.tok.tk_admin!, 'PUT', '/v1/admin/tokens/tk_mac/grant',
      { role: 'orchestrator', workgroup: 'liuwei', visible: ['team'] })
    expect(res.status).toBe(200)
    expect(readGrant(h.db, 'tk_mac')).toMatchObject({ role: 'orchestrator', workgroup: 'liuwei', visible: ['liuwei', 'team'] })
    const list = await (await req(h.app, h.tok.tk_admin!, 'GET', '/v1/admin/tokens')).json() as Array<Record<string, unknown>>
    expect(list.find(t => t.id === 'tk_mac')).toMatchObject({ role: 'orchestrator', workgroup: 'liuwei', visible: ['liuwei', 'team'] })
    const audit = await (await req(h.app, h.tok.tk_admin!, 'GET', '/v1/admin/audit')).json() as Array<{ event: string; detail: Record<string, unknown> }>
    expect(audit.find(a => a.event === 'token.grant')?.detail).toMatchObject({ token_id: 'tk_mac', role: 'orchestrator', workgroup: 'liuwei' })
  })

  it('a device token cannot grant itself anything', async () => {
    const h = harness(specs)
    const res = await req(h.app, h.tok.tk_mate!, 'PUT', '/v1/admin/tokens/tk_mate/grant', { role: 'orchestrator', workgroup: 'liuwei' })
    expect(res.status).toBe(401)
    expect(readGrant(h.db, 'tk_mate').role).toBe('worker')
  })

  it('an executor grant must name its machine, and only executors carry one', async () => {
    const h = harness(specs)
    expect((await req(h.app, h.tok.tk_admin!, 'PUT', '/v1/admin/tokens/tk_mac/grant', { role: 'executor', workgroup: 'liuwei' })).status).toBe(400)
    expect((await req(h.app, h.tok.tk_admin!, 'PUT', '/v1/admin/tokens/tk_mac/grant', { role: 'worker', workgroup: 'liuwei', machine: 'm4' })).status).toBe(400)
    expect((await req(h.app, h.tok.tk_admin!, 'PUT', '/v1/admin/tokens/tk_mac/grant', { role: 'executor', workgroup: 'liuwei', machine: 'm4' })).status).toBe(200)
  })

  it('404s for a token of another team or that does not exist', async () => {
    const h = harness(specs)
    expect((await req(h.app, h.tok.tk_admin!, 'PUT', '/v1/admin/tokens/tk_nope/grant', { role: 'worker', workgroup: 'team' })).status).toBe(404)
  })

  it('a newly paired device inherits the workgroups of its owner but never a privileged role', async () => {
    const h = harness(specs)
    await req(h.app, h.tok.tk_admin!, 'PUT', '/v1/admin/tokens/tk_mac/grant', { role: 'orchestrator', workgroup: 'liuwei', visible: ['team'] })
    const code = (await (await req(h.app, h.tok.tk_admin!, 'POST', '/v1/admin/users/weiliu/devices', {})).json() as { pair_code: string }).pair_code
    const paired = await h.app.request('/v1/auth/pair', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pair_code: code, device_label: 'new-mac' }),
    })
    expect(paired.status).toBe(200)
    const row = h.db.prepare("SELECT id FROM token WHERE label='new-mac'").get() as { id: string }
    expect(readGrant(h.db, row.id)).toMatchObject({ role: 'worker', workgroup: 'liuwei', visible: ['liuwei', 'team'], machine: null })
  })

  it('a teammate paired without any granted sibling stays in the default team workgroup', async () => {
    const h = harness(specs)
    const code = (await (await req(h.app, h.tok.tk_admin!, 'POST', '/v1/admin/users/jovie/devices', {})).json() as { pair_code: string }).pair_code
    await h.app.request('/v1/auth/pair', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pair_code: code, device_label: 'jovie-laptop' }),
    })
    const row = h.db.prepare("SELECT id FROM token WHERE label='jovie-laptop'").get() as { id: string }
    expect(readGrant(h.db, row.id)).toMatchObject({ role: 'worker', workgroup: 'team', visible: ['team'] })
  })
})
