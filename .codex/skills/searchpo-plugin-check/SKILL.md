---
name: searchpo-plugin-check
description: Validate the Searchpo Claude/Codex agent bridges, slash commands, and skill bundle. Use when checking bridge health, skill frontmatter, command mirrors, agent mirrors, resolver consistency, or after editing AGENTS.md, tools/skill-bridge-map.json, tools/sync-agent-skills.js, commands/*.md, agents/*.md, or any skills/*/SKILL.md file.
version: 1.0.0
triggers:
  - "bridge check"
  - "agent check"
  - "skills check"
  - "skill health"
  - "gbrain style"
  - "bridge sync"
tools:
  - shell
mutating: false
---

# Searchpo Bridge Check

Validate that Searchpo still exposes the same Claude/Codex skills, commands, and three-agent team.

## Workflow

Run:

```bash
npm run agent-plugin:check
npm run skills:check
```

For broader repo safety after code edits, also run:

```bash
npm run ci:static
```

## What Must Pass

- Every listed skill has `SKILL.md` with `name`, `description`, `triggers`, `tools`, and `mutating`.
- `tools/skill-bridge-map.json` lists every source skill, slash command, shared dependency, and exactly three agents: `searchpo-main-agent`, `searchpo-research-agent`, and `searchpo-impl-agent`.
- `agents/searchpo-main-agent.md`, `agents/searchpo-research-agent.md`, and `agents/searchpo-impl-agent.md` have `name`, `description`, `tools`, and non-empty instructions.
- `.claude/skills/` and `.codex/skills/` match the `skills/` source after `npm run skills:sync`.
- `.claude/commands/` and `.codex/commands/` match the `commands/` source after `npm run skills:sync`.
- `.claude/agents/` matches the `agents/` source after `npm run skills:sync`.
- `.codex/agents/` and `/Users/sunfl/.codex/agents/searchpo-*.toml` are generated from `agents/` after `npm run skills:sync`.
- Codex user-level skill symlinks point back to this repo unless `--project-only` is used.

## Output

Report the failing file and command. Do not print `.env` values. Do not use this skill to run provider, Lambda, or live publish flows.
