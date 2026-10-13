import { describe, it, expect } from 'vitest'
import { generatePairCode, parsePairCode } from './pair-code.ts'

describe('pair code', () => {
  it('generates codes in MESH-XXXX-XXXX-XXXX format', () => {
    const code = generatePairCode()
    expect(code).toMatch(/^MESH-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$/)
  })

  it('parses a valid code and validates its checksum', () => {
    const code = generatePairCode()
    expect(parsePairCode(code)).not.toBeNull()
  })

  it('rejects code with a tampered checksum', () => {
    const code = generatePairCode()
    const tampered = code.slice(0, -1) + (code.at(-1) === 'A' ? 'B' : 'A')
    expect(parsePairCode(tampered)).toBeNull()
  })

  it('rejects malformed strings', () => {
    expect(parsePairCode('not-a-code')).toBeNull()
    expect(parsePairCode('')).toBeNull()
    expect(parsePairCode('MESH-XXXX-XXXX')).toBeNull()
  })
})
