import { execSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join, basename } from 'node:path'

export interface WorkingContext {
  cwd?: string
  branch?: string
  repo?: string
}

export function detectWorkingContext(cwd: string = process.cwd()): WorkingContext {
  const ctx: WorkingContext = { cwd }
  try {
    if (existsSync(join(cwd, '.git'))) {
      ctx.branch = execSync('git -C . rev-parse --abbrev-ref HEAD', { cwd, encoding: 'utf8' }).trim()
      const remote = execSync('git -C . config --get remote.origin.url', { cwd, encoding: 'utf8' }).trim()
      ctx.repo = remote.replace(/\.git$/, '').split(/[:/]/).slice(-1)[0] || basename(cwd)
    } else {
      ctx.repo = basename(cwd)
    }
  } catch {
    // git not available or not a repo — best-effort only
  }
  return ctx
}
