import { describe, it, expect } from 'vitest'
import { Hono } from 'hono'
import { rateLimit } from './rate-limit.ts'

describe('rateLimit middleware', () => {
  it('allows under the limit then 429s', async () => {
    const app = new Hono()
    app.use('*', rateLimit({ windowMs: 1000, max: 2, key: () => 'k1' }))
    app.get('/x', c => c.text('ok'))
    expect((await app.request('/x')).status).toBe(200)
    expect((await app.request('/x')).status).toBe(200)
    expect((await app.request('/x')).status).toBe(429)
  })

  it('429 includes Retry-After header', async () => {
    const app = new Hono()
    app.use('*', rateLimit({ windowMs: 1000, max: 1, key: () => 'k1' }))
    app.get('/x', c => c.text('ok'))
    await app.request('/x')
    const res = await app.request('/x')
    expect(res.status).toBe(429)
    expect(res.headers.get('retry-after')).toMatch(/^\d+$/)
  })
})
