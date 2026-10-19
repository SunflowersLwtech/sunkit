import { describe, it, expect, afterEach } from 'vitest'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Inbox } from './inbox.ts'
import { HookChannel, hookSocketPath, serveHookSocket } from './hook-socket.ts'
import { PULL_INSTRUCTIONS } from './instructions.ts'
import { createMeshExtension, joinsMesh, piInstructions, serverConfig } from './pi-extension.ts'

type Handler = (event: any, ctx: any) => unknown

/** Just enough of pi's ExtensionAPI to drive the extension's handlers in order. */
function fakePi(sessionName?: string) {
  const handlers = new Map<string, Handler[]>()
  const servers: Array<{ name: string; config: any }> = []
  const sent: string[] = []
  const pi = {
    on: (event: string, h: Handler) => { handlers.set(event, [...(handlers.get(event) ?? []), h]) },
    registerMcpServer: (name: string, config: any) => { servers.push({ name, config }) },
    sendUserMessage: (text: string) => { sent.push(text) },
    getSessionName: () => sessionName,
  }
  const emit = async (event: string, payload: any = {}, ctx: any = { mode: 'tui', isIdle: () => true }) => {
    let last: unknown
    for (const h of handlers.get(event) ?? []) last = await h(payload, ctx)
    return last as any
  }
  return { pi, emit, servers, sent }
}

const msg = (from: string) => ({ content: 'hi', meta: { from, account: 'alice', msg_id: 'm', source: 'peers' } })

describe('pi extension, pure parts', () => {
  it('interactive and RPC sessions join; print and JSON runs, and MESH_JOIN=never, only send', () => {
    expect(joinsMesh('tui', {})).toBe(true)
    expect(joinsMesh('rpc', {})).toBe(true)
    expect(joinsMesh('print', {})).toBe(false)
    expect(joinsMesh('json', {})).toBe(false)
    expect(joinsMesh('tui', { MESH_JOIN: 'never' })).toBe(false)
  })

  it('registers the peer as a direct MCP server in pull mode, without the peer\'s own Herdr waker', () => {
    const c = serverConfig({ node: '/n', peer: '/p/mesh-peer.mjs', pull: true, sessionName: 'pi-smoke' })
    expect(c).toMatchObject({ command: '/n', args: ['/p/mesh-peer.mjs'], exposure: 'direct' })
    expect(c.env).toEqual({ MESH_JOIN: 'pull', MESH_HOST: 'pi', MESH_WAKE: '', MESH_SESSION_NAME: 'pi-smoke' })
    // No name: leave MESH_SESSION_NAME alone, so the peer falls back to pi-<Herdr tab> / pi-<dir>.
    expect(serverConfig({ node: '/n', peer: '/p', pull: false }).env).toEqual({ MESH_JOIN: 'never', MESH_HOST: 'pi', MESH_WAKE: '' })
  })

  it('carries the peer\'s safety rules unchanged, naming pi\'s tool names', () => {
    const text = piInstructions()
    expect(text).toContain(PULL_INSTRUCTIONS)
    expect(text).toContain('mcp__mesh__read_messages')
  })
})

