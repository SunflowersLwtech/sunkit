import { describe, it, expect, vi, afterEach } from 'vitest'
import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { LedgerClient, runLease, runMachine, runTask } from './ledger.ts'

interface Call {
  method: string
  origin: string
  path: string
  query: string
  body: unknown
  headers: Record<string, string>
}

interface Reply { status?: number; body: unknown }

/** A fake relay: every call is recorded, every answer comes from the handler list. */
function fakeRelay(handlers: Array<Reply | ((call: Call) => Reply)>) {
  const calls: Call[] = []
  const impl = vi.fn(async (url: string | URL, init: RequestInit = {}) => {
    const u = new URL(String(url))
    const call: Call = {
      method: (init.method ?? 'GET').toUpperCase(),
      origin: u.origin,
      path: u.pathname,
      query: u.search,
      body: init.body === undefined ? undefined : JSON.parse(String(init.body)),
      headers: (init.headers ?? {}) as Record<string, string>,
    }
    calls.push(call)
    const h = handlers[Math.min(calls.length - 1, handlers.length - 1)]
    if (!h) throw new Error('fake relay: no reply registered')
    const reply = typeof h === 'function' ? h(call) : h
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { 'content-type': 'application/json' },
    })
  })
  return { impl, calls }
}

const client = (impl: typeof globalThis.fetch): LedgerClient =>
  new LedgerClient({ relayUrl: 'https://relay.example', token: 'tok-123', session: 's_abcdefghijklmnop' }, { fetch: impl })

/** Collects what the CLI printed. */
function io() {
  const out: string[] = []
  const err: string[] = []
  return {
    out,
    err,
    deps: { out: (s: string) => { out.push(s) }, err: (s: string) => { err.push(s) }, sleep: async () => {} },
  }
}

const MACHINE = {
  machine: 'laptop',
  workgroup: 'core',
  reported_at: '2026-01-01T00:00:00.000Z',
  age_s: 12,
  stale: false,
  connected: true,
  report: {
    version: '1',
    herdr: { ok: true },
    load: { load1: 1.5, cpus: 8 },
    kinds: [],
    seats: [{ email: 'a@example.com', five_hour_pct: 42 }, { email: 'b@example.com' }],
    active: 2,
    blocked: 0,
    max_active: 4,
    agents: [{ name: 'one', agent: 'claude', status: 'idle', pane: 'w1:p1' }],
    roots: [],
  },
}

const TASK = {
  id: 'task_01ARZ3NDEKTSV4RRFFQ69G5FAV',
  title: 'Ship the thing',
  state: 'working',
  progress: 'half way there',
  reason: null,
  workgroup: 'core',
  assignee: { session: 's_abcdefghijklmnop', name: 'alice', machine: 'laptop' },
  dispatcher: { session: null, name: null, machine: null },
  parent_task: null,
  depth: 0,
  prompt_sha256: null,
  artifacts: [],
  seq: 7,
  created_at: '2026-01-01T00:00:00.000Z',
  updated_at: '2026-01-01T00:01:00.000Z',
  deadline: null,
  age_s: 60,
  stale: false,
}

const LEASE = {
  id: 'lease_01ARZ3NDEKTSV4RRFFQ69G5FAV',
  name: 'deploy/site',
  holder: { session: 's_abcdefghijklmnop', name: 'alice', machine: 'laptop', ref: 'alice' },
  task_id: null,
  note: null,
  expires_at: '2026-01-01T00:10:00.000Z',
  ttl_remaining_s: 600,
  renew_count: 0,
}

const savedEnv = { home: process.env.MESH_HOME, session: process.env.MESH_SESSION_ID }
afterEach(() => {
  if (savedEnv.home === undefined) delete process.env.MESH_HOME; else process.env.MESH_HOME = savedEnv.home
  if (savedEnv.session === undefined) delete process.env.MESH_SESSION_ID; else process.env.MESH_SESSION_ID = savedEnv.session
  vi.unstubAllGlobals()
})

