import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * Load environment variables from `.env.local` then `.env` in the given directory.
 * Uses Node's built-in process.loadEnvFile (>=v20.12 / v22), so no runtime dependency.
 *
 * Precedence (highest first):
 *   1. pre-existing process.env values
 *   2. .env.local
 *   3. .env
 *
 * loadEnvFile never overwrites existing env vars, so loading `.env.local` first
 * lets it shadow `.env` without touching anything the shell already exported.
 */
export function loadEnvFiles(cwd: string = process.cwd()): string[] {
  const loaded: string[] = []
  for (const name of ['.env.local', '.env']) {
    const path = resolve(cwd, name)
    if (existsSync(path)) {
      process.loadEnvFile(path)
      loaded.push(path)
    }
  }
  return loaded
}
