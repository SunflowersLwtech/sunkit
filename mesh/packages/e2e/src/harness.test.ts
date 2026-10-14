import { describe, it, expect } from 'vitest'
import { startHarness } from './harness.ts'

describe('startHarness', () => {
  it('provisions a team with N humans, each with a valid token', async () => {
    const h = await startHarness(['alice','bob','charlie'])
    try {
      const res = await fetch(new URL('/v1/peers', h.relayUrl), {
        headers: { authorization: `Bearer ${h.humans.alice!.token}` }
      })
      const peers = await res.json() as Array<{ handle: string }>
      expect(peers.map(p => p.handle).sort()).toEqual(['alice','bob','charlie'])
    } finally { await h.cleanup() }
  })

  it('message sent by alice can be fetched on bob\'s stream (via ?since=)', async () => {
    const h = await startHarness(['alice','bob'])
    try {
      await fetch(new URL('/v1/messages', h.relayUrl), {
        method: 'POST',
        headers: { authorization: `Bearer ${h.humans.alice!.token}`, 'content-type': 'application/json' },
        body: JSON.stringify({ to: 'bob', kind: 'chat', content: 'hello' })
      })
      const res = await fetch(new URL('/v1/stream?since=msg_00000000000000000000000000', h.relayUrl), {
        headers: { authorization: `Bearer ${h.humans.bob!.token}`, accept: 'text/event-stream' }
      })
      const reader = res.body!.getReader()
      const { value } = await reader.read()
      const text = new TextDecoder().decode(value)
      expect(text).toContain('"content":"hello"')
      try { await reader.cancel() } catch { /* ignore */ }
    } finally { await h.cleanup() }
  })
})
