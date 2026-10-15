import { describe, it, expect, beforeAll, afterAll, beforeEach, afterEach } from 'vitest'
import { spawn, execFile, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { promisify } from 'node:util'
import { build } from 'esbuild'
import { startHarness, type Harness } from '../harness.ts'

// Runs the peer the way a non-Claude MCP host (Devin CLI) does: the bundled
// mesh-peer.mjs as a stdio child, driven over JSON-RPC, no Claude Code involved.

const ROOT = resolve(import.meta.dirname, '../../../..')
let outDir: string
let PEER: string
let CLI: string

beforeAll(async () => {
  outDir = mkdtempSync(join(tmpdir(), 'mesh-bundle-'))
  PEER = join(outDir, 'mesh-peer.mjs')
  CLI = join(outDir, 'mesh-cli.mjs')
  const common = {
    bundle: true, platform: 'node' as const, format: 'esm' as const, target: 'node20', logLevel: 'silent' as const,
    banner: { js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);" },
  }
  await build({ ...common, entryPoints: [join(ROOT, 'packages/peer-agent/src/index.ts')], outfile: PEER })
  await build({ ...common, entryPoints: [join(ROOT, 'packages/peer-agent/src/cli.ts')], outfile: CLI })
})
afterAll(() => { rmSync(outDir, { recursive: true, force: true }) })

interface Peer {
  call: (tool: string, args?: Record<string, unknown>) => Promise<string>
  stop: () => void
}

function childEnv(meshHome: string, extra: Record<string, string>): NodeJS.ProcessEnv {
  // A throwaway HOME, so no real ~/.claude session file can name these peers.
  const home = mkdtempSync(join(tmpdir(), 'mesh-home-'))
  const env: NodeJS.ProcessEnv = { PATH: process.env.PATH, HOME: home, MESH_HOME: meshHome, ...extra }
  return env
}

async function startPeer(h: Harness, who: string, extra: Record<string, string>): Promise<Peer> {
  const cwd = mkdtempSync(join(tmpdir(), `host-${who}-`))
  const p: ChildProcessWithoutNullStreams = spawn(process.execPath, [PEER], {
    cwd, env: childEnv(join(h.humans[who]!.configDir, '.claude-mesh'), extra), stdio: ['pipe', 'pipe', 'pipe'],
  })
  let buf = ''
  let stderr = ''
  let next = 1
  const waiting = new Map<number, (m: { result?: { content?: Array<{ text: string }>; isError?: boolean }; error?: unknown }) => void>()
  p.stderr.on('data', d => { stderr += d })
  p.on('exit', code => {
    for (const [id, res] of waiting) { waiting.delete(id); res({ error: `peer exited (${code}): ${stderr.slice(-2000)}` }) }
  })
  p.stdout.on('data', d => {
    buf += d
    let i
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1)
      try { const m = JSON.parse(line); waiting.get(m.id)?.(m); waiting.delete(m.id) } catch { /* not JSON-RPC */ }
    }
  })
  const rpc = (method: string, params: unknown) => new Promise<{ result?: { content?: Array<{ text: string }>; isError?: boolean }; error?: unknown }>(res => {
    const id = next++
    waiting.set(id, res)
    p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
  })
  const init = await rpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'devin-like', version: '0' } })
  if (init.error) throw new Error(String(init.error))
  p.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n')
  return {
    call: async (tool, args = {}) => {
      const m = await rpc('tools/call', { name: tool, arguments: args })
      const text = (m.result?.content ?? []).map(c => c.text).join('\n')
      if (m.error || m.result?.isError) throw new Error(text || JSON.stringify(m.error))
      return text
    },
    stop: () => { p.kill() },
  }
}

