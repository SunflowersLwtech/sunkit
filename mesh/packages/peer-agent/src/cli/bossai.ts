import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { askHookSocket, hookSocketPath, type HookReply, type HookRequest } from '../hook-socket.ts'
import { meshDir } from '../paths.ts'
import { wakeNotice } from '../pi-extension.ts'
import { loadConfig, loadToken } from '../config.ts'
import { RelayClient } from '../outbound.ts'
import { sayWith } from './say.ts'
import { stableNode } from './devin.ts'

export const BOSSAI_USAGE =
  'usage: mesh bossai install [--server <url>] [--port-file <path>] [--id <mcp-server-id>] [--session <mesh-name>] [--node <path>] [--peer <path>] [--write]\n'
  + '       mesh bossai wake --chat <chatId> [--session <mesh-name>] [--server <url>] [--port-file <path>] [--token-file <path>] [--license-file <path>] [--notify <mesh-name>] [--poll-ms <n>] [--once]\n'
  + '                        [--bridge] [--allow <name-prefix,…>] [--grace-ms <n>]\n'
  + '\n'
  + 'install: register mesh-peer.mjs as a managed MCP server in the running BossAI desktop app\n'
  + '         (pure config; the BossAI session itself joins the mesh in pull mode).\n'
  + 'wake:    resident injector — BossAI has no hooks surface, so this plays the hooks\' role:\n'
  + '         poll the peer\'s hook socket, inject a mail notice via the local HTTP chat API\n'
  + '         (steer into an active run, else start a turn), report busy/idle, and optionally\n'
  + '         notify a mesh contact about pending tool approvals (never auto-approves).\n'
  + '         --bridge: while BossAI\'s own peer is offline (managed MCP connections close on\n'
  + '         session teardown), wake holds the mesh session with its own peer child, reads\n'
  + '         mail, stops the child, and injects the full letters so no mail waits for a turn.\n'
  + '         --allow: only inject mail whose sender name starts with one of these prefixes.\n'
  + 'wake needs a BossAI Cloud token: BOSSAI_CLOUD_TOKEN env or --token-file (chat API requires it).\n'
  + 'Cloud models also need the enterprise license per request: BOSSAI_CLOUD_LICENSE env or\n'
  + '--license-file (the licenseKey from the cloud /api/bossai/bootstrap response).'

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
  /** Enterprise cloud license (X-BossAI-Cloud-License); cloud models need it per request. */
  license?: string | undefined
  notify?: string | undefined
  pollMs: number
  /** Hold the mesh session with a bridge peer while BossAI's own peer is offline. */
  bridge?: boolean | undefined
  /** Sender name prefixes allowed to wake the worker; undefined = all. */
  allow?: string[] | undefined
  /** After the bridge stops, wait this long before restarting it (let BossAI's turn bind). */
  graceMs?: number | undefined
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

export interface BridgeHandle {
  ask: (req: HookRequest) => Promise<HookReply | undefined>
  /** read_messages text: <channel …> blocks, oldest first. */
  read: () => Promise<string>
  stop: () => Promise<void>
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
  /** Start/stop the idle-session bridge peer (--bridge). */
  startBridge?: (() => Promise<BridgeHandle>) | undefined
  log: (s: string) => void
  sleep: (ms: number) => Promise<void>
  now?: (() => number) | undefined
}

export interface ChannelLetter { attrs: string; from: string; body: string }

/** Parse formatInbox's <channel …> blocks so the whitelist can filter by sender. */
export function parseChannels(text: string): ChannelLetter[] {
  const out: ChannelLetter[] = []
  const re = /<channel([^>]*)>\n([\s\S]*?)\n<\/channel>/g
  for (const m of text.matchAll(re)) {
    const attrs = m[1] ?? ''
    const from = /from="([^"]*)"/.exec(attrs)?.[1] ?? ''
    out.push({ attrs, from, body: m[2] ?? '' })
  }
  return out
}

/** A sender is allowed when its name (before any [ref]) starts with an allowed prefix. */
export function senderAllowed(from: string, allow?: string[]): boolean {
  if (!allow || allow.length === 0) return true
  const name = from.split(' [')[0]!.trim()
  return allow.some(p => name.startsWith(p))
}

export function filterLetters(text: string, allow?: string[]): { kept: string; dropped: string[] } {
  const letters = parseChannels(text)
  const kept = letters.filter(l => senderAllowed(l.from, allow))
  const dropped = letters.filter(l => !senderAllowed(l.from, allow)).map(l => l.from)
  const lines = kept.map(l => `<channel${l.attrs}>\n${l.body}\n</channel>`)
  return { kept: lines.join('\n'), dropped }
}

export function bridgeNotice(letters: string): string {
  return `[mesh bridge] BossAI 空闲时 peer 不在线，以下信件由 wake 桥代收。请按信内 from 属性用 mesh 的 send_message 工具回复（本回合你的 mesh peer 已上线）。\n${letters}`
}

