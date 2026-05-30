---
name: searchpo-plugin-check
description: Validate the Searchpo agent plugin and skill bundle. Use when checking plugin health, bridge sync, skill frontmatter, resolver consistency, OpenClaw-style manifest readiness, or after editing AGENTS.md, openclaw.plugin.json, tools/skill-bridge-map.json, tools/sync-agent-skills.js, or any skills/*/SKILL.md file.
version: 1.0.0
triggers:
  - "plugin check"
  - "agent plugin"
  - "skills check"
  - "skill health"
  - "OpenClaw plugin"
  - "gbrain style"
  - "bridge sync"
tools:
  - shell
mutating: false
---

# Searchpo Plugin Check

Validate that Searchpo still behaves like a plugin-style agent skill bundle.

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

- `openclaw.plugin.json` lists every installable skill and shared dependency.
- Every listed skill has `SKILL.md` with `name`, `description`, `triggers`, `tools`, and `mutating`.
- `tools/skill-bridge-map.json` contains the same skill names as the plugin manifest.
- `.claude/skills/` and `.codex/skills/` match the `skills/` source after `npm run skills:sync`.
- Codex user-level skill symlinks point back to this repo unless `--project-only` is used.

## Output

Report the failing file and command. Do not print `.env` values. Do not use this skill to run provider, Lambda, or live publish flows.
