import type { CommandRequest, LeaseView, MachineView, TaskView } from '@claude-mesh/shared'
import { loadConfig, loadToken } from '../config.ts'
import { resolveTarget, type SessionRow } from '../resolve-target.ts'
import { askHostPeer } from './host-hook.ts'

/**
 * The relay's ledger, from the command line: machines (what each machine last reported),
 * tasks (who was asked to do what) and leases (what is currently held).
 *
 * Every request carries the token; the session id, when known, rides along in x-mesh-session
 * so the relay can bind the action to a live session (leases need it, tasks need it to
 * register work for the caller).
 */

export const MACHINE_USAGE =
  'usage: mesh machine list [--json] | mesh machine read <machine> <pane> [--lines N] | mesh machine probe <machine>'
export const TASK_USAGE =
  'usage: mesh task list [--since N] [--json] | mesh task show <id> | mesh task create --title <text> [--assignee <session id>] [--parent <task id>] | mesh task update <id> [--state S] [--progress text] [--reason text] [--if-seq N] | mesh task artifact <id> <type> <ref> [--note text]'
export const LEASE_USAGE =
  'usage: mesh lease list [--name N] [--json] | mesh lease acquire <name> --ttl <seconds> [--note text] [--task <task id>] | mesh lease renew <id> [--ttl seconds] | mesh lease release <id>'

/** What the relay says about a command it issued to a machine. */
export interface CommandView {
  id: string
  op: string
  machine: string
  state: 'queued' | 'claimed' | 'done' | 'failed'
  reason: string | null
  result: { ok: boolean; output?: string; error?: string } | null
  issued_at: string
  expires_at: string
}

export interface LedgerClientOpts {
  relayUrl: string
  token: string
  /** This session's id; sent as x-mesh-session so the relay can bind the request to it. */
  session?: string
  /** When no session is given: ask the peer of the host this command runs in (its hook socket). */
  discoverSession?: () => Promise<string | undefined>
}

interface Injected { fetch?: typeof globalThis.fetch }

/** A relay refusal: the HTTP status plus whatever the relay said about it. */
export class LedgerError extends Error {
  constructor(readonly status: number, readonly body: unknown, message: string) {
    super(message)
    this.name = 'LedgerError'
  }
}

/**
 * Text another session wrote (titles, progress, names, a screen) printed into this terminal: escape
 * sequences in it would drive the terminal, so control characters become '?'. `block` keeps lines.
 */
export function clean(text: string, block = false): string {
  return block
    ? text.replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g, '?')
    : text.replace(/[\u0000-\u001f\u007f-\u009f]/g, '?')
}

const SESSION_ID = /^s_[0-9a-z]+$/

function parseJson(text: string): unknown {
  if (!text) return undefined
  try { return JSON.parse(text) as unknown } catch { return undefined }
}

/** "<status> <error field of the body, or the raw body text>". */
function errorText(status: number, text: string, body: unknown): string {
  const field = body && typeof body === 'object' && typeof (body as { error?: unknown }).error === 'string'
    ? (body as { error: string }).error
    : undefined
  const detail = field ?? text.trim()
  return `${status} ${detail || 'no body'}`
}

export class LedgerClient {
  private fetchImpl: typeof globalThis.fetch
  private sessionId: Promise<string | undefined> | undefined

  constructor(private opts: LedgerClientOpts, inj: Injected = {}) {
    this.fetchImpl = inj.fetch ?? globalThis.fetch
  }

  /** `session` may be an id, or a name / `name [ref]` as list_agents shows it, resolved once. */
  private session(): Promise<string | undefined> {
    const s = this.opts.session
    if (!s && this.opts.discoverSession) {
      this.sessionId ??= this.opts.discoverSession().catch(() => undefined)
      return this.sessionId
    }
    if (!s || SESSION_ID.test(s)) return Promise.resolve(s)
    this.sessionId ??= (async () => {
      const res = await this.fetchImpl(this.url('/v1/sessions'), { headers: { authorization: `Bearer ${this.opts.token}` } })
      const text = await res.text()
      const body = parseJson(text)
      if (res.status !== 200 || !Array.isArray(body)) throw new LedgerError(res.status, body, errorText(res.status, text, body))
      const r = resolveTarget(s, body as SessionRow[], '')
      if (!r.ok) throw new LedgerError(404, null, `session ${r.error}`)
      return r.target.session_id
    })()
    return this.sessionId
  }

