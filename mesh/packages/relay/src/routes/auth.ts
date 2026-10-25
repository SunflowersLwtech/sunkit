import { Hono } from 'hono'
import { z } from 'zod'
import { ulid } from 'ulid'
import { generateRawToken, hashToken } from '../auth/hash.ts'
import { parsePairCode } from '../auth/pair-code.ts'
import { bearerAuth, type AuthContext } from '../auth/middleware.ts'
import type { Deps } from '../deps.ts'
import { rateLimit } from '../middleware/rate-limit.ts'
import { inheritGrant } from '../grants.ts'
import { getConnInfo } from '@hono/node-server/conninfo'

/** Pair codes are ~40 bits; cap guesses per source address. */
function clientAddress(c: Parameters<typeof getConnInfo>[0]): string {
  try { return getConnInfo(c).remote.address ?? 'unknown' } catch { return 'unknown' }
}

const PairBody = z.object({
  pair_code: z.string().min(1).max(64),
  device_label: z.string().min(1).max(64),
})

interface PairRow {
  human_id: string
  tier: 'human' | 'admin'
  expires_at: string
  consumed_at: string | null
  team_id: string
  handle: string
  display_name: string
  team_name: string
}

export function authRoute(deps: Deps) {
  const app = new Hono<{ Variables: AuthContext }>()

  app.post('/pair', rateLimit({ windowMs: 60_000, max: 10, key: c => `pair:${clientAddress(c)}` }), async c => {
    const parsed = PairBody.safeParse(await c.req.json().catch(() => null))
    if (!parsed.success) return c.json({ error: 'invalid_body' }, 400)
    if (!parsePairCode(parsed.data.pair_code)) return c.json({ error: 'invalid_code' }, 400)

    const codeHash = hashToken(parsed.data.pair_code)
    const row = deps.db.prepare(`
      SELECT p.human_id, p.tier, p.expires_at, p.consumed_at,
             h.team_id, h.handle, h.display_name, t.name AS team_name
      FROM pair_code p
      JOIN human h ON h.id = p.human_id
      JOIN team t ON t.id = h.team_id
      WHERE p.code_hash=?
    `).get(codeHash) as PairRow | undefined
    if (!row) return c.json({ error: 'invalid_code' }, 400)
    if (row.consumed_at !== null) return c.json({ error: 'code_consumed' }, 400)
    if (new Date(row.expires_at).getTime() < deps.now().getTime()) return c.json({ error: 'code_expired' }, 400)

    const raw = generateRawToken()
    const tokenId = `tk_${ulid()}`
    const nowIso = deps.now().toISOString()
    const tx = deps.db.transaction(() => {
      deps.db.prepare(
        "INSERT INTO token(id,human_id,token_hash,label,tier,created_at) VALUES (?,?,?,?,?,?)"
      ).run(tokenId, row.human_id, hashToken(raw), parsed.data.device_label, row.tier, nowIso)
      deps.db.prepare("UPDATE pair_code SET consumed_at=? WHERE code_hash=?").run(nowIso, codeHash)
      deps.db.prepare("UPDATE human SET last_active_at=? WHERE id=?").run(nowIso, row.human_id)
      const inherited = inheritGrant(deps.db, row.human_id, tokenId, nowIso)
      deps.db.prepare(
        "INSERT INTO audit_log(team_id,at,actor_human_id,event,detail_json) VALUES (?,?,?,?,?)"
      ).run(
        row.team_id, nowIso, row.human_id, 'token.pair',
        JSON.stringify({
          token_id: tokenId, label: parsed.data.device_label, tier: row.tier,
          ...(inherited ? { workgroup: inherited.workgroup, visible: inherited.visible } : {}),
        })
      )
    })
    tx()

    return c.json({
      token: raw,
      human: { handle: row.handle, display_name: row.display_name },
      team: { id: row.team_id, name: row.team_name },
    })
  })

  const revoke = new Hono<{ Variables: AuthContext }>()
  revoke.use('*', bearerAuth(deps.db, { requireTier: 'human' }))
  revoke.post('/', c => {
    const tokenId = c.get('token').id
    const nowIso = deps.now().toISOString()
    deps.db.prepare("UPDATE token SET revoked_at=? WHERE id=?").run(nowIso, tokenId)
    deps.db.prepare(
      "INSERT INTO audit_log(team_id,at,actor_human_id,event,detail_json) VALUES (?,?,?,?,?)"
    ).run(
      c.get('team_id'), nowIso, c.get('human').id, 'token.revoke_self',
      JSON.stringify({ token_id: tokenId })
    )
    return c.json({ ok: true })
  })
  app.route('/revoke', revoke)

  return app
}