/**
 * One wake poll. Keeps its own pending notice: a wake nudge is consumed once per arrival
 * (HookChannel.nudgedSeq), so an injection that hit the global concurrency 409 must be
 * retried from here, not re-asked from the peer.
 *
 * --bridge: BossAI closes managed MCP connections on session teardown, so an idle app has no
 * peer and mail queues on the relay. While no BossAI socket answers, wake holds the session
 * with its own peer child, reads the mail, stops the child (so BossAI's turn can take the
 * session over without a second live connection), and injects the full letters. A grace
 * window after stopping keeps the bridge from flapping against short turns.
 */
export function createWaker(o: WakeOpts, d: WakeDeps) {
  let socket: string | undefined
  let pending: HookReply | undefined
  let busy = false
  let lastAskNotified: string | undefined
  let bridge: BridgeHandle | undefined
  let bridgeStoppedAt = 0
  let pendingLetters: string | undefined
  const now = d.now ?? Date.now
  const graceMs = o.graceMs ?? 15_000
  const stopBridge = async () => {
    if (!bridge) return
    await bridge.stop().catch(e => d.log(`bridge stop failed: ${(e as Error).message}`))
    bridge = undefined
    bridgeStoppedAt = now()
  }
  return {
    async tick(): Promise<void> {
      const entries = await d.discover()
      const bossaiSocket = pickHookSocket(entries, o.session)
      if (bossaiSocket) {
        await stopBridge()
        socket = bossaiSocket
      } else {
        socket = undefined
      }
      if (busy && !(await d.activeRun())) {
        busy = false
        if (socket) await d.ask(socket, { op: 'idle' })
      }
      if (socket) {
        if (!busy && !pending) {
          const r = await d.ask(socket, { op: 'wake' })
          if (r?.continue && r.unread > 0) pending = r
        }
        if (pending && !busy) {
          const active = await d.activeRun()
          const res = await d.inject(injectionBody(wakeNotice(pending), active))
          if (res.ok) {
            d.log(`injected mail notice (${pending.unread} from ${pending.from.join(', ')})${active ? ' [steer]' : ''}`)
            pending = undefined
            busy = true
            await d.ask(socket, { op: 'turn' })
          } else if (res.status === 409) {
            d.log('injection deferred: another run holds the concurrency slot')
          } else {
            d.log(`injection failed: HTTP ${res.status}`)
            pending = undefined
          }
        }
      } else if (o.bridge && d.startBridge && !busy) {
        if (pendingLetters) {
          const active = await d.activeRun()
          const res = await d.inject(injectionBody(bridgeNotice(pendingLetters), active))
          if (res.ok) { d.log('injected bridged letters (retry)'); pendingLetters = undefined; busy = true }
          else d.log(`bridge injection still failing: HTTP ${res.status}`)
        }
        if (!bridge && !pendingLetters && !busy && now() - bridgeStoppedAt >= graceMs && !(await d.activeRun())) {
          bridge = await d.startBridge().catch(e => { d.log(`bridge start failed: ${(e as Error).message}`); return undefined })
          if (bridge) d.log('bridge peer holding the session while BossAI is idle')
        }
        if (bridge) {
          const r = await bridge.ask({ op: 'wake' })
          if (r?.continue && r.unread > 0) {
            const text = await bridge.read()
            const { kept, dropped } = filterLetters(text, o.allow)
            if (dropped.length > 0) d.log(`discarded mail from non-allowed senders: ${dropped.join(', ')}`)
            await stopBridge()
            if (kept) {
              const active = await d.activeRun()
              const res = await d.inject(injectionBody(bridgeNotice(kept), active))
              if (res.ok) { d.log('injected bridged letters'); busy = true }
              else { d.log(`bridge injection deferred (HTTP ${res.status}); letters held for retry`); pendingLetters = kept }
            }
          }
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
    async shutdown(): Promise<void> { await stopBridge() },
  }
}

/** Scan MESH_HOME/hooks/*.sock and whoami each live peer. Skips wake's own bridge socket. */
export async function discoverBossaiSockets(dir: string = meshDir()): Promise<{ path: string; name?: string }[]> {
  const hooks = join(dir, 'hooks')
  if (!existsSync(hooks)) return []
  const own = hookSocketPath(process.pid, dir)
  const out: { path: string; name?: string }[] = []
  for (const f of readdirSync(hooks)) {
    if (!f.endsWith('.sock')) continue
    const path = join(hooks, f)
    if (path === own) continue
    const r = await askHookSocket(path, { op: 'whoami' }, 800)
    if (r?.name) out.push({ path, name: r.name })
  }
  return out
}

/**
 * The idle-session bridge: a mesh-peer child speaking MCP stdio, registered under the same
 * session name. Its hook socket is keyed by this process's pid (the peer's ppid). Stopping
 * closes the MCP transport, which kills the child and frees the session for BossAI's own peer.
 */
export async function startMcpBridge(o: { node: string; peer: string; session: string }): Promise<BridgeHandle> {
  const { Client } = await import('@modelcontextprotocol/sdk/client/index.js')
  const { StdioClientTransport, getDefaultEnvironment } = await import('@modelcontextprotocol/sdk/client/stdio.js')
  const transport = new StdioClientTransport({
    command: o.node,
    args: [o.peer],
    env: { ...getDefaultEnvironment(), MESH_JOIN: 'pull', MESH_HOST: 'bossai', MESH_SESSION_NAME: o.session, MESH_WAKE: '' },
  })
  const client = new Client({ name: 'bossai-wake-bridge', version: '0.1.0' })
  await client.connect(transport)
  const sock = hookSocketPath(process.pid)
  return {
    ask: req => askHookSocket(sock, req),
    read: async () => {
      const r = await client.callTool({ name: 'read_messages', arguments: {} })
      return ((r.content ?? []) as { type: string; text?: string }[]).map(c => c.text ?? '').join('\n')
    },
    stop: async () => { await client.close() },
  }
}

export function parseBossaiWake(args: string[], env: NodeJS.ProcessEnv = process.env): WakeOpts {
  const chat = flag(args, '--chat')
  if (!chat) throw new Error(BOSSAI_USAGE)
  const tokenFile = flag(args, '--token-file')
  const token = env.BOSSAI_CLOUD_TOKEN ?? (tokenFile ? readFileSync(tokenFile, 'utf8').trim() : undefined)
  if (!token) throw new Error('wake needs a BossAI Cloud token: BOSSAI_CLOUD_TOKEN env or --token-file <path> (the chat API requires cloud identity).')
  const licenseFile = flag(args, '--license-file')
  const license = env.BOSSAI_CLOUD_LICENSE ?? (licenseFile ? readFileSync(licenseFile, 'utf8').trim() : undefined)
  const pollMs = Number(flag(args, '--poll-ms') ?? 3_000)
  const graceMs = Number(flag(args, '--grace-ms') ?? 15_000)
  const allowRaw = flag(args, '--allow')
  return {
    chat,
    session: flag(args, '--session'),
    server: resolveBossaiServer({ server: flag(args, '--server'), portFile: flag(args, '--port-file') }),
    token,
    license,
    notify: flag(args, '--notify'),
    pollMs: Number.isFinite(pollMs) && pollMs >= 500 ? pollMs : 3_000,
    bridge: args.includes('--bridge'),
    allow: allowRaw ? allowRaw.split(',').map(s => s.trim()).filter(Boolean) : undefined,
    graceMs: Number.isFinite(graceMs) && graceMs >= 0 ? graceMs : 15_000,
  }
}

export async function runBossaiWake(args: string[], io: { log?: (s: string) => void; fetch?: FetchLike; once?: boolean } = {}): Promise<number> {
  const log = io.log ?? console.log
  let o: WakeOpts
  try { o = parseBossaiWake(args) } catch (e) { log((e as Error).message); return 2 }
  const fetchImpl = io.fetch ?? fetch
  const auth: Record<string, string> = { Authorization: `Bearer ${o.token}`, 'Content-Type': 'application/json' }
  if (o.license) auth['X-BossAI-Cloud-License'] = o.license
  const api = (path: string) => `${o.server}/api${path}`
  let relay: RelayClient | undefined
  if (o.notify) {
    const cfg = loadConfig()
    relay = new RelayClient({ relayUrl: cfg.relay_url, token: loadToken(cfg.token_path), senderName: o.session ?? 'bossai-wake' })
  }
  const waker = createWaker(o, {
    ask: (path, req) => askHookSocket(path, req),
    discover: () => discoverBossaiSockets(),
    startBridge: o.bridge
      ? () => startMcpBridge({
        node: stableNode(process.env.PATH, process.execPath),
        peer: fileURLToPath(new URL('./mesh-peer.mjs', import.meta.url)),
        session: o.session ?? `bossai-${o.chat}`,
      })
      : undefined,
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
  log(`bossai wake: chat=${o.chat} session=${o.session ?? '(unique bossai-* peer)'} server=${o.server}${o.notify ? ` notify=${o.notify}` : ''}${o.bridge ? ' bridge=on' : ''}${o.allow ? ` allow=${o.allow.join(',')}` : ''}`)
  if (io.once || args.includes('--once')) { await waker.tick(); await waker.shutdown(); return 0 }
  process.on('SIGINT', () => { void waker.shutdown().then(() => process.exit(0)) })
  process.on('SIGTERM', () => { void waker.shutdown().then(() => process.exit(0)) })
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