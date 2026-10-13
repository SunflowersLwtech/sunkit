import { describe, it, expect, beforeEach } from 'vitest'
import { PermissionTracker } from './permission.ts'

describe('PermissionTracker', () => {
  let t: PermissionTracker
  beforeEach(() => { t = new PermissionTracker({ ttlMs: 1000 }) })

  it('records an incoming request_id with the msg_id that carried it', () => {
    t.recordIncoming('abcde', 'msg_01HR0000000000000000000001')
    expect(t.msgIdFor('abcde')).toBe('msg_01HR0000000000000000000001')
  })

  it('drops entries after ttl', async () => {
    const t2 = new PermissionTracker({ ttlMs: 10 })
    t2.recordIncoming('abcde', 'msg_x')
    await new Promise(r => setTimeout(r, 30))
    expect(t2.msgIdFor('abcde')).toBeUndefined()
  })

  it('returns undefined for unknown request_id', () => {
    expect(t.msgIdFor('xxxxx')).toBeUndefined()
  })
})
