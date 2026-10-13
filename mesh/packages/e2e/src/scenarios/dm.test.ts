import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { startHarness, type Harness } from '../harness.ts'
import { drive, canDrive } from '../claude-driver.ts'

describe.skipIf(!canDrive())('L3: DM round-trip', () => {
  let h: Harness
  beforeEach(async () => { h = await startHarness(['alice','bob']) })
  afterEach(async () => { await h.cleanup() })

  it('alice -> bob -> reply alice (via send_to_peer tool)', async () => {
    const bobPromise = drive({
      cwd: h.humans.bob!.configDir,
      prompt: 'When a <channel source="peers"> message arrives, respond to the sender using the send_to_peer tool. Reply with "pong".',
      timeoutMs: 45_000,
    })
    await new Promise(r => setTimeout(r, 1500))
    await drive({
      cwd: h.humans.alice!.configDir,
      prompt: 'Use the send_to_peer tool to send bob the content "ping".',
      timeoutMs: 45_000,
    })
    await bobPromise

    const resA = await fetch(new URL('/v1/stream?since=msg_00000000000000000000000000', h.relayUrl),
      { headers: { authorization: `Bearer ${h.humans.alice!.token}` } })
    const reader = resA.body!.getReader()
    const { value } = await reader.read()
    const text = new TextDecoder().decode(value)
    expect(text).toContain('pong')
    try { await reader.cancel() } catch { /* ignore */ }
  }, 120_000)
})
