#!/usr/bin/env node
import { execFile } from 'node:child_process'
import { existsSync, realpathSync } from 'node:fs'
import { cpus, freemem, homedir, loadavg, platform, totalmem } from 'node:os'
import { delimiter, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { assertTokenNotInRepo, loadConfig, loadToken } from '../config.ts'
import { Meshd, type Log, type Runner } from './daemon.ts'

// Entry point of meshd (bundled as plugins/mesh/server/meshd.mjs). It runs under the
// machine's service manager with its own MESH_HOME holding an executor token, never the
// device token the machine's sessions share.

const log: Log = (level, event, fields = {}) => {
  process.stderr.write(JSON.stringify({ level, event, at: new Date().toISOString(), ...fields }) + '\n')
}

/**
 * Service managers start with a bare PATH. The node running meshd goes first: agent CLIs such as
 * pi start with `#!/usr/bin/env node`, and on a machine whose node comes from a version manager
 * there is no node on the default PATH. Then the usual places agents and herdr live.
 */
function searchPath(): string {
  const home = homedir()
  const extra = [join(home, '.local/bin'), join(home, '.bun/bin'), '/opt/homebrew/bin', '/usr/local/bin']
  return [dirname(process.execPath), ...(process.env.PATH ?? '').split(delimiter).filter(Boolean), ...extra].join(delimiter)
}

const run: Runner = (file, args, timeoutMs) => new Promise(resolve => {
  execFile(file, args, { timeout: timeoutMs, maxBuffer: 4 * 1024 * 1024, env: { ...process.env, PATH: searchPath() } }, (err, stdout, stderr) => {
    if (err) resolve({ ok: false, stdout: String(stdout ?? ''), error: (String(stderr ?? '').trim() || err.message).slice(0, 500) })
    else resolve({ ok: true, stdout: String(stdout) })
  })
})

export async function main(): Promise<void> {
  // No .env loading: under a service manager the working directory is arbitrary, and whatever a
  // stray .env holds would be handed to every child process.
  if (!process.env.MESH_HOME) {
    log('error', 'meshd.no_mesh_home', { hint: 'set MESH_HOME to the directory holding this machine\'s executor token (not ~/.claude-mesh)' })
    process.exit(2)
  }
  const cfg = loadConfig()
  assertTokenNotInRepo(cfg.token_path)
  const token = loadToken(cfg.token_path)
  const home = homedir()
  const ccQuota = join(home, '.agents/tools/cc-quota')
  const maxActive = Number(process.env.MESHD_MAX_ACTIVE)
  const roots = ['~/Developer/products', '~/.agents/tmp', '~/Developer/obsun']

  const meshd = new Meshd({
    relayUrl: cfg.relay_url,
    token,
    herdrBin: process.env.HERDR_BIN ?? 'herdr',
    ccQuota: existsSync(ccQuota) ? ccQuota : null,
    // On a Mac a LaunchAgent already refreshes cc-quota's cache every 5 minutes; read that instead of calling again.
    ccQuotaArgs: platform() === 'darwin' ? ['--json', '--cache-only'] : ['--json'],
    ...(Number.isInteger(maxActive) && maxActive > 0 && maxActive <= 1000 ? { maxActive } : {}),
    roots: roots.map(p => ({ path: p, exists: () => existsSync(join(home, p.slice(2))) })),
    load: () => ({ load1: loadavg()[0] ?? 0, cpus: cpus().length || 1, memUsedPct: (1 - freemem() / totalmem()) * 100 }),
    run,
    fetch: globalThis.fetch,
    log,
  })
  const stop = (signal: string) => { log('info', 'meshd.stop', { signal }); meshd.stop(); setTimeout(() => process.exit(0), 200).unref() }
  process.on('SIGTERM', () => stop('SIGTERM'))
  process.on('SIGINT', () => stop('SIGINT'))
  log('info', 'meshd.start', { relay: cfg.relay_url, pid: process.pid })
  await meshd.start()
}

function invokedAsScript(): boolean {
  if (!process.argv[1]) return false
  try { return realpathSync(fileURLToPath(import.meta.url)) === realpathSync(process.argv[1]) } catch { return false }
}
if (invokedAsScript()) {
  main().catch(err => { log('error', 'meshd.fatal', { err: String(err instanceof Error ? err.message : err) }); process.exit(1) })
}
