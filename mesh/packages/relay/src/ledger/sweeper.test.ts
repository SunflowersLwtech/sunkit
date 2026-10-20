import { describe, it, expect } from 'vitest'
import { openDatabase } from '../db/db.ts'
import { TaskStore } from './tasks.ts'
import { LeaseStore } from './leases.ts'
import { startLedgerSweeper } from './sweeper.ts'

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
    const t = startLedgerSweeper({ tasks, leases, intervalMs: 20 })
    await new Promise(r => setTimeout(r, 60))
    clearInterval(t)
    const left = (db.prepare('SELECT title FROM task ORDER BY title').all() as Array<{ title: string }>).map(r => r.title)
    expect(left).toEqual(['live', 'recent'])
    expect(live.state).toBe('working')
    expect((db.prepare('SELECT COUNT(*) AS n FROM lease').get() as { n: number }).n).toBe(0)
  })
})
