// create_worker: spawn an interactive coding agent inside a herdr-managed pane
// on a reachable machine, over ssh. The machine label is anything ssh resolves
// (herdr machine names are ssh aliases); the worker shows up in that machine's
// herdr session so the operator can watch and steer it from a TUI.
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

const execFileP = promisify(execFile)

/** Runs `argv` as one remote command line on `machine` via ssh; returns stdout. */
export type SpawnRunner = (machine: string, argv: string[]) => Promise<string>

function shq(a: string): string {
  return `'${a.replace(/'/g, `'\\''`)}'`
}

export const sshRunner: SpawnRunner = async (machine, argv) => {
  const { stdout } = await execFileP('ssh', [machine, argv.map(shq).join(' ')], {
    timeout: 90_000,
    maxBuffer: 4 * 1024 * 1024,
  })
  return stdout
}

export interface SpawnWorkerInput {
  machine: string
  name: string
  cwd: string
  prompt: string
  kind?: string | undefined
  agentArgs?: string[] | undefined
}

function paneIdFromWorkspaceCreate(stdout: string): string {
  const parsed = JSON.parse(stdout) as { result?: { root_pane?: { pane_id?: string } } }
  const paneId = parsed.result?.root_pane?.pane_id
  if (!paneId) throw new Error(`workspace create returned no pane_id: ${stdout.slice(0, 200)}`)
  return paneId
}

export async function spawnWorker(input: SpawnWorkerInput, run: SpawnRunner = sshRunner): Promise<string> {
  const ws = await run(input.machine, ['herdr', 'workspace', 'create', '--label', input.name, '--cwd', input.cwd])
  const paneId = paneIdFromWorkspaceCreate(ws)
  const start = ['herdr', 'agent', 'start', input.name, '--kind', input.kind ?? 'devin', '--pane', paneId]
  if (input.agentArgs?.length) start.push('--', ...input.agentArgs)
  await run(input.machine, start)
  await run(input.machine, ['herdr', 'agent', 'prompt', input.name, input.prompt])
  return `worker ${input.name} (${input.kind ?? 'devin'}) spawned in ${paneId} on ${input.machine}; watch with: herdr --remote ${input.machine}`
}
