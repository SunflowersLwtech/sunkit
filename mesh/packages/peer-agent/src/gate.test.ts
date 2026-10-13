import { describe, it, expect, beforeEach } from 'vitest'
import { SenderGate } from './gate.ts'

describe('SenderGate', () => {
  let g: SenderGate
  beforeEach(() => { g = new SenderGate(['alice','bob','charlie']) })

  it('accepts known handles', () => { expect(g.accept('alice')).toBe(true) })
  it('rejects unknown handles, increments metric', () => {
    expect(g.accept('mallory')).toBe(false)
    expect(g.violations()).toBe(1)
  })
  it('roster can be refreshed', () => {
    g.setRoster(['alice'])
    expect(g.accept('bob')).toBe(false)
  })
})
