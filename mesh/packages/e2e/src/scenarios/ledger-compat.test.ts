import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { mkdtempSync, realpathSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { startHarness, type Harness } from '../harness.ts'

// The relay's ledger pushes task updates as their own SSE event name (`event: task`) and never
// stores them in the message table. This runs the peer exactly as machines run it today, the
// committed plugin bundle, against the new relay, and checks that a task event neither breaks
// its parser nor stalls its stream.

const BUNDLED_PEER = resolve(import.meta.dirname, '../../../../plugins/mesh/server/mesh-peer.mjs')

interface Peer {
  call: (tool: string, args?: Record<string, unknown>) => Promise<string>
  stderr: () => string
  stop: () => void
}

async function startBundledPeer(h: Harness, who: string, name: string): Promise<Peer> {
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), `host-${who}-`)))
  const home = realpathSync(mkdtempSync(join(tmpdir(), 'mesh-home-')))
  const p: ChildProcessWithoutNullStreams = spawn(process.execPath, [BUNDLED_PEER], {
    cwd,
    env: { PATH: process.env.PATH, HOME: home, MESH_HOME: join(h.humans[who]!.configDir, '.claude-mesh'), MESH_JOIN: 'pull', MESH_SESSION_NAME: name },
    stdio: ['pipe', 'pipe', 'pipe'],
  })
  let buf = ''
  let err = ''
  let next = 1
  const waiting = new Map<number, (m: { result?: { content?: Array<{ text: string }>; isError?: boolean }; error?: unknown }) => void>()
  p.stderr.on('data', d => { err += d })
  p.stdout.on('data', d => {
    buf += d
    let i
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1)
      try { const m = JSON.parse(line); waiting.get(m.id)?.(m); waiting.delete(m.id) } catch { /* not JSON-RPC */ }
    }
  })
  const rpc = (method: string, params: unknown) => new Promise<{ result?: { content?: Array<{ text: string }>; isError?: boolean }; error?: unknown }>(res => {
    const id = next++
    waiting.set(id, res)
    p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
  })
  await rpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'compat', version: '0' } })
  p.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n')
  return {
    call: async (tool, args = {}) => {
      const m = await rpc('tools/call', { name: tool, arguments: args })
      return (m.result?.content ?? []).map(c => c.text).join('\n')
    },
    stderr: () => err,
    stop: () => { p.kill() },
  }
}

async function until<T>(f: () => Promise<T | undefined>, what: string, ms = 10_000): Promise<T> {
  const end = Date.now() + ms
  for (;;) {
    const v = await f().catch(() => undefined)
    if (v !== undefined) return v
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`)
    await new Promise(r => setTimeout(r, 100))
  }
}

describe('L3: the deployed peer bundle against the ledger relay', () => {
  let h: Harness
  const peers: Peer[] = []
  beforeEach(async () => { h = await startHarness(['alice', 'bob']) })
  afterEach(async () => { for (const p of peers.splice(0)) p.stop(); await h.cleanup() })

  it('an event: task reaches the old peer without a decode error, and chat after it still arrives', async () => {
    const bob = await startBundledPeer(h, 'bob', 'bob-inbox'); peers.push(bob)
    const bobSession = await until(async () => {
      const rows = await (await fetch(`${h.relayUrl}/v1/sessions`, { headers: { authorization: `Bearer ${h.humans.bob!.token}` } })).json() as Array<{ session_id: string; name: string }>
      return rows.find(r => r.name === 'bob-inbox')?.session_id
    }, 'bob-inbox attached')

    const created = await fetch(`${h.relayUrl}/v1/tasks`, {
      method: 'POST',
      headers: { authorization: `Bearer ${h.humans.bob!.token}`, 'content-type': 'application/json', 'x-mesh-session': bobSession },
      body: JSON.stringify({ title: 'compat probe' }),
    })
    expect(created.status).toBe(201)
    // Whatever name it arrives under, wait until the peer has seen it, then judge how it handled it.
    await until(async () => (/"event":"(task|message)"/.test(bob.stderr()) ? true : undefined), 'the task event at the peer')
    expect(bob.stderr()).not.toContain('decode_error')
    expect(bob.stderr()).toContain('"event":"task"')

    const sent = await fetch(`${h.relayUrl}/v1/messages`, {
      method: 'POST',
      headers: { authorization: `Bearer ${h.humans.alice!.token}`, 'content-type': 'application/json' },
      body: JSON.stringify({ to: 'bob', to_session: bobSession, kind: 'chat', content: 'after the task event' }),
    })
    expect(sent.status).toBe(201)
    const inbox = await until(async () => { const t = await bob.call('read_messages'); return t.includes('after the task event') ? t : undefined }, 'chat after the task event')
    expect(inbox).toContain('after the task event')
    expect(bob.stderr()).not.toContain('decode_error')
  })
})
