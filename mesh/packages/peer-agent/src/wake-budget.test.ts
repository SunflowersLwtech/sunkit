import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { WakeBudget } from './wake-budget.ts'
import { IdleWaker } from './wake.ts'

describe('WakeBudget', () => {
  let dir: string
  let file: string
  let now: number

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'mesh-wake-budget-'))
    file = join(dir, 'wakes.json')
    now = 1_700_000_000_000
  })

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true })
  })

  it('allows 6 wakes per session in an hour and refuses the 7th until the window passes', () => {
    const budget = new WakeBudget({ file, now: () => now })
    for (let i = 0; i < 6; i++) expect(budget.take()).toBe(true)
    expect(budget.take()).toBe(false)
    expect(budget.used().session).toBe(6)

    now += 3_600_001
    expect(budget.take()).toBe(true)
    expect(budget.used().session).toBe(1)
  })

  it('stops two sessions on one machine together at the machine limit', () => {
    const a = new WakeBudget({ file, perSession: 5, perMachine: 7, now: () => now })
    const b = new WakeBudget({ file, perSession: 5, perMachine: 7, now: () => now })
    let allowed = 0
    for (let i = 0; i < 5; i++) if (a.take()) allowed++
    for (let i = 0; i < 5; i++) if (b.take()) allowed++
    expect(allowed).toBe(7)
    // a has spent its own session limit, b is stopped by the machine limit.
    expect(a.take()).toBe(false)
    expect(b.take()).toBe(false)
  })

  it('counts a corrupt ledger as empty and repairs it on the next take', () => {
    writeFileSync(file, 'not json')
    const budget = new WakeBudget({ file, now: () => now })
    expect(budget.take()).toBe(true)
    const entries = JSON.parse(readFileSync(file, 'utf8'))
    expect(entries).toEqual([now])
  })

  it('never throws when the ledger cannot be written, and still holds the session limit', () => {
    const blocker = join(dir, 'blocker')
    writeFileSync(blocker, 'not a directory')
    const budget = new WakeBudget({ file: join(blocker, 'wakes.json'), perSession: 2, perMachine: 5, now: () => now })
    let first: boolean | undefined
    expect(() => { first = budget.take() }).not.toThrow()
    expect(first).toBe(true)
    expect(budget.take()).toBe(true)
    expect(budget.take()).toBe(false)
    expect(budget.used().session).toBe(2)
  })

  it('keeps at most perMachine entries in the ledger file', () => {
    const a = new WakeBudget({ file, perSession: 50, perMachine: 3, now: () => now })
    const b = new WakeBudget({ file, perSession: 50, perMachine: 3, now: () => now })
    for (let i = 0; i < 10; i++) {
      a.take()
      b.take()
    }
    const entries = JSON.parse(readFileSync(file, 'utf8'))
    expect(entries.length).toBeLessThanOrEqual(3)
    expect(entries.length).toBe(3)
  })

  it('keeps the ledger private to the machine', () => {
    const budget = new WakeBudget({ file: join(dir, 'nested', 'wakes.json'), now: () => now })
    expect(budget.take()).toBe(true)
    if (process.platform !== 'win32') {
      expect(statSync(join(dir, 'nested')).mode & 0o777).toBe(0o700)
      expect(statSync(join(dir, 'nested', 'wakes.json')).mode & 0o777).toBe(0o600)
    }
  })
})

describe('IdleWaker with a budget', () => {
  it('does not send when the budget refuses, and does not spend the wake interval', () => {
    const sent: string[] = []
    let allow = false
    const waker = new IdleWaker({ send: t => sent.push(t), minIntervalMs: 60_000, budget: { take: () => allow } })
    expect(waker.maybeWake('idle', { size: 1, from: ['lead [abc123]'] })).toBe(false)
    expect(sent).toHaveLength(0)
    allow = true
    expect(waker.maybeWake('idle', { size: 1, from: ['lead [abc123]'] })).toBe(true)
    expect(sent).toHaveLength(1)
  })

  it('sends once when the budget allows', () => {
    const sent: string[] = []
    const waker = new IdleWaker({ send: t => sent.push(t), budget: { take: () => true } })
    expect(waker.maybeWake('idle', { size: 1, from: ['lead [abc123]'] })).toBe(true)
    expect(sent).toEqual(['[mesh] 1 new message from lead [abc123]. Call the mesh read_messages tool to read it.'])
  })
})
