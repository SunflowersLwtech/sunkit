import { createServer, connect, type Server } from 'node:net'
import { chmodSync, mkdirSync, rmSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { meshDir } from './paths.ts'
import type { Inbox } from './inbox.ts'

/**
 * A local socket through which the host's lifecycle hooks talk to its pull-mode peer.
 * Hosts such as Antigravity CLI run hook commands and MCP servers as children of the same
 * process, so both sides find the socket by that process's pid (Grok Build too). The hooks
 * learn whether messages are waiting (and tell the agent to read them); the peer learns busy/idle.
 */
export type HookRequest =
  | { op: 'turn' }
  | { op: 'tool' }
  | { op: 'idle' }
  /** natural: the turn ended on its own; absent, agy's NO_TOOL_CALL reason means that. */
  | { op: 'stop'; reason?: string; natural?: boolean }
export interface HookReply { unread: number; from: string[]; continue?: boolean; notify?: boolean }

export function hookSocketPath(hostPid: number, dir: string = meshDir()): string {
  if (process.platform === 'win32') {
    // Named pipes live in one global namespace: tell mesh identities (MESH_HOME) apart.
    const tag = createHash('sha256').update(dir).digest('hex').slice(0, 8)
    return `\\\\.\\pipe\\claude-mesh-hook-${tag}-${hostPid}`
  }
  return join(dir, 'hooks', `${hostPid}.sock`)
}

export class HookChannel {
  private nudgedSeq = 0
  private notifiedSeq = 0

  constructor(private readonly inbox: Inbox, private readonly onStatus: (s: 'busy' | 'idle') => void) {}

  handle(req: HookRequest): HookReply {
    const p = this.inbox.peek()
    const base = { unread: p.size, from: p.from }
    if (req.op === 'turn') {
      this.onStatus('busy')
      return base
    }
    if (req.op === 'tool') {
      // Hosts that keep what a hook adds to a tool result (Grok Build) are told once per new
      // arrival; a notice on every tool call would pile up in the conversation.
      this.onStatus('busy')
      const notify = p.size > 0 && p.seq > this.notifiedSeq
      if (notify) this.notifiedSeq = p.seq
      return { ...base, notify }
    }
    if (req.op === 'idle') {
      this.onStatus('idle')
      return base
    }
    if (req.op === 'stop') {
      // Keep going once per new arrival, and only after a turn that ended on its own:
      // never against the user's Esc, an error, or an invocation limit.
      const natural = req.natural ?? req.reason === 'NO_TOOL_CALL'
      if (p.size > 0 && p.seq > this.nudgedSeq && natural) {
        this.nudgedSeq = p.seq
        return { ...base, continue: true }
      }
      this.onStatus('idle')
      return { ...base, continue: false }
    }
    return base
  }
}

export async function serveHookSocket(path: string, channel: HookChannel): Promise<Server> {
  if (process.platform !== 'win32') {
    const dir = join(path, '..')
    mkdirSync(dir, { recursive: true, mode: 0o700 })
    chmodSync(dir, 0o700)
    // Left by a crashed peer, or a peer of an earlier process with the same pid.
    rmSync(path, { force: true })
  }
  const server = createServer(sock => {
    let buf = ''
    sock.setEncoding('utf8')
    sock.setTimeout(2_000, () => sock.destroy())
    sock.on('error', () => { /* the hook went away */ })
    sock.on('data', chunk => {
      buf += chunk
      if (buf.length > 4_096) { sock.destroy(); return }
      const i = buf.indexOf('\n')
      if (i < 0) return
      let reply: HookReply
      try { reply = channel.handle(JSON.parse(buf.slice(0, i)) as HookRequest) } catch { sock.destroy(); return }
      sock.end(JSON.stringify(reply) + '\n')
    })
  })
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject)
    server.listen(path, () => { server.off('error', reject); resolve() })
  })
  if (process.platform !== 'win32') chmodSync(path, 0o600)
  return server
}

/** One request to the peer behind `path`; undefined when nobody answers in time. */
export function askHookSocket(path: string, req: HookRequest, timeoutMs = 1_500): Promise<HookReply | undefined> {
  return new Promise(resolve => {
    let buf = ''
    let done = false
    const finish = (v: HookReply | undefined) => { if (!done) { done = true; sock.destroy(); resolve(v) } }
    const sock = connect(path)
    sock.setEncoding('utf8')
    sock.setTimeout(timeoutMs, () => finish(undefined))
    sock.on('error', () => finish(undefined))
    sock.on('connect', () => sock.write(JSON.stringify(req) + '\n'))
    sock.on('data', chunk => {
      buf += chunk
      const i = buf.indexOf('\n')
      if (i < 0) return
      try { finish(JSON.parse(buf.slice(0, i)) as HookReply) } catch { finish(undefined) }
    })
    sock.on('end', () => finish(undefined))
  })
}
