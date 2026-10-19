#!/usr/bin/env node
import { loadEnvFiles } from '@claude-mesh/shared'
import { runPair } from './cli/pair.ts'
import { writeMeshMcpConfig, MESH_SERVER_NAME } from './mcp-registration.ts'
import { resolveRelayUrl } from './cli/relay-url.ts'

loadEnvFiles()

function argValue(args: string[], flag: string): string | undefined {
  const i = args.indexOf(flag)
  return i >= 0 && i + 1 < args.length ? args[i + 1] : undefined
}

async function main(): Promise<void> {
  const [, , cmd, ...args] = process.argv
  if (cmd === 'pair') {
    const pairCode = args.find(a => /^MESH-/.test(a)) ?? process.env.MESH_PAIR_CODE ?? ''
    const label = argValue(args, '--label') ?? process.env.HOSTNAME ?? 'device'
    if (!pairCode) {
      console.error('usage: mesh pair <pair-code> [--relay <url>] [--label <device>]')
      process.exit(2)
    }
    // Use the same resolution order as admin/send/respond: --relay flag →
    // MESH_RELAY env → ~/.claude-mesh/config.json. The config.json fallback
    // only helps re-pairs (first-time pair has no config yet) but costs nothing.
    let relayUrl: string
    try { relayUrl = resolveRelayUrl(args) }
    catch {
      console.error('usage: mesh pair <pair-code> [--relay <url>] [--label <device>]')
      process.exit(2)
    }
    await runPair({ relayUrl, pairCode, deviceLabel: label })
    const mcpPath = writeMeshMcpConfig()
    console.log(`OK MCP config written to ${mcpPath} (not added to ~/.claude.json)`)
    console.log(`   start a mesh session with: claude --mcp-config ${mcpPath} --dangerously-load-development-channels server:${MESH_SERVER_NAME}`)
    return
  }
  if (cmd === 'mcp-config') {
    console.log(writeMeshMcpConfig())
    return
  }
  if (cmd === 'admin') {
    const { runAdmin } = await import('./cli/admin.ts')
    await runAdmin(args)
    return
  }
  if (cmd === 'respond') {
    const { runRespond } = await import('./cli/respond.ts')
    await runRespond(args)
    return
  }
  if (cmd === 'send') {
    const { runSend } = await import('./cli/send.ts')
    await runSend(args)
    return
  }
  if (cmd === 'policy') {
    const { runPolicy } = await import('./cli/policy.ts')
    process.exitCode = runPolicy(args)
    return
  }
  if (cmd === 'say') {
    const { runSay } = await import('./cli/say.ts')
    await runSay(args)
    return
  }
  if (cmd === 'agy') {
    const { runAgy } = await import('./cli/agy.ts')
    process.exitCode = await runAgy(args)
    return
  }
  if (cmd === 'grok') {
    const { runGrok } = await import('./cli/grok.ts')
    process.exitCode = await runGrok(args)
    return
  }
  if (cmd === 'devin') {
    const { runDevin } = await import('./cli/devin.ts')
    process.exitCode = runDevin(args)
    return
  }
  console.error('commands: pair, admin, respond, send, policy, say, devin, agy, grok')
  process.exit(2)
}

main().catch(err => {
  console.error(err instanceof Error ? err.message : err)
  process.exit(1)
})
