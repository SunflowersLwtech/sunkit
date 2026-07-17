# Searchpo Skill Resolver

This is the dispatcher for the Searchpo skill bundle. Read the matching `SKILL.md` before acting. If two skills match, read both and keep the main/impl ownership split intact.

## Routing

| Trigger | Skill |
| --- | --- |
| Full Searchpo flow, `/searchpo-full-flow`, complete provider/live E2E, publishable local render, live publish request | `skills/searchpo-full-flow/SKILL.md` |
| Topic/link widesearch orchestration, release gate, publish decision | `skills/searchpo-main-agent/SKILL.md` |
| Source research, AnySearch enrichment, FactBank, TopicBrief, source collection, cross-check hardening | `skills/searchpo-research-agent/SKILL.md` |
| DeepWiki MCP, GitHub repository architecture/context, repo Q&A, source-code context before FactBank | `skills/searchpo-deepwiki-research/SKILL.md` |
| Run scripts, provider adapters, Remotion render, Gemini audit, Douyin check/upload | `skills/searchpo-impl-agent/SKILL.md` |
| Inspect `.env` key availability, provider/API routing, DeepWiki MCP availability, side-effect capability selection | `skills/searchpo-agent-capabilities/SKILL.md` |
| Edit `src/`, captions, cover, Remotion metadata, render quality, Lambda render | `skills/remotion-best-practices/SKILL.md` |
| Validate Claude/Codex bridge map, skill/command/agent frontmatter, bridge sync, install health | `skills/searchpo-plugin-check/SKILL.md` |
| X/Twitter posting pack, repo/paper-to-X threads, X image assets, official X API publish, posting strategy memory | `x-threads/skills/github-repo-to-x-threads/SKILL.md` |

## Dispatch Rules

1. Prefer the most specific skill.
2. Keep live publishing behind an explicit user request for the current run.
3. Treat `skills/` as source of truth; bridge directories are generated.
4. Treat `agents/` as source of truth for the three-agent team. When an agent-team runtime is available, `searchpo-main-agent` delegates research to `searchpo-research-agent` and execution to `searchpo-impl-agent`.
5. Run `npm run skills:check` after skill, command, agent, or bridge-map edits.

## Shared Conventions

- `skills/_AGENT_README.md` explains the local skill directory contract.
- `config/searchpo_policy.json` owns keyword, copy, scoring, and provider-prompt policy.
- `config/agent_capabilities.json` owns redacted env-key/MCP capability routing. Use `scripts/agent_capabilities.py`; never print `.env` values.
- `.mcp.json` declares project MCP servers; DeepWiki belongs to repo research and does not replace canonical evidence.
- `vendor/anysearch-skill` is the project-vendored AnySearch runtime; do not put API keys there.
- Runtime artifacts under `runtime/` are evidence, not durable source.
- `x-threads/` is the merged `github-repo-to-x-threads` skillpack (X/Twitter distribution channel). It keeps its own `AGENTS.md`, resolver, manifests, and installer under `x-threads/`; it is routed from here but not part of the Claude/Codex bridge sync.
