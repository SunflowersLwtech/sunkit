import { Hono } from 'hono'
import { z } from 'zod'
import { ulid } from 'ulid'
import { HANDLE_REGEX, MachineNameSchema, PAIR_CODE_TTL_MS, RoleSchema, WorkgroupSchema } from '@claude-mesh/shared'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import { generatePairCode } from '../auth/pair-code.ts'
import { hashToken } from '../auth/hash.ts'
import { purgeInactive } from '../purge.ts'
import { grantFromRow, setGrant, type GrantRow } from '../grants.ts'
import { audit } from '../audit.ts'
import type { Deps } from '../deps.ts'

const CreateUserBody = z.object({
  handle: z.string().regex(HANDLE_REGEX),
  display_name: z.string().min(1).max(128),
  tier: z.enum(['human', 'admin']).default('human'),
  // When true, an existing handle is reset instead of rejected: old tokens
  // revoked, pending paircodes invalidated, disabled_at cleared, display_name
  // updated, and a fresh paircode minted. Old paired devices stop working.
  force: z.boolean().default(false),
})

const GrantBody = z.object({
  role: RoleSchema,
  workgroup: WorkgroupSchema,
  visible: z.array(WorkgroupSchema).max(16).default([]),
  machine: MachineNameSchema.nullable().optional(),
}).strict().superRefine((g, ctx) => {
  // An executor reports for exactly one machine; nobody else is bound to one.
  if (g.role === 'executor' && !g.machine) ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['machine'], message: 'executor needs machine' })
  if (g.role !== 'executor' && g.machine) ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['machine'], message: 'only executors have a machine' })
})

interface AuditRow {
  id: number
  at: string
  actor_human_id: string | null
  event: string
  detail_json: string
}