  private url(path: string, query?: Record<string, string | number | undefined>): URL {
    const u = new URL(path, this.opts.relayUrl)
    if (query) for (const [k, v] of Object.entries(query)) if (v !== undefined) u.searchParams.set(k, String(v))
    return u
  }

  private async headers(): Promise<Record<string, string>> {
    const session = await this.session()
    return {
      authorization: `Bearer ${this.opts.token}`,
      'content-type': 'application/json',
      ...(session ? { 'x-mesh-session': session } : {}),
    }
  }

  private async request<T>(url: URL, init: RequestInit = {}): Promise<T> {
    const res = await this.fetchImpl(url, { ...init, headers: await this.headers() })
    const text = await res.text()
    const body = parseJson(text)
    if (res.status < 200 || res.status >= 300) {
      throw new LedgerError(res.status, body, errorText(res.status, text, body))
    }
    return body as T
  }

  // Machines

  async listMachines(): Promise<MachineView[]> {
    return await this.request<MachineView[]>(this.url('/v1/machines'))
  }

  async issueCommand(machine: string, body: CommandRequest): Promise<CommandView> {
    return await this.request<CommandView>(
      this.url(`/v1/machines/${encodeURIComponent(machine)}/commands`),
      { method: 'POST', body: JSON.stringify(body) },
    )
  }

  async getCommand(id: string, waitSeconds = 25): Promise<CommandView> {
    return await this.request<CommandView>(this.url(`/v1/commands/${encodeURIComponent(id)}`, { wait: waitSeconds }))
  }

  // Tasks

  async listTasks(sinceSeq = 0): Promise<{ tasks: TaskView[]; seq: number }> {
    return await this.request<{ tasks: TaskView[]; seq: number }>(this.url('/v1/tasks', { since_seq: sinceSeq }))
  }

  async getTask(id: string): Promise<TaskView> {
    return await this.request<TaskView>(this.url(`/v1/tasks/${encodeURIComponent(id)}`))
  }

  async createTask(body: { title: string; assignee?: string; parent_task?: string }): Promise<TaskView> {
    return await this.request<TaskView>(this.url('/v1/tasks'), { method: 'POST', body: JSON.stringify(body) })
  }

  async updateTask(
    id: string,
    body: { state?: string; progress?: string; reason?: string; if_seq?: number },
  ): Promise<TaskView> {
    return await this.request<TaskView>(
      this.url(`/v1/tasks/${encodeURIComponent(id)}`),
      { method: 'PATCH', body: JSON.stringify(body) },
    )
  }

  async addArtifact(id: string, body: { type: string; ref: string; note?: string }): Promise<TaskView> {
    return await this.request<TaskView>(
      this.url(`/v1/tasks/${encodeURIComponent(id)}/artifacts`),
      { method: 'POST', body: JSON.stringify(body) },
    )
  }

  // Leases

  async listLeases(name?: string): Promise<LeaseView[]> {
    return await this.request<LeaseView[]>(this.url('/v1/leases', name === undefined ? undefined : { name }))
  }

  async acquireLease(body: { name: string; ttl_s: number; note?: string; task_id?: string }): Promise<LeaseView> {
    return await this.request<LeaseView>(this.url('/v1/leases'), { method: 'POST', body: JSON.stringify(body) })
  }

  async renewLease(id: string, body: { ttl_s?: number }): Promise<LeaseView> {
    return await this.request<LeaseView>(
      this.url(`/v1/leases/${encodeURIComponent(id)}/renew`),
      { method: 'POST', body: JSON.stringify(body) },
    )
  }

  async releaseLease(id: string): Promise<{ ok: boolean }> {
    return await this.request<{ ok: boolean }>(
      this.url(`/v1/leases/${encodeURIComponent(id)}`),
      { method: 'DELETE' },
    )
  }
}

export interface LedgerDeps {
  /** A ready client; when absent one is built from the config file and the token file. */
  client?: LedgerClient
  /** Asks the host's peer which session this is; tests replace it. */
  discover?: () => Promise<string | undefined>
  out?: (s: string) => void
  err?: (s: string) => void
  sleep?: (ms: number) => Promise<void>
}

interface Ctx {
  out: (s: string) => void
  err: (s: string) => void
  sleep: (ms: number) => Promise<void>
  client: () => LedgerClient
}

