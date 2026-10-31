import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";

import {
  name,
  version,
  estimateInputTokens,
  resolveWindowLimit,
  trimHeadTail,
  partitionTurnGroups,
  onProvider,
  onUsage,
  strategies,
  estimateMessageTokens,
  resetSeatTelemetryForTests,
} from "./context-budget.middleware.js";

function buildSyntheticSession({ turnCount = 24, toolResultSize = 36000 } = {}) {
  const messages = [
    {
      role: "user",
      content: "Implement the multi-seat weighted context budget engine and verify all unit tests pass.",
    },
  ];

  for (let i = 1; i <= turnCount; i++) {
    const toolId = `toolu_01_${i}`;
    messages.push({
      role: "assistant",
      content: [
        {
          type: "thinking",
          thinking: `Analyzing step ${i}:`.padEnd(1800, " reasoning detail"),
        },
        {
          type: "tool_use",
          id: toolId,
          name: i % 2 === 0 ? "Bash" : "Read",
          input:
            i % 2 === 0
              ? { command: `pytest tests/test_module_${i}.py -v` }
              : { file_path: `/workspace/src/engine_${i}.py` },
        },
      ],
    });

    const headLine = `[HEAD_MARKER_${i}] Running step ${i}\n`;
    const tailLine = `\n[TAIL_MARKER_${i}] Exit code: 0 (passed ${i} assertions)`;
    const fillerLen = Math.max(0, toolResultSize - headLine.length - tailLine.length);
    const filler = "x".repeat(fillerLen);

    messages.push({
      role: "user",
      content: [
        {
          type: "tool_result",
          tool_use_id: toolId,
          content: headLine + filler + tailLine,
        },
      ],
    });
  }

  messages.push({
    role: "assistant",
    content: [{ type: "text", text: "All intermediate checks finished. Ready for final step." }],
  });
  messages.push({
    role: "user",
    content: [{ type: "text", text: "Summarize the final state and verify everything is green." }],
  });

  return {
    model: "claude-opus-5-5",
    max_tokens: 32000,
    thinking: { type: "enabled", budget_tokens: 16000 },
    system: [{ type: "text", text: "You are a senior systems engineer." }],
    messages,
  };
}

const ctx = (id, model, options = {}, protocol = "anthropic") => ({
  protocol,
  provider: { id, name: id, account: "default", model },
  options,
});

function pairingProblems(messages) {
  const problems = [];
  const seen = new Set();
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    if (!Array.isArray(msg.content)) continue;
    for (const b of msg.content) {
      if (b && b.type === "tool_result" && !seen.has(b.tool_use_id)) problems.push(`orphan tool_result ${b.tool_use_id} at ${i}`);
    }
    const uses = msg.content.filter((b) => b && b.type === "tool_use");
    for (const tu of uses) {
      seen.add(tu.id);
      const next = messages[i + 1];
      const ids = new Set(((next && Array.isArray(next.content) && next.content) || []).filter((b) => b && b.type === "tool_result").map((b) => b.tool_use_id));
      if (!next || next.role !== "user" || !ids.has(tu.id)) problems.push(`tool_use ${tu.id} at ${i} without its tool_result`);
    }
  }
  return problems;
}

