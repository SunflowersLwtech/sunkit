import { askHookSocket, hookSocketPath, type HookReply, type HookRequest } from './hook-socket.ts'
import { PULL_INSTRUCTIONS } from './instructions.ts'

/**
 * The mesh as a pi (pi-coding-agent) extension. pi has MCP built in but no channels, so the
 * peer runs in pull mode as an MCP server this extension registers, and pi's lifecycle events
 * play the part of agy's and Grok Build's hooks: they report busy/idle through the peer's hook
 * socket, add a notice to a tool result when mail arrives, keep a turn that ended on its own
 * going once per new arrival, and (MESH_WAKE set) start a turn when mail reaches an idle
 * session. The extension runs inside the pi process and pi spawns the server as its child, so
 * both sides find the socket by pi's pid. Only the shapes of pi's API this file uses are
 * declared here; pi is not a dependency.
 */

type Content = { type: string; text?: string }
interface Ctx { mode?: string; isIdle?: () => boolean }
interface ToolResultEvent { content: Content[]; structuredContent?: unknown }
interface SettleEvent { entries: unknown[]; outcome?: string; context?: { canContinue?: boolean } }
interface StartEvent { systemPromptOptions?: { sections?: Record<string, string> } }
export interface PiApi {
  on(event: string, handler: (event: any, ctx: Ctx) => unknown): unknown
  registerMcpServer(name: string, config: Record<string, unknown>): void
  sendUserMessage(content: string, options?: { deliverAs?: 'steer' | 'followUp' }): void
  getSessionName?(): string | undefined
}

export interface MeshPiOptions {
  /** Absolute path of the node binary that runs the peer. */
  node: string
  /** Absolute path of the bundled peer, mesh-peer.mjs. */
  peer: string
  /** MCP server name; the tools are mcp__<name>__list_agents and so on. */
  name?: string
  env?: NodeJS.ProcessEnv
  /** Talks to the peer's hook socket; tests replace it. */
  ask?: (req: HookRequest) => Promise<HookReply | undefined>
  /** How often an idle session checks for mail when waking is on. */
  pollMs?: number
}

export const PI_TOOLS = (name = 'mesh') => ['list_agents', 'send_message', 'read_messages'].map(t => `mcp__${name}__${t}`)

/** System prompt section: the peer's own instructions (pi does not show MCP server instructions for direct tools). */
export function piInstructions(name = 'mesh'): string {
  return `The mesh tools here are ${PI_TOOLS(name).join(', ')}; where the text below says list_agents, send_message or read_messages it means these.\n\n${PULL_INSTRUCTIONS}`
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)
const readTool = (name: string) => `mcp__${name}__read_messages`

export function toolNotice(r: HookReply, name = 'mesh'): string {
  const n = r.unread
  return `[mesh] ${n} unread ${plural(n, 'message', 'messages')} from ${r.from.join(', ')} ${plural(n, 'is', 'are')} waiting. Call ${readTool(name)} to read ${plural(n, 'it', 'them')}.`
}
export function stopNotice(r: HookReply, name = 'mesh'): string {
  const n = r.unread
  return `[mesh] ${n} ${plural(n, 'message', 'messages')} from ${r.from.join(', ')} arrived and ${plural(n, 'is', 'are')} still unread. Call ${readTool(name)} and deal with ${plural(n, 'it', 'them')} before you finish.`
}
export function wakeNotice(r: HookReply, name = 'mesh'): string {
  const n = r.unread
  return `[mesh] ${n} new ${plural(n, 'message', 'messages')} from ${r.from.join(', ')}. Call ${readTool(name)} to read ${plural(n, 'it', 'them')}.`
}

/**
 * Interactive and RPC sessions join (pull); print and JSON runs answer one prompt and exit, so
 * they only send, as `agy -p` does. MESH_JOIN=never (worker --no-mesh) keeps any session out.
 */
export function joinsMesh(mode: string | undefined, env: NodeJS.ProcessEnv): boolean {
  if (env.MESH_JOIN === 'never') return false
  return mode === 'tui' || mode === 'rpc'
}

