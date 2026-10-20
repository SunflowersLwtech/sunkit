import { RoleSchema, WorkgroupSchema, type Role } from '@claude-mesh/shared'
import type { Db } from './db/db.ts'

/** Where a token's sessions, tasks and leases land, and which workgroups it may see. */
export interface Grant {
  role: Role
  workgroup: string
  /** Always contains `workgroup`. */
  visible: string[]
  /** Executors only: the one machine this token may report for. */
  machine: string | null
}

/**
 * A token nobody granted anything is the least privileged thing there is: a worker that sees
 * only the shared team workgroup. So a teammate's freshly paired device never sees a private
 * workgroup by accident; private visibility is always an explicit grant (or inherited from the
 * owner's other devices at pairing, see inheritGrant).
 */
export const DEFAULT_WORKGROUP = 'team'

export interface GrantRow {
  role: string | null
  workgroup: string | null
  visible_json: string | null
  machine: string | null
}

export function normalizeVisible(workgroup: string, visible: readonly string[]): string[] {
  const set = new Set([workgroup, ...visible.filter(v => WorkgroupSchema.safeParse(v).success)])
  return [...set]
}

/** Builds a grant from a LEFT JOINed token_grant row; missing or damaged rows fall back to the default. */
export function grantFromRow(row: GrantRow | undefined): Grant {
  const role = RoleSchema.safeParse(row?.role)
  const wg = WorkgroupSchema.safeParse(row?.workgroup)
  if (!row || !role.success || !wg.success) {
    return { role: 'worker', workgroup: DEFAULT_WORKGROUP, visible: [DEFAULT_WORKGROUP], machine: null }
  }
  let visible: string[] = []
  try {
    const parsed = JSON.parse(row.visible_json ?? '[]') as unknown
    if (Array.isArray(parsed)) visible = parsed.filter((v): v is string => typeof v === 'string')
  } catch { /* keep [] */ }
  return {
    role: role.data,
    workgroup: wg.data,
    visible: normalizeVisible(wg.data, visible),
    machine: role.data === 'executor' ? row.machine : null,
  }
}

export function readGrant(db: Db, tokenId: string): Grant {
  const row = db.prepare('SELECT role, workgroup, visible_json, machine FROM token_grant WHERE token_id=?').get(tokenId) as GrantRow | undefined
  return grantFromRow(row)
}

export function setGrant(db: Db, tokenId: string, g: Grant, nowIso: string): Grant {
  const visible = normalizeVisible(g.workgroup, g.visible)
  db.prepare(`
    INSERT INTO token_grant(token_id, role, workgroup, visible_json, machine, updated_at) VALUES (?,?,?,?,?,?)
    ON CONFLICT(token_id) DO UPDATE SET role=excluded.role, workgroup=excluded.workgroup,
      visible_json=excluded.visible_json, machine=excluded.machine, updated_at=excluded.updated_at
  `).run(tokenId, g.role, g.workgroup, JSON.stringify(visible), g.role === 'executor' ? g.machine : null, nowIso)
  return { ...g, visible, machine: g.role === 'executor' ? g.machine : null }
}

/**
 * A device paired for a human who already has a granted device takes that device's
 * workgroups (most recently granted wins), always as a plain worker: a privileged role or a
 * machine binding is never inherited. Returns the inherited grant, or null.
 */
export function inheritGrant(db: Db, humanId: string, newTokenId: string, nowIso: string): Grant | null {
  const row = db.prepare(`
    SELECT g.role, g.workgroup, g.visible_json, g.machine FROM token_grant g
    JOIN token t ON t.id = g.token_id
    WHERE t.human_id = ? AND t.revoked_at IS NULL AND t.id != ?
    ORDER BY g.updated_at DESC, g.token_id DESC LIMIT 1
  `).get(humanId, newTokenId) as GrantRow | undefined
  if (!row) return null
  const g = grantFromRow(row)
  return setGrant(db, newTokenId, { role: 'worker', workgroup: g.workgroup, visible: g.visible, machine: null }, nowIso)
}

export function canSee(g: Pick<Grant, 'visible'>, workgroup: string | null | undefined): boolean {
  return workgroup == null || g.visible.includes(workgroup)
}
