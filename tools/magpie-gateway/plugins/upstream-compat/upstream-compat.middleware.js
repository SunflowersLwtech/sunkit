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
// bedrock-glm5's window is 202,752 tokens and counts the reply a request asks
// for. Claude Code asks for 40,000, so every request with more than about 162K
// of prompt failed with 400 "This model's maximum context length is 202752
// tokens. However, you requested 40000 output tokens and your prompt contains at
// least 162754 tokens". On 10-27, 17:20-17:23, all three Claude seats were held
// at magpie's 95% and GLM-5 was the only member of long-opus left; magpie does
// not retry that 400, so those agents' turns failed. The reply a request asks
// for is now lowered to what the window leaves, by an estimate that errs high:
// one token per 3.8 ASCII characters of the request as JSON and one per other
// character (magpie's own estimate is a token per 4 bytes, and GLM counted
// 162,754 tokens in a request magpie put at 168,198). It never goes under
// 8,192 (a prompt that leaves less fails as before), and a thinking budget
// follows it down. Other providers keep the max_tokens the agent sent.
//
//   {"providers": ["bedrock-glm5", "deepseek", "devin"], "windows": {"bedrock-glm5": 202752}, "off": false}

const DEFERRED = ["tool_addition", "tool_removal", "tool_reference"]
const DEFAULT = ["bedrock-glm5", "deepseek", "devin"]
// what each provider needs beyond legal tool names
const STRIP = new Set(["bedrock-glm5", "deepseek"])
const AS_TEXT = new Set(["bedrock-glm5"])
// the windows that count the reply asked for (the vendor's own number)
const WINDOWS = { "bedrock-glm5": 202752 }
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

// how many characters of json are not ASCII; past 256K characters, from 64 slices
// of 4K spread over it, so a long history stays well inside the 250 ms hook limit
// (a hook that runs over loses every change it made, tool names included)
function nonAscii(json) {
  const count = (part) => part.length - part.replace(/[^\x00-\x7f]+/g, "").length
  const N = 64
  const W = 4096
  if (json.length <= N * W) return count(json)
  const step = Math.floor(json.length / N)
  let seen = 0
  for (let i = 0; i < N; i++) seen += count(json.slice(i * step, i * step + W))
  return Math.round((seen * json.length) / (N * W))
}

function fitWindow(body, window) {
  if (typeof body.max_tokens !== "number") return false
  const json = JSON.stringify(body)
  if (json.length + body.max_tokens + 1024 <= window) return false // fits even at a token a character
  const other = nonAscii(json)
  const estimate = Math.ceil((json.length - other) / 3.8) + other
  const room = Math.max(8192, window - estimate - 1024)
  if (body.max_tokens <= room) return false
  body.max_tokens = room
  const t = body.thinking
  if (t && typeof t.budget_tokens === "number" && t.budget_tokens >= room) t.budget_tokens = Math.max(1024, room - 4096)
  return true
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
  const window = Object.assign({}, WINDOWS, o.windows || {})[id]
  try {
    if (window && fitWindow(body, window)) changed = true
  } catch (e) {
    // the engine magpie runs this in is not V8: a failure here must not cost the fixes above
  }
  return changed ? body : undefined
}
