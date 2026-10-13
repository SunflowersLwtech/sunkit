import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mkdtempSync, rmSync, readFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { runPair } from './pair.ts'

let workdir = ''
beforeEach(() => { workdir = mkdtempSync(join(tmpdir(), 'mesh-pair-')) })
afterEach(() => { rmSync(workdir, { recursive: true, force: true }) })

describe('runPair', () => {
  it('POSTs the pair code to the relay and writes token + config', async () => {
    const fakeFetch = vi.fn(async () => new Response(JSON.stringify({
      token: 'A'.repeat(43),
      human: { handle: 'bob', display_name: 'Bob' },
      team: { id: 't1', name: 'acme' }
    }), { status: 200 }))
    await runPair({
      relayUrl: 'https://mesh.example',
      pairCode: 'MESH-XXXX-XXXX-XXXX',
      deviceLabel: 'laptop',
      home: workdir,
      fetch: fakeFetch as any
    })
    expect(existsSync(join(workdir, '.claude-mesh/token'))).toBe(true)
    expect(readFileSync(join(workdir, '.claude-mesh/token'), 'utf8')).toBe('A'.repeat(43))
    const cfg = JSON.parse(readFileSync(join(workdir, '.claude-mesh/config.json'), 'utf8'))
    expect(cfg.relay_url).toBe('https://mesh.example')
    expect(cfg.token_path).toContain('.claude-mesh')
    expect(cfg.permission_relay.enabled).toBe(false)
  })

  it('throws on non-200 from relay', async () => {
    const fakeFetch = vi.fn(async () =>
      new Response(JSON.stringify({ error: 'code_expired' }), { status: 400 }))
    await expect(runPair({
      relayUrl: 'https://mesh.example', pairCode: 'MESH-X', deviceLabel: 'l',
      home: workdir, fetch: fakeFetch as any
    })).rejects.toThrow(/code_expired/)
  })
})
