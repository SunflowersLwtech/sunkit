import { isTerminalTaskState, newTaskId, type Artifact, type TaskState, type TaskView } from '@claude-mesh/shared'
import type { Db } from '../db/db.ts'

/** A quiet non-terminal task is shown as stale; staleness is derived, never a state. */
export const TASK_STALE_MS = 15 * 60_000
export const TASK_RETENTION_MS = 7 * 24 * 60 * 60_000
export const MAX_ARTIFACTS = 20

export interface TaskRow {
  id: string
  team_id: string
  workgroup: string
  title: string
  state: TaskState
  progress: string | null
  reason: string | null
  assignee_session: string | null
  assignee_name: string | null
  assignee_machine: string | null
  assignee_token: string | null
  dispatcher_session: string | null
  dispatcher_name: string | null
  dispatcher_token: string
  parent_task: string | null
  depth: number
  prompt_sha256: string | null
  artifacts_json: string
  seq: number
  created_at: string
  updated_at: string
  deadline: string | null
  ended_at: string | null
}

export interface NewTask {
  team_id: string
  workgroup: string
  title: string
  state: TaskState
  assignee: { session: string | null; name: string | null; machine: string | null; token: string | null }
  dispatcher: { session: string | null; name: string | null; token: string }
  parent_task: string | null
  depth: number
  prompt_sha256: string | null
  deadline: string | null
}

/**
 * Who may move a task where. Terminal states are final (checked before this table); nothing
 * returns to submitted; cancel and reject are the dispatcher's call.
 */
const ALLOWED: Record<TaskState, { from: readonly TaskState[]; by: ReadonlyArray<'assignee' | 'dispatcher'> }> = {
  submitted: { from: [], by: [] },
  working: { from: ['submitted', 'working', 'input_required', 'auth_required'], by: ['assignee', 'dispatcher'] },
  input_required: { from: ['submitted', 'working', 'input_required', 'auth_required'], by: ['assignee', 'dispatcher'] },
  auth_required: { from: ['submitted', 'working', 'input_required', 'auth_required'], by: ['assignee', 'dispatcher'] },
  completed: { from: ['submitted', 'working', 'input_required', 'auth_required'], by: ['assignee', 'dispatcher'] },
  failed: { from: ['submitted', 'working', 'input_required', 'auth_required'], by: ['assignee', 'dispatcher'] },
  canceled: { from: ['submitted', 'working', 'input_required', 'auth_required'], by: ['dispatcher'] },
  rejected: { from: ['submitted'], by: ['dispatcher'] },
}

export type TransitionCheck =
  | { ok: true }
  | { ok: false; status: 403 | 409; error: 'task_terminal' | 'bad_transition' | 'not_allowed' }

export function checkTransition(from: TaskState, to: TaskState, actor: { assignee: boolean; dispatcher: boolean }): TransitionCheck {
  if (isTerminalTaskState(from)) return { ok: false, status: 409, error: 'task_terminal' }
  const rule = ALLOWED[to]
  if (!rule.from.includes(from)) return { ok: false, status: 409, error: 'bad_transition' }
  const may = (actor.assignee && rule.by.includes('assignee')) || (actor.dispatcher && rule.by.includes('dispatcher'))
  return may ? { ok: true } : { ok: false, status: 403, error: 'not_allowed' }
}

export class TaskStore {
  constructor(private readonly db: Db, private readonly now: () => Date) {}

  /** The relay is the only writer of seq: one atomic counter per team. */
  private nextSeq(team_id: string): number {
    const row = this.db.prepare(`
      INSERT INTO task_seq(team_id, seq) VALUES (?, 1)
      ON CONFLICT(team_id) DO UPDATE SET seq = seq + 1
      RETURNING seq
    `).get(team_id) as { seq: number }
    return row.seq
  }

  currentSeq(team_id: string): number {
    const row = this.db.prepare('SELECT seq FROM task_seq WHERE team_id=?').get(team_id) as { seq: number } | undefined
    return row?.seq ?? 0
  }

  create(t: NewTask): TaskRow {
    const at = this.now().toISOString()
    const id = newTaskId()
    this.db.transaction(() => {
      this.db.prepare(`
        INSERT INTO task(id, team_id, workgroup, title, state, assignee_session, assignee_name, assignee_machine, assignee_token,
          dispatcher_session, dispatcher_name, dispatcher_token, parent_task, depth, prompt_sha256, seq, created_at, updated_at, deadline)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      `).run(id, t.team_id, t.workgroup, t.title, t.state, t.assignee.session, t.assignee.name, t.assignee.machine, t.assignee.token,
        t.dispatcher.session, t.dispatcher.name, t.dispatcher.token, t.parent_task, t.depth, t.prompt_sha256,
        this.nextSeq(t.team_id), at, at, t.deadline)
    })()
    return this.get(t.team_id, id)!
  }

