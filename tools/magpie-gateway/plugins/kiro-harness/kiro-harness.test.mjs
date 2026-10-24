import { test } from "node:test"
import assert from "node:assert/strict"
import { onProvider, head, tail } from "./kiro-harness.middleware.js"

const EPH = { type: "ephemeral" }
const kiro = { protocol: "anthropic", provider: { id: "kiro", account: "kiro" }, options: {} }

// Claude Code 2.1.296's system blocks, as the Kiro plugin's cache-points test captured them
const cc = () => ({
  system: [
    { type: "text", text: "x-anthropic-billing-header: cc_version=2.1.310; cc_entrypoint=cli; cch=a1b2c;" },
    { type: "text", text: "You are a Claude agent, built on Anthropic's Claude Agent SDK.", cache_control: EPH },
    { type: "text", text: "You are an agent working with the user …", cache_control: EPH },
  ],
})

test("Claude Code's blocks: billing gone, identity gone, the rest wrapped, marks kept", () => {
  const b = onProvider(cc(), kiro)
  assert.ok(b)
  assert.equal(b.system.length, 2)
  assert.equal(b.system[0].text, head)
  assert.deepEqual(b.system[0].cache_control, EPH)
  assert.equal(b.system[1].text, "You are an agent working with the user …" + tail)
  assert.deepEqual(b.system[1].cache_control, EPH)
  assert.ok(!JSON.stringify(b).includes("billing-header"))
})

test("two requests whose billing lines differ are sent the same system", () => {
  const a = cc()
  const c = cc()
  c.system[0].text = "x-anthropic-billing-header: cc_version=2.1.310; cc_entrypoint=cli; cch=zz999;"
  assert.deepEqual(onProvider(a, kiro).system, onProvider(c, kiro).system)
})

test("the CLI identity in one string", () => {
  const b = onProvider({ system: "x-anthropic-billing-header: cch=1;\nYou are Claude Code, Anthropic's official CLI for Claude.\nDo the work." }, kiro)
  assert.equal(b.system, head + "Do the work." + tail)
})

test("running twice wraps once", () => {
  const once = onProvider(cc(), kiro)
  const again = onProvider(structuredClone(once), kiro)
  assert.equal(again, undefined)
})

test("a prompt without Claude Code's identity loses only the billing line", () => {
  const b = onProvider({ system: "x-anthropic-billing-header: cch=1;\nYou are Codex." }, kiro)
  assert.equal(b.system, "You are Codex.")
  assert.equal(onProvider({ system: "You are Codex." }, kiro), undefined)
})

test("another provider's request is left alone", () => {
  const body = cc()
  const before = structuredClone(body)
  assert.equal(onProvider(body, { ...kiro, provider: { id: "claude", account: "claude" } }), undefined)
  assert.equal(onProvider(body, { ...kiro, provider: { id: "opencode-go" } }), undefined)
  assert.deepEqual(body, before)
})

test("off leaves Kiro's request alone", () => {
  assert.equal(onProvider(cc(), { ...kiro, options: { off: true } }), undefined)
})

test("Chat Completions system message", () => {
  const b = onProvider(
    { messages: [{ role: "system", content: "You are Claude Code, Anthropic's official CLI for Claude.\nRules." }, { role: "user", content: "hi" }] },
    { ...kiro, protocol: "chat" },
  )
  assert.equal(b.messages[0].content, head + "Rules." + tail)
  assert.equal(b.messages[1].content, "hi")
})
