import { describe, it, expect, vi } from 'vitest'
import { ApprovalRouter } from './approval-routing.ts'
import {
  relayPermissionRequest,
  PERMISSION_REQUEST_NOTIFICATION_METHOD,
} from './permission-outbound.ts'
import type { Envelope, OutboundMessage } from '@claude-mesh/shared'

const NOW = new Date('2026-04-18T00:00:00Z')

function makeSend(): { sent: OutboundMessage[]; send: (m: OutboundMessage) => Promise<Envelope> } {
  const sent: OutboundMessage[] = []
  return {
    sent,
    send: async (m: OutboundMessage) => {
      sent.push(m)
      return {} as Envelope
    },
  }
}

function opts(routing: string, send: (m: OutboundMessage) => Promise<Envelope>) {
  const router = new ApprovalRouter({ routing: routing as never }, () => NOW)
  return { router, send, selfHandle: 'alice', ttlMs: 300_000, now: () => NOW }
}

describe('relayPermissionRequest', () => {
  const params = {
    request_id: 'abcde',
    tool_name: 'Bash',
    description: 'delete build output',
    input_preview: 'rm -rf dist/',
  }

  it('posts a permission_request envelope to the routed peer', async () => {
    const { sent, send } = makeSend()
    const n = await relayPermissionRequest(params, opts('ask_specific_peer:bob', send))
    expect(n).toBe(1)
    expect(sent).toHaveLength(1)
    const msg = sent[0]!
    expect(msg.to).toBe('bob')
    expect(msg.kind).toBe('permission_request')
    expect(msg.content).toBe('delete build output')
    expect(msg.meta).toMatchObject({
      request_id: 'abcde',
      tool_name: 'Bash',
      input_preview: 'rm -rf dist/',
      requester: 'alice',
      expires_at: new Date(NOW.getTime() + 300_000).toISOString(),
    })
  })

  it('does nothing under never_relay routing', async () => {
    const { sent, send } = makeSend()
    const n = await relayPermissionRequest(params, opts('never_relay', send))
    expect(n).toBe(0)
    expect(sent).toHaveLength(0)
  })

  it('falls back to tool_name + input_preview when description is empty', async () => {
    const { sent, send } = makeSend()
    await relayPermissionRequest(
      { ...params, description: '' },
      opts('ask_specific_peer:bob', send)
    )
    expect(sent[0]!.content).toBe('Bash: rm -rf dist/')
  })

  it('rejects malformed params without sending or throwing', async () => {
    const { sent, send } = makeSend()
    const n = await relayPermissionRequest({ tool_name: 'Bash' }, opts('ask_specific_peer:bob', send))
    expect(n).toBe(0)
    expect(sent).toHaveLength(0)
  })

  it('swallows relay send failures (local dialog must never break)', async () => {
    const send = vi.fn().mockRejectedValue(new Error('relay down'))
    const n = await relayPermissionRequest(params, opts('ask_specific_peer:bob', send))
    expect(n).toBe(0)
    expect(send).toHaveBeenCalledTimes(1)
  })

  it('refuses to relay when selfHandle is empty (unattributable request)', async () => {
    const { sent, send } = makeSend()
    const o = { ...opts('ask_specific_peer:bob', send), selfHandle: '' }
    const n = await relayPermissionRequest(params, o)
    expect(n).toBe(0)
    expect(sent).toHaveLength(0)
  })

  it('clips oversized description so the envelope stays under MAX_CONTENT_BYTES', async () => {
    const { sent, send } = makeSend()
    const huge = 'é'.repeat(70_000) // 140 000 bytes utf8
    await relayPermissionRequest(
      { ...params, description: huge },
      opts('ask_specific_peer:bob', send)
    )
    expect(sent).toHaveLength(1)
    expect(Buffer.byteLength(sent[0]!.content, 'utf8')).toBeLessThanOrEqual(65536)
    expect(sent[0]!.content.length).toBeGreaterThan(0)
  })

  it('exports the channels-native notification method name', () => {
    expect(PERMISSION_REQUEST_NOTIFICATION_METHOD).toBe(
      'notifications/claude/channel/permission_request'
    )
  })
})
