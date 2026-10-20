import { logJson } from '../logger.ts'
import type { TaskStore } from './tasks.ts'
import type { LeaseStore } from './leases.ts'

/** Drops finished tasks and released leases past their retention, on a timer that never keeps the process alive. */
export function startLedgerSweeper(opts: { tasks: TaskStore; leases: LeaseStore; intervalMs: number }): NodeJS.Timeout {
  const tick = (): void => {
    try {
      const tasks = opts.tasks.sweep()
      const leases = opts.leases.sweep()
      if (tasks + leases > 0) logJson('info', 'ledger.sweep', { tasks, leases })
    } catch (err) {
      logJson('warn', 'ledger.sweep_error', { err: String(err instanceof Error ? err.message : err) })
    }
  }
  const t = setInterval(tick, opts.intervalMs)
  t.unref()
  return t
}