/** How long to wait between two polls of a command; the relay itself waits up to 25 s per poll. */
const POLL_INTERVAL_MS = 250
/** How many times a command is polled before the CLI gives up on it. */
const MAX_POLLS = 3

interface Parsed {
  positional: string[]
  flags: Record<string, string | true>
}

/** Split `--flag value` pairs from the free arguments. */
function parseArgs(args: string[]): Parsed {
  const positional: string[] = []
  const flags: Record<string, string | true> = {}
  for (let i = 0; i < args.length; i++) {
    const a = args[i]!
    if (!a.startsWith('--')) { positional.push(a); continue }
    const eq = a.indexOf('=')
    if (eq > 0) { flags[a.slice(2, eq)] = a.slice(eq + 1); continue }
    const next = args[i + 1]
    if (next !== undefined && !next.startsWith('--')) { flags[a.slice(2)] = next; i++; continue }
    flags[a.slice(2)] = true
  }
  return { positional, flags }
}

function flagString(flags: Parsed['flags'], name: string): string | undefined {
  const v = flags[name]
  return typeof v === 'string' ? v : undefined
}

function flagNumber(flags: Parsed['flags'], name: string): number | undefined {
  const v = flagString(flags, name)
  if (v === undefined) return undefined
  const n = Number(v)
  return Number.isInteger(n) ? n : undefined
}

/** `--relay <url>` and `--session <id>` work for every ledger command. */
function splitGlobals(args: string[]): { rest: string[]; relay?: string; session?: string } {
  const rest: string[] = []
  let relay: string | undefined
  let session: string | undefined
  for (let i = 0; i < args.length; i++) {
    const a = args[i]!
    if (a === '--relay' && i + 1 < args.length) { relay = args[++i]; continue }
    if (a === '--session' && i + 1 < args.length) { session = args[++i]; continue }
    if (a.startsWith('--relay=')) { relay = a.slice('--relay='.length); continue }
    if (a.startsWith('--session=')) { session = a.slice('--session='.length); continue }
    rest.push(a)
  }
  return { rest, ...(relay !== undefined ? { relay } : {}), ...(session !== undefined ? { session } : {}) }
}

function makeCtx(globals: { relay?: string; session?: string }, deps: LedgerDeps): Ctx {
  const { relay, session } = globals
  let cached: LedgerClient | undefined
  return {
    out: deps.out ?? ((s: string) => console.log(s)),
    err: deps.err ?? ((s: string) => console.error(s)),
    sleep: deps.sleep ?? ((ms: number) => new Promise<void>(resolve => { setTimeout(resolve, ms) })),
    client: () => {
      if (deps.client) return deps.client
      if (!cached) {
        const cfg = loadConfig()
        const discover = deps.discover ?? (async () => (await askHostPeer({ op: 'whoami' }))?.session)
        cached = new LedgerClient({
          relayUrl: relay ?? cfg.relay_url,
          token: loadToken(cfg.token_path),
          ...(session ? { session } : {}),
          // --session first; then the peer of the host this runs in (a Bash tool of Claude Code,
          // pi, agy …), which knows its session even when an outer session's MESH_SESSION_ID was
          // inherited; MESH_SESSION_ID last.
          discoverSession: async () => (await discover().catch(() => undefined)) ?? process.env.MESH_SESSION_ID,
        })
      }
      return cached
    },
  }
}

function machineLine(m: MachineView): string {
  const r = m.report
  const seats = r.seats
    .map(s => (s.five_hour_pct === undefined ? s.email : `${s.email} ${s.five_hour_pct}%`))
    .join(' ')
  return clean([
    m.machine,
    m.stale ? 'stale' : 'ok',
    m.connected ? 'connected' : 'offline',
    `age ${m.age_s}s`,
    `load ${r.load.load1}/${r.load.cpus}`,
    `active ${r.active}/${r.max_active ?? '?'}`,
    `seats ${seats || 'none'}`,
    `agents ${r.agents.length}`,
  ].join('  '))
}

function taskLine(t: TaskView): string {
  const name = t.assignee.name ?? '-'
  const machine = t.assignee.machine ?? '-'
  return clean(`${t.id}  ${t.state}${t.stale ? ' stale' : ''}  ${name}@${machine}  ${t.title}`)
}

