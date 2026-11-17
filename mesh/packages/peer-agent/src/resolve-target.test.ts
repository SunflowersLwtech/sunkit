import { describe, it, expect } from 'vitest'
import { resolveTarget, type SessionRow } from './resolve-target.ts'

const r = (session_id: string, name: string): SessionRow => ({
  session_id, ref: session_id.slice(-6), name, account: 'a', device: 'd', status: 'idle', last_seen: '',
})
const SELF = 's_01hrk7y0000000000000self01'

describe('resolveTarget', () => {
  const rows = [r(SELF, 'me'), r('s_01hrk7y0000000000000aaaaaa', 'x'), r('s_01hrk7y0000000000000bbbbbb', 'x')]

  it('a wrong ref never falls back to another session with the same name', () => {
    expect(resolveTarget('x [zzzzzz]', rows, SELF).ok).toBe(false)
  })
  it('a correct ref with a stale name is refused (names and refs must agree)', () => {
    expect(resolveTarget('y [aaaaaa]', rows, SELF).ok).toBe(false)
  })
  it('unknown names explain how to recover', () => {
    const res = resolveTarget('ghost', rows, SELF)
    expect(res.ok).toBe(false)
    if (!res.ok) expect(res.error).toContain('list_agents')
  })
})

describe('resolveTarget stale-row preference', () => {
  const row = (ref: string, status: string): any => ({ session_id: 's' + ref, ref, name: 'w', account: 'a', device: 'd', status, last_seen: '' })
  it('prefers the single live session over stale reconnecting rows', () => {
    const r = resolveTarget('w', [row('aaaaaa', 'reconnecting'), row('bbbbbb', 'idle')], 'self')
    expect(r.ok && r.target.ref).toBe('bbbbbb')
  })
  it('still errors when two live sessions share a name', () => {
    const r = resolveTarget('w', [row('aaaaaa', 'idle'), row('bbbbbb', 'busy')], 'self')
    expect(r.ok).toBe(false)
  })
})

describe('resolveTarget unknown status', () => {
  it('taches unknown (attached, no status report) as live over reconnecting', () => {
    const row = (ref: string, status: string): any => ({ session_id: 's' + ref, ref, name: 'c', account: 'a', device: 'd', status, last_seen: '' })
    const r = resolveTarget('c', [row('aaaaaa', 'reconnecting'), row('bbbbbb', 'unknown')], 'self')
    expect(r.ok && r.target.ref).toBe('bbbbbb')
  })
})
