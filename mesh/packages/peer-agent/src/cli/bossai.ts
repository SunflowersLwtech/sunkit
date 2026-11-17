import { existsSync, readFileSync, readdirSync, mkdirSync, copyFileSync, chmodSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { askHookSocket, hookSocketPath, type HookReply, type HookRequest } from '../hook-socket.ts'
import { meshDir } from '../paths.ts'
import { wakeNotice } from '../pi-extension.ts'
import { loadConfig, loadToken } from '../config.ts'
import { RelayClient } from '../outbound.ts'
import { sayWith } from './say.ts'
import { stableNode } from './devin.ts'
import { bossaiPortFile } from './bossai-paths.ts'
import { parseAllow } from '../sender-allow.ts'

export { bossaiPortFile }

export const BOSSAI_USAGE =
  'usage: mesh bossai install [--server <url>] [--port-file <path>] [--id <mcp-server-id>] [--session <mesh-name>] [--allow <name,…>] [--node <path>] [--peer <path>] [--write]\n'
  + '       mesh bossai wake --chat <chatId> [--session <mesh-name>] [--server <url>] [--port-file <path>] [--token-file <path>] [--license-file <path>] [--notify <mesh-name>] [--poll-ms <n>] [--once]\n'
  + '                        [--bridge] [--allow <name-prefix,…>] [--approvers <name@token-id,…>] [--grace-ms <n>] [--run-mode cloud|hybrid|local] [--model <id>]\n'
  + '\n'
  + 'install: register mesh-peer.mjs as a managed MCP server in the running BossAI desktop app\n'
  + '         (pure config; the BossAI session itself joins the mesh in pull mode).\n'
  + '         --allow: the peer itself only takes mail from a live session ("<name> [ref]", not\n'
  + '         send-only) with a listed name, on its own mesh account, sent with the pinned token\n'
  + '         (MESH_ALLOW, <session-name>@<token-id>). Use the same pins as wake --allow: mid-turn\n'
  + '         BossAI reads its mail with read_messages, which wake never sees.\n'
  + 'wake:    resident injector — BossAI has no hooks surface, so this plays the hooks\' role:\n'
  + '         poll the peer\'s hook socket, inject a mail notice via the local HTTP chat API\n'
  + '         (steer into an active run, else start a turn), report busy/idle, and optionally\n'
  + '         notify a mesh contact about pending tool approvals (never auto-approves).\n'
  + '         --bridge: while BossAI\'s own peer is offline (managed MCP connections close on\n'
  + '         session teardown), wake holds the mesh session with its own peer child, reads\n'
  + '         mail, stops the child, and injects the full letters so no mail waits for a turn.\n'
  + '         --allow: only inject mail that --approvers would accept as a sender: a live session\n'
  + '         with that name, on the worker\'s own account, sent with the pinned token. Entries are\n'
  + '         <session-name>@<token-id>, like --approvers; a bare name or an empty list is refused.\n'
  + '         --approvers: hold a permanent <session>-ctl mesh session; approvers reply there with\n'
  + '         APPROVE/DENY <toolCallId> [reason] and wake settles the ask (scope once, never auto).\n'
  + '         Only a live session (from="<name> [ref]", not send-only) whose name equals an approver,\n'
  + '         on the worker\'s own account, sent with that approver\'s device token may settle: each\n'
  + '         entry is <session-name>@<token-id> (the id, not the token: GET /v1/admin/tokens lists\n'
  + '         them by device label). The relay stamps every letter with its sender token\'s id, so a\n'
  + '         session of the same name on another token of the account is refused, and so is a\n'
  + '         letter from a relay too old to stamp it.\n'
  + '         --run-mode/--model: sent with every new turn wake starts (a turn without them falls to\n'
  + '         the session default, and a local first turn locks the session to local for good).\n'
  + 'wake needs a BossAI Cloud token: BOSSAI_CLOUD_TOKEN env (inject it from the secret store, e.g. vk run -r)\n'
  + 'or --token-file (refused when group/other can read it). --server must be a loopback URL.\n'
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
  /** `<name>@<token-id>` pins the peer takes mail from (MESH_ALLOW); undefined = every sender. */
  allow?: string[] | undefined
  node: string
  peer: string
}

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : undefined
}


