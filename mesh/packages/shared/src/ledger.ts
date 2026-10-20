import { z } from 'zod'
import { monotonicFactory } from 'ulid'
import { LoginSchema, SessionIdSchema, SessionNameSchema } from './envelope.ts'

// The relay's ledger: who is where doing what (cards), what they were asked to do (tasks),
// what they produced (artifacts), what they are holding (leases), and what each machine can
// run (machine reports). Vocabulary and the task state machine follow A2A v1.0 (§4.1);
// transport stays this relay's own HTTP + SSE.

const ULID = '[0-9A-HJKMNP-TV-Z]{26}'
const monotonicUlid = monotonicFactory()

export type TaskId = `task_${string}`
export type LeaseId = `lease_${string}`
export type CommandId = `cmd_${string}`

const TASK_ID_REGEX = new RegExp(`^task_${ULID}$`)
export const TaskIdSchema = z.string().regex(TASK_ID_REGEX)
export const LeaseIdSchema = z.string().regex(new RegExp(`^lease_${ULID}$`))
export const CommandIdSchema = z.string().regex(new RegExp(`^cmd_${ULID}$`))

export function newTaskId(): TaskId { return `task_${monotonicUlid()}` as TaskId }
export function newLeaseId(): LeaseId { return `lease_${monotonicUlid()}` as LeaseId }
export function newCommandId(): CommandId { return `cmd_${monotonicUlid()}` as CommandId }
export function isValidTaskId(id: string): id is TaskId { return TASK_ID_REGEX.test(id) }

/** A2A TaskState (spec §4.1.3), lowercased. `stale` is never a state: it is derived from age. */
export const TASK_STATES = [
  'submitted', 'working', 'input_required', 'auth_required',
  'completed', 'failed', 'canceled', 'rejected',
] as const
export const TaskStateSchema = z.enum(TASK_STATES)
export type TaskState = z.infer<typeof TaskStateSchema>
const TERMINAL: ReadonlySet<TaskState> = new Set(['completed', 'failed', 'canceled', 'rejected'])
export function isTerminalTaskState(s: TaskState): boolean { return TERMINAL.has(s) }

/** A visibility boundary. Assigned by the relay from the token; a client never picks one it was not granted. */
export const WorkgroupSchema = z.string().regex(/^[a-z][a-z0-9-]{0,31}$/)
/** What a token may do. Bound to the token id, never to a session (session ids are visible to the whole team). */
export const RoleSchema = z.enum(['worker', 'orchestrator', 'observer', 'executor'])
export type Role = z.infer<typeof RoleSchema>

export const AgentKindSchema = z.enum(['claude', 'pi', 'agy', 'grok', 'devin'])
export type AgentKind = z.infer<typeof AgentKindSchema>
export const MachineNameSchema = z.string().regex(/^[a-z0-9][a-z0-9-]{0,62}$/)
export const HerdrWorkspaceIdSchema = z.string().regex(/^w[0-9A-Za-z]{1,8}$/)
export const HerdrTabIdSchema = z.string().regex(/^w[0-9A-Za-z]{1,8}:t[0-9A-Za-z]{1,8}$/)
export const HerdrPaneIdSchema = z.string().regex(/^w[0-9A-Za-z]{1,8}:p[0-9A-Za-z]{1,8}$/)

/**
 * Drops userinfo, query and fragment from anything URL-shaped so a token pasted into a
 * free-ish field does not travel further. Paths (POSIX or Windows) pass through unchanged.
 */
