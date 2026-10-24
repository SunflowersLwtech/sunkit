import { test } from "node:test"
import assert from "node:assert/strict"
import { onProvider } from "./zed-compat.middleware.js"

const zed = { protocol: "anthropic", provider: { id: "zed", account: "zed" }, options: {} }

// what Claude Code 2.1.310 sent that Zed refused
const cc = () => ({
  model: "claude-sonnet-5-5",
  context_management: { edits: [{ type: "clear_thinking_20251015" }, { type: "clear_tool_uses_20250919" }] },
  messages: [
    { role: "user", content: "Use a subagent to read b.txt" },
    { role: "assistant", content: [{ type: "text", text: "ok" }] },
  ],
})

test("context_management is dropped and string content becomes a text block", () => {
  const b = onProvider(cc(), zed)
  assert.ok(b)
  assert.equal("context_management" in b, false)
  assert.deepEqual(b.messages[0].content, [{ type: "text", text: "Use a subagent to read b.txt" }])
  assert.deepEqual(b.messages[1].content, [{ type: "text", text: "ok" }])
})

test("a request Zed already accepts is left alone", () => {
  assert.equal(onProvider({ messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }] }, zed), undefined)
})

test("another provider's request is left alone", () => {
  const body = cc()
  const before = structuredClone(body)
  assert.equal(onProvider(body, { ...zed, provider: { id: "kiro", account: "kiro" } }), undefined)
  assert.deepEqual(body, before)
})

test("off leaves Zed's request alone", () => {
  assert.equal(onProvider(cc(), { ...zed, options: { off: true } }), undefined)
})