export function adminRoute(deps: Deps) {
  const app = new Hono<{ Variables: AuthContext }>()
  app.use('*', bearerAuth(deps.db, { requireTier: 'admin' }))

  app.post('/users', async c => {
    const parsed = CreateUserBody.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    const team = c.get('team_id')
    const { handle, display_name, tier, force } = parsed.data
    const existing = deps.db.prepare(
      "SELECT id FROM human WHERE team_id=? AND handle=?"
    ).get(team, handle) as { id: string } | undefined

    if (existing && !force) return c.json({ error: 'handle_taken' }, 409)

    const code = generatePairCode()
    const now = deps.now().toISOString()
    const expires = new Date(deps.now().getTime() + PAIR_CODE_TTL_MS).toISOString()
    const humanId = existing?.id ?? `h_${ulid()}`

    const tx = deps.db.transaction(() => {
      if (existing) {
        // Reset path: reuse the row, revoke old tokens, invalidate pending
        // paircodes, clear any disabled tombstone, refresh display_name.
        deps.db.prepare(
          "UPDATE human SET display_name=?, disabled_at=NULL WHERE id=?"
        ).run(display_name, existing.id)
        deps.db.prepare(
          "UPDATE token SET revoked_at=? WHERE human_id=? AND revoked_at IS NULL"
        ).run(now, existing.id)
        deps.db.prepare(
          "DELETE FROM pair_code WHERE human_id=?"
        ).run(existing.id)
      } else {
        deps.db.prepare(
          "INSERT INTO human(id,team_id,handle,display_name,created_at,last_active_at) VALUES (?,?,?,?,?,?)"
        ).run(humanId, team, handle, display_name, now, now)
      }
      deps.db.prepare(
        "INSERT INTO pair_code(code_hash,human_id,tier,expires_at,created_at) VALUES (?,?,?,?,?)"
      ).run(hashToken(code), humanId, tier, expires, now)
      deps.db.prepare(
        "INSERT INTO audit_log(team_id,at,actor_human_id,event,detail_json) VALUES (?,?,?,?,?)"
      ).run(
        team, now, c.get('human').id, existing ? 'user.reset' : 'user.create',
        JSON.stringify({ handle, tier })
      )
    })
    tx()
    return c.json({
      handle, display_name, tier, pair_code: code, expires_at: expires,
      reset: Boolean(existing),
    }, existing ? 200 : 201)
  })

  // Pair one more device to an existing user. Unlike POST /users with force,
  // this never revokes the user's existing tokens.
  app.post('/users/:handle/devices', c => {
    const team = c.get('team_id')
    const handle = c.req.param('handle')
    const row = deps.db.prepare(
      "SELECT id FROM human WHERE team_id=? AND handle=? AND disabled_at IS NULL"
    ).get(team, handle) as { id: string } | undefined
    if (!row) return c.json({ error: 'unknown_user' }, 404)
    const code = generatePairCode()
    const now = deps.now().toISOString()
    const expires = new Date(deps.now().getTime() + PAIR_CODE_TTL_MS).toISOString()
    // Device tokens are always human-tier; admin access stays with the admin token.
    deps.db.prepare(
      "INSERT INTO pair_code(code_hash,human_id,tier,expires_at,created_at) VALUES (?,?,?,?,?)"
    ).run(hashToken(code), row.id, 'human', expires, now)
    deps.db.prepare(
      "INSERT INTO audit_log(team_id,at,actor_human_id,event,detail_json) VALUES (?,?,?,?,?)"
    ).run(team, now, c.get('human').id, 'user.add_device', JSON.stringify({ handle }))
    return c.json({ handle, pair_code: code, expires_at: expires }, 201)
  })

  app.delete('/users/:handle', c => {
    const team = c.get('team_id')
    const handle = c.req.param('handle')
    const hard = c.req.query('hard') === 'true'
    const now = deps.now().toISOString()

    if (hard) {
      const row = deps.db.prepare(
        "SELECT id FROM human WHERE team_id=? AND handle=?"
      ).get(team, handle) as { id: string } | undefined
      if (!row) return c.json({ error: 'not_found' }, 404)
      // Hard delete: cascade-remove all rows tied to this human so the
      // handle becomes reusable without --force. Audit is inserted BEFORE
      // the human row so the FK reference stays valid.
      deps.db.transaction(() => {
        deps.db.prepare(
          "INSERT INTO audit_log(team_id,at,actor_human_id,event,detail_json) VALUES (?,?,?,?,?)"
        ).run(team, now, c.get('human').id, 'user.delete', JSON.stringify({ handle, hard: true }))
        deps.db.prepare("DELETE FROM token WHERE human_id=?").run(row.id)
        deps.db.prepare("DELETE FROM pair_code WHERE human_id=?").run(row.id)
        deps.db.prepare("DELETE FROM human WHERE id=?").run(row.id)
      })()
      return c.json({ ok: true, hard: true })
    }

    // Soft disable (default): tombstone + revoke tokens, keep row + handle.
    const info = deps.db.prepare(
      "UPDATE human SET disabled_at=? WHERE team_id=? AND handle=? AND disabled_at IS NULL"
    ).run(now, team, handle)
    if (info.changes === 0) return c.json({ error: 'not_found' }, 404)
    deps.db.prepare(`
      UPDATE token SET revoked_at=? WHERE revoked_at IS NULL AND human_id IN
        (SELECT id FROM human WHERE team_id=? AND handle=?)`
    ).run(now, team, handle)
    deps.db.prepare(
      "INSERT INTO audit_log(team_id,at,actor_human_id,event,detail_json) VALUES (?,?,?,?,?)"
    ).run(team, now, c.get('human').id, 'user.disable', JSON.stringify({ handle }))
    return c.json({ ok: true, hard: false })
  })

  app.post('/purge-inactive', async c => {
    const body = await c.req.json().catch(() => ({})) as { days?: number }
    const days = Math.max(1, Math.floor(body.days ?? 30))
    const team = c.get('team_id')
    const cutoff = new Date(deps.now().getTime() - days * 24 * 60 * 60 * 1000).toISOString()
    const result = purgeInactive(deps.db, team, cutoff, c.get('human').id, deps.now().toISOString())
    return c.json({ purged: result.handles, days })
  })

  app.get('/tokens', c => {
    const team = c.get('team_id')
    const rows = deps.db.prepare(`
      SELECT t.id, t.label, t.tier, t.created_at, t.revoked_at, h.handle,
             g.role, g.workgroup, g.visible_json, g.machine
      FROM token t JOIN human h ON h.id = t.human_id
      LEFT JOIN token_grant g ON g.token_id = t.id
      WHERE h.team_id=? ORDER BY t.created_at DESC
    `).all(team) as Array<GrantRow & { id: string; label: string; tier: string; created_at: string; revoked_at: string | null; handle: string }>
    return c.json(rows.map(({ role, workgroup, visible_json, machine, ...t }) => {
      const g = grantFromRow(role === null ? undefined : { role, workgroup, visible_json, machine })
      return { ...t, role: g.role, workgroup: g.workgroup, visible: g.visible, machine: g.machine, granted: role !== null }
    }))
  })

  app.put('/tokens/:id/grant', async c => {
    const parsed = GrantBody.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body', issues: parsed.error.issues }, 400)
    const team = c.get('team_id')
    const id = c.req.param('id')
    const tok = deps.db.prepare(`
      SELECT t.id FROM token t JOIN human h ON h.id = t.human_id
      WHERE t.id=? AND h.team_id=? AND t.revoked_at IS NULL
    `).get(id, team) as { id: string } | undefined
    if (!tok) return c.json({ error: 'not_found' }, 404)
    const now = deps.now().toISOString()
    const g = setGrant(deps.db, id, {
      role: parsed.data.role, workgroup: parsed.data.workgroup, visible: parsed.data.visible, machine: parsed.data.machine ?? null,
    }, now)
    audit(deps.db, team, c.get('human').id, 'token.grant', { token_id: id, role: g.role, workgroup: g.workgroup, visible: g.visible, machine: g.machine }, now)
    return c.json({ token_id: id, ...g })
  })

  app.delete('/tokens/:id', c => {
    const team = c.get('team_id')
    const id = c.req.param('id')
    const now = deps.now().toISOString()
    const info = deps.db.prepare(`
      UPDATE token SET revoked_at=?
      WHERE id=? AND revoked_at IS NULL AND human_id IN (SELECT id FROM human WHERE team_id=?)
    `).run(now, id, team)
    if (info.changes === 0) return c.json({ error: 'not_found' }, 404)
    deps.db.prepare(
      "INSERT INTO audit_log(team_id,at,actor_human_id,event,detail_json) VALUES (?,?,?,?,?)"
    ).run(team, now, c.get('human').id, 'token.revoke', JSON.stringify({ token_id: id }))
    return c.json({ ok: true })
  })

  app.get('/audit', c => {
    const team = c.get('team_id')
    const since = c.req.query('since') ?? '1970-01-01T00:00:00Z'
    const rows = deps.db.prepare(
      "SELECT id, at, actor_human_id, event, detail_json FROM audit_log WHERE team_id=? AND at >= ? ORDER BY at ASC LIMIT 1000"
    ).all(team, since) as AuditRow[]
    return c.json(rows.map(r => ({ ...r, detail: JSON.parse(r.detail_json) })))
  })

  return app
}
