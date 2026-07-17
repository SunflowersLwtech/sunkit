# sunkit

SunflowersLwtech's toolbox — Claude Code skills, agents, commands, and MCP servers,
packaged as a plugin marketplace.

## Install

```
/plugin marketplace add SunflowersLwtech/sunkit
/plugin install polanyi-design@sunkit
```

## Plugins

| Plugin | Type | What it does |
|--------|------|--------------|
| [polanyi-design](plugins/polanyi-design) | Skill | Frontend design cognitive engine grounded in Michael Polanyi's tacit knowledge framework — expert-level visual judgment for UI design and design systems |
| [loopify-requirements](plugins/loopify-requirements) | Skill | Convert prompts and vague tasks into repeatable, verifiable loops with goal/scope/verification/escalation/stop conditions |
| [github-repo-to-x-threads](plugins/searchpo/x-threads) | Skill + Command | Analyze technical sources and produce responsible X content packs with evidence review, quality chain, and image assets |
| [searchpo](plugins/searchpo) | Skills + Command | OSS Radar search pipeline — data prep, agent harness, research/impl agents, `searchpo-full-flow` |
| [mcp-creator-growth](https://github.com/SunflowersLwtech/mcp_creator_growth) | MCP server | Context-aware learning sidebar for AI coding assistants (Python, runs via `uvx`; independent repo) |
| [search-harness](plugins/search-harness) | Knowledge skill | Domain knowledge and roadmap for building a search harness for coding agents |

## Provenance

This repository started life as `polanyi-design` and was renamed to `sunkit`
(the old URL redirects here). The other plugins were merged in from their
original repositories with full commit history preserved (`git subtree`):

- `plugins/polanyi-design/skills/polanyi-design/` — this repo's original content
- `plugins/searchpo/` ← searchpo
- `plugins/loopify-requirements/skills/loopify-requirements/` ← loopify-requirements
- `plugins/search-harness/skills/search-harness/` ← search-harness
- `mcp-creator-growth` lives in its own repository: [mcp_creator_growth](https://github.com/SunflowersLwtech/mcp_creator_growth) (referenced by this marketplace)

## Requirements

- `mcp-creator-growth` needs [uv](https://docs.astral.sh/uv/) installed (`uvx` launches the server straight from its plugin directory).

## License

Individual plugins keep the licenses of their source repositories (see each
plugin directory).
