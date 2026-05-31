# Searchpo Installation Guide for AI Agents

Read `AGENTS.md` first. This file is the short install and verification path for Claude Code and Codex agent hosts.

## Step 1: Install Dependencies

```bash
npm install
```

Optional provider and publish credentials live in `.env`. Never print secret values. Contract mode does not require DeepSeek, Gemini, AWS, Lambda, or live Douyin credentials.

## Step 2: Load Skills

Searchpo skills are first-class files in this repo:

```text
skills/
  RESOLVER.md
  _AGENT_README.md
  searchpo-main-agent/SKILL.md
  searchpo-impl-agent/SKILL.md
  remotion-best-practices/SKILL.md
  searchpo-plugin-check/SKILL.md
```

Searchpo slash commands are first-class files in this repo:

```text
commands/
  searchpo-full-flow.md
```

Searchpo agent-team definitions are first-class files in this repo:

```text
agents/
  searchpo-main-agent.md
  searchpo-research-agent.md
  searchpo-impl-agent.md
```

Generated host mirrors are derived from `skills/`, `commands/`, and `agents/`:

```bash
npm run skills:sync
npm run skills:check
```

Do not edit `.claude/skills/*`, `.codex/skills/*`, `.claude/commands/*`, `.codex/commands/*`, `.claude/agents/*`, `.codex/agents/*`, or `~/.codex/agents/searchpo-*.toml` directly.

## Step 3: Verify Plugin Health

```bash
npm run agent-plugin:check
npm run ci:static
```

`agent-plugin:check` validates skill paths, command paths, agent paths, shared deps, frontmatter routing metadata, and the bridge map. `ci:static` adds TypeScript, JSON, Python compile, shell syntax, and live-publish guard checks.

## Step 4: Run the Safe Flow

```bash
npm run e2e
```

This is the default contract flow: local render, manifest-level Douyin check, no live upload.

Only use higher-side-effect tiers when the operator explicitly asks:

```bash
npm run e2e:provider
npm run e2e:lambda
npm run e2e:live
```

Live publish requires an explicit current-run request and `SEARCHPO_DOUYIN_LIVE=1`.