/** Read the port file the desktop app writes; undefined when absent or malformed. */
export function readBossaiPort(path: string, read: (p: string) => string = p => readFileSync(p, 'utf8')): number | undefined {
  try {
    const port = (JSON.parse(read(path)) as { port?: unknown }).port
    return typeof port === 'number' && Number.isInteger(port) && port > 0 && port < 65536 ? port : undefined
  } catch { return undefined }
}

export function assertLoopbackServer(url: string): string {
  let host: string
  try { host = new URL(url).hostname } catch { throw new Error(`--server is not a URL: ${url}`) }
  if (!['127.0.0.1', 'localhost', '[::1]', '::1'].includes(host)) {
    throw new Error(`--server must be a loopback URL (the BossAI server only listens on 127.0.0.1); got ${host}`)
  }
  return url
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
  if (o.allow?.length) env.MESH_ALLOW = o.allow.join(',')
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
    allow: (() => {
      const raw = flag(args, '--allow')
      if (raw === undefined) return defaults.allow
      const allow = parseAllow(raw)
      if (allow === undefined) throw new Error('--allow is empty; give <session-name>@<token-id>,… or leave the flag out')
      return allow
    })(),
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
  /** `<name>@<token-id>` pins whose mail is injected (same rule as approvers); undefined = all. */
  allow?: string[] | undefined
  /** `<name>@<token-id>` pins allowed to settle approval asks via the control session; undefined = notify only. */
  approvers?: string[] | undefined
  /** The worker's own mesh account; approval replies must come from this account (names alone are spoofable). */
  account?: string | undefined
  /** After the bridge stops, wait this long before restarting it (let BossAI's turn bind). */
  graceMs?: number | undefined
  /** Sent with every new turn wake starts; without it a turn falls to the session default. */
  runMode?: 'cloud' | 'hybrid' | 'local' | undefined
  model?: string | undefined
}

/** Choose the peer socket whose whoami name matches; with no --session, a unique bossai-* peer. */
export function pickHookSocket(entries: { path: string; name?: string }[], session?: string): string | undefined {
  if (session) return entries.find(e => e.name === session)?.path
  const bossai = entries.filter(e => e.name?.startsWith('bossai'))
  return bossai.length === 1 ? bossai[0]!.path : undefined
}

/** steer into an active run; a plain chat body starts a new turn when idle. */
export function injectionBody(notice: string, activeRun: boolean, turn: { runMode?: string | undefined; model?: string | undefined } = {}): Record<string, unknown> {
  if (activeRun) return { text: notice, deliverAs: 'steer' }
  return { text: notice, ...(turn.runMode ? { runMode: turn.runMode } : {}), ...(turn.model ? { model: turn.model } : {}) }
}

