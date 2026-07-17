# searchpo Agent Workbench Source Of Truth

This repo treats project skills, commands, and agent definitions as the durable Claude/Codex interface. Claude Code and Codex bridges are generated from the same source so the two hosts do not drift.

## Durable Sources

| Layer | Source | Notes |
| --- | --- | --- |
| Bridge map | `tools/skill-bridge-map.json` | Stable mapping from source skill/command/agent names to Claude and Codex bridge paths. |
| Agent install protocol | `INSTALL_FOR_AGENTS.md` | Short setup and verification path for Claude Code and Codex hosts. |
| Cross-host rules | `AGENTS.md` | Codex-readable operating instructions. Keep host-neutral rules here. |
| Claude host rules | `CLAUDE.md` | Claude Code entry rules. Keep only Claude-specific notes here when they diverge. |
| Project skills | `skills/*/SKILL.md` | True source for Searchpo agent behavior. Edit these first. |
| Slash commands | `commands/*.md` | True source for cross-host slash command entrypoints such as `/searchpo-full-flow`. |
| Agent definitions | `agents/*.md` | True source for the three-agent team: `searchpo-main-agent` lead, `searchpo-research-agent` research teammate, and `searchpo-impl-agent` implementation teammate. |
| Agent-team alignment | `docs/agent-team-alignment.md` | Claude/Codex mechanism mapping and operational prompt contract. |
| Skill resolver/shared deps | `skills/RESOLVER.md`, `skills/_AGENT_README.md` | Dispatcher and local skill-directory contract copied into host bridges. |
| Bridge scripts | `tools/sync-*-skills.js` | Regenerate mirrors and install Codex user-level symlinks. |

## Current Skill Set

| Skill | Trigger Surface | Owner |
| --- | --- | --- |
| `searchpo-main-agent` | End-to-end Searchpo runs, release gates, publish decisions | Main agent |
| `searchpo-research-agent` | AnySearch enrichment, source maps, FactBank, TopicBrief, cross-check evidence | Research agent |
| `searchpo-impl-agent` | Script execution, Remotion render, Gemini audit, Douyin check/upload | Implementation agent |
| `remotion-best-practices` | Editing `src/`, render settings, animation, captions, video output | Remotion editing agent |
| `searchpo-plugin-check` | Claude/Codex bridge map, resolver, frontmatter, and mirror health | Agent workbench maintainer |

## Current Agent Team

| Agent | Host Bridge | Owner |
| --- | --- | --- |
| `searchpo-main-agent` | `.claude/agents/searchpo-main-agent.md`, `.codex/agents/searchpo-main-agent.toml`, `~/.codex/agents/searchpo-main-agent.toml` | Team lead, task assignment, release gates, publish decision |
| `searchpo-research-agent` | `.claude/agents/searchpo-research-agent.md`, `.codex/agents/searchpo-research-agent.toml`, `~/.codex/agents/searchpo-research-agent.toml` | Teammate, AnySearch enrichment, source maps, FactBank, TopicBrief, cross-check evidence |
| `searchpo-impl-agent` | `.claude/agents/searchpo-impl-agent.md`, `.codex/agents/searchpo-impl-agent.toml`, `~/.codex/agents/searchpo-impl-agent.toml` | Teammate, scripts, DeepSeek, Remotion, Gemini, Douyin execution |

## Bridge Policy

- Edit `skills/*` first.
- Edit `commands/*` first when adding or changing slash commands.
- Edit `agents/*` first when adding or changing Claude/Codex agent-team behavior.
- Keep `skills/RESOLVER.md` and `tools/skill-bridge-map.json` in sync when adding or removing skills, commands, or agents.
- Run `npm run skills:sync` after skill, command, or agent edits.
- Treat `.claude/skills/*` and `.codex/skills/*` as generated mirrors.
- Treat `.claude/commands/*` and `.codex/commands/*` as generated mirrors.
- Treat `.claude/agents/*`, `.codex/agents/*`, and `/Users/sunfl/.codex/agents/searchpo-*.toml` as generated mirrors.
- Treat `/Users/sunfl/.codex/skills/searchpo-*` as Codex discovery symlinks back to this repo.
- Treat `tools/skill-bridge-map.json` `agentTeam` as declarative ownership metadata, not a Claude runtime team config.
- Do not maintain long-form instructions only inside a bridge.

## Verification

Use:

```bash
npm run agent-plugin:check
npm run skills:check
npm run ci:static
```

`agent-plugin:check` verifies source skills, commands, agents, shared deps, and bridge-map coverage. `skills:check` verifies frontmatter, project bridge mirrors, command mirrors, agent mirrors, shared deps, and Codex user-level symlinks/agent files. `ci:static` verifies project contracts and safe command wiring.
