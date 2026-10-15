import { readFileSync } from 'node:fs'
import type { MessageId, OutboundMessage } from '@claude-mesh/shared'
import { loadConfig, loadToken } from '../config.ts'
import { RelayClient } from '../outbound.ts'
import { formatAddress, resolveTarget } from '../resolve-target.ts'
import { sanitizeName } from '../session-identity.ts'

export const SAY_USAGE = 'usage: mesh say [--as <name>] [--reply-to <msg_id>] <to> <message…|->   (name defaults to $MESH_SESSION_NAME; "-" reads the message from stdin)'

export interface SayArgs {
  as: string
  to: string
  message: string
  replyTo?: string
}

/** Parse `say` arguments; the message is the rest of the line, or stdin when it is "-". */
export function parseSayArgs(args: string[], env: NodeJS.ProcessEnv, stdin?: () => string): SayArgs {
  const rest: string[] = []
  let as: string | undefined
  let replyTo: string | undefined
  for (let i = 0; i < args.length; i++) {
    const a = args[i]!
    if (a === '--as') { as = args[++i]; continue }
    if (a === '--reply-to') { replyTo = args[++i]; continue }
    if (a === '--relay') { i++; continue }
    rest.push(a)
  }
  const [to, ...words] = rest
  let message = words.join(' ')
  if (message === '-' && stdin) message = stdin()
  const name = (as ?? env.MESH_SESSION_NAME ?? '').trim()
  if (!to || !message.trim() || !name) throw new Error(SAY_USAGE)
  return { as: sanitizeName(name), to, message, ...(replyTo ? { replyTo } : {}) }
}

/**
 * Send one message as a named, send-only sender: for scripts and agents that have
 * no MCP connection to the mesh. Nothing is registered, so nothing can be addressed
 * back to this name unless a live session also carries it.
 */
export async function sayWith(client: Pick<RelayClient, 'listSessions' | 'send'>, a: SayArgs): Promise<string> {
  const r = resolveTarget(a.to, await client.listSessions(), '')
  if (!r.ok) throw new Error(r.error)
  const payload: OutboundMessage = {
    to: r.target.account,
    to_session: r.target.session_id,
    kind: 'chat',
    content: a.message,
    meta: {},
  }
  if (a.replyTo) payload.in_reply_to = a.replyTo as MessageId
  const env = await client.send(payload)
  const state = env.delivered_at ? 'delivered' : 'queued (session reconnecting)'
  return `${state} to ${formatAddress(r.target)} as ${a.as} (${env.id})`
}

export async function runSay(args: string[]): Promise<void> {
  const a = parseSayArgs(args, process.env, () => readFileSync(0, 'utf8'))
  const cfg = loadConfig()
  const relayUrl = args.includes('--relay') ? args[args.indexOf('--relay') + 1]! : cfg.relay_url
  const client = new RelayClient({ relayUrl, token: loadToken(cfg.token_path), senderName: a.as })
  console.log(await sayWith(client, a))
}