describe('pi extension against a running peer', () => {
  const saved = process.env.MESH_HOME
  const closers: Array<() => void> = []
  afterEach(() => {
    for (const c of closers.splice(0)) c()
    if (saved === undefined) delete process.env.MESH_HOME; else process.env.MESH_HOME = saved
  })
  const peer = async () => {
    process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'pi-ext-'))
    const inbox = new Inbox()
    const statuses: string[] = []
    // The extension runs inside pi and pi spawns the peer, so the peer listens under pi's pid: here, ours.
    const server = await serveHookSocket(hookSocketPath(process.pid), new HookChannel(inbox, s => statuses.push(s)))
    closers.push(() => server.close())
    return { inbox, statuses }
  }

  it('names the session, reports idle, busy while working, notices mail on a tool result once, and keeps a completed run going once', async () => {
    const { inbox, statuses } = await peer()
    const f = fakePi('pi-smoke')
    createMeshExtension({ node: '/n', peer: '/p', env: {} })(f.pi)
    await f.emit('session_start', { reason: 'startup' })
    expect(f.servers).toEqual([{ name: 'mesh', config: expect.objectContaining({ env: expect.objectContaining({ MESH_SESSION_NAME: 'pi-smoke', MESH_JOIN: 'pull' }) }) }])
    await new Promise(r => setTimeout(r, 50))

    const start = { systemPromptOptions: { sections: { other: 'x' } as Record<string, string> } }
    await f.emit('before_agent_start', start)
    expect(start.systemPromptOptions.sections.other).toBe('x')
    expect(start.systemPromptOptions.sections.mesh).toBe(piInstructions())
    await f.emit('agent_start')
    await new Promise(r => setTimeout(r, 50))

    const result = { content: [{ type: 'text', text: 'file contents' }] }
    expect(await f.emit('tool_result', result)).toBeUndefined()
    inbox.push(msg('lead [abc123]'))
    const changed = await f.emit('tool_result', result)
    expect(changed.content).toHaveLength(2)
    expect(changed.content[0]).toEqual({ type: 'text', text: 'file contents' })
    expect(changed.content[1].text).toMatch(/^\[mesh\] 1 unread message from lead \[abc123\] is waiting\. Call mcp__mesh__read_messages/)
    expect(await f.emit('tool_result', result)).toBeUndefined()

    const settle = { entries: [{ type: 'custom', customType: 'other' }], outcome: 'completed', context: { canContinue: true } }
    const kept = await f.emit('agent_before_settle', settle)
    expect(kept.continue).toBe(true)
    expect(kept.entries[0]).toEqual({ type: 'custom', customType: 'other' })
    expect(kept.entries[1]).toMatchObject({ type: 'custom_message', customType: 'mesh', display: true })
    expect(kept.entries[1].content).toContain('mcp__mesh__read_messages')
    // Same message, the continued run ends again without reading it: let it settle.
    expect(await f.emit('agent_before_settle', settle)).toBeUndefined()
    await f.emit('agent_settled', { aborted: false })
    await new Promise(r => setTimeout(r, 50))
    expect(statuses).toEqual(['idle', 'busy', 'busy', 'busy', 'busy', 'idle', 'idle'])
    expect(f.sent).toEqual([])
  })

  it('never keeps going a run the user aborted or that failed', async () => {
    const { inbox } = await peer()
    const f = fakePi()
    createMeshExtension({ node: '/n', peer: '/p', env: {} })(f.pi)
    await f.emit('session_start')
    await f.emit('agent_start')
    inbox.push(msg('lead [abc123]'))
    for (const outcome of ['aborted', 'error']) {
      expect(await f.emit('agent_before_settle', { entries: [], outcome, context: { canContinue: true } })).toBeUndefined()
    }
  })

  it('with MESH_WAKE set, an idle session starts a turn once per arrival, and a busy one is left to its tool notices', async () => {
    const { inbox } = await peer()
    const f = fakePi('pi-wake')
    let idle = true
    const ctx = { mode: 'tui', isIdle: () => idle }
    createMeshExtension({ node: '/n', peer: '/p', env: { MESH_WAKE: 'herdr' }, pollMs: 20 })(f.pi)
    await f.emit('session_start', {}, ctx)
    await new Promise(r => setTimeout(r, 80))
    expect(f.sent).toEqual([])
    inbox.push(msg('lead [abc123]'))
    await new Promise(r => setTimeout(r, 120))
    expect(f.sent).toHaveLength(1)
    expect(f.sent[0]).toMatch(/^\[mesh\] 1 new message from lead \[abc123\]\. Call mcp__mesh__read_messages/)
    // Busy: no wake, however much arrives.
    idle = false
    await f.emit('agent_start', {}, ctx)
    inbox.push(msg('ops [def456]'))
    await new Promise(r => setTimeout(r, 120))
    expect(f.sent).toHaveLength(1)
    // Polling must not run while busy: it would report the session idle and use up the nudge
    // this arrival is owed when the run ends.
    const kept = await f.emit('agent_before_settle', { entries: [], outcome: 'completed', context: { canContinue: true } }, ctx)
    expect(kept?.continue).toBe(true)
    await f.emit('session_shutdown', { reason: 'quit' }, ctx)
  })

  it('a print run registers the server send-only and touches nothing else', async () => {
    const { inbox, statuses } = await peer()
    const f = fakePi('pi-print')
    createMeshExtension({ node: '/n', peer: '/p', env: { MESH_WAKE: 'herdr' }, pollMs: 20 })(f.pi)
    const ctx = { mode: 'print', isIdle: () => true }
    await f.emit('session_start', {}, ctx)
    expect(f.servers[0]!.config.env.MESH_JOIN).toBe('never')
    inbox.push(msg('lead [abc123]'))
    const start = { systemPromptOptions: { sections: {} as Record<string, string> } }
    await f.emit('before_agent_start', start, ctx)
    await f.emit('agent_start', {}, ctx)
    expect(await f.emit('tool_result', { content: [] }, ctx)).toBeUndefined()
    await new Promise(r => setTimeout(r, 80))
    expect(start.systemPromptOptions.sections).toEqual({})
    expect(statuses).toEqual([])
    expect(f.sent).toEqual([])
  })

  it('stays quiet with no peer listening', async () => {
    process.env.MESH_HOME = mkdtempSync(join(tmpdir(), 'pi-ext-'))
    const f = fakePi()
    createMeshExtension({ node: '/n', peer: '/p', env: {} })(f.pi)
    await f.emit('session_start')
    await f.emit('agent_start')
    expect(await f.emit('tool_result', { content: [{ type: 'text', text: 'x' }] })).toBeUndefined()
    expect(await f.emit('agent_before_settle', { entries: [], outcome: 'completed' })).toBeUndefined()
    await f.emit('session_shutdown')
  })
})