/** Shell asks carry the command line: send a short, redacted form to the --notify contact. */
export function redactSubtitle(s: string, max = 160): string {
  const r = s
    .replace(/(bearer\s+)\S+/gi, '$1[redacted]')
    .replace(/((?:token|key|secret|password|passwd|pwd|auth)[\w-]*\s*[=:]\s*)("[^"]*"|'[^']*'|\S+)/gi, '$1[redacted]')
    .replace(/[A-Za-z0-9_+/=-]{32,}/g, '[redacted]')
  return r.length > max ? `${r.slice(0, max)}…` : r
}

export function approvalNotice(ask: { toolName?: string; subtitle?: string; toolCallId: string }, chat: string, ctlSession?: string): string {
  const how = ctlSession
    ? `批准/拒绝：给 mesh 会话 ${ctlSession} 发「APPROVE ${ask.toolCallId}」或「DENY ${ask.toolCallId} <理由>」（仅白名单批准人有效，一次性放行）。`
    : '请到 BossAI 桌面端处理。'
  return `BossAI 审批请求 · ${ask.toolName ?? 'tool'}${ask.subtitle ? `: ${redactSubtitle(ask.subtitle)}` : ''} — 会话 ${chat}。${how}默认 5 分钟超时自动拒；mesh 不会代为批准。`
}

export type ApprovalCommand = { action: 'allow' | 'deny'; toolCallId: string; reason?: string }

/** APPROVE <id> / DENY <id> [reason] — the mesh-side approval reply format. */
export function parseApprovalCommand(body: string): ApprovalCommand | undefined {
  const m = /^\s*(APPROVE|DENY)\s+(\S+)(?:\s+([\s\S]*))?$/i.exec(body.trim())
  if (!m) return undefined
  const reason = m[3]?.trim()
  return {
    action: m[1]!.toUpperCase() === 'APPROVE' ? 'allow' : 'deny',
    toolCallId: m[2]!,
    ...(reason ? { reason: reason.slice(0, 500) } : {}),
  }
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
  discover: () => Promise<{ path: string; name?: string; mode?: 'pull' | 'push' | 'send' }[]>
  activeRun: () => Promise<boolean>
  inject: (body: Record<string, unknown>) => Promise<{ ok: boolean; status: number }>
  pendingAsk: () => Promise<{ toolCallId: string; toolName?: string; subtitle?: string } | undefined>
  notify: (text: string) => Promise<void>
  /** Start/stop the idle-session bridge peer (--bridge). */
  startBridge?: (() => Promise<BridgeHandle>) | undefined
  /** Permanent control-session peer reading approval replies (--approvers). */
  startCtl?: (() => Promise<{ read: () => Promise<string> }>) | undefined
  /** Settle a pending approval ask (scope once, never memorized). */
  resolveAsk?: ((toolCallId: string, action: 'allow' | 'deny', reason?: string) => Promise<{ ok: boolean; status: number }>) | undefined
  log: (s: string) => void
  sleep: (ms: number) => Promise<void>
  now?: (() => number) | undefined
}

export interface ChannelLetter { attrs: string; from: string; body: string }

/**
 * The keys a <channel> tag carries when nothing but the relay wrote it. Sender meta is rendered
 * first and can add any other key (`x_from`, `reply_from`, …), so a key is read by its exact name,
 * never by a substring search, and a letter with a key outside this set is not trusted. It must
 * equal the keys shared's envelopeToChannelNotification reserves, or a real approval is refused.
 * `from_token` is the relay-stamped id of the sending token; shared drops a sender's own.
 */
export const CHANNEL_KEYS: ReadonlySet<string> = new Set(['from', 'sender', 'account', 'from_token', 'login', 'msg_id', 'in_reply_to', 'thread_root', 'source'])

/**
 * Parse ` key="value" …` exactly: every byte belongs to an attribute and no key appears twice.
 * Undefined when the tag is malformed or repeats a key.
 */
export function parseAttrs(attrs: string): Map<string, string> | undefined {
  const re = /\s+([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"/y
  const out = new Map<string, string>()
  let i = 0
  for (;;) {
    re.lastIndex = i
    const m = re.exec(attrs)
    if (!m) break
    if (out.has(m[1]!)) return undefined
    out.set(m[1]!, m[2]!)
    i = re.lastIndex
  }
  return attrs.slice(i).trim() === '' ? out : undefined
}

/** Whether a letter's tag can be trusted at all: well-formed, no repeated key, only relay keys. */
export function letterShape(letter: ChannelLetter): 'ok' | 'malformed' | 'unknown-key' {
  const f = parseAttrs(letter.attrs)
  if (!f) return 'malformed'
  for (const k of f.keys()) if (!CHANNEL_KEYS.has(k)) return 'unknown-key'
  return 'ok'
}

/** Parse formatInbox's <channel …> blocks so the whitelist can filter by sender. */
export function parseChannels(text: string): ChannelLetter[] {
  const out: ChannelLetter[] = []
  const re = /<channel([^>]*)>\n([\s\S]*?)\n<\/channel>/g
  for (const m of text.matchAll(re)) {
    const attrs = m[1] ?? ''
    const from = parseAttrs(attrs)?.get('from') ?? ''
    out.push({ attrs, from, body: m[2] ?? '' })
  }
  return out
}

/**
 * Who may settle an approval. A send-only sender's name is a label any script on the account
 * picks, so only a live session counts (`from` carries `[ref]`, no `sender` attr), its name must
 * equal an approver exactly (no prefixes: `feishu-assistant-x` is not `feishu-assistant`), the
 * relay-verified account must be the worker's own, and the letter must carry the relay-stamped
 * token id an entry `<name>@<token-id>` pins. A bare `<name>` entry is `unpinned` and never settles.
 * Unknown own account fails closed.
 */
export function approverVerdict(letter: ChannelLetter, approvers: string[], account: string | undefined): 'ok' | 'malformed' | 'unknown-key' | 'send-only' | 'not-an-approver' | 'foreign-account' | 'no-own-account' | 'unpinned' | 'no-token' | 'wrong-token' {
  const shape = letterShape(letter)
  if (shape !== 'ok') return shape
  const f = parseAttrs(letter.attrs)!
  if (f.has('sender')) return 'send-only'
  const m = /^(\S+) \[([a-z0-9]+)\]$/.exec(f.get('from') ?? '')
  if (!m) return 'send-only'
  const entries = approvers.map(splitPin).filter(a => a.name === m[1])
  if (entries.length === 0) return 'not-an-approver'
  if (!account) return 'no-own-account'
  if (f.get('account') !== account) return 'foreign-account'
  // A name is any session's choice, even across one account's devices: only a pinned entry can
  // settle, and only with the relay-stamped id of the token that sent the letter. A bare name never
  // does, even next to a pin for the same name. No stamp (an older relay) fails closed.
  const pins = entries.filter(a => a.token)
  if (pins.length === 0) return 'unpinned'
  const token = f.get('from_token')
  if (!token) return 'no-token'
  return pins.some(a => a.token === token) ? 'ok' : 'wrong-token'
}

function splitPin(entry: string): { name: string; token?: string } {
  const i = entry.lastIndexOf('@')
  return i < 0 ? { name: entry } : { name: entry.slice(0, i), token: entry.slice(i + 1) }
}

/** --approvers: every entry must pin a token, `<session-name>@<token-id>`; a bare name is refused. */
export function parseApprovers(raw: string): string[] {
  const entries = raw.split(',').map(s => s.trim()).filter(Boolean)
  for (const e of entries) {
    if (!/^[^\s@\[\]<>"&]+@[A-Za-z0-9_-]{1,64}$/.test(e)) {
      throw new Error(`--approvers entry "${e}" must be <session-name>@<token-id> (token ids: GET /v1/admin/tokens)`)
    }
  }
  return entries
}

/** A sender is allowed when its name (before any [ref]) starts with an allowed prefix. */
export function senderAllowed(from: string, allow?: string[]): boolean {
  if (!allow || allow.length === 0) return true
  const name = from.split(' [')[0]!.trim()
  return allow.some(p => name.startsWith(p))
}

export function filterLetters(text: string, allow?: string[]): { kept: string; dropped: string[] } {
  const letters = parseChannels(text)
  // With an allow-list, a letter whose tag cannot be read exactly is dropped, whatever it names.
  const keep = (l: ChannelLetter) => senderAllowed(l.from, allow) && (!allow?.length || letterShape(l) === 'ok')
  const kept = letters.filter(keep)
  const dropped = letters.filter(l => !keep(l)).map(l => l.from || '(unreadable tag)')
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
  let ctl: { read: () => Promise<string> } | undefined
  const ctlSession = o.session ? `${o.session}-ctl` : undefined
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
      // Send-only peers (the app's managed MCP peer) serve a hook socket under the same
      // name but hold no inbox; only a pull peer means BossAI itself is reading mail.
      const bossaiSocket = pickHookSocket(entries.filter(e => e.mode !== 'send'), o.session)
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
          const res = await d.inject(injectionBody(wakeNotice(pending), active, o))
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
          const res = await d.inject(injectionBody(bridgeNotice(pendingLetters), active, o))
          if (res.ok) { d.log('injected bridged letters (retry)'); pendingLetters = undefined; busy = true }
          else d.log(`bridge injection still failing: HTTP ${res.status}`)
        }
        // The bridge holds the session permanently: the app peer is send-only and never
        // takes over the stream, and fleet sweeps reap processes whose mesh name is offline.
        if (!bridge && !pendingLetters && !busy && now() - bridgeStoppedAt >= graceMs) {
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
              // Held before the request: a throw here must not lose letters already read off the peer.
              pendingLetters = kept
              const active = await d.activeRun()
              const res = await d.inject(injectionBody(bridgeNotice(kept), active, o))
              if (res.ok) { d.log('injected bridged letters'); busy = true; pendingLetters = undefined }
              else d.log(`bridge injection deferred (HTTP ${res.status}); letters held for retry`)
            }
          }
        }
      }
      if (o.notify) {
        const ask = await d.pendingAsk()
        if (ask && ask.toolCallId !== lastAskNotified) {
          lastAskNotified = ask.toolCallId
          await d.notify(approvalNotice(ask, o.chat, o.approvers?.length ? ctlSession : undefined)).catch(e => d.log(`approval notify failed: ${(e as Error).message}`))
        }
        if (!ask) lastAskNotified = undefined
      }
      if (o.approvers?.length && d.startCtl && d.resolveAsk && ctlSession) {
        if (!ctl) ctl = await d.startCtl().catch(e => { d.log(`ctl peer start failed: ${(e as Error).message}`); return undefined })
        if (ctl) {
          const text = await ctl.read().catch(() => '')
          for (const letter of parseChannels(text)) {
            const cmd = parseApprovalCommand(letter.body)
            if (!cmd) { d.log(`ctl: non-command mail from ${letter.from} discarded`); continue }
            const verdict = approverVerdict(letter, o.approvers, o.account)
            if (verdict !== 'ok') { d.log(`ctl: approval from ${letter.from} ignored (${verdict})`); continue }
            const res = await d.resolveAsk(cmd.toolCallId, cmd.action, cmd.reason)
            d.log(res.ok ? `ctl: ${cmd.action} ${cmd.toolCallId} settled via mesh (by ${letter.from})` : `ctl: settle ${cmd.toolCallId} failed HTTP ${res.status} (already settled or expired?)`)
          }
        }
      }
    },
    async run(): Promise<void> {
      let failures = 0
      for (;;) {
        try { await this.tick(); failures = 0 } catch (e) {
          failures++
          d.log(`tick failed (${failures} in a row): ${(e as Error).message}`)
        }
        await d.sleep(failures ? Math.min(o.pollMs * 2 ** failures, 60_000) : o.pollMs)
      }
    },
    async shutdown(): Promise<void> { await stopBridge() },
  }
}

