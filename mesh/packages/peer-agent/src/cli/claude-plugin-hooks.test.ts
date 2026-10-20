import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { CLAUDE_HOOK_EVENTS } from './claude.ts'

// The plugin's hooks.json is loaded by every Claude Code session that has the mesh plugin: a
// typo there would break nothing visibly and simply never report. Pin its shape here.
const HOOKS = resolve(import.meta.dirname, '../../../../plugins/mesh/hooks/hooks.json')

describe('plugins/mesh/hooks/hooks.json', () => {
  const doc = JSON.parse(readFileSync(HOOKS, 'utf8')) as { hooks: Record<string, Array<{ matcher?: string; hooks: Array<Record<string, unknown>> }>> }

  it('wires each Claude Code event to one `mesh claude hook <event>` in exec form', () => {
    const wired = Object.entries(doc.hooks).flatMap(([event, groups]) => groups.flatMap(g => g.hooks.map(h => ({ event, h }))))
    expect(wired.map(w => w.event).sort()).toEqual(['Notification', 'SessionEnd', 'SessionStart', 'Stop', 'UserPromptSubmit'])
    for (const { h } of wired) {
      expect(h.type).toBe('command')
      expect(h.command).toBe('node')
      const args = h.args as string[]
      expect(args.slice(0, 3)).toEqual(['${CLAUDE_PLUGIN_ROOT}/server/mesh-cli.mjs', 'claude', 'hook'])
      expect(CLAUDE_HOOK_EVENTS).toContain(args[3])
    }
  })

  it('never makes the user wait on a turn: everything but session start and end runs in the background', () => {
    for (const ev of ['UserPromptSubmit', 'Notification', 'Stop']) expect(doc.hooks[ev]![0]!.hooks[0]!.async).toBe(true)
    expect(doc.hooks.SessionEnd![0]!.hooks[0]!.timeout).toBeLessThanOrEqual(2)
  })

  it('only permission and input prompts count as blocked', () => {
    expect(doc.hooks.Notification![0]!.matcher).toBe('permission_prompt|elicitation_dialog|agent_needs_input')
  })
})
