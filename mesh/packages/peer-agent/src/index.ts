#!/usr/bin/env node
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocol/sdk/types.js'
import { createMcpServer } from './mcp-server.ts'
import { loadConfig, loadToken, assertTokenNotInRepo, defaultConfigPath } from './config.ts'
import { existsSync } from 'node:fs'
import { RelayClient } from './outbound.ts'
import { registerTools, TOOL_DESCRIPTORS } from './tools.ts'
import { SenderGate } from './gate.ts'
import { InboundDispatcher } from './inbound.ts'
import { StreamClient } from './stream.ts'
import { ReplyLimiter } from './reply-limiter.ts'
import { mintSessionId, probeClaudeSession, readClaudeLogin, type SessionSnapshot } from './session-identity.ts'
import { decideJoin, parentCommandLine } from './join-policy.ts'
import { pathToFileURL } from 'node:url'
import { logJson } from './logger.ts'

const IDENTITY_POLL_MS = 3_000

async function main(): Promise<void> {
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

  // Permission relay is deliberately never offered: under bypass-permissions it
  // would only add a path for a peer to answer prompts on this machine.
  const { server } = createMcpServer({ permissionRelay: false })

  const cwd = process.cwd()
  let identity: SessionSnapshot = probeClaudeSession({ cwd })
  let login = readClaudeLogin()
  // Only sessions that will actually receive pushes register as reachable.
  const decision = decideJoin({
    env: process.env.MESH_JOIN,
    commandLine: parentCommandLine(),
    sessionKind: identity.kind,
  })
  const sessionId = decision.join ? mintSessionId() : ''
  const client = new RelayClient({ relayUrl: cfg.relay_url, token, ...(decision.join ? { sessionId } : {}) })

  const replyLimiter = new ReplyLimiter({ windowMs: 10_000, maxReplies: 2 })
  const { callTool } = registerTools(client, { selfSessionId: sessionId, replyLimiter })

  // Static tool list: never changes for the life of the process, so it never
  // invalidates the session's prompt cache.
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [...TOOL_DESCRIPTORS] }))
  server.setRequestHandler(CallToolRequestSchema, async req => {
    try { return await callTool(req.params.name, req.params.arguments ?? {}) }
    catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      return { content: [{ type: 'text', text: `error: ${message}` }], isError: true }
    }
  })

  server.onerror = err => { logJson('error', 'peer.mcp.error', describeError(err)) }

  logJson('info', 'peer.startup', {
    relay_url: cfg.relay_url, session: sessionId, name: identity.name, join: decision.join, reason: decision.reason,
  })
  await server.connect(new StdioServerTransport())
  // Send-only: tools work, but this session is not listed and receives nothing.
  if (!decision.join) return

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

  // Follow Claude Code's own name/status for this session (read-only).
  setInterval(() => {
    const next = probeClaudeSession({ cwd })
    const nextLogin = readClaudeLogin()
    if (next.name === identity.name && next.status === identity.status && nextLogin === login) return
    identity = next
    login = nextLogin
    client.updateSelf({ name: next.name, status: next.status, ...(nextLogin ? { login: nextLogin } : {}) })
      .catch(err => logJson('warn', 'peer.session.update_error', describeError(err)))
  }, IDENTITY_POLL_MS).unref()

  let cursor: string | undefined
  const dispatcher = new InboundDispatcher({
    gate,
    sessionId,
    chatOnly: true,
    emit: n => { void server.notification(n as never) },
    setCursor: id => { cursor = id },
    replyLimiter,
  })

  const stream = new StreamClient({
    relayUrl: cfg.relay_url,
    token,
    sinceCursor: () => cursor,
    sessionParams: () => ({ session: sessionId, name: identity.name, status: identity.status, cwd, ...(login ? { login } : {}) }),
    onEnvelope: e => dispatcher.handle(e),
    onAuthError: () => { logJson('error', 'peer.auth_failed'); process.exit(2) },
  })
  stream.start().catch(err => {
    logJson('error', 'peer.stream.fatal', {
      err: String(err instanceof Error ? err.message : err),
    })
    process.exit(1)
  })
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

const invokedAsScript = Boolean(process.argv[1]) && import.meta.url === pathToFileURL(process.argv[1]!).href
if (invokedAsScript) {
  main().catch(err => {
    logJson('error', 'peer.fatal', describeError(err))
    process.exit(1)
  })
}
