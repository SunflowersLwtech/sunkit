import { describe, expect, it, vi } from 'vitest'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  approvalNotice, bossaiControlToken, bossaiPortFile, bossaiServerBody, createWaker,
  injectionBody, parseBossaiInstall, parseBossaiWake, pickHookSocket, readBossaiPort,
  resolveBossaiServer, runBossaiInstall, type WakeDeps,
} from './bossai.ts'
import type { HookReply, HookRequest } from '../hook-socket.ts'

const PORT_JSON = JSON.stringify({ port: 57291 })

describe('bossaiPortFile', () => {
  it('uses Electron userData per platform', () => {
    expect(bossaiPortFile('darwin', {}, '/h')).toBe('/h/Library/Application Support/@bossai/desktop/desktop-server-port.json')
    expect(bossaiPortFile('win32', { APPDATA: 'C:\\Users\\x\\AppData\\Roaming' }, '/h')).toContain('@bossai')
    expect(bossaiPortFile('linux', {}, '/h')).toBe('/h/.config/@bossai/desktop/desktop-server-port.json')
    expect(bossaiPortFile('linux', { XDG_CONFIG_HOME: '/cfg' }, '/h')).toBe('/cfg/@bossai/desktop/desktop-server-port.json')
  })
})

describe('readBossaiPort / resolveBossaiServer', () => {
  it('reads a valid port and rejects malformed files', () => {
    expect(readBossaiPort('p', () => PORT_JSON)).toBe(57291)
    expect(readBossaiPort('p', () => '{"port":"x"}')).toBeUndefined()
    expect(readBossaiPort('p', () => { throw new Error('ENOENT') })).toBeUndefined()
  })
  it('prefers --server, strips trailing slashes, falls back to the port file', () => {
    expect(resolveBossaiServer({ server: 'http://127.0.0.1:9999/' })).toBe('http://127.0.0.1:9999')
    const dir = mkdtempSync(join(tmpdir(), 'bossai-port-'))
    const pf = join(dir, 'desktop-server-port.json')
    writeFileSync(pf, PORT_JSON)
    expect(resolveBossaiServer({ portFile: pf }, 'linux', {})).toBe('http://127.0.0.1:57291')
  })
  it('throws a helpful error when the app is not running', () => {
    expect(() => resolveBossaiServer({ portFile: 'missing' }, 'linux', {})).toThrow(/desktop app running/)
  })
})

describe('bossaiServerBody', () => {
  it('registers the peer as stdio MCP in pull mode with the session name', () => {
    const body = bossaiServerBody({ id: 'mesh', session: 'bossai-m2', node: '/n', peer: '/p.mjs' })
    expect(body.id).toBe('mesh')
    expect(body.enabled).toBe(true)
    const t = body.transport as { type: string; command: string; args: string[]; env: Record<string, string> }
    expect(t.type).toBe('stdio')
    expect(t.command).toBe('/n')
    expect(t.args).toEqual(['/p.mjs'])
    expect(t.env).toEqual({ MESH_JOIN: 'pull', MESH_HOST: 'bossai', MESH_WAKE: '', MESH_SESSION_NAME: 'bossai-m2' })
  })
  it('omits MESH_SESSION_NAME when unnamed', () => {
    const body = bossaiServerBody({ id: 'mesh', node: '/n', peer: '/p' })
    expect((body.transport as { env: Record<string, string> }).env.MESH_SESSION_NAME).toBeUndefined()
  })
})

describe('parseBossaiInstall', () => {
  it('reads flags over defaults', () => {
    const o = parseBossaiInstall(['--id', 'm2', '--session', 'bossai-m2', '--server', 'http://127.0.0.1:1'], { id: 'mesh', node: '/n', peer: '/p' })
    expect(o.id).toBe('m2')
    expect(o.session).toBe('bossai-m2')
    expect(o.server).toBe('http://127.0.0.1:1')
    expect(o.node).toBe('/n')
  })
})

