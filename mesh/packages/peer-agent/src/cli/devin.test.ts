import { describe, it, expect, afterEach, vi } from 'vitest'
import { existsSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { DEVIN_EVENTS, devinAddArgs, devinHookOutput, devinHookRequest, devinHooks, mergeDevinHooks, parseDevinInstall, runDevin, runDevinHook, runDevinInstall, shellQuote, stableNode } from './devin.ts'
import { HookChannel, hookSocketPath, serveHookSocket } from '../hook-socket.ts'
import { Inbox } from '../inbox.ts'

const opts = { node: '/opt/homebrew/bin/node', peer: '/k/mesh-peer.mjs', cli: '/k/mesh cli.mjs', scope: 'user' as const, name: 'mesh', config: '/x/devin/config.json' }

// A group another tool put in the same file (the shape Orca left on a Windows machine).
const foreign = { hooks: [{ type: 'command', command: 'C:\\Users\\x\\.orca\\agent-hooks\\devin-hook.cmd', timeout: 10 }] }

describe('mesh devin install', () => {
  it('adds the peer in pull mode as host devin, without a session name in the config', () => {
    expect(devinAddArgs(opts)).toEqual(['mcp', 'add', '-s', 'user', 'mesh', '-e', 'MESH_JOIN=pull', '-e', 'MESH_HOST=devin', '--', '/opt/homebrew/bin/node', '/k/mesh-peer.mjs'])
    expect(devinAddArgs(opts).join(' ')).not.toContain('MESH_SESSION_NAME')
  })

  it('hooks run the bundled CLI with the same node for each event, quoted for sh -c; SessionStart may wait for the peer', () => {
    const h = devinHooks(opts, 'darwin') as Record<string, Array<{ hooks: Array<{ type: string; command: string; timeout: number }> }>>
    expect(Object.keys(h)).toEqual([...DEVIN_EVENTS])
    expect(DEVIN_EVENTS).toEqual(['SessionStart', 'UserPromptSubmit', 'PostToolUse', 'Stop', 'SessionEnd'])
    for (const e of DEVIN_EVENTS) {
      expect(h[e]).toEqual([{ hooks: [{ type: 'command', command: `/opt/homebrew/bin/node '/k/mesh cli.mjs' devin hook ${e}`, timeout: e === 'SessionStart' ? 10 : 5 }] }])
    }
  })

  it('on Windows the paths are double-quoted with forward slashes (Devin runs hooks through Git Bash; cmd reads them too)', () => {
    const h = devinHooks({ ...opts, node: 'C:\\Program Files\\nodejs\\node.exe', cli: 'E:\\Developer\\sunkit\\mesh-cli.mjs' }, 'win32') as Record<string, Array<{ hooks: Array<{ command: string }> }>>
    expect(h.Stop![0]!.hooks[0]!.command).toBe('"C:/Program Files/nodejs/node.exe" "E:/Developer/sunkit/mesh-cli.mjs" devin hook Stop')
  })

  it('merging keeps every other setting and hook, and replaces an earlier mesh entry instead of adding a second', () => {
    const before = JSON.stringify({ version: 1, theme_mode: 'dark', hooks: { Stop: [foreign], PreToolUse: [foreign] }, agent: { model: 'swe-2-high' } })
    const first = JSON.parse(mergeDevinHooks(before, devinHooks(opts, 'darwin')))
    expect(first.version).toBe(1)
    expect(first.theme_mode).toBe('dark')
    expect(first.agent).toEqual({ model: 'swe-2-high' })
    expect(first.hooks.PreToolUse).toEqual([foreign])
    expect(first.hooks.Stop).toEqual([foreign, { hooks: [{ type: 'command', command: `/opt/homebrew/bin/node '/k/mesh cli.mjs' devin hook Stop`, timeout: 5 }] }])
    expect(Object.keys(first.hooks).sort()).toEqual(['PostToolUse', 'PreToolUse', 'SessionEnd', 'SessionStart', 'Stop', 'UserPromptSubmit'])

    // Reinstalled from a moved checkout: the old mesh entry goes, the foreign one stays.
    const moved = JSON.parse(mergeDevinHooks(JSON.stringify(first), devinHooks({ ...opts, cli: '/new/mesh-cli.mjs' }, 'darwin')))
    expect(moved.hooks.Stop).toEqual([foreign, { hooks: [{ type: 'command', command: '/opt/homebrew/bin/node /new/mesh-cli.mjs devin hook Stop', timeout: 5 }] }])
    for (const e of DEVIN_EVENTS) expect(JSON.stringify(moved.hooks[e])).not.toContain('/k/mesh cli.mjs')

    // Same install twice: byte-identical.
    const once = mergeDevinHooks(before, devinHooks(opts, 'darwin'))
    expect(mergeDevinHooks(once, devinHooks(opts, 'darwin'))).toBe(once)
  })

  it('drops a mesh entry for an event this version no longer installs, and the event if nothing else is left', () => {
    const old = { hooks: { PreToolUse: [{ hooks: [{ type: 'command', command: "/n/node '/k/mesh-cli.mjs' devin hook PreToolUse" }] }], PostCompaction: [foreign, { hooks: [{ type: 'command', command: '/n/node /k/mesh-cli.mjs devin hook PostCompaction' }] }] } }
    const out = JSON.parse(mergeDevinHooks(JSON.stringify(old), devinHooks(opts, 'darwin')))
    expect(out.hooks.PreToolUse).toBeUndefined()
    expect(out.hooks.PostCompaction).toEqual([foreign])
  })

  it('starts from nothing, tolerates a BOM, and refuses a file that is not a JSON object', () => {
    expect(Object.keys(JSON.parse(mergeDevinHooks(undefined, devinHooks(opts, 'darwin'))))).toEqual(['hooks'])
    expect(JSON.parse(mergeDevinHooks('\uFEFF{"theme_mode":"dark"}', devinHooks(opts, 'darwin'))).theme_mode).toBe('dark')
    expect(() => mergeDevinHooks('[1]', devinHooks(opts, 'darwin'))).toThrow(/not a JSON object/)
    expect(() => mergeDevinHooks('{"hooks":[]}', devinHooks(opts, 'darwin'))).toThrow(/"hooks" is not an object/)
  })

  it('--write replaces the MCP server and merges the hooks into config.json, backing up a changed file; without it nothing is touched', () => {
    const dir = mkdtempSync(join(tmpdir(), 'devin-inst-'))
    const config = join(dir, 'devin', 'config.json')
    const runs: string[][] = []
    const run = (file: string, argv: string[]) => {
      runs.push([file, ...argv])
      if (argv[1] === 'remove') throw new Error('server not found')
    }
    const args = ['--config', config, '--node', '/n/node', '--peer', '/p/mesh-peer.mjs', '--cli', '/p/mesh-cli.mjs']
    expect(runDevinInstall(args, { log: () => {}, run })).toBe(0)
    expect(runs).toEqual([])
    expect(existsSync(config)).toBe(false)

    expect(runDevinInstall([...args, '--write'], { log: () => {}, run })).toBe(0)
    expect(runs).toEqual([
      ['devin', 'mcp', 'remove', '-s', 'user', 'mesh'],
      ['devin', 'mcp', 'add', '-s', 'user', 'mesh', '-e', 'MESH_JOIN=pull', '-e', 'MESH_HOST=devin', '--', '/n/node', '/p/mesh-peer.mjs'],
    ])
    const written = JSON.parse(readFileSync(config, 'utf8'))
    expect(written.hooks.Stop[0].hooks[0].command).toMatch(/^"?\/n\/node"? "?\/p\/mesh-cli\.mjs"? devin hook Stop$/)
    expect(readdirSync(join(dir, 'devin'))).toEqual(['config.json'])

    // Unchanged: no backup.
    runDevinInstall([...args, '--write'], { log: () => {}, run })
    expect(readdirSync(join(dir, 'devin'))).toEqual(['config.json'])

    // Someone else's settings in the file: kept, and the file before our change is backed up.
    writeFileSync(config, JSON.stringify({ theme_mode: 'light', hooks: { Stop: [foreign] } }))
    runDevinInstall([...args, '--write'], { log: () => {}, run })
    const files = readdirSync(join(dir, 'devin')).sort()
    expect(files).toHaveLength(2)
    expect(files[1]).toMatch(/^config\.json\.bak-mesh-\d{8}-\d{6}$/)
    const merged = JSON.parse(readFileSync(config, 'utf8'))
    expect(merged.theme_mode).toBe('light')
    expect(merged.hooks.Stop[0]).toEqual(foreign)
    expect(merged.hooks.Stop).toHaveLength(2)
  })
})

describe('mesh devin install options', () => {
  const defaults = { node: '/opt/node/bin/node', peer: '/Users/me/sunkit/mesh/plugins/mesh/server/mesh-peer.mjs', cli: '/Users/me/sunkit/mesh/plugins/mesh/server/mesh-cli.mjs', config: '/Users/me/.config/devin/config.json' }
  it('builds a devin mcp add that runs the peer in pull mode with absolute paths', () => {
    expect(devinAddArgs(parseDevinInstall([], defaults))).toEqual([
      'mcp', 'add', '-s', 'user', 'mesh', '-e', 'MESH_JOIN=pull', '-e', 'MESH_HOST=devin', '--', '/opt/node/bin/node', '/Users/me/sunkit/mesh/plugins/mesh/server/mesh-peer.mjs',
    ])
    expect(parseDevinInstall(['--scope', 'local', '--name', 'mesh2', '--peer', '/p.mjs', '--config', '/c.json'], defaults)).toEqual({ ...defaults, peer: '/p.mjs', config: '/c.json', scope: 'local', name: 'mesh2' })
    expect(() => parseDevinInstall(['--scope', 'global'], defaults)).toThrow(/usage/)
  })
  it('only prints by default; --write runs devin with exactly that argv', async () => {
    const lines: string[] = []
    const run = vi.fn()
    const config = join(mkdtempSync(join(tmpdir(), 'devin-run-')), 'config.json')
    expect(await runDevin(['install', '--config', config], { log: l => lines.push(l), run })).toBe(0)
    expect(run).not.toHaveBeenCalled()
    expect(lines[0]).toMatch(/^devin mcp add -s user mesh -e MESH_JOIN=pull -e MESH_HOST=devin -- \S+ \S+mesh-peer\.mjs$/)
    expect(existsSync(config)).toBe(false)
    await runDevin(['install', '--write', '--config', config], { log: () => {}, run })
    expect(run).toHaveBeenCalledWith('devin', expect.arrayContaining(['mcp', 'add', '-e', 'MESH_JOIN=pull', 'MESH_HOST=devin']))
    expect(existsSync(config)).toBe(true)
    expect(await runDevin(['bogus'], { log: () => {} })).toBe(2)
  })
  it('uses the node on PATH (a link that survives upgrades), skipping fnm per-shell dirs; --node overrides', () => {
    const exists = (p: string) => ['/x/fnm_multishells/123_456/bin/node', '/opt/homebrew/bin/node', '/usr/bin/node'].includes(p)
    expect(stableNode('/x/fnm_multishells/123_456/bin:/opt/homebrew/bin:/usr/bin', '/opt/homebrew/Cellar/node/26.0.0/bin/node', exists)).toBe('/opt/homebrew/bin/node')
    expect(stableNode('/nowhere', '/fallback/node', exists)).toBe('/fallback/node')
    expect(stableNode(undefined, '/fallback/node', exists)).toBe('/fallback/node')
    expect(parseDevinInstall(['--node', '/usr/local/bin/node'], defaults).node).toBe('/usr/local/bin/node')
  })
  it('quotes paths with spaces for the shell', () => {
    expect(shellQuote('/Library/Application Support/x')).toBe("'/Library/Application Support/x'")
    expect(shellQuote('/usr/bin/node')).toBe('/usr/bin/node')
  })
})

describe('mesh devin hook', () => {
  it('maps Devin CLI events to requests; every Stop is the agent ending its own turn', () => {
    expect(devinHookRequest('SessionStart', { source: 'startup' })).toEqual({ op: 'idle' })
    expect(devinHookRequest('UserPromptSubmit', { prompt: 'x' })).toEqual({ op: 'turn' })
    expect(devinHookRequest('PostToolUse', { tool_name: 'exec' })).toEqual({ op: 'tool' })
    // Devin fires no Stop when the user interrupts (measured on 3000.11.3): a Stop is always natural.
    expect(devinHookRequest('Stop', { stop_hook_active: false })).toEqual({ op: 'stop', natural: true })
    expect(devinHookRequest('Stop', { stop_hook_active: true })).toEqual({ op: 'stop', natural: true })
    expect(devinHookRequest('SessionEnd', { reason: 'exit' })).toBeUndefined()
    expect(devinHookRequest('PreToolUse', {})).toBeUndefined()
  })

  it('adds a notice to a tool result only when the peer asks, and blocks a stop only when it says continue; names senders, never content', () => {
    expect(devinHookOutput('PostToolUse', undefined)).toEqual({})
    expect(devinHookOutput('PostToolUse', { unread: 1, from: ['lead [abc123]'], notify: false })).toEqual({})
    expect(devinHookOutput('PostToolUse', { unread: 1, from: ['lead [abc123]'], notify: true })).toEqual({
      hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: '[mesh] 1 unread message from lead [abc123] is waiting. Call the mesh read_messages tool to read it.' },
    })
    expect(devinHookOutput('Stop', { unread: 1, from: ['lead [abc123]'], continue: false })).toEqual({})
    const out = devinHookOutput('Stop', { unread: 2, from: ['a [1]', 'b [2]'], continue: true })
    expect(out.decision).toBe('block')
    expect(out.reason).toMatch(/^\[mesh\] 2 messages from a \[1\], b \[2\] arrived and are still unread/)
    expect(devinHookOutput('UserPromptSubmit', { unread: 1, from: ['x'], continue: true, notify: true })).toEqual({})
  })

  describe('against a running peer', () => {
    const saved = process.env.MESH_HOME
    const closers: Array<() => void> = []
    afterEach(() => {
      for (const c of closers.splice(0)) c()
      if (saved === undefined) delete process.env.MESH_HOME; else process.env.MESH_HOME = saved
    })
    const serve = async (statuses: string[], inbox = new Inbox()) => {
      const server = await serveHookSocket(hookSocketPath(process.ppid), new HookChannel(inbox, s => statuses.push(s)))
      closers.push(() => server.close())
      return inbox
    }

    it('reports idle at start and busy while working, tells a tool call once, keeps a stop going once per arrival', async () => {
      process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'devin-hook-'))
      const statuses: string[] = []
      const inbox = await serve(statuses)
      const out: string[] = []
      // The hook's parent is a shell or the agent; the peer is a child of the agent. Here the peer is
      // served at our parent's pid and the hook is told its parent is us, so it must look one level up.
      const hook = (event: string, payload: object) => runDevinHook([event], { stdin: async () => JSON.stringify(payload), write: s => out.push(s), ppid: process.pid })

      expect(await hook('SessionStart', { source: 'startup', session_id: 'spiny-keyboard' })).toBe(0)
      expect(out.pop()).toBe('{}\n')
      await hook('UserPromptSubmit', { prompt: 'work', session_id: 'spiny-keyboard' })
      await hook('PostToolUse', { tool_name: 'exec', session_id: 'spiny-keyboard' })
      expect(out.splice(0)).toEqual(['{}\n', '{}\n'])
      inbox.push({ content: 'hi', meta: { from: 'lead [abc123]' } })
      await hook('PostToolUse', { tool_name: 'read', session_id: 'spiny-keyboard' })
      expect(JSON.parse(out.pop()!).hookSpecificOutput.additionalContext).toContain('from lead [abc123]')
      await hook('PostToolUse', { tool_name: 'read', session_id: 'spiny-keyboard' })
      expect(out.pop()).toBe('{}\n')
      await hook('Stop', { stop_hook_active: false, session_id: 'spiny-keyboard' })
      expect(JSON.parse(out.pop()!).decision).toBe('block')
      await hook('Stop', { stop_hook_active: true, session_id: 'spiny-keyboard' })
      expect(out.pop()).toBe('{}\n')
      expect(statuses).toEqual(['idle', 'busy', 'busy', 'busy', 'busy', 'idle'])
    })

    it('remembers which process answered for a session, so later hooks skip the search; SessionEnd forgets it', async () => {
      process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'devin-hook-'))
      const statuses: string[] = []
      await serve(statuses)
      const out: string[] = []
      const hook = (event: string, payload: object, ppid: number) => runDevinHook([event], { stdin: async () => JSON.stringify(payload), write: s => out.push(s), ppid })

      await hook('SessionStart', { source: 'startup', session_id: 'dapper-limit' }, process.pid)
      expect(statuses).toEqual(['idle'])
      // pid 1 has no peer and no useful ancestors: only the remembered process can answer.
      await hook('UserPromptSubmit', { prompt: 'x', session_id: 'dapper-limit' }, 1)
      expect(statuses).toEqual(['idle', 'busy'])
      // A different session is not given that process.
      await hook('Stop', { session_id: 'other-session' }, 1)
      expect(statuses).toEqual(['idle', 'busy'])
      // A session id that is not a plain word is never used in a path, even when a peer answers.
      await hook('UserPromptSubmit', { prompt: 'x', session_id: '../../../escape' }, process.pid)
      expect(statuses).toEqual(['idle', 'busy', 'busy'])
      expect(readdirSync(join(process.env.MESH_HOME!, 'hooks')).filter(f => f.endsWith('.pid'))).toEqual(['devin-dapper-limit.pid'])
      expect(existsSync(join(process.env.MESH_HOME!, 'escape.pid'))).toBe(false)
      await hook('Stop', { session_id: '../../etc' }, 1)
      expect(statuses).toEqual(['idle', 'busy', 'busy'])

      await hook('SessionEnd', { reason: 'exit', session_id: 'dapper-limit' }, 1)
      await hook('Stop', { session_id: 'dapper-limit' }, 1)
      expect(statuses).toEqual(['idle', 'busy', 'busy'])
      expect(out.every(s => s === '{}\n')).toBe(true)
    })

    it('SessionStart waits for a peer that is still starting; other events do not wait', async () => {
      process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'devin-hook-'))
      const statuses: string[] = []
      const t0 = Date.now()
      const late = runDevinHook(['SessionStart'], { stdin: async () => '{"source":"startup"}', write: () => {}, ppid: process.pid })
      await new Promise(r => setTimeout(r, 400))
      await serve(statuses)
      expect(await late).toBe(0)
      expect(statuses).toEqual(['idle'])
      expect(Date.now() - t0).toBeLessThan(3_000)
    })

    it('a hook without a peer answers {} at once, except SessionStart which gives up after its wait', async () => {
      process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'devin-hook-'))
      const out: string[] = []
      let t0 = Date.now()
      await runDevinHook(['PostToolUse'], { stdin: async () => '{}', write: s => out.push(s), ppid: 1 })
      expect(Date.now() - t0).toBeLessThan(1_000)
      t0 = Date.now()
      await runDevinHook(['SessionStart'], { stdin: async () => '{}', write: s => out.push(s), ppid: 1, waitMs: 600 })
      const waited = Date.now() - t0
      expect(waited).toBeGreaterThanOrEqual(500)
      expect(waited).toBeLessThan(2_000)
      expect(out).toEqual(['{}\n', '{}\n'])
    })

    it('prints {} and exits 0 when the event is unknown or stdin is not JSON', async () => {
      process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'devin-hook-'))
      const out: string[] = []
      for (const [event, raw] of [['Stop', 'not json'], ['PreToolUse', '{}'], ['', '']] as const) {
        expect(await runDevinHook(event ? [event] : [], { stdin: async () => raw, write: s => out.push(s), ppid: 1 })).toBe(0)
      }
      expect(out).toEqual(['{}\n', '{}\n', '{}\n'])
    })
  })
})