  get(team_id: string, id: string): TaskRow | undefined {
    return this.db.prepare('SELECT * FROM task WHERE id=? AND team_id=?').get(id, team_id) as TaskRow | undefined
  }

  list(team_id: string, visible: readonly string[], sinceSeq: number, limit = 500): TaskRow[] {
    return this.db.prepare(`
      SELECT * FROM task WHERE team_id=? AND seq > ? AND workgroup IN (SELECT value FROM json_each(?))
      ORDER BY seq ASC LIMIT ?
    `).all(team_id, sinceSeq, JSON.stringify(visible), limit) as TaskRow[]
  }

  /** Applies a validated change. `ifSeq` makes it conditional on nobody having written since. */
  update(team_id: string, id: string, change: { state?: TaskState; progress?: string; reason?: string },
    ifSeq?: number): { ok: true; row: TaskRow } | { ok: false; seq: number; terminal: boolean } {
    return this.db.transaction(() => {
      const cur = this.get(team_id, id)!
      // Checked again on the row as it is now: whatever the caller read earlier may be stale.
      if (isTerminalTaskState(cur.state)) return { ok: false as const, seq: cur.seq, terminal: true }
      if (ifSeq !== undefined && cur.seq !== ifSeq) return { ok: false as const, seq: cur.seq, terminal: false }
      const at = this.now().toISOString()
      const state = change.state ?? cur.state
      this.db.prepare(`
        UPDATE task SET state=?, progress=?, reason=?, seq=?, updated_at=?, ended_at=? WHERE id=? AND team_id=?
      `).run(state, change.progress ?? cur.progress, change.reason ?? cur.reason, this.nextSeq(team_id), at,
        isTerminalTaskState(state) && !cur.ended_at ? at : cur.ended_at, id, team_id)
      return { ok: true as const, row: this.get(team_id, id)! }
    })()
  }

  addArtifact(team_id: string, id: string, a: Artifact): TaskRow | 'full' {
    return this.db.transaction(() => {
      const cur = this.get(team_id, id)!
      const list = JSON.parse(cur.artifacts_json) as unknown[]
      if (list.length >= MAX_ARTIFACTS) return 'full' as const
      const at = this.now().toISOString()
      list.push({ ...a, at })
      this.db.prepare('UPDATE task SET artifacts_json=?, seq=?, updated_at=? WHERE id=? AND team_id=?')
        .run(JSON.stringify(list), this.nextSeq(team_id), at, id, team_id)
      return this.get(team_id, id)!
    })()
  }

  rebind(team_id: string, id: string, to: { session: string; name: string; machine: string | null }): TaskRow {
    const at = this.now().toISOString()
    this.db.prepare(`
      UPDATE task SET assignee_session=?, assignee_name=?, assignee_machine=?, seq=?, updated_at=? WHERE id=? AND team_id=?
    `).run(to.session, to.name, to.machine, this.nextSeq(team_id), at, id, team_id)
    return this.get(team_id, id)!
  }

  /**
   * Fails tasks nobody touched for the retention period (reason `abandoned`), then drops tasks
   * that ended more than the retention period ago. Returns how many were dropped.
   */
  sweep(): number {
    const now = this.now()
    const cutoff = new Date(now.getTime() - TASK_RETENTION_MS).toISOString()
    const quiet = this.db.prepare(`
      SELECT id, team_id FROM task WHERE ended_at IS NULL AND updated_at < ?
    `).all(cutoff) as Array<{ id: string; team_id: string }>
    for (const t of quiet) {
      this.db.transaction(() => {
        this.db.prepare("UPDATE task SET state='failed', reason='abandoned', seq=?, updated_at=?, ended_at=? WHERE id=?")
          .run(this.nextSeq(t.team_id), now.toISOString(), now.toISOString(), t.id)
      })()
    }
    return this.db.prepare('DELETE FROM task WHERE ended_at IS NOT NULL AND ended_at < ?').run(cutoff).changes
  }

  view(r: TaskRow): TaskView {
    const ageMs = Math.max(0, this.now().getTime() - Date.parse(r.updated_at))
    return {
      id: r.id,
      title: r.title,
      state: r.state,
      progress: r.progress,
      reason: r.reason,
      workgroup: r.workgroup,
      assignee: { session: r.assignee_session, name: r.assignee_name, machine: r.assignee_machine },
      dispatcher: { session: r.dispatcher_session, name: r.dispatcher_name },
      parent_task: r.parent_task,
      depth: r.depth,
      prompt_sha256: r.prompt_sha256,
      artifacts: JSON.parse(r.artifacts_json) as TaskView['artifacts'],
      seq: r.seq,
      created_at: r.created_at,
      updated_at: r.updated_at,
      deadline: r.deadline,
      age_s: Math.floor(ageMs / 1000),
      stale: !isTerminalTaskState(r.state) && ageMs > TASK_STALE_MS,
    }
  }
}
