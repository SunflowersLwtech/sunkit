import { Hono } from 'hono'
import type { Deps } from './deps.ts'
import { messagesRoute } from './routes/messages.ts'
import { streamRoute } from './routes/stream.ts'
import { presenceRoute } from './routes/presence.ts'
import { peersRoute } from './routes/peers.ts'
import { authRoute } from './routes/auth.ts'
import { adminRoute } from './routes/admin.ts'
import { metricsRoute } from './routes/metrics.ts'
import { permissionRoute } from './routes/permission.ts'
import { accessLog } from './middleware/access-log.ts'
import { sessionsRoute } from './routes/sessions.ts'
import { SessionRegistry } from './sessions/registry.ts'
import { TaskStore } from './ledger/tasks.ts'
import { tasksRoute } from './routes/tasks.ts'
import { LeaseStore } from './ledger/leases.ts'
import { leasesRoute } from './routes/leases.ts'

export function buildApp(inputDeps: Deps) {
  const deps: Deps = { ...inputDeps, sessions: inputDeps.sessions ?? new SessionRegistry() }
  const tasks = inputDeps.tasks ?? new TaskStore(deps.db, deps.now)
  const leases = inputDeps.leases ?? new LeaseStore(deps.db, deps.now)
  const app = new Hono()
  app.use('*', accessLog)
  app.get('/health', c => c.json({ ok: true }))
  app.route('/metrics', metricsRoute(deps))
  app.route('/v1/messages', messagesRoute(deps))
  app.route('/v1/stream', streamRoute(deps))
  app.route('/v1/presence', presenceRoute(deps))
  app.route('/v1/peers', peersRoute(deps))
  app.route('/v1/sessions', sessionsRoute(deps))
  app.route('/v1/tasks', tasksRoute({ ...deps, tasks }))
  app.route('/v1/leases', leasesRoute({ ...deps, tasks, leases }))
  app.route('/v1/auth', authRoute(deps))
  app.route('/v1/admin', adminRoute(deps))
  app.route('/v1/permission', permissionRoute(deps))
  return app
}
