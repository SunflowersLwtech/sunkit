import { describe, it, expect, afterEach } from 'vitest'
import { mkdtempSync, readFileSync, readdirSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { agyAddArgs, agyHookEntry, agyHookOutput, hookRequest, mergeHooks, runAgyHook, runAgyInstall, sessionRules } from './agy.ts'
import { HookChannel, hookSocketPath, serveHookSocket } from '../hook-socket.ts'
import { Inbox } from '../inbox.ts'
import { IdleWaker, herdrWaker } from '../wake.ts'

const opts = { node: '/opt/homebrew/bin/node', peer: '/k/mesh-peer.mjs', cli: '/k/mesh cli.mjs', name: 'mesh', hooks: '/x/hooks.json' }

describe('mesh agy install', () => {
  it('adds the peer in pull mode as host agy, without a session name in the config', () => {
    expect(agyAddArgs(opts)).toEqual(['mcp', 'add', '-e', 'MESH_JOIN=pull', '-e', 'MESH_HOST=agy', 'mesh', '--', '/opt/homebrew/bin/node', '/k/mesh-peer.mjs'])
    expect(agyAddArgs(opts).join(' ')).not.toContain('MESH_SESSION_NAME')
  })

  it('hooks run the bundled CLI with the same node, quoted for sh -c', () => {
    expect(agyHookEntry(opts)).toEqual({
      SessionStart: [{ type: 'command', command: "/opt/homebrew/bin/node '/k/mesh cli.mjs' agy hook SessionStart", timeout: 5 }],
      PreInvocation: [{ type: 'command', command: "/opt/homebrew/bin/node '/k/mesh cli.mjs' agy hook PreInvocation", timeout: 5 }],
      Stop: [{ type: 'command', command: "/opt/homebrew/bin/node '/k/mesh cli.mjs' agy hook Stop", timeout: 5 }],
    })
  })

  it('merging keeps every other named hook (Herdr) and replaces only ours', () => {
    const herdr = { herdr: { PreInvocation: [{ command: 'bash herdr.sh session', timeout: 10, type: 'command' }] } }
    const once = JSON.parse(mergeHooks('﻿' + JSON.stringify(herdr), 'mesh', { Stop: [] }))
    expect(once).toEqual({ ...herdr, mesh: { Stop: [] } })
    expect(JSON.parse(mergeHooks(JSON.stringify(once), 'mesh', { PreInvocation: [] }))).toEqual({ ...herdr, mesh: { PreInvocation: [] } })
    expect(JSON.parse(mergeHooks(undefined, 'mesh', {}))).toEqual({ mesh: {} })
    expect(JSON.parse(mergeHooks('  ', 'mesh', {}))).toEqual({ mesh: {} })
    expect(() => mergeHooks('[1]', 'mesh', {})).toThrow(/not a JSON object/)
    expect(() => mergeHooks('{bad', 'mesh', {})).toThrow()
  })

  it('--write runs agy mcp add and writes hooks.json with a backup; without it nothing is touched', () => {
    const dir = mkdtempSync(join(tmpdir(), 'agy-inst-'))
    const hooks = join(dir, 'hooks.json')
    writeFileSync(hooks, JSON.stringify({ herdr: { PreInvocation: [] } }))
    const runs: string[][] = []
    const run = (file: string, argv: string[]) => { runs.push([file, ...argv]) }
    const args = ['--hooks', hooks, '--node', '/n/node', '--peer', '/p/mesh-peer.mjs', '--cli', '/p/mesh-cli.mjs']
    runAgyInstall(args, { log: () => {}, run })
    expect(runs).toEqual([])
    expect(JSON.parse(readFileSync(hooks, 'utf8'))).toEqual({ herdr: { PreInvocation: [] } })

    runAgyInstall([...args, '--write'], { log: () => {}, run })
    expect(runs).toEqual([['agy', 'mcp', 'add', '-e', 'MESH_JOIN=pull', '-e', 'MESH_HOST=agy', 'mesh', '--', '/n/node', '/p/mesh-peer.mjs']])
    const written = JSON.parse(readFileSync(hooks, 'utf8'))
    expect(Object.keys(written)).toEqual(['herdr', 'mesh'])
    expect(written.mesh.Stop[0].command).toBe('/n/node /p/mesh-cli.mjs agy hook Stop')
    const backups = readdirSync(dir).filter(f => f.startsWith('hooks.json.bak-mesh-'))
    expect(backups).toHaveLength(1)
    expect(JSON.parse(readFileSync(join(dir, backups[0]!), 'utf8'))).toEqual({ herdr: { PreInvocation: [] } })

    // Running it again changes nothing and leaves no second backup.
    runAgyInstall([...args, '--write'], { log: () => {}, run })
    expect(readdirSync(dir).filter(f => f.startsWith('hooks.json.bak-mesh-'))).toHaveLength(1)
  })

  it('--write creates hooks.json when there is none', () => {
    const dir = mkdtempSync(join(tmpdir(), 'agy-inst-'))
    const hooks = join(dir, 'config', 'hooks.json')
    runAgyInstall(['--hooks', hooks, '--write'], { log: () => {}, run: () => {} })
    expect(Object.keys(JSON.parse(readFileSync(hooks, 'utf8')))).toEqual(['mesh'])
  })
})

describe('mesh agy hook', () => {
  it('session rules come from AGY_SESSION_RULES_B64, else AGY_SESSION_RULES_FILE, trimmed and capped', () => {
    const b64 = (t: string) => Buffer.from(t, 'utf8').toString('base64')
    expect(sessionRules({ AGY_SESSION_RULES_B64: b64('  汇报给「秘书」\n第二条 \'x\'  ') })).toBe('汇报给「秘书」\n第二条 \'x\'')
    const dir = mkdtempSync(join(tmpdir(), 'agy-rules-'))
    writeFileSync(join(dir, 'r.txt'), 'from file\n')
    expect(sessionRules({ AGY_SESSION_RULES_FILE: join(dir, 'r.txt') })).toBe('from file')
    expect(sessionRules({ AGY_SESSION_RULES_B64: b64('b64 wins'), AGY_SESSION_RULES_FILE: join(dir, 'r.txt') })).toBe('b64 wins')
    expect(sessionRules({ AGY_SESSION_RULES_FILE: join(dir, 'missing.txt') })).toBe('')
    expect(sessionRules({})).toBe('')
    expect(sessionRules({ AGY_SESSION_RULES_B64: b64('x'.repeat(30_000)) })).toHaveLength(20_000)
  })

  it('SessionStart injects the rules as a system message, or nothing', async () => {
    const saved = process.env.AGY_SESSION_RULES_B64
    try {
      const out: string[] = []
      const run = () => runAgyHook(['SessionStart'], { stdin: async () => '{"conversationId":"c"}', write: s => out.push(s), ppid: 1 })
      delete process.env.AGY_SESSION_RULES_B64
      await run()
      process.env.AGY_SESSION_RULES_B64 = Buffer.from('每条消息末行写「— ok」', 'utf8').toString('base64')
      await run()
      expect(out).toEqual(['{}\n', JSON.stringify({ injectSteps: [{ systemMessage: { systemMessage: '每条消息末行写「— ok」' } }] }) + '\n'])
    } finally {
      if (saved === undefined) delete process.env.AGY_SESSION_RULES_B64; else process.env.AGY_SESSION_RULES_B64 = saved
    }
  })

  it('maps agy events to requests', () => {
    expect(hookRequest('PreInvocation', {})).toEqual({ op: 'turn' })
    expect(hookRequest('Stop', { terminationReason: 'NO_TOOL_CALL' })).toEqual({ op: 'stop', reason: 'NO_TOOL_CALL' })
    expect(hookRequest('Stop', undefined)).toEqual({ op: 'stop' })
    expect(hookRequest('SessionStart', {})).toBeUndefined()
  })

  it('injects a notice before a model call only when something is unread, naming senders, never content', () => {
    expect(agyHookOutput('PreInvocation', undefined)).toEqual({})
    expect(agyHookOutput('PreInvocation', { unread: 0, from: [] })).toEqual({})
    expect(agyHookOutput('PreInvocation', { unread: 1, from: ['lead [abc123]'] })).toEqual({
      injectSteps: [{ ephemeralMessage: '[mesh] 1 unread message from lead [abc123] is waiting. Call the mesh read_messages tool to read it.' }],
    })
    expect(JSON.stringify(agyHookOutput('PreInvocation', { unread: 2, from: ['a [1]', 'b [2]'] }))).toContain('2 unread messages from a [1], b [2] are waiting')
  })

  it('keeps the agent going at a stop only when the peer says so', () => {
    expect(agyHookOutput('Stop', { unread: 1, from: ['lead [abc123]'], continue: false })).toEqual({})
    const out = agyHookOutput('Stop', { unread: 1, from: ['lead [abc123]'], continue: true })
    expect(out.decision).toBe('continue')
    expect(out.reason).toMatch(/^\[mesh\] 1 message from lead \[abc123\] arrived and is still unread/)
    expect(agyHookOutput('PreInvocation', { unread: 1, from: ['x'], continue: true })).not.toHaveProperty('decision')
  })

  describe('against a running peer', () => {
    const saved = process.env.MESH_HOME
    const closers: Array<() => void> = []
    afterEach(() => {
      for (const c of closers.splice(0)) c()
      if (saved === undefined) delete process.env.MESH_HOME; else process.env.MESH_HOME = saved
    })

    it('finds the peer by its host pid, falling back to the grandparent when sh did not exec', async () => {
      process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'agy-hook-'))
      const inbox = new Inbox()
      const statuses: string[] = []
      // The host is our parent; the hook is asked as if it ran under an intermediate shell (us).
      const server = await serveHookSocket(hookSocketPath(process.ppid), new HookChannel(inbox, s => statuses.push(s)))
      closers.push(() => server.close())
      const out: string[] = []
      const hook = (event: string, payload: object) => runAgyHook([event], { stdin: async () => JSON.stringify(payload), write: s => out.push(s), ppid: process.pid })

      expect(await hook('PreInvocation', { invocationNum: 0 })).toBe(0)
      expect(out.pop()).toBe('{}\n')
      inbox.push({ content: 'hi', meta: { from: 'lead [abc123]' } })
      await hook('PreInvocation', { invocationNum: 1 })
      expect(JSON.parse(out.pop()!).injectSteps[0].ephemeralMessage).toContain('from lead [abc123]')
      await hook('Stop', { terminationReason: 'NO_TOOL_CALL' })
      expect(JSON.parse(out.pop()!).decision).toBe('continue')
      await hook('Stop', { terminationReason: 'NO_TOOL_CALL' })
      expect(out.pop()).toBe('{}\n')
      expect(statuses).toEqual(['busy', 'busy', 'idle'])
    })

    it('prints {} and exits 0 when there is no peer, the event is unknown, or stdin is not JSON', async () => {
      process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'agy-hook-'))
      const out: string[] = []
      for (const [event, raw] of [['PreInvocation', '{}'], ['Stop', 'not json'], ['SessionStart', '{}'], ['', '']] as const) {
        expect(await runAgyHook(event ? [event] : [], { stdin: async () => raw, write: s => out.push(s), ppid: 1 })).toBe(0)
      }
      expect(out).toEqual(['{}\n', '{}\n', '{}\n', '{}\n'])
      expect(existsSync(join(process.env.MESH_HOME, 'hooks'))).toBe(false)
    })
  })
})

