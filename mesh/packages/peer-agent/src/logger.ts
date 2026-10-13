export function logJson(level: 'info' | 'warn' | 'error', event: string, fields: Record<string, unknown> = {}): void {
  const safe: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(fields)) {
    if (['content', 'token', 'authorization'].includes(k)) continue
    safe[k] = v
  }
  process.stderr.write(JSON.stringify({ level, event, at: new Date().toISOString(), ...safe }) + '\n')
}
