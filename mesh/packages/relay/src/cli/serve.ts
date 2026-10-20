import { existsSync } from 'node:fs'
import { serve } from '@hono/node-server'
import { buildApp } from '../app.ts'
import { openDatabase } from '../db/db.ts'
import { MessageStore } from '../messages/store.ts'
import { Fanout } from '../fanout.ts'
import { PresenceRegistry } from '../presence/registry.ts'
import { startInactivitySweeper } from '../purge.ts'
import { logJson } from '../logger.ts'
import { TaskStore } from '../ledger/tasks.ts'
import { LeaseStore } from '../ledger/leases.ts'
import { startLedgerSweeper } from '../ledger/sweeper.ts'
import { CommandQueue, MachineRegistry } from '../machines/registry.ts'
import { audit } from '../audit.ts'

export interface ServeOpts {
  db_path: string
  port: number
  host: string
  inactive_days?: number   // auto-purge users idle this long (default 30, disable with 0)
  sweep_interval_ms?: number   // (default 1h)
}

export function startServer(opts: ServeOpts) {
  if (!existsSync(opts.db_path)) {
    console.error(
      `No database at ${opts.db_path}.\n` +
      `Run \`node packages/relay/dist/index.js init\` first to create the team and schema.`
    )
    process.exit(1)
  }
  const db = openDatabase(opts.db_path)
  const store = new MessageStore(db)
  const fanout = new Fanout()
  const presence = new PresenceRegistry()
  const now = () => new Date()
  const tasks = new TaskStore(db, now)
  const leases = new LeaseStore(db, now)
  const clock = () => Date.now()
  const machines = new MachineRegistry(clock)
  const commands = new CommandQueue(clock, cmd =>
    audit(db, cmd.team_id, cmd.issuer.human_id, 'dispatch.fail', { cmd_id: cmd.id, op: cmd.op, machine: cmd.machine, reason: 'no_ack' }, new Date().toISOString()))
  const app = buildApp({ db, store, fanout, presence, tasks, leases, machines, commands, now })
  // Independent of the inactivity sweep (which deployments may disable): ledger rows always age out.
  startLedgerSweeper({ tasks, leases, commands, intervalMs: opts.sweep_interval_ms ?? 60 * 60 * 1000 })
  const server = serve({ fetch: app.fetch, port: opts.port, hostname: opts.host })

  const days = opts.inactive_days ?? 30
  if (days > 0) {
    const intervalMs = opts.sweep_interval_ms ?? 60 * 60 * 1000
    startInactivitySweeper(db, { intervalMs, days, now: () => new Date() })
    logJson('info', 'relay.inactivity_sweeper.started', { days, interval_ms: intervalMs })
  }

  logJson('info', 'relay.started', { host: opts.host, port: opts.port, db_path: opts.db_path })
  return server
}
