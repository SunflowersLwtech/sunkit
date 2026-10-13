import type { Db } from './db/db.ts'
import { logJson } from './logger.ts'

export interface PurgeResult {
  handles: string[]
}

/**
 * Hard-deletes users with last_active_at older than `cutoffIso`.
 *
 * Safety rails:
 * - Users who currently hold an active admin-tier token are NEVER purged,
 *   even if inactive — losing the sole admin would leave the team orphaned.
 * - Single transaction per team so the sweep is atomic.
 * - Audit log gets a `user.purge` event per deleted handle BEFORE the row
 *   vanishes so the FK reference stays valid.
 */
export function purgeInactive(
  db: Db,
  teamId: string,
  cutoffIso: string,
  actorHumanId: string | null,
  nowIso: string,
): PurgeResult {
  // Pick candidates: users inactive past cutoff who don't hold an active
  // admin-tier token. The NOT EXISTS clause keeps team admins safe.
  const candidates = db.prepare(`
    SELECT h.id, h.handle
    FROM human h
    WHERE h.team_id = ?
      AND (h.last_active_at IS NULL OR h.last_active_at < ?)
      AND NOT EXISTS (
        SELECT 1 FROM token t
        WHERE t.human_id = h.id AND t.tier = 'admin' AND t.revoked_at IS NULL
      )
  `).all(teamId, cutoffIso) as Array<{ id: string; handle: string }>

  if (candidates.length === 0) return { handles: [] }

  db.transaction(() => {
    for (const c of candidates) {
      db.prepare(
        "INSERT INTO audit_log(team_id,at,actor_human_id,event,detail_json) VALUES (?,?,?,?,?)"
      ).run(teamId, nowIso, actorHumanId, 'user.purge',
        JSON.stringify({ handle: c.handle, cutoff: cutoffIso, reason: 'inactive' }))
      db.prepare("DELETE FROM token WHERE human_id=?").run(c.id)
      db.prepare("DELETE FROM pair_code WHERE human_id=?").run(c.id)
      db.prepare("DELETE FROM human WHERE id=?").run(c.id)
    }
  })()

  return { handles: candidates.map(c => c.handle) }
}

/**
 * Starts a recurring background sweep. Returns the interval handle so the
 * caller can clear it at shutdown.
 */
export function startInactivitySweeper(
  db: Db,
  opts: { intervalMs: number; days: number; now: () => Date }
): NodeJS.Timeout {
  const tick = (): void => {
    try {
      const nowDate = opts.now()
      const nowIso = nowDate.toISOString()
      const cutoff = new Date(nowDate.getTime() - opts.days * 24 * 60 * 60 * 1000).toISOString()
      const teams = db.prepare("SELECT id FROM team").all() as Array<{ id: string }>
      for (const t of teams) {
        const r = purgeInactive(db, t.id, cutoff, null, nowIso)
        if (r.handles.length > 0) {
          logJson('info', 'purge.sweep', { team_id: t.id, count: r.handles.length, handles: r.handles.join(','), days: opts.days })
        }
      }
    } catch (err) {
      logJson('warn', 'purge.sweep_error', { err: String(err instanceof Error ? err.message : err) })
    }
  }
  return setInterval(tick, opts.intervalMs)
}
