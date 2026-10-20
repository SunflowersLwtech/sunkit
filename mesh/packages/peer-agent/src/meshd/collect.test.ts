import { describe, it, expect } from 'vitest'
import { MachineReportSchema } from '@claude-mesh/shared'
import { buildReport, cleanVersion, parseCcQuota, parseHerdrAgents } from './collect.ts'

// Shapes copied from herdr 0.9.5 `agent list` and cc-quota --json output.
const herdrList = {
  id: 'cli:agent:list',
  result: {
    type: 'agent_list',
    agents: [
      { agent: 'claude', agent_status: 'working', cwd: '/home/u', name: 'mesh-a2a', pane_id: 'w4:p1R', tab_id: 'w4:t1R', workspace_id: 'w4', terminal_title_stripped: 'mesh-a2a' },
      {
        agent: 'pi', agent_status: 'idle', cwd: '/home/u/Developer/products', name: 'pi-free-rev-a', pane_id: 'w4:p1N', tab_id: 'w4:t1N', workspace_id: 'w4',
        agent_session: { agent: 'pi', kind: 'path', source: 'herdr:pi', value: '/home/u/.pi/agent/sessions/x/2026.jsonl' },
      },
      { agent: 'claude', agent_status: 'blocked', pane_id: 'w4:p2', terminal_title_stripped: 'untitled' },
      { agent: 'claude', agent_status: 'working', name: 'no-pane' },
      { agent: 'claude', agent_status: 'idle' },
      { agent: 'claude', agent_status: 'waiting-for-something-new', name: 'odd', pane_id: 'w4:p3' },
      { agent: 'claude', agent_status: 'idle', name: 'bad pane', pane_id: 'p9; rm -rf /' },
    ],
  },
}

describe('parseHerdrAgents', () => {
  it('maps herdr agents to report agents, keeping the resume handle herdr already knows', () => {
    const agents = parseHerdrAgents(herdrList)
    expect(agents.map(a => a.name)).toEqual(['mesh-a2a', 'pi-free-rev-a', 'untitled', 'odd'])
    expect(agents[1]).toMatchObject({ agent: 'pi', status: 'idle', pane: 'w4:p1N', agent_session: { kind: 'path', value: '/home/u/.pi/agent/sessions/x/2026.jsonl' } })
    expect(agents[2]).toMatchObject({ status: 'blocked', pane: 'w4:p2' })
  })

  it('turns a status it does not know into unknown instead of dropping the agent', () => {
    expect(parseHerdrAgents(herdrList).find(a => a.name === 'odd')?.status).toBe('unknown')
  })

  it('returns nothing for output it cannot read', () => {
    expect(parseHerdrAgents(null)).toEqual([])
    expect(parseHerdrAgents({ result: { agents: 'x' } })).toEqual([])
    expect(parseHerdrAgents({ error: 'server not running' })).toEqual([])
  })
})

describe('parseCcQuota', () => {
  it('reads seats with their five-hour usage', () => {
    const seats = parseCcQuota({
      host: 'h', accounts: [
        { config_dir: '~/.claude', email: 'weiliu@duocodetech.com', org_name: 'DuoCode', subscription: 'team', five_hour: { pct: 26, resets_at: '2026-10-20T01:59:59Z' }, blocked: [] },
        { config_dir: '~/.claude-max', email: 'x@y.z', subscription: 'max', five_hour: { pct: 99 }, blocked: ['opus'] },
        { email: 'not an email' },
      ],
    })
    expect(seats).toEqual([
      { email: 'weiliu@duocodetech.com', org: 'DuoCode', plan: 'team', five_hour_pct: 26, resets_at: '2026-10-20T01:59:59.000Z', blocked: false },
      { email: 'x@y.z', plan: 'max', five_hour_pct: 99, blocked: true },
    ])
  })

  it('is empty when cc-quota printed nothing usable', () => {
    expect(parseCcQuota(undefined)).toEqual([])
    expect(parseCcQuota({ accounts: null })).toEqual([])
  })
})

describe('cleanVersion', () => {
  it('keeps the first line, in the characters the relay accepts', () => {
    expect(cleanVersion('2.1.304 (Claude Code)\n')).toBe('2.1.304 (Claude Code)')
    expect(cleanVersion('herdr 0.9.5')).toBe('herdr 0.9.5')
    expect(cleanVersion('\n\n')).toBeUndefined()
    expect(cleanVersion('v1.2 <script>')).toBe('v1.2 script')
  })
})

describe('buildReport', () => {
  it('produces a report the relay accepts, counting working and blocked agents', () => {
    const agents = parseHerdrAgents(herdrList)
    const r = buildReport({
      version: '0.1.0', herdr: { ok: true, version: '0.9.5' }, agents,
      kinds: [{ kind: 'claude', version: '2.1.304 (Claude Code)' }, { kind: 'pi', version: '1.3.0' }],
      seats: [], load1: 1.234, cpus: 8, memUsedPct: 41.6, maxActive: 3,
      roots: [{ path: '~/Developer/products', exists: true }],
    })
    expect(MachineReportSchema.safeParse(r).success).toBe(true)
    expect(r).toMatchObject({ active: 1, blocked: 1, max_active: 3, load: { load1: 1.23, cpus: 8, mem_used_pct: 42 } })
  })

  it('still produces a valid report when herdr is down', () => {
    const r = buildReport({
      version: '0.1.0', herdr: { ok: false, error: 'connect ENOENT /run/herdr.sock '.repeat(20) }, agents: [],
      kinds: [], seats: [], load1: 0, cpus: 2, roots: [],
    })
    expect(MachineReportSchema.safeParse(r).success).toBe(true)
    expect(r.herdr.error!.length).toBeLessThanOrEqual(200)
  })
})
