import { newLeaseId, sessionRef, type LeaseView } from '@claude-mesh/shared'
import type { Db } from '../db/db.ts'

export const MAX_LEASES_PER_SESSION = 3
/** Total time one session may add by renewing (across its live leases). */
export const MAX_RENEW_S_PER_SESSION = 2 * 60 * 60
export const LEASE_RETENTION_MS = 7 * 24 * 60 * 60_000

export interface LeaseRow {
  id: string
  team_id: string
  workgroup: string
  name: string
  holder_session: string
  holder_name: string
  holder_machine: string | null
  holder_token: string
  task_id: string | null
  note: string | null
  ttl_s: number
  acquired_at: string
  expires_at: string
  renew_count: number
  renewed_s: number
  released_at: string | null
  release_reason: string | null
}

export interface Holder { session: string; name: string; machine: string | null; token: string; workgroup: string }

export type AcquireResult =
  | { ok: true; lease: LeaseRow; expired: LeaseRow | null }
  | { ok: false; error: 'lease_held'; lease: LeaseRow }
  | { ok: false; error: 'lease_quota' }

/**
 * Leases live in SQLite, so a relay restart keeps them. Expiry is judged on read
 * (`expires_at > now` is live); there is no timer. better-sqlite3 runs each transaction
 * synchronously, so two acquires of one name cannot interleave.
 */
export class LeaseStore {
  constructor(private readonly db: Db, private readonly now: () => Date) {}

  private nowIso(): string { return this.now().toISOString() }

  /** The unreleased row for a name, expired or not. */
  private current(team_id: string, name: string): LeaseRow | undefined {
    return this.db.prepare('SELECT * FROM lease WHERE team_id=? AND name=? AND released_at IS NULL').get(team_id, name) as LeaseRow | undefined
  }

  isLive(l: LeaseRow): boolean {
    return Date.parse(l.expires_at) > this.now().getTime()
  }

  get(team_id: string, id: string): LeaseRow | undefined {
    return this.db.prepare('SELECT * FROM lease WHERE id=? AND team_id=?').get(id, team_id) as LeaseRow | undefined
  }

  liveCount(holder_session: string): number {
    const row = this.db.prepare('SELECT COUNT(*) AS n FROM lease WHERE holder_session=? AND released_at IS NULL AND expires_at > ?')
      .get(holder_session, this.nowIso()) as { n: number }
    return row.n
  }

  acquire(team_id: string, name: string, ttl_s: number, holder: Holder, extra: { task_id: string | null; note: string | null }): AcquireResult {
    return this.db.transaction((): AcquireResult => {
      const at = this.now()
      const cur = this.current(team_id, name)
      if (cur && this.isLive(cur)) return { ok: false, error: 'lease_held', lease: cur }
      if (this.liveCount(holder.session) >= MAX_LEASES_PER_SESSION) return { ok: false, error: 'lease_quota' }
      let expired: LeaseRow | null = null
      if (cur) {
        this.db.prepare("UPDATE lease SET released_at=?, release_reason='expire' WHERE id=?").run(at.toISOString(), cur.id)
        expired = cur
      }
      const id = newLeaseId()
      this.db.prepare(`
        INSERT INTO lease(id, team_id, workgroup, name, holder_session, holder_name, holder_machine, holder_token, task_id, note, ttl_s, acquired_at, expires_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
      `).run(id, team_id, holder.workgroup, name, holder.session, holder.name, holder.machine, holder.token, extra.task_id, extra.note,
        ttl_s, at.toISOString(), new Date(at.getTime() + ttl_s * 1000).toISOString())
      return { ok: true, lease: this.get(team_id, id)!, expired }
    })()
  }

  renew(team_id: string, id: string, ttl_s: number): { ok: true; lease: LeaseRow } | { ok: false; error: 'lease_expired' | 'lease_quota' } {
    return this.db.transaction(() => {
      const l = this.get(team_id, id)!
      if (l.released_at !== null || !this.isLive(l)) return { ok: false as const, error: 'lease_expired' as const }
      const used = this.db.prepare('SELECT COALESCE(SUM(renewed_s), 0) AS s FROM lease WHERE holder_session=? AND released_at IS NULL')
        .get(l.holder_session) as { s: number }
      if (used.s + ttl_s > MAX_RENEW_S_PER_SESSION) return { ok: false as const, error: 'lease_quota' as const }
      const at = this.now()
      this.db.prepare('UPDATE lease SET expires_at=?, ttl_s=?, renew_count=renew_count+1, renewed_s=renewed_s+? WHERE id=?')
        .run(new Date(at.getTime() + ttl_s * 1000).toISOString(), ttl_s, ttl_s, id)
      return { ok: true as const, lease: this.get(team_id, id)! }
    })()
  }

  release(team_id: string, id: string, reason: 'release' | 'force'): boolean {
    return this.db.prepare('UPDATE lease SET released_at=?, release_reason=? WHERE id=? AND team_id=? AND released_at IS NULL')
      .run(this.nowIso(), reason, id, team_id).changes > 0
  }

  listLive(team_id: string): LeaseRow[] {
    return this.db.prepare('SELECT * FROM lease WHERE team_id=? AND released_at IS NULL AND expires_at > ? ORDER BY name')
      .all(team_id, this.nowIso()) as LeaseRow[]
  }

  sweep(): number {
    const cutoff = new Date(this.now().getTime() - LEASE_RETENTION_MS).toISOString()
    return this.db.prepare('DELETE FROM lease WHERE released_at IS NOT NULL AND released_at < ?').run(cutoff).changes
  }

  /** `showHolder` false: the caller learns the name is held and until when, not by whom. */
  view(l: LeaseRow, showHolder: boolean): LeaseView {
    return {
      id: l.id,
      name: l.name,
      holder: showHolder ? { session: l.holder_session, ref: sessionRef(l.holder_session), name: l.holder_name, machine: l.holder_machine } : null,
      task_id: showHolder ? l.task_id : null,
      note: showHolder ? l.note : null,
      expires_at: l.expires_at,
      ttl_remaining_s: Math.max(0, Math.ceil((Date.parse(l.expires_at) - this.now().getTime()) / 1000)),
      renew_count: l.renew_count,
    }
  }
}
