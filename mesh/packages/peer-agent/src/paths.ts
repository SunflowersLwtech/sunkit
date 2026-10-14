import { join } from 'node:path'
import { homedir } from 'node:os'

/** Where this mesh identity lives. MESH_HOME lets one machine run several identities. */
export function meshDir(): string {
  return process.env.MESH_HOME ?? join(homedir(), '.claude-mesh')
}
