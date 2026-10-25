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

test("tool_addition blocks become tools in the request", () => {
  const def = (name) => ({ name, description: "d", input_schema: { type: "object", properties: {} } })
  const add = (name) => ({ type: "tool_addition", tool: { type: "tool_definition", definition: def(name) } })
  const b = onProvider({
    model: "claude-sonnet-5-5",
    tools: [def("Bash"), def("Read")],
    messages: [
      { role: "user", content: [{ type: "text", text: "hi" }] },
      { role: "system", content: [add("mcp__x__one"), add("Read")] },
      { role: "user", content: [{ type: "text", text: "go" }, add("mcp__x__two")] },
    ],
  }, zed)
  assert.deepEqual(b.tools.map((x) => x.name), ["Bash", "Read", "mcp__x__one", "mcp__x__two"])
  assert.equal(JSON.stringify(b.messages).includes("tool_addition"), false)
  assert.deepEqual(b.messages.map((m) => m.role), ["user", "user"])
  assert.deepEqual(b.messages[1].content, [{ type: "text", text: "go" }])
})

// the N150 secretary's history, measured 2026-10-25: Zed's ToolResultContent refused all of these
test("tool_result content becomes text blocks only", () => {
  const b = onProvider({
    model: "claude-sonnet-5-5",
    messages: [
      { role: "user", content: [
        { type: "tool_result", tool_use_id: "t1", content: "md-panel-2026-10-22.md\nmobile-view…" },
        { type: "tool_result", tool_use_id: "t2", content: "" },
        { type: "tool_result", tool_use_id: "t3", content: [{ type: "text", text: "already text" }] },
        { type: "tool_result", tool_use_id: "t4", content: [
          { type: "tool_reference", tool_name: "mcp__x__search" }, { type: "text", text: "ok" },
        ] },
        { type: "tool_result", tool_use_id: "t5", content: [{ type: "image", source: { type: "base64", data: "iVBOR…" } }] },
      ] },
    ],
  }, zed)
  const rs = b.messages[0].content
  assert.deepEqual(rs[0].content, [{ type: "text", text: "md-panel-2026-10-22.md\nmobile-view…" }])
  assert.deepEqual(rs[1].content, [{ type: "text", text: "" }])
  assert.deepEqual(rs[2].content, [{ type: "text", text: "already text" }])
  assert.deepEqual(rs[3].content, [
    { type: "text", text: JSON.stringify({ type: "tool_reference", tool_name: "mcp__x__search" }) },
    { type: "text", text: "ok" },
  ])
  assert.deepEqual(rs[4].content, [{ type: "text", text: "[image omitted: zed tool_result]" }])
})

test("all-text tool_result blocks are left alone", () => {
  const body = { messages: [{ role: "user", content: [{ type: "tool_result", tool_use_id: "t", content: [{ type: "text", text: "x" }] }] }] }
  const before = structuredClone(body)
  assert.equal(onProvider(body, zed), undefined)
  assert.deepEqual(body, before)
})

test("tool_removal blocks are dropped", () => {
  const b = onProvider({
    model: "claude-sonnet-5-5",
    tools: [{ name: "Bash" }],
    messages: [
      { role: "user", content: [{ type: "text", text: "hi" }] },
      { role: "system", content: [{ type: "tool_removal", tool: { name: "mcp__x__one" } }] },
    ],
  }, zed)
  assert.equal(JSON.stringify(b.messages).includes("tool_removal"), false)
  assert.deepEqual(b.messages.map((m) => m.role), ["user"])
})
