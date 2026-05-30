# Searchpo Installation Guide for AI Agents

Read `AGENTS.md` first. This file is the short install and verification path for an agent host that wants to load Searchpo as a plugin-style skill bundle.

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

Generated host mirrors are derived from `skills/`:

```bash
npm run skills:sync
npm run skills:check
```

Do not edit `.claude/skills/*` or `.codex/skills/*` directly.

## Step 3: Verify Plugin Health

```bash
npm run agent-plugin:check
npm run ci:static
```

`agent-plugin:check` validates `openclaw.plugin.json`, skill paths, shared deps, frontmatter routing metadata, and the bridge map. `ci:static` adds TypeScript, JSON, Python compile, shell syntax, and live-publish guard checks.

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
