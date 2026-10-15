import { describe, it, expect, vi } from 'vitest'
import { parseSayArgs, sayWith, SAY_USAGE } from './say.ts'
import { devinAddArgs, parseDevinInstall, runDevin, shellQuote, stableNode } from './devin.ts'
import type { SessionRow } from '../resolve-target.ts'

const rows: SessionRow[] = [
  { session_id: 's_01hrk7y0000000000000aaaaaa', ref: 'aaaaaa', name: 'feishu-assistant', account: 'weiliu', device: 'n150', status: 'idle', last_seen: 'x' },
  { session_id: 's_01hrk7y0000000000000bbbbbb', ref: 'bbbbbb', name: 'dup', account: 'duocode', device: 'm4', status: 'idle', last_seen: 'x' },
  { session_id: 's_01hrk7y0000000000000cccccc', ref: 'cccccc', name: 'dup', account: 'duocode', device: 'mone', status: 'idle', last_seen: 'x' },
]

describe('mesh say: arguments', () => {
  it('takes the name from --as, else MESH_SESSION_NAME, and the rest of the line as the message', () => {
    expect(parseSayArgs(['--as', 'hipimind-devin', 'feishu-assistant', '[m4/x]', 'gates', 'green'], {}))
      .toEqual({ as: 'hipimind-devin', to: 'feishu-assistant', message: '[m4/x] gates green' })
    expect(parseSayArgs(['feishu-assistant', 'hi'], { MESH_SESSION_NAME: 'pi-devin' }).as).toBe('pi-devin')
    expect(parseSayArgs(['--as', 'a', 'feishu-assistant', 'hi'], { MESH_SESSION_NAME: 'b' }).as).toBe('a')
  })
  it('sanitizes the name the same way session names are', () => {
    expect(parseSayArgs(['--as', 'my devin [1]', 'x', 'hi'], {}).as).toBe('my-devin-1')
  })
  it('passes --reply-to through and reads the message from stdin for "-"', () => {
    expect(parseSayArgs(['--reply-to', 'msg_01HRK7Y000000000000000000A', '--as', 'a', 'x', '-'], {}, () => 'from stdin\n'))
      .toEqual({ as: 'a', to: 'x', message: 'from stdin\n', replyTo: 'msg_01HRK7Y000000000000000000A' })
  })
  it('refuses without a name, a recipient or a message', () => {
    expect(() => parseSayArgs(['x', 'hi'], {})).toThrow(SAY_USAGE)
    expect(() => parseSayArgs(['--as', 'a', 'x'], {})).toThrow(SAY_USAGE)
    expect(() => parseSayArgs(['--as', 'a'], {})).toThrow(SAY_USAGE)
  })
})

describe('mesh say: sending', () => {
  const client = (delivered = true) => {
    const send = vi.fn(async () => ({ id: 'msg_01HRK7Y000000000000000000B', delivered_at: delivered ? 'now' : null }))
    return { listSessions: vi.fn(async () => rows), send } as never as { listSessions: () => Promise<SessionRow[]>; send: typeof send }
  }
  it('addresses the resolved session and sets in_reply_to', async () => {
    const c = client()
    const out = await sayWith(c as never, { as: 'pi-devin', to: 'feishu-assistant', message: 'done', replyTo: 'msg_01HRK7Y000000000000000000A' })
    expect(c.send).toHaveBeenCalledWith({ to: 'weiliu', to_session: 's_01hrk7y0000000000000aaaaaa', kind: 'chat', content: 'done', meta: {}, in_reply_to: 'msg_01HRK7Y000000000000000000A' })
    expect(out).toBe('delivered to feishu-assistant [aaaaaa] as pi-devin (msg_01HRK7Y000000000000000000B)')
  })
  it('reports a session that is reconnecting, and refuses ambiguous or unknown names', async () => {
    expect(await sayWith(client(false) as never, { as: 'a', to: 'feishu-assistant', message: 'x' })).toMatch(/^queued/)
    await expect(sayWith(client() as never, { as: 'a', to: 'dup', message: 'x' })).rejects.toThrow(/matches 2 sessions/)
    await expect(sayWith(client() as never, { as: 'a', to: 'nobody', message: 'x' })).rejects.toThrow(/no live session named "nobody"/)
    await expect(sayWith(client() as never, { as: 'a', to: 'dup [cccccc]', message: 'x' })).resolves.toMatch(/dup \[cccccc\]/)
  })
})

describe('mesh devin install', () => {
  const defaults = { node: '/opt/node/bin/node', peer: '/Users/me/sunkit/mesh/plugins/mesh/server/mesh-peer.mjs' }
  it('builds a devin mcp add that runs the peer in pull mode with absolute paths', () => {
    expect(devinAddArgs(parseDevinInstall([], defaults))).toEqual([
      'mcp', 'add', '-s', 'user', 'mesh', '-e', 'MESH_JOIN=pull', '--', '/opt/node/bin/node', '/Users/me/sunkit/mesh/plugins/mesh/server/mesh-peer.mjs',
    ])
    expect(parseDevinInstall(['--scope', 'local', '--name', 'mesh2', '--peer', '/p.mjs'], defaults)).toEqual({ ...defaults, peer: '/p.mjs', scope: 'local', name: 'mesh2' })
    expect(() => parseDevinInstall(['--scope', 'global'], defaults)).toThrow(/usage/)
  })
  it('only prints by default; --write runs devin with exactly that argv', () => {
    const lines: string[] = []
    const run = vi.fn()
    expect(runDevin(['install'], { log: l => lines.push(l), run })).toBe(0)
    expect(run).not.toHaveBeenCalled()
    expect(lines[0]).toMatch(/^devin mcp add -s user mesh -e MESH_JOIN=pull -- \S+ \S+mesh-peer\.mjs$/)
    runDevin(['install', '--write'], { log: () => {}, run })
    expect(run).toHaveBeenCalledWith('devin', expect.arrayContaining(['mcp', 'add', '-e', 'MESH_JOIN=pull']))
    expect(runDevin(['bogus'], { log: () => {} })).toBe(2)
  })
  it('uses the node on PATH (a link that survives upgrades), skipping fnm per-shell dirs; --node overrides', () => {
    const exists = (p: string) => ['/x/fnm_multishells/123_456/bin/node', '/opt/homebrew/bin/node', '/usr/bin/node'].includes(p)
    expect(stableNode('/x/fnm_multishells/123_456/bin:/opt/homebrew/bin:/usr/bin', '/opt/homebrew/Cellar/node/26.0.0/bin/node', exists)).toBe('/opt/homebrew/bin/node')
    expect(stableNode('/nowhere', '/fallback/node', exists)).toBe('/fallback/node')
    expect(stableNode(undefined, '/fallback/node', exists)).toBe('/fallback/node')
    expect(parseDevinInstall(['--node', '/usr/local/bin/node'], defaults).node).toBe('/usr/local/bin/node')
  })

  it('quotes paths with spaces for the shell', () => {
    expect(shellQuote('/Library/Application Support/x')).toBe("'/Library/Application Support/x'")
    expect(shellQuote('/usr/bin/node')).toBe('/usr/bin/node')
  })
})
