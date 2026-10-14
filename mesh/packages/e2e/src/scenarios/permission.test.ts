import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { startHarness, type Harness } from '../harness.ts'

describe('L3: permission relay (via /v1/permission/respond)', () => {
  let h: Harness
  beforeEach(async () => { h = await startHarness(['alice','bob'], { permissionRelay: true }) })
  afterEach(async () => { await h.cleanup() })

  it('alice sends permission_request; bob allows via /v1/permission/respond', async () => {
    const req = await fetch(new URL('/v1/messages', h.relayUrl), {
      method: 'POST',
      headers: { authorization: `Bearer ${h.humans.alice!.token}`, 'content-type': 'application/json' },
      body: JSON.stringify({
        to: 'bob', kind: 'permission_request', content: 'rm -rf dist/',
        meta: {
          request_id: 'abcde', tool_name: 'Bash', input_preview: 'rm -rf dist/',
          requester: 'alice', expires_at: new Date(Date.now()+60_000).toISOString()
        }
      })
    })
    expect(req.status).toBe(201)

    const respond = await fetch(new URL('/v1/permission/respond', h.relayUrl), {
      method: 'POST',
      headers: { authorization: `Bearer ${h.humans.bob!.token}`, 'content-type': 'application/json' },
      body: JSON.stringify({ request_id: 'abcde', verdict: 'allow', reason: 'ok' })
    })
    expect(respond.status).toBe(200)

    const res = await fetch(new URL('/v1/stream?since=msg_00000000000000000000000000', h.relayUrl),
      { headers: { authorization: `Bearer ${h.humans.alice!.token}` } })
    const reader = res.body!.getReader()
    const { value } = await reader.read()
    const text = new TextDecoder().decode(value)
    expect(text).toContain('"kind":"permission_verdict"')
    expect(text).toContain('"behavior":"allow"')
    try { await reader.cancel() } catch { /* ignore */ }
  })

  it('expired permission_request yields 410', async () => {
    await fetch(new URL('/v1/messages', h.relayUrl), {
      method: 'POST',
      headers: { authorization: `Bearer ${h.humans.alice!.token}`, 'content-type': 'application/json' },
      body: JSON.stringify({
        to: 'bob', kind: 'permission_request', content: 'x',
        meta: { request_id: 'abcde', tool_name: 'x', input_preview: 'x',
                requester: 'alice', expires_at: new Date(Date.now()-1000).toISOString() }
      })
    })
    const res = await fetch(new URL('/v1/permission/respond', h.relayUrl), {
      method: 'POST',
      headers: { authorization: `Bearer ${h.humans.bob!.token}`, 'content-type': 'application/json' },
      body: JSON.stringify({ request_id: 'abcde', verdict: 'allow' })
    })
    expect(res.status).toBe(410)
  })
})
