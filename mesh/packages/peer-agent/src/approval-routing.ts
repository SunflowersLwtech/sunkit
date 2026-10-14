const THREAD_WINDOW_MS = 10 * 60_000

export type RoutingPolicy =
  | 'never_relay'
  | 'ask_thread_participants'
  | 'ask_team'
  | `ask_specific_peer:${string}`

export interface ApprovalRouterCfg { routing: RoutingPolicy }

export class ApprovalRouter {
  private recent = new Map<string, number>() // handle -> timestamp ms

  constructor(private cfg: ApprovalRouterCfg, private now: () => Date = () => new Date()) {}

  recordDm(handle: string, at: Date = this.now()): void {
    this.recent.set(handle, at.getTime())
  }

  pick({ excludeSelf }: { excludeSelf: string }): string[] | null {
    const r = this.cfg.routing
    if (r === 'never_relay') return null
    if (r === 'ask_team') return ['@team']
    if (r.startsWith('ask_specific_peer:')) {
      const h = r.slice('ask_specific_peer:'.length)
      return h === excludeSelf ? null : [h]
    }
    const nowMs = this.now().getTime()
    let bestHandle: string | null = null
    let bestTime = 0
    for (const [h, t] of this.recent) {
      if (h === excludeSelf) continue
      if (nowMs - t > THREAD_WINDOW_MS) continue
      if (t > bestTime) { bestTime = t; bestHandle = h }
    }
    return bestHandle ? [bestHandle] : null
  }
}
