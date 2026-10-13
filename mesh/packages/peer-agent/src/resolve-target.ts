export interface SessionRow {
  session_id: string
  ref: string
  name: string
  account: string
  device: string
  cwd?: string
  login?: string
  status: string
  last_seen: string
}

export type Resolution =
  | { ok: true; target: SessionRow }
  | { ok: false; error: string }

const WITH_REF = /^(.+?) \[([0-9a-z]{6})\]$/

/**
 * Resolve a `to` address the way Claude Code's own SendMessage does: an exact
 * session name, or `name [ref]` to disambiguate. Never resolves to ourselves.
 */
export function resolveTarget(to: string, rows: SessionRow[], selfId: string): Resolution {
  const others = rows.filter(r => r.session_id !== selfId)
  const trimmed = to.trim()
  const m = WITH_REF.exec(trimmed)
  if (m) {
    const hit = others.find(r => r.name === m[1] && r.ref === m[2])
    return hit ? { ok: true, target: hit } : { ok: false, error: `no live session "${trimmed}"; call list_agents for current names` }
  }
  const byName = others.filter(r => r.name === trimmed)
  if (byName.length === 1) return { ok: true, target: byName[0]! }
  if (byName.length > 1) {
    return {
      ok: false,
      error: `"${trimmed}" matches ${byName.length} sessions; resend with one of: ${byName.map(formatAddress).join(', ')}`,
    }
  }
  if (rows.some(r => r.session_id === selfId && r.name === trimmed)) {
    return { ok: false, error: `"${trimmed}" is this session` }
  }
  return { ok: false, error: `no live session named "${trimmed}"; call list_agents for current names` }
}

export function formatAddress(r: SessionRow): string {
  return `${r.name} [${r.ref}]`
}

export function formatListing(rows: SessionRow[], selfId: string): string {
  if (rows.length === 0) return 'No live sessions on the mesh.'
  return rows.map(r => {
    const self = r.session_id === selfId ? ' (this session)' : ''
    const where = r.cwd ? ` · ${r.cwd}` : ''
    const who = r.login ? `${r.login} (mesh ${r.account}@${r.device})` : `${r.account}@${r.device}`
    return `${formatAddress(r)}${self} — ${who} · ${r.status}${where}`
  }).join('\n')
}
