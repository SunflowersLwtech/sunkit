import { appendFileSync } from 'node:fs'
import { SESSION_ID_REGEX } from '@claude-mesh/shared'
import type { HookReply, HookRequest } from '../hook-socket.ts'
import { askHostPeer, forgetHostPeer, readStdin } from './host-hook.ts'

/**
 * `mesh claude hook <event>`, run by the mesh plugin's hooks (plugins/mesh/hooks/hooks.json):
 * tells this session's peer that a turn started, that Claude Code waits for a person, that the
 * turn ended, or that the session ends; at session start it passes the model on and exports
 * MESH_SESSION_ID for the commands Claude runs. Claude Code adds a hook's stdout to the context
 * on SessionStart and UserPromptSubmit, so this prints nothing, ever, and always exits 0: a
 * session without a mesh peer must not notice it.
 */
export const CLAUDE_HOOK_EVENTS = ['session-start', 'turn', 'blocked', 'stop', 'end'] as const
type ClaudeHookEvent = typeof CLAUDE_HOOK_EVENTS[number]

interface Deps {
  stdin: () => Promise<string>
  ask: (req: HookRequest, opts: { cacheKey?: string | undefined; waitMs?: number }) => Promise<HookReply | undefined>
  forget: (cacheKey: string | undefined) => void
  env: NodeJS.ProcessEnv
}

const defaults: Deps = {
  stdin: readStdin,
  ask: (req, opts) => askHostPeer(req, process.ppid, opts),
  forget: forgetHostPeer,
  env: process.env,
}

/** The peer starts with the session; at session start give it a moment to open its socket. */
const START_WAIT_MS = 4_000

export async function runClaudeHook(args: string[], deps: Deps = defaults): Promise<number> {
  const event = args[0] as ClaudeHookEvent
  if (!(CLAUDE_HOOK_EVENTS as readonly string[]).includes(event)) return 0
  let input: { session_id?: unknown; model?: unknown } = {}
  try { input = JSON.parse(await deps.stdin()) as typeof input } catch { /* no input: still report the event */ }
  const cacheKey = typeof input.session_id === 'string' ? input.session_id : undefined
  try {
    if (event === 'session-start') {
      const card = typeof input.model === 'string' ? { model: input.model } : {}
      await deps.ask({ op: 'card', card }, { cacheKey, waitMs: START_WAIT_MS })
      const me = await deps.ask({ op: 'whoami' }, { cacheKey })
      const envFile = deps.env.CLAUDE_ENV_FILE
      if (envFile && me?.session && SESSION_ID_REGEX.test(me.session)) {
        appendFileSync(envFile, `export MESH_SESSION_ID=${me.session}\n`)
      }
      return 0
    }
    if (event === 'turn') await deps.ask({ op: 'turn' }, { cacheKey })
    if (event === 'blocked') await deps.ask({ op: 'blocked' }, { cacheKey })
    if (event === 'stop') await deps.ask({ op: 'stop', natural: true }, { cacheKey })
    if (event === 'end') {
      await deps.ask({ op: 'end' }, { cacheKey })
      deps.forget(cacheKey)
    }
  } catch {
    // Nothing a hook does may break the session.
  }
  return 0
}
