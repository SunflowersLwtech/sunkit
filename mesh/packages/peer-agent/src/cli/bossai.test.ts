import { describe, expect, it, vi } from 'vitest'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  approvalNotice, bossaiControlToken, bossaiPortFile, bossaiServerBody, createWaker,
  filterLetters, injectionBody, parseBossaiInstall, parseBossaiWake, parseChannels, pickHookSocket,
  approvalNotice, discoverBossaiSockets, parseApprovalCommand, readBossaiPort, resolveBossaiServer, runBossaiInstall, senderAllowed, type WakeDeps,
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
describe('parseChannels / senderAllowed / filterLetters', () => {
  const text = '<channel from="feishu-assistant [8vetwb]" account="weiliu" msg_id="m1">\n任务一\n</channel>\n<channel from="stranger [x]" account="other" msg_id="m2">\n坏信\n</channel>'
  it('parses channel blocks with from and body', () => {
    const ls = parseChannels(text)
    expect(ls).toHaveLength(2)
    expect(ls[0]!.from).toBe('feishu-assistant [8vetwb]')
    expect(ls[0]!.body).toBe('任务一')
  })
  it('matches sender name prefixes before the [ref]', () => {
    expect(senderAllowed('feishu-assistant [8vetwb]', ['feishu-assistant'])).toBe(true)
    expect(senderAllowed('stranger [x]', ['feishu-assistant'])).toBe(false)
    expect(senderAllowed('anyone', undefined)).toBe(true)
  })
  it('keeps allowed letters and reports dropped senders', () => {
    const r = filterLetters(text, ['feishu-assistant'])
    expect(r.kept).toContain('任务一')
    expect(r.kept).not.toContain('坏信')
    expect(r.dropped).toEqual(['stranger [x]'])
  })
})

describe('createWaker --bridge', () => {
  const letters = '<channel from="feishu-assistant [8vetwb]" account="weiliu" msg_id="m1">\n干活\n</channel>'
  function bridgeDeps(over: Partial<WakeDeps> = {}) {
    const events: string[] = []
    const handle = {
      ask: async (req: HookRequest) => { events.push(`bridge:${req.op}`); return { unread: 1, from: ['feishu-assistant'], continue: true } },
      read: async () => { events.push('bridge:read'); return letters },
      stop: async () => { events.push('bridge:stop') },
    }
    const d = deps({
      discover: async () => [],
      startBridge: async () => { events.push('bridge:start'); return handle },
      ...over,
    })
    return { d, events }
  }
  const bopts = { ...opts, bridge: true, graceMs: 0 }
  it('holds the session, reads mail, stops the child, injects full letters', async () => {
    const { d, events } = bridgeDeps()
    await createWaker(bopts, d).tick()
    expect(events).toEqual(['bridge:start', 'bridge:wake', 'bridge:read', 'bridge:stop'])
    expect(d.injected[0]!.text).toContain('干活')
    expect(d.injected[0]!.text).toContain('send_message')
  })
  it('discards non-allowed senders without injecting', async () => {
    const { d } = bridgeDeps()
    const logs: string[] = []
    d.log = s => logs.push(s)
    await createWaker({ ...bopts, allow: ['someone-else'] }, d).tick()
    expect(d.injected).toHaveLength(0)
    expect(logs.join('\n')).toContain('non-allowed')
  })
  it('holds letters for retry when injection is deferred, without re-reading', async () => {
    let fail = true
    const { d, events } = bridgeDeps({ inject: async body => { d.injected.push(body); if (fail) { fail = false; return { ok: false, status: 409 } } return { ok: true, status: 200 } } })
    const w = createWaker(bopts, d)
    await w.tick()
    await w.tick()
    expect(d.injected).toHaveLength(2)
    expect(events.filter(e => e === 'bridge:read')).toHaveLength(1)
  })
  it('stops the bridge when BossAI own peer appears', async () => {
    const { d, events } = bridgeDeps()
    const w = createWaker(bopts, d)
    await w.tick()
    d.discover = async () => [{ path: '/a.sock', name: 'bossai-m2' }]
    await w.tick()
    expect(events.filter(e => e === 'bridge:stop').length).toBeGreaterThanOrEqual(1)
  })
  it('respects the grace window after stopping', async () => {
    let t = 100_000
    const { d, events } = bridgeDeps({ now: () => t })
    const w = createWaker({ ...bopts, graceMs: 15_000 }, d)
    await w.tick()
    t += 5_000
    await w.tick()
    expect(events.filter(e => e === 'bridge:start')).toHaveLength(1)
    t += 15_000
    await w.tick()
    expect(events.filter(e => e === 'bridge:start')).toHaveLength(2)
  })
  it('without --bridge, an idle app does nothing', async () => {
    const { d } = bridgeDeps()
    await createWaker(opts, d).tick()
    expect(d.injected).toHaveLength(0)
  })
})

describe('parseBossaiWake v2 flags', () => {
  it('parses bridge, allow and grace', () => {
    const o = parseBossaiWake(['--chat', 'c', '--server', 'http://x', '--bridge', '--allow', 'feishu-assistant, m4-', '--grace-ms', '5000'], { BOSSAI_CLOUD_TOKEN: 't' })
    expect(o.bridge).toBe(true)
    expect(o.allow).toEqual(['feishu-assistant', 'm4-'])
    expect(o.graceMs).toBe(5000)
  })
})

