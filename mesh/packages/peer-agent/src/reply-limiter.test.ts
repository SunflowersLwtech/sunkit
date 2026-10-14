import { describe, it, expect, beforeEach } from 'vitest'
import { ReplyLimiter } from './reply-limiter.ts'

describe('ReplyLimiter', () => {
  let l: ReplyLimiter
  let nowMs: number
  beforeEach(() => { nowMs = 1000; l = new ReplyLimiter({ windowMs: 5000, maxReplies: 2 }, () => nowMs) })

  it('allows up to maxReplies per sender within window', () => {
    l.recordInbound('alice')
    expect(l.canReplyTo('alice')).toBe(true); l.recordOutbound('alice')
    expect(l.canReplyTo('alice')).toBe(true); l.recordOutbound('alice')
    expect(l.canReplyTo('alice')).toBe(false)
  })

  it('isolates counts per peer', () => {
    l.recordInbound('alice'); l.recordInbound('bob')
    l.recordOutbound('alice'); l.recordOutbound('alice')
    expect(l.canReplyTo('bob')).toBe(true)
  })

  it('resets after window elapses', () => {
    l.recordInbound('alice')
    l.recordOutbound('alice'); l.recordOutbound('alice')
    expect(l.canReplyTo('alice')).toBe(false)
    nowMs += 6000
    l.recordInbound('alice')
    expect(l.canReplyTo('alice')).toBe(true)
  })

  it('canReplyTo returns true when no recent inbound exists (non-reply sends are always allowed)', () => {
    expect(l.canReplyTo('mallory')).toBe(true)
  })
})
