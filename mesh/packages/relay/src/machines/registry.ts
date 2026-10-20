import { newCommandId, type CommandRequest, type CommandResult, type MachineReport, type MachineView } from '@claude-mesh/shared'

/** No report for this long: the machine is shown stale and its sessions are hidden (never shown idle). */
export const MACHINE_STALE_MS = 90_000
/** No report for this long: the machine is dropped from the list. */
export const MACHINE_FORGET_MS = 10 * 60_000
/** A command not answered by then fails as no_ack; it is never re-queued on its own. */
export const COMMAND_TTL_MS = 60_000
/** Finished commands (and the output they carry) are kept this long for the issuer, then dropped. */
export const COMMAND_KEEP_MS = 10 * 60_000

interface MachineEntry {
  team_id: string
  machine: string
  workgroup: string
  token_id: string
  report: MachineReport
  reported_at: number
  streams: number
}

/**
 * What each machine's executor last said about itself. In memory on purpose, like sessions:
 * a relay restart forgets it and the executors report again within a minute.
 */
export class MachineRegistry {
  private byKey = new Map<string, MachineEntry>()
  private streams = new Map<string, number>()

  constructor(private now: () => number = () => Date.now()) {}

  private key(team_id: string, machine: string): string { return `${team_id}\u0000${machine}` }

  report(team_id: string, machine: string, workgroup: string, token_id: string, report: MachineReport): void {
    const k = this.key(team_id, machine)
    this.byKey.set(k, { team_id, machine, workgroup, token_id, report, reported_at: this.now(), streams: this.streams.get(k) ?? 0 })
  }

  attach(team_id: string, machine: string): void {
    const k = this.key(team_id, machine)
    this.streams.set(k, (this.streams.get(k) ?? 0) + 1)
    const e = this.byKey.get(k)
    if (e) e.streams = this.streams.get(k)!
  }

  detach(team_id: string, machine: string): void {
    const k = this.key(team_id, machine)
    const n = Math.max(0, (this.streams.get(k) ?? 0) - 1)
    if (n === 0) this.streams.delete(k)
    else this.streams.set(k, n)
    const e = this.byKey.get(k)
    if (e) e.streams = n
  }

  get(team_id: string, machine: string): MachineEntry | undefined {
    const e = this.byKey.get(this.key(team_id, machine))
    if (e && this.now() - e.reported_at > MACHINE_FORGET_MS) return undefined
    return e
  }

  list(team_id: string, visible: readonly string[]): MachineView[] {
    const out: MachineView[] = []
    const t = this.now()
    for (const [k, e] of this.byKey) {
      const ageMs = t - e.reported_at
      if (ageMs > MACHINE_FORGET_MS) { this.byKey.delete(k); continue }
      if (e.team_id !== team_id || !visible.includes(e.workgroup)) continue
      const stale = ageMs > MACHINE_STALE_MS
      out.push({
        machine: e.machine,
        workgroup: e.workgroup,
        reported_at: new Date(e.reported_at).toISOString(),
        age_s: Math.floor(ageMs / 1000),
        stale,
        connected: e.streams > 0,
        // A machine we have not heard from cannot vouch for its sessions: drop them rather than show them idle.
        report: stale ? { ...e.report, agents: [], active: 0, blocked: 0 } : e.report,
      })
    }
    return out.sort((a, b) => a.machine.localeCompare(b.machine))
  }
}

export type CommandState = 'queued' | 'claimed' | 'done' | 'failed'

export interface Command {
  id: string
  team_id: string
  machine: string
  op: CommandRequest['op']
  args: Record<string, unknown>
  state: CommandState
  reason: string | null
  result: CommandResult | null
  issued_at: number
  expires_at: number
  finished_at: number | null
  issuer: { token_id: string; human_id: string; session: string | null; name: string }
}

export interface CommandView {
  id: string
  op: string
  machine: string
  state: CommandState
  reason: string | null
  result: CommandResult | null
  issued_at: string
  expires_at: string
}

type Listener = (c: Command) => void

