import { describe, it, expect } from 'vitest'
import { hashToken, timingSafeEqual, generateRawToken } from './hash.ts'

describe('token hashing', () => {
  it('generates a raw token that is a long random string', () => {
    const t = generateRawToken()
    expect(t).toMatch(/^[A-Za-z0-9_-]{43}$/) // 32 bytes url-safe b64
  })

  it('hashToken is deterministic', () => {
    expect(hashToken('abc').equals(hashToken('abc'))).toBe(true)
  })

  it('hashToken differs for different inputs', () => {
    expect(hashToken('abc').equals(hashToken('abd'))).toBe(false)
  })

  it('timingSafeEqual returns true for equal buffers and false otherwise', () => {
    const a = hashToken('x')
    const b = hashToken('x')
    const c = hashToken('y')
    expect(timingSafeEqual(a, b)).toBe(true)
    expect(timingSafeEqual(a, c)).toBe(false)
  })

  it('timingSafeEqual returns false for different-length buffers', () => {
    expect(timingSafeEqual(Buffer.from('abc'), Buffer.from('abcd'))).toBe(false)
  })
})
