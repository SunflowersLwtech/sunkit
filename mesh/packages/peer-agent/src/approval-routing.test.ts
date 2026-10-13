import { describe, it, expect } from 'vitest'
import { ApprovalRouter } from './approval-routing.ts'

describe('ApprovalRouter', () => {
  const now = () => new Date('2026-04-18T00:00:00Z')
  let r: ApprovalRouter

  it('never_relay returns null', () => {
    r = new ApprovalRouter({ routing: 'never_relay' }, now)
    expect(r.pick({ excludeSelf: 'alice' })).toBeNull()
  })

  it('ask_specific_peer returns the named handle', () => {
    r = new ApprovalRouter({ routing: 'ask_specific_peer:bob' }, now)
    expect(r.pick({ excludeSelf: 'alice' })).toEqual(['bob'])
  })

  it('ask_team returns @team', () => {
    r = new ApprovalRouter({ routing: 'ask_team' }, now)
    expect(r.pick({ excludeSelf: 'alice' })).toEqual(['@team'])
  })

  it('ask_thread_participants falls back to most recent DM partner if no active thread', () => {
    r = new ApprovalRouter({ routing: 'ask_thread_participants' }, now)
    r.recordDm('bob', now())
    expect(r.pick({ excludeSelf: 'alice' })).toEqual(['bob'])
  })

  it('ask_thread_participants returns null when no history', () => {
    r = new ApprovalRouter({ routing: 'ask_thread_participants' }, now)
    expect(r.pick({ excludeSelf: 'alice' })).toBeNull()
  })

  it('ask_thread_participants expires entries older than 10 min', () => {
    const baseTime = new Date('2026-04-18T00:00:00Z').getTime()
    let mockNow = baseTime
    r = new ApprovalRouter({ routing: 'ask_thread_participants' }, () => new Date(mockNow))
    r.recordDm('bob', new Date(baseTime))
    mockNow = baseTime + 11 * 60_000
    expect(r.pick({ excludeSelf: 'alice' })).toBeNull()
  })
})
