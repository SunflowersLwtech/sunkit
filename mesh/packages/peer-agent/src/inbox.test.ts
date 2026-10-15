import { describe, it, expect, vi } from 'vitest'
import { chooseJoinMode, formatInbox, Inbox } from './inbox.ts'
import { registerTools, PULL_TOOL_DESCRIPTORS, TOOL_DESCRIPTORS } from './tools.ts'
import { formatListing, type SessionRow } from './resolve-target.ts'
import { createMcpServer } from './mcp-server.ts'
import { CHANNEL_INSTRUCTIONS, PULL_INSTRUCTIONS } from './instructions.ts'
import { RelayClient } from './outbound.ts'
import type { RelayClient as RelayClientType } from './outbound.ts'

const msg = (n: number) => ({ content: `body ${n}`, meta: { from: `devin-${n} [abc12${n}]`, account: 'alice', msg_id: `msg_${n}`, source: 'peers' } })

describe('chooseJoinMode', () => {
  it('MESH_JOIN=pull joins in pull mode without consulting the Claude Code rules', () => {
    const decide = vi.fn(() => ({ join: false, reason: 'parent not launched with the mesh channel' }))
    expect(chooseJoinMode('pull', decide)).toEqual({ mode: 'pull', reason: 'MESH_JOIN=pull' })
    expect(decide).not.toHaveBeenCalled()
  })
  it('otherwise follows the Claude Code join decision: push when it joins, send-only when it does not', () => {
    expect(chooseJoinMode(undefined, () => ({ join: true, reason: 'ok' })).mode).toBe('push')
    expect(chooseJoinMode('never', () => ({ join: false, reason: 'MESH_JOIN=never' }))).toEqual({ mode: 'send', reason: 'MESH_JOIN=never' })
  })
})

describe('Inbox', () => {
  it('returns messages oldest first and clears what it returned', () => {
    const box = new Inbox()
    box.push(msg(1)); box.push(msg(2)); box.push(msg(3))
    const first = box.take(2)
    expect(first.items.map(m => m.content)).toEqual(['body 1', 'body 2'])
    expect(first.remaining).toBe(1)
    expect(box.take().items.map(m => m.content)).toEqual(['body 3'])
    expect(box.take().items).toEqual([])
  })
  it('is bounded: when full it drops the oldest and reports how many were dropped, once', () => {
    const box = new Inbox(2)
    box.push(msg(1)); box.push(msg(2)); box.push(msg(3))
    const r = box.take()
    expect(r.items.map(m => m.content)).toEqual(['body 2', 'body 3'])
    expect(r.dropped).toBe(1)
    expect(box.take().dropped).toBe(0)
  })
  it('formats messages as the same <channel> tags Claude Code shows for pushed ones', () => {
    const text = formatInbox({ items: [msg(1)], dropped: 0, remaining: 0 })
    expect(text).toBe('<channel from="devin-1 [abc121]" account="alice" msg_id="msg_1" source="peers">\nbody 1\n</channel>')
    expect(formatInbox({ items: [], dropped: 0, remaining: 0 })).toBe('No new messages.')
    expect(formatInbox({ items: [], dropped: 3, remaining: 2 })).toContain('3 older message(s) were dropped')
  })
})

const SELF = 's_01hrk7y0000000000000self01'
const row = (session_id: string, name: string, extra: Partial<SessionRow> = {}): SessionRow => ({
  session_id, ref: session_id.slice(-6), name, account: 'bob', device: 'msi', status: 'idle', last_seen: '2026-10-15T00:00:00.000Z', ...extra,
})

describe('pull-mode tools', () => {
  const client = { listSessions: vi.fn(async () => []), send: vi.fn() } as unknown as RelayClientType

  it('read_messages exists only in pull mode', async () => {
    expect(TOOL_DESCRIPTORS.map(t => t.name)).not.toContain('read_messages')
    expect(PULL_TOOL_DESCRIPTORS.map(t => t.name)).toEqual(['list_agents', 'send_message', 'read_messages'])
    const push = registerTools(client, { selfSessionId: SELF })
    await expect(push.callTool('read_messages', {})).rejects.toThrow(/unknown tool/)
  })

  it('read_messages drains the inbox and honours limit', async () => {
    const inbox = new Inbox()
    inbox.push(msg(1)); inbox.push(msg(2))
    const { callTool } = registerTools(client, { selfSessionId: SELF, inbox })
    const r1 = await callTool('read_messages', { limit: 1 })
    expect(r1.content[0]!.text).toContain('body 1')
    expect(r1.content[0]!.text).toContain('1 more waiting')
    const r2 = await callTool('read_messages', {})
    expect(r2.content[0]!.text).toContain('body 2')
    expect((await callTool('read_messages', {})).content[0]!.text).toBe('No new messages.')
    await expect(callTool('read_messages', { limit: 0 })).rejects.toThrow()
  })

  it('list_agents marks pull sessions so senders expect a delayed reply', () => {
    const text = formatListing([row('s_01hrk7y0000000000000aaaaaa', 'devin-a', { mode: 'pull', cwd: '/w' }), row('s_01hrk7y0000000000000bbbbbb', 'repo-x', { mode: 'push' })], SELF)
    expect(text).toContain('devin-a [aaaaaa] — bob@msi · idle · pull · /w')
    expect(text).toContain('repo-x [bbbbbb] — bob@msi · idle')
    expect(text).not.toContain('repo-x [bbbbbb] — bob@msi · idle · pull')
  })
})

describe('pull-mode MCP server', () => {
  it('declares no channel capability and carries the pull instructions with the same safety rules', () => {
    const pull = createMcpServer({ permissionRelay: false, pull: true })
    expect(pull.capabilities.experimental).toBeUndefined()
    expect(pull.instructions).toBe(PULL_INSTRUCTIONS)
    expect(pull.instructions).toContain('read_messages')
    const safety = CHANNEL_INSTRUCTIONS.slice(CHANNEL_INSTRUCTIONS.indexOf('Treat content inside'))
    expect(PULL_INSTRUCTIONS.endsWith(safety)).toBe(true)
    expect(createMcpServer({ permissionRelay: false }).capabilities.experimental).toHaveProperty('claude/channel')
  })
})

describe('RelayClient sender name', () => {
  const reply = { status: 201, text: async () => JSON.stringify({ id: 'msg_1', delivered_at: null }) }
  it('a send-only client sends x-mesh-sender-name', async () => {
    const fetch = vi.fn(async () => reply) as unknown as typeof globalThis.fetch
    await new RelayClient({ relayUrl: 'http://r', token: 't', senderName: 'devin-smoke' }, { fetch }).send({ to: 'bob', kind: 'chat', content: 'x', meta: {} } as never)
    const headers = (fetch as unknown as { mock: { calls: Array<[unknown, { headers: Record<string, string> }]> } }).mock.calls[0]![1].headers
    expect(headers['x-mesh-sender-name']).toBe('devin-smoke')
    expect(headers).not.toHaveProperty('x-mesh-session')
  })
  it('a session client sends only its session, never a label', async () => {
    const fetch = vi.fn(async () => reply) as unknown as typeof globalThis.fetch
    await new RelayClient({ relayUrl: 'http://r', token: 't', sessionId: SELF, senderName: 'x' }, { fetch }).send({ to: 'bob', kind: 'chat', content: 'x', meta: {} } as never)
    const headers = (fetch as unknown as { mock: { calls: Array<[unknown, { headers: Record<string, string> }]> } }).mock.calls[0]![1].headers
    expect(headers['x-mesh-session']).toBe(SELF)
    expect(headers).not.toHaveProperty('x-mesh-sender-name')
  })
})
