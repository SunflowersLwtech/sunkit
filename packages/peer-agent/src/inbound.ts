import type { Envelope } from '@claude-mesh/shared'
import { envelopeToChannelNotification } from '@claude-mesh/shared'
import { SenderGate } from './gate.ts'
import type { PermissionTracker } from './permission.ts'
import type { ReplyLimiter } from './reply-limiter.ts'
import { logJson } from './logger.ts'

export interface InboundDispatcherOpts {
  gate: SenderGate
  /** When set, only chat addressed to this session (or to the account as a whole) is surfaced. */
  sessionId?: string | undefined
  /** When true, only kind=chat reaches Claude; presence and permission traffic is dropped. */
  chatOnly?: boolean | undefined
  emit: (notification: { method: string; params: Record<string, unknown> }) => void
  setCursor: (id: string) => void
  permissionTracker?: PermissionTracker | undefined
  replyLimiter?: ReplyLimiter | undefined
  /** Called for gated inbound chats so approval routing sees both directions of a thread (spec §5). */
  recordDm?: ((handle: string) => void) | undefined
}

export class InboundDispatcher {
  constructor(private opts: InboundDispatcherOpts) {}

  handle(e: Envelope): void {
    logJson('info', 'peer.inbound.received', { from: e.from, kind: e.kind, msg_id: e.id })
    if (!this.opts.gate.accept(e.from)) {
      logJson('warn', 'peer.inbound.sender_gate_drop', { from: e.from, msg_id: e.id })
      return
    }
    if (this.opts.chatOnly && e.kind !== 'chat') {
      this.opts.setCursor(e.id)
      return
    }
    if (this.opts.sessionId && e.to_session && e.to_session !== this.opts.sessionId) {
      logJson('warn', 'peer.inbound.wrong_session_drop', { msg_id: e.id })
      this.opts.setCursor(e.id)
      return
    }
    if (e.kind === 'chat') this.opts.recordDm?.(e.from)
    if (e.kind === 'permission_request' && this.opts.permissionTracker) {
      const rid = e.meta.request_id ?? ''
      if (rid) this.opts.permissionTracker.recordIncoming(rid, e.id, e.from)
    }
    const notification = envelopeToChannelNotification(e)
    // Key the loop guard by the reply address Claude will use ("name [ref]" or handle).
    this.opts.replyLimiter?.recordInbound(String(notification.params.meta.from ?? e.from))
    try {
      this.opts.emit(notification)
      logJson('info', 'peer.inbound.emitted', { method: notification.method, msg_id: e.id })
    } catch (err) {
      logJson('error', 'peer.inbound.emit_error', {
        method: notification.method,
        msg_id: e.id,
        err: String(err instanceof Error ? err.message : err),
      })
    }
    this.opts.setCursor(e.id)
  }
}
