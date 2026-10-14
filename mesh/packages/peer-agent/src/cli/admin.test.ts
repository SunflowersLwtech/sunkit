import { describe, it, expect, vi } from 'vitest'
import { runAdminAddUser } from './admin.ts'

describe('runAdminAddUser', () => {
  it('POSTs to /v1/admin/users with admin bearer and prints pair code', async () => {
    const calls: { url: string; init: RequestInit }[] = []
    const fakeFetch = vi.fn(async (url: string | URL, init: RequestInit) => {
      calls.push({ url: String(url), init })
      return new Response(JSON.stringify({
        handle: 'bob', display_name: 'Bob', tier: 'human',
        pair_code: 'MESH-XXXX-XXXX-XXXX', expires_at: '2026-04-20T00:00:00Z'
      }), { status: 201 })
    })
    const logs: string[] = []
    await runAdminAddUser({
      relayUrl: 'https://mesh.example', adminToken: 'admin-tok',
      handle: 'bob', displayName: 'Bob', tier: 'human',
      fetch: fakeFetch as any, out: s => logs.push(s)
    })
    expect(calls[0]!.url).toContain('/v1/admin/users')
    expect((calls[0]!.init.headers as Record<string, string>).authorization).toBe('Bearer admin-tok')
    expect(logs.join('\n')).toContain('MESH-XXXX-XXXX-XXXX')
  })
})
