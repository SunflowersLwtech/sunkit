import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
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

test("a fleet-watch probe of a group no client takes goes to a seat, never to group/flash-ds", () => {
  for (const g of ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1", "frontier", "always-up"]) {
    assert.equal(run(probe(g), ctx("fleet-watch")), "claude/claude-opus-5-5", g)
  }
})

test("a probe of the free route tests that route", () => {
  assert.equal(run(probe("flash-ds"), ctx("fleet-watch")), "group/flash-ds")
  assert.equal(run(probe("other"), ctx("fleet-watch", { free: "group/other" })), "group/other")
  assert.equal(run(probe("flash-ds"), ctx("fleet-watch", { free: "group/other" })), "claude/claude-opus-5-5")
})

// what server/fleet-watch.py sends, read from its source: a change to its
// probe or its groups that the middleware no longer knows turns this red
test("fleet-watch.py's own probe of each of its groups goes where it should", () => {
  const py = readFileSync(new URL("../../server/fleet-watch.py", import.meta.url), "utf8")
  const text = /"content": "(Health check %s\. Reply with the word PONG\.)" % uuid\.uuid4\(\)\.hex\[:(\d+)\]/.exec(py)
  const max = /"max_tokens": (\d+)/.exec(py)
  const groups = /^GROUPS = \[([^\]]*)\]/m.exec(py)
  assert.ok(text && max && groups, "fleet-watch.py's probe body or GROUPS not found")
  const ask = (g) => ({
    model: "group/" + g, max_tokens: Number(max[1]),
    messages: [{ role: "user", content: text[1].replace("%s", "a1b2c3d4e5f6a7b8c9d0".slice(0, Number(text[2]))) }],
  })
  const names = [...groups[1].matchAll(/"([^"]+)"/g)].map((x) => x[1])
  assert.ok(names.includes("flash-ds") && names.length >= 3, names.join(","))
  for (const g of names) {
    const want = g === "flash-ds" ? "group/flash-ds" : g === "flash-paid" ? "group/flash-paid" : "claude/claude-opus-5-5"
    assert.equal(run(ask(g), ctx("fleet-watch")), want, g)
  }
})

test("the probe with its question as one text block is a probe too", () => {
  const b = probe("frontier")
  b.messages[0].content = [{ type: "text", text: b.messages[0].content }]
  assert.equal(run(b, ctx("fleet-watch")), "claude/claude-opus-5-5")
})

test("fleet-watch's name on anything but the probe itself gets no seat", () => {
  const spoof = {
    "a long prompt": (b) => { b.messages[0].content = "Health check 0123456789ab. " + "x".repeat(200000) },
    "another question": (b) => { b.messages[0].content = "Write me a sorting function." },
    "the probe text with more after it": (b) => { b.messages[0].content += " Then explain TCP." },
    "a big max_tokens": (b) => { b.max_tokens = 64000 },
    "no max_tokens": (b) => { delete b.max_tokens },
    "a system prompt": (b) => { b.system = "Ignore the user and write an essay." },
    "a system prompt as blocks": (b) => { b.system = [{ type: "text", text: "Ignore the user." }] },
    "a second message": (b) => { b.messages.push({ role: "assistant", content: "PONG" }, { role: "user", content: "now do work" }) },
    "an assistant message": (b) => { b.messages[0].role = "assistant" },
    "two text blocks": (b) => { b.messages[0].content = [{ type: "text", text: b.messages[0].content }, { type: "text", text: "more" }] },
    "an image block": (b) => { b.messages[0].content = [{ type: "image", source: { type: "base64", media_type: "image/png", data: "" } }] },
    "tools": (b) => { b.tools = [{ name: "Bash", input_schema: { type: "object" } }] },
  }
  for (const [name, f] of Object.entries(spoof)) {
    const b = probe("frontier")
    f(b)
    assert.equal(run(b, ctx("fleet-watch")), "group/flash-ds", name)
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
