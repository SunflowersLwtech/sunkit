import type { Envelope } from '@claude-mesh/shared'
import { TEAM_BROADCAST_HANDLE } from '@claude-mesh/shared'

export interface Subscriber {
  handle: string
  team_id: string
  /** Set when the stream belongs to a specific Claude Code session. */
  session?: string
  deliver: (e: Envelope) => void
}

export class Fanout {
  // team_id -> handle -> Set<Subscriber>
  private subs = new Map<string, Map<string, Set<Subscriber>>>()

  subscribe(sub: Subscriber): void {
    let byHandle = this.subs.get(sub.team_id)
    if (!byHandle) {
      byHandle = new Map()
      this.subs.set(sub.team_id, byHandle)
    }
    let set = byHandle.get(sub.handle)
    if (!set) {
      set = new Set()
      byHandle.set(sub.handle, set)
    }
    set.add(sub)
  }

  unsubscribe(sub: Subscriber): void {
    const byHandle = this.subs.get(sub.team_id)
    if (!byHandle) return
    const set = byHandle.get(sub.handle)
    if (!set) return
    set.delete(sub)
    if (set.size === 0) byHandle.delete(sub.handle)
  }

  deliver(e: Envelope): void {
    const byHandle = this.subs.get(e.team)
    if (!byHandle) return
    if (e.to === TEAM_BROADCAST_HANDLE) {
      for (const [handle, set] of byHandle) {
        if (handle === e.from) continue
        for (const sub of set) sub.deliver(e)
      }
      return
    }
    const set = byHandle.get(e.to)
    if (!set) return
    for (const sub of set) {
      if (e.to_session && sub.session !== e.to_session) continue
      sub.deliver(e)
    }
  }

  isSessionOnline(team_id: string, handle: string, session: string): boolean {
    for (const sub of this.subs.get(team_id)?.get(handle) ?? []) {
      if (sub.session === session) return true
    }
    return false
  }

  onlineHandles(team_id: string): string[] {
    return Array.from(this.subs.get(team_id)?.keys() ?? [])
  }

  isOnline(team_id: string, handle: string): boolean {
    return (this.subs.get(team_id)?.get(handle)?.size ?? 0) > 0
  }
}
