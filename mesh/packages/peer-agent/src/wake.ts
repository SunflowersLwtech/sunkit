import { spawn } from 'node:child_process'

/**
 * Opt-in (MESH_WAKE=herdr): when a message reaches a pull host that its hooks last reported
 * idle, type a short prompt into its Herdr pane so it reads the message now instead of at the
 * user's next prompt. The prompt names the sender, never the message: the content still
 * arrives through read_messages, as peer input. Off by default because it types into a pane a
 * person may be using.
 */
export class IdleWaker {
  private last = Number.NEGATIVE_INFINITY

  constructor(private readonly opts: { send: (text: string) => void; minIntervalMs?: number; now?: () => number }) {}

  maybeWake(status: string | undefined, waiting: { size: number; from: string[] }): boolean {
    if (status !== 'idle' || waiting.size <= 0) return false
    const now = (this.opts.now ?? Date.now)()
    if (now - this.last < (this.opts.minIntervalMs ?? 20_000)) return false
    this.last = now
    const n = waiting.size
    this.opts.send(`[mesh] ${n} new ${n === 1 ? 'message' : 'messages'} from ${waiting.from.join(', ')}. Call the mesh read_messages tool to read ${n === 1 ? 'it' : 'them'}.`)
    return true
  }
}

/** The Herdr waker for this process's pane, or undefined unless MESH_WAKE=herdr inside Herdr. */
export function herdrWaker(env: NodeJS.ProcessEnv = process.env, start: (file: string, args: string[]) => void = startDetached): IdleWaker | undefined {
  if (env.MESH_WAKE !== 'herdr' || env.HERDR_ENV !== '1' || !env.HERDR_PANE_ID) return undefined
  const bin = env.HERDR_BIN_PATH || 'herdr'
  const pane = env.HERDR_PANE_ID
  return new IdleWaker({ send: text => start(bin, ['agent', 'prompt', pane, text]) })
}

function startDetached(file: string, args: string[]): void {
  try {
    const child = spawn(file, args, { stdio: 'ignore', detached: true })
    child.on('error', () => { /* no herdr: nothing to wake */ })
    child.unref()
  } catch { /* nothing to wake */ }
}
