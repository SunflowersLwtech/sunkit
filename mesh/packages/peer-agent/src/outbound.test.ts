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
