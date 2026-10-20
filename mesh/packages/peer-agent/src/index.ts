#!/usr/bin/env node
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocol/sdk/types.js'
import { createMcpServer } from './mcp-server.ts'
import { loadConfig, loadToken, assertTokenNotInRepo, defaultConfigPath } from './config.ts'
import { existsSync, realpathSync, rmSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { CardPatchSchema } from '@claude-mesh/shared'
import { CardWriter, initialCard, type CardFields } from './card.ts'
import { TaskDriver } from './task-driver.ts'
import { RelayClient } from './outbound.ts'
import { registerTools, TOOL_DESCRIPTORS, PULL_TOOL_DESCRIPTORS } from './tools.ts'
import { chooseJoinMode, Inbox } from './inbox.ts'
import { SenderGate } from './gate.ts'
import { InboundDispatcher } from './inbound.ts'
import { StreamClient } from './stream.ts'
import { ReplyLimiter } from './reply-limiter.ts'
import { mintSessionId, probeClaudeSession, probeHostSession, readClaudeLogin, type SessionSnapshot } from './session-identity.ts'
import { decideJoin, hostCommandLine, isOneShotHostRun, parentCommandLine } from './join-policy.ts'
import { onHostClosed } from './host-lifetime.ts'
import { HookChannel, hookSocketPath, serveHookSocket } from './hook-socket.ts'
import { herdrWaker } from './wake.ts'
import { WakeBudget } from './wake-budget.ts'
import { meshDir } from './paths.ts'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { logJson } from './logger.ts'

const IDENTITY_POLL_MS = 3_000

async function main(): Promise<void> {
  // The host closing stdin means it is gone; without this the relay stream keeps the
  // peer alive and listed after a host that does not signal its servers (Devin CLI) exits.
  onHostClosed(process.stdin, reason => {
    logJson('info', 'peer.host_closed', { reason })
    process.exit(0)
  })
  // Installed as a plugin on a machine that was never paired: stay a silent,
  // tool-less server instead of failing (a failed server is noise in /mcp).
  if (!existsSync(defaultConfigPath())) {
    const { server } = createMcpServer({ permissionRelay: false })
    server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [] }))
    logJson('info', 'peer.unpaired', { config: defaultConfigPath() })
    await server.connect(new StdioServerTransport())
    return
  }
  const cfg = loadConfig()
  assertTokenNotInRepo(cfg.token_path)
  const token = loadToken(cfg.token_path)

  const cwd = process.cwd()
  // A pull host is not Claude Code: its name never comes from Claude's session registry.
  const pullHost = process.env.MESH_JOIN === 'pull'
  let identity: SessionSnapshot = pullHost ? probeHostSession({ cwd }) : probeClaudeSession({ cwd })
  // Only sessions that will actually receive messages register as reachable: pushed
  // through a Claude Code channel, or (MESH_JOIN=pull) held for read_messages.
  const decision = chooseJoinMode(process.env.MESH_JOIN, () => decideJoin({
    env: process.env.MESH_JOIN,
    commandLine: parentCommandLine(),
    sessionKind: identity.kind,
  }), () => isOneShotHostRun(hostCommandLine()))
  const pull = decision.mode === 'pull'
  const joins = decision.mode !== 'send'
  // The login shown in list_agents is the machine's Claude login; a pull host is not Claude.
  const readLogin = () => (pullHost ? undefined : readClaudeLogin())
  let login = readLogin()

  // Permission relay is deliberately never offered: under bypass-permissions it
  // would only add a path for a peer to answer prompts on this machine.
  const { server } = createMcpServer({ permissionRelay: false, pull })

  const sessionId = joins ? mintSessionId() : ''
  // A send-only peer with a name set (MESH_SESSION_NAME) still signs its messages with it.
  const senderName = !joins && process.env.MESH_SESSION_NAME?.trim() ? identity.name : undefined
  const client = new RelayClient({
    relayUrl: cfg.relay_url, token,
    ...(joins ? { sessionId } : {}),
    ...(senderName ? { senderName } : {}),
  })

  const inbox = pull ? new Inbox() : undefined
  const replyLimiter = new ReplyLimiter({ windowMs: 10_000, maxReplies: 2 })
  const { callTool } = registerTools(client, { selfSessionId: sessionId, replyLimiter, inbox })

  // Static tool list: never changes for the life of the process, so it never
  // invalidates the session's prompt cache.
  const tools = pull ? PULL_TOOL_DESCRIPTORS : TOOL_DESCRIPTORS
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [...tools] }))
  server.setRequestHandler(CallToolRequestSchema, async req => {
    try { return await callTool(req.params.name, req.params.arguments ?? {}) }
    catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      return { content: [{ type: 'text', text: `error: ${message}` }], isError: true }
    }
  })

  server.onerror = err => { logJson('error', 'peer.mcp.error', describeError(err)) }

  logJson('info', 'peer.startup', {
    relay_url: cfg.relay_url, session: sessionId, name: identity.name, join: joins, mode: decision.mode, reason: decision.reason,
  })
  await server.connect(new StdioServerTransport())
  // Send-only: tools work, but this session is not listed and receives nothing.
  if (!joins) return

  // Seed the roster. A relay outage at startup must not break the Claude Code
  // session: start empty and let the refresh loop recover.
  const gate = new SenderGate([])
  const refreshRoster = async () => {
    try {
      const peers = await client.listPeers()
      gate.setRoster(peers.map(p => p.handle))
    } catch (err) {
      logJson('warn', 'peer.roster.refresh_error', describeError(err))
    }
  }
  void refreshRoster()
  setInterval(refreshRoster, 60_000).unref()

  // The session's card (what it is, where, on what) and its relay task (MESH_TASK_ID). The peer is
  // their only writer here; the host's hooks tell it what changed. MESH_CARD_WRITE=0 turns both off.
  const cardOn = process.env.MESH_CARD_WRITE !== '0'
  const machine = cfg.machine ?? (process.env.MESH_MACHINE?.trim() || undefined)
  const git = (args: string[]) => {
    try { return execFileSync('git', args, { cwd, encoding: 'utf8', timeout: 2_000, stdio: ['ignore', 'pipe', 'ignore'] }) } catch { return undefined }
  }
  const card0 = initialCard({ env: process.env, host: pullHost ? (process.env.MESH_HOST ?? '') : undefined, machine, git })
  const cards = new CardWriter(card => client.writeCard(card), { enabled: cardOn })
  cards.set({ ...card0, source: pullHost ? 'hook' : 'poll' })
  const tasks = cardOn && card0.task_id
    ? new TaskDriver({ get: id => client.getTask(id), patch: (id, b) => client.patchTask(id, b), rebind: id => client.rebindTask(id) },
      card0.task_id, sessionId, (event, fields) => logJson('info', event, fields))
    : undefined
  // Once Claude Code's hooks report (the mesh plugin's hooks.json), they own busy/idle and the
  // status poll below stops writing it; the poll keeps following the name and the login.
  let hooksActive = false

  // Follow Claude Code's own name/status for this session (read-only). A pull host keeps the
  // name it started with.
  if (!pull) setInterval(() => {
    const next = probeClaudeSession({ cwd })
    const nextLogin = readLogin()
    const status = hooksActive ? identity.status : next.status
    if (next.name === identity.name && status === identity.status && nextLogin === login) return
    const statusChanged = status !== identity.status
    identity = { ...next, status }
    login = nextLogin
    client.updateSelf({ name: next.name, ...(statusChanged ? { status } : {}), ...(nextLogin ? { login: nextLogin } : {}) })
      .catch(err => logJson('warn', 'peer.session.update_error', describeError(err)))
  }, IDENTITY_POLL_MS).unref()

  // Every joined session listens on a local socket for its host's lifecycle hooks: pull hosts
  // (agy, Grok Build, Devin CLI, pi) to see the inbox and report busy/idle, Claude Code (the
  // plugin's hooks) to report turns; all of them for the card and the task. MESH_WAKE=herdr also
  // prompts an idle pull host.
  // One wake budget per session, its ledger shared by every session on the machine: Herdr wakes
  // and turns a host starts by itself (pi) count against the same limits.
  const wakeBudget = new WakeBudget({ file: join(meshDir(), 'wakes.json') })
  const waker = inbox ? herdrWaker(process.env, undefined, wakeBudget) : undefined
  {
    const setStatus = (status: 'busy' | 'idle') => {
      if (identity.status === status) return
      identity = { ...identity, status }
      client.updateSelf({ status }).catch(err => logJson('warn', 'peer.session.update_error', describeError(err)))
    }
    const hookPath = hookSocketPath(process.ppid)
    const channel = new HookChannel(inbox ?? new Inbox(), setStatus, {
      onEvent: e => {
        if (!hooksActive && !pull) { hooksActive = true; cards.set({ source: 'hook' }) }
        void tasks?.on(e)
      },
      onCard: c => cards.set(cardFromHook(c)),
      whoami: () => ({ session: sessionId, name: identity.name }),
      wakeAllowed: () => wakeBudget.take(),
    })
    serveHookSocket(hookPath, channel)
      .then(server => {
        server.unref()
        if (process.platform !== 'win32') process.on('exit', () => { try { rmSync(hookPath, { force: true }) } catch { /* gone */ } })
        logJson('info', 'peer.hooks.listening', { path: hookPath, wake: !!waker })
      })
      .catch(err => logJson('warn', 'peer.hooks.listen_error', describeError(err)))
  }

  let cursor: string | undefined
  let taskStarted = false
  const dispatcher = new InboundDispatcher({
    gate,
    sessionId,
    chatOnly: true,
    // Pull mode keeps chat for read_messages; push mode hands it to Claude Code's channel.
    emit: n => {
      if (inbox) {
        if (n.method === 'notifications/claude/channel') {
          inbox.push(n.params as { content: string; meta: Record<string, string> })
          waker?.maybeWake(identity.status, inbox.peek())
        }
      }
      else void server.notification(n as never)
    },
    setCursor: id => { cursor = id },
    replyLimiter,
  })

  const stream = new StreamClient({
    relayUrl: cfg.relay_url,
    token,
    sinceCursor: () => cursor,
    sessionParams: () => ({ session: sessionId, name: identity.name, status: identity.status, cwd, ...(login ? { login } : {}), ...(pull ? { mode: 'pull' } : {}) }),
    onEnvelope: e => dispatcher.handle(e),
    // A host that reported busy/idle before the relay attached this session lost that update
    // (404): send what we have now if it differs from what the stream was opened with. The card
    // goes again in full (a restarted relay forgot it), and the first open starts the task driver.
    onOpen: sent => {
      cards.resend()
      if (!taskStarted) { taskStarted = true; void tasks?.start() }
      if (sent.status === identity.status) return
      client.updateSelf({ status: identity.status }).catch(err => logJson('warn', 'peer.session.update_error', describeError(err)))
    },
    onAuthError: () => { logJson('error', 'peer.auth_failed'); process.exit(2) },
  })
  stream.start().catch(err => {
    logJson('error', 'peer.stream.fatal', {
      err: String(err instanceof Error ? err.message : err),
    })
    process.exit(1)
  })
}