/** Scan MESH_HOME/hooks/*.sock and whoami each live peer. Skips wake's own bridge socket. */
export async function discoverBossaiSockets(dir: string = meshDir()): Promise<{ path: string; name?: string; mode?: 'pull' | 'push' | 'send' }[]> {
  const hooks = join(dir, 'hooks')
  if (!existsSync(hooks)) return []
  const own = hookSocketPath(process.pid, dir)
  const out: { path: string; name?: string; mode?: 'pull' | 'push' | 'send' }[] = []
  for (const f of readdirSync(hooks)) {
    if (!f.endsWith('.sock')) continue
    const path = join(hooks, f)
    if (path === own) continue
    const r = await askHookSocket(path, { op: 'whoami' }, 800)
    if (r?.name) out.push({ path, name: r.name, ...(r.mode ? { mode: r.mode } : {}) })
  }
  return out
}

/**
 * The idle-session bridge: a mesh-peer child speaking MCP stdio, registered under the same
 * session name. Its hook socket is keyed by this process's pid (the peer's ppid). Stopping
 * closes the MCP transport, which kills the child and frees the session for BossAI's own peer.
 */
/**
 * Bridge peer env. A distinct MESH_HOME moves the peer's hook socket out of the default
 * hooks dir: two peers under the same wake pid would otherwise fight over one socket path
 * (the ctl peer must not steal the main bridge's socket).
 */
