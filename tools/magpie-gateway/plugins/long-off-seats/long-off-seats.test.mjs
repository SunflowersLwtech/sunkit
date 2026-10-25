import { test } from "node:test"
import assert from "node:assert/strict"
import { onRequest, estimate } from "./long-off-seats.middleware.js"

const ctx = { protocol: "anthropic", options: {} }
// a Claude Code-shaped request whose messages hold about n tokens of English
const req = (model, n) => ({
  model,
  system: [{ type: "text", text: "You are Claude Code." }],
  tools: [{ name: "Bash", input_schema: { type: "object" } }],
  messages: [
    { role: "user", content: [{ type: "text", text: "x".repeat(Math.round(n * 3.5)) }] },
    { role: "assistant", content: [{ type: "tool_use", id: "t1", name: "Bash", input: { command: "ls" } }] },
    { role: "user", content: [{ type: "tool_result", tool_use_id: "t1", content: "a.txt" }] },
  ],
})

test("a short request keeps its group, so a new session still starts on a seat", () => {
  assert.equal(onRequest(req("claude-opus-5-5", 60000), ctx), undefined)
})

test("a long request for each Claude group goes to that group's copy without the seats", () => {
  assert.equal(onRequest(req("claude-opus-5-5", 250000), ctx).model, "group/long-opus")
  assert.equal(onRequest(req("claude-sonnet-5-5", 250000), ctx).model, "group/long-sonnet")
  assert.equal(onRequest(req("claude-haiku-5-5", 250000), ctx).model, "group/long-haiku")
  assert.equal(onRequest(req("claude-fable-5-1", 250000), ctx).model, "group/long-opus")
})

test("the [1m] suffix and the group/ prefix name the same group", () => {
  assert.equal(onRequest(req("claude-opus-5-5[1m]", 250000), ctx).model, "group/long-opus")
  assert.equal(onRequest(req("group/claude-opus-5-5", 250000), ctx).model, "group/long-opus")
})

test("a model named with its provider is left as asked, however long", () => {
  assert.equal(onRequest(req("claude/claude-opus-5-5", 250000), ctx), undefined)
  assert.equal(onRequest(req("zed/claude-sonnet-5-5", 250000), ctx), undefined)
})

test("the threshold is the boundary: just under stays, at it moves", () => {
  const o = { ...ctx, options: { threshold: 100000 } }
  const just = (n) => ({ model: "claude-opus-5-5", messages: [{ role: "user", content: "x".repeat(Math.round(n * 3.5)) }] })
  assert.equal(onRequest(just(99000), o), undefined)
  assert.equal(onRequest(just(100500), o).model, "group/long-opus")
})

test("CJK counts a token a character, so a Chinese conversation isn't judged short", () => {
  // 210K Chinese characters is about 210K tokens; counted as ASCII it would be 60K
  const body = { model: "claude-opus-5-5", messages: [{ role: "user", content: "汉".repeat(210000) }] }
  assert.ok(estimate(body) >= 200000)
  assert.equal(onRequest(body, ctx).model, "group/long-opus")
})

test("an image counts as 1,600 tokens, not its base64 length", () => {
  const img = { type: "image", source: { type: "base64", media_type: "image/png", data: "A".repeat(3_000_000) } }
  const body = { model: "claude-opus-5-5", messages: [{ role: "user", content: [img, { type: "text", text: "what is this" }] }] }
  assert.ok(estimate(body) < 2000)
  assert.equal(onRequest(body, ctx), undefined)
})

test("tool calls and results count toward the length", () => {
  const big = "y".repeat(800000) // ~229K tokens in one tool result
  const body = { model: "claude-opus-5-5", messages: [
    { role: "assistant", content: [{ type: "tool_use", id: "t", name: "Read", input: { file_path: "/a" } }] },
    { role: "user", content: [{ type: "tool_result", tool_use_id: "t", content: [{ type: "text", text: big }] }] },
  ] }
  assert.equal(onRequest(body, ctx).model, "group/long-opus")
})

test("off, or a model the map doesn't name, leaves the request alone", () => {
  assert.equal(onRequest(req("claude-opus-5-5", 250000), { ...ctx, options: { off: true } }), undefined)
  assert.equal(onRequest(req("frontier", 250000), ctx), undefined)
  assert.equal(onRequest(req("grok/grok-4.7", 250000), ctx), undefined)
})
