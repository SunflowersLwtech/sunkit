import { chmodSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

export interface WakeBudgetOpts {
  /** Wakes one session (this process) may start per window. Default 6. */
  perSession?: number
  /** Wakes every session on the machine may start per window. Default 60. */
  perMachine?: number
  /** Length of the sliding window. Default one hour. */
  windowMs?: number
  /** Machine-wide ledger: a JSON array of epoch-ms numbers. */
  file: string
  /** Clock, injectable for tests. Default Date.now. */
  now?: () => number
}

/**
 * A hard local limit on how many wakes a session (and the machine it lives on) may start.
 *
 * Every wake starts a model turn, so a loop of messages could otherwise keep a session
 * turning all day. The relay cannot police this: it does not know which sessions wake, so the
 * limit has to live on the machine. The session count is kept in memory (this process is one
 * session); the machine count is a shared ledger file, because sibling sessions run as
 * separate processes on the same box.
 *
 * The machine limit is skipped when the ledger cannot be read or written — a broken file
 * must not stop wakes forever — but the session limit always applies.
 */
export class WakeBudget {
  private readonly perSession: number
  private readonly perMachine: number
  private readonly windowMs: number
  private readonly file: string
  private readonly now: () => number
  /** Wake timestamps of this process (this session). */
  private session: number[] = []

  constructor(opts: WakeBudgetOpts) {
    this.perSession = opts.perSession ?? 6
    this.perMachine = opts.perMachine ?? 60
    this.windowMs = opts.windowMs ?? 3_600_000
    this.file = opts.file
    this.now = opts.now ?? Date.now
  }

  /** True (and records the wake) when both limits allow it; false otherwise. Never throws. */
  take(): boolean {
    const now = this.now()
    const session = this.session.filter(t => now - t < this.windowMs)
    if (session.length >= this.perSession) {
      this.session = session
      return false
    }
    // null means the ledger is unusable: skip the machine limit for this call only.
    const entries = this.readLedger(now)
    if (entries !== null && entries.length >= this.perMachine) {
      this.session = session
      return false
    }
    this.session = [...session, now]
    if (entries !== null) this.writeLedger([...entries, now])
    return true
  }

  /** Wakes counted in the current window, for logs. */
  used(): { session: number; machine: number } {
    const now = this.now()
    const session = this.session.filter(t => now - t < this.windowMs).length
    const entries = this.readLedger(now)
    const machine = entries === null ? 0 : entries.filter(t => now - t < this.windowMs).length
    return { session, machine }
  }

  /**
   * The ledger entries inside the window, or null when the file cannot be read at all.
   * A missing, empty or corrupt file counts as an empty ledger.
   */
  private readLedger(now: number): number[] | null {
    let raw: string
    try {
      raw = readFileSync(this.file, 'utf8')
    } catch (err) {
      const code = (err as NodeJS.ErrnoException).code
      if (code === 'ENOENT') return []
      return null
    }
    let parsed: unknown
    try {
      parsed = JSON.parse(raw)
    } catch {
      return [] // corrupt ledger: treat as empty and let the next write repair it
    }
    if (!Array.isArray(parsed)) return []
    return parsed.filter((v): v is number => typeof v === 'number' && Number.isFinite(v)).filter(t => now - t < this.windowMs)
  }

  /** Append-and-truncate to the ledger, atomically. Returns false when it could not be written. */
  private writeLedger(entries: number[]): boolean {
    const dir = dirname(this.file)
    const tmp = `${this.file}.${process.pid}.tmp`
    const kept = entries.slice(-Math.max(1, this.perMachine))
    try {
      if (!existsSync(dir)) mkdirSync(dir, { recursive: true, mode: 0o700 })
      writeFileSync(tmp, JSON.stringify(kept), { mode: 0o600 })
      chmodSync(tmp, 0o600)
      renameSync(tmp, this.file)
      return true
    } catch {
      try { rmSync(tmp, { force: true }) } catch { /* nothing to clean up */ }
      return false
    }
  }
}
