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
| [mcp-creator-growth](plugins/mcp-creator-growth) | MCP server | Context-aware learning sidebar for AI coding assistants (Python, runs via `uvx`) |
| [search-harness](plugins/search-harness) | Knowledge skill | Domain knowledge and roadmap for building a search harness for coding agents |

## Provenance

Each plugin directory was merged from its original repository with full commit
history preserved (`git subtree`):

- `plugins/searchpo/` ← [searchpo](https://github.com/SunflowersLwtech/searchpo)
- `plugins/polanyi-design/skills/polanyi-design/` ← [polanyi-design](https://github.com/SunflowersLwtech/polanyi-design)
- `plugins/loopify-requirements/skills/loopify-requirements/` ← [loopify-requirements](https://github.com/SunflowersLwtech/loopify-requirements)
- `plugins/mcp-creator-growth/` ← [mcp_creator_growth](https://github.com/SunflowersLwtech/mcp_creator_growth)
- `plugins/search-harness/skills/search-harness/` ← [search-harness](https://github.com/SunflowersLwtech/search-harness)

## Requirements

- `mcp-creator-growth` needs [uv](https://docs.astral.sh/uv/) installed (`uvx` launches the server straight from the plugin directory).

## License

Individual plugins keep the licenses of their source repositories (see each
plugin directory).
