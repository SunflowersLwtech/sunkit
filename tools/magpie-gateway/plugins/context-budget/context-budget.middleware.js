/**
 * context-budget.middleware.js — Magpie Gateway Plugin
 *
 * Provider-aware context window budgeting, surgical payload slimming for
 * constrained fallback models (zcode/GLM-5, bedrock-glm5, devin, deepseek),
 * prefix-cache protection for primary Claude seats, and multi-dimensional
 * weighted seat selection (ceiling + expiring-quota discount + cache-stampede
 * affinity).
 *
 * Runtime compatibility:
 *   - Pure ES module for Magpie's embedded moejs engine (no Node builtins).
 *   - Returns `undefined` when no mutation is needed so moejs skips re-marshaling
 *     large request bodies across the JS <-> Go boundary.
 *   - Uses native regex slice sampling (`nonAsciiSampled`) rather than JS char
 *     loops to stay well inside Magpie's 250ms hook / 20ms strategy limits even
 *     on 3 MB+ conversation transcripts.
 */

export const name = "context-budget";
export const version = "1.0.1";
export const description =
  "Provider-aware context budgeting, surgical fallback slimming, and cache-aware weighted seat routing";

export const options = {
  enabled: {
    type: "boolean",
    default: true,
    description: "Enable provider-aware context budgeting and fallback slimming",
  },
  preserveCacheProviders: {
    type: "string",
    default: "claude",
    description:
      "Comma-separated provider IDs where prefix cache stability is strictly preserved unless exceeding the hard window limit",
  },
  safetyRatio: {
    type: "number",
    default: 0.90,
    description: "Fraction of provider context window allowed before slimming triggers",
  },
  defaultReserveOutput: {
    type: "number",
    default: 16384,
    description: "Default output token reservation subtracted from provider window budget",
  },
  keepRecentMessages: {
    type: "number",
    default: 10,
    description: "Number of most recent messages protected during Stage 1 surgical slimming",
  },
  toolResultMaxChars: {
    type: "number",
    default: 2400,
    description: "Max characters retained per older tool_result in Stage 1 (head + tail preserved)",
  },
  oldTextMaxChars: {
    type: "number",
    default: 4000,
    description: "Max characters retained per older text block in Stage 1 (head + tail preserved)",
  },
  ceiling: {
    type: "number",
    default: 88,
    description: "Soft quota usage ceiling (%) before deprioritizing a seat to reserve headroom",
  },
  hardCeiling: {
    type: "number",
    default: 98,
    description: "Hard quota usage ceiling (%) before treating a seat as near-exhausted",
  },
  expiringHorizonMinutes: {
    type: "number",
    default: 90,
    description:
      "Reset horizon (minutes) within which remaining quota receives a use-it-or-lose-it discount",
  },
  expiringMaxDiscount: {
    type: "number",
    default: 28,
    description: "Maximum percentage-point discount applied when a quota window resets imminently",
  },
  stampedeWindowSeconds: {
    type: "number",
    default: 300,
    description:
      "Time window (seconds) to keep sticky affinity on a seat that recently warmed prompt cache",
  },
  accountsFirst: {
    type: "string",
    default: "",
    description:
      "Comma-separated account substrings prioritized before other seats in the same health tier",
  },
};

export const DEFAULT_PROVIDER_WINDOWS = {
  claude: 1000000,
  zcode: 200000,
  "bedrock-glm5": 202752,
  devin: 262144,
  deepseek: 131072,
  grok: 131072,
  "opencode-go": 200000,
  "trae-cn": 200000,
  "trae-global": 200000,
  workbuddy: 200000,
  zed: 200000,
  codex: 272000,
  gemini: 1000000,
  "gemini-cli": 1000000,
};

export const DEFAULT_MODEL_WINDOWS = {
  "claude-haiku-4-5": 200000,
  "claude-haiku-4-5-20251001": 200000,
  "glm-5-turbo": 131072,
  "glm-5.1": 200000,
  "glm-5.3": 200000,
  "GLM-5.1": 200000,
  "GLM-5.3": 200000,
  "deepseek-chat": 131072,
  "deepseek-reasoner": 131072,
};

