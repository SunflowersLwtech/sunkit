import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { askHookSocket, hookSocketPath, type HookReply, type HookRequest } from '../hook-socket.ts'
import { parentPid } from '../join-policy.ts'
import { meshDir } from '../paths.ts'

/**
 * Up to `depth` ancestors of `pid`, nearest first. On Windows one PowerShell call for the whole
 * chain: each call takes about a second and a half, and Devin's Git Bash puts two shells between
 * a hook and the agent.
 */
export function ancestors(pid: number, depth: number, parentOf: (pid: number) => number | undefined = parentPid): number[] {
  if (process.platform === 'win32' && parentOf === parentPid) {
    try {
      const out = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
        `$p=${pid}; for($i=0;$i -lt ${depth};$i++){ $x=Get-CimInstance Win32_Process -Filter "ProcessId=$p"; if(-not $x){break}; $x.ParentProcessId; $p=$x.ParentProcessId }`,
      ], { encoding: 'utf8', timeout: 10_000, windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] })
      return out.split(/\s+/).map(Number).filter(n => n > 0)
    } catch {
      return []
    }
  }
  const out: number[] = []
  for (let p: number | undefined = pid; out.length < depth;) {
    p = parentOf(p)
    if (!p || p === 1) break
    out.push(p)
  }
  return out
}

export interface AskOpts {
  /** Remember which process answered under this key (a host's session id), so later hooks of that session skip the search. */
  cacheKey?: string | undefined
  /** Keep trying this long for a peer that is still starting. */
  waitMs?: number
}

const KEY = /^[A-Za-z0-9_-]{1,80}$/

function cachePath(key: string | undefined): string | undefined {
  return key && KEY.test(key) ? join(meshDir(), 'hooks', `${key}.pid`) : undefined
}

/** Forget the process remembered for a session (its end). */
export function forgetHostPeer(cacheKey: string | undefined): void {
  const path = cachePath(cacheKey)
  if (path) rmSync(path, { force: true })
}

async function askPid(pid: number, req: HookRequest): Promise<HookReply | undefined> {
  const path = hookSocketPath(pid)
  if (process.platform !== 'win32' && !existsSync(path)) return undefined
  return askHookSocket(path, req)
}

/**
 * Ask the pull-mode peer of the host that ran this hook. Hosts run hook commands and MCP servers
 * as children of the same process (agy, Grok Build; for Devin CLI that is its agent, `devin acp`).
 * A hook command run through `sh -c` usually replaces the shell, so the host is our parent; if the
 * shell stayed around it is our grandparent, and under Devin's Git Bash on Windows the
 * great-grandparent. Undefined when no peer answers.
 */
export async function askHostPeer(req: HookRequest, ppid: number = process.ppid, opts: AskOpts = {}): Promise<HookReply | undefined> {
  const cache = cachePath(opts.cacheKey)
  let cached: number | undefined
  if (cache) { try { cached = Number(readFileSync(cache, 'utf8').trim()) || undefined } catch { /* none yet */ } }
  const remember = (pid: number) => {
    if (!cache || pid === cached) return
    try { mkdirSync(join(cache, '..'), { recursive: true, mode: 0o700 }); writeFileSync(cache, String(pid), { mode: 0o600 }) } catch { /* only a shortcut */ }
  }
  const deadline = Date.now() + (opts.waitMs ?? 0)
  // The parent's ancestors are looked up only when nearer candidates do not answer, and only once.
  let chain: number[] | undefined
  for (;;) {
    for (const pid of [cached, ppid]) {
      const reply = pid ? await askPid(pid, req) : undefined
      if (reply) { remember(pid!); return reply }
    }
    for (const pid of (chain ??= ancestors(ppid, 2))) {
      const reply = await askPid(pid, req)
      if (reply) { remember(pid); return reply }
    }
    if (Date.now() >= deadline) return undefined
    await new Promise(r => setTimeout(r, 200))
  }
}

export function readStdin(): Promise<string> {
  return new Promise(resolve => {
    if (process.stdin.isTTY) { resolve(''); return }
    let buf = ''
    const timer = setTimeout(() => resolve(buf), 2_000)
    process.stdin.setEncoding('utf8')
    process.stdin.on('data', d => { buf += d; if (buf.length > 1_000_000) { clearTimeout(timer); resolve(buf) } })
    process.stdin.on('end', () => { clearTimeout(timer); resolve(buf) })
    process.stdin.on('error', () => { clearTimeout(timer); resolve(buf) })
  })
}
