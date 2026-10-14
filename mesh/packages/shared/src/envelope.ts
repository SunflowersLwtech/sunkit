import { z } from 'zod'
import {
  HANDLE_REGEX, META_KEY_REGEX, MAX_CONTENT_BYTES,
  MAX_META_KEY_LENGTH, MAX_META_VALUE_LENGTH,
  PROTOCOL_VERSION, TEAM_BROADCAST_HANDLE
} from './constants.ts'

export const AddressSchema = z.union([
  z.string().regex(HANDLE_REGEX, 'handle'),
  z.literal(TEAM_BROADCAST_HANDLE)
])

export const KindSchema = z.enum([
  'chat', 'presence_update', 'permission_request', 'permission_verdict'
])

export const MetaSchema = z.record(
  z.string().regex(META_KEY_REGEX).max(MAX_META_KEY_LENGTH),
  z.string().max(MAX_META_VALUE_LENGTH)
).default({})

const ContentSchema = z.string().refine(
  s => Buffer.byteLength(s, 'utf8') <= MAX_CONTENT_BYTES,
  { message: `content exceeds ${MAX_CONTENT_BYTES} bytes` }
)

const MessageIdSchema = z.string().regex(/^msg_[0-9A-HJKMNP-TV-Z]{26}$/)

/** Session ids are minted by each peer-agent (one per Claude Code session). */
export const SESSION_ID_REGEX = /^s_[0-9a-z]{16,32}$/
export const SessionIdSchema = z.string().regex(SESSION_ID_REGEX)
/** Human-readable session name, mirroring Claude Code's own session names. */
/** Short disambiguator shown as `name [ref]`, like Claude Code's own ListAgents rows. */
export function sessionRef(sessionId: string): string {
  return sessionId.slice(-6)
}
/** Self-reported Claude login of the sending machine (display only; never an identity). */
export const LoginSchema = z.string().min(3).max(254).regex(/^[^\s<>"&]+@[^\s<>"&]+$/)
export const SessionNameSchema = z.string().min(1).max(64).regex(/^[^\s\[\]<>"&]+$/)

export const EnvelopeSchema = z.object({
  id: MessageIdSchema,
  v: z.literal(PROTOCOL_VERSION),
  team: z.string().min(1).max(64),
  from: z.string().regex(HANDLE_REGEX),
  to: AddressSchema,
  in_reply_to: MessageIdSchema.nullable(),
  thread_root: MessageIdSchema.nullable(),
  kind: KindSchema,
  content: ContentSchema,
  meta: MetaSchema,
  sent_at: z.string().datetime(),
  delivered_at: z.string().datetime().nullable(),
  // Session addressing. All three are set by the relay, never trusted from clients.
  from_session: SessionIdSchema.nullable().default(null),
  from_name: SessionNameSchema.nullable().default(null),
  to_session: SessionIdSchema.nullable().default(null),
  from_login: LoginSchema.nullable().default(null)
}).superRefine((e, ctx) => {
  if (e.kind === 'permission_verdict' && e.in_reply_to === null) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ['in_reply_to'],
      message: 'permission_verdict requires in_reply_to referencing the permission_request'
    })
  }
})
export type Envelope = z.infer<typeof EnvelopeSchema>

export const OutboundMessageSchema = z.object({
  to: AddressSchema,
  kind: KindSchema,
  content: ContentSchema,
  meta: MetaSchema.optional(),
  in_reply_to: MessageIdSchema.nullable().optional(),
  to_session: SessionIdSchema.optional()
}).strict()
export type OutboundMessage = z.infer<typeof OutboundMessageSchema>

export interface EnvelopeRow {
  id: string
  v: number
  team_id: string
  from_handle: string
  to_handle: string
  in_reply_to: string | null
  thread_root: string | null
  kind: Envelope['kind']
  content: string
  meta_json: string
  sent_at: string
  delivered_at: string | null
  from_session?: string | null
  from_name?: string | null
  to_session?: string | null
  from_login?: string | null
}

export function envelopeToRow(e: Envelope): EnvelopeRow {
  return {
    id: e.id, v: e.v, team_id: e.team,
    from_handle: e.from, to_handle: e.to,
    in_reply_to: e.in_reply_to, thread_root: e.thread_root,
    kind: e.kind, content: e.content,
    meta_json: JSON.stringify(e.meta),
    sent_at: e.sent_at, delivered_at: e.delivered_at,
    from_session: e.from_session, from_name: e.from_name, to_session: e.to_session,
    from_login: e.from_login
  }
}

export function envelopeFromRow(row: EnvelopeRow): Envelope {
  return EnvelopeSchema.parse({
    id: row.id, v: row.v, team: row.team_id,
    from: row.from_handle, to: row.to_handle,
    in_reply_to: row.in_reply_to, thread_root: row.thread_root,
    kind: row.kind, content: row.content,
    meta: JSON.parse(row.meta_json) as Record<string, string>,
    sent_at: row.sent_at, delivered_at: row.delivered_at,
    from_session: row.from_session ?? null, from_name: row.from_name ?? null,
    to_session: row.to_session ?? null,
    from_login: row.from_login ?? null
  })
}
