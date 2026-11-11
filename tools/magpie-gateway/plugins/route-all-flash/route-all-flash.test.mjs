import { test } from "node:test"
import assert from "node:assert/strict"
import { onRequest } from "./route-all-flash.middleware.js"

const SESSION = "11111111-2222-3333-4444-555555555555"
const DEVICE = "d9d9d9d9"

// what server/fleet-watch.py's probe() sends; magpie names its agent from
// the User-Agent fleet-watch/1
const probe = (group) => ({
  model: "group/" + group,
  max_tokens: 256,
  messages: [{ role: "user", content: "Health check 0123456789ab. Reply with the word PONG." }],
})
const ctx = (agent, options = {}) => ({ protocol: "anthropic", model: "", stream: false, path: "/v1/messages", agent, options })

// a Claude Code request: tools, and metadata.user_id naming its session
const cc = (model, session = SESSION) => ({
  model,
  max_tokens: 64000,
  tools: [{ name: "Bash", input_schema: { type: "object" } }],
  metadata: { user_id: JSON.stringify({ device_id: DEVICE, account_uuid: "", session_id: session }) },
  messages: [{ role: "user", content: "hi" }],
})

const run = (body, c) => {
  const out = onRequest(body, c)
  return out === undefined ? undefined : out.model
}

test("a fleet-watch probe of any group goes to a seat, never to group/flash-ds", () => {
  for (const g of ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1",
    "long-opus", "long-sonnet", "long-haiku", "frontier", "always-up"]) {
    assert.equal(run(probe(g), ctx("fleet-watch")), "claude/claude-opus-5-5", g)
  }
})

test("options.probe picks where probes go", () => {
  assert.equal(run(probe("frontier"), ctx("fleet-watch", { probe: "grok/grok-4.7" })), "grok/grok-4.7")
  assert.equal(run(probe("frontier"), ctx("fleet-watch", { probe: "" })), "claude/claude-opus-5-5")
})

test("the same one-word question from any other agent still goes to group/flash-ds", () => {
  // the probe is known by who sends it, not by its shape: gw-fallback (the
  // secretary's own check) and a script's tiny request look the same
  for (const a of ["gw-fallback", "Python-urllib", "claude", "litellm", "", undefined]) {
    assert.equal(run(probe("claude-opus-5-5"), ctx(a)), "group/flash-ds", String(a))
  }
  assert.equal(run(probe("claude-opus-5-5"), undefined), "group/flash-ds")
})

test("a request under fleet-watch's name that brings tools is split like any other", () => {
  const body = cc("claude-opus-5-5", "99999999-0000-0000-0000-000000000000")
  assert.equal(run(body, ctx("fleet-watch")), "group/flash-ds")
  assert.equal(run(cc("claude-opus-5-5"), ctx("fleet-watch", { sessions: [SESSION] })), "claude/claude-opus-5-5")
  const noTools = probe("frontier")
  noTools.tools = []
  assert.equal(run(noTools, ctx("fleet-watch")), "claude/claude-opus-5-5")
})

test("a probe that names a real route of its own is left as asked", () => {
  for (const m of ["deepseek/deepseek-flash", "devin/swe-2", "zcode/GLM-5.3", "group/flash-paid", "litellm-claude-api/claude-haiku-5-5"]) {
    const b = probe("x")
    b.model = m
    assert.equal(run(b, ctx("fleet-watch")), m)
  }
})

test("off leaves every request alone, probes too", () => {
  assert.equal(onRequest(probe("frontier"), ctx("fleet-watch", { off: true })), undefined)
})

// the split as it was before probes had a way of their own

test("a session not on the list goes to group/flash-ds", () => {
  assert.equal(run(cc("claude-opus-5-5"), ctx("claude")), "group/flash-ds")
  assert.equal(run(cc("claude-opus-5-5"), ctx("claude", { free: "group/other" })), "group/other")
})

test("a listed session keeps its own Claude model as the claude provider's", () => {
  const o = { sessions: [SESSION] }
  assert.equal(run(cc("claude-opus-5-5"), ctx("claude", o)), "claude/claude-opus-5-5")
  assert.equal(run(cc("group/claude-sonnet-5-5"), ctx("claude", o)), "claude/claude-sonnet-5-5")
  assert.equal(run(cc("frontier"), ctx("claude", o)), "group/flash-ds")
})

test("the older user_id form names the session too", () => {
  const b = cc("claude-opus-5-5")
  b.metadata.user_id = "user_abc_account_def_session_" + SESSION
  assert.equal(run(b, ctx("claude", { sessions: [SESSION] })), "claude/claude-opus-5-5")
})

test("the secretary gets a seat only while its lease runs", () => {
  const o = (until) => ({ secretary: [DEVICE], seatUntil: until })
  assert.equal(run(cc("group/auto-deepseek-v4-1-flash", "x"), ctx("claude", o(Date.now() + 60000))), "claude/claude-opus-5-5")
  assert.equal(run(cc("group/auto-deepseek-v4-1-flash", "x"), ctx("claude", o(Date.now() - 1))), "group/flash-ds")
})

test("the Feishu assistant goes to group/flash-paid", () => {
  const b = cc("group/auto-deepseek-v4-1-flash", "x")
  b.system = [{ type: "text", text: "你是刘维的个人助理。" }]
  assert.equal(run(b, ctx("claude")), "group/flash-paid")
})

test("real routes of their own are left as asked", () => {
  for (const m of ["deepseek/deepseek-flash", "always-up", "devin/swe-2", "group/flash-paid", "zcode/GLM-5.3", "workbuddy/glm-5.3", "litellm-claude-api/claude-haiku-5-5"]) {
    assert.equal(run(cc(m), ctx("claude")), m)
  }
})
