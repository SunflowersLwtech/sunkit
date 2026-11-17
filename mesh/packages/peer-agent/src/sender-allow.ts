import type { Envelope } from '@claude-mesh/shared'

export type AllowVerdict = 'ok' | 'send-only' | 'not-listed' | 'foreign-account' | 'no-own-account'

/**
 * MESH_ALLOW: the session names this peer takes mail from, comma-separated. Unset or blank means
 * no allow-list (every gated sender, as before).
 */
export function parseAllow(value: string | undefined): string[] | undefined {
  const names = (value ?? '').split(',').map(s => s.trim()).filter(Boolean)
  return names.length > 0 ? names : undefined
}

/**
 * The rule `mesh bossai wake` applies to --approvers and --allow, at the peer itself: a pull host
 * (BossAI) reads its own mail with read_messages while a turn runs, and that mail never passes
 * through wake. Only a live session counts (a send-only sender's name is a label any script on
 * the account chooses), its name must equal an allowed name exactly (no prefixes:
 * `feishu-assistant-x` is not `feishu-assistant`), and the relay-verified account must be this
 * peer's own. Unknown own account fails closed.
 */
export function allowVerdict(
  e: Pick<Envelope, 'from' | 'from_session' | 'from_name'>,
  allow: string[],
  ownAccount: string | undefined,
): AllowVerdict {
  if (!e.from_session || !e.from_name) return 'send-only'
  if (!allow.includes(e.from_name)) return 'not-listed'
  if (!ownAccount) return 'no-own-account'
  return e.from === ownAccount ? 'ok' : 'foreign-account'
}
