import { MachineAgentSchema, MachineReportSchema, type MachineAgent, type MachineReport } from '@claude-mesh/shared'

// Pure parsing for meshd: turns what herdr, cc-quota and `<agent> --version` print into the
// relay's closed MachineReport shape. Anything that does not fit is dropped, never forwarded raw.

interface HerdrAgent {
  agent?: unknown
  agent_status?: unknown
  agent_session?: { kind?: unknown; value?: unknown } | null
  cwd?: unknown
  name?: unknown
  pane_id?: unknown
  tab_id?: unknown
  workspace_id?: unknown
  terminal_title_stripped?: unknown
}

const str = (v: unknown): string | undefined => (typeof v === 'string' && v.length > 0 ? v : undefined)

/** `herdr agent list` JSON → report agents. Entries that fail the schema are skipped one by one. */
export function parseHerdrAgents(raw: unknown): MachineAgent[] {
  const list = (raw as { result?: { agents?: unknown } } | null)?.result?.agents
  if (!Array.isArray(list)) return []
  const out: MachineAgent[] = []
  for (const a of list as HerdrAgent[]) {
    const pane = str(a.pane_id)
    if (!pane) continue
    const session = a.agent_session && str(a.agent_session.value)
      ? { kind: str(a.agent_session.kind) ?? 'unknown', value: str(a.agent_session.value)!.slice(0, 1024) }
      : undefined
    const candidate = {
      name: (str(a.name) ?? str(a.terminal_title_stripped) ?? pane).slice(0, 64),
      agent: (str(a.agent) ?? 'unknown').toLowerCase().slice(0, 32),
      status: str(a.agent_status) ?? 'unknown',
      pane,
      ...(str(a.tab_id) ? { tab: str(a.tab_id) } : {}),
      ...(str(a.workspace_id) ? { workspace: str(a.workspace_id) } : {}),
      ...(str(a.cwd) ? { cwd: str(a.cwd)!.slice(0, 1024) } : {}),
      ...(session ? { agent_session: session } : {}),
    }
    const parsed = MachineAgentSchema.safeParse(candidate)
    if (parsed.success) out.push(parsed.data)
    if (out.length >= 64) break
  }
  return out
}

interface QuotaAccount {
  config_dir?: unknown
  email?: unknown
  org_name?: unknown
  subscription?: unknown
  five_hour?: { pct?: unknown; resets_at?: unknown } | null
  blocked?: unknown
}

/** `cc-quota --json` → seats: every config dir cc-quota reads (dispatch picks the default one). */
export function parseCcQuota(raw: unknown): MachineReport['seats'] {
  const accounts = (raw as { accounts?: unknown } | null)?.accounts
  if (!Array.isArray(accounts)) return []
  const seats: MachineReport['seats'] = []
  for (const a of accounts as QuotaAccount[]) {
    const email = str(a.email)
    if (!email || !/^[^\s<>"&]+@[^\s<>"&]+$/.test(email)) continue
    const pct = typeof a.five_hour?.pct === 'number' ? a.five_hour.pct : undefined
    const resets = str(a.five_hour?.resets_at)
    seats.push({
      email,
      ...(str(a.org_name) ? { org: str(a.org_name)!.slice(0, 64) } : {}),
      ...(str(a.subscription) && /^[a-z_-]{1,16}$/.test(str(a.subscription)!) ? { plan: str(a.subscription) } : {}),
      ...(pct !== undefined && pct >= 0 && pct <= 1000 ? { five_hour_pct: pct } : {}),
      ...(resets && !Number.isNaN(Date.parse(resets)) ? { resets_at: new Date(resets).toISOString() } : {}),
      blocked: Array.isArray(a.blocked) && a.blocked.length > 0,
    })
    if (seats.length >= 6) break
  }
  return seats
}

/** First line of `<cli> --version`, reduced to the characters the relay accepts. */
export function cleanVersion(out: string): string | undefined {
  const line = out.split('\n').map(l => l.trim()).find(Boolean)
  if (!line) return undefined
  const v = line.replace(/[^A-Za-z0-9._ ()+-]/g, '').slice(0, 64).trim()
  return v || undefined
}

export interface CollectInput {
  version: string
  herdr: { ok: boolean; version?: string; error?: string }
  agents: MachineAgent[]
  kinds: MachineReport['kinds']
  seats: MachineReport['seats']
  load1: number
  cpus: number
  memUsedPct?: number
  maxActive?: number
  roots: Array<{ path: string; exists: boolean }>
}

export function buildReport(i: CollectInput): MachineReport {
  return {
    version: i.version,
    herdr: { ok: i.herdr.ok, ...(i.herdr.version ? { version: i.herdr.version } : {}), ...(i.herdr.error ? { error: i.herdr.error.slice(0, 200) } : {}) },
    load: { load1: Math.max(0, Math.round(i.load1 * 100) / 100), cpus: Math.max(1, i.cpus), ...(i.memUsedPct !== undefined ? { mem_used_pct: Math.round(i.memUsedPct) } : {}) },
    kinds: i.kinds.slice(0, 8),
    seats: i.seats,
    active: i.agents.filter(a => a.status === 'working').length,
    blocked: i.agents.filter(a => a.status === 'blocked').length,
    ...(i.maxActive !== undefined ? { max_active: i.maxActive } : {}),
    agents: i.agents,
    roots: i.roots.slice(0, 8),
  }
}

const LISTS = ['agents', 'seats', 'kinds', 'roots'] as const
const OPTIONAL = ['max_active'] as const

/**
 * Makes a report fit the relay's schema by dropping what does not: an offending list entry or an
 * optional field. One bad value must not cost the whole report (the relay refuses it all).
 * Returns null when the problem is in a field that cannot be dropped.
 */
export function fitReport(report: MachineReport): { report: MachineReport; dropped: string[] } | null {
  let r: Record<string, unknown> = { ...report }
  const dropped: string[] = []
  for (let round = 0; round < 5; round++) {
    const parsed = MachineReportSchema.safeParse(r)
    if (parsed.success) return { report: parsed.data, dropped }
    const remove = new Map<string, Set<number>>()
    for (const issue of parsed.error.issues) {
      const [top, idx] = issue.path
      if (typeof top === 'string' && (LISTS as readonly string[]).includes(top) && typeof idx === 'number') {
        if (!remove.has(top)) remove.set(top, new Set())
        remove.get(top)!.add(idx)
      } else if (typeof top === 'string' && (OPTIONAL as readonly string[]).includes(top)) {
        delete r[top]
        dropped.push(top)
      } else {
        return null
      }
    }
    for (const [top, idxs] of remove) {
      r = { ...r, [top]: (r[top] as unknown[]).filter((_, i) => !idxs.has(i)) }
      dropped.push(`${top}[${[...idxs].join(',')}]`)
    }
  }
  return null
}
