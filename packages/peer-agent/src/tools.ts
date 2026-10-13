import { z } from 'zod'
import type { OutboundMessage, MessageId } from '@claude-mesh/shared'
import type { RelayClient } from './outbound.ts'
import type { ReplyLimiter } from './reply-limiter.ts'
import { resolveTarget, formatListing, formatAddress } from './resolve-target.ts'

const ListInput = z.object({}).strict()
const SendMessageInput = z.object({
  to: z.string().min(1),
  message: z.string().min(1),
  in_reply_to: z.string().optional(),
}).strict()

export const TOOL_DESCRIPTORS = [
  {
    name: 'list_agents',
    description: 'List the live Claude Code sessions on the mesh — including sessions signed in to other accounts on other machines — that send_message can reach. Each row is "name [ref] — account@device · busy|idle · cwd".',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'send_message',
    description: 'Send a message to another Claude Code session on the mesh. `to` is a session name from list_agents, or "name [ref]" when a name is shared; to reply, copy the incoming message\'s from attribute. The recipient sees the first line as a preview, so make it a clear, self-contained sentence.',
    inputSchema: {
      type: 'object',
      properties: {
        to: { type: 'string', description: 'session name, or "name [ref]"' },
        message: { type: 'string' },
        in_reply_to: { type: 'string', description: 'msg_id being answered (optional)' },
      },
      required: ['to', 'message'],
    },
  },
] as const

export interface ToolOpts {
  /** This session's id; excluded from send targets and marked in listings. */
  selfSessionId: string
  replyLimiter?: ReplyLimiter | undefined
}

export function registerTools(client: RelayClient, opts: ToolOpts) {
  const { selfSessionId, replyLimiter } = opts
  async function callTool(name: string, args: unknown): Promise<{ content: Array<{ type: 'text'; text: string }> }> {
    if (name === 'list_agents') {
      ListInput.parse(args)
      const rows = await client.listSessions()
      return { content: [{ type: 'text', text: formatListing(rows, selfSessionId) }] }
    }
    if (name === 'send_message') {
      const input = SendMessageInput.parse(args)
      const r = resolveTarget(input.to, await client.listSessions(), selfSessionId)
      if (!r.ok) throw new Error(r.error)
      const address = formatAddress(r.target)
      if (replyLimiter && !replyLimiter.canReplyTo(address)) {
        throw new Error(`loop guard: too many messages to ${address} in the last few seconds; ask your user before continuing`)
      }
      const payload: OutboundMessage = {
        to: r.target.account,
        to_session: r.target.session_id,
        kind: 'chat',
        content: input.message,
        meta: {},
      }
      if (input.in_reply_to !== undefined) payload.in_reply_to = input.in_reply_to as MessageId
      const env = await client.send(payload)
      replyLimiter?.recordOutbound(address)
      const state = env.delivered_at ? 'delivered' : 'queued (session reconnecting)'
      return { content: [{ type: 'text', text: `${state} to ${address} (${env.id})` }] }
    }
    throw new Error(`unknown tool: ${name}`)
  }
  return { callTool }
}
