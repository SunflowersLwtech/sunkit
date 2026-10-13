import { describe, it, expect, beforeEach } from 'vitest'
import { InboundDispatcher } from './inbound.ts'
import { SenderGate } from './gate.ts'
import type { Envelope } from '@claude-mesh/shared'

const envelope = (overrides: Partial<Envelope> = {}): Envelope => ({
  id: 'msg_01HRK7Y0000000000000000000', v: 1, team: 't1',
  from: 'alice', to: 'bob', in_reply_to: null, thread_root: null,
  kind: 'chat', content: 'hi', meta: {},
  sent_at: '2026-04-17T00:00:00.000Z', delivered_at: null,
  from_session: null, from_name: null, to_session: null,
  ...overrides
})

describe('InboundDispatcher', () => {
  let sent: { method: string; params: Record<string, unknown> }[]
  let d: InboundDispatcher
  beforeEach(() => {
    sent = []
    d = new InboundDispatcher({
      gate: new SenderGate(['alice','bob']),
      emit: n => { sent.push(n) },
      setCursor: () => { /* no-op */ },
    })
  })

  it('emits a claude/channel notification for a chat from known peer', () => {
    d.handle(envelope())
    expect(sent).toHaveLength(1)
    expect(sent[0]!.method).toBe('notifications/claude/channel')
  })

  it('drops messages from unknown peers', () => {
    d.handle(envelope({ from: 'mallory' }))
    expect(sent).toHaveLength(0)
  })

  it('records gated inbound chats as DM partners for approval routing', () => {
    const recorded: string[] = []
    d = new InboundDispatcher({
      gate: new SenderGate(['alice']),
      emit: () => { /* no-op */ },
      setCursor: () => { /* no-op */ },
      recordDm: h => { recorded.push(h) },
    })
    d.handle(envelope({ from: 'alice', kind: 'chat' }))
    d.handle(envelope({ from: 'mallory', kind: 'chat' }))      // gated: not recorded
    d.handle(envelope({ from: 'alice', kind: 'presence_update' })) // not a chat: not recorded
    expect(recorded).toEqual(['alice'])
  })

  it('maps kind=permission_request to correct method', () => {
    d.handle(envelope({
      kind: 'permission_request',
      meta: { request_id: 'abcde', tool_name: 'Bash', input_preview: 'ls', requester: 'alice' }
    }))
    expect(sent[0]!.method).toBe('notifications/claude/channel/permission_request')
  })

  it('maps kind=permission_verdict to correct method', () => {
    d.handle(envelope({
      kind: 'permission_verdict',
      in_reply_to: 'msg_01HRK7Y0000000000000000001',
      meta: { request_id: 'abcde', behavior: 'allow' }
    }))
    expect(sent[0]!.method).toBe('notifications/claude/channel/permission')
  })

  it('updates cursor on each accepted message', () => {
    const cursors: string[] = []
    const d2 = new InboundDispatcher({
      gate: new SenderGate(['alice']),
      emit: () => { /* no-op */ },
      setCursor: id => cursors.push(id),
    })
    d2.handle(envelope({ id: 'msg_01HRK7Y0000000000000000001' }))
    d2.handle(envelope({ id: 'msg_01HRK7Y0000000000000000002', from: 'alice' }))
    expect(cursors[cursors.length - 1]).toBe('msg_01HRK7Y0000000000000000002')
  })

  it('still advances cursor when emit throws (error is logged, not propagated)', () => {
    const cursors: string[] = []
    const d3 = new InboundDispatcher({
      gate: new SenderGate(['alice']),
      emit: () => { throw new Error('mcp server detached') },
      setCursor: id => cursors.push(id),
    })
    // Should not throw — handle swallows the emit error after logging it.
    expect(() => d3.handle(envelope({ id: 'msg_01HRK7Y0000000000000000099' }))).not.toThrow()
    expect(cursors).toEqual(['msg_01HRK7Y0000000000000000099'])
  })

  it('tolerates non-Error thrown from emit (String coercion branch)', () => {
    const d4 = new InboundDispatcher({
      gate: new SenderGate(['alice']),
      // eslint-disable-next-line @typescript-eslint/no-throw-literal
      emit: () => { throw 'string reason' },
      setCursor: () => { /* no-op */ },
    })
    expect(() => d4.handle(envelope())).not.toThrow()
  })

  describe('session mode (chatOnly + sessionId)', () => {
    const ME = 's_01hrk7y0000000000000mine01'
    let out: { method: string; params: Record<string, unknown> }[]
    let cursor: string | undefined
    let sd: InboundDispatcher
    beforeEach(() => {
      out = []; cursor = undefined
      sd = new InboundDispatcher({
        gate: new SenderGate(['alice']), sessionId: ME, chatOnly: true,
        emit: n => { out.push(n) }, setCursor: id => { cursor = id },
      })
    })

    it('surfaces chat addressed to this session or to the account', () => {
      sd.handle(envelope({ to_session: ME }))
      sd.handle(envelope({ id: 'msg_01HRK7Y0000000000000000001' }))
      expect(out).toHaveLength(2)
    })

    it('drops chat addressed to a sibling session but still advances the cursor', () => {
      sd.handle(envelope({ to_session: 's_01hrk7y0000000000000other1' }))
      expect(out).toHaveLength(0)
      expect(cursor).toBe('msg_01HRK7Y0000000000000000000')
    })

    it('never surfaces presence or permission traffic', () => {
      for (const kind of ['presence_update', 'permission_request'] as const) sd.handle(envelope({ kind }))
      sd.handle(envelope({ kind: 'permission_verdict', in_reply_to: 'msg_01HRK7Y0000000000000000009' }))
      expect(out).toHaveLength(0)
    })
  })
})
