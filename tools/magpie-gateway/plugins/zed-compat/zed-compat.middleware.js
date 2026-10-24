// Claude Code on a Zed account, as magpie gateway middleware (onProvider: only what a Zed
// account is sent changes).
//
// Claude Code 2.1.310 sends `context_management` (edits such as clear_thinking_20251015 and
// clear_tool_uses_*) on its Messages requests. Zed's cloud.zed.dev parses the body strictly
// and refuses the whole request:
//   400 Zed: failed to parse Anthropic request: unknown variant `clear_thinking_20251015`,
//   expected `compact_20260112`
// so every Claude Code turn on zed/* failed. The edits only trim old thinking and tool
// results server-side; leaving them out sends the whole context, which Zed accepts.
//
// Zed also refuses a message whose content is a plain string (a subagent's first turn):
//   400 Zed: failed to parse Anthropic request: invalid type: string "…"
// Such content is sent as one text block, which means the same.
//
//   {"accounts": ["zed"], "off": false}

export function onProvider(body, ctx) {
  const o = ctx.options || {}
  if (o.off) return
  const accounts = Array.isArray(o.accounts) && o.accounts.length ? o.accounts : ["zed"]
  const p = ctx.provider || {}
  if (!accounts.includes(p.account) && !accounts.includes(p.id)) return
  if (ctx.protocol !== "anthropic" || !body) return
  let changed = false
  if ("context_management" in body) {
    delete body.context_management
    changed = true
  }
  if (Array.isArray(body.messages)) {
    for (const m of body.messages) {
      if (m && typeof m.content === "string") {
        m.content = [{ type: "text", text: m.content }]
        changed = true
      }
    }
  }
  return changed ? body : undefined
}
