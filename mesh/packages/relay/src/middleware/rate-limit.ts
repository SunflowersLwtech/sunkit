import type { MiddlewareHandler, Context } from 'hono'

export interface RateLimitOpts {
  windowMs: number
  max: number
  key: (c: Context) => string
}

interface Bucket { count: number; resetAt: number }

/** Fixed-window counter keyed by an arbitrary string; for routes whose key is only known after parsing the body. */
export interface Limiter {
  /** Counts one hit; returns the seconds to wait when the key is over its limit, or 0. */
  hit(key: string): number
}

export function createLimiter(windowMs: number, max: number, now: () => number = Date.now): Limiter {
  const buckets = new Map<string, Bucket>()
  return {
    hit(key: string): number {
      const t = now()
      let b = buckets.get(key)
      if (!b || b.resetAt <= t) {
        // Drop expired buckets now and then so per-session keys do not pile up.
        if (buckets.size > 10_000) for (const [k, v] of buckets) if (v.resetAt <= t) buckets.delete(k)
        b = { count: 0, resetAt: t + windowMs }
        buckets.set(key, b)
      }
      b.count++
      return b.count > max ? Math.max(1, Math.ceil((b.resetAt - t) / 1000)) : 0
    },
  }
}

export function rateLimit(opts: RateLimitOpts): MiddlewareHandler {
  const limiter = createLimiter(opts.windowMs, opts.max)
  return async (c, next) => {
    const retry = limiter.hit(opts.key(c))
    if (retry > 0) return c.json({ error: 'rate_limited' }, 429, { 'retry-after': String(retry) })
    return next()
  }
}
