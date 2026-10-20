import { describe, it, expect, beforeAll, afterAll, beforeEach, afterEach } from 'vitest'
import { spawn, type ChildProcess } from 'node:child_process'
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { build } from 'esbuild'
import { startHarness, type Harness } from '../harness.ts'

// meshd as it ships (the bundled entry point), against a real relay, with a stub herdr on PATH.

const ROOT = resolve(import.meta.dirname, '../../../..')
let outDir: string
let MESHD: string

beforeAll(async () => {
  outDir = mkdtempSync(join(tmpdir(), 'meshd-bundle-'))
  MESHD = join(outDir, 'meshd.mjs')
  await build({
    bundle: true, platform: 'node', format: 'esm', target: 'node20', logLevel: 'silent',
    banner: { js: "import { createRequire as __cr } from 'node:module'; const require = __cr(import.meta.url);" },
    entryPoints: [join(ROOT, 'packages/peer-agent/src/meshd/main.ts')], outfile: MESHD,
  })
})
afterAll(() => { rmSync(outDir, { recursive: true, force: true }) })

// An agent CLI the way npm installs one: a node script found through `env`.
const PI_STUB = `#!/usr/bin/env node
console.log('1.3.0')
`

const HERDR_STUB = `#!/usr/bin/env node
const a = process.argv.slice(2)
if (a[0] === '--version') { console.log('herdr 0.9.5'); process.exit(0) }
if (a[0] === 'agent' && a[1] === 'list') {
  console.log(JSON.stringify({ result: { agents: [
    { agent: 'claude', agent_status: 'working', name: 'stub-worker', pane_id: 'w9:p1', tab_id: 'w9:t1', workspace_id: 'w9', cwd: '/tmp' },
  ] } }))
  process.exit(0)
}
if (a[0] === 'agent' && a[1] === 'read' && a[2] === 'w9:p1') { console.log('screen of ' + a[2] + ' lines=' + a[a.indexOf('--lines') + 1]); process.exit(0) }
console.error('stub: unexpected ' + a.join(' ')); process.exit(3)
`

async function api(h: Harness, token: string, method: string, path: string, body?: unknown) {
  const res = await fetch(new URL(path, h.relayUrl), {
    method, headers: { authorization: `Bearer ${token}`, ...(body !== undefined ? { 'content-type': 'application/json' } : {}) },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  return { status: res.status, json: await res.json().catch(() => null) as any }
}

/** Pairs one more device for `handle`, grants it, and returns its raw token. */
async function device(h: Harness, handle: string, label: string, grant: Record<string, unknown>): Promise<string> {
  const code = (await api(h, h.adminToken, 'POST', `/v1/admin/users/${handle}/devices`, {})).json.pair_code as string
  const paired = await (await fetch(new URL('/v1/auth/pair', h.relayUrl), {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ pair_code: code, device_label: label }),
  })).json() as { token: string }
  const tokens = (await api(h, h.adminToken, 'GET', '/v1/admin/tokens')).json as Array<{ id: string; label: string }>
  const id = tokens.find(t => t.label === label)!.id
  expect((await api(h, h.adminToken, 'PUT', `/v1/admin/tokens/${id}/grant`, grant)).status).toBe(200)
  return paired.token
}

