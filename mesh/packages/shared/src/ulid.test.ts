import { describe, it, expect } from 'vitest'
import { newMessageId, isValidMessageId, compareMessageIds } from './ulid.ts'

describe('message id', () => {
  it('generates ids with msg_ prefix followed by a ULID', () => {
    const id = newMessageId()
    expect(id).toMatch(/^msg_[0-9A-HJKMNP-TV-Z]{26}$/)
  })
  it('generates strictly sortable ids when called sequentially', () => {
    const ids = Array.from({ length: 50 }, () => newMessageId())
    const sorted = [...ids].sort()
    expect(ids).toEqual(sorted)
  })
  it('validates well-formed ids', () => {
    expect(isValidMessageId(newMessageId())).toBe(true)
  })
  it('rejects malformed ids', () => {
    expect(isValidMessageId('not-a-msg-id')).toBe(false)
    expect(isValidMessageId('msg_')).toBe(false)
    expect(isValidMessageId('')).toBe(false)
  })
  it('compares ids by lexicographic order', () => {
    const a = newMessageId()
    const b = newMessageId()
    expect(compareMessageIds(a, b)).toBeLessThan(0)
    expect(compareMessageIds(b, a)).toBeGreaterThan(0)
    expect(compareMessageIds(a, a)).toBe(0)
  })
})
