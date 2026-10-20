import { describe, it, expect } from 'vitest'
import { openDatabase } from '../db/db.ts'
import { TaskStore } from './tasks.ts'
import { LeaseStore } from './leases.ts'
import { startLedgerSweeper } from './sweeper.ts'
import { CommandQueue } from '../machines/registry.ts'

describe('ledger retention', () => {
  it('drops tasks that ended over 7 days ago and released leases over 7 days old, keeps the rest', async () => {
    const db = openDatabase(':memory:')
    db.prepare("INSERT INTO team(id,name,retention_days,created_at) VALUES ('t1','acme',7,?)").run(new Date().toISOString())
    let now = Date.parse('2026-10-01T00:00:00Z')
    const tasks = new TaskStore(db, () => new Date(now))
    const leases = new LeaseStore(db, () => new Date(now))
    const mk = (title: string) => tasks.create({
      team_id: 't1', workgroup: 'team', title, state: 'working',
      assignee: { session: 's_x', name: 'x', machine: null, token: 'tk' }, dispatcher: { session: null, name: 'x', token: 'tk' },
      parent_task: null, depth: 0, prompt_sha256: null, deadline: null,
    })
    const old = mk('old'); tasks.update('t1', old.id, { state: 'completed' })
    const live = mk('live')
    const l = leases.acquire('t1', 'repo/x', 60, { session: 's_x', name: 'x', machine: null, token: 'tk', workgroup: 'team' }, { task_id: null, note: null })
    if (!l.ok) throw new Error('acquire')
    leases.release('t1', l.lease.id, 'release')
    now += 8 * 24 * 60 * 60_000
    const recent = mk('recent'); tasks.update('t1', recent.id, { state: 'failed' })
    const stop = startLedgerSweeper({ tasks, leases, intervalMs: 20 })
    await new Promise(r => setTimeout(r, 60))
    stop()
    const left = db.prepare('SELECT title, state, reason FROM task ORDER BY title').all() as Array<{ title: string; state: string; reason: string | null }>
    // 'live' was quiet for 8 days: failed as abandoned (and dropped only after another week).
    expect(left).toEqual([{ title: 'live', state: 'failed', reason: 'abandoned' }, { title: 'recent', state: 'failed', reason: null }])
    expect(live.state).toBe('working')
    expect((db.prepare('SELECT COUNT(*) AS n FROM lease').get() as { n: number }).n).toBe(0)
  })

  it('expires unanswered commands on its own, without anyone reading the queue', async () => {
    let now = 1_000_000
    const expired: string[] = []
    const q = new CommandQueue(() => now, c => expired.push(c.id))
    const db = openDatabase(':memory:')
    const cmd = q.issue('t1', 'm4', { op: 'probe' }, { token_id: 'tk', human_id: 'h', session: null, name: 'x' })
    now += 61_000
    const stop = startLedgerSweeper({ tasks: new TaskStore(db, () => new Date(now)), leases: new LeaseStore(db, () => new Date(now)), commands: q, intervalMs: 60_000, commandEveryMs: 10 })
    await new Promise(r => setTimeout(r, 40))
    stop()
    expect(expired).toEqual([cmd.id])
  })
})
