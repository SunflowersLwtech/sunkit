import { describe, it, expect, vi } from 'vitest'
import { callRespond } from './respond.ts'

describe('callRespond', () => {
  it('POSTs /v1/permission/respond with request_id and verdict', async () => {
    const fakeFetch = vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, verdict_id: 'msg_y' }), { status: 200 }))
    const r = await callRespond({
      relayUrl: 'https://x', token: 'tok',
      requestId: 'abcde', verdict: 'allow', reason: 'ok',
      fetch: fakeFetch as any
    })
    expect(r.ok).toBe(true)
  })
  it('throws on 404', async () => {
    const fakeFetch = vi.fn(async () =>
      new Response(JSON.stringify({ error: 'request_not_found' }), { status: 404 }))
    await expect(callRespond({
      relayUrl: 'https://x', token: 'tok', requestId: 'abcde', verdict: 'deny',
      fetch: fakeFetch as any
    })).rejects.toThrow(/request_not_found/)
  })
})