describe('parseBossaiWake license', () => {
  it('reads the license from env or file and attaches nothing when absent', () => {
    const o = parseBossaiWake(['--chat', 'c', '--server', 'http://x'], { BOSSAI_CLOUD_TOKEN: 't', BOSSAI_CLOUD_LICENSE: 'lic' })
    expect(o.license).toBe('lic')
    const o2 = parseBossaiWake(['--chat', 'c', '--server', 'http://x'], { BOSSAI_CLOUD_TOKEN: 't' })
    expect(o2.license).toBeUndefined()
  })
})

describe('discoverBossaiSockets', () => {
  it('skips wake own bridge socket so the bridge is not mistaken for BossAI peer', async () => {
    const { mkdtempSync, mkdirSync } = await import('node:fs')
    const { tmpdir } = await import('node:os')
    const { join } = await import('node:path')
    const { serveHookSocket, HookChannel, hookSocketPath } = await import('../hook-socket.ts')
    const { Inbox } = await import('../inbox.ts')
    const dir = mkdtempSync(join(tmpdir(), 'mesh-hooks-'))
    mkdirSync(join(dir, 'hooks'), { recursive: true })
    const own = await serveHookSocket(hookSocketPath(process.pid, dir), new HookChannel(new Inbox(), () => {}, { whoami: () => ({ session: 's', name: 'bossai-devdesk' }) }))
    const other = await serveHookSocket(join(dir, 'hooks', '999999.sock'), new HookChannel(new Inbox(), () => {}, { whoami: () => ({ session: 's2', name: 'bossai-devdesk' }) }))
    try {
      const found = await discoverBossaiSockets(dir)
      expect(found.map(f => f.path)).toEqual([join(dir, 'hooks', '999999.sock')])
    } finally { own.close(); other.close() }
  })
})

describe('parseApprovalCommand / approvalNotice v3', () => {
  it('parses APPROVE and DENY with reason', () => {
    expect(parseApprovalCommand('APPROVE call_1')).toEqual({ action: 'allow', toolCallId: 'call_1' })
    expect(parseApprovalCommand('deny call_2 太危险')).toEqual({ action: 'deny', toolCallId: 'call_2', reason: '太危险' })
    expect(parseApprovalCommand('你好')).toBeUndefined()
    expect(parseApprovalCommand('APPROVE')).toBeUndefined()
  })
  it('notice tells approvers the ctl session and command format', () => {
    const s = approvalNotice({ toolCallId: 'call_1', toolName: 'shell_command' }, 'chat-1', 'bossai-devdesk-ctl')
    expect(s).toContain('bossai-devdesk-ctl')
    expect(s).toContain('APPROVE call_1')
    expect(s).toContain('不会代为批准')
  })
})

describe('createWaker --approvers (mesh-side approval settlement)', () => {
  const ctlLetter = (from: string, body: string) => `<channel from="${from}" account="weiliu" msg_id="m">\n${body}\n</channel>`
  function ctlDeps(reads: string[], over: Partial<WakeDeps> = {}) {
    const settled: { id: string; action: string; reason?: string }[] = []
    const logs: string[] = []
    const d = deps({
      discover: async () => [],
      startCtl: async () => ({ read: async () => reads.shift() ?? '' }),
      resolveAsk: async (id, action, reason) => { settled.push({ id, action, ...(reason ? { reason } : {}) }); return { ok: true, status: 200 } },
      log: s => logs.push(s),
      ...over,
    })
    return { d, settled, logs }
  }
  const aopts = { ...opts, approvers: ['feishu-assistant'] }
  it('settles an APPROVE from an allowed approver, scope once', async () => {
    const { d, settled } = ctlDeps([ctlLetter('feishu-assistant [8vetwb]', 'APPROVE call_1')])
    await createWaker(aopts, d).tick()
    expect(settled).toEqual([{ id: 'call_1', action: 'allow' }])
  })
  it('ignores approval attempts from non-approvers', async () => {
    const { d, settled, logs } = ctlDeps([ctlLetter('stranger [x]', 'APPROVE call_1')])
    await createWaker(aopts, d).tick()
    expect(settled).toHaveLength(0)
    expect(logs.join('\n')).toContain('non-approver')
  })
  it('discards non-command mail on the ctl session', async () => {
    const { d, settled, logs } = ctlDeps([ctlLetter('feishu-assistant [8vetwb]', '随便聊聊')])
    await createWaker(aopts, d).tick()
    expect(settled).toHaveLength(0)
    expect(logs.join('\n')).toContain('non-command')
  })
  it('without --approvers no ctl peer is started', async () => {
    const { d } = ctlDeps([ctlLetter('feishu-assistant [8vetwb]', 'APPROVE call_1')])
    let started = false
    d.startCtl = async () => { started = true; return { read: async () => '' } }
    await createWaker(opts, d).tick()
    expect(started).toBe(false)
  })
})

describe('parseBossaiWake approvers', () => {
  it('parses --approvers list', () => {
    const o = parseBossaiWake(['--chat', 'c', '--server', 'http://x', '--approvers', 'feishu-assistant, bossai-handoff'], { BOSSAI_CLOUD_TOKEN: 't' })
    expect(o.approvers).toEqual(['feishu-assistant', 'bossai-handoff'])
  })
})
