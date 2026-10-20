/**
 * Moves the session's relay task (MESH_TASK_ID) along with what its host does: the first turn
 * makes a dispatched task `working`, a permission prompt `input_required`, the end of that turn
 * `working` again. It never completes, fails or cancels a task: a turn ending is not the work
 * being done, so the end states stay explicit (`mesh task update`, closeout, the dispatcher).
 */
export type HostEvent = 'turn' | 'tool' | 'blocked' | 'stop' | 'idle' | 'end'

export interface TaskApi {
  get(id: string): Promise<{ status: number; task?: { state: string; assignee: { session: string | null } } }>
  patch(id: string, body: { state: string }): Promise<{ status: number; error?: string }>
  rebind(id: string): Promise<{ status: number }>
}

const TERMINAL = new Set(['completed', 'failed', 'canceled', 'rejected'])

const WANT: Partial<Record<HostEvent, (cur: string | undefined) => string | undefined>> = {
  turn: () => 'working',
  tool: () => 'working',
  blocked: () => 'input_required',
  // The turn ended: whatever blocked it is over. Nothing else changes on a stop.
  stop: cur => (cur === 'input_required' ? 'working' : undefined),
  idle: cur => (cur === 'input_required' ? 'working' : undefined),
}

export class TaskDriver {
  private state: string | undefined
  private final = false
  private queue: Promise<void> = Promise.resolve()

  constructor(private readonly api: TaskApi, private readonly id: string, private readonly session: string,
    private readonly log: (event: string, fields: Record<string, unknown>) => void = () => {}) {}

  /** Learns the task's state and, after a restart or --resume, takes it over from the previous session. */
  async start(): Promise<void> {
    try {
      const r = await this.api.get(this.id)
      if (r.status !== 200 || !r.task) { this.log('peer.task.unknown', { task: this.id, status: r.status }); return }
      this.state = r.task.state
      if (TERMINAL.has(this.state)) { this.final = true; return }
      if (r.task.assignee.session && r.task.assignee.session !== this.session) {
        const rb = await this.api.rebind(this.id)
        this.log('peer.task.rebind', { task: this.id, status: rb.status })
        // Still held by a live session (or not ours): this session does not drive it.
        if (rb.status !== 200) this.final = true
      }
    } catch (err) {
      this.log('peer.task.start_error', { task: this.id, err: String(err instanceof Error ? err.message : err) })
    }
  }

  /** Serialized: events arrive faster than the relay answers, and each must see the state the last one left. */
  on(event: HostEvent): Promise<void> {
    this.queue = this.queue.then(() => this.apply(event)).catch(() => {})
    return this.queue
  }

  private async apply(event: HostEvent): Promise<void> {
    if (this.final) return
    const want = WANT[event]?.(this.state)
    if (!want || want === this.state) return
    const r = await this.api.patch(this.id, { state: want })
    if (r.status === 200) { this.state = want; return }
    if (r.status === 409 && r.error === 'task_terminal') { this.final = true; return }
    this.log('peer.task.update_refused', { task: this.id, want, status: r.status, error: r.error ?? '' })
    // Not this session's to move (403) or gone (404): stop asking on every event.
    if (r.status === 403 || r.status === 404) this.final = true
  }
}