/** Fields a hook may set on the card (it knows the model; the peer knows the rest), each checked against the relay's schema. */
export function cardFromHook(c: Record<string, unknown>): CardFields {
  const out: Record<string, unknown> = {}
  for (const key of ['model', 'repo', 'branch'] as const) {
    if (c[key] === undefined) continue
    const r = CardPatchSchema.shape[key].safeParse(c[key])
    if (r.success) out[key] = r.data
  }
  return out as CardFields
}

function describeError(err: unknown): Record<string, string> {
  if (!(err instanceof Error)) return { err: String(err) }
  const out: Record<string, string> = { err: err.message, name: err.name }
  const anyErr = err as { code?: unknown; cause?: unknown }
  if (typeof anyErr.code === 'string') out.code = anyErr.code
  if (anyErr.cause instanceof Error) {
    out.cause_message = anyErr.cause.message
    out.cause_name = anyErr.cause.name
    const anyCause = anyErr.cause as { code?: unknown; address?: unknown; port?: unknown }
    if (typeof anyCause.code === 'string') out.cause_code = anyCause.code
    if (typeof anyCause.address === 'string') out.cause_address = anyCause.address
    if (typeof anyCause.port === 'number') out.cause_port = String(anyCause.port)
  } else if (anyErr.cause !== undefined) {
    out.cause = String(anyErr.cause)
  }
  return out
}

// Compare real paths: started through a symlink (macOS /var -> /private/var, a linked
// checkout), the two spellings differ and the server would exit without running.
function invokedAsScript(): boolean {
  if (!process.argv[1]) return false
  try { return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1]) } catch { return false }
}
if (invokedAsScript()) {
  main().catch(err => {
    logJson('error', 'peer.fatal', describeError(err))
    process.exit(1)
  })
}
