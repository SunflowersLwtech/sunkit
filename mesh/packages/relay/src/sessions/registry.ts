import { sessionRef, type AgentKind, type HerdrLocation, type Role } from '@claude-mesh/shared'

export type SessionStatus = 'busy' | 'idle' | 'unknown'
/** push: the host shows messages as they arrive (Claude Code channels); pull: the host reads them when it checks its inbox. */
export type SessionMode = 'push' | 'pull'

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
  mode: SessionMode
  streams: number
  last_seen: string
  /** Epoch ms when the last stream closed; the entry stays addressable until the grace period ends. */
  detached_at?: number
  /** Set by the relay from the token's grant (or a granted move); never taken from the client as-is. */
  workgroup: string
  /** True once the session moved itself (a granted self-update); only a move survives a reconnect. */
  wg_moved?: boolean
  /** The token's role at attach time; display only, every check re-reads the request token's grant. */
  role: Role
  card: SessionCard
  /** Epoch ms of the last card write (attach or self-update). */
  card_at: number
}

/** The A2A-style card a session's host writes about itself (fixed fields, validated upstream). */
export interface SessionCard {
  agent?: AgentKind
  model?: string
  repo?: string
  branch?: string
  herdr?: HerdrLocation
  task_id?: string
  source?: 'hook' | 'poll' | 'manual'
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
  mode: SessionMode
  last_seen: string
  workgroup: string
  role: Role
  agent?: AgentKind
  model?: string
  repo?: string
  branch?: string
  herdr?: HerdrLocation
  task_id?: string
  source?: 'hook' | 'poll' | 'manual'
  /** Relay time of the last card write, and its age, so clients with skewed clocks agree. */
  updated_at: string
  age_s: number
}

export type CardPatch = { [K in keyof SessionCard]?: SessionCard[K] | undefined } & {
  name?: string | undefined
  cwd?: string | undefined
  login?: string | undefined
  status?: SessionStatus | undefined
  workgroup?: string | undefined
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
  mode?: SessionMode | undefined
  workgroup?: string | undefined
  /** The token's granted workgroups: a reconnect keeps an earlier move only while it is still granted. */
  visible?: readonly string[] | undefined
  role?: Role | undefined
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
      mode: input.mode ?? existing?.mode ?? 'push',
      streams: (existing?.streams ?? 0) + 1,
      last_seen: new Date(this.now()).toISOString(),
      // A reconnect keeps a granted move (e.g. into the shared workgroup) and the card.
      // A session follows its token's current grant on every reconnect, except one that moved
      // itself into another workgroup the token is still granted.
      workgroup: existing?.wg_moved && (input.visible ?? []).includes(existing.workgroup)
        ? existing.workgroup
        : input.workgroup ?? 'team',
      ...(existing?.wg_moved && (input.visible ?? []).includes(existing.workgroup) ? { wg_moved: true } : {}),
      role: input.role ?? existing?.role ?? 'worker',
      card: existing?.card ?? {},
      card_at: existing?.card_at ?? this.now(),
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

  update(session_id: string, token_id: string, patch: CardPatch): boolean {
    const e = this.owned(session_id, token_id)
    if (!e) return false
    if (patch.name !== undefined) e.name = patch.name
    if (patch.cwd !== undefined) e.cwd = patch.cwd
    if (patch.login !== undefined) e.login = patch.login
    if (patch.status !== undefined) e.status = patch.status
    if (patch.workgroup !== undefined) { e.workgroup = patch.workgroup; e.wg_moved = true }
    const card: SessionCard = { ...e.card }
    for (const k of ['agent', 'model', 'repo', 'branch', 'herdr', 'task_id', 'source'] as const) {
      if (patch[k] !== undefined) (card as Record<string, unknown>)[k] = patch[k]
    }
    e.card = card
    e.card_at = this.now()
    e.last_seen = new Date(this.now()).toISOString()
    return true
  }

  /** Sessions of the team whose workgroup is in `visible` (all of them when `visible` is omitted). */
  listTeam(team_id: string, visible?: readonly string[]): SessionView[] {
    this.sweep()
    const out: SessionView[] = []
    for (const e of this.byId.values()) {
      if (e.team_id !== team_id) continue
      if (visible && !visible.includes(e.workgroup)) continue
      const view: SessionView = {
        session_id: e.session_id,
        ref: sessionRef(e.session_id),
        name: e.name,
        account: e.handle,
        device: e.device,
        status: e.streams > 0 ? e.status : 'reconnecting',
        mode: e.mode,
        last_seen: e.last_seen,
        workgroup: e.workgroup,
        role: e.role,
        ...e.card,
        updated_at: new Date(e.card_at).toISOString(),
        age_s: Math.max(0, Math.floor((this.now() - e.card_at) / 1000)),
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
