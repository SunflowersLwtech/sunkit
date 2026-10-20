import { basename } from 'node:path'
import { AgentKindSchema, CardPatchSchema, HerdrLocationSchema, TaskIdSchema, type CardPatch } from '@claude-mesh/shared'

/**
 * The session's card on the relay: what it is, where it runs, what it works on. The peer is
 * its only writer on this machine; host hooks tell the peer what changed and the peer writes,
 * at most once per batch window and only the fields that changed.
 */
export type CardFields = Pick<CardPatch, 'agent' | 'model' | 'repo' | 'branch' | 'herdr' | 'task_id' | 'source'>

const FIELD = CardPatchSchema.shape

function fit<K extends keyof CardFields>(key: K, value: unknown): CardFields[K] | undefined {
  const r = FIELD[key].safeParse(value)
  return r.success ? (r.data as CardFields[K]) : undefined
}

export interface InitialCardInput {
  env: NodeJS.ProcessEnv
  /** MESH_HOST of a pull host (agy, grok, devin, pi); undefined for Claude Code. */
  host: string | undefined
  /** This machine's name as Herdr and meshd know it (config `machine` or MESH_MACHINE). */
  machine: string | undefined
  /** Runs git in the session's directory; undefined when it fails. */
  git: (args: string[]) => string | undefined
}

/** What the peer can tell about its session at startup. Anything that does not fit the relay's fields is left out. */
export function initialCard(i: InitialCardInput): CardFields {
  const card: CardFields = {}
  const agent = AgentKindSchema.safeParse(i.host ?? 'claude')
  if (agent.success) card.agent = agent.data
  const model = fit('model', i.env.MESH_MODEL?.trim())
  if (model) card.model = model
  const top = i.git(['rev-parse', '--show-toplevel'])?.trim()
  const repo = top ? fit('repo', basename(top)) : undefined
  if (repo) card.repo = repo
  const branch = i.git(['rev-parse', '--abbrev-ref', 'HEAD'])?.trim()
  const b = branch && branch !== 'HEAD' ? fit('branch', branch) : undefined
  if (b) card.branch = b
  if (i.env.HERDR_ENV === '1' && i.machine) {
    const herdr = HerdrLocationSchema.safeParse({
      machine: i.machine,
      ...(i.env.HERDR_TAB_ID ? { tab: i.env.HERDR_TAB_ID } : {}),
      ...(i.env.HERDR_PANE_ID ? { pane: i.env.HERDR_PANE_ID } : {}),
    })
    if (herdr.success) card.herdr = herdr.data
  }
  const task = TaskIdSchema.safeParse(i.env.MESH_TASK_ID)
  if (task.success) card.task_id = task.data
  return card
}

export interface CardWriterOpts {
  delayMs?: number
  /** MESH_CARD_WRITE=0 turns the card off: nothing is written. */
  enabled?: boolean
  /** Runs fn after the delay; returns a cancel. Tests replace it. */
  schedule?: (fn: () => void, ms: number) => () => void
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export class CardWriter {
  private card: CardFields = {}
  private sent: CardFields = {}
  private cancel: (() => void) | null = null
  private failures = 0
  private readonly delayMs: number
  private readonly enabled: boolean
  private readonly schedule: (fn: () => void, ms: number) => () => void

  constructor(private readonly write: (patch: CardFields) => Promise<void>, opts: CardWriterOpts = {}) {
    this.delayMs = opts.delayMs ?? 2_000
    this.enabled = opts.enabled ?? true
    this.schedule = opts.schedule ?? ((fn, ms) => { const t = setTimeout(fn, ms); t.unref?.(); return () => clearTimeout(t) })
  }

  get current(): CardFields { return { ...this.card } }

  set(patch: CardFields): void {
    if (!this.enabled) return
    this.card = { ...this.card, ...Object.fromEntries(Object.entries(patch).filter(([, v]) => v !== undefined)) }
    this.arm()
  }

  /** The relay lost the card (it restarted, the stream reattached): send all of it again. */
  resend(): void {
    if (!this.enabled) return
    this.sent = {}
    this.arm()
  }

  private pending(): CardFields {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(this.card)) if (!same(v, (this.sent as Record<string, unknown>)[k])) out[k] = v
    return out as CardFields
  }

  private arm(): void {
    if (this.cancel || Object.keys(this.pending()).length === 0) return
    // After failures, wait longer each time (up to a minute) instead of hitting the relay every window.
    const delay = Math.min(60_000, this.delayMs * 2 ** this.failures)
    this.cancel = this.schedule(() => { this.cancel = null; void this.flush() }, delay)
  }

  async flush(): Promise<void> {
    if (!this.enabled) return
    const patch = this.pending()
    if (Object.keys(patch).length === 0) return
    try {
      await this.write(patch)
      this.sent = { ...this.sent, ...patch }
      this.failures = 0
    } catch (err) {
      const { status, code } = err as { status?: number; code?: string }
      if (status !== undefined && status >= 400 && status < 500 && status !== 404 && status !== 429) {
        // The relay refuses this for good (a task that is gone or not ours, a value it rejects):
        // drop it and send the rest, rather than asking again forever.
        if (code === 'task_not_assigned') {
          delete this.card.task_id
        } else {
          this.sent = { ...this.sent, ...patch }
        }
      } else {
        // Not attached yet, rate-limited, relay down: kept as pending, tried again later.
        this.failures = Math.min(this.failures + 1, 10)
      }
    }
    this.arm()
  }
}
