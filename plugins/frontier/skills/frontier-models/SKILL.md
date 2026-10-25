---
name: frontier-models
description: The models and harnesses this machine can reach beyond its own Claude seat, and how to use them. Covers the magpie gateway (llm-gateway) and its routing groups, switching a claude-gw session to GPT-6.1 Sol, Grok 4.7, Kimi, GLM, DeepSeek, Qwen or Doubao, and the subagents agy-pro, agy-trial, zen, zcode and frontier. Fires on 「用 GPT/Grok/Gemini/GLM/Kimi/DeepSeek/Qwen」「换个模型」「有哪些模型」「magpie」「网关」「路由组」「降级」「让 Antigravity/OpenCode/ZCode 做」「出图」「看视频」, "which models can I use", "ask GPT", "second opinion from another model", "route through the gateway".
---

# Frontier models and harnesses

Plain `claude` talks to Anthropic on this machine's Claude seat. Everything else goes through one of two doors.

## 1. The magpie gateway: other models inside Claude Code

`claude-gw` starts a Claude Code session on the gateway (llm-gateway, `http://100.116.218.86:3425`; this machine's key is in `~/.claude/magpie-settings.json`). The `/model` picker in a claude-gw session lists the frontier rows below; `/model <id>` takes any id `harness-run models` prints.

Routing groups (magpie `routing=order`, `stays=session`: one member per session for the prompt cache, the next member when it fails or runs out):

| id | chain |
|---|---|
| `claude-opus-5-5` (Opus row, claude-gw's default) | Opus 5.5 on the three Claude Team seats → Kiro Opus 5.5 → `claude-sonnet-5-5` |
| `claude-sonnet-5-5` | Sonnet 5.5 on the seats → Zed Sonnet 5.5 → Kiro Sonnet 5.5 → `frontier` |
| `claude-haiku-5-5` | Haiku 5.5 on the seats → Zed Haiku 5.5 → Kiro Haiku 5.5 → DeepSeek V4.1 Flash → GLM-5.3 Flash → Go Haiku |
| `claude-fable-5-1` | `claude-opus-5-5` (no Fable on the gateway) |
| `frontier` | GPT-6.1 Sol (Zed) → Grok 4.7 → GPT-6 Sol → GPT-6.1 Sol (Trae) → Kimi K3.1 Pro → GLM-5.3 → DeepSeek V4 Pro → Qwen3.8 Max → MiniMax M3 → Doubao Seed 2.1 Pro → the OpenCode Go copies |
| `auto/<model>` (magpie finds these) | one model on whichever subscription renews soonest and has quota, e.g. `auto/gpt-6.1-sol`, `auto/glm-5.3`, `auto/kimi-k3.1-pro`, `auto/deepseek-v4-pro`, `auto/qwen3.8-max` |

Subscriptions behind it: Kiro Student (1000 credits a month), Zed Student, Grok (SuperGrok), WorkBuddy free, Trae CN and Trae Global, OpenCode Go, Copilot Student (only `copilot/auto`; named models are refused on the Student plan). The Claude seats are served by magpie's subscription bridge (a Claude Code process on the server per conversation), each capped at 95% of its five hours. A session stays on one seat; when that seat is used up it moves to the next seat, and the move retells the whole conversation to a new process once, which costs a full cache write (up to 835K tokens for a long session; on the first night one seat's five hours went in under 40 minutes this way). So the gateway keeps conversations of about 200K tokens or more off the seats: they go to the same chain without the seats (`long-opus`, `long-sonnet`, `long-haiku`), and wait there when it is all out of allowance. Never point an already-running session at the gateway, and prefer a new claude-gw session to resuming a long one.

Known gaps: Gemini through the gateway fails with Claude Code's tools (the Zed plugin sends `AUTO` where Zed wants `auto`); use agy for Gemini. A non-Claude id makes Claude Code assume a 200K window.

## 2. Harness subagents: a task in another official client

Each runs `harness-run` (this plugin's `bin/`), returns the answer and any files, and never retries on another account.

| subagent | client, account, where | good for |
|---|---|---|
| `agy-pro` | Antigravity, weiliu0607 (AI Pro, paid), on m2 | images, video, audio, Gemini 4 Argon, Antigravity's Opus 5.5 |
| `agy-trial` | Antigravity, devweiliu0607 (Samsung trial), on M4 | the same, a separate quota |
| `zen` | OpenCode CLI here, Zen free models (DeepSeek V4.1 Flash / GLM-5.3 Flash Free, zero retention) | cheap second opinions, reviews, small edits |
| `zcode` | ZCode CLI on M4, Z.ai account | GLM in Z.ai's own client (needs a plan first) |
| `frontier` | headless Claude Code on the gateway | GPT, Grok, Kimi, GLM, DeepSeek, Qwen with Claude Code's tools |

agy and zcode run in a job folder on their Mac (`~/.harness-jobs/`), so send files with the task; zen and frontier work in the current folder and only read unless told to edit. `harness-run status agy-pro|agy-trial` reads Antigravity's quota.

## Rules

- Each subscription is used through its own official client or the gateway plugin magpie ships for it. Antigravity, Zen's free tier and ZCode's Start Plan forbid other clients, so they appear only as subagents running their own CLI, never as gateway models.
- One account per run: when agy-pro is out of quota, report it; don't move the task to agy-trial on your own.
- The Feishu secretary (N150) stays on Opus 5.5 on the three Claude Team seats; seat-guard moves it between seats, and only when all three are used up does it go to the gateway (cc-connect provider `magpie`, model `claude-opus-5-5`).
