import type { Readable } from 'node:stream'

/**
 * Calls `onGone` once when the MCP host closes our stdin, which is what happens when
 * the host exits or drops this server. Claude Code also signals its servers on exit, but
 * other hosts (Devin CLI, including `devin mcp list`) only close the pipe; the relay
 * stream would then keep the peer running, and its session listed, indefinitely.
 */
export function onHostClosed(stdin: Readable, onGone: (reason: 'stdin_end' | 'stdin_close') => void): void {
  let done = false
  const fire = (reason: 'stdin_end' | 'stdin_close') => {
    if (done) return
    done = true
    onGone(reason)
  }
  stdin.once('end', () => fire('stdin_end'))
  stdin.once('close', () => fire('stdin_close'))
}
