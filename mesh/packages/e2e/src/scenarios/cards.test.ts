import { describe, it, expect, beforeAll, afterAll, beforeEach, afterEach } from 'vitest'
import { spawn, execFile, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { promisify } from 'node:util'
import { build } from 'esbuild'
import { startHarness, type Harness } from '../harness.ts'

// The session card and task written by the peer from host hook events, the way a Claude Code
// session with the mesh plugin runs them: the bundled peer (joined as a push session) and the
// bundled CLI's `claude hook` commands, both children of this process, as they are children of
// the claude process in real life.

const ROOT = resolve(import.meta.dirname, '../../../..')
const run = promisify(execFile)
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

async function api(h: Harness, token: string, method: string, path: string, body?: unknown, headers: Record<string, string> = {}) {
  const res = await fetch(new URL(path, h.relayUrl), {
    method, headers: { authorization: `Bearer ${token}`, ...(body !== undefined ? { 'content-type': 'application/json' } : {}), ...headers },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  return { status: res.status, json: await res.json().catch(() => null) as any }
}

async function device(h: Harness, handle: string, label: string, grant: Record<string, unknown>): Promise<string> {
  const code = (await api(h, h.adminToken, 'POST', `/v1/admin/users/${handle}/devices`, {})).json.pair_code as string
  const paired = await (await fetch(new URL('/v1/auth/pair', h.relayUrl), {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ pair_code: code, device_label: label }),
  })).json() as { token: string }
  const id = ((await api(h, h.adminToken, 'GET', '/v1/admin/tokens')).json as Array<{ id: string; label: string }>).find(t => t.label === label)!.id
  await api(h, h.adminToken, 'PUT', `/v1/admin/tokens/${id}/grant`, grant)
  return paired.token
}

async function until<T>(f: () => Promise<T | undefined>, what: string, ms = 15_000): Promise<T> {
  const end = Date.now() + ms
  for (;;) {
    const v = await f().catch(() => undefined)
    if (v !== undefined) return v
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`)
    await new Promise(r => setTimeout(r, 200))
  }
}

describe('L3: cards and tasks from host hooks', () => {
  let h: Harness
  const procs: ChildProcessWithoutNullStreams[] = []
  let meshHome: string
  let home: string
  beforeEach(async () => {
    h = await startHarness(['alice'])
    meshHome = join(h.humans.alice!.configDir, '.claude-mesh')
    home = realpathSync(mkdtempSync(join(tmpdir(), 'cards-home-')))
  })
  afterEach(async () => { for (const p of procs.splice(0)) p.kill(); await h.cleanup(); rmSync(home, { recursive: true, force: true }) })

  const env = (extra: Record<string, string> = {}): NodeJS.ProcessEnv => ({ PATH: process.env.PATH, HOME: home, MESH_HOME: meshHome, ...extra })
  const hook = (event: string, stdin = '{"session_id":"cc-1","model":"claude-opus-5-5"}', extra: Record<string, string> = {}) =>
    new Promise<{ code: number | null; out: string }>(res => {
      const p = spawn(process.execPath, [CLI, 'claude', 'hook', event], { env: env(extra), stdio: ['pipe', 'pipe', 'pipe'] })
      let out = ''
      p.stdout.on('data', d => { out += d })
      p.on('exit', code => res({ code, out }))
      p.stdin.end(stdin)
    })
  const startPeer = (extra: Record<string, string>) => {
    const cwd = realpathSync(mkdtempSync(join(tmpdir(), 'cards-cwd-')))
    const p = spawn(process.execPath, [PEER], {
      cwd, env: env({ MESH_JOIN: 'always', MESH_SESSION_NAME: 'card-e2e', HERDR_ENV: '1', HERDR_PANE_ID: 'w9:p1', HERDR_TAB_ID: 'w9:t1', MESH_MACHINE: 'e2e-box', ...extra }),
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    procs.push(p)
    return p
  }
  const row = async (tok: string, name = 'card-e2e') => ((await api(h, tok, 'GET', '/v1/sessions')).json as Array<Record<string, any>>).find(r => r.name === name && r.status !== 'reconnecting')
  const task = async (tok: string, id: string) => (await api(h, tok, 'GET', `/v1/tasks/${id}`)).json as { state: string; assignee: { session: string } }

  it('writes the card, takes over the task after a restart, and follows turns, prompts and stops', async () => {
    const orch = await device(h, 'alice', 'orch-e2e', { role: 'orchestrator', workgroup: 'team' })
    const alice = h.humans.alice!.token
    // A task dispatched to an earlier process of this session (the session id changes on every start).
    const old = 's_01hrk7y0000000000000old001'
    const ac = new AbortController()
    void fetch(new URL(`/v1/stream?session=${old}&name=card-e2e`, h.relayUrl), { headers: { authorization: `Bearer ${alice}` }, signal: ac.signal }).catch(() => {})
    await until(async () => (await row(alice)) ? true : undefined, 'the earlier session listed')
    const t = (await api(h, orch, 'POST', '/v1/tasks', { title: 'e2e work', assignee: old })).json as { id: string; state: string }
    expect(t.state).toBe('submitted')
    ac.abort()

    startPeer({ MESH_TASK_ID: t.id })
    const card = await until(async () => { const r = await row(alice); return r?.agent ? r : undefined }, 'the card')
    expect(card).toMatchObject({ agent: 'claude', herdr: { machine: 'e2e-box', tab: 'w9:t1', pane: 'w9:p1' }, task_id: t.id, source: 'poll' })
    const me = card.session_id as string
    await until(async () => ((await task(alice, t.id)).assignee.session === me ? true : undefined), 'the task rebound to this session')

    const envFile = join(home, 'cc.env'); writeFileSync(envFile, '')
    expect((await hook('session-start', undefined, { CLAUDE_ENV_FILE: envFile })).out).toBe('')
    expect(readFileSync(envFile, 'utf8')).toBe(`export MESH_SESSION_ID=${me}\n`)
    await until(async () => ((await row(alice))?.model === 'claude-opus-5-5' ? true : undefined), 'the model from the session-start hook')

    const turn = await hook('turn')
    expect(turn).toEqual({ code: 0, out: '' })
    await until(async () => ((await task(alice, t.id)).state === 'working' ? true : undefined), 'working after the first turn')
    expect((await row(alice))?.status).toBe('busy')
    await hook('blocked')
    await until(async () => ((await task(alice, t.id)).state === 'input_required' ? true : undefined), 'input_required on a permission prompt')
    await hook('stop')
    await until(async () => ((await task(alice, t.id)).state === 'working' ? true : undefined), 'working again once the turn ended')
    await until(async () => ((await row(alice))?.status === 'idle' ? true : undefined), 'idle after the stop')
    await until(async () => ((await row(alice))?.source === 'hook' ? true : undefined), 'the card marked as hook-fed')

    // A command run inside the host finds the session through the peer: no --session needed.
    const lease = await run(process.execPath, [CLI, 'lease', 'acquire', 'repo/e2e', '--ttl', '60'], { env: env() })
    expect(lease.stdout).toMatch(/^lease_[0-9A-Z]{26} {2}expires /)
    const leases = (await api(h, alice, 'GET', '/v1/leases')).json as Array<{ holder: { session: string } }>
    expect(leases[0]!.holder.session).toBe(me)
  })

  it('MESH_CARD_WRITE=0 writes no card and leaves the task alone', async () => {
    const orch = await device(h, 'alice', 'orch-e2e', { role: 'orchestrator', workgroup: 'team' })
    const alice = h.humans.alice!.token
    startPeer({ MESH_CARD_WRITE: '0' })
    const r = await until(async () => row(alice), 'the session')
    const t = (await api(h, orch, 'POST', '/v1/tasks', { title: 'x', assignee: r.session_id })).json as { id: string }
    await hook('turn')
    await new Promise(res => setTimeout(res, 2_500))
    expect((await row(alice))?.agent).toBeUndefined()
    expect((await task(alice, t.id)).state).toBe('submitted')
    expect((await row(alice))?.status).toBe('busy')
  })
})
