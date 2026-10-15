import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

export const DEVIN_USAGE = 'usage: mesh devin install [--scope user|project|local] [--name mesh] [--peer <path to mesh-peer.mjs>] [--write]'

export interface DevinInstallOpts {
  /** Absolute path of the node binary Devin should run (Devin may not share the shell's PATH). */
  node: string
  /** Absolute path of the bundled peer, mesh-peer.mjs. */
  peer: string
  scope: 'user' | 'project' | 'local'
  name: string
}

/** argv for `devin mcp add`: the peer in pull mode, so Devin reads messages with read_messages. */
export function devinAddArgs(o: DevinInstallOpts): string[] {
  return ['mcp', 'add', '-s', o.scope, o.name, '-e', 'MESH_JOIN=pull', '--', o.node, o.peer]
}

export function shellQuote(s: string): string {
  return /^[A-Za-z0-9_./:=@%+-]+$/.test(s) ? s : `'${s.replace(/'/g, `'\\''`)}'`
}

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : undefined
}

export function parseDevinInstall(args: string[], defaults: { node: string; peer: string }): DevinInstallOpts {
  const scope = flag(args, '--scope') ?? 'user'
  if (scope !== 'user' && scope !== 'project' && scope !== 'local') throw new Error(DEVIN_USAGE)
  return { node: defaults.node, peer: flag(args, '--peer') ?? defaults.peer, scope, name: flag(args, '--name') ?? 'mesh' }
}

export function runDevin(args: string[], io: { log?: (s: string) => void; run?: (file: string, argv: string[]) => void } = {}): number {
  const log = io.log ?? console.log
  const [sub, ...rest] = args
  if (sub !== 'install') { console.error(DEVIN_USAGE); return 2 }
  // In the bundle this file is mesh-cli.mjs, next to mesh-peer.mjs.
  const peer = fileURLToPath(new URL('./mesh-peer.mjs', import.meta.url))
  const o = parseDevinInstall(rest, { node: process.execPath, peer })
  const argv = devinAddArgs(o)
  log(`devin ${argv.map(shellQuote).join(' ')}`)
  log(`If a "${o.name}" server is already configured in that scope, remove it first: devin mcp remove -s ${o.scope} ${o.name}`)
  log('Name each Devin session before starting it: export MESH_SESSION_NAME=<name>; devin')
  log('Messages to it wait in an inbox; the agent reads them with read_messages. Rows for it in list_agents are marked "pull".')
  if (rest.includes('--write')) {
    const run = io.run ?? ((file: string, a: string[]) => { execFileSync(file, a, { stdio: 'inherit' }) })
    run('devin', argv)
    log('written')
  }
  return 0
}
