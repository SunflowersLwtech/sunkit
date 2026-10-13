import { writeFileSync, mkdirSync } from 'node:fs'
import { join, resolve, dirname } from 'node:path'
import { homedir } from 'node:os'
import { fileURLToPath } from 'node:url'

export const MESH_SERVER_NAME = 'mesh'

/**
 * Writes a standalone MCP config (~/.claude-mesh/mcp.json) for use with
 * `claude --mcp-config <file> --dangerously-load-development-channels server:mesh`.
 * Deliberately never touches ~/.claude.json: a global entry would load the
 * mesh into every Claude Code session, and Claude Code rewrites that file
 * itself while running.
 */
export function writeMeshMcpConfig(home: string = homedir()): string {
  const here = dirname(fileURLToPath(import.meta.url))
  const config = {
    mcpServers: {
      [MESH_SERVER_NAME]: {
        type: 'stdio',
        command: process.execPath,
        args: [resolve(join(here, 'index.js'))],
      },
    },
  }
  const dir = join(home, '.claude-mesh')
  mkdirSync(dir, { recursive: true })
  const path = join(dir, 'mcp.json')
  writeFileSync(path, JSON.stringify(config, null, 2) + '\n')
  return path
}
