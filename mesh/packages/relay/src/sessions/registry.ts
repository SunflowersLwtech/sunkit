import { sessionRef } from '@claude-mesh/shared'

export type SessionStatus = 'busy' | 'idle' | 'unknown'

export interface SessionEntry {
  session_id: string
  team_id: string
  handle: string
  token_id: string
  device: string
  name: string
  cwd?: string
  login?: string
  status: SessionStatus
  streams: number
  last_seen: string
  /** Epoch ms when the last stream closed; the entry stays addressable until the grace period ends. */
  detached_at?: number
}

export interface SessionView {
  /** Not a secret: sessions are bound to their owner's token, so knowing an id grants nothing. */
  session_id: string
  ref: string
  name: string
  account: string
  device: string
  cwd?: string
  login?: string
  status: SessionStatus | 'reconnecting'
  last_seen: string
}

export interface AttachInput {
  session_id: string
  team_id: string
  handle: string
  token_id: string
  device: string
  name: string
  cwd?: string | undefined
  login?: string | undefined
  status?: SessionStatus | undefined
}

export class SessionOwnershipError extends Error {}

/**
 * Live Claude Code sessions, one per peer-agent process. In-memory on purpose:
 * a session only exists while its peer-agent holds a stream open, so a relay
 * restart correctly forgets everything and peer-agents re-attach on reconnect.
 */
export class SessionRegistry {
  private byId = new Map<string, SessionEntry>()

  constructor(
    private now: () => number = () => Date.now(),
    private graceMs = 60_000,
  ) {}

  attach(input: AttachInput): SessionEntry {
    this.sweep()
    const existing = this.byId.get(input.session_id)
    if (existing && existing.token_id !== input.token_id) {
      throw new SessionOwnershipError(`session ${input.session_id} belongs to another token`)
    }
    const entry: SessionEntry = {
      session_id: input.session_id,
      team_id: input.team_id,
      handle: input.handle,
      token_id: input.token_id,
      device: input.device,
      name: input.name,
      status: input.status ?? existing?.status ?? 'unknown',
      streams: (existing?.streams ?? 0) + 1,
      last_seen: new Date(this.now()).toISOString(),
    }
    const cwd = input.cwd ?? existing?.cwd
    if (cwd !== undefined) entry.cwd = cwd
    const login = input.login ?? existing?.login
    if (login !== undefined) entry.login = login
    this.byId.set(input.session_id, entry)
    return entry
  }

  detach(session_id: string): void {
    const e = this.byId.get(session_id)
    if (!e) return
    e.streams = Math.max(0, e.streams - 1)
    e.last_seen = new Date(this.now()).toISOString()
    if (e.streams === 0) e.detached_at = this.now()
  }

  /** Returns the entry only if `token_id` owns it. */
  owned(session_id: string, token_id: string): SessionEntry | undefined {
    this.sweep()
    const e = this.byId.get(session_id)
    return e && e.token_id === token_id ? e : undefined
  }

  get(session_id: string): SessionEntry | undefined {
    this.sweep()
    return this.byId.get(session_id)
  }

  update(session_id: string, token_id: string, patch: { name?: string | undefined; cwd?: string | undefined; login?: string | undefined; status?: SessionStatus | undefined }): boolean {
    const e = this.owned(session_id, token_id)
    if (!e) return false
    if (patch.name !== undefined) e.name = patch.name
    if (patch.cwd !== undefined) e.cwd = patch.cwd
    if (patch.login !== undefined) e.login = patch.login
    if (patch.status !== undefined) e.status = patch.status
    e.last_seen = new Date(this.now()).toISOString()
    return true
  }

  listTeam(team_id: string): SessionView[] {
    this.sweep()
    const out: SessionView[] = []
    for (const e of this.byId.values()) {
      if (e.team_id !== team_id) continue
      const view: SessionView = {
        session_id: e.session_id,
        ref: sessionRef(e.session_id),
        name: e.name,
        account: e.handle,
        device: e.device,
        status: e.streams > 0 ? e.status : 'reconnecting',
        last_seen: e.last_seen,
      }
      if (e.cwd !== undefined) view.cwd = e.cwd
      if (e.login !== undefined) view.login = e.login
      out.push(view)
    }
    return out.sort((a, b) => a.name.localeCompare(b.name) || a.ref.localeCompare(b.ref))
  }

  private sweep(): void {
    const cutoff = this.now() - this.graceMs
    for (const [id, e] of this.byId) {
      if (e.streams === 0 && e.detached_at !== undefined && e.detached_at < cutoff) this.byId.delete(id)
    }
  }
}