async function until<T>(f: () => Promise<T | undefined>, what: string, ms = 15_000): Promise<T> {
  const end = Date.now() + ms
  for (;;) {
    const v = await f().catch(() => undefined)
    if (v !== undefined) return v
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`)
    await new Promise(r => setTimeout(r, 150))
  }
}

describe('L3: meshd against the relay', () => {
  let h: Harness
  let proc: ChildProcess | null = null
  let stderr = ''
  let dir: string
  beforeEach(async () => { h = await startHarness(['alice']); dir = mkdtempSync(join(tmpdir(), 'meshd-e2e-')) })
  afterEach(async () => { proc?.kill(); proc = null; await h.cleanup(); rmSync(dir, { recursive: true, force: true }) })

  function startMeshd(token: string, extraEnv: Record<string, string> = {}) {
    const home = join(dir, 'home'); const bin = join(dir, 'bin'); const meshHome = join(dir, 'meshd-home')
    for (const d of [home, bin, meshHome]) mkdirSync(d, { recursive: true })
    writeFileSync(join(bin, 'herdr'), HERDR_STUB); chmodSync(join(bin, 'herdr'), 0o755)
    writeFileSync(join(bin, 'pi'), PI_STUB); chmodSync(join(bin, 'pi'), 0o755)
    writeFileSync(join(meshHome, 'token'), token, { mode: 0o600 })
    writeFileSync(join(meshHome, 'config.json'), JSON.stringify({ relay_url: h.relayUrl, token_path: join(meshHome, 'token') }))
    // No node on PATH, as under systemd on a machine whose node comes from a version manager.
    proc = spawn(process.execPath, [MESHD], {
      env: { PATH: `${bin}:/usr/bin:/bin`, HOME: home, MESH_HOME: meshHome, MESHD_MAX_ACTIVE: '3', ...extraEnv },
      stdio: ['ignore', 'ignore', 'pipe'],
    })
    proc.stderr!.on('data', d => { stderr += d })
  }

  it('reports the machine bound to its token and answers an orchestrator\'s read', async () => {
    const exec = await device(h, 'alice', 'meshd-e2e', { role: 'executor', workgroup: 'team', machine: 'e2e-box' })
    const orch = await device(h, 'alice', 'orch-e2e', { role: 'orchestrator', workgroup: 'team' })
    startMeshd(exec)

    const machine = await until(async () => {
      const list = (await api(h, orch, 'GET', '/v1/machines')).json as Array<{ machine: string; connected: boolean; report: { agents: Array<{ name: string }> } }>
      const m = list.find(x => x.machine === 'e2e-box')
      return m && m.connected ? m : undefined
    }, 'e2e-box reported and connected')
    expect(machine.report).toMatchObject({ herdr: { ok: true, version: '0.9.5' }, active: 1, max_active: 3, agents: [{ name: 'stub-worker', pane: 'w9:p1' }] })
    expect((machine.report as unknown as { kinds: unknown[] }).kinds).toContainEqual({ kind: 'pi', version: '1.3.0' })

    const issued = await api(h, orch, 'POST', '/v1/machines/e2e-box/commands', { op: 'read', args: { pane: 'w9:p1', lines: 12 } })
    expect(issued.status).toBe(202)
    const done = (await api(h, orch, 'GET', `/v1/commands/${issued.json.id}?wait=10`)).json
    expect(done).toMatchObject({ state: 'done', result: { ok: true, output: 'screen of w9:p1 lines=12\n' } })
    await until(async () => (stderr.includes('"event":"meshd.command"') ? true : undefined), 'meshd logging the command')
    expect(stderr).toMatch(/"event":"meshd.command","at":"[^"]+","id":"cmd_[0-9A-Z]{26}","op":"read","ok":true,"status":200/)
  })

  it('refuses to start on the shared device config (no MESH_HOME), and a worker token cannot report', async () => {
    const res = spawn(process.execPath, [MESHD], { env: { PATH: dirname(process.execPath), HOME: dir }, stdio: ['ignore', 'ignore', 'pipe'] })
    let err = ''
    res.stderr!.on('data', d => { err += d })
    const code = await new Promise<number | null>(r => res.on('exit', c => r(c)))
    expect(code).toBe(2)
    expect(err).toContain('meshd.no_mesh_home')

    const worker = await device(h, 'alice', 'plain-device', { role: 'worker', workgroup: 'team' })
    startMeshd(worker)
    await until(async () => (stderr.includes('meshd.report_rejected') ? true : undefined), 'a rejected report')
    expect(stderr).toContain('"status":403')
  })
})
