import { describe, it, expect } from 'vitest'
import { TaskDriver, type TaskApi } from './task-driver.ts'

const ID = 'task_01HRK7Y0000000000000000000'
const ME = 's_01hrk7y0000000000000aaaaa1'

function api(initial: { state: string; session: string | null }) {
  const calls: string[] = []
  let state = initial.state
  let session = initial.session
  const a: TaskApi = {
    async get() { calls.push('get'); return { status: 200, task: { state, assignee: { session } } } },
    async patch(_id, body) {
      calls.push(`patch:${body.state}`)
      if (['completed', 'failed', 'canceled', 'rejected'].includes(state)) return { status: 409, error: 'task_terminal' }
      state = body.state
      return { status: 200 }
    },
    async rebind() { calls.push('rebind'); session = ME; return { status: 200 } },
  }
  return { a, calls, get state() { return state } }
}

describe('TaskDriver', () => {
  it('moves a dispatched task to working on the first turn and to input_required while blocked', async () => {
    const r = api({ state: 'submitted', session: ME })
    const d = new TaskDriver(r.a, ID, ME)
    await d.start()
    await d.on('turn')
    await d.on('tool')
    await d.on('turn')
    expect(r.state).toBe('working')
    await d.on('blocked')
    expect(r.state).toBe('input_required')
    await d.on('stop')
    expect(r.state).toBe('working')
    // A turn ending never completes the task: that needs an explicit done.
    await d.on('idle')
    expect(r.state).toBe('working')
    expect(r.calls.filter(c => c.startsWith('patch'))).toEqual(['patch:working', 'patch:input_required', 'patch:working'])
  })

  it('a turn that ended on its own starts a dispatched task even when the start of that turn was missed', async () => {
    // A host that starts its MCP servers with the first prompt (Grok Build 1.0.62) runs that
    // prompt's hook before the peer listens: the first thing the peer hears is the turn ending.
    const r = api({ state: 'submitted', session: ME })
    const d = new TaskDriver(r.a, ID, ME)
    await d.start()
    await d.on('done')
    expect(r.state).toBe('working')
    await d.on('blocked')
    await d.on('done')
    expect(r.state).toBe('working')
    expect(r.calls.filter(c => c.startsWith('patch'))).toEqual(['patch:working', 'patch:input_required', 'patch:working'])
  })

  it('a session that starts, is interrupted or closes before any turn ended leaves a dispatched task submitted', async () => {
    const r = api({ state: 'submitted', session: ME })
    const d = new TaskDriver(r.a, ID, ME)
    await d.start()
    await d.on('idle'); await d.on('stop'); await d.on('end')
    expect(r.state).toBe('submitted')
    expect(r.calls.filter(c => c.startsWith('patch'))).toEqual([])
  })

  it('takes the task over from the session it had before a restart', async () => {
    const r = api({ state: 'working', session: 's_01hrk7y0000000000000old000' })
    const d = new TaskDriver(r.a, ID, ME)
    await d.start()
    expect(r.calls).toEqual(['get', 'rebind'])
  })

  it('leaves a finished task alone, and stops trying once the relay says it is final', async () => {
    const r = api({ state: 'completed', session: ME })
    const d = new TaskDriver(r.a, ID, ME)
    await d.start()
    await d.on('turn')
    await d.on('blocked')
    expect(r.calls).toEqual(['get'])
  })

  it('a relay that is down at start does not stop later updates', async () => {
    let down = true
    const r = api({ state: 'submitted', session: ME })
    const flaky: TaskApi = { ...r.a, get: async () => { if (down) throw new Error('down'); return r.a.get(ID) } }
    const d = new TaskDriver(flaky, ID, ME)
    await d.start()
    down = false
    await d.on('turn')
    expect(r.state).toBe('working')
  })

  it('stops driving a task the relay will not let this session move', async () => {
    const calls: string[] = []
    const a: TaskApi = {
      async get() { calls.push('get'); return { status: 200, task: { state: 'working', assignee: { session: 's_other000000000000000' } } } },
      async patch() { calls.push('patch'); return { status: 403, error: 'not_allowed' } },
      async rebind() { calls.push('rebind'); return { status: 409 } },
    }
    const d = new TaskDriver(a, ID, ME)
    await d.start()
    await d.on('blocked'); await d.on('turn'); await d.on('blocked')
    expect(calls).toEqual(['get', 'rebind'])
  })

  it('a refused update stops further ones', async () => {
    const calls: string[] = []
    const a: TaskApi = {
      async get() { return { status: 200, task: { state: 'submitted', assignee: { session: ME } } } },
      async patch() { calls.push('patch'); return { status: 403, error: 'not_allowed' } },
      async rebind() { return { status: 200 } },
    }
    const d = new TaskDriver(a, ID, ME)
    await d.start()
    await d.on('turn'); await d.on('blocked'); await d.on('turn')
    expect(calls).toEqual(['patch'])
  })
})
