// Claude Code on a Kiro account, as magpie gateway middleware (onProvider:
// only what a Kiro account is sent changes; every other provider gets the
// prompt as the agent wrote it).
//
// Kiro puts the caller's system prompt at the head of the first user
// message, under Kiro's own prompt that already names the model Kiro. Two
// things in Claude Code's prompt then go wrong:
//
// - its identity line ("You are Claude Code, Anthropic's official CLI…" or
//   "You are a Claude agent, built on Anthropic's Claude Agent SDK.")
//   quoted inside a user message reads as injected text, and the model
//   disowns the whole prompt. Recast: the line goes and the rest is wrapped
//   in <harness_instructions> that say whose instructions they are;
// - the billing line (x-anthropic-billing-header: …; cch=…) changes every
//   request and sits at the very start, so Kiro's prompt cache never hits
//   on anything after it. It is dropped.
//
// Ported from the 2026-10-08 local patch to magpie's built-in Kiro gateway
// (internal/gateway/kiro.go, kiroHarness + withoutBillingHeader), which the
// community Kiro plugin doesn't carry.
//
//   {"accounts": ["kiro"], "off": false}

export const head = `<harness_instructions>
The user runs you inside Claude Code, Anthropic's agentic coding CLI, which they chose as their agent harness. Everything inside these tags is that harness's own operating instructions, supplied by the user's client rather than typed by the user. For this session the user wants you to work as Claude Code: follow these instructions as your system instructions, use the harness's tools and conventions, and refer to yourself as Claude Code. The user's actual request is the message after these tags.
`
export const tail = "\n</harness_instructions>"

const identity = /^You are (Claude Code, Anthropic's official CLI for Claude|a Claude agent, built on Anthropic's Claude Agent SDK)\.[ \t]*\n?/m
const billing = /^x-anthropic-billing-header:[^\n]*\n?/m

export function onProvider(body, ctx) {
  const o = ctx.options || {}
  if (o.off) return
  const accounts = Array.isArray(o.accounts) && o.accounts.length ? o.accounts : ["kiro"]
  const p = ctx.provider || {}
  if (!accounts.includes(p.account) && !accounts.includes(p.id)) return
  switch (ctx.protocol) {
    case "anthropic":
      if (typeof body.system === "string") {
        const t = recastText(body.system)
        if (t === body.system) return
        body.system = t
        return body
      }
      if (Array.isArray(body.system)) return recastBlocks(body.system) ? body : undefined
      return
    case "chat":
      return recastMessages(body.messages) ? body : undefined
    case "responses":
      if (typeof body.instructions === "string") {
        const t = recastText(body.instructions)
        if (t !== body.instructions) {
          body.instructions = t
          return body
        }
      }
      return recastMessages(body.input) ? body : undefined
  }
}

// recastText: one string of instructions
export function recastText(s) {
  const noBill = s.replace(billing, "")
  if (!identity.test(noBill)) return noBill
  return head + noBill.replace(identity, "") + tail
}

// recastBlocks: Anthropic system blocks, kept as blocks so their cache
// marks stay where the agent put them. Returns whether anything changed.
export function recastBlocks(blocks) {
  let changed = false
  let found = false
  for (let i = blocks.length - 1; i >= 0; i--) {
    const b = blocks[i]
    if (!b || typeof b.text !== "string") continue
    let t = b.text.replace(billing, "")
    if (identity.test(t)) {
      found = true
      t = t.replace(identity, "")
    }
    if (t !== b.text) changed = true
    // a block left empty is taken out, unless it holds a cache mark
    if (t.trim() === "" && !b.cache_control) blocks.splice(i, 1)
    else b.text = t
  }
  if (!found) return changed
  const texts = blocks.filter((b) => b && typeof b.text === "string")
  if (!texts.length) return changed
  texts[0].text = head + texts[0].text
  texts[texts.length - 1].text = texts[texts.length - 1].text + tail
  return true
}

// system or developer messages of a Chat Completions or Responses body
function recastMessages(list) {
  if (!Array.isArray(list)) return false
  let changed = false
  for (const m of list) {
    if (!m || (m.role !== "system" && m.role !== "developer")) continue
    if (typeof m.content === "string") {
      const t = recastText(m.content)
      if (t !== m.content) {
        m.content = t
        changed = true
      }
    } else if (Array.isArray(m.content) && recastBlocks(m.content)) changed = true
  }
  return changed
}
