import type { Envelope } from '@claude-mesh/shared'
import { TEAM_BROADCAST_HANDLE } from '@claude-mesh/shared'

/** Who may see a message that is not addressed to one session (a handle or @team). */
export interface Route {
  /** The sender's workgroup. */
  from_wg: string
  /** Workgroups the sender may reach (its token's granted workgroups). */
  scope: readonly string[]
}

/** Which workgroup a subscriber sits in and which ones its token may see. Read on every delivery. */
export interface Viewer { workgroup: string; visible: readonly string[] }

export interface Subscriber {
  handle: string
  team_id: string
  /** Set when the stream belongs to a specific Claude Code session. */
  session?: string
  /** Absent for subscribers that predate workgroups (tests, tools): they see everything, as before. */
  viewer?: () => Viewer
  deliver: (e: Envelope) => void
  /** Non-message SSE events (`event: task`). Old peers skip unknown event names, so this never reaches their parser. */
  deliverEvent?: (event: string, data: string) => void
}

/**
 * A message to one session was checked when it was sent. Anything wider reaches a subscriber
 * only if the sender may reach that subscriber's workgroup and the subscriber may see the sender's.
 */
export function routeAllows(route: Route | undefined, sub: Pick<Subscriber, 'viewer'>): boolean {
  if (!route || !sub.viewer) return true
  const v = sub.viewer()
  return route.scope.includes(v.workgroup) && v.visible.includes(route.from_wg)
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

  /** Returns how many live streams received it: a message nobody in scope received stays pending. */
  deliver(e: Envelope, route?: Route): number {
    const byHandle = this.subs.get(e.team)
    if (!byHandle) return 0
    let n = 0
    if (e.to === TEAM_BROADCAST_HANDLE) {
      for (const [handle, set] of byHandle) {
        if (handle === e.from) continue
        for (const sub of set) if (routeAllows(route, sub)) { sub.deliver(e); n++ }
      }
      return n
    }
    const set = byHandle.get(e.to)
    if (!set) return 0
    for (const sub of set) {
      if (e.to_session && sub.session !== e.to_session) continue
      if (!e.to_session && !routeAllows(route, sub)) continue
      sub.deliver(e)
      n++
    }
    return n
  }

  /** Pushes a ledger event to every live stream of the team that may see `workgroup`. Not stored, not replayed. */
  deliverEvent(team_id: string, workgroup: string, event: string, data: string): number {
    let n = 0
    for (const set of this.subs.get(team_id)?.values() ?? []) {
      for (const sub of set) {
        if (!sub.deliverEvent) continue
        if (sub.viewer && !sub.viewer().visible.includes(workgroup)) continue
        sub.deliverEvent(event, data)
        n++
      }
    }
    return n
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