describe('bossaiControlToken', () => {
  it('bootstraps with the same-origin header', async () => {
    const fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ token: 't' }), text: async () => '' }))
    expect(await bossaiControlToken('http://x', fetch)).toBe('t')
    expect(fetch.mock.calls[0]![1]!.headers!['Sec-Fetch-Site']).toBe('same-origin')
  })
  it('fails on HTTP error or missing token', async () => {
    await expect(bossaiControlToken('http://x', async () => ({ ok: false, status: 401, json: async () => ({}), text: async () => '' }))).rejects.toThrow(/401/)
    await expect(bossaiControlToken('http://x', async () => ({ ok: true, status: 200, json: async () => ({}), text: async () => '' }))).rejects.toThrow(/no token/)
  })
})

describe('runBossaiInstall', () => {
  const base = ['--server', 'http://127.0.0.1:1', '--session', 'bossai-m2']
  it('dry-run prints the payload and touches nothing', async () => {
    const fetch = vi.fn()
    const lines: string[] = []
    expect(await runBossaiInstall(base, { log: s => lines.push(s), fetch })).toBe(0)
    expect(fetch).not.toHaveBeenCalled()
    expect(lines.join('\n')).toContain('POST /api/mcp/servers')
  })
  it('--write bootstraps the control token then posts the config', async () => {
    const fetch = vi.fn(async (url: string) => ({
      ok: true, status: url.endsWith('control-token') ? 200 : 200,
      json: async () => url.endsWith('control-token') ? { token: 'ct' } : { ok: true },
      text: async () => '',
    }))
    expect(await runBossaiInstall([...base, '--write'], { log: () => {}, fetch })).toBe(0)
    expect(fetch).toHaveBeenCalledTimes(2)
    const post = fetch.mock.calls[1]!
    expect(post[0]).toBe('http://127.0.0.1:1/api/mcp/servers')
    expect(post[1]!.headers!['x-bossai-mcp-control-token']).toBe('ct')
    expect(JSON.parse(post[1]!.body!).id).toBe('mesh')
  })
  it('reports an existing server without retrying', async () => {
    const fetch = vi.fn(async (url: string) => ({
      ok: url.endsWith('control-token'), status: url.endsWith('control-token') ? 200 : 409,
      json: async () => ({ token: 'ct' }), text: async () => 'exists',
    }))
    const lines: string[] = []
    expect(await runBossaiInstall([...base, '--write'], { log: s => lines.push(s), fetch })).toBe(1)
    expect(lines.join('\n')).toContain('already exists')
  })
})

describe('pickHookSocket', () => {
  const entries = [{ path: '/a.sock', name: 'bossai-m2' }, { path: '/b.sock', name: 'pi-x' }]
  it('matches the exact session name', () => {
    expect(pickHookSocket(entries, 'bossai-m2')).toBe('/a.sock')
    expect(pickHookSocket(entries, 'nope')).toBeUndefined()
  })
  it('without a name, takes a unique bossai-* peer only', () => {
    expect(pickHookSocket(entries)).toBe('/a.sock')
    expect(pickHookSocket([...entries, { path: '/c.sock', name: 'bossai-m3' }])).toBeUndefined()
    expect(pickHookSocket([{ path: '/b.sock', name: 'pi-x' }])).toBeUndefined()
  })
})

describe('injectionBody / approvalNotice', () => {
  it('steers into an active run, plain chat when idle', () => {
    expect(injectionBody('n', true)).toEqual({ text: 'n', deliverAs: 'steer' })
    expect(injectionBody('n', false)).toEqual({ text: 'n' })
  })
  it('names the tool, the session, and never offers auto-approval', () => {
    const s = approvalNotice({ toolCallId: 't1', toolName: 'shell_command', subtitle: 'rm -rf x' }, 'chat-1')
    expect(s).toContain('shell_command')
    expect(s).toContain('chat-1')
    expect(s).toContain('不会代为批准')
  })
})