describe("context-budget Magpie middleware plugin", () => {
  beforeEach(() => {
    resetSeatTelemetryForTests();
  });

  it("exports valid Magpie plugin metadata and strategy entrypoints", () => {
    assert.equal(name, "context-budget");
    assert.equal(typeof version, "string");
    assert.equal(typeof onProvider, "function");
    assert.equal(typeof onUsage, "function");
    assert.equal(typeof strategies.weighted, "function");
    assert.equal(typeof strategies.ceiling, "function");
  });

  it("knows a window only when the options name one", () => {
    assert.equal(resolveWindowLimit("zcode", "GLM-5.3"), 0);
    assert.equal(resolveWindowLimit("bedrock-glm5", "glm-5.1", { windows: {} }), 0);
    assert.equal(resolveWindowLimit("bedrock-glm5", "glm-5.1", { windows: { "bedrock-glm5": 202752 } }), 202752);
    assert.equal(resolveWindowLimit("zcode", "custom-model", { windows: { "zcode/custom-model": 160000, zcode: 1000000 } }), 160000);
    assert.equal(resolveWindowLimit("zcode", "GLM-5.3", { windows: { "GLM-5.3": 900000 } }), 900000);
  });

  it("leaves a provider with no configured window exactly as sent, max_tokens included", () => {
    // 1.0.x cut zcode to 200K and grok's max_tokens to 16384 from its own table.
    for (const options of [{}, { windows: { "bedrock-glm5": 202752 } }]) {
      for (const [id, model] of [["zcode", "GLM-5.3"], ["grok", "grok-4.7"], ["devin", "claude-opus-5-5"]]) {
        const body = buildSyntheticSession({ turnCount: 25, toolResultSize: 36000 });
        const before = JSON.stringify(body);
        const out = onProvider(body, ctx(id, model, options));
        assert.equal(out, undefined, `${id} ${JSON.stringify(options)}: expected no rewrite`);
        assert.equal(JSON.stringify(body), before, `${id}: body changed`);
      }
    }
  });

  it("leaves a non-Anthropic body alone even with a window configured", () => {
    const body = buildSyntheticSession({ turnCount: 25, toolResultSize: 36000 });
    const before = JSON.stringify(body);
    const out = onProvider(body, ctx("zcode", "GLM-5.3", { windows: { zcode: 200000 } }, "openai"));
    assert.equal(out, undefined);
    assert.equal(JSON.stringify(body), before);
  });

  it("strictly preserves message prefix on primary claude seats (~280K tokens)", () => {
    const body = buildSyntheticSession({ turnCount: 25, toolResultSize: 36000 });
    const beforeJson = JSON.stringify(body.messages);
    const initialTokens = estimateInputTokens(body);
    assert.ok(initialTokens > 220000, `Expected >220K tokens, got ${initialTokens}`);

    const out = onProvider(body, ctx("claude", "claude-opus-5-5", { windows: { claude: 200000 } }));

    assert.equal(out, undefined);
    assert.equal(JSON.stringify(body.messages), beforeJson);
  });

  it("returns at once for claude and slims a 3 MB history for a configured window (V8 timing; moejs is slower)", () => {
    const body = buildSyntheticSession({ turnCount: 60, toolResultSize: 52000 });
    const jsonSize = JSON.stringify(body).length;
    assert.ok(jsonSize > 3_000_000, `Expected >3MB payload, got ${jsonSize}`);

    const t0 = performance.now();
    const outClaude = onProvider(body, ctx("claude", "claude-opus-5-5"));
    const claudeMs = performance.now() - t0;
    assert.equal(outClaude, undefined);
    assert.ok(claudeMs < 5, `Expected O(1) <5ms on claude, took ${claudeMs.toFixed(2)}ms`);

    const outZcode = onProvider(body, ctx("zcode", "GLM-5.3", { windows: { zcode: 200000 } }));
    assert.ok(outZcode);
  });

  it("slims a ~280K token session to fit a configured 200K window while preserving head/tail markers", () => {
    const body = buildSyntheticSession({ turnCount: 25, toolResultSize: 36000 });
    const initialTokens = estimateInputTokens(body);
    assert.ok(initialTokens > 220000);

    const out = onProvider(body, ctx("zcode", "GLM-5.3", { keepRecentMessages: 6, windows: { zcode: 200000 } }));

    const afterTokens = estimateInputTokens(out);
    const zcodeInputBudget = Math.floor(200000 * 0.9) - 16384;
    assert.ok(
      afterTokens <= zcodeInputBudget,
      `Expected slimmed tokens (${afterTokens}) <= zcode budget (${zcodeInputBudget})`
    );

    assert.equal(
      out.messages[0].content,
      "Implement the multi-seat weighted context budget engine and verify all unit tests pass."
    );

    const firstToolContent = out.messages[2].content[0].content;
    assert.ok(firstToolContent.includes("[HEAD_MARKER_1]"));
    assert.ok(firstToolContent.includes("[TAIL_MARKER_1]"));
    assert.ok(firstToolContent.includes("[context-budget: trimmed"));
  });

  it("folds middle turns without splitting a tool_use from its tool_result, at every budget", () => {
    // Where the fold lands (on a tool_use or on a tool_result) depends on the
    // budget, so one window can pass by parity: sweep them, both directions.
    let folded = 0;
    for (let win = 30000; win <= 50000; win += 500) {
      const body = buildSyntheticSession({ turnCount: 80, toolResultSize: 12000 });
      const before = body.messages.length;
      const out = onProvider(body, ctx("deepseek", "deepseek-reasoner", {
        keepRecentMessages: 6,
        windows: { deepseek: win },
        defaultReserveOutput: 4096,
      }));
      if (out.messages.length < before) folded++;
      assert.deepEqual(pairingProblems(out.messages), [], `window ${win}`);
      if (win === 36000) {
        const afterTokens = estimateInputTokens(out);
        assert.ok(afterTokens <= 36000, `Expected tokens <= 36000, got ${afterTokens}`);
        assert.ok(out.max_tokens <= 36000 - afterTokens + 2048);
        if (out.thinking) assert.ok(out.thinking.budget_tokens < out.max_tokens);
      }
    }
    assert.ok(folded >= 20, `expected the sweep to fold, folded ${folded} of 41`);
  });

  it("keeps max_tokens when the reply fits the window and lowers it only when it doesn't", () => {
    const small = () => ({
      model: "m",
      max_tokens: 64000,
      thinking: { type: "enabled", budget_tokens: 60000 },
      messages: [{ role: "user", content: "x".repeat(72000) }], // ~20K tokens
    });
    const fits = small();
    assert.equal(onProvider(fits, ctx("zcode", "GLM-5.3", { windows: { zcode: 1000000 } })), undefined);
    assert.equal(fits.max_tokens, 64000);

    const tight = onProvider(small(), ctx("zcode", "GLM-5.3", { windows: { zcode: 50000 } }));
    assert.ok(tight, "expected a rewrite for a 50K window");
    const room = Math.floor(50000 * 0.95) - estimateInputTokens(tight);
    assert.ok(tight.max_tokens <= room && tight.max_tokens >= room - 16, `max_tokens ${tight.max_tokens}, room ${room}`);
    assert.ok(tight.thinking.budget_tokens < tight.max_tokens);
    assert.deepEqual(tight.messages, small().messages);
  });

  it("logs one count-only line per rewritten request when log is on, nothing when off", () => {
    const lines = [];
    const orig = console.log;
    console.log = (...a) => lines.push(a.join(" "));
    try {
      onProvider(buildSyntheticSession({ turnCount: 25, toolResultSize: 36000 }), ctx("zcode", "GLM-5.3", { windows: { zcode: 200000 } }));
      assert.equal(lines.length, 0);
      onProvider(buildSyntheticSession({ turnCount: 25, toolResultSize: 36000 }), ctx("zcode", "GLM-5.3", { windows: { zcode: 200000 }, log: true }));
      onProvider(buildSyntheticSession({ turnCount: 2, toolResultSize: 100 }), ctx("zcode", "GLM-5.3", { windows: { zcode: 200000 }, log: true }));
    } finally {
      console.log = orig;
    }
    assert.equal(lines.length, 1, lines.join("\n"));
    assert.match(lines[0], /^rewrote provider=zcode model=GLM-5\.3 window=200000 est=\d+->\d+ max_tokens=32000->\d+ stages=slim/);
    assert.ok(!/MARKER|Implement|pytest|xxxx/.test(lines[0]), lines[0]);
  });

  it("ranks seats with expiring-quota discount, ceiling protection, and cache-stampede stickiness", () => {
    const nowMs = 1_760_000_000_000;

    onUsage(
      {
        time: new Date(nowMs - 60_000).toISOString(),
        provider: "claude",
        account: "duocodetechu@gmail.com",
        key: "seat-b",
        status: 200,
        cacheWrite: 95000,
        cacheRead: 120000,
      },
      { stampedeWindowSeconds: 300 }
    );

    const seats = [
      { key: "seat-a", account: "weiliu@duocodetech.com", used: 93, soon: [nowMs + 4 * 3600 * 1000], resting: false },
      { key: "seat-b", account: "duocodetechu@gmail.com", used: 62, soon: [nowMs + 3 * 3600 * 1000], resting: false },
      { key: "seat-c", account: "duocodetechu@duocodetech.com", used: 56, soon: [nowMs + 3 * 3600 * 1000], resting: false },
      { key: "seat-d", account: "expiring-seat@duocodetech.com", used: 89, soon: [nowMs + 10 * 60 * 1000], resting: false },
    ];

    const opts = { ceiling: 88, hardCeiling: 98, expiringHorizonMinutes: 90, expiringMaxDiscount: 28, stampedeWindowSeconds: 300, _nowMs: nowMs };
    const order = strategies.weighted("claude", seats, opts);

    assert.equal(order.length, 4);
    assert.deepEqual([...order].sort(), [0, 1, 2, 3]);
    assert.equal(order[0], 1, `Expected warm-cache seat-b (1) first, got order ${order}`);
    assert.equal(order[3], 0, `Expected over-ceiling seat-a (0) last, got order ${order}`);

    // A window about to renew counts as less used: 80% renewing in 5 minutes
    // goes before 60% renewing in 4 hours.
    const expiring = strategies.weighted("claude", [
      { key: "late", used: 60, soon: [nowMs + 4 * 3600 * 1000] },
      { key: "soon", used: 80, soon: [nowMs + 5 * 60 * 1000] },
    ], opts);
    assert.deepEqual(expiring, [1, 0], "expiring discount");

    // Over the soft ceiling is a tier of its own: a seat at 90% goes after one
    // at 70% even when the 70% one scores worse (a recent 429 adds 25).
    onUsage({ time: new Date(nowMs - 30_000).toISOString(), key: "err", status: 429 }, { stampedeWindowSeconds: 300 });
    const tiered = strategies.weighted("claude", [
      { key: "high", used: 90, soon: [nowMs + 4 * 3600 * 1000] },
      { key: "err", used: 70, soon: [nowMs + 4 * 3600 * 1000] },
    ], opts);
    assert.deepEqual(tiered, [1, 0], "soft-ceiling tier");
  });
});
