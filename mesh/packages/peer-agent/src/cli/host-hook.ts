import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { askHookSocket, hookSocketPath, type HookReply, type HookRequest } from '../hook-socket.ts'

function parentOf(pid: number): number | undefined {
  try {
    if (process.platform === 'linux') return Number(readFileSync(`/proc/${pid}/stat`, 'utf8').replace(/^.*\) /s, '').split(' ')[1]) || undefined
    if (process.platform === 'win32') return undefined
    return Number(execFileSync('ps', ['-o', 'ppid=', '-p', String(pid)], { encoding: 'utf8', timeout: 2_000 }).trim()) || undefined
  } catch {
    return undefined
  }
}

/**
 * Ask the pull-mode peer of the host that ran this hook. Hosts (agy, Grok Build) run hook
 * commands and MCP servers as children of the same process; a hook command run through
 * `sh -c` usually replaces the shell, so the host is our parent, and if the shell stayed
 * around it is our grandparent. Undefined when no peer answers.
 */
export async function askHostPeer(req: HookRequest, ppid: number = process.ppid): Promise<HookReply | undefined> {
  for (const pid of [ppid, parentOf(ppid)]) {
    if (!pid) continue
    const path = hookSocketPath(pid)
    if (process.platform !== 'win32' && !existsSync(path)) continue
    const reply = await askHookSocket(path, req)
    if (reply) return reply
  }
  return undefined
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
