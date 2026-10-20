import type { Db } from './db/db.ts'

/**
 * One audit row. `detail` carries ids, names, machines and reasons only: never message
 * content, prompts, command output or anything token-shaped.
 */
export function audit(db: Db, teamId: string, actorHumanId: string | null, event: string, detail: Record<string, unknown>, nowIso: string): void {
  db.prepare('INSERT INTO audit_log(team_id,at,actor_human_id,event,detail_json) VALUES (?,?,?,?,?)')
    .run(teamId, nowIso, actorHumanId, event, JSON.stringify(detail))
}
