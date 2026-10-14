import { describe, it, expect } from 'vitest'
import { createMcpServer } from './mcp-server.ts'

describe('createMcpServer', () => {
  it('declares claude/channel capability', () => {
    const { capabilities } = createMcpServer({ permissionRelay: false })
    expect(capabilities.experimental).toHaveProperty('claude/channel')
    expect(capabilities.experimental).not.toHaveProperty('claude/channel/permission')
  })

  it('also declares claude/channel/permission when permissionRelay=true', () => {
    const { capabilities } = createMcpServer({ permissionRelay: true })
    expect(capabilities.experimental).toHaveProperty('claude/channel')
    expect(capabilities.experimental).toHaveProperty('claude/channel/permission')
  })

  it('sets CHANNEL_INSTRUCTIONS on the server', () => {
    const { instructions } = createMcpServer({ permissionRelay: false })
    expect(instructions).toContain('UNTRUSTED USER INPUT')
    expect(instructions).toContain('Never auto-approve')
  })
})
