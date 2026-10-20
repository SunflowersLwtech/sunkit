import { describe, it, expect } from 'vitest'
import { MachineReportSchema } from '@claude-mesh/shared'
import { Meshd, type MeshdOpts, type RunResult } from './daemon.ts'

interface Call { url: string; method: string; body?: unknown; headers: Record<string, string> }

function harness(opts: { run?: (file: string, args: string[]) => RunResult; streams?: string[][]; reportStatus?: number } = {}) {
  const calls: Call[] = []
  const runs: Array<{ file: string; args: string[] }> = []
  const logs: Array<{ event: string; fields?: Record<string, unknown> }> = []
  const streams = [...(opts.streams ?? [])]
  let meshd: Meshd
  const fetch = (async (input: URL | string, init: RequestInit = {}) => {
    const url = String(input)
    calls.push({ url, method: init.method ?? 'GET', headers: init.headers as Record<string, string>, ...(init.body ? { body: JSON.parse(String(init.body)) } : {}) })
    if (url.endsWith('/v1/machines/self/stream')) {
      const chunks = streams.shift()
      if (!chunks) { meshd.stop(); throw new Error('no more streams') }
      const body = new ReadableStream<Uint8Array>({
        start(c) { for (const ch of chunks) c.enqueue(new TextEncoder().encode(ch)); c.close() },
      })
      return new Response(body, { status: 200 })
    }
    if (url.endsWith('/v1/machines/self')) return new Response('{"ok":true}', { status: opts.reportStatus ?? 200 })
    if (url.includes('/v1/commands/')) return new Response('{"ok":true}', { status: 200 })
    return new Response('{}', { status: 404 })
  }) as typeof globalThis.fetch
  const run = async (file: string, args: string[]): Promise<RunResult> => {
    runs.push({ file, args })
    if (opts.run) return opts.run(file, args)
    if (args[0] === 'agent' && args[1] === 'list') {
      return { ok: true, stdout: JSON.stringify({ result: { agents: [{ agent: 'claude', agent_status: 'working', name: 'w1', pane_id: 'w4:p1', tab_id: 'w4:t1', workspace_id: 'w4' }] } }) }
    }
    if (args[0] === 'agent' && args[1] === 'read') return { ok: true, stdout: 'line 1\nline 2\n' }
    if (args[0] === '--version') return file === 'claude' ? { ok: true, stdout: '2.1.304 (Claude Code)\n' } : file === 'herdr' ? { ok: true, stdout: 'herdr 0.9.5\n' } : { ok: false, stdout: '', error: 'ENOENT' }
    if (file.endsWith('cc-quota')) return { ok: true, stdout: JSON.stringify({ accounts: [{ email: 'a@b.c', subscription: 'team', five_hour: { pct: 12 } }] }) }
    return { ok: false, stdout: '', error: 'unexpected' }
  }
  const o: MeshdOpts = {
    relayUrl: 'http://relay.test', token: 'T'.repeat(43), herdrBin: 'herdr', ccQuota: '/x/cc-quota', ccQuotaArgs: ['--json'], maxActive: 3,
    roots: [{ path: '~/Developer/products', exists: () => true }],
    load: () => ({ load1: 0.5, cpus: 8 }),
    run: (f, a) => run(f, a), fetch, sleep: async () => {}, log: (_l, event, fields) => { logs.push({ event, ...(fields ? { fields } : {}) }) },
  }
  meshd = new Meshd(o)
  return { meshd, calls, runs, logs }
}

describe('meshd reports', () => {
  it('posts a report the relay schema accepts, built from herdr, the agents installed and cc-quota', async () => {
    const h = harness()
    expect(await h.meshd.report()).toBe(200)
    const post = h.calls.find(c => c.url.endsWith('/v1/machines/self'))!
    expect(post.method).toBe('POST')
    expect(post.headers.authorization).toBe(`Bearer ${'T'.repeat(43)}`)
    expect(MachineReportSchema.safeParse(post.body).success).toBe(true)
    expect(post.body).toMatchObject({
      herdr: { ok: true, version: '0.9.5' }, kinds: [{ kind: 'claude', version: '2.1.304 (Claude Code)' }],
      seats: [{ email: 'a@b.c', five_hour_pct: 12 }], active: 1, max_active: 3, agents: [{ name: 'w1', pane: 'w4:p1' }],
    })
  })

  it('caches the agent versions and seats between reports', async () => {
    const h = harness()
    await h.meshd.report()
    await h.meshd.report()
    expect(h.runs.filter(r => r.file === 'claude').length).toBe(1)
    expect(h.runs.filter(r => r.file.endsWith('cc-quota')).length).toBe(1)
    expect(h.runs.filter(r => r.args[1] === 'list').length).toBe(2)
  })

  it('still reports when herdr is down, saying so', async () => {
    const h = harness({ run: (f, a) => (f === 'herdr' ? { ok: false, stdout: '', error: 'server not running' } : { ok: false, stdout: '' }) })
    await h.meshd.report()
    const post = h.calls.find(c => c.url.endsWith('/v1/machines/self'))!
    expect(post.body).toMatchObject({ herdr: { ok: false, error: 'server not running' }, agents: [] })
  })
})