/**
 * The MCP server entry. pi starts it with its own environment plus this env, so the session
 * name and Herdr's variables reach the peer. MESH_WAKE is cleared for the peer: this extension
 * starts the turn itself, and the peer's Herdr waker would type the same prompt into the pane.
 */
export function serverConfig(o: { node: string; peer: string; pull: boolean; sessionName?: string | undefined }): Record<string, unknown> {
  const env: Record<string, string> = { MESH_JOIN: o.pull ? 'pull' : 'never', MESH_HOST: 'pi', MESH_WAKE: '' }
  if (o.sessionName) env.MESH_SESSION_NAME = o.sessionName
  return {
    command: o.node,
    args: [o.peer],
    env,
    exposure: 'direct',
    description: 'Messages with Claude Code sessions and other agents on the mesh: list_agents, send_message, read_messages.',
  }
}

export function createMeshExtension(o: MeshPiOptions): (pi: PiApi) => void {
  return function mesh(pi: PiApi): void {
    const env = o.env ?? process.env
    const name = o.name ?? 'mesh'
    const ask = o.ask ?? ((req: HookRequest) => askHookSocket(hookSocketPath(process.pid), req))
    let pull = false
    let busy = false
    let ctx: Ctx | undefined
    let timer: ReturnType<typeof setInterval> | undefined
    let waking = false

    // The peer opens its socket a moment after pi connects to it: report idle once it answers.
    const reportIdle = async () => {
      for (let i = 0; i < 20 && pull && !busy; i++) {
        if (await ask({ op: 'idle' })) return
        await new Promise(r => setTimeout(r, 500))
      }
    }
    const pollWake = async () => {
      if (!pull || busy || waking || (ctx?.isIdle && !ctx.isIdle())) return
      waking = true
      try {
        const r = await ask({ op: 'wake' })
        if (r?.continue && r.unread > 0 && !busy && (!ctx?.isIdle || ctx.isIdle())) pi.sendUserMessage(wakeNotice(r, name))
      } finally { waking = false }
    }

    pi.on('session_start', (_e, c) => {
      ctx = c
      pull = joinsMesh(c?.mode, env)
      const sessionName = env.MESH_SESSION_NAME?.trim() || pi.getSessionName?.()?.trim() || undefined
      pi.registerMcpServer(name, serverConfig({ node: o.node, peer: o.peer, pull, sessionName }))
      if (!pull) return
      void reportIdle()
      if (env.MESH_WAKE && env.MESH_WAKE !== '0' && !timer) {
        timer = setInterval(() => { void pollWake() }, o.pollMs ?? 3_000)
        timer.unref?.()
      }
    })
    pi.on('before_agent_start', (e: StartEvent, c) => {
      ctx = c ?? ctx
      if (!pull || !e.systemPromptOptions) return
      e.systemPromptOptions.sections = { ...(e.systemPromptOptions.sections ?? {}), mesh: piInstructions(name) }
    })
    pi.on('agent_start', (_e, c) => {
      ctx = c ?? ctx
      if (!pull) return
      busy = true
      void ask({ op: 'turn' })
    })
    pi.on('tool_result', async (e: ToolResultEvent) => {
      if (!pull) return undefined
      const r = await ask({ op: 'tool' })
      if (!r?.notify || r.unread <= 0) return undefined
      return {
        content: [...e.content, { type: 'text', text: toolNotice(r, name) }],
        ...(e.structuredContent !== undefined ? { structuredContent: e.structuredContent } : {}),
      }
    })
    // The last point where a run can be kept going: only a run that completed on its own,
    // never one the user aborted or that failed.
    pi.on('agent_before_settle', async (e: SettleEvent) => {
      if (!pull) return undefined
      const r = await ask({ op: 'stop', natural: e.outcome === 'completed' })
      if (!r?.continue || e.context?.canContinue === false) return undefined
      return { entries: [...e.entries, { type: 'custom_message', customType: 'mesh', content: stopNotice(r, name), display: true }], continue: true }
    })
    pi.on('agent_settled', () => {
      if (!pull) return
      busy = false
      void ask({ op: 'idle' })
    })
    pi.on('session_shutdown', () => {
      if (timer) clearInterval(timer)
      timer = undefined
    })
  }
}
