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

  it("resolves provider and model context window limits accurately", () => {
    assert.equal(resolveWindowLimit("claude", "claude-opus-4-7"), 1000000);
    assert.equal(resolveWindowLimit("zcode", "GLM-5.3"), 200000);
    assert.equal(resolveWindowLimit("bedrock-glm5", "glm-5.1"), 202752);
    assert.equal(resolveWindowLimit("devin", "claude-opus-4-6"), 262144);
    assert.equal(resolveWindowLimit("deepseek", "deepseek-reasoner"), 131072);
    assert.equal(
      resolveWindowLimit("zcode", "custom-model", { windows: { "zcode/custom-model": 160000 } }),
      160000
    );
  });

  it("strictly preserves message prefix on primary claude seats (~280K tokens < 1M window)", () => {
    const body = buildSyntheticSession({ turnCount: 25, toolResultSize: 36000 });
    const beforeJson = JSON.stringify(body.messages);
    const initialTokens = estimateInputTokens(body);
    assert.ok(initialTokens > 220000, `Expected >220K tokens, got ${initialTokens}`);

    const out = onProvider(body, {
      provider: { id: "claude", name: "claude", account: "weiliu@duocodetech.com", model: "claude-opus-4-7" },
      options: {},
    });

    assert.equal(out, undefined);
    assert.equal(JSON.stringify(body.messages), beforeJson);
  });

  it("completes a 3 MB history well inside Magpie's 250 ms moejs hook limit", () => {
    const body = buildSyntheticSession({ turnCount: 60, toolResultSize: 52000 });
    const jsonSize = JSON.stringify(body).length;
    assert.ok(jsonSize > 3_000_000, `Expected >3MB payload, got ${jsonSize}`);

    const t0 = performance.now();
    const outClaude = onProvider(body, {
      provider: { id: "claude", name: "claude", account: "weiliu@duocodetech.com", model: "claude-opus-4-7" },
      options: {},
    });
    const claudeMs = performance.now() - t0;
    assert.equal(outClaude, undefined);
    assert.ok(claudeMs < 5, `Expected O(1) <5ms on claude, took ${claudeMs.toFixed(2)}ms`);

    const t1 = performance.now();
    const outZcode = onProvider(body, {
      provider: { id: "zcode", name: "zcode", account: "default", model: "GLM-5.3" },
      options: {},
    });
    const zcodeMs = performance.now() - t1;
    assert.ok(outZcode);
    assert.ok(zcodeMs < 50, `Expected <50ms on 3MB zcode slimming, took ${zcodeMs.toFixed(2)}ms`);
  });

  it("slims a ~280K token session to fit zcode (200K) while preserving head/tail markers and recent turns", () => {
    const body = buildSyntheticSession({ turnCount: 25, toolResultSize: 36000 });
    const initialTokens = estimateInputTokens(body);
    assert.ok(initialTokens > 220000);

    const out = onProvider(body, {
      provider: { id: "zcode", name: "zcode", account: "default", model: "GLM-5.3" },
      options: { keepRecentMessages: 6 },
    });

    const afterTokens = estimateInputTokens(out);
    const zcodeInputBudget = Math.floor(200000 * 0.9) - 16384;
    assert.ok(
      afterTokens <= zcodeInputBudget,
      `Expected slimmed tokens (${afterTokens}) <= zcode budget (${zcodeInputBudget})`
    );

    // First user prompt must be untouched
    assert.equal(
      out.messages[0].content,
      "Implement the multi-seat weighted context budget engine and verify all unit tests pass."
    );

    // Older tool_result should preserve both HEAD_MARKER_1 and TAIL_MARKER_1
    const firstToolResultMsg = out.messages[2];
    const firstToolContent = firstToolResultMsg.content[0].content;
    assert.ok(firstToolContent.includes("[HEAD_MARKER_1]"));
    assert.ok(firstToolContent.includes("[TAIL_MARKER_1]"));
    assert.ok(firstToolContent.includes("[context-budget: trimmed"));
  });

  it("folds middle turns safely without breaking tool_use <-> tool_result pairing under tight 131K deepseek budget", () => {
    // 50 turns with dense messages so Stage 1+2 still exceed 131K, triggering Stage 3 middle-turn folding
    const body = buildSyntheticSession({ turnCount: 80, toolResultSize: 12000 });
    const out = onProvider(body, {
      provider: { id: "deepseek", name: "deepseek", account: "default", model: "deepseek-reasoner" },
      options: {
        keepRecentMessages: 6,
        // Force a tight window to exercise Stage 3 turn-group folding deterministically
        windows: { deepseek: 36000 },
        defaultReserveOutput: 4096,
      },
    });

    const afterTokens = estimateInputTokens(out);
    assert.ok(afterTokens <= 36000, `Expected tokens <= 36000, got ${afterTokens}`);

    // Verify every tool_use block in `out.messages` is immediately followed by a user message with matching tool_result
    for (let i = 0; i < out.messages.length; i++) {
      const msg = out.messages[i];
      if (Array.isArray(msg.content)) {
        const toolUses = msg.content.filter((b) => b && b.type === "tool_use");
        if (toolUses.length > 0) {
          const nextMsg = out.messages[i + 1];
          assert.ok(nextMsg, `Message ${i} has tool_use but no following message`);
          assert.equal(nextMsg.role, "user");
          const resultIds = new Set(
            (nextMsg.content || [])
              .filter((b) => b && b.type === "tool_result")
              .map((b) => b.tool_use_id)
          );
          for (const tu of toolUses) {
            assert.ok(
              resultIds.has(tu.id),
              `Missing matching tool_result for tool_use ${tu.id}`
            );
          }
        }
      }
    }

    // Clamp verification: max_tokens and thinking.budget_tokens must respect remaining window
    assert.ok(out.max_tokens <= 36000 - afterTokens + 2048);
    if (out.thinking) {
      assert.ok(out.thinking.budget_tokens < out.max_tokens);
    }
  });

  it("ranks seats with expiring-quota discount, ceiling protection, and cache-stampede stickiness", () => {
    const nowMs = 1_760_000_000_000;

    // Record a warm cacheWrite on seat-b (`duocodetechu@gmail.com`) 60 seconds ago
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
      {
        key: "seat-a",
        account: "weiliu@duocodetech.com",
        used: 93, // Above 88% soft ceiling, resets in 4 hours -> Tier 1
        soon: [nowMs + 4 * 3600 * 1000],
        resting: false,
      },
      {
        key: "seat-b",
        account: "duocodetechu@gmail.com",
        used: 62, // Healthy + has warm cache -> should beat seat-c despite slightly higher raw used%
        soon: [nowMs + 3 * 3600 * 1000],
        resting: false,
      },
      {
        key: "seat-c",
        account: "duocodetechu@duocodetech.com",
        used: 56, // Healthy but cold cache
        soon: [nowMs + 3 * 3600 * 1000],
        resting: false,
      },
      {
        key: "seat-d",
        account: "expiring-seat@duocodetech.com",
        used: 89, // Raw 89% (>88% ceiling), BUT resets in 10 minutes! Expiring discount pulls it into Tier 0
        soon: [nowMs + 10 * 60 * 1000],
        resting: false,
      },
    ];

    const order = strategies.weighted("claude", seats, {
      ceiling: 88,
      hardCeiling: 98,
      expiringHorizonMinutes: 90,
      expiringMaxDiscount: 28,
      stampedeWindowSeconds: 300,
      _nowMs: nowMs,
    });

    assert.equal(order.length, 4);
    assert.deepEqual([...order].sort(), [0, 1, 2, 3]);
    // seat-b (idx 1) has warm cache (62 - 14 = 48 effective score) so it beats cold seat-c (idx 2, score 56)
    assert.equal(order[0], 1, `Expected warm-cache seat-b (1) first, got order ${order}`);
    // seat-a (idx 0, 93% used, resets in 4h) should be last (Tier 1 above ceiling)
    assert.equal(order[3], 0, `Expected over-ceiling seat-a (0) last, got order ${order}`);
  });
});
