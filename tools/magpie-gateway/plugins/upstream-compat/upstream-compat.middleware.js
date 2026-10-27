// Per-provider fixes for upstreams that reject shapes Claude Code history carries,
// as magpie gateway middleware (onProvider: only what the named provider is sent
// changes; every other provider gets the body as the agent wrote it).
//
// bedrock-glm5 (LiteLLM -> Bedrock Converse): Bedrock validates every toolUse.name
// in the request, not only the new one: [a-zA-Z0-9_-]{1,64}. GLM-5 sometimes emits
// an invalid name (once it put a whole `mesh send "obsun-ce [qzxsah]" "received…"`
// command line, 74 chars with spaces and quotes, into a tool_use name). Anthropic
// ignores it, but every later request to Bedrock then fails the whole request with
//   400 "Value at 'messages.N.member.content.M.member.toolUse.name' failed to satisfy
//   constraint: Member must have length less than or equal to 64 … [a-zA-Z0-9_-]+"
// and magpie treats that 400 as the request's own fault (not retryable), so a
// session pinned to bedrock-glm5 died on every turn. Names are sanitized
// deterministically (invalid chars -> _, trim to 64, empty -> "tool"); a
// collision between two different original names gets a _2/_3 suffix. The same
// fix runs on tools[].name so the model only ever sees legal names.
//
// Devin answers the same poisoned history with a bare 400 "an internal error
// occurred" (the feishu secretary's session failed 8 turns in a row from 11:19:55
// on 10-27, one second after GLM-5 wrote that 74-char name), so names are
// sanitized for every listed provider, not only Bedrock.
//
// deepseek (api.deepseek.com/anthropic) and bedrock-glm5 both choke on Claude
// Code's deferred-tool blocks. DeepSeek answers 422 "unknown variant
// `tool_definition`, expected `tool_reference`" (it takes a tool_addition naming
// a tool, but not one defining it, nor tool_removal, nor a message's own
// tool_reference); Bedrock's strict parser refuses the same blocks. They are
// stripped the way magpie's own withoutDeferredTools does: tool_addition /
// tool_removal / tool_reference blocks leave messages, a tool_definition carried
// inline joins the request's own tools list (one already there wins), and a
// message they leave empty goes too. A tool_result's tool_reference content is
// ToolSearch's answer and stays for deepseek; for bedrock-glm5 every non-text
// tool_result content is said as text instead (Converse wouldn't read it).
//
// Devin takes the deferred-tool blocks as they are, so it keeps them.
//
//   {"providers": ["bedrock-glm5", "deepseek", "devin"], "off": false}

const DEFERRED = ["tool_addition", "tool_removal", "tool_reference"]
const DEFAULT = ["bedrock-glm5", "deepseek", "devin"]
// what each provider needs beyond legal tool names
const STRIP = new Set(["bedrock-glm5", "deepseek"])
const AS_TEXT = new Set(["bedrock-glm5"])
const NAME_OK = /^[a-zA-Z0-9_-]{1,64}$/
const asText = (x) => ({ type: "text", text: typeof x === "string" ? x : JSON.stringify(x) })

function cleanName(name, seen) {
  let n = String(name == null ? "" : name).replace(/[^a-zA-Z0-9_-]/g, "_")
  n = n.replace(/^_+|_+$/g, "") || "tool"
  if (n.length > 64) n = n.slice(0, 64)
  if (seen.has(n) && seen.get(n) !== name) {
    let i = 2
    let cand
    do {
      cand = (n.slice(0, 62) + "_" + i).slice(0, 64)
      i++
    } while (seen.has(cand) && seen.get(cand) !== name)
    n = cand
  }
  seen.set(n, name)
  return n
}

function fixToolNames(body) {
  let changed = false
  const seen = new Map()
  if (Array.isArray(body.tools)) {
    for (const t of body.tools) {
      if (t && typeof t.name === "string" && !NAME_OK.test(t.name)) {
        t.name = cleanName(t.name, seen)
        changed = true
      }
    }
  }
  const walk = (v) => {
    if (Array.isArray(v)) { for (const x of v) walk(x); return }
    if (!v || typeof v !== "object") return
    if (v.type === "tool_use" && typeof v.name === "string" && !NAME_OK.test(v.name)) {
      v.name = cleanName(v.name, seen)
      changed = true
    }
    for (const k of Object.keys(v)) {
      if (k === "name" && v.type === "tool_use") continue
      walk(v[k])
    }
  }
  if (Array.isArray(body.messages)) walk(body.messages)
  return changed
}

function withoutDeferred(body) {
  const added = []
  let changed = false
  for (const m of body.messages) {
    if (!m || !Array.isArray(m.content) || !m.content.some((b) => b && DEFERRED.includes(b.type))) continue
    for (const b of m.content) {
      if (b && b.type === "tool_addition" && b.tool && b.tool.type === "tool_definition" && b.tool.definition && b.tool.definition.name) {
        added.push(b.tool.definition)
      }
    }
    m.content = m.content.filter((b) => !(b && DEFERRED.includes(b.type)))
    changed = true
  }
  if (!changed) return false
  body.messages = body.messages.filter((m) => !(m && Array.isArray(m.content) && m.content.length === 0))
  const have = new Set((body.tools || []).map((x) => x && x.name))
  for (const d of added) {
    if (d.name && !have.has(d.name)) {
      ;(body.tools = body.tools || []).push(d)
      have.add(d.name)
    }
  }
  return true
}

function resultsAsText(body) {
  let changed = false
  for (const m of body.messages) {
    if (!m || !Array.isArray(m.content)) continue
    for (const b of m.content) {
      if (!b || b.type !== "tool_result") continue
      if (typeof b.content === "string") { b.content = [{ type: "text", text: b.content }]; changed = true; continue }
      if (!Array.isArray(b.content)) continue
      if (b.content.every((c) => c && c.type === "text")) continue
      b.content = b.content.map((c) => (c && c.type === "text" ? c : asText(c)))
      changed = true
      continue
    }
  }
  return changed
}

export function onProvider(body, ctx) {
  const o = (ctx && ctx.options) || {}
  if (o.off) return
  const ids = Array.isArray(o.providers) && o.providers.length ? o.providers : DEFAULT
  const p = (ctx && ctx.provider) || {}
  const id = ids.includes(p.id) ? p.id : ids.includes(p.account) ? p.account : null
  if (!id) return
  if (ctx.protocol !== "anthropic" || !body || !Array.isArray(body.messages)) return
  let changed = STRIP.has(id) && withoutDeferred(body)
  if (fixToolNames(body)) changed = true
  if (AS_TEXT.has(id) && resultsAsText(body)) changed = true
  return changed ? body : undefined
}
