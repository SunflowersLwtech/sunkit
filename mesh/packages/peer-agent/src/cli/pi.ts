import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { stableNode } from './devin.ts'

export const PI_USAGE = 'usage: mesh pi install [--node <path>] [--peer <path to mesh-peer.mjs>] [--module <path to mesh-pi.mjs>] [--extension <path>] [--write]'

export interface PiInstallOpts {
  /** Absolute path of the node binary that runs the peer. */
  node: string
  /** Absolute path of the bundled peer, mesh-peer.mjs. */
  peer: string
  /** Absolute path of the bundled extension, mesh-pi.mjs. */
  module: string
  /** The file pi loads: <pi agent dir>/extensions/mesh.ts. */
  extension: string
}

/**
 * The file in pi's extensions directory: a two-line loader for the bundled extension, so
 * updating the sunkit checkout updates what pi runs, as the agy and Grok Build hooks do.
 */
export function piExtensionFile(o: PiInstallOpts): string {
  return [
    '// Written by `mesh pi install` (sunkit mesh plugin). Rerun it instead of editing this file.',
    `import { createMeshExtension } from ${JSON.stringify(pathToFileURL(o.module).href)}`,
    `export default createMeshExtension({ node: ${JSON.stringify(o.node)}, peer: ${JSON.stringify(o.peer)} })`,
    '',
  ].join('\n')
}

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : undefined
}

export function parsePiInstall(args: string[], defaults: PiInstallOpts): PiInstallOpts {
  return {
    node: flag(args, '--node') ?? defaults.node,
    peer: flag(args, '--peer') ?? defaults.peer,
    module: flag(args, '--module') ?? defaults.module,
    extension: flag(args, '--extension') ?? defaults.extension,
  }
}

function stamp(d = new Date()): string {
  return d.toISOString().replace(/[-:]/g, '').replace(/\..*$/, '').replace('T', '-')
}

export function runPiInstall(args: string[], io: { log?: (s: string) => void } = {}): number {
  const log = io.log ?? console.log
  const agentDir = process.env.PI_CODING_AGENT_DIR || join(homedir(), '.pi', 'agent')
  const o = parsePiInstall(args, {
    node: stableNode(process.env.PATH, process.execPath),
    // In the bundle this file is mesh-cli.mjs, next to mesh-peer.mjs and mesh-pi.mjs.
    peer: fileURLToPath(new URL('./mesh-peer.mjs', import.meta.url)),
    module: fileURLToPath(new URL('./mesh-pi.mjs', import.meta.url)),
    extension: join(agentDir, 'extensions', 'mesh.ts'),
  })
  const text = piExtensionFile(o)
  log(`${o.extension}:\n${text}`)
  log('Name each session before starting it: MESH_SESSION_NAME=<name> pi, or pi --name <name>. Unnamed sessions are pi-<Herdr tab label> or pi-<directory>.')
  log('Tools: mcp__mesh__list_agents, mcp__mesh__send_message, mcp__mesh__read_messages. Messages wait in an inbox; a tool result says when one arrives, and a run that completes with mail unread runs once more. With MESH_WAKE set (e.g. MESH_WAKE=herdr), mail to an idle session starts a turn. pi -p and --mode json only send.')
  if (!args.includes('--write')) return 0
  const before = existsSync(o.extension) ? readFileSync(o.extension, 'utf8') : undefined
  if (before !== text) {
    mkdirSync(dirname(o.extension), { recursive: true })
    // Not *.ts, so pi does not load the backup as a second extension.
    if (before !== undefined) copyFileSync(o.extension, `${o.extension}.bak-mesh-${stamp()}`)
    writeFileSync(o.extension, text)
  }
  log('written')
  return 0
}

export async function runPi(args: string[]): Promise<number> {
  const [sub, ...rest] = args
  if (sub === 'install') return runPiInstall(rest)
  console.error(PI_USAGE)
  return 2
}
