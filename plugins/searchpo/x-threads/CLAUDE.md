# Claude Code Entry Point

This repository is an agent skillpack/plugin for producing responsible
Agent-engineering-positioned X content packs from technical sources, profile
prompts, and support/KYC complaint rewrites.

Read in this order:

1. `AGENTS.md`
2. `INSTALL_FOR_AGENTS.md`
3. `skills/RESOLVER.md`
4. `skills/github-repo-to-x-threads/SKILL.md`

The canonical reusable skill is `skills/github-repo-to-x-threads/`. The
`.claude/` directory is a generated local adapter only; do not edit it as the
source of truth.

Use `commands/github-repo-to-x-threads.md` as the slash-command adapter, and use
`scripts/install_skill_bundle.sh /Users/sunfl/Documents/media/X` when validating
local Claude/Codex install surfaces.
