import { CommandRequestSchema, HerdrPaneIdSchema, type AgentKind, type CommandResult, type MachineReport } from '@claude-mesh/shared'
import { parseSseEvent } from '../stream.ts'
import { buildReport, cleanVersion, fitReport, parseCcQuota, parseHerdrAgents } from './collect.ts'

// meshd: one per machine, holding an `executor` token bound to that machine. It reports what
// the machine can run and what is running there, and answers the relay's read-only commands
// (probe, read). It only ever talks to the relay; it never listens on a port and never runs a
// shell: every external program is called with a fixed argv.

export const MESHD_VERSION = '0.1.0'
export const REPORT_EVERY_MS = 30_000
const KINDS_EVERY_MS = 30 * 60_000
const QUOTA_EVERY_MS = 5 * 60_000
const READ_DEFAULT_LINES = 80
const OUTPUT_CAP = 60_000
const KINDS: AgentKind[] = ['claude', 'pi', 'agy', 'grok', 'devin']

export interface RunResult { ok: boolean; stdout: string; error?: string }
export type Runner = (file: string, args: string[], timeoutMs: number) => Promise<RunResult>
export type Log = (level: 'info' | 'warn' | 'error', event: string, fields?: Record<string, unknown>) => void

export interface MeshdOpts {
  relayUrl: string
  token: string
  herdrBin: string
  /** Path of cc-quota, or null when this machine has none. */
  ccQuota: string | null
  ccQuotaArgs: string[]
  maxActive?: number
  /** Directory roots dispatch may use, reported as exists/missing (display paths, e.g. ~/Developer/products). */
  roots: Array<{ path: string; exists: () => boolean }>
  load: () => { load1: number; cpus: number; memUsedPct?: number }
  run: Runner
  fetch: typeof globalThis.fetch
  now?: () => number
  sleep?: (ms: number) => Promise<void>
  log: Log
}

export class Meshd {
  private stopped = false
  private aborter: AbortController | null = null
  private kinds: { at: number; value: MachineReport['kinds'] } | null = null
  private seats: { at: number; value: MachineReport['seats'] } | null = null
  private now: () => number
  private sleep: (ms: number) => Promise<void>

  constructor(private o: MeshdOpts) {
    this.now = o.now ?? Date.now
    this.sleep = o.sleep ?? (ms => new Promise(r => setTimeout(r, ms)))
  }

  private headers(json = false): Record<string, string> {
    return { authorization: `Bearer ${this.o.token}`, ...(json ? { 'content-type': 'application/json' } : {}) }
  }

  private async detectKinds(): Promise<MachineReport['kinds']> {
    if (this.kinds && this.now() - this.kinds.at < KINDS_EVERY_MS) return this.kinds.value
    // In parallel: five sequential 10 s timeouts would outlast the relay's stale window.
    const runs = await Promise.all(KINDS.map(kind => this.o.run(kind, ['--version'], 10_000)))
    const value: MachineReport['kinds'] = []
    KINDS.forEach((kind, i) => {
      const r = runs[i]!
      if (!r.ok) return
      const version = cleanVersion(r.stdout)
      value.push(version ? { kind, version } : { kind })
    })
    this.kinds = { at: this.now(), value }
    return value
  }

  private async readSeats(): Promise<MachineReport['seats']> {
    if (!this.o.ccQuota) return []
    if (this.seats && this.now() - this.seats.at < QUOTA_EVERY_MS) return this.seats.value
    const r = await this.o.run(this.o.ccQuota, this.o.ccQuotaArgs, 30_000)
    let value: MachineReport['seats'] = this.seats?.value ?? []
    if (r.ok) {
      try { value = parseCcQuota(JSON.parse(r.stdout)) } catch { /* keep the last reading */ }
    }
    this.seats = { at: this.now(), value }
    return value
  }

  async collect(): Promise<MachineReport> {
    const [list, ver, kinds, seats] = await Promise.all([
      this.o.run(this.o.herdrBin, ['agent', 'list'], 15_000),
      this.o.run(this.o.herdrBin, ['--version'], 10_000),
      this.detectKinds(),
      this.readSeats(),
    ])
    let agents: MachineReport['agents'] = []
    let herdr: { ok: boolean; version?: string; error?: string } = { ok: list.ok }
    if (list.ok) {
      try { agents = parseHerdrAgents(JSON.parse(list.stdout)) } catch { herdr = { ok: false, error: 'unreadable agent list' } }
    } else {
      herdr.error = (list.error ?? 'herdr failed').slice(0, 200)
    }
    const v = ver.ok ? cleanVersion(ver.stdout)?.replace(/^herdr\s+/, '') : undefined
    if (v && /^[A-Za-z0-9._+-]{1,32}$/.test(v)) herdr.version = v
    const load = this.o.load()
    return buildReport({
      version: MESHD_VERSION, herdr, agents,
      kinds, seats,
      load1: load.load1, cpus: load.cpus, ...(load.memUsedPct !== undefined ? { memUsedPct: load.memUsedPct } : {}),
      ...(this.o.maxActive !== undefined ? { maxActive: this.o.maxActive } : {}),
      roots: this.o.roots.map(r => ({ path: r.path, exists: r.exists() })),
    })
  }

  /** Collects and sends one report. Returns the HTTP status (0 when nothing reached the relay). */
  async report(): Promise<number> {
    let body: MachineReport
    try { body = await this.collect() } catch (err) {
      this.o.log('warn', 'meshd.collect_error', { err: String(err instanceof Error ? err.message : err) })
      return 0
    }
    return this.post(body)
  }