describe('idle waker', () => {
  it('wakes an idle session once per interval, naming senders but never the message', () => {
    let t = 1_000_000
    const sent: string[] = []
    const w = new IdleWaker({ send: s => sent.push(s), minIntervalMs: 20_000, now: () => t })
    expect(w.maybeWake('busy', { size: 1, from: ['lead [abc123]'] })).toBe(false)
    expect(w.maybeWake('unknown', { size: 1, from: ['lead [abc123]'] })).toBe(false)
    expect(w.maybeWake(undefined, { size: 1, from: ['lead [abc123]'] })).toBe(false)
    expect(w.maybeWake('idle', { size: 0, from: [] })).toBe(false)
    expect(w.maybeWake('idle', { size: 1, from: ['lead [abc123]'] })).toBe(true)
    t += 5_000
    expect(w.maybeWake('idle', { size: 2, from: ['lead [abc123]'] })).toBe(false)
    t += 20_000
    expect(w.maybeWake('idle', { size: 2, from: ['lead [abc123]', 'ops [d]'] })).toBe(true)
    expect(sent).toEqual([
      '[mesh] 1 new message from lead [abc123]. Call the mesh read_messages tool to read it.',
      '[mesh] 2 new messages from lead [abc123], ops [d]. Call the mesh read_messages tool to read them.',
    ])
  })

  it('is only built for MESH_WAKE=herdr inside a Herdr pane, and prompts that pane', () => {
    const starts: string[][] = []
    const start = (file: string, args: string[]) => { starts.push([file, ...args]) }
    expect(herdrWaker({ HERDR_ENV: '1', HERDR_PANE_ID: 'w1:p2' }, start)).toBeUndefined()
    expect(herdrWaker({ MESH_WAKE: 'herdr', HERDR_PANE_ID: 'w1:p2' }, start)).toBeUndefined()
    expect(herdrWaker({ MESH_WAKE: 'herdr', HERDR_ENV: '1' }, start)).toBeUndefined()
    const w = herdrWaker({ MESH_WAKE: 'herdr', HERDR_ENV: '1', HERDR_PANE_ID: 'w1:p2', HERDR_BIN_PATH: '/b/herdr' }, start)!
    w.maybeWake('idle', { size: 1, from: ['lead [abc123]'] })
    expect(starts).toEqual([['/b/herdr', 'agent', 'prompt', 'w1:p2', '[mesh] 1 new message from lead [abc123]. Call the mesh read_messages tool to read it.']])
  })
})
