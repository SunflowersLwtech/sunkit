import { describe, it, expect, vi } from 'vitest'
import { RelayClient } from './outbound.ts'

describe('RelayClient', () => {
  it('sends POST /v1/messages with bearer and idempotency key', async () => {
    const calls: { url: string; init: RequestInit }[] = []
    const fakeFetch = vi.fn(async (url: string | URL, init: RequestInit) => {
      calls.push({ url: String(url), init })
      return new Response(JSON.stringify({
        id: 'msg_01HRK7Y000000000000000000A',
        v: 1, team: 't1', from: 'alice', to: 'bob',
        in_reply_to: null, thread_root: null, kind: 'chat', content: 'hi', meta: {},
        sent_at: '2026-01-01T00:00:00.000Z', delivered_at: null,
      }), { status: 201, headers: { 'content-type': 'application/json' } })
    })
    const c = new RelayClient({ relayUrl: 'https://x', token: 'tok' }, { fetch: fakeFetch as any })
    const r = await c.send({ to: 'bob', kind: 'chat', content: 'hi' })
    expect(r.id).toBe('msg_01HRK7Y000000000000000000A')
    expect(calls[0]!.url).toBe('https://x/v1/messages')
    const headers = calls[0]!.init.headers as Record<string, string>
    expect(headers.authorization).toBe('Bearer tok')
    expect(headers['idempotency-key']).toMatch(/^[a-z0-9-]+$/)
  })

  it('throws on non-201 with body', async () => {
    const fakeFetch = vi.fn(async () =>
      new Response(JSON.stringify({ error: 'invalid_body' }), { status: 400 }))
    const c = new RelayClient({ relayUrl: 'https://x', token: 'tok' }, { fetch: fakeFetch as any })
    await expect(c.send({ to: 'bob', kind: 'chat', content: 'x' })).rejects.toThrow(/invalid_body/)
  })

  it('listPeers calls GET /v1/peers', async () => {
    const fakeFetch = vi.fn(async () =>
      new Response(JSON.stringify([{ handle: 'alice', online: true }]), { status: 200 }))
    const c = new RelayClient({ relayUrl: 'https://x', token: 'tok' }, { fetch: fakeFetch as any })
    const list = await c.listPeers()
    expect(list[0]!.handle).toBe('alice')
  })
})

describe('RelayClient ledger calls', () => {
  const rig = (status: number, body: unknown = {}) => {
    const calls: { url: string; init: RequestInit }[] = []
    const f = vi.fn(async (url: string | URL, init: RequestInit) => { calls.push({ url: String(url), init }); return new Response(JSON.stringify(body), { status }) })
    return { calls, c: new RelayClient({ relayUrl: 'https://x', token: 'tok', sessionId: 's_01hrk7y0000000000000aaaaa1' }, { fetch: f as any }) }
  }

  it('writes card fields with the session, and says when the relay has not attached the session yet', async () => {
    const ok = rig(200)
    await ok.c.writeCard({ agent: 'claude', repo: 'sunkit' })
    expect(JSON.parse(String(ok.calls[0]!.init.body))).toEqual({ session: 's_01hrk7y0000000000000aaaaa1', agent: 'claude', repo: 'sunkit' })
    await expect(rig(404).c.writeCard({ agent: 'claude' })).rejects.toThrow(/not attached/)
  })

  it('reads, moves and rebinds a task as this session', async () => {
    const g = rig(200, { state: 'submitted', assignee: { session: null } })
    expect(await g.c.getTask('task_01HRK7Y0000000000000000000')).toEqual({ status: 200, task: { state: 'submitted', assignee: { session: null } } })
    const p = rig(409, { error: 'task_terminal' })
    expect(await p.c.patchTask('task_01HRK7Y0000000000000000000', { state: 'working' })).toEqual({ status: 409, error: 'task_terminal' })
    const h = p.calls[0]!.init.headers as Record<string, string>
    expect(h['x-mesh-session']).toBe('s_01hrk7y0000000000000aaaaa1')
    expect(p.calls[0]!.init.method).toBe('PATCH')
    const r = rig(200, {})
    expect((await r.c.rebindTask('task_01HRK7Y0000000000000000000')).status).toBe(200)
    expect(r.calls[0]!.url).toBe('https://x/v1/tasks/task_01HRK7Y0000000000000000000/rebind')
  })
})
