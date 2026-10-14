import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { startHarness, type Harness } from '../harness.ts'

describe('L3: thread reconstruction (relay-only, no CC needed)', () => {
  let h: Harness
  beforeEach(async () => { h = await startHarness(['alice','bob','charlie']) })
  afterEach(async () => { await h.cleanup() })

  it('thread_root stays fixed across a 4-message reply chain', async () => {
    async function post(from: 'alice'|'bob'|'charlie', to: string, content: string, in_reply_to?: string) {
      const body: Record<string, unknown> = { to, kind: 'chat', content }
      if (in_reply_to) body.in_reply_to = in_reply_to
      const res = await fetch(new URL('/v1/messages', h.relayUrl), {
        method: 'POST',
        headers: { authorization: `Bearer ${h.humans[from]!.token}`, 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      return await res.json() as { id: string; thread_root: string | null }
    }
    const root = await post('alice', 'bob', 'r0')
    const r1 = await post('bob', 'alice', 'r1', root.id)
    const r2 = await post('charlie', 'alice', 'r2', r1.id)
    const r3 = await post('alice', 'bob', 'r3', r2.id)
    expect(r1.thread_root).toBe(root.id)
    expect(r2.thread_root).toBe(root.id)
    expect(r3.thread_root).toBe(root.id)
  })
})
