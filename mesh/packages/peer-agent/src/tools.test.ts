import { describe, it, expect, vi } from 'vitest'
import { registerTools, TOOL_DESCRIPTORS } from './tools.ts'
import { ReplyLimiter } from './reply-limiter.ts'
import type { RelayClient } from './outbound.ts'
import type { SessionRow } from './resolve-target.ts'

const SELF = 's_01hrk7y0000000000000self01'
const row = (session_id: string, name: string, account = 'bob', ref = session_id.slice(-6)): SessionRow => ({
  session_id, ref, name, account, device: 'msi', status: 'idle', last_seen: '2026-10-13T00:00:00.000Z',
})
const ROWS = [
  row(SELF, 'opensource-1c', 'alice'),
  row('s_01hrk7y0000000000000aaaaaa', 'repo-x'),
  row('s_01hrk7y0000000000000bbbbbb', 'dup'),
  row('s_01hrk7y0000000000000cccccc', 'dup', 'carol'),
]

function fakeClient(rows = ROWS) {
  const send = vi.fn(async (m: { to: string }) => ({
    id: 'msg_01HRK7Y000000000000000000A', delivered_at: '2026-10-13T00:00:00.000Z', to: m.to,
  }))
  return { send, listSessions: vi.fn(async () => rows) } as unknown as RelayClient & { send: typeof send }
}

describe('tools', () => {
  it('advertises exactly list_agents and send_message', () => {
    expect(TOOL_DESCRIPTORS.map(t => t.name)).toEqual(['list_agents', 'send_message'])
  })

  it('rejects the legacy tool names', async () => {
    const { callTool } = registerTools(fakeClient(), { selfSessionId: SELF })
    for (const legacy of ['send_to_peer', 'list_peers', 'set_summary', 'respond_to_permission']) {
      await expect(callTool(legacy, {})).rejects.toThrow('unknown tool')
    }
  })

  it('list_agents shows the reported claude.ai login next to the mesh identity', async () => {
    const rows = [{ ...row('s_01hrk7y0000000000000login1', 'gm'), login: 'x@gmail.com' }]
    const { callTool } = registerTools(fakeClient(rows), { selfSessionId: SELF })
    expect((await callTool('list_agents', {})).content[0]!.text).toContain('gm [login1] — x@gmail.com (mesh bob@msi) · idle')
  })

  it('list_agents renders native-style rows and marks this session', async () => {
    const { callTool } = registerTools(fakeClient(), { selfSessionId: SELF })
    const text = (await callTool('list_agents', {})).content[0]!.text
    expect(text).toContain('opensource-1c [self01] (this session) — alice@msi · idle')
    expect(text).toContain('repo-x [aaaaaa] — bob@msi · idle')
  })

  it('send_message addresses the resolved session and its account', async () => {
    const client = fakeClient()
    const { callTool } = registerTools(client, { selfSessionId: SELF })
    const res = await callTool('send_message', { to: 'repo-x', message: 'tests are red on main' })
    expect(client.send).toHaveBeenCalledWith({
      to: 'bob', to_session: 's_01hrk7y0000000000000aaaaaa', kind: 'chat', content: 'tests are red on main', meta: {},
    })
    expect(res.content[0]!.text).toContain('delivered to repo-x [aaaaaa]')
  })

  it('send_message accepts "name [ref]" to pick between duplicates and refuses the bare duplicate name', async () => {
    const client = fakeClient()
    const { callTool } = registerTools(client, { selfSessionId: SELF })
    await expect(callTool('send_message', { to: 'dup', message: 'x' })).rejects.toThrow('matches 2 sessions')
    await callTool('send_message', { to: 'dup [cccccc]', message: 'x' })
    expect(client.send).toHaveBeenCalledWith(expect.objectContaining({ to: 'carol', to_session: 's_01hrk7y0000000000000cccccc' }))
  })

  it('send_message never sends to this session and does not let meta through', async () => {
    const client = fakeClient()
    const { callTool } = registerTools(client, { selfSessionId: SELF })
    await expect(callTool('send_message', { to: 'opensource-1c', message: 'x' })).rejects.toThrow('is this session')
    await expect(callTool('send_message', { to: 'repo-x', message: 'x', meta: { from: 'x' } })).rejects.toThrow()
    expect(client.send).not.toHaveBeenCalled()
  })

  it('loop guard: after an inbound message, at most 2 quick replies to that sender', async () => {
    const limiter = new ReplyLimiter({ windowMs: 10_000, maxReplies: 2 })
    limiter.recordInbound('repo-x [aaaaaa]')
    const client = fakeClient()
    const { callTool } = registerTools(client, { selfSessionId: SELF, replyLimiter: limiter })
    await callTool('send_message', { to: 'repo-x', message: '1' })
    await callTool('send_message', { to: 'repo-x', message: '2' })
    await expect(callTool('send_message', { to: 'repo-x', message: '3' })).rejects.toThrow('loop guard')
    expect(client.send).toHaveBeenCalledTimes(2)
  })
})
