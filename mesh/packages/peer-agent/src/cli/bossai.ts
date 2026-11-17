import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { askHookSocket, type HookReply, type HookRequest } from '../hook-socket.ts'
import { meshDir } from '../paths.ts'
import { wakeNotice } from '../pi-extension.ts'
import { loadConfig, loadToken } from '../config.ts'
import { RelayClient } from '../outbound.ts'
import { sayWith } from './say.ts'
import { stableNode } from './devin.ts'

export const BOSSAI_USAGE =
  'usage: mesh bossai install [--server <url>] [--port-file <path>] [--id <mcp-server-id>] [--session <mesh-name>] [--node <path>] [--peer <path>] [--write]\n'
  + '       mesh bossai wake --chat <chatId> [--session <mesh-name>] [--server <url>] [--port-file <path>] [--token-file <path>] [--notify <mesh-name>] [--poll-ms <n>] [--once]\n'
  + '\n'
  + 'install: register mesh-peer.mjs as a managed MCP server in the running BossAI desktop app\n'
  + '         (pure config; the BossAI session itself joins the mesh in pull mode).\n'
  + 'wake:    resident injector — BossAI has no hooks surface, so this plays the hooks\' role:\n'
  + '         poll the peer\'s hook socket, inject a mail notice via the local HTTP chat API\n'
  + '         (steer into an active run, else start a turn), report busy/idle, and optionally\n'
  + '         notify a mesh contact about pending tool approvals (never auto-approves).\n'
  + 'wake needs a BossAI Cloud token: BOSSAI_CLOUD_TOKEN env or --token-file (chat API requires it).'

export interface BossaiInstallOpts {
  /** BossAI embedded server origin, e.g. http://127.0.0.1:57291. Discovered from the port file when absent. */
  server?: string | undefined
  /** Override the userData desktop-server-port.json path. */
  portFile?: string | undefined
  /** Managed MCP server id inside BossAI. */
  id: string
  /** Mesh session name the peer registers as (MESH_SESSION_NAME). */
  session?: string | undefined
  node: string
  peer: string
}

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : undefined
}

/** Electron userData of the desktop app, per platform (app name "@bossai/desktop"). */
export function bossaiPortFile(platform: NodeJS.Platform, env: NodeJS.ProcessEnv = process.env, home: string = homedir()): string {
  const base = platform === 'darwin'
    ? join(home, 'Library', 'Application Support')
    : platform === 'win32'
      ? (env.APPDATA ?? join(home, 'AppData', 'Roaming'))
      : (env.XDG_CONFIG_HOME ?? join(home, '.config'))
  return join(base, '@bossai', 'desktop', 'desktop-server-port.json')
}

/** Read the port file the desktop app writes; undefined when absent or malformed. */
export function readBossaiPort(path: string, read: (p: string) => string = p => readFileSync(p, 'utf8')): number | undefined {
  try {
    const port = (JSON.parse(read(path)) as { port?: unknown }).port
    return typeof port === 'number' && Number.isInteger(port) && port > 0 && port < 65536 ? port : undefined
  } catch { return undefined }
}

export function resolveBossaiServer(o: { server?: string | undefined; portFile?: string | undefined }, platform: NodeJS.Platform = process.platform, env: NodeJS.ProcessEnv = process.env): string {
  if (o.server) return o.server.replace(/\/+$/, '')
  const port = readBossaiPort(o.portFile ?? bossaiPortFile(platform, env))
  if (port === undefined) throw new Error('BossAI server port not found: is the desktop app running? Pass --server <url> or --port-file <path>.')
  return `http://127.0.0.1:${port}`
}