function leaseLine(l: LeaseView): string {
  const holder = l.holder ? `${l.holder.name ?? '-'}@${l.holder.machine ?? '-'}` : '(hidden)'
  return clean(`${l.name}  ${holder}  ${l.ttl_remaining_s}s left  ${l.id}`)
}

/** Wait for a command to finish; the relay answers with whatever the machine reported. */
async function awaitCommand(cmd: CommandView, ctx: Ctx): Promise<number> {
  let current = cmd
  for (let poll = 0; poll < MAX_POLLS; poll++) {
    if (current.state === 'done' || current.state === 'failed') break
    await ctx.sleep(POLL_INTERVAL_MS)
    current = await ctx.client().getCommand(current.id)
  }
  if (current.state === 'done') {
    ctx.out(clean(current.result?.output ?? '', true))
    return 0
  }
  if (current.state === 'failed') {
    ctx.err(clean(`failed: ${current.reason ?? current.result?.error ?? 'unknown error'}`))
    return 1
  }
  ctx.err(`command ${current.id} did not finish (state ${current.state})`)
  return 1
}

export async function runMachine(args: string[], deps: LedgerDeps = {}): Promise<number> {
  const globals = splitGlobals(args)
  const ctx = makeCtx(globals, deps)
  const { rest } = globals
  const [sub, ...rest2] = rest
  try {
    if (sub === 'list') {
      const { positional, flags } = parseArgs(rest2)
      if (positional.length) { ctx.err(MACHINE_USAGE); return 2 }
      const machines = await ctx.client().listMachines()
      if (flags.json) { ctx.out(JSON.stringify(machines)); return 0 }
      for (const m of machines) ctx.out(machineLine(m))
      return 0
    }
    if (sub === 'read') {
      const { positional, flags } = parseArgs(rest2)
      const machine = positional[0]
      const pane = positional[1]
      const lines = flagNumber(flags, 'lines')
      if (!machine || !pane || positional.length > 2
        || (flags.lines !== undefined && (lines === undefined || lines < 1))) {
        ctx.err(MACHINE_USAGE)
        return 2
      }
      const cmd = await ctx.client().issueCommand(machine, {
        op: 'read',
        args: { pane, ...(lines !== undefined ? { lines } : {}) },
      })
      return await awaitCommand(cmd, ctx)
    }
    if (sub === 'probe') {
      const { positional } = parseArgs(rest2)
      const machine = positional[0]
      if (!machine || positional.length > 1) { ctx.err(MACHINE_USAGE); return 2 }
      const cmd = await ctx.client().issueCommand(machine, { op: 'probe' })
      return await awaitCommand(cmd, ctx)
    }
    ctx.err(MACHINE_USAGE)
    return 2
  } catch (err) {
    ctx.err(err instanceof Error ? err.message : String(err))
    return 1
  }
}

export async function runTask(args: string[], deps: LedgerDeps = {}): Promise<number> {
  const globals = splitGlobals(args)
  const ctx = makeCtx(globals, deps)
  const { rest } = globals
  const [sub, ...rest2] = rest
  try {
    if (sub === 'list') {
      const { positional, flags } = parseArgs(rest2)
      const since = flagNumber(flags, 'since')
      if (positional.length || (flags.since !== undefined && (since === undefined || since < 0))) {
        ctx.err(TASK_USAGE)
        return 2
      }
      const body = await ctx.client().listTasks(since ?? 0)
      if (flags.json) { ctx.out(JSON.stringify(body)); return 0 }
      for (const t of body.tasks) {
        ctx.out(taskLine(t))
        if (t.progress) ctx.out(`  ${clean(t.progress)}`)
      }
      return 0
    }
    if (sub === 'show') {
      const { positional } = parseArgs(rest2)
      const id = positional[0]
      if (!id || positional.length > 1) { ctx.err(TASK_USAGE); return 2 }
      const t = await ctx.client().getTask(id)
      ctx.out(JSON.stringify(t, null, 2))
      return 0
    }
    if (sub === 'create') {
      const { positional, flags } = parseArgs(rest2)
      const title = flagString(flags, 'title')
      if (!title || !title.trim() || positional.length) { ctx.err(TASK_USAGE); return 2 }
      const assignee = flagString(flags, 'assignee')
      const parent = flagString(flags, 'parent')
      const t = await ctx.client().createTask({
        title,
        ...(assignee ? { assignee } : {}),
        ...(parent ? { parent_task: parent } : {}),
      })
      ctx.out(`${t.id}  ${t.state}`)
      return 0
    }
    if (sub === 'update') {
      const { positional, flags } = parseArgs(rest2)
      const id = positional[0]
      const state = flagString(flags, 'state')
      const progress = flagString(flags, 'progress')
      const reason = flagString(flags, 'reason')
      const ifSeq = flagNumber(flags, 'if-seq')
      if (!id || positional.length > 1 || (flags['if-seq'] !== undefined && ifSeq === undefined)) {
        ctx.err(TASK_USAGE)
        return 2
      }
      const body: { state?: string; progress?: string; reason?: string; if_seq?: number } = {
        ...(state ? { state } : {}),
        ...(progress ? { progress } : {}),
        ...(reason ? { reason } : {}),
        ...(ifSeq !== undefined ? { if_seq: ifSeq } : {}),
      }
      if (Object.keys(body).length === 0) { ctx.err(TASK_USAGE); return 2 }
      const t = await ctx.client().updateTask(id, body)
      ctx.out(`${t.id}  ${t.state}`)
      return 0
    }
    if (sub === 'artifact') {
      const { positional, flags } = parseArgs(rest2)
      const [id, type, ref] = positional
      if (!id || !type || !ref || positional.length > 3) { ctx.err(TASK_USAGE); return 2 }
      const note = flagString(flags, 'note')
      await ctx.client().addArtifact(id, { type, ref, ...(note ? { note } : {}) })
      ctx.out(`added ${type} ${ref}`)
      return 0
    }
    ctx.err(TASK_USAGE)
    return 2
  } catch (err) {
    ctx.err(err instanceof Error ? err.message : String(err))
    return 1
  }
}