describe('meshd commands', () => {
  it('reads a pane with a fixed argv', async () => {
    const h = harness()
    expect(await h.meshd.execute({ op: 'read', args: { pane: 'w4:p1', lines: 40 } })).toEqual({ ok: true, output: 'line 1\nline 2\n' })
    expect(h.runs.at(-1)).toEqual({ file: 'herdr', args: ['agent', 'read', 'w4:p1', '--source', 'recent', '--lines', '40'] })
  })

  it('refuses anything that is not a valid read-only command, without running anything', async () => {
    const h = harness()
    for (const c of [{ op: 'read', args: { pane: 'w4:p1; id' } }, { op: 'spawn', args: {} }, { op: 'read', args: { pane: 'w4:p1', extra: 1 } }, null]) {
      expect(await h.meshd.execute(c)).toEqual({ ok: false, error: 'invalid command' })
    }
    expect(h.runs).toEqual([])
  })

  it('keeps the end of a long screen', async () => {
    const h = harness({ run: () => ({ ok: true, stdout: 'x'.repeat(70_000) + 'END' }) })
    const r = await h.meshd.execute({ op: 'read', args: { pane: 'w4:p1' } })
    expect(r.output!.length).toBe(60_000)
    expect(r.output!.endsWith('END')).toBe(true)
  })

  it('probe sends a fresh report and answers with a summary', async () => {
    const h = harness()
    const r = await h.meshd.execute({ op: 'probe' })
    expect(r).toEqual({ ok: true, output: JSON.stringify({ herdr: true, agents: 1, active: 1, blocked: 0 }) })
    expect(h.calls.filter(c => c.url.endsWith('/v1/machines/self'))).toHaveLength(1)
  })

  it('takes commands from the executor stream, answers each once, and reconnects after a drop', async () => {
    const h = harness({
      streams: [
        ['event: ping\ndata: 1\n\n', 'event: command\ndata: {"id":"cmd_1","op":"read","args":{"pane":"w4:p1"}}\n\n'],
        ['event: command\ndata: {"id":"cmd_2","op":"probe"}\n\n', 'event: message\ndata: {"id":"cmd_x","op":"read"}\n\n'],
      ],
    })
    await h.meshd.streamLoop()
    await new Promise(r => setTimeout(r, 20))
    const results = h.calls.filter(c => c.url.includes('/v1/commands/'))
    expect(results.map(c => c.url)).toEqual(['http://relay.test/v1/commands/cmd_1/result', 'http://relay.test/v1/commands/cmd_2/result'])
    expect(results[0]!.body).toEqual({ ok: true, output: 'line 1\nline 2\n' })
    expect(h.calls.filter(c => c.url.endsWith('/stream'))).toHaveLength(3)
  })
})

describe('meshd after review', () => {
  it('does not hammer a relay whose stream answers 200 and closes at once: the backoff keeps growing', async () => {
    const sleeps: number[] = []
    const h = harness({ streams: [[], [], [], [], []] })
    ;(h.meshd as unknown as { sleep: (ms: number) => Promise<void> }).sleep = async ms => { sleeps.push(ms) }
    await h.meshd.streamLoop()
    expect(sleeps.slice(0, 4)).toEqual([500, 1000, 2000, 4000])
  })

  it('drops the field or entry the relay would refuse instead of losing the whole report', async () => {
    const h = harness({
      run: (file, args) => {
        if (args[0] === 'agent' && args[1] === 'list') return { ok: true, stdout: JSON.stringify({ result: { agents: [{ agent: 'claude', agent_status: 'idle', name: 'ok', pane_id: 'w4:p1' }] } }) }
        return { ok: false, stdout: '' }
      },
    })
    ;(h.meshd as unknown as { o: { maxActive: number } }).o.maxActive = 5000
    expect(await h.meshd.report()).toBe(200)
    const post = h.calls.find(c => c.url.endsWith('/v1/machines/self'))!
    expect(MachineReportSchema.safeParse(post.body).success).toBe(true)
    expect(post.body).not.toHaveProperty('max_active')
    expect(post.body).toMatchObject({ agents: [{ name: 'ok' }] })
  })

  it('a probe that meets the relay\'s report limit waits and tries once more', async () => {
    let n = 0
    const h = harness()
    const orig = (h.meshd as unknown as { o: { fetch: typeof fetch } }).o.fetch
    ;(h.meshd as unknown as { o: { fetch: typeof fetch } }).o.fetch = (async (u: URL | string, init?: RequestInit) => {
      if (String(u).endsWith('/v1/machines/self') && n++ === 0) return new Response('{"error":"rate_limited"}', { status: 429, headers: { 'retry-after': '1' } })
      return orig(u, init)
    }) as typeof fetch
    const r = await h.meshd.execute({ op: 'probe' })
    expect(r.ok).toBe(true)
    expect(n).toBe(2)
  })
})