/** POST /api/mcp/servers body: the peer as a stdio MCP server, pull mode, named session. */
export function bossaiServerBody(o: BossaiInstallOpts): Record<string, unknown> {
  const env: Record<string, string> = { MESH_JOIN: 'pull', MESH_HOST: 'bossai', MESH_WAKE: '' }
  if (o.session) env.MESH_SESSION_NAME = o.session
  return {
    id: o.id,
    label: `mesh (${o.session ?? o.id})`,
    transport: { type: 'stdio', command: o.node, args: [o.peer], env },
    enabled: true,
  }
}

export function parseBossaiInstall(args: string[], defaults: BossaiInstallOpts): BossaiInstallOpts {
  return {
    server: flag(args, '--server') ?? defaults.server,
    portFile: flag(args, '--port-file') ?? defaults.portFile,
    id: flag(args, '--id') ?? defaults.id,
    session: flag(args, '--session') ?? defaults.session,
    node: flag(args, '--node') ?? defaults.node,
    peer: flag(args, '--peer') ?? defaults.peer,
  }
}

type FetchLike = (url: string, init?: { method?: string; headers?: Record<string, string>; body?: string; signal?: AbortSignal }) => Promise<{ ok: boolean; status: number; json(): Promise<unknown>; text(): Promise<string> }>

/** The MCP control plane trusts a same-origin browser bootstrap; curl-style callers mirror it. */
export async function bossaiControlToken(server: string, fetchImpl: FetchLike = fetch): Promise<string> {
  const res = await fetchImpl(`${server}/api/mcp/control-token`, { headers: { 'Sec-Fetch-Site': 'same-origin' }, signal: AbortSignal.timeout(8_000) })
  if (!res.ok) throw new Error(`control-token bootstrap failed: HTTP ${res.status}`)
  const token = (await res.json() as { token?: string }).token
  if (!token) throw new Error('control-token bootstrap returned no token')
  return token
}

