import {
  EnvelopeSchema,
  envelopeFromRow,
  newMessageId,
  PROTOCOL_VERSION,
  TEAM_BROADCAST_HANDLE,
  type Envelope,
  type EnvelopeRow,
  type OutboundMessage,
} from '@claude-mesh/shared'
import type { Db } from '../db/db.ts'

export class MessageStore {
  constructor(private readonly db: Db) {}

  insert(
    team_id: string,
    from_handle: string,
    msg: OutboundMessage,
    sender: { session: string; name: string; login?: string } | null = null,
  ): Envelope {
    if (msg.to !== TEAM_BROADCAST_HANDLE) {
      const rcpt = this.db.prepare(
        "SELECT 1 AS x FROM human WHERE team_id=? AND handle=? AND disabled_at IS NULL"
      ).get(team_id, msg.to)
      if (!rcpt) throw new Error(`unknown recipient: ${msg.to}`)
    }

    let thread_root: string | null = null
    if (msg.in_reply_to) {
      const parent = this.db.prepare(
        "SELECT thread_root, id FROM message WHERE id=? AND team_id=?"
      ).get(msg.in_reply_to, team_id) as { thread_root: string | null; id: string } | undefined
      if (!parent) throw new Error(`unknown in_reply_to: ${msg.in_reply_to}`)
      thread_root = parent.thread_root ?? parent.id
    }

    const envelope: Envelope = EnvelopeSchema.parse({
      id: newMessageId(),
      v: PROTOCOL_VERSION,
      team: team_id,
      from: from_handle,
      to: msg.to,
      in_reply_to: msg.in_reply_to ?? null,
      thread_root,
      kind: msg.kind,
      content: msg.content,
      meta: msg.meta ?? {},
      sent_at: new Date().toISOString(),
      delivered_at: null,
      from_session: sender?.session ?? null,
      from_name: sender?.name ?? null,
      to_session: msg.to_session ?? null,
      from_login: sender?.login ?? null,
    })

    this.db.prepare(`
      INSERT INTO message(id,v,team_id,from_handle,to_handle,in_reply_to,thread_root,kind,content,meta_json,sent_at,delivered_at,from_session,from_name,to_session,from_login)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    `).run(
      envelope.id, envelope.v, envelope.team, envelope.from, envelope.to,
      envelope.in_reply_to, envelope.thread_root, envelope.kind, envelope.content,
      JSON.stringify(envelope.meta), envelope.sent_at, envelope.delivered_at,
      envelope.from_session, envelope.from_name, envelope.to_session, envelope.from_login
    )
    return envelope
  }

  /**
   * A session-scoped reader (session !== null) also sees handle-level and
   * broadcast messages, but never messages addressed to a sibling session.
   */
  fetchSince(team_id: string, to_handle: string, since_id: string, session: string | null = null): Envelope[] {
    const rows = this.db.prepare(`
      SELECT id, v, team_id, from_handle, to_handle, in_reply_to, thread_root,
             kind, content, meta_json, sent_at, delivered_at, from_session, from_name, to_session, from_login
      FROM message
      WHERE team_id=? AND id > ?
        AND (to_handle=? OR (to_handle='@team' AND from_handle != ?))
        AND (to_session IS NULL OR to_session = ?)
      ORDER BY id ASC LIMIT 1000
    `).all(team_id, since_id, to_handle, to_handle, session) as EnvelopeRow[]
    return rows.map(envelopeFromRow)
  }

  fetchPendingFor(team_id: string, to_handle: string, session: string | null = null): Envelope[] {
    const rows = this.db.prepare(`
      SELECT id, v, team_id, from_handle, to_handle, in_reply_to, thread_root,
             kind, content, meta_json, sent_at, delivered_at, from_session, from_name, to_session, from_login
      FROM message
      WHERE team_id=? AND delivered_at IS NULL
        AND (to_handle=? OR (to_handle='@team' AND from_handle != ?))
        AND (to_session IS NULL OR to_session = ?)
      ORDER BY id ASC LIMIT 1000
    `).all(team_id, to_handle, to_handle, session) as EnvelopeRow[]
    return rows.map(envelopeFromRow)
  }

  markDelivered(id: string): void {
    this.db.prepare(
      "UPDATE message SET delivered_at=COALESCE(delivered_at,?) WHERE id=?"
    ).run(new Date().toISOString(), id)
  }
}
