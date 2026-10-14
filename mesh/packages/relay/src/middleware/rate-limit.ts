import type { MiddlewareHandler, Context } from 'hono'

export interface RateLimitOpts {
  windowMs: number
  max: number
  key: (c: Context) => string
}

interface Bucket { count: number; resetAt: number }

export function rateLimit(opts: RateLimitOpts): MiddlewareHandler {
  const buckets = new Map<string, Bucket>()
  return async (c, next) => {
    const k = opts.key(c)
    const now = Date.now()
    let b = buckets.get(k)
    if (!b || b.resetAt <= now) {
      b = { count: 0, resetAt: now + opts.windowMs }
      buckets.set(k, b)
    }
    b.count++
    if (b.count > opts.max) {
      const retry = Math.ceil((b.resetAt - now) / 1000)
      return c.json({ error: 'rate_limited' }, 429, { 'retry-after': String(retry) })
    }
    return next()
  }
}