export async function runBossaiInstall(args: string[], io: { log?: (s: string) => void; fetch?: FetchLike } = {}): Promise<number> {
  const log = io.log ?? console.log
  const o = parseBossaiInstall(args, {
    id: 'mesh',
    node: stableNode(process.env.PATH, process.execPath),
    // In the bundle this file is mesh-cli.mjs, next to mesh-peer.mjs.
    peer: fileURLToPath(new URL('./mesh-peer.mjs', import.meta.url)),
  })
  let server: string
  try { server = resolveBossaiServer(o) } catch (e) { log((e as Error).message); return 2 }
  const body = bossaiServerBody(o)
  log(`BossAI server: ${server}`)
  log(`POST /api/mcp/servers\n${JSON.stringify(body, null, 2)}`)
  log('The BossAI session joins the mesh in pull mode once the server connects (a chat turn or MCP discover).')
  log('Tools in BossAI: mesh list_agents / send_message / read_messages (managed MCP). Mail waits in an inbox; run `mesh bossai wake --chat <chatId>` to inject notices.')
  if (!args.includes('--write')) return 0
  const fetchImpl = io.fetch ?? fetch
  const token = await bossaiControlToken(server, fetchImpl)
  const res = await fetchImpl(`${server}/api/mcp/servers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-bossai-mcp-control-token': token },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(10_000),
  })
  if (res.status === 409) { log(`MCP server "${o.id}" already exists in BossAI; remove it in 设置 → MCP or pick another --id.`); return 1 }
  if (!res.ok) { log(`install failed: HTTP ${res.status} ${(await res.text()).slice(0, 200)}`); return 1 }
  log('written. Verify: BossAI 设置 → MCP shows the server; `mesh bossai wake` keeps a worker session reading mail.')
  return 0
}

// ---- wake -----------------------------------------------------------------

export interface WakeOpts {
  chat: string
  session?: string | undefined
  server: string
  token: string
  notify?: string | undefined
  pollMs: number
}

/** Choose the peer socket whose whoami name matches; with no --session, a unique bossai-* peer. */
export function pickHookSocket(entries: { path: string; name?: string }[], session?: string): string | undefined {
  if (session) return entries.find(e => e.name === session)?.path
  const bossai = entries.filter(e => e.name?.startsWith('bossai'))
  return bossai.length === 1 ? bossai[0]!.path : undefined
}

/** steer into an active run; a plain chat body starts a new turn when idle. */
export function injectionBody(notice: string, activeRun: boolean): Record<string, unknown> {
  return activeRun ? { text: notice, deliverAs: 'steer' } : { text: notice }
}

export function approvalNotice(ask: { toolName?: string; subtitle?: string; toolCallId: string }, chat: string): string {
  return `BossAI 审批请求 · ${ask.toolName ?? 'tool'}${ask.subtitle ? `: ${ask.subtitle}` : ''} — 会话 ${chat}，请到 BossAI 桌面端处理（默认 5 分钟超时自动拒）。mesh 不会代为批准。`
}

export interface WakeDeps {
  /** Ask a hook socket; undefined when nobody answers. */
  ask: (path: string, req: HookRequest) => Promise<HookReply | undefined>
  /** Candidate sockets with whoami names, refreshed by the caller. */
  discover: () => Promise<{ path: string; name?: string }[]>
  activeRun: () => Promise<boolean>
  inject: (body: Record<string, unknown>) => Promise<{ ok: boolean; status: number }>
  pendingAsk: () => Promise<{ toolCallId: string; toolName?: string; subtitle?: string } | undefined>
  notify: (text: string) => Promise<void>
  log: (s: string) => void
  sleep: (ms: number) => Promise<void>
}

/**
 * One wake poll. Keeps its own pending notice: a wake nudge is consumed once per arrival
 * (HookChannel.nudgedSeq), so an injection that hit the global concurrency 409 must be
 * retried from here, not re-asked from the peer.
 */
export function createWaker(o: WakeOpts, d: WakeDeps) {
  let socket: string | undefined
  let pending: HookReply | undefined
  let busy = false
  let lastAskNotified: string | undefined
  return {
    async tick(): Promise<void> {
      if (!socket || !(await d.ask(socket, { op: 'whoami' }))) {
        socket = pickHookSocket(await d.discover(), o.session)
      }
      const s = socket
      if (!s) return
      if (busy) {
        if (!(await d.activeRun())) { busy = false; await d.ask(s, { op: 'idle' }) }
      } else if (!pending) {
        const r = await d.ask(s, { op: 'wake' })
        if (r?.continue && r.unread > 0) pending = r
      }
      if (pending && !busy) {
        const active = await d.activeRun()
        const res = await d.inject(injectionBody(wakeNotice(pending), active))
        if (res.ok) {
          d.log(`injected mail notice (${pending.unread} from ${pending.from.join(', ')})${active ? ' [steer]' : ''}`)
          pending = undefined
          busy = true
          await d.ask(s, { op: 'turn' })
        } else if (res.status === 409) {
          d.log('injection deferred: another run holds the concurrency slot')
        } else {
          d.log(`injection failed: HTTP ${res.status}`)
          pending = undefined
        }
      }
      if (o.notify) {
        const ask = await d.pendingAsk()
        if (ask && ask.toolCallId !== lastAskNotified) {
          lastAskNotified = ask.toolCallId
          await d.notify(approvalNotice(ask, o.chat)).catch(e => d.log(`approval notify failed: ${(e as Error).message}`))
        }
        if (!ask) lastAskNotified = undefined
      }
    },
    async run(): Promise<void> {
      for (;;) { await this.tick(); await d.sleep(o.pollMs) }
    },
  }
}

/** Scan MESH_HOME/hooks/*.sock and whoami each live peer. */
export async function discoverBossaiSockets(dir: string = meshDir()): Promise<{ path: string; name?: string }[]> {
  const hooks = join(dir, 'hooks')
  if (!existsSync(hooks)) return []
  const out: { path: string; name?: string }[] = []
  for (const f of readdirSync(hooks)) {
    if (!f.endsWith('.sock')) continue
    const path = join(hooks, f)
    const r = await askHookSocket(path, { op: 'whoami' }, 800)
    if (r?.name) out.push({ path, name: r.name })
  }
  return out
}

export function parseBossaiWake(args: string[], env: NodeJS.ProcessEnv = process.env): WakeOpts {
  const chat = flag(args, '--chat')
  if (!chat) throw new Error(BOSSAI_USAGE)
  const tokenFile = flag(args, '--token-file')
  const token = env.BOSSAI_CLOUD_TOKEN ?? (tokenFile ? readFileSync(tokenFile, 'utf8').trim() : undefined)
  if (!token) throw new Error('wake needs a BossAI Cloud token: BOSSAI_CLOUD_TOKEN env or --token-file <path> (the chat API requires cloud identity).')
  const pollMs = Number(flag(args, '--poll-ms') ?? 3_000)
  return {
    chat,
    session: flag(args, '--session'),
    server: resolveBossaiServer({ server: flag(args, '--server'), portFile: flag(args, '--port-file') }),
    token,
    notify: flag(args, '--notify'),
    pollMs: Number.isFinite(pollMs) && pollMs >= 500 ? pollMs : 3_000,
  }
}

export async function runBossaiWake(args: string[], io: { log?: (s: string) => void; fetch?: FetchLike; once?: boolean } = {}): Promise<number> {
  const log = io.log ?? console.log
  let o: WakeOpts
  try { o = parseBossaiWake(args) } catch (e) { log((e as Error).message); return 2 }
  const fetchImpl = io.fetch ?? fetch
  const auth = { Authorization: `Bearer ${o.token}`, 'Content-Type': 'application/json' }
  const api = (path: string) => `${o.server}/api${path}`
  let relay: RelayClient | undefined
  if (o.notify) {
    const cfg = loadConfig()
    relay = new RelayClient({ relayUrl: cfg.relay_url, token: loadToken(cfg.token_path), senderName: o.session ?? 'bossai-wake' })
  }
  const waker = createWaker(o, {
    ask: (path, req) => askHookSocket(path, req),
    discover: () => discoverBossaiSockets(),
    activeRun: async () => {
      const res = await fetchImpl(api(`/pi/sessions/${o.chat}/runs/active`), { headers: auth, signal: AbortSignal.timeout(5_000) })
      if (!res.ok) return false
      return (await res.json() as { active?: boolean }).active === true
    },
    inject: async body => {
      const res = await fetchImpl(api(`/pi/sessions/${o.chat}/chat`), { method: 'POST', headers: auth, body: JSON.stringify(body), signal: AbortSignal.timeout(15_000) })
      return { ok: res.ok, status: res.status }
    },
    pendingAsk: async () => {
      const res = await fetchImpl(api(`/sessions/${o.chat}/permission-ask`), { headers: auth, signal: AbortSignal.timeout(5_000) })
      if (!res.ok) return undefined
      return (await res.json() as { pending?: { toolCallId: string; toolName?: string; subtitle?: string } }).pending ?? undefined
    },
    notify: async text => {
      if (!relay || !o.notify) return
      log(await sayWith(relay, { as: o.session ?? 'bossai-wake', to: o.notify, message: text }))
    },
    log,
    sleep: ms => new Promise(r => setTimeout(r, ms)),
  })
  log(`bossai wake: chat=${o.chat} session=${o.session ?? '(unique bossai-* peer)'} server=${o.server}${o.notify ? ` notify=${o.notify}` : ''}`)
  if (io.once || args.includes('--once')) { await waker.tick(); return 0 }
  await waker.run()
  return 0
}

export async function runBossai(args: string[]): Promise<number> {
  const [sub, ...rest] = args
  if (sub === 'install') return runBossaiInstall(rest)
  if (sub === 'wake') return runBossaiWake(rest)
  console.error(BOSSAI_USAGE)
  return 2
}