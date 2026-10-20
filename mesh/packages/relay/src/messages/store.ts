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
import type { Route, Viewer } from '../fanout.ts'

// A row not addressed to one session is visible to a reader when the sender may reach the
// reader's workgroup and the reader may see the sender's (see routeAllows). Rows written before
// workgroups existed carry NULLs and stay visible, as before.
const ROUTE_FILTER = `
        AND (to_session IS NOT NULL
             OR ((scope_json IS NULL OR EXISTS (SELECT 1 FROM json_each(scope_json) WHERE value = @wg))
                 AND (from_wg IS NULL OR from_wg IN (SELECT value FROM json_each(@visible)))))`

export class MessageStore {
  constructor(private readonly db: Db) {}

  insert(
    team_id: string,
    from_handle: string,
    msg: OutboundMessage,
    sender: { session?: string; name: string; login?: string } | null = null,
    route?: Route,
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
      INSERT INTO message(id,v,team_id,from_handle,to_handle,in_reply_to,thread_root,kind,content,meta_json,sent_at,delivered_at,from_session,from_name,to_session,from_login,from_wg,scope_json)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    `).run(
      envelope.id, envelope.v, envelope.team, envelope.from, envelope.to,
      envelope.in_reply_to, envelope.thread_root, envelope.kind, envelope.content,
      JSON.stringify(envelope.meta), envelope.sent_at, envelope.delivered_at,
      envelope.from_session, envelope.from_name, envelope.to_session, envelope.from_login,
      route?.from_wg ?? null, route ? JSON.stringify(route.scope) : null
    )
    return envelope
  }

  /**
   * A session-scoped reader (session !== null) also sees handle-level and
   * broadcast messages, but never messages addressed to a sibling session.
   */
  fetchSince(team_id: string, to_handle: string, since_id: string, session: string | null = null, viewer?: Viewer): Envelope[] {
    const rows = this.db.prepare(`
      SELECT id, v, team_id, from_handle, to_handle, in_reply_to, thread_root,
             kind, content, meta_json, sent_at, delivered_at, from_session, from_name, to_session, from_login
      FROM message
      WHERE team_id=@team AND id > @since
        AND (to_handle=@handle OR (to_handle='@team' AND from_handle != @handle))
        AND (to_session IS NULL OR to_session = @session)
        ${viewer ? ROUTE_FILTER : ''}
      ORDER BY id ASC LIMIT 1000
    `).all({ team: team_id, since: since_id, handle: to_handle, session, ...viewerParams(viewer) }) as EnvelopeRow[]
    return rows.map(envelopeFromRow)
  }

  fetchPendingFor(team_id: string, to_handle: string, session: string | null = null, viewer?: Viewer): Envelope[] {
    const rows = this.db.prepare(`
      SELECT id, v, team_id, from_handle, to_handle, in_reply_to, thread_root,
             kind, content, meta_json, sent_at, delivered_at, from_session, from_name, to_session, from_login
      FROM message
      WHERE team_id=@team AND delivered_at IS NULL
        AND (to_handle=@handle OR (to_handle='@team' AND from_handle != @handle))
        AND (to_session IS NULL OR to_session = @session)
        ${viewer ? ROUTE_FILTER : ''}
      ORDER BY id ASC LIMIT 1000
    `).all({ team: team_id, handle: to_handle, session, ...viewerParams(viewer) }) as EnvelopeRow[]
    return rows.map(envelopeFromRow)
  }

  markDelivered(id: string): void {
    this.db.prepare(
      "UPDATE message SET delivered_at=COALESCE(delivered_at,?) WHERE id=?"
    ).run(new Date().toISOString(), id)
  }
}

function viewerParams(viewer: Viewer | undefined): Record<string, string> {
  return viewer ? { wg: viewer.workgroup, visible: JSON.stringify(viewer.visible) } : {}
}
