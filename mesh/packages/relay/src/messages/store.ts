import {
  EnvelopeSchema,
  envelopeFromRow,
  newMessageId,
  PROTOCOL_VERSION,
  sessionRef,
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

/** What the relay knows about a send besides the message itself, kept in the delivery log. */
export interface SendTrace {
  /** The sender token's label (its device). */
  from_device?: string
  /** The addressed session, for session-addressed messages. */
  to?: { name: string; device: string; workgroup: string }
}

/** Who took a message off the relay: a live stream at send time, or a stream that connected later. */
export interface DeliveryTrace {
  via: 'live' | 'backlog'
  name?: string
  device?: string
}

/** Delivery log rows older than this are dropped by the ledger sweeper. */
export const EVENT_RETENTION_DAYS = 14

export interface EventParty {
  account: string
  name?: string
  ref?: string
  device?: string
}

/** One row of GET /v1/events. Metadata only: the message content never leaves through here. */
export interface DeliveryEventView {
  seq: number
  at: string
  msg_id: string
  state: 'sent' | 'delivered'
  from: EventParty
  to: EventParty
  bytes: number
  sent_at: string
  /** delivered only: delivered at minus sent at, both relay clock. */
  latency_ms?: number
  via?: 'live' | 'backlog'
}

interface EventRow {
  seq: number
  state: 'sent' | 'delivered'
  at: string
  via: 'live' | 'backlog' | null
  d_name: string | null
  d_device: string | null
  from_device: string | null
  s_to_name: string | null
  s_to_device: string | null
  msg_id: string
  from_handle: string
  from_name: string | null
  from_session: string | null
  to_handle: string
  to_session: string | null
  sent_at: string
  bytes: number
}

export class MessageStore {
  constructor(private readonly db: Db, private readonly now: () => Date = () => new Date()) {}

  insert(
    team_id: string,
    from_handle: string,
    msg: OutboundMessage,
    sender: { session?: string; name: string; login?: string } | null = null,
    route?: Route,
    trace?: SendTrace,
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
      sent_at: this.now().toISOString(),
      delivered_at: null,
      from_session: sender?.session ?? null,
      from_name: sender?.name ?? null,
      to_session: msg.to_session ?? null,
      from_login: sender?.login ?? null,
    })

    this.db.transaction(() => {
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
      // Only conversation is logged; presence and permission traffic would drown it.
      if (envelope.kind === 'chat') {
        this.db.prepare(`
          INSERT INTO delivery_event(team_id,msg_id,state,at,from_device,to_name,to_device,to_wg,via)
          VALUES (?,?,'sent',?,?,?,?,?,NULL)
        `).run(team_id, envelope.id, envelope.sent_at, trace?.from_device ?? null,
          trace?.to?.name ?? null, trace?.to?.device ?? null, trace?.to?.workgroup ?? null)
      }
    })()
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

  /**
   * Stamps the first delivery and logs it; later calls for the same message change nothing.
   * `how` says which stream took it (absent: a live stream already counted at send time).
   */
  markDelivered(id: string, how: DeliveryTrace = { via: 'live' }): void {
    const at = this.now().toISOString()
    this.db.transaction(() => {
      const row = this.db.prepare(
        "UPDATE message SET delivered_at=? WHERE id=? AND delivered_at IS NULL RETURNING team_id, kind"
      ).get(at, id) as { team_id: string; kind: string } | undefined
      if (!row || row.kind !== 'chat') return
      this.db.prepare(`
        INSERT INTO delivery_event(team_id,msg_id,state,at,from_device,to_name,to_device,to_wg,via)
        VALUES (?,?,'delivered',?,NULL,?,?,NULL,?)
      `).run(row.team_id, id, at, how.name ?? null, how.device ?? null, how.via)
    })()
  }

  /**
   * The delivery log as `visible` may see it: a row shows when the reader may see the sender's
   * workgroup and, for a session-addressed message, the addressed session's workgroup.
   * With `sinceSeq`, rows after it in order; without, the latest `limit` rows (still in order).
   * `seq` is where the next call resumes.
   */
  events(team_id: string, visible: readonly string[], opts: { sinceSeq?: number; limit: number }): { events: DeliveryEventView[]; seq: number } {
    const tail = opts.sinceSeq === undefined
    const rows = this.db.prepare(`
      SELECT e.seq, e.state, e.at, e.via, e.to_name AS d_name, e.to_device AS d_device,
             s.from_device, s.to_name AS s_to_name, s.to_device AS s_to_device,
             m.id AS msg_id, m.from_handle, m.from_name, m.from_session, m.to_handle, m.to_session, m.sent_at,
             length(CAST(m.content AS BLOB)) AS bytes
      FROM delivery_event e
      JOIN message m ON m.id = e.msg_id AND m.team_id = e.team_id
      LEFT JOIN delivery_event s ON s.msg_id = e.msg_id AND s.state = 'sent'
      WHERE e.team_id = @team ${tail ? '' : 'AND e.seq > @since'}
        AND (m.from_wg IS NULL OR m.from_wg IN (SELECT value FROM json_each(@visible)))
        -- Fail closed without the sent row: retention may drop it before the delivered one,
        -- and a message stored before this log existed never had one. Treating its absence
        -- as "no addressed session" would show the recipient's session to readers the
        -- addressed-workgroup check is exactly meant to hide.
        AND s.seq IS NOT NULL
        AND (s.to_wg IS NULL OR s.to_wg IN (SELECT value FROM json_each(@visible)))
      ORDER BY e.seq ${tail ? 'DESC' : 'ASC'} LIMIT @limit
    `).all({ team: team_id, since: opts.sinceSeq ?? 0, visible: JSON.stringify(visible), limit: opts.limit }) as EventRow[]
    if (tail) rows.reverse()
    const max = (this.db.prepare('SELECT MAX(seq) AS s FROM delivery_event WHERE team_id=?').get(team_id) as { s: number | null }).s ?? 0
    // A full page in order resumes from its last row; anything else has seen the whole log.
    const seq = !tail && rows.length === opts.limit ? rows[rows.length - 1]!.seq : Math.max(opts.sinceSeq ?? 0, max)
    return { events: rows.map(eventView), seq }
  }

  /** Drops delivery log rows older than the retention; returns how many went. */
  sweepEvents(): number {
    const cutoff = new Date(this.now().getTime() - EVENT_RETENTION_DAYS * 86_400_000).toISOString()
    return this.db.prepare('DELETE FROM delivery_event WHERE at < ?').run(cutoff).changes
  }
}

function eventView(r: EventRow): DeliveryEventView {
  const from: EventParty = { account: r.from_handle }
  if (r.from_name) from.name = r.from_name
  if (r.from_session) from.ref = sessionRef(r.from_session)
  if (r.from_device) from.device = r.from_device
  const to: EventParty = { account: r.to_handle }
  const toName = r.d_name ?? r.s_to_name
  const toDevice = r.d_device ?? r.s_to_device
  if (toName) to.name = toName
  if (r.to_session) to.ref = sessionRef(r.to_session)
  if (toDevice) to.device = toDevice
  const v: DeliveryEventView = { seq: r.seq, at: r.at, msg_id: r.msg_id, state: r.state, from, to, bytes: r.bytes, sent_at: r.sent_at }
  if (r.state === 'delivered') {
    v.latency_ms = Math.max(0, Date.parse(r.at) - Date.parse(r.sent_at))
    if (r.via) v.via = r.via
  }
  return v
}

function viewerParams(viewer: Viewer | undefined): Record<string, string> {
  return viewer ? { wg: viewer.workgroup, visible: JSON.stringify(viewer.visible) } : {}
}
