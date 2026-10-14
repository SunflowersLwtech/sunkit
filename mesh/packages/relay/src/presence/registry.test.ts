import { describe, it, expect, beforeEach } from 'vitest'
import { PresenceRegistry } from './registry.ts'

describe('PresenceRegistry', () => {
  let p: PresenceRegistry
  beforeEach(() => { p = new PresenceRegistry(() => new Date('2026-01-01T00:00:00Z')) })

  it('records and reads back presence', () => {
    p.set('t1', 'alice', 'laptop', { summary: 'grinding auth', cwd: '/src', branch: 'main', repo: 'x' })
    const snap = p.get('t1', 'alice')
    expect(snap?.summary).toBe('grinding auth')
    expect(snap?.sessions[0]).toMatchObject({ label: 'laptop', branch: 'main' })
  })

  it('merges multiple sessions for one human', () => {
    p.set('t1', 'alice', 'laptop', { summary: 'A', cwd: '/', branch: 'main', repo: 'r' })
    p.set('t1', 'alice', 'desktop', { summary: 'A', cwd: '/', branch: 'dev', repo: 'r' })
    expect(p.get('t1', 'alice')?.sessions).toHaveLength(2)
  })

  it('remove drops a session', () => {
    p.set('t1', 'alice', 'laptop', { summary: 'A', cwd: '/', branch: 'main', repo: 'r' })
    p.remove('t1', 'alice', 'laptop')
    expect(p.get('t1', 'alice')).toBeUndefined()
  })

  it('listTeam returns all humans with their summaries', () => {
    p.set('t1', 'alice', 'laptop', { summary: 'A', cwd: '/', branch: 'm', repo: 'r' })
    p.set('t1', 'bob',   'laptop', { summary: 'B', cwd: '/', branch: 'm', repo: 'r' })
    const list = p.listTeam('t1')
    expect(list.map(h => h.handle).sort()).toEqual(['alice','bob'])
  })
})