  private async post(body: MachineReport, retryOn429 = false): Promise<number> {
    const fit = fitReport(body)
    if (!fit) { this.o.log('error', 'meshd.report_unfit'); return 0 }
    if (fit.dropped.length) this.o.log('warn', 'meshd.report_trimmed', { dropped: fit.dropped.join(' ') })
    try {
      const res = await this.o.fetch(new URL('/v1/machines/self', this.o.relayUrl), { method: 'POST', headers: this.headers(true), body: JSON.stringify(fit.report) })
      if (res.status === 429 && retryOn429) {
        const wait = Math.min(10, Number(res.headers.get('retry-after')) || 3)
        await res.text().catch(() => '')
        await this.sleep(wait * 1000)
        return this.post(body, false)
      }
      if (res.status !== 200) this.o.log('warn', 'meshd.report_rejected', { status: res.status, body: (await res.text()).slice(0, 200) })
      return res.status
    } catch (err) {
      this.o.log('warn', 'meshd.report_error', { err: String(err instanceof Error ? err.message : err) })
      return 0
    }
  }

  /** Runs one relay command. Never throws: a failure is a result with ok=false. */
  async execute(raw: unknown): Promise<CommandResult> {
    // The relay validated it already; check again here, since this is where it turns into argv.
    const parsed = CommandRequestSchema.safeParse({ op: (raw as { op?: unknown })?.op, args: (raw as { args?: unknown })?.args })
    if (!parsed.success) return { ok: false, error: 'invalid command' }
    const cmd = parsed.data
    if (cmd.op === 'probe') {
      // A fresh report right now, so the caller's next machine list is current.
      const r = await this.collect().catch(() => null)
      if (!r) return { ok: false, error: 'collect failed' }
      // A probe right after a scheduled report can meet the relay's 2-per-5s limit: wait and send once more.
      const status = await this.post(r, true)
      return status === 200
        ? { ok: true, output: JSON.stringify({ herdr: r.herdr.ok, agents: r.agents.length, active: r.active, blocked: r.blocked }) }
        : { ok: false, error: `report ${status}` }
    }
    const pane = HerdrPaneIdSchema.parse(cmd.args.pane)
    const lines = String(cmd.args.lines ?? READ_DEFAULT_LINES)
    const r = await this.o.run(this.o.herdrBin, ['agent', 'read', pane, '--source', 'recent', '--lines', lines], 15_000)
    if (!r.ok) return { ok: false, error: (r.error ?? 'herdr agent read failed').slice(0, 500) }
    // Keep the end of the screen: that is where the agent is now.
    return { ok: true, output: r.stdout.length > OUTPUT_CAP ? r.stdout.slice(-OUTPUT_CAP) : r.stdout }
  }

  async postResult(id: string, result: CommandResult): Promise<number> {
    try {
      const res = await this.o.fetch(new URL(`/v1/commands/${encodeURIComponent(id)}/result`, this.o.relayUrl), {
        method: 'POST', headers: this.headers(true), body: JSON.stringify(result),
      })
      return res.status
    } catch (err) {
      this.o.log('warn', 'meshd.result_error', { id, err: String(err instanceof Error ? err.message : err) })
      return 0
    }
  }

  async onCommand(data: string): Promise<void> {
    let msg: { id?: unknown; op?: unknown; args?: unknown }
    try { msg = JSON.parse(data) as typeof msg } catch { return }
    if (typeof msg.id !== 'string') return
    const started = this.now()
    const result = await this.execute(msg)
    const status = await this.postResult(msg.id, result)
    this.o.log('info', 'meshd.command', { id: msg.id, op: String(msg.op), ok: result.ok, status, ms: this.now() - started })
  }

  /** Holds the executor stream open, reconnecting with backoff, until stop(). */
  async streamLoop(): Promise<void> {
    let attempt = 0
    while (!this.stopped) {
      this.aborter = new AbortController()
      try {
        const res = await this.o.fetch(new URL('/v1/machines/self/stream', this.o.relayUrl), {
          headers: { ...this.headers(), accept: 'text/event-stream' }, signal: this.aborter.signal,
        })
        if (res.status === 401 || res.status === 403) {
          this.o.log('error', 'meshd.stream_refused', { status: res.status })
          await this.sleep(60_000)
          continue
        }
        if (res.status !== 200 || !res.body) throw new Error(`stream http ${res.status}`)
        const openedAt = this.now()
        this.o.log('info', 'meshd.stream.open')
        const reader = (res.body as ReadableStream<Uint8Array>).getReader()
        const decoder = new TextDecoder()
        let buf = ''
        for (;;) {
          const { value, done } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const parts = buf.split('\n\n')
          buf = parts.pop() ?? ''
          for (const block of parts) {
            const ev = parseSseEvent(block)
            if (ev) attempt = 0
            if (ev?.event === 'command') void this.onCommand(ev.data)
          }
        }
        // Only a stream that stayed up resets the backoff: one that answers 200 and closes at once
        // (a proxy, a captive page) must not turn this into a 2-per-second loop.
        if (this.now() - openedAt >= 10_000) attempt = 0
      } catch (err) {
        if (this.stopped) break
        this.o.log('warn', 'meshd.stream.disconnect', { err: String(err instanceof Error ? err.message : err) })
      }
      if (this.stopped) break
      await this.sleep(Math.min(30_000, 500 * 2 ** Math.min(attempt++, 6)))
    }
  }

  async reportLoop(): Promise<void> {
    while (!this.stopped) {
      const status = await this.report()
      await this.sleep(status === 429 ? REPORT_EVERY_MS * 2 : REPORT_EVERY_MS)
    }
  }

  start(): Promise<void[]> {
    return Promise.all([this.reportLoop(), this.streamLoop()])
  }

  stop(): void {
    this.stopped = true
    this.aborter?.abort()
  }
}
