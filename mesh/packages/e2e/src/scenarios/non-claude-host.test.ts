import { describe, it, expect, beforeAll, afterAll, beforeEach, afterEach } from 'vitest'
import { spawn, execFile, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'
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
  /** What a host such as Devin CLI does when it exits: close the pipe, send no signal. */
  closeStdin: () => void
  exited: Promise<{ code: number | null; signal: NodeJS.Signals | null }>
}

function childEnv(meshHome: string, extra: Record<string, string>, home = mkdtempSync(join(tmpdir(), 'mesh-home-'))): NodeJS.ProcessEnv {
  // A throwaway HOME, so no real ~/.claude session file can name these peers.
  const env: NodeJS.ProcessEnv = { PATH: process.env.PATH, HOME: home, MESH_HOME: meshHome, ...extra }
  return env
}

/** Set up the host's HOME and working directory before the peer starts (real paths, as the peer sees them). */
type Prepare = (dirs: { home: string; cwd: string }) => void

async function startPeer(h: Harness, who: string, extra: Record<string, string>, prepare?: Prepare): Promise<Peer> {
  const cwd = realpathSync(mkdtempSync(join(tmpdir(), `host-${who}-`)))
  const home = realpathSync(mkdtempSync(join(tmpdir(), 'mesh-home-')))
  prepare?.({ home, cwd })
  const p: ChildProcessWithoutNullStreams = spawn(process.execPath, [PEER], {
    cwd, env: childEnv(join(h.humans[who]!.configDir, '.claude-mesh'), extra, home), stdio: ['pipe', 'pipe', 'pipe'],
  })
  let buf = ''
  let stderr = ''
  let next = 1
  const waiting = new Map<number, (m: { result?: { content?: Array<{ text: string }>; isError?: boolean }; error?: unknown }) => void>()
  p.stderr.on('data', d => { stderr += d })
  const exited = new Promise<{ code: number | null; signal: NodeJS.Signals | null }>(res => { p.on('exit', (code, signal) => res({ code, signal })) })
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
    closeStdin: () => { p.stdin.end() },
    exited,
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
  const peer = async (who: string, extra: Record<string, string>, prepare?: Prepare) => { const p = await startPeer(h, who, extra, prepare); peers.push(p); return p }
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

  it('an unnamed pull peer is named after its directory with the host prefix, not after a Claude session in that directory', async () => {
    let cwd = ''
    // A live Claude Code session (this test process) registered in the same directory as the host.
    const neighbour: Prepare = d => {
      cwd = d.cwd
      mkdirSync(join(d.home, '.claude', 'sessions'), { recursive: true })
      writeFileSync(join(d.home, '.claude', 'sessions', `${process.pid}.json`), JSON.stringify({ pid: process.pid, cwd: d.cwd, name: 'claude-neighbour', status: 'busy', kind: 'interactive', startedAt: Date.now() }))
    }
    const agy = await peer('alice', { MESH_JOIN: 'pull', MESH_HOST: 'agy' }, neighbour)
    const expected = `agy-${basename(cwd)}`
    const listing = await until(async () => { const t = await agy.call('list_agents'); return t.includes('(this session)') ? t : undefined }, 'own row in list_agents')
    expect(listing).not.toContain('claude-neighbour')
    expect(listing).toMatch(new RegExp(`^${expected} \\[[0-9a-z]{6}\\] \\(this session\\) — alice@e2e · unknown · pull · `, 'm'))
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

  it('a pull peer exits when its host closes stdin without signalling it, and its session stops being live', async () => {
    const devin = await peer('alice', { MESH_JOIN: 'pull', MESH_SESSION_NAME: 'devin-gone' })
    const watcher = await peer('bob', { MESH_JOIN: 'pull', MESH_SESSION_NAME: 'bob-watch' })
    await until(async () => ((await watcher.call('list_agents')).match(/^devin-gone \[[0-9a-z]{6}\] — alice@e2e · unknown · pull/m) ? true : undefined), 'devin-gone live')

    devin.closeStdin()
    const exit = await Promise.race([devin.exited, new Promise<'still running'>(r => setTimeout(() => r('still running'), 5_000))])
    expect(exit).toEqual({ code: 0, signal: null })
    const after = await until(async () => { const t = await watcher.call('list_agents'); return /^devin-gone .* · reconnecting/m.test(t) ? t : undefined }, 'devin-gone reconnecting')
    expect(after).toMatch(/^devin-gone \[[0-9a-z]{6}\] — alice@e2e · reconnecting/m)
  })

  it('agy hooks: told about arrivals mid-turn, nudged once at a stop, busy/idle on the mesh, and an idle pane woken through Herdr', async () => {
    const meshHome = join(h.humans.alice!.configDir, '.claude-mesh')
    const work = mkdtempSync(join(tmpdir(), 'agy-wake-'))
    const wakeLog = join(work, 'herdr-calls')
    const fakeHerdr = join(work, 'herdr')
    writeFileSync(fakeHerdr, `#!/bin/sh\nprintf '%s|' "$@" >> '${wakeLog}'\necho >> '${wakeLog}'\n`, { mode: 0o755 })
    const agy = await peer('alice', { MESH_JOIN: 'pull', MESH_HOST: 'agy', MESH_SESSION_NAME: 'agy-e2e', MESH_WAKE: 'herdr', HERDR_ENV: '1', HERDR_PANE_ID: 'w9:p9', HERDR_BIN_PATH: fakeHerdr })
    const bob = await peer('bob', { MESH_JOIN: 'pull', MESH_SESSION_NAME: 'bob-inbox' })
    // The hook runs as a child of the same process as the peer (this test), the way agy runs both.
    const hook = async (event: string, payload: object = {}) => {
      const child = execFile(process.execPath, [CLI, 'agy', 'hook', event], { env: childEnv(meshHome, {}) })
      child.stdin!.end(JSON.stringify(payload))
      const out = await new Promise<string>((res, rej) => { let o = ''; child.stdout!.on('data', d => { o += d }); child.on('exit', c => (c === 0 ? res(o) : rej(new Error(`hook exit ${c}`)))) })
      return JSON.parse(out) as { injectSteps?: Array<{ ephemeralMessage: string }>; decision?: string; reason?: string }
    }
    const row = async (state: string) => until(async () => { const t = await bob.call('list_agents'); return new RegExp(`^agy-e2e \\[[0-9a-z]{6}\\] — alice@e2e · ${state} · pull`, 'm').test(t) ? t : undefined }, `agy-e2e ${state}`)
    await row('unknown')
    await until(async () => (Object.keys(await hook('PreInvocation')).length === 0 ? true : undefined), 'hook socket up')
    await row('busy')

    await bob.call('send_message', { to: 'agy-e2e', message: 'please read me' })
    const turn = await until(async () => { const o = await hook('PreInvocation', { invocationNum: 1 }); return o.injectSteps ? o : undefined }, 'a notice before the next model call')
    expect(turn.injectSteps![0]!.ephemeralMessage).toMatch(/^\[mesh\] 1 unread message from bob-inbox \[[0-9a-z]{6}\] is waiting\. Call the mesh read_messages tool/)
    expect(JSON.stringify(turn)).not.toContain('please read me')
    expect(await hook('Stop', { terminationReason: 'USER_CANCELED' })).toEqual({})
    await row('idle')
    expect((await hook('Stop', { terminationReason: 'NO_TOOL_CALL' })).decision).toBe('continue')
    expect(await hook('Stop', { terminationReason: 'NO_TOOL_CALL' })).toEqual({})
    expect((await nextMessage(agy)).body).toBe('please read me')

    // Idle now (the last stop): a new message wakes the pane, naming the sender only.
    expect(existsSync(wakeLog)).toBe(false)
    await bob.call('send_message', { to: 'agy-e2e', message: 'second' })
    const calls = await until(async () => (existsSync(wakeLog) ? readFileSync(wakeLog, 'utf8') : undefined), 'a herdr prompt')
    expect(calls).toMatch(/^agent\|prompt\|w9:p9\|\[mesh\] 1 new message from bob-inbox \[[0-9a-z]{6}\]\. Call the mesh read_messages tool to read it\.\|\n$/)
    expect(calls).not.toContain('second')
  })

  it('grok hooks: idle from the start so a fresh pane can be woken, one notice on a tool result, a natural stop kept going once', async () => {
    const meshHome = join(h.humans.alice!.configDir, '.claude-mesh')
    const work = mkdtempSync(join(tmpdir(), 'grok-wake-'))
    const wakeLog = join(work, 'herdr-calls')
    const fakeHerdr = join(work, 'herdr')
    writeFileSync(fakeHerdr, `#!/bin/sh\nprintf '%s|' "$@" >> '${wakeLog}'\necho >> '${wakeLog}'\n`, { mode: 0o755 })
    const grok = await peer('alice', { MESH_JOIN: 'pull', MESH_HOST: 'grok', MESH_SESSION_NAME: 'grok-e2e', MESH_WAKE: 'herdr', HERDR_ENV: '1', HERDR_PANE_ID: 'w9:p8', HERDR_BIN_PATH: fakeHerdr })
    const bob = await peer('bob', { MESH_JOIN: 'pull', MESH_SESSION_NAME: 'bob-inbox' })
    // Grok Build runs hooks and MCP servers as children of the grok process; here that is this test.
    const hook = async (event: string, payload: object = {}) => {
      const child = execFile(process.execPath, [CLI, 'grok', 'hook', event], { env: childEnv(meshHome, {}) })
      child.stdin!.end(JSON.stringify(payload))
      const out = await new Promise<string>((res, rej) => { let o = ''; child.stdout!.on('data', d => { o += d }); child.on('exit', c => (c === 0 ? res(o) : rej(new Error(`hook exit ${c}`)))) })
      return JSON.parse(out) as { hookSpecificOutput?: { hookEventName: string; additionalContext: string }; decision?: string; reason?: string }
    }
    const row = async (state: string) => until(async () => { const t = await bob.call('list_agents'); return new RegExp(`^grok-e2e \\[[0-9a-z]{6}\\] — alice@e2e · ${state} · pull`, 'm').test(t) ? t : undefined }, `grok-e2e ${state}`)
    await row('unknown')
    // SessionStart fires when grok starts, before any prompt.
    await until(async () => (Object.keys(await hook('SessionStart', { source: 'new' })).length === 0 ? true : undefined), 'hook socket up')
    await row('idle')
    await bob.call('send_message', { to: 'grok-e2e', message: 'first' })
    const calls = await until(async () => (existsSync(wakeLog) ? readFileSync(wakeLog, 'utf8') : undefined), 'a herdr prompt')
    expect(calls).toMatch(/^agent\|prompt\|w9:p8\|\[mesh\] 1 new message from bob-inbox \[[0-9a-z]{6}\]\. Call the mesh read_messages tool to read it\.\|\n$/)
    expect(calls).not.toContain('first')

    // The wake prompt starts a turn; the agent reads.
    expect(await hook('UserPromptSubmit', { prompt: '[mesh] 1 new message' })).toEqual({})
    await row('busy')
    expect((await nextMessage(grok)).body).toBe('first')
    expect(await hook('PostToolUse', { toolName: 'mesh__read_messages' })).toEqual({})

    // Mail during the turn: the next tool result carries one notice, the one after does not.
    await bob.call('send_message', { to: 'grok-e2e', message: 'second' })
    const tool = await until(async () => { const o = await hook('PostToolUse', { toolName: 'read_file' }); return o.hookSpecificOutput ? o : undefined }, 'a notice on a tool result')
    expect(tool.hookSpecificOutput).toEqual({ hookEventName: 'PostToolUse', additionalContext: expect.stringMatching(/^\[mesh\] 1 unread message from bob-inbox \[[0-9a-z]{6}\] is waiting\. Call the mesh read_messages tool/) })
    expect(JSON.stringify(tool)).not.toContain('second')
    expect(await hook('PostToolUse', { toolName: 'read_file' })).toEqual({})
    // An interrupt is never overridden; a turn that ended on its own runs once more.
    expect(await hook('StopCancelled', { reason: 'user_interrupt' })).toEqual({})
    await row('idle')
    expect((await hook('Stop', { reason: 'end_turn', stopHookActive: false })).decision).toBe('block')
    expect(await hook('Stop', { reason: 'end_turn', stopHookActive: true })).toEqual({})
    expect((await nextMessage(grok)).body).toBe('second')
  })

  it('devin hooks: idle from the start so a fresh pane can be woken, one notice on a tool result, a stop kept going once, the session forgotten at its end', async () => {
    const meshHome = join(h.humans.alice!.configDir, '.claude-mesh')
    const work = mkdtempSync(join(tmpdir(), 'devin-wake-'))
    const wakeLog = join(work, 'herdr-calls')
    const fakeHerdr = join(work, 'herdr')
    writeFileSync(fakeHerdr, `#!/bin/sh\nprintf '%s|' "$@" >> '${wakeLog}'\necho >> '${wakeLog}'\n`, { mode: 0o755 })
    const devin = await peer('alice', { MESH_JOIN: 'pull', MESH_HOST: 'devin', MESH_SESSION_NAME: 'devin-e2e', MESH_WAKE: 'herdr', HERDR_ENV: '1', HERDR_PANE_ID: 'w9:p7', HERDR_BIN_PATH: fakeHerdr })
    const bob = await peer('bob', { MESH_JOIN: 'pull', MESH_SESSION_NAME: 'bob-inbox' })
    // Devin CLI runs hooks and MCP servers as children of its agent process (`devin acp`); here that is this test.
    const sid = 'spiny-keyboard'
    const hook = async (event: string, payload: object = {}) => {
      const child = execFile(process.execPath, [CLI, 'devin', 'hook', event], { env: childEnv(meshHome, {}) })
      child.stdin!.end(JSON.stringify({ hook_event_name: event, session_id: sid, ...payload }))
      const out = await new Promise<string>((res, rej) => { let o = ''; child.stdout!.on('data', d => { o += d }); child.on('exit', c => (c === 0 ? res(o) : rej(new Error(`hook exit ${c}`)))) })
      return JSON.parse(out) as { hookSpecificOutput?: { hookEventName: string; additionalContext: string }; decision?: string; reason?: string }
    }
    const row = async (state: string) => until(async () => { const t = await bob.call('list_agents'); return new RegExp(`^devin-e2e \\[[0-9a-z]{6}\\] — alice@e2e · ${state} · pull`, 'm').test(t) ? t : undefined }, `devin-e2e ${state}`)
    await row('unknown')
    expect(await hook('SessionStart', { source: 'startup' })).toEqual({})
    await row('idle')
    expect(existsSync(join(meshHome, 'hooks', `devin-${sid}.pid`))).toBe(true)

    await bob.call('send_message', { to: 'devin-e2e', message: 'first' })
    const calls = await until(async () => (existsSync(wakeLog) ? readFileSync(wakeLog, 'utf8') : undefined), 'a herdr prompt')
    expect(calls).toMatch(/^agent\|prompt\|w9:p7\|\[mesh\] 1 new message from bob-inbox \[[0-9a-z]{6}\]\. Call the mesh read_messages tool to read it\.\|\n$/)
    expect(calls).not.toContain('first')

    expect(await hook('UserPromptSubmit', { prompt: '[mesh] 1 new message' })).toEqual({})
    await row('busy')
    expect((await nextMessage(devin)).body).toBe('first')
    expect(await hook('PostToolUse', { tool_name: 'mcp__mesh__read_messages', tool_response: { success: true } })).toEqual({})

    await bob.call('send_message', { to: 'devin-e2e', message: 'second' })
    const tool = await until(async () => { const o = await hook('PostToolUse', { tool_name: 'exec' }); return o.hookSpecificOutput ? o : undefined }, 'a notice on a tool result')
    expect(tool.hookSpecificOutput).toEqual({ hookEventName: 'PostToolUse', additionalContext: expect.stringMatching(/^\[mesh\] 1 unread message from bob-inbox \[[0-9a-z]{6}\] is waiting\. Call the mesh read_messages tool/) })
    expect(JSON.stringify(tool)).not.toContain('second')
    expect(await hook('PostToolUse', { tool_name: 'exec' })).toEqual({})
    const stop = await hook('Stop', { stop_hook_active: false, last_assistant_message: 'done' })
    expect(stop.decision).toBe('block')
    expect(stop.reason).not.toContain('second')
    expect(await hook('Stop', { stop_hook_active: true })).toEqual({})
    await row('idle')
    expect((await nextMessage(devin)).body).toBe('second')

    expect(await hook('SessionEnd', { reason: 'exit' })).toEqual({})
    expect(existsSync(join(meshHome, 'hooks', `devin-${sid}.pid`))).toBe(false)

    // Devin on Windows runs hooks through Git Bash: two shells between the hook and the agent. Same
    // depth here (neither shell execs into the next), under a session id with nothing remembered.
    await bob.call('send_message', { to: 'devin-e2e', message: 'third' })
    await until(async () => ((await bob.call('list_agents')).match(/^devin-e2e .* · idle · pull/m) ? true : undefined), 'devin-e2e idle')
    const deep = execFile('sh', ['-c', `sh -c '"$0" "$1" devin hook UserPromptSubmit; true' "$0" "$1"; true`, process.execPath, CLI], { env: childEnv(meshHome, {}) })
    deep.stdin!.end(JSON.stringify({ hook_event_name: 'UserPromptSubmit', session_id: 'deep-session', prompt: 'x' }))
    expect(await new Promise<string>(res => { let o = ''; deep.stdout!.on('data', d => { o += d }); deep.on('exit', () => res(o)) })).toBe('{}\n')
    await row('busy')
    expect(readFileSync(join(meshHome, 'hooks', 'devin-deep-session.pid'), 'utf8')).toBe(String(process.pid))
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
