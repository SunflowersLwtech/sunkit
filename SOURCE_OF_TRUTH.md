# searchpo Agent Workbench Source Of Truth

This repo treats project skills as the durable agent interface. Claude Code and Codex bridges are generated from the same source so the two hosts do not drift.

## Durable Sources

| Layer | Source | Notes |
| --- | --- | --- |
| Plugin manifest | `openclaw.plugin.json` | Installable bundle metadata: skills, shared deps, safe commands, and live-publish guard contract. |
| Agent install protocol | `INSTALL_FOR_AGENTS.md` | Short setup and verification path for plugin-style agent hosts. |
| Cross-host rules | `AGENTS.md` | Codex-readable operating instructions. Keep host-neutral rules here. |
| Claude host rules | `CLAUDE.md` | Claude Code entry rules. Keep only Claude-specific notes here when they diverge. |
| Project skills | `skills/*/SKILL.md` | True source for Searchpo agent behavior. Edit these first. |
| Skill resolver/shared deps | `skills/RESOLVER.md`, `skills/_AGENT_README.md` | Dispatcher and local skill-directory contract copied into host bridges. |
| Bridge map | `tools/skill-bridge-map.json` | Stable mapping from source skill names to Claude and Codex bridge paths. |
| Bridge scripts | `tools/sync-*-skills.js` | Regenerate mirrors and install Codex user-level symlinks. |

## Current Skill Set

| Skill | Trigger Surface | Owner |
| --- | --- | --- |
| `searchpo-main-agent` | End-to-end Searchpo runs, release gates, publish decisions | Main agent |
| `searchpo-impl-agent` | Script execution, Remotion render, Gemini audit, Douyin check/upload | Implementation agent |
| `remotion-best-practices` | Editing `src/`, render settings, animation, captions, video output | Remotion editing agent |
| `searchpo-plugin-check` | Plugin manifest, resolver, frontmatter, and bridge health | Agent workbench maintainer |

## Bridge Policy

- Edit `skills/*` first.
- Keep `openclaw.plugin.json`, `skills/RESOLVER.md`, and `tools/skill-bridge-map.json` in sync when adding or removing skills.
- Run `npm run skills:sync` after skill edits.
- Treat `.claude/skills/*` and `.codex/skills/*` as generated mirrors.
- Treat `/Users/sunfl/.codex/skills/searchpo-*` as Codex discovery symlinks back to this repo.
- Do not maintain long-form instructions only inside a bridge.

## Verification

Use:

```bash
npm run agent-plugin:check
npm run skills:check
npm run ci:static
```

`agent-plugin:check` verifies manifest, shared deps, skill metadata, and bridge-map coverage. `skills:check` verifies frontmatter, project bridge mirrors, shared deps, and Codex user-level symlinks. `ci:static` verifies project contracts and safe command wiring.
