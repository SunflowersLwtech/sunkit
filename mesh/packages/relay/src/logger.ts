export type LogFields = Record<string, string | number | boolean | null>

const BLOCKED_KEYS = new Set(['content', 'token', 'raw_body', 'authorization'])

export function logJson(level: 'info' | 'warn' | 'error', event: string, fields: LogFields = {}): void {
  const safe: LogFields = {}
  for (const [k, v] of Object.entries(fields)) {
    if (BLOCKED_KEYS.has(k)) continue
    safe[k] = v
  }
  process.stdout.write(JSON.stringify({ level, event, at: new Date().toISOString(), ...safe }) + '\n')
}
