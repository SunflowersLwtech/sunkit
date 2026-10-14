import { describe, it, expect, beforeEach } from 'vitest'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { SessionIdSchema, SessionNameSchema } from '@claude-mesh/shared'
import { mintSessionId, probeClaudeSession, sanitizeName, readClaudeLogin } from './session-identity.ts'
import { utimesSync } from 'node:fs'

describe('session identity', () => {
  let dir: string
  beforeEach(() => { dir = mkdtempSync(join(tmpdir(), 'mesh-sess-')) })
  const put = (pid: number, body: object) => writeFileSync(join(dir, `${pid}.json`), JSON.stringify(body))

  it('mints ids the relay accepts', () => {
    expect(SessionIdSchema.safeParse(mintSessionId()).success).toBe(true)
    expect(mintSessionId()).not.toBe(mintSessionId())
  })

  it('sanitized names always pass the relay schema', () => {
    for (const raw of ['my repo [wip]', '  ', 'a"b<c>&d', 'x'.repeat(200), '日本語 プロジェクト']) {
      expect(SessionNameSchema.safeParse(sanitizeName(raw)).success).toBe(true)
    }
  })

  it('uses the parent Claude Code session name and status', () => {
    put(4242, { pid: 4242, cwd: '/w/repo', name: 'repo-1c', status: 'busy', kind: 'interactive' })
    expect(probeClaudeSession({ sessionsDir: dir, ppid: 4242, cwd: '/w/repo' }))
      .toEqual({ name: 'repo-1c', status: 'busy', kind: 'interactive' })
  })

  it('falls back to the newest live session in the same cwd when the parent is a wrapper', () => {
    put(1, { pid: 1, cwd: '/w/repo', name: 'old', startedAt: 1 })
    put(2, { pid: 2, cwd: '/w/repo', name: 'new', startedAt: 2, status: 'idle' })
    put(3, { pid: 3, cwd: '/w/repo', name: 'dead', startedAt: 3 })
    put(4, { pid: 4, cwd: '/w/other', name: 'elsewhere', startedAt: 4 })
    const r = probeClaudeSession({ sessionsDir: dir, ppid: 999, cwd: '/w/repo', isAlive: pid => pid !== 3 })
    expect(r).toEqual({ name: 'new', status: 'idle' })
  })

  it('falls back to the cwd basename when the registry is missing or unreadable', () => {
    writeFileSync(join(dir, '7.json'), '{not json')
    expect(probeClaudeSession({ sessionsDir: join(dir, 'nope'), ppid: 7, cwd: '/w/my repo' }))
      .toEqual({ name: 'my-repo', status: 'unknown' })
    expect(probeClaudeSession({ sessionsDir: dir, ppid: 7, cwd: '/w/x' })).toEqual({ name: 'x', status: 'unknown' })
  })

  it('reads the signed-in claude.ai email and notices a /login switch', () => {
    const f = join(dir, '.claude.json')
    writeFileSync(f, JSON.stringify({ oauthAccount: { emailAddress: 'a@duocodetech.com' } }))
    expect(readClaudeLogin(f)).toBe('a@duocodetech.com')
    writeFileSync(f, JSON.stringify({ oauthAccount: { emailAddress: 'b@gmail.com' } }))
    utimesSync(f, new Date(), new Date(Date.now() + 5000))
    expect(readClaudeLogin(f)).toBe('b@gmail.com')
  })

  it('returns undefined for API-key setups, malformed values or a missing file', () => {
    const f = join(dir, '.claude.json')
    writeFileSync(f, JSON.stringify({}))
    expect(readClaudeLogin(f)).toBeUndefined()
    writeFileSync(f, JSON.stringify({ oauthAccount: { emailAddress: 'x <y@z>' } }))
    utimesSync(f, new Date(), new Date(Date.now() + 9000))
    expect(readClaudeLogin(f)).toBeUndefined()
    expect(readClaudeLogin(join(dir, 'nope.json'))).toBeUndefined()
  })
})
