# Searchpo Skill Resolver

This is the dispatcher for the Searchpo skill bundle. Read the matching `SKILL.md` before acting. If two skills match, read both and keep the main/impl ownership split intact.

## Routing

| Trigger | Skill |
| --- | --- |
| Full Searchpo flow, daily radar, topic-mode run, release gate, publish decision | `skills/searchpo-main-agent/SKILL.md` |
| Run scripts, provider adapters, Remotion render, Gemini audit, Douyin check/upload | `skills/searchpo-impl-agent/SKILL.md` |
| Edit `src/`, captions, cover, Remotion metadata, render quality, Lambda render | `skills/remotion-best-practices/SKILL.md` |
| Validate plugin manifest, skill frontmatter, bridge sync, install health | `skills/searchpo-plugin-check/SKILL.md` |

## Dispatch Rules

1. Prefer the most specific skill.
2. Keep live publishing behind an explicit user request for the current run.
3. Treat `skills/` as source of truth; bridge directories are generated.
4. Use `openclaw.plugin.json` as the installable bundle manifest.
5. Run `npm run skills:check` after skill or manifest edits.

## Shared Conventions

- `skills/_AGENT_README.md` explains the local skill directory contract.
- `config/searchpo_policy.json` owns keyword, copy, scoring, and provider-prompt policy.
- Runtime artifacts under `runtime/` are evidence, not durable source.