export const DEFAULT_PROVIDER_MAX_OUTPUT = {
  claude: 64000,
  zcode: 32768,
  "bedrock-glm5": 32768,
  devin: 32768,
  deepseek: 16384,
  grok: 16384,
  "opencode-go": 32768,
};

const seatTelemetry = new Map();
const MAX_TELEMETRY_SEATS = 256;

function parseCsvList(val, fallback = []) {
  if (Array.isArray(val)) {
    return val.map((item) => String(item).trim()).filter(Boolean);
  }
  if (typeof val === "string" && val.trim().length > 0) {
    return val
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return fallback;
}

/**
 * Counts non-ASCII characters using native regex replacement on bounded slices
 * so moejs stays inside native Go string primitives (<2ms on 3MB payloads).
 */
function countNonAsciiSampled(str) {
  const len = str.length;
  if (len === 0) return 0;
  if (len <= 32768) {
    return len - str.replace(/[^\x00-\x7f]+/g, "").length;
  }
  const slices = 16;
  const sliceLen = 2048;
  const step = Math.floor(len / slices);
  let nonAscii = 0;
  for (let i = 0; i < slices; i++) {
    const sub = str.slice(i * step, i * step + sliceLen);
    nonAscii += sub.length - sub.replace(/[^\x00-\x7f]+/g, "").length;
  }
  return Math.round((nonAscii * len) / (slices * sliceLen));
}

export function estimateStringTokens(str) {
  if (!str || typeof str !== "string") return 0;
  const len = str.length;
  if (len === 0) return 0;
  const nonAscii = countNonAsciiSampled(str);
  return Math.ceil((len - nonAscii) / 3.6) + nonAscii;
}

export function estimateBlockTokens(block) {
  if (!block) return 0;
  if (typeof block === "string") return estimateStringTokens(block);
  if (typeof block !== "object") return 4;

  const type = block.type;
  if (type === "text") {
    return estimateStringTokens(block.text || "") + 4;
  }
  if (type === "thinking") {
    return estimateStringTokens(block.thinking || "") + 8;
  }
  if (type === "image" || type === "document") {
    const data = block.source?.data;
    if (typeof data === "string" && data.length > 0) {
      return Math.min(16000, Math.max(1200, Math.ceil(data.length / 750)));
    }
    return 1200;
  }
  if (type === "tool_use") {
    let inputTokens = 12 + estimateStringTokens(block.name || "");
    if (typeof block.input === "string") {
      inputTokens += estimateStringTokens(block.input);
    } else if (block.input && typeof block.input === "object") {
      for (const key of Object.keys(block.input)) {
        const val = block.input[key];
        if (typeof val === "string") {
          inputTokens += estimateStringTokens(val) + 2;
        } else if (val !== null && val !== undefined) {
          inputTokens += 16;
        }
      }
    }
    return inputTokens;
  }
  if (type === "tool_result") {
    const content = block.content;
    if (typeof content === "string") {
      return estimateStringTokens(content) + 12;
    }
    if (Array.isArray(content)) {
      let sum = 12;
      for (let i = 0; i < content.length; i++) {
        sum += estimateBlockTokens(content[i]);
      }
      return sum;
    }
    return 16;
  }
  return 16;
}

export function estimateMessageTokens(msg) {
  if (!msg || typeof msg !== "object") return 0;
  const content = msg.content;
  if (typeof content === "string") {
    return estimateStringTokens(content) + 6;
  }
  if (Array.isArray(content)) {
    let total = 6;
    for (let i = 0; i < content.length; i++) {
      total += estimateBlockTokens(content[i]);
    }
    return total;
  }
  return 6;
}

export function estimateInputTokens(body) {
  if (!body || typeof body !== "object") return 0;
  let total = 0;

  if (typeof body.system === "string") {
    total += estimateStringTokens(body.system) + 8;
  } else if (Array.isArray(body.system)) {
    for (let i = 0; i < body.system.length; i++) {
      total += estimateBlockTokens(body.system[i]);
    }
  }

  if (Array.isArray(body.tools)) {
    total += body.tools.length * 140;
  }

  if (Array.isArray(body.messages)) {
    for (let i = 0; i < body.messages.length; i++) {
      total += estimateMessageTokens(body.messages[i]);
    }
  }

  return total;
}

export function resolveWindowLimit(providerId, model, opts = {}) {
  const customWindows = opts?.windows && typeof opts.windows === "object" ? opts.windows : null;
  const pId = String(providerId || "").trim();
  const mId = String(model || "").trim();

  if (customWindows) {
    if (pId && mId && typeof customWindows[`${pId}/${mId}`] === "number") {
      return customWindows[`${pId}/${mId}`];
    }
    if (mId && typeof customWindows[mId] === "number") {
      return customWindows[mId];
    }
    if (pId && typeof customWindows[pId] === "number") {
      return customWindows[pId];
    }
  }

  if (pId === "bedrock-glm5") {
    return DEFAULT_PROVIDER_WINDOWS["bedrock-glm5"];
  }
  if (mId && typeof DEFAULT_MODEL_WINDOWS[mId] === "number") {
    return DEFAULT_MODEL_WINDOWS[mId];
  }
  if (pId && typeof DEFAULT_PROVIDER_WINDOWS[pId] === "number") {
    return DEFAULT_PROVIDER_WINDOWS[pId];
  }
  return 200000;
}

export function trimHeadTail(text, maxChars, headRatio = 0.58) {
  if (typeof text !== "string" || text.length <= maxChars || maxChars < 64) {
    return text;
  }
  const omitted = text.length - maxChars;
  const marker = `\n...[context-budget: trimmed ${omitted} chars to fit fallback window]...\n`;
  const usable = Math.max(32, maxChars - marker.length);
  const headChars = Math.max(16, Math.floor(usable * headRatio));
  const tailChars = Math.max(16, usable - headChars);
  return text.slice(0, headChars) + marker + text.slice(text.length - tailChars);
}

function slimContentBlock(block, cfg) {
  if (!block || typeof block !== "object") return block;

  if (block.type === "image" || block.type === "document") {
    if (block.source && block.source.type === "base64") {
      cfg.mutated = true;
      return {
        type: "text",
        text: `[context-budget: omitted inline ${block.type} (${block.source.media_type || "binary"}) for constrained provider window]`,
      };
    }
    return block;
  }

  if (block.type === "tool_result") {
    if (typeof block.content === "string") {
      if (block.content.length > cfg.toolResultMaxChars) {
        cfg.mutated = true;
        return {
          ...block,
          content: trimHeadTail(block.content, cfg.toolResultMaxChars, 0.55),
        };
      }
      return block;
    }
    if (Array.isArray(block.content)) {
      let blockMutated = false;
      const nextContent = new Array(block.content.length);
      for (let i = 0; i < block.content.length; i++) {
        const sub = block.content[i];
        if (!sub || typeof sub !== "object") {
          nextContent[i] = sub;
          continue;
        }
        if (sub.type === "image" || sub.type === "document") {
          blockMutated = true;
          nextContent[i] = {
            type: "text",
            text: `[context-budget: omitted tool_result ${sub.type}]`,
          };
        } else if (sub.type === "text" && typeof sub.text === "string" && sub.text.length > cfg.toolResultMaxChars) {
          blockMutated = true;
          nextContent[i] = {
            ...sub,
            text: trimHeadTail(sub.text, cfg.toolResultMaxChars, 0.55),
          };
        } else {
          nextContent[i] = sub;
        }
      }
      if (blockMutated) {
        cfg.mutated = true;
        return { ...block, content: nextContent };
      }
    }
    return block;
  }

  if (block.type === "text" && typeof block.text === "string") {
    if (cfg.trimText && block.text.length > cfg.oldTextMaxChars) {
      cfg.mutated = true;
      return {
        ...block,
        text: trimHeadTail(block.text, cfg.oldTextMaxChars, 0.6),
      };
    }
    return block;
  }

  if (block.type === "thinking" && cfg.dropOldThinking) {
    if (!block.signature && typeof block.thinking === "string" && block.thinking.length > 600) {
      cfg.mutated = true;
      return {
        ...block,
        thinking: trimHeadTail(block.thinking, 600, 0.4),
      };
    }
  }

  if (block.type === "tool_use" && cfg.trimToolInput && block.input && typeof block.input === "object") {
    const heavyKeys = ["content", "new_string", "old_string", "patch", "file_text", "command"];
    let inputMutated = false;
    const nextInput = { ...block.input };
    for (let i = 0; i < heavyKeys.length; i++) {
      const k = heavyKeys[i];
      if (typeof nextInput[k] === "string" && nextInput[k].length > cfg.toolInputMaxChars) {
        nextInput[k] = trimHeadTail(nextInput[k], cfg.toolInputMaxChars, 0.5);
        inputMutated = true;
      }
    }
    if (inputMutated) {
      cfg.mutated = true;
      return { ...block, input: nextInput };
    }
  }

  return block;
}

function slimOlderMessages(messages, cfg) {
  if (!Array.isArray(messages) || messages.length === 0) return messages;
  const cutoff = Math.max(0, messages.length - cfg.keepRecentMessages);
  if (cutoff === 0) return messages;

  const out = messages.slice();
  for (let i = 0; i < cutoff; i++) {
    const msg = out[i];
    if (!msg || typeof msg !== "object") continue;
    const isFirstUser = i === 0 && msg.role === "user";
    const blockCfg = {
      ...cfg,
      trimText: !isFirstUser,
    };

    if (typeof msg.content === "string") {
      if (!isFirstUser && msg.content.length > cfg.oldTextMaxChars) {
        cfg.mutated = true;
        out[i] = {
          ...msg,
          content: trimHeadTail(msg.content, cfg.oldTextMaxChars, 0.6),
        };
      }
    } else if (Array.isArray(msg.content)) {
      const nextBlocks = new Array(msg.content.length);
      for (let j = 0; j < msg.content.length; j++) {
        nextBlocks[j] = slimContentBlock(msg.content[j], blockCfg);
      }
      if (blockCfg.mutated) {
        cfg.mutated = true;
        out[i] = { ...msg, content: nextBlocks };
      }
    }
  }
  return out;
}

function hasToolUse(msg) {
  if (!msg || !Array.isArray(msg.content)) return false;
  for (let i = 0; i < msg.content.length; i++) {
    if (msg.content[i] && msg.content[i].type === "tool_use") return true;
  }
  return false;
}

function hasToolResult(msg) {
  if (!msg || !Array.isArray(msg.content)) return false;
  for (let i = 0; i < msg.content.length; i++) {
    if (msg.content[i] && msg.content[i].type === "tool_result") return true;
  }
  return false;
}

export function partitionTurnGroups(messages, startIdx = 0) {
  const groups = [];
  let i = startIdx;
  while (i < messages.length) {
    const msg = messages[i];
    if (hasToolUse(msg) && i + 1 < messages.length && hasToolResult(messages[i + 1])) {
      groups.push([msg, messages[i + 1]]);
      i += 2;
    } else {
      groups.push([msg]);
      i += 1;
    }
  }
  return groups;
}

function summarizeFoldedGroups(foldedGroups) {
  const toolCounts = new Map();
  const files = [];
  const userNotes = [];
  let foldedMsgCount = 0;

  const fileKeys = ["file_path", "path", "Path", "target_file", "filename"];

  for (let g = 0; g < foldedGroups.length; g++) {
    const group = foldedGroups[g];
    for (let m = 0; m < group.length; m++) {
      const msg = group[m];
      if (!msg) continue;
      foldedMsgCount++;

      if (msg.role === "user" && typeof msg.content === "string") {
        const snippet = msg.content.trim().replace(/\s+/g, " ").slice(0, 140);
        if (snippet && userNotes.length < 6) userNotes.push(snippet);
      } else if (Array.isArray(msg.content)) {
        for (let b = 0; b < msg.content.length; b++) {
          const block = msg.content[b];
          if (!block || typeof block !== "object") continue;
          if (block.type === "tool_use") {
            const tName = block.name || "tool";
            toolCounts.set(tName, (toolCounts.get(tName) || 0) + 1);
            if (block.input && typeof block.input === "object" && files.length < 16) {
              for (let k = 0; k < fileKeys.length; k++) {
                const candidate = block.input[fileKeys[k]];
                if (typeof candidate === "string" && candidate.length > 0 && !files.includes(candidate)) {
                  files.push(candidate);
                }
              }
            }
          } else if (
            msg.role === "user" &&
            block.type === "text" &&
            typeof block.text === "string" &&
            userNotes.length < 6 &&
            !block.text.startsWith("<system-reminder>")
          ) {
            const snippet = block.text.trim().replace(/\s+/g, " ").slice(0, 140);
            if (snippet) userNotes.push(snippet);
          }
        }
      }
    }
  }

  const toolSummary = Array.from(toolCounts.entries())
    .map(([k, v]) => `${k}(×${v})`)
    .join(", ");

  const parts = [
    `[context-budget: folded ${foldedMsgCount} middle messages to fit fallback context window]`,
  ];
  if (toolSummary) parts.push(`Tools executed: ${toolSummary}`);
  if (files.length > 0) parts.push(`Files touched: ${files.join(", ")}`);
  if (userNotes.length > 0) parts.push(`Intermediate prompts: ${userNotes.join(" | ")}`);
  return parts.join("\n");
}

export function foldMiddleTurns(messages, baseOverheadTokens, inputBudget) {
  if (!Array.isArray(messages) || messages.length <= 3) return messages;

  const firstMsg = messages[0];
  const firstTokens = estimateMessageTokens(firstMsg);
  const groups = partitionTurnGroups(messages, 1);
  if (groups.length <= 1) return messages;

  const groupTokens = groups.map((grp) =>
    grp.reduce((acc, m) => acc + estimateMessageTokens(m), 0)
  );

  const tailBudget = Math.max(
    2048,
    inputBudget - baseOverheadTokens - firstTokens - 500
  );

  let keptTokens = 0;
  let keepFromGroupIdx = groups.length;

  for (let i = groups.length - 1; i >= 0; i--) {
    if (keptTokens + groupTokens[i] <= tailBudget || keepFromGroupIdx === groups.length) {
      keptTokens += groupTokens[i];
      keepFromGroupIdx = i;
    } else {
      break;
    }
  }

  if (keepFromGroupIdx <= 0) {
    return messages;
  }

  const foldedGroups = groups.slice(0, keepFromGroupIdx);
  const tailGroups = groups.slice(keepFromGroupIdx);
  const digestText = summarizeFoldedGroups(foldedGroups);

  const tailMessages = [];
  for (let i = 0; i < tailGroups.length; i++) {
    for (let j = 0; j < tailGroups[i].length; j++) {
      tailMessages.push(tailGroups[i][j]);
    }
  }

  const result = [firstMsg];
  const firstTailRole = tailMessages[0]?.role;

  if (firstTailRole === "user") {
    result.push({
      role: "assistant",
      content: [{ type: "text", text: digestText }],
    });
  } else {
    result.push({
      role: "assistant",
      content: [
        {
          type: "text",
          text: "[context-budget: acknowledging initial task before folded middle history]",
        },
      ],
    });
    result.push({
      role: "user",
      content: [{ type: "text", text: digestText }],
    });
  }

  for (let i = 0; i < tailMessages.length; i++) {
    result.push(tailMessages[i]);
  }
  return result;
}

function clampOutputAndThinking(body, inputTokens, windowLimit, providerId, opts = {}) {
  let mutated = false;
  const safetyRatio = Number(opts.safetyRatio) > 0 ? Number(opts.safetyRatio) : 0.90;
  const hardSafeWindow = Math.floor(windowLimit * Math.min(0.97, safetyRatio + 0.05));
  const providerMaxOut = DEFAULT_PROVIDER_MAX_OUTPUT[providerId] || 32768;
  const availableForOutput = Math.max(1024, hardSafeWindow - inputTokens);

  const currentMaxTokens =
    typeof body.max_tokens === "number" && body.max_tokens > 0
      ? body.max_tokens
      : Math.min(providerMaxOut, Number(opts.defaultReserveOutput) || 16384);

  const clampedMaxTokens = Math.min(currentMaxTokens, providerMaxOut, availableForOutput);
  if (typeof body.max_tokens === "number" && body.max_tokens !== clampedMaxTokens) {
    body.max_tokens = clampedMaxTokens;
    mutated = true;
  }

  if (body.thinking && typeof body.thinking === "object") {
    if (typeof body.thinking.budget_tokens === "number") {
      if (clampedMaxTokens <= 2048) {
        delete body.thinking;
        mutated = true;
      } else if (body.thinking.budget_tokens >= clampedMaxTokens) {
        body.thinking = {
          ...body.thinking,
          budget_tokens: Math.max(1024, clampedMaxTokens - 1024),
        };
        mutated = true;
      }
    }
  }
  return mutated;
}

export function onProvider(body, ctx) {
  const opts = ctx?.options || {};
  if (opts.enabled === false || opts.off === true) return undefined;
  if (!body || typeof body !== "object" || !Array.isArray(body.messages)) return undefined;

  const providerId = String(ctx?.provider?.id || "").trim();
  const model = String(ctx?.provider?.model || body.model || "").trim();
  const windowLimit = resolveWindowLimit(providerId, model, opts);

  // O(1) fast path for primary Claude 1M seats: preserve 100% prefix cache stability
  // without traversing or re-serializing the body in moejs.
  const preserveSet = new Set(parseCsvList(opts.preserveCacheProviders, ["claude"]));
  if (preserveSet.has(providerId) && windowLimit >= 900000 && !opts.enforceClaudeCeiling) {
    return undefined;
  }

  const safetyRatio =
    Number(opts.safetyRatio) > 0 && Number(opts.safetyRatio) <= 0.98
      ? Number(opts.safetyRatio)
      : 0.90;
  const reserveOutput =
    Number(opts.defaultReserveOutput) > 0 ? Number(opts.defaultReserveOutput) : 16384;

  const safeTotalTokens = Math.floor(windowLimit * safetyRatio);
  const inputBudget = Math.max(8192, safeTotalTokens - reserveOutput);

  const initialInputTokens = estimateInputTokens(body);

  if (preserveSet.has(providerId) && initialInputTokens <= inputBudget) {
    return undefined;
  }

  if (initialInputTokens <= inputBudget) {
    const clamped = clampOutputAndThinking(body, initialInputTokens, windowLimit, providerId, opts);
    return clamped ? body : undefined;
  }

  let changed = false;

  // Stage 1: Surgical slimming of older tool_result payloads, base64 images, and oversized text blocks
  const keepRecent1 =
    Number(opts.keepRecentMessages) >= 2 ? Number(opts.keepRecentMessages) : 10;
  const toolMax1 =
    Number(opts.toolResultMaxChars) >= 200 ? Number(opts.toolResultMaxChars) : 2400;
  const textMax1 =
    Number(opts.oldTextMaxChars) >= 400 ? Number(opts.oldTextMaxChars) : 4000;

  const stage1Cfg = {
    keepRecentMessages: keepRecent1,
    toolResultMaxChars: toolMax1,
    oldTextMaxChars: textMax1,
    trimToolInput: false,
    toolInputMaxChars: 2400,
    dropOldThinking: providerId !== "claude",
    mutated: false,
  };
  body.messages = slimOlderMessages(body.messages, stage1Cfg);
  if (stage1Cfg.mutated) changed = true;

  let currentTokens = estimateInputTokens(body);

  // Stage 2: Tighter head/tail bounds + oversized tool_use.input trimming
  if (currentTokens > inputBudget) {
    const stage2Cfg = {
      keepRecentMessages: Math.min(6, keepRecent1),
      toolResultMaxChars: Math.min(800, toolMax1),
      oldTextMaxChars: Math.min(1200, textMax1),
      trimToolInput: true,
      toolInputMaxChars: 900,
      dropOldThinking: true,
      mutated: false,
    };
    body.messages = slimOlderMessages(body.messages, stage2Cfg);
    if (stage2Cfg.mutated) changed = true;
    currentTokens = estimateInputTokens(body);
  }

  // Stage 3: Pair-safe middle turn folding when payload still exceeds fallback window
  if (currentTokens > inputBudget && body.messages.length > 4) {
    const messagesOnlyTokens = body.messages.reduce(
      (sum, m) => sum + estimateMessageTokens(m),
      0
    );
    const baseOverhead = Math.max(0, currentTokens - messagesOnlyTokens);
    const beforeLen = body.messages.length;
    body.messages = foldMiddleTurns(body.messages, baseOverhead, inputBudget);
    if (body.messages.length !== beforeLen) changed = true;
    currentTokens = estimateInputTokens(body);
  }

  // Stage 4: Clamp max_tokens & thinking.budget_tokens so input + output never overflows provider window
  if (clampOutputAndThinking(body, currentTokens, windowLimit, providerId, opts)) {
    changed = true;
  }
  return changed ? body : undefined;
}

function pruneEvents(events, cutoffMs) {
  let idx = 0;
  while (idx < events.length && events[idx].ts < cutoffMs) {
    idx++;
  }
  return idx > 0 ? events.slice(idx) : events;
}

export function onUsage(row, opts = {}) {
  if (!row || typeof row !== "object") return;
  const seatId = row.key || row.account;
  if (!seatId) return;

  const nowMs = row.time ? Date.parse(row.time) || Date.now() : Date.now();
  const windowSec = Number(opts?.stampedeWindowSeconds) > 0 ? Number(opts.stampedeWindowSeconds) : 300;
  const cutoffMs = nowMs - windowSec * 1000;

  let entry = seatTelemetry.get(seatId);
  if (!entry) {
    if (seatTelemetry.size >= MAX_TELEMETRY_SEATS) {
      const oldestKey = seatTelemetry.keys().next().value;
      if (oldestKey !== undefined) seatTelemetry.delete(oldestKey);
    }
    entry = {
      account: row.account || "",
      events: [],
      lastCacheWriteAt: 0,
      lastCacheReadAt: 0,
      lastErrorAt: 0,
    };
    seatTelemetry.set(seatId, entry);
  }

  entry.events = pruneEvents(entry.events, cutoffMs);
  const cw = Number(row.cacheWrite) || 0;
  const cr = Number(row.cacheRead) || 0;
  const isErr = Number(row.status) >= 429 || Boolean(row.error);

  entry.events.push({
    ts: nowMs,
    cacheWrite: cw,
    cacheRead: cr,
    error: isErr ? 1 : 0,
  });

  if (cw > 0) entry.lastCacheWriteAt = nowMs;
  if (cr > 0) entry.lastCacheReadAt = nowMs;
  if (isErr) entry.lastErrorAt = nowMs;

  if (row.account && row.account !== seatId) {
    seatTelemetry.set(row.account, entry);
  }
}

export function getSeatTelemetrySnapshot(seatId, nowMs = Date.now(), windowSec = 300) {
  const entry = seatTelemetry.get(seatId);
  if (!entry) {
    return {
      recentCacheWrite: 0,
      recentCacheRead: 0,
      recentErrors: 0,
      lastCacheWriteAt: 0,
      lastErrorAt: 0,
    };
  }
  const cutoffMs = nowMs - windowSec * 1000;
  let recentCacheWrite = 0;
  let recentCacheRead = 0;
  let recentErrors = 0;
  for (let i = 0; i < entry.events.length; i++) {
    const ev = entry.events[i];
    if (ev.ts >= cutoffMs) {
      recentCacheWrite += ev.cacheWrite;
      recentCacheRead += ev.cacheRead;
      recentErrors += ev.error;
    }
  }
  return {
    recentCacheWrite,
    recentCacheRead,
    recentErrors,
    lastCacheWriteAt: entry.lastCacheWriteAt,
    lastErrorAt: entry.lastErrorAt,
  };
}

export function resetSeatTelemetryForTests() {
  seatTelemetry.clear();
}

function computeExpiringDiscount(seat, nowMs, horizonMinutes, maxDiscount) {
  if (!seat || !Array.isArray(seat.soon) || seat.soon.length === 0) return 0;
  const horizonMs = horizonMinutes * 60 * 1000;
  if (horizonMs <= 0) return 0;

  let nearestDeltaMs = Infinity;
  for (let i = 0; i < seat.soon.length; i++) {
    const resetMs = Number(seat.soon[i]);
    if (resetMs > nowMs) {
      const delta = resetMs - nowMs;
      if (delta < nearestDeltaMs) nearestDeltaMs = delta;
    }
  }

  if (nearestDeltaMs > horizonMs) return 0;
  const urgency = 1 - nearestDeltaMs / horizonMs;
  return urgency * maxDiscount;
}

function matchesAccountPriority(seat, priorityPatterns) {
  if (!priorityPatterns || priorityPatterns.length === 0) return -1;
  const acct = String(seat?.account || seat?.key || "").toLowerCase();
  for (let i = 0; i < priorityPatterns.length; i++) {
    if (acct.includes(priorityPatterns[i].toLowerCase())) {
      return i;
    }
  }
  return -1;
}

export function weightedSeatStrategy(pool, seats, opts = {}) {
  if (!Array.isArray(seats) || seats.length === 0) return [];
  if (seats.length === 1) return [0];

  const ceiling = Number(opts.ceiling) > 0 ? Number(opts.ceiling) : 88;
  const hardCeiling = Number(opts.hardCeiling) > ceiling ? Number(opts.hardCeiling) : 98;
  const horizonMin =
    Number(opts.expiringHorizonMinutes) >= 0 ? Number(opts.expiringHorizonMinutes) : 90;
  const maxDiscount =
    Number(opts.expiringMaxDiscount) >= 0 ? Number(opts.expiringMaxDiscount) : 28;
  const stampedeSec =
    Number(opts.stampedeWindowSeconds) > 0 ? Number(opts.stampedeWindowSeconds) : 300;
  const priorityList = parseCsvList(opts.accountsFirst, []);
  const nowMs = Number(opts._nowMs) || Date.now();

  const scored = seats.map((seat, idx) => {
    const rawUsed = typeof seat?.used === "number" ? seat.used : 0;
    const isResting = Boolean(seat?.resting);
    const discount = computeExpiringDiscount(seat, nowMs, horizonMin, maxDiscount);
    const effectiveUsed = Math.max(0, rawUsed - discount);

    const telem =
      getSeatTelemetrySnapshot(seat?.key, nowMs, stampedeSec).lastCacheWriteAt > 0 ||
      getSeatTelemetrySnapshot(seat?.key, nowMs, stampedeSec).recentErrors > 0
        ? getSeatTelemetrySnapshot(seat?.key, nowMs, stampedeSec)
        : getSeatTelemetrySnapshot(seat?.account, nowMs, stampedeSec);

    const hasWarmCache =
      telem.recentCacheWrite > 20000 || telem.recentCacheRead > 50000;
    const cacheAffinityBonus = hasWarmCache && rawUsed < hardCeiling ? 14 : 0;

    const prioIdx = matchesAccountPriority(seat, priorityList);
    const prioBonus = prioIdx >= 0 ? (priorityList.length - prioIdx) * 8 : 0;
    const errorPenalty = telem.recentErrors * 25;

    let tier = 0;
    if (isResting || rawUsed >= 100) {
      tier = 3;
    } else if (rawUsed >= hardCeiling) {
      tier = 2;
    } else if (effectiveUsed >= ceiling) {
      tier = 1;
    }

    const compositeScore =
      effectiveUsed - cacheAffinityBonus - prioBonus + errorPenalty;

    return {
      idx,
      tier,
      compositeScore,
      rawUsed,
    };
  });

  scored.sort((a, b) => {
    if (a.tier !== b.tier) return a.tier - b.tier;
    if (Math.abs(a.compositeScore - b.compositeScore) > 0.001) {
      return a.compositeScore - b.compositeScore;
    }
    return a.idx - b.idx;
  });

  return scored.map((item) => item.idx);
}

export function ceilingSeatStrategy(pool, seats, opts = {}) {
  return weightedSeatStrategy(pool, seats, {
    ...opts,
    stampedeWindowSeconds: 1,
  });
}

export const strategies = {
  weighted: weightedSeatStrategy,
  ceiling: ceilingSeatStrategy,
};
