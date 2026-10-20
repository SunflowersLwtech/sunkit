import { describe, it, expect } from 'vitest'
import {
  ArtifactSchema, CardPatchSchema, CommandRequestSchema, LeaseNameSchema, MachineReportSchema,
  TaskStateSchema, WorkgroupSchema, isTerminalTaskState, newCommandId, newLeaseId, newTaskId,
  redactUrlCredentials, isValidTaskId,
} from './ledger.ts'

describe('task state', () => {
  it('uses the A2A TaskState names, lowercased', () => {
    for (const s of ['submitted', 'working', 'input_required', 'auth_required', 'completed', 'failed', 'canceled', 'rejected']) {
      expect(TaskStateSchema.safeParse(s).success).toBe(true)
    }
    expect(TaskStateSchema.safeParse('stale').success).toBe(false)
    expect(TaskStateSchema.safeParse('idle').success).toBe(false)
  })

  it('treats completed/failed/canceled/rejected as terminal and nothing else', () => {
    expect(['completed', 'failed', 'canceled', 'rejected'].every(s => isTerminalTaskState(s as never))).toBe(true)
    expect(['submitted', 'working', 'input_required', 'auth_required'].some(s => isTerminalTaskState(s as never))).toBe(false)
  })
})

describe('ids', () => {
  it('mints prefixed, monotonic ULIDs', () => {
    const a = newTaskId(); const b = newTaskId()
    expect(a).toMatch(/^task_[0-9A-HJKMNP-TV-Z]{26}$/)
    expect(a < b).toBe(true)
    expect(isValidTaskId(a)).toBe(true)
    expect(isValidTaskId('task_x')).toBe(false)
    expect(newLeaseId()).toMatch(/^lease_[0-9A-HJKMNP-TV-Z]{26}$/)
    expect(newCommandId()).toMatch(/^cmd_[0-9A-HJKMNP-TV-Z]{26}$/)
  })
})

describe('workgroup', () => {
  it('accepts short lowercase names only', () => {
    expect(WorkgroupSchema.safeParse('liuwei').success).toBe(true)
    expect(WorkgroupSchema.safeParse('team').success).toBe(true)
    expect(WorkgroupSchema.safeParse('Team').success).toBe(false)
    expect(WorkgroupSchema.safeParse('a'.repeat(33)).success).toBe(false)
    expect(WorkgroupSchema.safeParse('').success).toBe(false)
  })
})

describe('card patch (session self-update) is a fixed whitelist', () => {
  it('accepts the five card fields plus the existing ones', () => {
    const r = CardPatchSchema.safeParse({
      session: 's_01hrk7y0000000000000aaaaaa', name: 'fr-inkrec', status: 'busy',
      agent: 'claude', model: 'deepseek/deepseek-v4.1-flash', repo: 'foldrender', branch: 'feat/ink-recognize',
      herdr: { machine: 'm4', tab: 'wC:t4Y', pane: 'wC:p54' }, task_id: newTaskId(), source: 'hook',
    })
    expect(r.success).toBe(true)
  })

  it('accepts real model ids with a context suffix or a :free tag', () => {
    for (const m of ['claude-opus-5-5[1m]', 'minimax/minimax-m3.1-flash:free', 'gemini-4-argon-medium']) {
      expect(CardPatchSchema.safeParse({ session: 's_01hrk7y0000000000000aaaaaa', model: m }).success).toBe(true)
    }
  })

  it('rejects fields the server owns (role, workgroup is checked separately, dispatched_by) and any free map', () => {
    const base = { session: 's_01hrk7y0000000000000aaaaaa' }
    expect(CardPatchSchema.safeParse({ ...base, role: 'orchestrator' }).success).toBe(false)
    expect(CardPatchSchema.safeParse({ ...base, dispatched_by: 'feishu-assistant' }).success).toBe(false)
    expect(CardPatchSchema.safeParse({ ...base, extra: { token: 'x' } }).success).toBe(false)
    expect(CardPatchSchema.safeParse({ ...base, herdr: { machine: 'm4', env: 'X=1' } }).success).toBe(false)
  })

  it('rejects an unknown agent kind and malformed herdr ids', () => {
    const base = { session: 's_01hrk7y0000000000000aaaaaa' }
    expect(CardPatchSchema.safeParse({ ...base, agent: 'bash' }).success).toBe(false)
    expect(CardPatchSchema.safeParse({ ...base, herdr: { machine: 'm4', pane: 'p54; rm -rf /' } }).success).toBe(false)
    expect(CardPatchSchema.safeParse({ ...base, herdr: { machine: 'M4!' } }).success).toBe(false)
  })

  it('rejects branch/repo values that carry a URL with credentials or spaces', () => {
    const base = { session: 's_01hrk7y0000000000000aaaaaa' }
    expect(CardPatchSchema.safeParse({ ...base, repo: 'https://tok@github.com/x/y' }).success).toBe(false)
    expect(CardPatchSchema.safeParse({ ...base, branch: 'feat/x y' }).success).toBe(false)
    expect(CardPatchSchema.safeParse({ ...base, branch: 'feat/user_auth' }).success).toBe(true)
  })
})

