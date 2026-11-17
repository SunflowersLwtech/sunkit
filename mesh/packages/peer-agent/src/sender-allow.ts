import type { Envelope } from '@claude-mesh/shared'

export type AllowVerdict = 'ok' | 'send-only' | 'not-listed' | 'foreign-account' | 'no-own-account' | 'unpinned' | 'no-token' | 'wrong-token'

function splitPin(entry: string): { name: string; token?: string } {
  const i = entry.lastIndexOf('@')
  return i < 0 ? { name: entry } : { name: entry.slice(0, i), token: entry.slice(i + 1) }
}

/**
 * MESH_ALLOW: the session-token pairs this peer takes mail from, comma-separated
 * `<name>@<token-id>` pins. A bare name is a config error (never an allow-list) — the same rule
 * `mesh bossai wake --approvers` applies. Unset or blank means no allow-list (every gated sender).
 */
export function parseAllow(value: string | undefined): string[] | undefined {
  const entries = (value ?? '').split(',').map(s => s.trim()).filter(Boolean)
  if (entries.length === 0) return undefined
  for (const e of entries) {
    if (!/^[^\s@\[\]<>"&]+@[A-Za-z0-9_-]{1,64}$/.test(e)) {
      throw new Error(`MESH_ALLOW entry "${e}" must be <session-name>@<token-id> (token ids: GET /v1/admin/tokens)`)
    }
  }
  return entries
}

/**
 * The rule `mesh bossai wake --allow` applies at the peer itself: a pull host (BossAI) reads its
 * own mail with read_messages while a turn runs, and that mail never passes through wake. Only a
 * live session counts (a send-only sender's name is a label any script on the account chooses),
 * its name must equal an allowed name exactly (no prefixes: `feishu-assistant-x` is not
 * `feishu-assistant`), the relay-verified account must be this peer's own, and the letter must
 * carry the relay-stamped id of the pinned token. A bare entry is `unpinned` and never ok — the
 * config is wrong, so nothing is let through. Unknown own account fails closed.
 */
export function allowVerdict(
  e: Pick<Envelope, 'from' | 'from_session' | 'from_name' | 'from_token'>,
  allow: string[],
  ownAccount: string | undefined,
): AllowVerdict {
  if (!e.from_session || !e.from_name) return 'send-only'
  const entries = allow.map(splitPin).filter(a => a.name === e.from_name)
  if (entries.length === 0) return 'not-listed'
  if (!ownAccount) return 'no-own-account'
  if (e.from !== ownAccount) return 'foreign-account'
  const pins = entries.filter(a => a.token)
  if (pins.length === 0) return 'unpinned'
  if (!e.from_token) return 'no-token'
  return pins.some(a => a.token === e.from_token) ? 'ok' : 'wrong-token'
}