export function redactUrlCredentials(value: string): string {
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) return value
  try {
    const u = new URL(value)
    return `${u.protocol}//${u.host}${u.pathname}`
  } catch {
    return value.replace(/\/\/[^/@]*@/, '//').replace(/[?#].*$/, '')
  }
}

const RepoSchema = z.string().regex(/^[A-Za-z0-9._-]{1,64}$/)
const BranchSchema = z.string().max(128).regex(/^[A-Za-z0-9._+-][A-Za-z0-9._/+-]{0,127}$/)
  .refine(b => !b.includes('..'), 'branch')
const ModelSchema = z.string().regex(/^[A-Za-z0-9._:/@+\[\]-]{1,64}$/)

export const HerdrLocationSchema = z.object({
  machine: MachineNameSchema,
  tab: HerdrTabIdSchema.optional(),
  pane: HerdrPaneIdSchema.optional(),
}).strict()
export type HerdrLocation = z.infer<typeof HerdrLocationSchema>

/** hook: written by host lifecycle hooks (seconds fresh); poll: a 3 s poll; manual: typed by a person, may be old. */
export const CardSourceSchema = z.enum(['hook', 'poll', 'manual'])

/**
 * Body of POST /v1/sessions/self. A fixed whitelist: no free-form map anywhere, because a free
 * map is exactly where credentials get smuggled. `workgroup` is accepted only when the relay
 * finds it among the token's granted workgroups; role and dispatched_by are never accepted.
 */
export const CardPatchSchema = z.object({
  session: z.string(),
  name: SessionNameSchema.optional(),
  cwd: z.string().max(1024).optional(),
  login: LoginSchema.optional(),
  status: z.enum(['busy', 'idle', 'unknown']).optional(),
  agent: AgentKindSchema.optional(),
  model: ModelSchema.optional(),
  repo: RepoSchema.optional(),
  branch: BranchSchema.optional(),
  herdr: HerdrLocationSchema.optional(),
  task_id: TaskIdSchema.optional(),
  source: CardSourceSchema.optional(),
  workgroup: WorkgroupSchema.optional(),
}).strict()
export type CardPatch = z.infer<typeof CardPatchSchema>

export const ArtifactTypeSchema = z.enum(['pr', 'commit', 'vault', 'deploy', 'url'])

function artifactRefOk(type: z.infer<typeof ArtifactTypeSchema>, ref: string): boolean {
  if (/[\u0000-\u001f\u007f\s]/.test(ref)) return false
  if (type === 'vault') {
    return !ref.startsWith('/') && !ref.includes('\\') && !ref.split('/').some(seg => seg === '..' || seg === '')
  }
  if (type === 'deploy') return /^[A-Za-z0-9._:+-]{1,64}@[0-9TZ:.+-]{4,40}$/.test(ref)
  if (ref.startsWith('gh://')) return /^gh:\/\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(\/(pull|issues|commit)\/[0-9a-f]+)?$/.test(ref)
  let u: URL
  try { u = new URL(ref) } catch { return false }
  return u.protocol === 'https:' && u.username === '' && u.password === ''
}

/** A task output. Receivers never auto-fetch `ref` or paste what it points at into another agent's context. */
export const ArtifactSchema = z.object({
  type: ArtifactTypeSchema,
  ref: z.string().min(1).max(512),
  note: z.string().max(200).optional(),
}).strict().superRefine((a, ctx) => {
  if (!artifactRefOk(a.type, a.ref)) ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['ref'], message: 'ref' })
})
export type Artifact = z.infer<typeof ArtifactSchema>

