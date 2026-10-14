import { describe, it, expect } from 'vitest'
import { parseSseEvent } from './stream.ts'

describe('parseSseEvent', () => {
  it('parses event + data', () => {
    const ev = parseSseEvent('event: message\ndata: {"id":"msg_x"}')
    expect(ev).toEqual({ event: 'message', data: '{"id":"msg_x"}' })
  })
  it('defaults event to "message"', () => {
    const ev = parseSseEvent('data: hello')
    expect(ev?.event).toBe('message')
  })
  it('merges multi-line data with newlines', () => {
    const ev = parseSseEvent('event: x\ndata: a\ndata: b')
    expect(ev?.data).toBe('a\nb')
  })
  it('returns null for comment-only or empty blocks', () => {
    expect(parseSseEvent(': keepalive')).toBeNull()
    expect(parseSseEvent('')).toBeNull()
  })
})
