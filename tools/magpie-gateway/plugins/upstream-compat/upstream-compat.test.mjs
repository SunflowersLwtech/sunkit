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