/** deploy/<product>, repo/<repo>, file/<sha1 prefix of an absolute path>, device/<device>, build/<machine>, cred/<vault item>. */
export const LeaseNameSchema = z.string().regex(/^(deploy|repo|file|device|build|cred)\/[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/)
  .refine(n => !n.includes('..'), 'lease name')
export const MAX_LEASE_TTL_S = 1800
export const MIN_LEASE_TTL_S = 30
/** Namespaces whose lease must hang off an active task the holder owns. */
export const TASK_BOUND_LEASE_PREFIXES = ['deploy/', 'cred/'] as const

const AgentStatusSchema = z.enum(['idle', 'working', 'blocked', 'done', 'unknown']).catch('unknown')

export const MachineAgentSchema = z.object({
  name: z.string().min(1).max(64),
  agent: z.string().regex(/^[a-z0-9_-]{1,32}$/),
  status: AgentStatusSchema,
  pane: HerdrPaneIdSchema,
  tab: HerdrTabIdSchema.optional(),
  workspace: HerdrWorkspaceIdSchema.optional(),
  cwd: z.string().max(1024).transform(redactUrlCredentials).optional(),
  agent_session: z.object({
    kind: z.string().regex(/^[a-z_]{1,16}$/),
    value: z.string().min(1).max(1024),
  }).strict().optional(),
}).strict()
export type MachineAgent = z.infer<typeof MachineAgentSchema>

/** Body of POST /v1/machines/self, sent by the machine's executor (meshd). Bounded and closed at every level. */
export const MachineReportSchema = z.object({
  version: z.string().regex(/^[A-Za-z0-9._+-]{1,32}$/),
  herdr: z.object({
    ok: z.boolean(),
    version: z.string().regex(/^[A-Za-z0-9._+-]{1,32}$/).optional(),
    error: z.string().max(200).optional(),
  }).strict(),
  load: z.object({
    load1: z.number().min(0).max(10_000),
    cpus: z.number().int().min(1).max(1024),
    mem_used_pct: z.number().min(0).max(100).optional(),
  }).strict(),
  kinds: z.array(z.object({
    kind: AgentKindSchema,
    version: z.string().regex(/^[A-Za-z0-9._ ()+-]{1,64}$/).optional(),
  }).strict()).max(8),
  seats: z.array(z.object({
    email: LoginSchema,
    org: z.string().max(64).optional(),
    plan: z.string().regex(/^[a-z_-]{1,16}$/).optional(),
    five_hour_pct: z.number().min(0).max(1000).optional(),
    resets_at: z.string().datetime().optional(),
    blocked: z.boolean().optional(),
  }).strict()).max(6),
  active: z.number().int().min(0).max(1000),
  blocked: z.number().int().min(0).max(1000),
  max_active: z.number().int().min(0).max(1000).optional(),
  agents: z.array(MachineAgentSchema).max(64),
  roots: z.array(z.object({ path: z.string().min(1).max(256), exists: z.boolean() }).strict()).max(8),
}).strict()
export type MachineReport = z.infer<typeof MachineReportSchema>

/** Read-only executor commands (P1). spawn/close/closeout arrive with P4, behind their own gate. */
export const CommandRequestSchema = z.discriminatedUnion('op', [
  z.object({ op: z.literal('probe'), args: z.object({}).strict().optional() }).strict(),
  z.object({
    op: z.literal('read'),
    args: z.object({ pane: HerdrPaneIdSchema, lines: z.number().int().min(1).max(400).optional() }).strict(),
  }).strict(),
])
export type CommandRequest = z.infer<typeof CommandRequestSchema>

export const CommandResultSchema = z.object({
  ok: z.boolean(),
  output: z.string().max(65_536).optional(),
  error: z.string().max(500).optional(),
}).strict()
export type CommandResult = z.infer<typeof CommandResultSchema>

export const TaskCreateSchema = z.object({
  title: z.string().min(1).max(120),
  /** Omit to register a task for the calling session itself (depth 0). Another session's id needs the orchestrator role. */
  assignee: SessionIdSchema.optional(),
  parent_task: TaskIdSchema.optional(),
  prompt_sha256: z.string().regex(/^[0-9a-f]{64}$/).optional(),
  deadline: z.string().datetime().optional(),
}).strict()
export type TaskCreate = z.infer<typeof TaskCreateSchema>

export const TaskUpdateSchema = z.object({
  state: TaskStateSchema.optional(),
  progress: z.string().max(200).optional(),
  reason: z.string().max(200).optional(),
  if_seq: z.number().int().min(0).optional(),
}).strict()
export type TaskUpdate = z.infer<typeof TaskUpdateSchema>

export const LeaseAcquireSchema = z.object({
  name: LeaseNameSchema,
  ttl_s: z.number().int().min(MIN_LEASE_TTL_S).max(MAX_LEASE_TTL_S),
  note: z.string().max(200).optional(),
  task_id: TaskIdSchema.optional(),
}).strict()
export type LeaseAcquire = z.infer<typeof LeaseAcquireSchema>

// Wire views (what GET returns). Server-stamped times; `age_s`/`ttl_remaining_s` are computed by the
// relay so clients with skewed clocks still agree.

export interface SessionRefView { session: string | null; name: string | null; machine?: string | null }

export interface TaskView {
  id: string
  title: string
  state: TaskState
  progress: string | null
  reason: string | null
  workgroup: string
  assignee: SessionRefView
  dispatcher: SessionRefView
  parent_task: string | null
  depth: number
  prompt_sha256: string | null
  artifacts: Array<Artifact & { at: string }>
  seq: number
  created_at: string
  updated_at: string
  deadline: string | null
  age_s: number
  stale: boolean
}

export interface LeaseView {
  id: string
  name: string
  /** null when the holder sits in a workgroup the caller cannot see: you learn it is held, not by whom. */
  holder: (SessionRefView & { ref: string }) | null
  task_id: string | null
  note: string | null
  expires_at: string
  ttl_remaining_s: number
  renew_count: number
}

export interface MachineView {
  machine: string
  workgroup: string
  reported_at: string
  age_s: number
  stale: boolean
  connected: boolean
  report: MachineReport
}
