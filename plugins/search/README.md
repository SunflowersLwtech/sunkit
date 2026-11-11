# search

One skill that routes every web task to the right retrieval path, with each
path's detail skill shipped alongside it. Part of [sunkit](../../README.md).

```
/plugin marketplace add SunflowersLwtech/sunkit
/plugin install search@sunkit
```

## Members

| Skill | What it is | Source / license |
|---|---|---|
| `search` | The router: picks a tool by task shape, then reads the matching detail doc by path | This repo, Apache-2.0 |
| `verbatim-fetch` | Which retrieval rung returns a page's actual words (WebFetch summarizes), what each rung silently drops, x.com handling | This repo, Apache-2.0 |
| `anysearch` | Structured vertical search CLI | Vendored from [anysearch-ai/anysearch-skill](https://github.com/anysearch-ai/anysearch-skill) tag `v3.1.1`, Apache-2.0 — see its `LICENSE`/`NOTICE` and `UPSTREAM.md` for the small local diff |
| `exa-research` | Research orchestrator: plans and dispatches subagents for deep dives, literature reviews, "find me all X" | Vendored from [exa-labs/exa-mcp-server](https://github.com/exa-labs/exa-mcp-server), MIT — see its `LICENSE` and `UPSTREAM.md` |
| `exa-agent` | Exa Agent (`agent_run`, usage-billed): list-building, enrichment, structured output, extra data providers | Vendored from [exa-labs/exa-mcp-server](https://github.com/exa-labs/exa-mcp-server), MIT — see its `LICENSE` and `UPSTREAM.md` |

## What you need to configure yourself

- **Exa MCP**: add Exa's server to your MCP config — the hosted endpoint
  `https://mcp.exa.ai/mcp` (OAuth) or an instance that carries your own API
  key. The router degrades gracefully without it: anysearch's general search
  plus the built-in `WebSearch`/`WebFetch` still cover the open-web rows.
- **anysearch key** (optional): anonymous access works with lower rate limits;
  the skill's own SKILL.md describes configuring `ANYSEARCH_API_KEY` via `.env`
  or the environment. No key is bundled.

The member skills are hidden from the skill list
(`disable-model-invocation`) — the router instructs the model to `Read` their
SKILL.md by path when a task matches a row, which keeps the whole set to one
skill-list entry.
