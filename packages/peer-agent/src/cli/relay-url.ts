import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { meshDir } from '../paths.ts'

function argValue(args: string[], flag: string): string | undefined {
  const i = args.indexOf(flag)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : undefined
}

function readConfigRelayUrl(): string | undefined {
  const p = join(meshDir(), 'config.json')
  if (!existsSync(p)) return undefined
  try {
    const cfg = JSON.parse(readFileSync(p, 'utf8')) as { relay_url?: unknown }
    return typeof cfg.relay_url === 'string' ? cfg.relay_url : undefined
  } catch {
    return undefined
  }
}

export function resolveRelayUrl(args: string[]): string {
  const url = argValue(args, '--relay') ?? process.env.MESH_RELAY ?? readConfigRelayUrl()
  if (!url) {
    throw new Error(
      'missing relay URL. Provide one of: --relay <url>, MESH_RELAY env var, or pair first with `mesh pair` (writes ~/.claude-mesh/config.json).'
    )
  }
  return url
}