describe('redactUrlCredentials', () => {
  it('drops userinfo and query from URL-looking values and leaves paths alone', () => {
    expect(redactUrlCredentials('https://ghp_abc@github.com/x/y?token=1#f')).toBe('https://github.com/x/y')
    expect(redactUrlCredentials('/Users/user_foo/Developer/x')).toBe('/Users/user_foo/Developer/x')
    expect(redactUrlCredentials('C:\\Users\\x')).toBe('C:\\Users\\x')
  })
})

describe('artifacts', () => {
  it('accepts https links, gh:// refs, vault-relative paths and version@time deploys', () => {
    expect(ArtifactSchema.safeParse({ type: 'pr', ref: 'https://github.com/o/r/pull/71' }).success).toBe(true)
    expect(ArtifactSchema.safeParse({ type: 'pr', ref: 'gh://o/r/pull/71' }).success).toBe(true)
    expect(ArtifactSchema.safeParse({ type: 'vault', ref: 'Memory/obsun/mesh-a2a-design-2026-10-19.md' }).success).toBe(true)
    expect(ArtifactSchema.safeParse({ type: 'deploy', ref: 'relay-5fd1a08@2026-10-20T10:00:00Z' }).success).toBe(true)
  })

  it('rejects credentials, other schemes, absolute or escaping vault paths', () => {
    expect(ArtifactSchema.safeParse({ type: 'url', ref: 'https://user:pw@example.com/x' }).success).toBe(false)
    expect(ArtifactSchema.safeParse({ type: 'url', ref: 'http://example.com/x' }).success).toBe(false)
    expect(ArtifactSchema.safeParse({ type: 'url', ref: 'javascript:alert(1)' }).success).toBe(false)
    expect(ArtifactSchema.safeParse({ type: 'url', ref: 'file:///etc/passwd' }).success).toBe(false)
    expect(ArtifactSchema.safeParse({ type: 'vault', ref: '/etc/passwd' }).success).toBe(false)
    expect(ArtifactSchema.safeParse({ type: 'vault', ref: 'Memory/../../.ssh/id_ed25519' }).success).toBe(false)
    expect(ArtifactSchema.safeParse({ type: 'deploy', ref: 'v1 && curl x' }).success).toBe(false)
    expect(ArtifactSchema.safeParse({ type: 'pr', ref: 'https://github.com/o/r/pull/71', secret: 'x' }).success).toBe(false)
  })
})

describe('lease names', () => {
  it('accepts the documented namespaces only', () => {
    for (const n of ['deploy/foldrender', 'repo/sunkit', 'file/0123456789ab', 'device/fold7', 'build/m4', 'cred/infra-creds']) {
      expect(LeaseNameSchema.safeParse(n).success).toBe(true)
    }
    for (const n of ['deploy/', 'misc/x', 'deploy/a/b', 'deploy/../x', 'Deploy/x', 'deploy/x y']) {
      expect(LeaseNameSchema.safeParse(n).success).toBe(false)
    }
  })
})

describe('machine report', () => {
  const report = {
    version: '0.1.0',
    herdr: { ok: true, version: '0.9.5' },
    load: { load1: 1.5, cpus: 8 },
    kinds: [{ kind: 'claude', version: '2.1.300' }, { kind: 'pi' }],
    seats: [{ email: 'weiliu@duocodetech.com', plan: 'team', five_hour_pct: 26, resets_at: '2026-10-20T01:59:59Z', blocked: false }],
    active: 2, blocked: 0, max_active: 3,
    agents: [{
      name: 'mesh-a2a', agent: 'claude', status: 'working', pane: 'w4:p1R', tab: 'w4:t1R', workspace: 'w4', cwd: '/home/sunfl',
      agent_session: { kind: 'path', value: '/home/sunfl/.pi/agent/sessions/x.jsonl' },
    }],
    roots: [{ path: '~/Developer/products', exists: true }],
  }

  it('accepts a full report', () => {
    expect(MachineReportSchema.safeParse(report).success).toBe(true)
  })

  it('rejects free-form extras and oversize lists', () => {
    expect(MachineReportSchema.safeParse({ ...report, env: { AWS_SECRET: 'x' } }).success).toBe(false)
    expect(MachineReportSchema.safeParse({ ...report, agents: Array(65).fill(report.agents[0]) }).success).toBe(false)
    expect(MachineReportSchema.safeParse({ ...report, agents: [{ ...report.agents[0], screen: 'x' }] }).success).toBe(false)
  })

  it('keeps an unknown herdr agent label instead of failing the whole report', () => {
    const r = MachineReportSchema.safeParse({ ...report, agents: [{ ...report.agents[0], agent: 'codex' }] })
    expect(r.success).toBe(true)
  })
})

describe('command request', () => {
  it('allows only read-only ops with bounded args', () => {
    expect(CommandRequestSchema.safeParse({ op: 'probe' }).success).toBe(true)
    expect(CommandRequestSchema.safeParse({ op: 'read', args: { pane: 'w4:p1R', lines: 80 } }).success).toBe(true)
    expect(CommandRequestSchema.safeParse({ op: 'spawn', args: {} }).success).toBe(false)
    expect(CommandRequestSchema.safeParse({ op: 'read', args: { pane: 'w4:p1R', lines: 5000 } }).success).toBe(false)
    expect(CommandRequestSchema.safeParse({ op: 'read', args: { pane: 'w4:p1R; id' } }).success).toBe(false)
    expect(CommandRequestSchema.safeParse({ op: 'read', args: { pane: 'w4:p1R', cmd: 'id' } }).success).toBe(false)
  })
})