function deps(over: Partial<WakeDeps> = {}): WakeDeps & { asks: HookRequest[]; injected: Record<string, unknown>[]; notified: string[] } {
  const asks: HookRequest[] = []
  const injected: Record<string, unknown>[] = []
  const notified: string[] = []
  return {
    asks, injected, notified,
    ask: async (_p, req) => { asks.push(req); return req.op === 'whoami' ? { unread: 0, from: [], name: 'bossai-m2' } : { unread: 1, from: ['feishu-assistant'], continue: true } },
    discover: async () => [{ path: '/a.sock', name: 'bossai-m2' }],
    activeRun: async () => false,
    inject: async body => { injected.push(body); return { ok: true, status: 200 } },
    pendingAsk: async () => undefined,
    notify: async text => { notified.push(text) },
    log: () => {},
    sleep: async () => {},
    ...over,
  }
}
const opts = { chat: 'chat-1', session: 'bossai-m2', server: 'http://x', token: 't', pollMs: 1 }

describe('createWaker', () => {
  it('injects a plain notice when idle and reports the turn', async () => {
    const d = deps()
    await createWaker(opts, d).tick()
    expect(d.injected).toEqual([{ text: expect.stringContaining('read_messages') }])
    expect(d.asks.map(a => a.op)).toEqual(['wake', 'turn'])
  })
  it('steers when a run is active', async () => {
    const d = deps({ activeRun: async () => true })
    await createWaker(opts, d).tick()
    expect(d.injected[0]!.deliverAs).toBe('steer')
  })
  it('reports idle once the injected run finishes', async () => {
    let active = true
    const d = deps({ activeRun: async () => active })
    const w = createWaker(opts, d)
    await w.tick()
    active = false
    await w.tick()
    expect(d.asks.map(a => a.op)).toContain('idle')
  })
  it('retries a 409-deferred injection without re-asking the wake nudge', async () => {
    let fail = true
    const d = deps({ inject: async body => { d.injected.push(body); if (fail) { fail = false; return { ok: false, status: 409 } } return { ok: true, status: 200 } } })
    const w = createWaker(opts, d)
    await w.tick()
    await w.tick()
    expect(d.injected).toHaveLength(2)
    expect(d.asks.filter(a => a.op === 'wake')).toHaveLength(1)
  })
  it('does nothing without a matching socket', async () => {
    const d = deps({ discover: async () => [] })
    await createWaker(opts, d).tick()
    expect(d.injected).toHaveLength(0)
  })
  it('notifies a mesh contact once per pending approval', async () => {
    let ask: { toolCallId: string; toolName: string } | undefined = { toolCallId: 't1', toolName: 'shell_command' }
    const d = deps({ pendingAsk: async () => ask })
    const w = createWaker({ ...opts, notify: 'feishu-assistant' }, d)
    await w.tick()
    await w.tick()
    expect(d.notified).toHaveLength(1)
    expect(d.notified[0]).toContain('shell_command')
    ask = undefined
    await w.tick()
    ask = { toolCallId: 't2', toolName: 'write' }
    await w.tick()
    expect(d.notified).toHaveLength(2)
  })
})

describe('parseBossaiWake', () => {
  it('requires --chat and a token', () => {
    expect(() => parseBossaiWake([], {})).toThrow(/usage/)
    expect(() => parseBossaiWake(['--chat', 'c', '--server', 'http://x'], {})).toThrow(/token/)
    const o = parseBossaiWake(['--chat', 'c', '--server', 'http://x'], { BOSSAI_CLOUD_TOKEN: 't' })
    expect(o.chat).toBe('c')
    expect(o.token).toBe('t')
    expect(o.pollMs).toBe(3000)
  })
  it('clamps a too-small poll interval', () => {
    const o = parseBossaiWake(['--chat', 'c', '--server', 'http://x', '--poll-ms', '10'], { BOSSAI_CLOUD_TOKEN: 't' })
    expect(o.pollMs).toBe(3000)
  })
})