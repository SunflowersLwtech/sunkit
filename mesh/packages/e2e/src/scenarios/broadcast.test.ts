import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { startHarness, type Harness } from '../harness.ts'
import { drive, canDrive } from '../claude-driver.ts'

describe.skipIf(!canDrive())('L3: broadcast scatter/gather', () => {
  let h: Harness
  beforeEach(async () => { h = await startHarness(['alice','bob','charlie']) })
  afterEach(async () => { await h.cleanup() })

  it('@team from alice reaches bob and charlie', async () => {
    const bobP = drive({ cwd: h.humans.bob!.configDir,
      prompt: 'When a broadcast arrives, reply to the sender with "got-it-bob".', timeoutMs: 45_000 })
    const charlieP = drive({ cwd: h.humans.charlie!.configDir,
      prompt: 'When a broadcast arrives, reply to the sender with "got-it-charlie".', timeoutMs: 45_000 })
    await new Promise(r => setTimeout(r, 1500))
    await drive({ cwd: h.humans.alice!.configDir,
      prompt: 'Use send_to_peer with to="@team" and content="roll-call".', timeoutMs: 45_000 })
    await Promise.all([bobP, charlieP])

    const res = await fetch(new URL('/v1/stream?since=msg_00000000000000000000000000', h.relayUrl),
      { headers: { authorization: `Bearer ${h.humans.alice!.token}` } })
    const reader = res.body!.getReader()
    const { value } = await reader.read()
    const text = new TextDecoder().decode(value)
    expect(text).toContain('got-it-bob')
    expect(text).toContain('got-it-charlie')
    try { await reader.cancel() } catch { /* ignore */ }
  }, 180_000)
})
