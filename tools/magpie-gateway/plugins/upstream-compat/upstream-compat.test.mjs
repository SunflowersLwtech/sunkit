import { test } from "node:test"
import assert from "node:assert/strict"
import { onProvider } from "./upstream-compat.middleware.js"

const to = (id) => ({ protocol: "anthropic", provider: { id, account: "" }, options: {} })
// the name GLM-5 wrote into the secretary's history on 10-27
const BAD = 'mesh send "obsun-ce [qzxsah]" "收到，fake provider 已删干净，readback 一致"'

const poisoned = () => ({
  model: "claude-opus-5-5",
  tools: [{ name: "Bash", input_schema: { type: "object" } }],
  messages: [
    { role: "user", content: [{ type: "text", text: "tell obsun-ce" }] },
    { role: "assistant", content: [{ type: "tool_use", id: "t1", name: BAD, input: {} }] },
    { role: "user", content: [{ type: "tool_result", tool_use_id: "t1", content: "No such tool available" }] },
    { role: "assistant", content: [{ type: "tool_use", id: "t2", name: "Bash", input: { command: "ls" } }] },
    { role: "user", content: [{ type: "tool_result", tool_use_id: "t2", content: [{ type: "text", text: "a.txt" }] }] },
  ],
})

const deferred = () => ({
  model: "claude-opus-5-5",
  tools: [{ name: "Bash", input_schema: { type: "object" } }],
  messages: [
    { role: "user", content: [{ type: "text", text: "hi" }] },
    {
      role: "user",
      content: [
        { type: "tool_addition", tool: { type: "tool_definition", definition: { name: "WebFetch", input_schema: { type: "object" } } } },
        { type: "text", text: "go" },
      ],
    },
  ],
})

const legal = /^[a-zA-Z0-9_-]{1,64}$/
const names = (b) => b.messages.flatMap((m) => (Array.isArray(m.content) ? m.content : [])).filter((c) => c.type === "tool_use").map((c) => c.name)

for (const id of ["bedrock-glm5", "deepseek", "devin"]) {
  test(`${id}: an illegal tool_use name in history becomes a legal one, legal names stay`, () => {
    const b = onProvider(poisoned(), to(id))
    assert.ok(b)
    const [bad, bash] = names(b)
    assert.match(bad, legal)
    assert.ok(bad.startsWith("mesh_send"), bad)
    assert.equal(bash, "Bash")
  })
}

test("the same history is renamed the same way every turn, so a cached prefix stays cached", () => {
  assert.deepEqual(onProvider(poisoned(), to("devin")), onProvider(poisoned(), to("devin")))
})

test("two different illegal names that clean to the same name stay apart", () => {
  const body = poisoned()
  body.messages[3].content[0].name = BAD + "!"
  const [a, b] = names(onProvider(body, to("devin")))
  assert.match(a, legal)
  assert.match(b, legal)
  assert.notEqual(a, b)
})

test("devin keeps the deferred-tool blocks it accepts", () => {
  assert.equal(onProvider(deferred(), to("devin")), undefined)
})

test("deepseek and bedrock-glm5 lose the deferred-tool blocks, and the defined tool joins tools", () => {
  for (const id of ["deepseek", "bedrock-glm5"]) {
    const b = onProvider(deferred(), to(id))
    assert.ok(b, id)
    assert.equal(JSON.stringify(b.messages).includes("tool_addition"), false, id)
    assert.deepEqual(b.tools.map((t) => t.name), ["Bash", "WebFetch"], id)
  }
})

test("only bedrock-glm5 has a string tool_result said as a text block", () => {
  const glm = onProvider(poisoned(), to("bedrock-glm5"))
  assert.deepEqual(glm.messages[2].content[0].content, [{ type: "text", text: "No such tool available" }])
  const devin = onProvider(poisoned(), to("devin"))
  assert.equal(devin.messages[2].content[0].content, "No such tool available")
})

test("a clean request is left alone for every listed provider", () => {
  const clean = () => ({ messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }] })
  for (const id of ["bedrock-glm5", "deepseek", "devin"]) assert.equal(onProvider(clean(), to(id)), undefined, id)
})

test("a provider not listed gets the body as written", () => {
  const body = poisoned()
  const before = structuredClone(body)
  assert.equal(onProvider(body, to("claude")), undefined)
  assert.deepEqual(body, before)
})

test("providers in options replace the default list", () => {
  const ctx = { ...to("devin"), options: { providers: ["deepseek"] } }
  assert.equal(onProvider(poisoned(), ctx), undefined)
  assert.ok(onProvider(poisoned(), { ...ctx, provider: { id: "deepseek" } }))
})

test("off leaves everything alone", () => {
  assert.equal(onProvider(poisoned(), { ...to("devin"), options: { off: true } }), undefined)
})

