import type { MiddlewareHandler } from 'hono'
import { logJson } from '../logger.ts'

export const accessLog: MiddlewareHandler = async (c, next) => {
  const start = Date.now()
  await next()
  logJson('info', 'http.request', {
    method: c.req.method,
    path: new URL(c.req.url).pathname,
    status: c.res.status,
    ms: Date.now() - start,
  })
}