/**
 * Commands for executors. Delivered once to a live executor stream (or on its next connect),
 * answered once; anything unanswered after COMMAND_TTL_MS fails as no_ack. The payload and
 * output live only here and only for the issuer.
 */
export class CommandQueue {
  private byId = new Map<string, Command>()
  private listeners = new Map<string, Set<Listener>>()
  private waiters = new Map<string, Set<() => void>>()

  constructor(private now: () => number = () => Date.now(), private onExpire: (c: Command) => void = () => {}) {}

  private key(team_id: string, machine: string): string { return `${team_id}\u0000${machine}` }

  issue(team_id: string, machine: string, req: CommandRequest, issuer: Command['issuer']): Command {
    const t = this.now()
    const cmd: Command = {
      id: newCommandId(), team_id, machine, op: req.op, args: (req.args ?? {}) as Record<string, unknown>,
      state: 'queued', reason: null, result: null, issued_at: t, expires_at: t + COMMAND_TTL_MS, finished_at: null, issuer,
    }
    this.byId.set(cmd.id, cmd)
    for (const l of this.listeners.get(this.key(team_id, machine)) ?? []) {
      if (cmd.state !== 'queued') break
      l(cmd)
    }
    return cmd
  }

  /** Registers an executor stream; returns the commands queued for it meanwhile and an unsubscribe. */
  listen(team_id: string, machine: string, l: Listener): { backlog: Command[]; stop: () => void } {
    const k = this.key(team_id, machine)
    let set = this.listeners.get(k)
    if (!set) { set = new Set(); this.listeners.set(k, set) }
    set.add(l)
    const backlog = [...this.byId.values()].filter(c => c.team_id === team_id && c.machine === machine && this.refresh(c).state === 'queued')
    return { backlog, stop: () => { set!.delete(l); if (set!.size === 0) this.listeners.delete(k) } }
  }

  markClaimed(c: Command): void {
    if (this.refresh(c).state === 'queued') c.state = 'claimed'
  }

  get(id: string): Command | undefined {
    this.gc()
    const c = this.byId.get(id)
    return c ? this.refresh(c) : undefined
  }

  complete(c: Command, result: CommandResult): boolean {
    if (this.refresh(c).state === 'done' || c.state === 'failed') return false
    c.state = result.ok ? 'done' : 'failed'
    c.reason = result.ok ? null : 'executor_error'
    c.result = result
    c.finished_at = this.now()
    this.wake(c.id)
    return true
  }

  /** Resolves when the command finishes, or after `ms`. */
  wait(id: string, ms: number): Promise<void> {
    return new Promise(resolve => {
      const c = this.byId.get(id)
      if (!c || c.state === 'done' || c.state === 'failed') return resolve()
      const until = Math.min(ms, Math.max(0, c.expires_at - this.now()) + 10)
      let set = this.waiters.get(id)
      if (!set) { set = new Set(); this.waiters.set(id, set) }
      const done = () => { clearTimeout(timer); set!.delete(done); resolve() }
      const timer = setTimeout(done, until)
      set.add(done)
    })
  }

  view(c: Command): CommandView {
    return {
      id: c.id, op: c.op, machine: c.machine, state: c.state, reason: c.reason, result: c.result,
      issued_at: new Date(c.issued_at).toISOString(), expires_at: new Date(c.expires_at).toISOString(),
    }
  }

  private refresh(c: Command): Command {
    if ((c.state === 'queued' || c.state === 'claimed') && this.now() > c.expires_at) {
      c.state = 'failed'
      c.reason = 'no_ack'
      c.finished_at = this.now()
      this.onExpire(c)
      this.wake(c.id)
    }
    return c
  }

  private wake(id: string): void {
    for (const w of [...(this.waiters.get(id) ?? [])]) w()
    this.waiters.delete(id)
  }

  /** Expires overdue commands and drops finished ones past COMMAND_KEEP_MS. */
  gc(): void {
    const t = this.now()
    for (const [id, c] of this.byId) {
      this.refresh(c)
      if (c.finished_at !== null && t - c.finished_at > COMMAND_KEEP_MS) this.byId.delete(id)
    }
  }
}