test("a 3 MB history with one bad name is fixed well inside the 250 ms hook limit", () => {
  const body = poisoned()
  for (let i = 0; i < 3000; i++) {
    body.messages.push({ role: "assistant", content: [{ type: "tool_use", id: `x${i}`, name: "Read", input: { file_path: "/a/" + "b".repeat(400) } }] })
    body.messages.push({ role: "user", content: [{ type: "tool_result", tool_use_id: `x${i}`, content: [{ type: "text", text: "c".repeat(600) }] }] })
  }
  const t = performance.now()
  const b = onProvider(body, to("devin"))
  const ms = performance.now() - t
  assert.match(names(b)[0], legal)
  assert.ok(ms < 100, `${ms} ms`)
})

// a Claude Code request of about `chars` characters of history, asking for 40,000 tokens
const long = (chars, text = "x") => ({
  model: "claude-opus-5-5",
  max_tokens: 40000,
  thinking: { type: "enabled", budget_tokens: 31999 },
  tools: [{ name: "Bash", input_schema: { type: "object" } }],
  messages: [{ role: "user", content: [{ type: "text", text: text.repeat(Math.ceil(chars / text.length)) }] }],
})

test("bedrock-glm5: the reply asked for is lowered to what its 202,752-token window leaves", () => {
  // ~650K ASCII characters: GLM counts ~160K tokens (10-27's failing requests were 163-169K)
  const b = onProvider(long(650000), to("bedrock-glm5"))
  const estimate = Math.ceil(JSON.stringify(b).length / 3.8)
  assert.ok(b.max_tokens < 40000 && b.max_tokens >= 8192, String(b.max_tokens))
  assert.ok(estimate + b.max_tokens <= 202752, `${estimate} + ${b.max_tokens}`)
  assert.ok(b.thinking.budget_tokens < b.max_tokens && b.thinking.budget_tokens >= 1024)
})

test("bedrock-glm5: a request that fits keeps its max_tokens and thinking budget", () => {
  const body = long(200000)
  const before = structuredClone(body)
  assert.equal(onProvider(body, to("bedrock-glm5")), undefined)
  assert.deepEqual(body, before)
})

test("bedrock-glm5: non-ASCII text counts a token per character, not per 3.8", () => {
  // 175K Chinese characters fit by the ASCII rate (~46K) but not by the per-character one
  const b = onProvider(long(175000, "网关"), to("bedrock-glm5"))
  assert.ok(b && b.max_tokens <= 202752 - 175000, String(b && b.max_tokens))
  // the same past 256K characters, where it is sampled: 120K Chinese among 600K ASCII
  const mixed = long(600000)
  mixed.messages.push({ role: "user", content: [{ type: "text", text: "网关".repeat(60000) }] })
  const m = onProvider(mixed, to("bedrock-glm5"))
  const ascii = Math.ceil(JSON.stringify(m).length / 3.8)
  assert.ok(m.max_tokens < 202752 - ascii - 1024, `${m.max_tokens} vs ${202752 - ascii - 1024} by the ASCII rate`)
})

test("bedrock-glm5: never under 8,192, and a body without max_tokens is left alone", () => {
  assert.equal(onProvider(long(900000), to("bedrock-glm5")).max_tokens, 8192)
  const body = long(900000)
  delete body.max_tokens
  assert.equal(onProvider(body, to("bedrock-glm5")), undefined)
})

test("other providers keep the max_tokens the agent sent", () => {
  for (const id of ["deepseek", "devin"]) assert.equal(onProvider(long(650000), to(id)), undefined)
})

test("windows in options set or override a provider's window", () => {
  const ctx = { ...to("deepseek"), options: { windows: { deepseek: 128000 } } }
  assert.ok(onProvider(long(450000), ctx).max_tokens < 40000)
  const glm = { ...to("bedrock-glm5"), options: { windows: { "bedrock-glm5": 1000000 } } }
  assert.equal(onProvider(long(650000), glm), undefined)
})

test("fitting a 3 MB request stays well inside the 250 ms hook limit", () => {
  const t = performance.now()
  onProvider(long(3000000, "ab网"), to("bedrock-glm5"))
  const ms = performance.now() - t
  assert.ok(ms < 100, `${ms} ms`)
})

test("a failing window fit keeps the other fixes", () => {
  const body = poisoned()
  body.max_tokens = 40000
  body.messages.push({ role: "user", content: [{ type: "text", text: "x".repeat(700000) }] })
  const real = JSON.stringify
  JSON.stringify = () => { throw new Error("not in this engine") }
  let b
  try {
    b = onProvider(body, to("bedrock-glm5"))
  } finally {
    JSON.stringify = real
  }
  assert.match(names(b)[0], legal)
  assert.equal(b.max_tokens, 40000)
})
