import { describe, it, expect, afterEach } from 'vitest'
import { mkdtempSync, readFileSync, readdirSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { GROK_EVENTS, grokAddArgs, grokHookOutput, grokHookRequest, grokHooksFile, runGrokHook, runGrokInstall } from './grok.ts'
import { HookChannel, hookSocketPath, serveHookSocket } from '../hook-socket.ts'
import { Inbox } from '../inbox.ts'

const opts = { node: '/opt/homebrew/bin/node', peer: '/k/mesh-peer.mjs', cli: '/k/mesh cli.mjs', name: 'mesh', hooks: '/x/hooks/mesh.json' }

describe('mesh grok install', () => {
  it('adds the peer in pull mode as host grok, without a session name in the config', () => {
    expect(grokAddArgs(opts)).toEqual(['mcp', 'add', '-e', 'MESH_JOIN=pull', '-e', 'MESH_HOST=grok', 'mesh', '--', '/opt/homebrew/bin/node', '/k/mesh-peer.mjs'])
    expect(grokAddArgs(opts).join(' ')).not.toContain('MESH_SESSION_NAME')
  })

  it('the hooks file runs the bundled CLI with the same node for every event, quoted for sh -c, with a short timeout', () => {
    const f = grokHooksFile(opts) as { hooks: Record<string, Array<{ hooks: Array<{ type: string; command: string; timeout: number }> }>> }
    expect(Object.keys(f.hooks)).toEqual([...GROK_EVENTS])
    expect(GROK_EVENTS).toEqual(['SessionStart', 'UserPromptSubmit', 'PostToolUse', 'PostToolUseFailure', 'Stop', 'StopCancelled', 'StopFailure'])
    for (const e of GROK_EVENTS) {
      expect(f.hooks[e]).toEqual([{ hooks: [{ type: 'command', command: `/opt/homebrew/bin/node '/k/mesh cli.mjs' grok hook ${e}`, timeout: 5 }] }])
    }
  })

  it('--write runs grok mcp add and writes our own hooks file, backing up a changed one; without it nothing is touched', () => {
    const dir = mkdtempSync(join(tmpdir(), 'grok-inst-'))
    const hooks = join(dir, 'hooks', 'mesh.json')
    const runs: string[][] = []
    const run = (file: string, argv: string[]) => { runs.push([file, ...argv]) }
    const args = ['--hooks', hooks, '--node', '/n/node', '--peer', '/p/mesh-peer.mjs', '--cli', '/p/mesh-cli.mjs']
    runGrokInstall(args, { log: () => {}, run })
    expect(runs).toEqual([])
    expect(existsSync(hooks)).toBe(false)

    runGrokInstall([...args, '--write'], { log: () => {}, run })
    expect(runs).toEqual([['grok', 'mcp', 'add', '-e', 'MESH_JOIN=pull', '-e', 'MESH_HOST=grok', 'mesh', '--', '/n/node', '/p/mesh-peer.mjs']])
    const written = JSON.parse(readFileSync(hooks, 'utf8'))
    expect(written.hooks.Stop[0].hooks[0].command).toBe('/n/node /p/mesh-cli.mjs grok hook Stop')
    // First write: nothing to back up.
    expect(readdirSync(join(dir, 'hooks'))).toEqual(['mesh.json'])

    // Same paths again: no change, no backup.
    runGrokInstall([...args, '--write'], { log: () => {}, run })
    expect(readdirSync(join(dir, 'hooks'))).toEqual(['mesh.json'])

    // A changed install (new cli path) keeps the old file as a backup that Grok does not load (not *.json).
    writeFileSync(hooks, '{"hooks":{}}')
    runGrokInstall([...args, '--write'], { log: () => {}, run })
    const files = readdirSync(join(dir, 'hooks')).sort()
    expect(files).toHaveLength(2)
    expect(files[0]).toBe('mesh.json')
    expect(files[1]).toMatch(/^mesh\.json\.bak-mesh-\d{8}-\d{6}$/)
    expect(readFileSync(join(dir, 'hooks', files[1]!), 'utf8')).toBe('{"hooks":{}}')
  })
})

describe('mesh grok hook', () => {
  it('maps Grok Build events to requests; only a stop that ended the turn on its own is natural', () => {
    expect(grokHookRequest('SessionStart', { source: 'new' })).toEqual({ op: 'idle' })
    expect(grokHookRequest('UserPromptSubmit', { prompt: 'x' })).toEqual({ op: 'turn' })
    expect(grokHookRequest('PostToolUse', { toolName: 'search_tool' })).toEqual({ op: 'tool' })
    expect(grokHookRequest('PostToolUseFailure', {})).toEqual({ op: 'tool' })
    expect(grokHookRequest('Stop', { reason: 'end_turn', stopHookActive: false })).toEqual({ op: 'stop', reason: 'end_turn', natural: true })
    expect(grokHookRequest('Stop', { reason: 'shutdown' })).toEqual({ op: 'stop', reason: 'shutdown', natural: false })
    expect(grokHookRequest('Stop', undefined)).toEqual({ op: 'stop', natural: false })
    expect(grokHookRequest('StopCancelled', { reason: 'user_interrupt' })).toEqual({ op: 'stop', reason: 'user_interrupt', natural: false })
    expect(grokHookRequest('StopFailure', { reason: 'rate_limit' })).toEqual({ op: 'stop', reason: 'rate_limit', natural: false })
    expect(grokHookRequest('SessionEnd', {})).toBeUndefined()
    expect(grokHookRequest('PreToolUse', {})).toBeUndefined()
  })

  it('adds a notice to a tool result only when the peer asks, naming senders, never content', () => {
    expect(grokHookOutput('PostToolUse', undefined)).toEqual({})
    expect(grokHookOutput('PostToolUse', { unread: 1, from: ['lead [abc123]'], notify: false })).toEqual({})
    expect(grokHookOutput('PostToolUse', { unread: 0, from: [], notify: true })).toEqual({})
    expect(grokHookOutput('PostToolUse', { unread: 1, from: ['lead [abc123]'], notify: true })).toEqual({
      hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: '[mesh] 1 unread message from lead [abc123] is waiting. Call the mesh read_messages tool to read it.' },
    })
    const failure = grokHookOutput('PostToolUseFailure', { unread: 2, from: ['a [1]', 'b [2]'], notify: true }) as { hookSpecificOutput: { hookEventName: string; additionalContext: string } }
    expect(failure.hookSpecificOutput.hookEventName).toBe('PostToolUseFailure')
    expect(failure.hookSpecificOutput.additionalContext).toContain('2 unread messages from a [1], b [2] are waiting')
  })

  it('blocks a stop only when the peer says continue', () => {
    expect(grokHookOutput('Stop', { unread: 1, from: ['lead [abc123]'], continue: false })).toEqual({})
    const out = grokHookOutput('Stop', { unread: 1, from: ['lead [abc123]'], continue: true })
    expect(out.decision).toBe('block')
    expect(out.reason).toMatch(/^\[mesh\] 1 message from lead \[abc123\] arrived and is still unread/)
    expect(grokHookOutput('StopCancelled', { unread: 1, from: ['x'], continue: true })).toEqual({})
    expect(grokHookOutput('PostToolUse', { unread: 1, from: ['x'], continue: true })).toEqual({})
  })

  describe('against a running peer', () => {
    const saved = process.env.MESH_HOME
    const closers: Array<() => void> = []
    afterEach(() => {
      for (const c of closers.splice(0)) c()
      if (saved === undefined) delete process.env.MESH_HOME; else process.env.MESH_HOME = saved
    })

    it('reports idle at start and busy while working, tells a tool call once, keeps a natural stop going once', async () => {
      process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'grok-hook-'))
      const inbox = new Inbox()
      const statuses: string[] = []
      const server = await serveHookSocket(hookSocketPath(process.ppid), new HookChannel(inbox, s => statuses.push(s)))
      closers.push(() => server.close())
      const out: string[] = []
      const hook = (event: string, payload: object) => runGrokHook([event], { stdin: async () => JSON.stringify(payload), write: s => out.push(s), ppid: process.pid })

      expect(await hook('SessionStart', { source: 'new' })).toBe(0)
      expect(out.pop()).toBe('{}\n')
      await hook('UserPromptSubmit', { prompt: 'work' })
      await hook('PostToolUse', { toolName: 'search_tool' })
      expect(out.splice(0)).toEqual(['{}\n', '{}\n'])
      inbox.push({ content: 'hi', meta: { from: 'lead [abc123]' } })
      await hook('PostToolUse', { toolName: 'read_file' })
      expect(JSON.parse(out.pop()!).hookSpecificOutput.additionalContext).toContain('from lead [abc123]')
      await hook('PostToolUse', { toolName: 'read_file' })
      expect(out.pop()).toBe('{}\n')
      await hook('Stop', { reason: 'end_turn', stopHookActive: false })
      expect(JSON.parse(out.pop()!).decision).toBe('block')
      await hook('Stop', { reason: 'end_turn', stopHookActive: true })
      expect(out.pop()).toBe('{}\n')
      // Every hook reports; the peer only sends a change (index.ts).
      expect(statuses).toEqual(['idle', 'busy', 'busy', 'busy', 'busy', 'idle'])
    })

    it('an interrupted turn goes idle and is never kept going', async () => {
      process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'grok-hook-'))
      const inbox = new Inbox()
      const statuses: string[] = []
      const server = await serveHookSocket(hookSocketPath(process.ppid), new HookChannel(inbox, s => statuses.push(s)))
      closers.push(() => server.close())
      const out: string[] = []
      inbox.push({ content: 'hi', meta: { from: 'lead [abc123]' } })
      await runGrokHook(['UserPromptSubmit'], { stdin: async () => '{}', write: s => out.push(s), ppid: process.pid })
      await runGrokHook(['StopCancelled'], { stdin: async () => '{"reason":"user_interrupt"}', write: s => out.push(s), ppid: process.pid })
      expect(out).toEqual(['{}\n', '{}\n'])
      expect(statuses).toEqual(['busy', 'idle'])
    })

    it('prints {} and exits 0 when there is no peer, the event is unknown, or stdin is not JSON', async () => {
      process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'grok-hook-'))
      const out: string[] = []
      for (const [event, raw] of [['PostToolUse', '{}'], ['Stop', 'not json'], ['SessionStart', '{}'], ['', '']] as const) {
        expect(await runGrokHook(event ? [event] : [], { stdin: async () => raw, write: s => out.push(s), ppid: 1 })).toBe(0)
      }
      expect(out).toEqual(['{}\n', '{}\n', '{}\n', '{}\n'])
      expect(existsSync(join(process.env.MESH_HOME, 'hooks'))).toBe(false)
    })
  })
})
