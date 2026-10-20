import { logJson } from '../logger.ts'
import type { TaskStore } from './tasks.ts'
import type { LeaseStore } from './leases.ts'
import type { CommandQueue } from '../machines/registry.ts'

/** Command expiry must not wait for somebody to read the queue: no_ack is audited within this. */
export const COMMAND_GC_EVERY_MS = 15_000

/**
 * Ages the ledger out on timers that never keep the process alive: abandoned tasks fail,
 * finished tasks and released leases go after their retention, unanswered commands expire.
 */
export function startLedgerSweeper(opts: { tasks: TaskStore; leases: LeaseStore; commands?: CommandQueue; intervalMs: number; commandEveryMs?: number }): () => void {
  const tick = (): void => {
    try {
      const tasks = opts.tasks.sweep()
      const leases = opts.leases.sweep()
      if (tasks + leases > 0) logJson('info', 'ledger.sweep', { tasks, leases })
    } catch (err) {
      logJson('warn', 'ledger.sweep_error', { err: String(err instanceof Error ? err.message : err) })
    }
  }
  const timers = [setInterval(tick, opts.intervalMs)]
  if (opts.commands) {
    const commands = opts.commands
    timers.push(setInterval(() => {
      try { commands.gc() } catch (err) { logJson('warn', 'ledger.command_gc_error', { err: String(err instanceof Error ? err.message : err) }) }
    }, opts.commandEveryMs ?? COMMAND_GC_EVERY_MS))
  }
  for (const t of timers) t.unref()
  return () => { for (const t of timers) clearInterval(t) }
}