describe('mesh machine', () => {
  it('lists the machines the relay knows about', async () => {
    const relay = fakeRelay([{ body: [MACHINE] }])
    const io1 = io()
    const code = await runMachine(['list'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(relay.calls).toHaveLength(1)
    expect(relay.calls[0]!.method).toBe('GET')
    expect(relay.calls[0]!.path).toBe('/v1/machines')
    expect(relay.calls[0]!.query).toBe('')
    expect(relay.calls[0]!.headers.authorization).toBe('Bearer tok-123')
    expect(relay.calls[0]!.headers['x-mesh-session']).toBe('s_abcdefghijklmnop')
    expect(io1.out).toEqual([
      'laptop  ok  connected  age 12s  load 1.5/8  active 2/4  seats a@example.com 42% b@example.com  agents 1',
    ])
  })

  it('--json prints the raw array', async () => {
    const relay = fakeRelay([{ body: [MACHINE] }])
    const io1 = io()
    const code = await runMachine(['list', '--json'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(JSON.parse(io1.out[0]!)).toEqual([MACHINE])
  })

  it('reads a pane: it issues the command, polls until it is done and prints the output', async () => {
    const relay = fakeRelay([
      { status: 202, body: { id: 'cmd_01ARZ3NDEKTSV4RRFFQ69G5FAV', op: 'read', machine: 'laptop', state: 'queued', reason: null, result: null, issued_at: '', expires_at: '' } },
      { body: { id: 'cmd_01ARZ3NDEKTSV4RRFFQ69G5FAV', op: 'read', machine: 'laptop', state: 'claimed', reason: null, result: null, issued_at: '', expires_at: '' } },
      { body: { id: 'cmd_01ARZ3NDEKTSV4RRFFQ69G5FAV', op: 'read', machine: 'laptop', state: 'done', reason: null, result: { ok: true, output: 'hello from the pane' }, issued_at: '', expires_at: '' } },
    ])
    const io1 = io()
    const code = await runMachine(['read', 'laptop', 'w1:p1', '--lines', '20'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(relay.calls).toHaveLength(3)
    expect(relay.calls[0]!.method).toBe('POST')
    expect(relay.calls[0]!.path).toBe('/v1/machines/laptop/commands')
    expect(relay.calls[0]!.body).toEqual({ op: 'read', args: { pane: 'w1:p1', lines: 20 } })
    expect(relay.calls[0]!.headers['x-mesh-session']).toBe('s_abcdefghijklmnop')
    expect(relay.calls[1]!.method).toBe('GET')
    expect(relay.calls[1]!.path).toBe('/v1/commands/cmd_01ARZ3NDEKTSV4RRFFQ69G5FAV')
    expect(relay.calls[1]!.query).toBe('?wait=25')
    expect(relay.calls[2]!.query).toBe('?wait=25')
    expect(io1.out).toEqual(['hello from the pane'])
  })

  it('leaves the lines out when they are not asked for', async () => {
    const relay = fakeRelay([
      { status: 202, body: { id: 'cmd_1', op: 'read', machine: 'laptop', state: 'done', reason: null, result: { ok: true, output: 'x' }, issued_at: '', expires_at: '' } },
    ])
    const io1 = io()
    const code = await runMachine(['read', 'laptop', 'w1:p1'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(relay.calls[0]!.body).toEqual({ op: 'read', args: { pane: 'w1:p1' } })
    expect(relay.calls).toHaveLength(1)
  })

  it('stops polling after three tries and says the command did not finish', async () => {
    const relay = fakeRelay([
      { status: 202, body: { id: 'cmd_1', op: 'read', machine: 'laptop', state: 'queued', reason: null, result: null, issued_at: '', expires_at: '' } },
      { body: { id: 'cmd_1', op: 'read', machine: 'laptop', state: 'claimed', reason: null, result: null, issued_at: '', expires_at: '' } },
    ])
    const io1 = io()
    const code = await runMachine(['read', 'laptop', 'w1:p1'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(1)
    expect(relay.calls.filter(c => c.path === '/v1/commands/cmd_1')).toHaveLength(3)
    expect(io1.err[0]).toContain('did not finish')
  })

  it('probes a machine', async () => {
    const relay = fakeRelay([
      { status: 202, body: { id: 'cmd_2', op: 'probe', machine: 'laptop', state: 'done', reason: null, result: { ok: true, output: 'ok' }, issued_at: '', expires_at: '' } },
    ])
    const io1 = io()
    const code = await runMachine(['probe', 'laptop'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(relay.calls[0]!.method).toBe('POST')
    expect(relay.calls[0]!.path).toBe('/v1/machines/laptop/commands')
    expect(relay.calls[0]!.body).toEqual({ op: 'probe' })
    expect(io1.out).toEqual(['ok'])
  })

  it('reports a failed command', async () => {
    const relay = fakeRelay([
      { status: 202, body: { id: 'cmd_3', op: 'probe', machine: 'laptop', state: 'failed', reason: 'executor_error', result: { ok: false, error: 'no such pane' }, issued_at: '', expires_at: '' } },
    ])
    const io1 = io()
    const code = await runMachine(['probe', 'laptop'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(1)
    expect(io1.err).toEqual(['failed: executor_error'])
    expect(io1.out).toEqual([])
  })

  it('turns a relay refusal into exit code 1 and says what the relay said', async () => {
    const relay = fakeRelay([{ status: 403, body: { error: 'not_a_dispatcher' } }])
    const io1 = io()
    const code = await runMachine(['probe', 'laptop'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(1)
    expect(io1.err).toEqual(['403 not_a_dispatcher'])
  })

  it('does not call the relay when the arguments are wrong', async () => {
    const relay = fakeRelay([{ body: [] }])
    const io1 = io()
    expect(await runMachine(['nonsense'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(await runMachine(['read'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(await runMachine(['read', 'laptop'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(await runMachine(['probe'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(relay.calls).toHaveLength(0)
    expect(io1.err).toHaveLength(4)
    expect(io1.err[0]).toContain('usage: mesh machine')
  })
})

describe('mesh task', () => {
  it('lists the tasks', async () => {
    const relay = fakeRelay([{ body: { tasks: [TASK], seq: 7 } }])
    const io1 = io()
    const code = await runTask(['list'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(relay.calls[0]!.method).toBe('GET')
    expect(relay.calls[0]!.path).toBe('/v1/tasks')
    expect(relay.calls[0]!.query).toBe('?since_seq=0')
    expect(relay.calls[0]!.headers['x-mesh-session']).toBe('s_abcdefghijklmnop')
    expect(io1.out).toEqual([
      'task_01ARZ3NDEKTSV4RRFFQ69G5FAV  working  alice@laptop  Ship the thing',
      '  half way there',
    ])
  })

  it('lists the tasks from a sequence and shows a stale one as stale', async () => {
    const relay = fakeRelay([{ body: { tasks: [{ ...TASK, stale: true }], seq: 8 } }])
    const io1 = io()
    const code = await runTask(['list', '--since', '5'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(relay.calls[0]!.query).toBe('?since_seq=5')
    expect(io1.out[0]).toBe('task_01ARZ3NDEKTSV4RRFFQ69G5FAV  working stale  alice@laptop  Ship the thing')
  })

  it('--json prints the raw answer', async () => {
    const relay = fakeRelay([{ body: { tasks: [TASK], seq: 7 } }])
    const io1 = io()
    const code = await runTask(['list', '--json'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(JSON.parse(io1.out[0]!)).toEqual({ tasks: [TASK], seq: 7 })
  })

  it('shows one task as pretty JSON', async () => {
    const relay = fakeRelay([{ body: TASK }])
    const io1 = io()
    const code = await runTask(['show', TASK.id], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(relay.calls[0]!.method).toBe('GET')
    expect(relay.calls[0]!.path).toBe(`/v1/tasks/${TASK.id}`)
    expect(io1.out[0]).toContain('\n  "title": "Ship the thing"')
    expect(JSON.parse(io1.out[0]!)).toEqual(TASK)
  })

  it('creates a task', async () => {
    const relay = fakeRelay([{ status: 201, body: { ...TASK, id: 'task_new', state: 'submitted' } }])
    const io1 = io()
    const code = await runTask(
      ['create', '--title', 'Ship the thing', '--assignee', 's_abcdefghijklmnop', '--parent', 'task_parent'],
      { client: client(relay.impl as any), ...io1.deps },
    )

    expect(code).toBe(0)
    expect(relay.calls[0]!.method).toBe('POST')
    expect(relay.calls[0]!.path).toBe('/v1/tasks')
    expect(relay.calls[0]!.body).toEqual({ title: 'Ship the thing', assignee: 's_abcdefghijklmnop', parent_task: 'task_parent' })
    expect(relay.calls[0]!.headers['x-mesh-session']).toBe('s_abcdefghijklmnop')
    expect(io1.out).toEqual(['task_new  submitted'])
  })

  it('creates a task for itself with only a title', async () => {
    const relay = fakeRelay([{ status: 201, body: { ...TASK, id: 'task_new' } }])
    const io1 = io()
    const code = await runTask(['create', '--title', 'Do the thing'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(relay.calls[0]!.body).toEqual({ title: 'Do the thing' })
  })

  it('updates only the fields it was given', async () => {
    const relay = fakeRelay([{ body: { ...TASK, state: 'completed' } }])
    const io1 = io()
    const code = await runTask(
      ['update', TASK.id, '--state', 'completed', '--if-seq', '7'],
      { client: client(relay.impl as any), ...io1.deps },
    )

    expect(code).toBe(0)
    expect(relay.calls[0]!.method).toBe('PATCH')
    expect(relay.calls[0]!.path).toBe(`/v1/tasks/${TASK.id}`)
    expect(relay.calls[0]!.body).toEqual({ state: 'completed', if_seq: 7 })
    expect(io1.out).toEqual([`${TASK.id}  completed`])
  })

  it('adds an artifact', async () => {
    const relay = fakeRelay([{ body: TASK }])
    const io1 = io()
    const code = await runTask(
      ['artifact', TASK.id, 'pr', 'https://example.com/pr/1', '--note', 'the first cut'],
      { client: client(relay.impl as any), ...io1.deps },
    )

    expect(code).toBe(0)
    expect(relay.calls[0]!.method).toBe('POST')
    expect(relay.calls[0]!.path).toBe(`/v1/tasks/${TASK.id}/artifacts`)
    expect(relay.calls[0]!.body).toEqual({ type: 'pr', ref: 'https://example.com/pr/1', note: 'the first cut' })
    expect(io1.out).toEqual(['added pr https://example.com/pr/1'])
  })

  it('refuses an update without a single field and an unknown subcommand', async () => {
    const relay = fakeRelay([{ body: TASK }])
    const io1 = io()
    expect(await runTask(['update', TASK.id], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(await runTask(['whatever'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(await runTask(['create'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(await runTask(['show'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(await runTask(['artifact', TASK.id, 'pr'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(relay.calls).toHaveLength(0)
    expect(io1.err).toHaveLength(5)
    expect(io1.err[0]).toContain('usage: mesh task')
  })
})

describe('mesh lease', () => {
  it('lists the leases', async () => {
    const relay = fakeRelay([{ body: [LEASE] }])
    const io1 = io()
    const code = await runLease(['list'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(relay.calls[0]!.method).toBe('GET')
    expect(relay.calls[0]!.path).toBe('/v1/leases')
    expect(relay.calls[0]!.query).toBe('')
    expect(relay.calls[0]!.headers['x-mesh-session']).toBe('s_abcdefghijklmnop')
    expect(io1.out).toEqual(['deploy/site  alice@laptop  600s left  lease_01ARZ3NDEKTSV4RRFFQ69G5FAV'])
  })

  it('lists the leases of one name, and hides a holder the caller cannot see', async () => {
    const relay = fakeRelay([{ body: [{ ...LEASE, holder: null }] }])
    const io1 = io()
    const code = await runLease(['list', '--name', 'deploy/site'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(relay.calls[0]!.query).toBe('?name=deploy%2Fsite')
    expect(io1.out).toEqual(['deploy/site  (hidden)  600s left  lease_01ARZ3NDEKTSV4RRFFQ69G5FAV'])
  })

  it('acquires a lease', async () => {
    const relay = fakeRelay([{ status: 201, body: LEASE }])
    const io1 = io()
    const code = await runLease(
      ['acquire', 'deploy/site', '--ttl', '600', '--note', 'the deploy', '--task', TASK.id],
      { client: client(relay.impl as any), ...io1.deps },
    )

    expect(code).toBe(0)
    expect(relay.calls[0]!.method).toBe('POST')
    expect(relay.calls[0]!.path).toBe('/v1/leases')
    expect(relay.calls[0]!.body).toEqual({ name: 'deploy/site', ttl_s: 600, note: 'the deploy', task_id: TASK.id })
    expect(io1.out).toEqual(['lease_01ARZ3NDEKTSV4RRFFQ69G5FAV  expires 2026-01-01T00:10:00.000Z'])
  })

  it('says who holds a lease it cannot take', async () => {
    const relay = fakeRelay([{ status: 409, body: { error: 'lease_held', message: 'deploy/site is held by bob on desktop for another 5 min' } }])
    const io1 = io()
    const code = await runLease(['acquire', 'deploy/site', '--ttl', '600'], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(1)
    expect(io1.err).toEqual(['deploy/site is held by bob on desktop for another 5 min'])
  })

  it('renews a lease, with and without a new ttl', async () => {
    const relay = fakeRelay([{ body: LEASE }])
    const io1 = io()
    expect(await runLease(['renew', LEASE.id, '--ttl', '300'], { client: client(relay.impl as any), ...io1.deps })).toBe(0)
    expect(relay.calls[0]!.method).toBe('POST')
    expect(relay.calls[0]!.path).toBe(`/v1/leases/${LEASE.id}/renew`)
    expect(relay.calls[0]!.body).toEqual({ ttl_s: 300 })

    expect(await runLease(['renew', LEASE.id], { client: client(relay.impl as any), ...io1.deps })).toBe(0)
    expect(relay.calls[1]!.body).toEqual({})
    expect(io1.out).toEqual([
      'lease_01ARZ3NDEKTSV4RRFFQ69G5FAV  expires 2026-01-01T00:10:00.000Z',
      'lease_01ARZ3NDEKTSV4RRFFQ69G5FAV  expires 2026-01-01T00:10:00.000Z',
    ])
  })

  it('releases a lease', async () => {
    const relay = fakeRelay([{ body: { ok: true } }])
    const io1 = io()
    const code = await runLease(['release', LEASE.id], { client: client(relay.impl as any), ...io1.deps })

    expect(code).toBe(0)
    expect(relay.calls[0]!.method).toBe('DELETE')
    expect(relay.calls[0]!.path).toBe(`/v1/leases/${LEASE.id}`)
    expect(io1.out).toEqual([`released ${LEASE.id}`])
  })

  it('refuses a bad lease command without calling the relay', async () => {
    const relay = fakeRelay([{ body: [] }])
    const io1 = io()
    expect(await runLease(['acquire', 'deploy/site'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(await runLease(['renew'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(await runLease(['release'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(await runLease(['nope'], { client: client(relay.impl as any), ...io1.deps })).toBe(2)
    expect(relay.calls).toHaveLength(0)
    expect(io1.err).toHaveLength(4)
    expect(io1.err[0]).toContain('usage: mesh lease')
  })
})

describe('the ledger client without an injected one', () => {
  it('uses the config file, the token file and the session from the environment', async () => {
    const home = mkdtempSync(join(tmpdir(), 'mesh-ledger-'))
    writeFileSync(join(home, 'config.json'), JSON.stringify({ relay_url: 'https://relay.local', token_path: join(home, 'token') }))
    writeFileSync(join(home, 'token'), 'file-token\n')
    process.env.MESH_HOME = home
    process.env.MESH_SESSION_ID = 's_fromenvironment'

    const calls: Call[] = []
    vi.stubGlobal('fetch', async (url: string | URL, init: RequestInit = {}) => {
      const u = new URL(String(url))
      calls.push({
        method: (init.method ?? 'GET').toUpperCase(),
        origin: u.origin,
        path: u.pathname,
        query: u.search,
        body: undefined,
        headers: (init.headers ?? {}) as Record<string, string>,
      })
      return new Response(JSON.stringify([]), { status: 200, headers: { 'content-type': 'application/json' } })
    })

    const io1 = io()
    const code = await runMachine(['list'], io1.deps)
    expect(code).toBe(0)
    expect(calls[0]!.origin).toBe('https://relay.local')
    expect(calls[0]!.path).toBe('/v1/machines')
    expect(String(calls[0]!.headers.authorization)).toContain('file-token')
    expect(calls[0]!.headers['x-mesh-session']).toBe('s_fromenvironment')
  })

  it('takes the relay and the session from the flags', async () => {
    const calls: Call[] = []
    vi.stubGlobal('fetch', async (url: string | URL, init: RequestInit = {}) => {
      const u = new URL(String(url))
      calls.push({
        method: (init.method ?? 'GET').toUpperCase(),
        origin: u.origin,
        path: u.pathname,
        query: u.search,
        body: undefined,
        headers: (init.headers ?? {}) as Record<string, string>,
      })
      return new Response(JSON.stringify([]), { status: 200, headers: { 'content-type': 'application/json' } })
    })

    const io1 = io()
    const home = mkdtempSync(join(tmpdir(), 'mesh-ledger-'))
    writeFileSync(join(home, 'config.json'), JSON.stringify({ relay_url: 'https://relay.local', token_path: join(home, 'token') }))
    writeFileSync(join(home, 'token'), 'file-token\n')
    process.env.MESH_HOME = home
    delete process.env.MESH_SESSION_ID

    const code = await runMachine(['list', '--relay', 'https://other.relay', '--session', 's_flagged'], io1.deps)
    expect(code).toBe(0)
    expect(calls[0]!.origin).toBe('https://other.relay')
    expect(calls[0]!.headers['x-mesh-session']).toBe('s_flagged')
  })
})
