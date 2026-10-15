import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, basename } from 'node:path'
import { ulid } from 'ulid'
import { claudeConfigDir, claudeGlobalConfigPath } from './managed-policy.ts'

export type SessionStatus = 'busy' | 'idle' | 'unknown'

export interface SessionSnapshot {
  name: string
  status: SessionStatus
  /** Claude Code's own session kind ("interactive", …) when the registry has it. */
  kind?: string
}

let loginCache: { path: string; mtimeMs: number; login: string | undefined } | null = null

/**
 * The claude.ai account Claude Code is signed in with, read (never written)
 * from its global config. Display only: the mesh identity is the paired token.
 * Re-read only when the file changes, so `/login` mid-session shows up.
 */
export function readClaudeLogin(path = claudeGlobalConfigPath()): string | undefined {
  try {
    const mtimeMs = statSync(path).mtimeMs
    if (loginCache && loginCache.path === path && loginCache.mtimeMs === mtimeMs) return loginCache.login
    const j = JSON.parse(readFileSync(path, 'utf8')) as { oauthAccount?: { emailAddress?: unknown } }
    const email = j.oauthAccount?.emailAddress
    const login = typeof email === 'string' && /^[^\s<>"&]+@[^\s<>"&]+$/.test(email) && email.length <= 254 ? email : undefined
    loginCache = { path, mtimeMs, login }
    return login
  } catch {
    return undefined
  }
}

/** One id per peer-agent process, i.e. per Claude Code session. */
export function mintSessionId(): string {
  return `s_${ulid().toLowerCase()}`
}

/** Coerce anything into a valid session name (no spaces/brackets/quotes, ≤64 chars). */
export function sanitizeName(raw: string): string {
  const cleaned = raw.trim().replace(/[\s[\]<>"&]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64)
  return cleaned.length > 0 ? cleaned : 'session'
}

interface ClaudeSessionFile {
  pid?: number
  cwd?: string
  name?: string
  status?: string
  kind?: string
  startedAt?: number
}

export interface IdentityProbeOpts {
  sessionsDir?: string
  ppid?: number
  cwd?: string
  isAlive?: (pid: number) => boolean
}

function defaultIsAlive(pid: number): boolean {
  try { process.kill(pid, 0); return true } catch (err) {
    return (err as NodeJS.ErrnoException).code === 'EPERM'
  }
}

function readSessionFile(path: string): ClaudeSessionFile | undefined {
  try { return JSON.parse(readFileSync(path, 'utf8')) as ClaudeSessionFile } catch { return undefined }
}

/**
 * Read-only peek at Claude Code's own per-process session registry
 * (<config dir>/sessions/<pid>.json; the config dir is CLAUDE_CONFIG_DIR or
 * ~/.claude) so a mesh session carries the same name and busy/idle status
 * the user sees natively. The file format is internal to
 * Claude Code, so every field is optional and any failure falls back to the
 * working directory's basename with status "unknown". Nothing is ever written.
 */
export function probeClaudeSession(opts: IdentityProbeOpts = {}): SessionSnapshot {
  const dir = opts.sessionsDir ?? join(claudeConfigDir(), 'sessions')
  const cwd = opts.cwd ?? process.cwd()
  const isAlive = opts.isAlive ?? defaultIsAlive
  const fallback: SessionSnapshot = { name: sanitizeName(basename(cwd)), status: 'unknown' }

  // 1) The common case: Claude Code spawned us directly, so our parent is the session.
  const ppid = opts.ppid ?? process.ppid
  let file = readSessionFile(join(dir, `${ppid}.json`))

  // 2) Wrapped launch (e.g. cmd.exe on Windows): newest live session in the same cwd.
  if (!file) {
    let entries: string[] = []
    try { entries = readdirSync(dir).filter(f => f.endsWith('.json')) } catch { /* no registry */ }
    const candidates = entries
      .map(f => readSessionFile(join(dir, f)))
      .filter((f): f is ClaudeSessionFile =>
        !!f && f.cwd === cwd && typeof f.pid === 'number' && isAlive(f.pid))
      .sort((a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0))
    file = candidates[0]
  }
  if (!file) return fallback

  const status: SessionStatus = file.status === 'busy' || file.status === 'idle' ? file.status : 'unknown'
  const snap: SessionSnapshot = { name: file.name ? sanitizeName(file.name) : fallback.name, status }
  if (typeof file.kind === 'string') snap.kind = file.kind
  return snap
}