async function until<T>(f: () => Promise<T | undefined>, what: string, ms = 10_000): Promise<T> {
  const end = Date.now() + ms
  for (;;) {
    const v = await f().catch(() => undefined)
    if (v !== undefined) return v
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`)
    await new Promise(r => setTimeout(r, 100))
  }
}

const attrs = (tag: string): Record<string, string> =>
  Object.fromEntries([...tag.matchAll(/ ([a-z_]+)="([^"]*)"/g)].map(m => [m[1]!, m[2]!]))

async function nextMessage(p: Peer): Promise<{ attrs: Record<string, string>; body: string }> {
  const text = await until(async () => { const t = await p.call('read_messages'); return t.includes('<channel') ? t : undefined }, 'a message in the inbox')
  const m = /<channel([^>]*)>\n([\s\S]*?)\n<\/channel>/.exec(text)!
  return { attrs: attrs(m[1]!), body: m[2]! }
}

describe('L3: hosts without channels (Devin-style), relay-only', () => {
  let h: Harness
  const peers: Peer[] = []
  const peer = async (who: string, extra: Record<string, string>) => { const p = await startPeer(h, who, extra); peers.push(p); return p }
  beforeEach(async () => { h = await startHarness(['alice', 'bob']) })
  afterEach(async () => { for (const p of peers.splice(0)) p.stop(); await h.cleanup() })

  it('pull sessions are listed as "pull", and messages go both ways under the names they were given', async () => {
    const devin = await peer('alice', { MESH_JOIN: 'pull', MESH_SESSION_NAME: 'devin-e2e' })
    const inbox = await peer('bob', { MESH_JOIN: 'pull', MESH_SESSION_NAME: 'bob-inbox' })

    const listing = await until(async () => { const t = await devin.call('list_agents'); return t.includes('bob-inbox') ? t : undefined }, 'bob-inbox in list_agents')
    expect(listing).toMatch(/^bob-inbox \[[0-9a-z]{6}\] — bob@e2e · unknown · pull · /m)
    expect(listing).toMatch(/^devin-e2e \[[0-9a-z]{6}\] \(this session\) — alice@e2e · unknown · pull · /m)

    expect(await devin.call('send_message', { to: 'bob-inbox', message: 'hello from devin' })).toMatch(/^delivered to bob-inbox \[/)
    const got = await nextMessage(inbox)
    expect(got.attrs.from).toMatch(/^devin-e2e \[[0-9a-z]{6}\]$/)
    expect(got.attrs.account).toBe('alice')
    expect(got.attrs).not.toHaveProperty('sender')
    expect(got.body).toBe('hello from devin')

    // Reply by copying `from` verbatim, as the instructions say; the pull sender reads it later.
    await inbox.call('send_message', { to: got.attrs.from!, message: 'got it', in_reply_to: got.attrs.msg_id! })
    const back = await nextMessage(devin)
    expect(back.attrs.from).toMatch(/^bob-inbox \[[0-9a-z]{6}\]$/)
    expect(back.attrs.in_reply_to).toBe(got.attrs.msg_id)
    expect(back.body).toBe('got it')
    expect(await devin.call('read_messages')).toBe('No new messages.')
  })

  it('a send-only peer (MESH_JOIN=never) with MESH_SESSION_NAME is not listed, and its messages carry that name', async () => {
    const inbox = await peer('bob', { MESH_JOIN: 'pull', MESH_SESSION_NAME: 'bob-inbox' })
    const oneshot = await peer('alice', { MESH_JOIN: 'never', MESH_SESSION_NAME: 'devin-oneshot' })
    await until(async () => ((await oneshot.call('list_agents')).includes('bob-inbox') ? true : undefined), 'bob-inbox listed')
    expect(await oneshot.call('list_agents')).not.toContain('devin-oneshot')

    await oneshot.call('send_message', { to: 'bob-inbox', message: 'one-shot report' })
    const got = await nextMessage(inbox)
    expect(got.attrs.from).toBe('devin-oneshot')
    expect(got.attrs.sender).toBe('send-only')
    expect(got.attrs.account).toBe('alice')
  })

  it('a send-only peer without a name still shows its account handle, as before', async () => {
    const inbox = await peer('bob', { MESH_JOIN: 'pull', MESH_SESSION_NAME: 'bob-inbox' })
    const anon = await peer('alice', { MESH_JOIN: 'never' })
    await until(async () => ((await anon.call('list_agents')).includes('bob-inbox') ? true : undefined), 'bob-inbox listed')
    await anon.call('send_message', { to: 'bob-inbox', message: 'x' })
    const got = await nextMessage(inbox)
    expect(got.attrs.from).toBe('alice')
    expect(got.attrs).not.toHaveProperty('sender')
  })

  it('mesh say --as sends one message under that name, with --reply-to', async () => {
    const inbox = await peer('bob', { MESH_JOIN: 'pull', MESH_SESSION_NAME: 'bob-inbox' })
    const lister = await peer('alice', { MESH_JOIN: 'never' })
    await until(async () => ((await lister.call('list_agents')).includes('bob-inbox') ? true : undefined), 'bob-inbox listed')
    await lister.call('send_message', { to: 'bob-inbox', message: 'earlier message' })
    const replyTo = (await nextMessage(inbox)).attrs.msg_id!
    const { stdout } = await promisify(execFile)(process.execPath, [CLI, 'say', '--as', 'docs-devin', '--reply-to', replyTo, 'bob-inbox', '[docs-devin]', 'gates', 'green'], {
      env: childEnv(join(h.humans.alice!.configDir, '.claude-mesh'), {}),
    })
    expect(stdout).toMatch(/^delivered to bob-inbox \[[0-9a-z]{6}\] as docs-devin \(msg_/)
    const got = await nextMessage(inbox)
    expect(got.attrs.from).toBe('docs-devin')
    expect(got.attrs.sender).toBe('send-only')
    expect(got.attrs.in_reply_to).toBe(replyTo)
    expect(got.body).toBe('[docs-devin] gates green')
  })
})
