export interface ReplyLimiterOpts { windowMs: number; maxReplies: number }

interface PeerState { lastInboundAt: number; outboundCount: number }

export class ReplyLimiter {
  private state = new Map<string, PeerState>()

  constructor(private opts: ReplyLimiterOpts, private now: () => number = () => Date.now()) {}

  recordInbound(from: string): void {
    this.state.set(from, { lastInboundAt: this.now(), outboundCount: 0 })
  }

  /** Returns true if a reply to `to` is allowed right now. If no recent inbound from `to`, always true. */
  canReplyTo(to: string): boolean {
    const s = this.state.get(to)
    if (!s) return true
    if (this.now() - s.lastInboundAt > this.opts.windowMs) return true
    return s.outboundCount < this.opts.maxReplies
  }

  recordOutbound(to: string): void {
    const s = this.state.get(to)
    if (!s) return
    if (this.now() - s.lastInboundAt <= this.opts.windowMs) s.outboundCount++
  }
}