export function bridgeEnv(o: { session: string; meshHome?: string }): Record<string, string> {
  const env: Record<string, string> = { MESH_JOIN: 'pull', MESH_HOST: 'bossai', MESH_SESSION_NAME: o.session, MESH_WAKE: '' }
  if (o.meshHome) env.MESH_HOME = o.meshHome
  return env
}

/** The ctl peer gets its own MESH_HOME; wake seeds it with the device pairing (same machine). */
export function ensureCtlHome(mainDir: string = meshDir()): string {
  const ctlDir = `${mainDir}-ctl`
  mkdirSync(ctlDir, { recursive: true, mode: 0o700 })
  for (const f of ['config.json', 'token']) {
    const src = join(mainDir, f)
    const dst = join(ctlDir, f)
    if (existsSync(src) && !existsSync(dst)) {
      copyFileSync(src, dst)
      chmodSync(dst, 0o600)
    }
  }
  return ctlDir
}

export async function startMcpBridge(o: { node: string; peer: string; session: string; meshHome?: string }): Promise<BridgeHandle> {
  const { Client } = await import('@modelcontextprotocol/sdk/client/index.js')
  const { StdioClientTransport, getDefaultEnvironment } = await import('@modelcontextprotocol/sdk/client/stdio.js')
  const transport = new StdioClientTransport({
    command: o.node,
    args: [o.peer],
    env: { ...getDefaultEnvironment(), ...bridgeEnv(o) },
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
  if (!env.BOSSAI_CLOUD_TOKEN && tokenFile && process.platform !== 'win32' && (statSync(tokenFile).mode & 0o077) !== 0) {
    throw new Error(`--token-file ${tokenFile} is readable by group or others; chmod 600 it, or better inject BOSSAI_CLOUD_TOKEN from the secret store.`)
  }
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
    server: assertLoopbackServer(resolveBossaiServer({ server: flag(args, '--server'), portFile: flag(args, '--port-file') })),
    token,
    license,
    notify: flag(args, '--notify'),
    account: (() => { try { return loadConfig().self_handle } catch { return undefined } })(),
    pollMs: Number.isFinite(pollMs) && pollMs >= 500 ? pollMs : 3_000,
    bridge: args.includes('--bridge'),
    allow: allowRaw ? allowRaw.split(',').map(s => s.trim()).filter(Boolean) : undefined,
    approvers: (() => { const a = flag(args, '--approvers'); return a ? parseApprovers(a) : undefined })(),
    graceMs: Number.isFinite(graceMs) && graceMs >= 0 ? graceMs : 15_000,
    runMode: (() => {
      const m = flag(args, '--run-mode')
      if (m === undefined) return undefined
      if (m !== 'cloud' && m !== 'hybrid' && m !== 'local') throw new Error('--run-mode must be cloud, hybrid or local')
      return m
    })(),
    model: flag(args, '--model'),
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
    startCtl: o.approvers?.length && o.session
      ? async () => {
        const home = ensureCtlHome()
        const h = await startMcpBridge({
          node: stableNode(process.env.PATH, process.execPath),
          peer: fileURLToPath(new URL('./mesh-peer.mjs', import.meta.url)),
          session: `${o.session}-ctl`,
          meshHome: home,
        })
        // Report idle so the relay card shows a live status, not "unknown".
        void askHookSocket(join(home, 'hooks', `${process.pid}.sock`), { op: 'idle' })
        return { read: h.read }
      }
      : undefined,
    resolveAsk: async (toolCallId, action, reason) => {
      const res = await fetchImpl(api(`/sessions/${o.chat}/permission-ask`), {
        method: 'POST',
        headers: auth,
        body: JSON.stringify({ toolCallId, action, scope: 'once', ...(reason ? { reason } : {}) }),
        signal: AbortSignal.timeout(8_000),
      })
      return { ok: res.ok, status: res.status }
    },
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