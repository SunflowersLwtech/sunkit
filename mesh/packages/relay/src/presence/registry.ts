export interface PresenceSession {
  label: string
  cwd?: string
  branch?: string
  repo?: string
}

export interface PresenceSnapshot {
  handle: string
  summary: string
  last_seen: string
  sessions: PresenceSession[]
}

interface SessionState {
  label: string
  summary: string
  cwd?: string
  branch?: string
  repo?: string
  last_seen: string
}

export interface PresenceInput {
  summary: string
  cwd?: string | undefined
  branch?: string | undefined
  repo?: string | undefined
}

function copyOptional(src: PresenceInput): Omit<SessionState, 'label' | 'summary' | 'last_seen'> {
  const out: Omit<SessionState, 'label' | 'summary' | 'last_seen'> = {}
  if (src.cwd !== undefined) out.cwd = src.cwd
  if (src.branch !== undefined) out.branch = src.branch
  if (src.repo !== undefined) out.repo = src.repo
  return out
}

function toSession(s: SessionState): PresenceSession {
  const out: PresenceSession = { label: s.label }
  if (s.cwd !== undefined) out.cwd = s.cwd
  if (s.branch !== undefined) out.branch = s.branch
  if (s.repo !== undefined) out.repo = s.repo
  return out
}

export class PresenceRegistry {
  private state = new Map<string, Map<string, Map<string, SessionState>>>()

  constructor(private now: () => Date = () => new Date()) {}

  set(team: string, handle: string, label: string, s: PresenceInput): void {
    let byHandle = this.state.get(team)
    if (!byHandle) {
      byHandle = new Map()
      this.state.set(team, byHandle)
    }
    let byLabel = byHandle.get(handle)
    if (!byLabel) {
      byLabel = new Map()
      byHandle.set(handle, byLabel)
    }
    byLabel.set(label, {
      label,
      summary: s.summary,
      ...copyOptional(s),
      last_seen: this.now().toISOString(),
    })
  }

  remove(team: string, handle: string, label: string): void {
    const byLabel = this.state.get(team)?.get(handle)
    if (!byLabel) return
    byLabel.delete(label)
    if (byLabel.size === 0) this.state.get(team)?.delete(handle)
  }

  get(team: string, handle: string): PresenceSnapshot | undefined {
    const byLabel = this.state.get(team)?.get(handle)
    if (!byLabel || byLabel.size === 0) return undefined
    const sessions = Array.from(byLabel.values())
    const first = sessions[0]!
    const last_seen = sessions.reduce(
      (max, s) => (s.last_seen > max ? s.last_seen : max),
      first.last_seen
    )
    return {
      handle,
      summary: first.summary,
      last_seen,
      sessions: sessions.map(toSession),
    }
  }

  listTeam(team: string): PresenceSnapshot[] {
    const byHandle = this.state.get(team)
    if (!byHandle) return []
    const out: PresenceSnapshot[] = []
    for (const handle of byHandle.keys()) {
      const snap = this.get(team, handle)
      if (snap) out.push(snap)
    }
    return out
  }
}
