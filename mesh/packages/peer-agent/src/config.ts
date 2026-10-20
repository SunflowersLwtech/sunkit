import { readFileSync, existsSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { homedir } from 'node:os'
import { z } from 'zod'
import { readTokenFile } from './cli/token-file.ts'
import { meshDir } from './paths.ts'

export const ConfigSchema = z.object({
  relay_url: z.string().url(),
  token_path: z.string(),
  self_handle: z.string().optional(),
  /** This machine's name as Herdr and meshd know it, for the session card (e.g. m4, aws-sin-8c32g-261016). */
  machine: z.string().regex(/^[a-z0-9][a-z0-9-]{0,62}$/).optional(),
  admin_token_path: z.string().optional(),
  permission_relay: z.object({
    enabled: z.boolean().default(false),
    routing: z.enum(['never_relay','ask_thread_participants','ask_team'])
      .or(z.string().startsWith('ask_specific_peer:'))
      .default('never_relay')
  }).default({ enabled: false, routing: 'never_relay' }),
  presence: z.object({
    auto_publish_cwd: z.boolean().default(true),
    auto_publish_branch: z.boolean().default(true),
    auto_publish_repo: z.boolean().default(true)
  }).default({ auto_publish_cwd: true, auto_publish_branch: true, auto_publish_repo: true }),
  audit_log: z.string().default(() => join(meshDir(), 'audit'))
})
export type MeshConfig = z.infer<typeof ConfigSchema>

export function defaultConfigPath(): string {
  return join(meshDir(), 'config.json')
}

export function loadConfig(path: string = defaultConfigPath()): MeshConfig {
  if (!existsSync(path)) throw new Error(`config file not found: ${path}`)
  const raw = JSON.parse(readFileSync(path, 'utf8'))
  return ConfigSchema.parse(raw)
}

export function loadToken(path: string): string {
  if (!existsSync(path)) throw new Error(`token file not found: ${path}`)
  return readTokenFile(path)
}

/** Walk up from `start` looking for a .git dir. If found, inspect .git/config for any remote.url. */
export function isInsideGitRepoWithRemote(start: string): boolean {
  let dir = resolve(start)
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const gitDir = join(dir, '.git')
    if (existsSync(gitDir) && statSync(gitDir).isDirectory()) {
      const cfg = join(gitDir, 'config')
      if (existsSync(cfg)) {
        const text = readFileSync(cfg, 'utf8')
        if (/\[remote\s+"[^"]+"\][^\[]*\burl\s*=\s*\S+/s.test(text)) return true
      }
      return false
    }
    const parent = dirname(dir)
    if (parent === dir) return false
    dir = parent
  }
}

export function assertTokenNotInRepo(tokenPath: string): void {
  const dir = dirname(resolve(tokenPath))
  if (isInsideGitRepoWithRemote(dir)) {
    throw new Error(
      `refusing to start: token file "${tokenPath}" is inside a git worktree with a remote. ` +
      `Move it out of the tree or remove the remote.`
    )
  }
}