export async function runLease(args: string[], deps: LedgerDeps = {}): Promise<number> {
  const globals = splitGlobals(args)
  const ctx = makeCtx(globals, deps)
  const { rest } = globals
  const [sub, ...rest2] = rest
  try {
    if (sub === 'list') {
      const { positional, flags } = parseArgs(rest2)
      if (positional.length) { ctx.err(LEASE_USAGE); return 2 }
      const name = flagString(flags, 'name')
      const leases = await ctx.client().listLeases(name)
      if (flags.json) { ctx.out(JSON.stringify(leases)); return 0 }
      for (const l of leases) ctx.out(leaseLine(l))
      return 0
    }
    if (sub === 'acquire') {
      const { positional, flags } = parseArgs(rest2)
      const name = positional[0]
      const ttl = flagNumber(flags, 'ttl')
      if (!name || ttl === undefined || ttl <= 0 || positional.length > 1) { ctx.err(LEASE_USAGE); return 2 }
      const note = flagString(flags, 'note')
      const task = flagString(flags, 'task')
      try {
        const lease = await ctx.client().acquireLease({
          name,
          ttl_s: ttl,
          ...(note ? { note } : {}),
          ...(task ? { task_id: task } : {}),
        })
        ctx.out(`${lease.id}  expires ${lease.expires_at}`)
        return 0
      } catch (err) {
        // A held lease comes back with a message that says who holds it and for how long.
        if (err instanceof LedgerError && err.status === 409) {
          const message = err.body && typeof err.body === 'object' && typeof (err.body as { message?: unknown }).message === 'string'
            ? (err.body as { message: string }).message
            : undefined
          ctx.err(clean(message ?? err.message))
          return 1
        }
        throw err
      }
    }
    if (sub === 'renew') {
      const { positional, flags } = parseArgs(rest2)
      const id = positional[0]
      const ttl = flagNumber(flags, 'ttl')
      if (!id || positional.length > 1 || (flags.ttl !== undefined && (ttl === undefined || ttl <= 0))) {
        ctx.err(LEASE_USAGE)
        return 2
      }
      const lease = await ctx.client().renewLease(id, ttl === undefined ? {} : { ttl_s: ttl })
      ctx.out(`${lease.id}  expires ${lease.expires_at}`)
      return 0
    }
    if (sub === 'release') {
      const { positional } = parseArgs(rest2)
      const id = positional[0]
      if (!id || positional.length > 1) { ctx.err(LEASE_USAGE); return 2 }
      await ctx.client().releaseLease(id)
      ctx.out(`released ${id}`)
      return 0
    }
    ctx.err(LEASE_USAGE)
    return 2
  } catch (err) {
    ctx.err(err instanceof Error ? err.message : String(err))
    return 1
  }
}
