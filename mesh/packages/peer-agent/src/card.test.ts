import { describe, it, expect } from 'vitest'
import { CardWriter, initialCard } from './card.ts'

const TASK = 'task_01HRK7Y0000000000000000000'

describe('initialCard', () => {
  it('describes a Claude Code session inside Herdr on a known machine, in a git checkout, working on a task', () => {
    const git = (args: string[]) => (args.includes('--show-toplevel') ? '/home/u/Developer/products/foldrender\n' : 'feat/ink\n')
    const card = initialCard({
      env: { HERDR_ENV: '1', HERDR_PANE_ID: 'w4:p1R', HERDR_TAB_ID: 'w4:t1R', MESH_TASK_ID: TASK, MESH_MODEL: 'claude-opus-5-5' },
      host: undefined, machine: 'aws-sin-8c32g-261016', git,
    })
    expect(card).toEqual({
      agent: 'claude', model: 'claude-opus-5-5', repo: 'foldrender', branch: 'feat/ink',
      herdr: { machine: 'aws-sin-8c32g-261016', tab: 'w4:t1R', pane: 'w4:p1R' }, task_id: TASK,
    })
  })

  it('takes the host kind from MESH_HOST and leaves out what it cannot vouch for', () => {
    const card = initialCard({ env: { HERDR_ENV: '1', HERDR_PANE_ID: 'w4:p1R', MESH_TASK_ID: 'nope' }, host: 'grok', machine: undefined, git: () => undefined })
    expect(card).toEqual({ agent: 'grok' })
  })

  it('drops values that do not fit the relay\'s fixed fields', () => {
    const git = (args: string[]) => (args.includes('--show-toplevel') ? '/x/has space\n' : 'feat/x..y\n')
    const card = initialCard({ env: { MESH_MODEL: 'model with spaces' }, host: 'unknown-host', machine: 'M4!', git })
    expect(card).toEqual({})
  })
})

describe('CardWriter', () => {
  function rig() {
    const sent: Array<Record<string, unknown>> = []
    let timer: (() => void) | null = null
    const w = new CardWriter(async p => { sent.push(p) }, { delayMs: 2_000, schedule: (fn) => { timer = fn; return () => { timer = null } } })
    return { w, sent, fire: async () => { const t = timer; timer = null; t?.(); await new Promise(r => setImmediate(r)) } }
  }

  it('batches changes into one write and sends only what changed', async () => {
    const r = rig()
    r.w.set({ agent: 'claude', repo: 'sunkit' })
    r.w.set({ branch: 'main' })
    expect(r.sent).toEqual([])
    await r.fire()
    expect(r.sent).toEqual([{ agent: 'claude', repo: 'sunkit', branch: 'main' }])
    r.w.set({ repo: 'sunkit', branch: 'main' })
    await r.fire()
    expect(r.sent).toHaveLength(1)
    r.w.set({ branch: 'feat/x' })
    await r.fire()
    expect(r.sent[1]).toEqual({ branch: 'feat/x' })
  })

  it('sends the whole card again after the relay forgot it (a reconnect)', async () => {
    const r = rig()
    r.w.set({ agent: 'pi', model: 'm' })
    await r.fire()
    r.w.resend()
    await r.fire()
    expect(r.sent[1]).toEqual({ agent: 'pi', model: 'm' })
  })

  it('keeps unsent fields when a write fails and tries them again', async () => {
    const sent: Array<Record<string, unknown>> = []
    let fail = true
    let timer: (() => void) | null = null
    const w = new CardWriter(async p => { if (fail) throw new Error('relay down'); sent.push(p) }, { delayMs: 10, schedule: fn => { timer = fn; return () => { timer = null } } })
    w.set({ repo: 'a' })
    timer!(); await new Promise(r => setImmediate(r))
    fail = false
    expect(timer).not.toBeNull()
    timer!(); await new Promise(r => setImmediate(r))
    expect(sent).toEqual([{ repo: 'a' }])
  })

  it('writes nothing when disabled (MESH_CARD_WRITE=0)', async () => {
    const sent: unknown[] = []
    const w = new CardWriter(async p => { sent.push(p) }, { delayMs: 0, enabled: false })
    w.set({ agent: 'claude' })
    await w.flush()
    expect(sent).toEqual([])
  })
})
