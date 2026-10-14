import { META_KEY_REGEX, CHANNEL_SOURCE_PEERS } from './constants.ts'
import { sessionRef, type Envelope } from './envelope.ts'

export interface ChannelNotification {
  method: string
  params: {
    content: string
    meta: Record<string, string>
    request_id?: string
    tool_name?: string
    description?: string
    input_preview?: string
    behavior?: 'allow' | 'deny'
  }
}

export function envelopeToChannelNotification(e: Envelope): ChannelNotification {
  const safeMeta = sanitizeMeta(e.meta)

  if (e.kind === 'permission_request') {
    return {
      method: 'notifications/claude/channel/permission_request',
      params: {
        content: e.content,
        meta: safeMeta,
        request_id: safeMeta.request_id ?? '',
        tool_name: safeMeta.tool_name ?? '',
        description: e.content,
        input_preview: safeMeta.input_preview ?? ''
      }
    }
  }

  if (e.kind === 'permission_verdict') {
    return {
      method: 'notifications/claude/channel/permission',
      params: {
        content: '',
        meta: safeMeta,
        request_id: safeMeta.request_id ?? '',
        behavior: safeMeta.behavior === 'deny' ? 'deny' : 'allow'
      }
    }
  }

  return {
    method: 'notifications/claude/channel',
    params: {
      content: escapeChannelBody(e.content),
      // Sender-controlled meta goes first so relay-set identity fields always win.
      meta: {
        ...withoutReserved(safeMeta),
        // `from` is the reply address: the sender's session when it has one, else its handle.
        from: e.from_session && e.from_name ? `${e.from_name} [${sessionRef(e.from_session)}]` : e.from,
        account: e.from,
        ...(e.from_login ? { login: e.from_login } : {}),
        msg_id: e.id,
        ...(e.in_reply_to ? { in_reply_to: e.in_reply_to } : {}),
        ...(e.thread_root ? { thread_root: e.thread_root } : {}),
        source: CHANNEL_SOURCE_PEERS
      }
    }
  }
}

const RESERVED_META_KEYS = new Set(['from', 'account', 'login', 'msg_id', 'in_reply_to', 'thread_root', 'source'])

function withoutReserved(meta: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(meta).filter(([k]) => !RESERVED_META_KEYS.has(k)))
}

function sanitizeMeta(meta: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(meta)) {
    if (META_KEY_REGEX.test(k)) out[k] = escapeChannelAttr(v)
  }
  return out
}

export function escapeChannelAttr(s: string): string {
  return s.replace(/[<>&"]/g, c =>
    c === '<' ? '&lt;' : c === '>' ? '&gt;' : c === '&' ? '&amp;' : '&quot;')
}

export function escapeChannelBody(s: string): string {
  return s.replace(/[<>&]/g, c =>
    c === '<' ? '&lt;' : c === '>' ? '&gt;' : '&amp;')
}
