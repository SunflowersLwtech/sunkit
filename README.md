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
| [mesh](mesh) | Channel plugin + relay | `list_agents` / `send_message` between Claude Code sessions on different accounts and machines, through a self-hosted relay |
| [archify](https://github.com/tt-a1i/archify) | Skill (third-party, installs disabled) | tt-a1i/archify pinned to a reviewed commit: typed JSON rendered as interactive standalone HTML diagrams. Not a slash command of its own; another skill reads its `SKILL.md` from the install path |

Not a plugin: [tools/session-rescue](tools/session-rescue) holds two standalone Python scripts that get stuck or archived Claude sessions back.
[tools/magpie-gateway](tools/magpie-gateway) deploys a magpie gateway for Claude Code on a server, with two gateway middlewares and the client scripts. It is also not a plugin.

## mesh

Claude Code's built-in `ListAgents` / `SendMessage` only reach sessions signed in to the same
claude.ai account. [mesh](mesh/README.md) is a small self-hosted relay plus a channel plugin, so
interactive sessions on other accounts and machines can list each other and exchange messages,
which show up in the receiving session on their own. It is a fork of
[pouriamrt/claude-mesh](https://github.com/pouriamrt/claude-mesh) that addresses sessions
rather than people and fixes a sender-spoofing bug.

```
/plugin marketplace add SunflowersLwtech/sunkit
/plugin install mesh@sunkit
claude --channels plugin:mesh@sunkit
```

It also needs a running relay, a pairing code per machine, and (on Team/Enterprise plans) an
org allowlist entry `{ "marketplace": "sunkit", "plugin": "mesh" }` under
`allowedChannelPlugins`; [mesh/README.md](mesh/README.md) walks through all three, plus the
shell wrappers that add the `--channels` flag to plain `claude`. Agents without channels, such as
Devin CLI, join in pull mode and read their messages with `read_messages`; scripts can send with
`mesh say` ([mesh/README.md](mesh/README.md#devin-cli-and-other-agents-without-channels)).

## session-rescue

[tools/session-rescue](tools/session-rescue/README.md) has two single-file Python scripts with no
dependencies:

- `claude_rescue.py` finds interactive Claude Code sessions stuck on repeated
  `API Error: Connection refused` and restarts them in place with `--resume` (macOS / Linux,
  inside herdr or tmux).
- `claude_unarchive.py` restores Claude Desktop Cowork sessions that disappear after being
  archived (macOS / Windows).

```bash
python3 tools/session-rescue/claude_rescue.py scan
python3 tools/session-rescue/claude_unarchive.py --list
```

## Provenance

This repository started life as `polanyi-design` and was renamed to `sunkit`
(the old URL redirects here). The other plugins were merged in from their
original repositories with full commit history preserved (`git subtree`):

- `plugins/polanyi-design/skills/polanyi-design/` — this repo's original content
- `plugins/searchpo/` ← searchpo
- `plugins/loopify-requirements/skills/loopify-requirements/` ← loopify-requirements
- `plugins/search-harness/skills/search-harness/` ← search-harness
- `mesh/` and `tools/session-rescue/` ← claude-code-toolkit (`git merge`, original commit ids kept; that repository had itself absorbed claude-mesh, a fork of pouriamrt/claude-mesh, and claude-session-rescue)
- `mcp-creator-growth` lives in its own repository: [mcp_creator_growth](https://github.com/SunflowersLwtech/mcp_creator_growth) (referenced by this marketplace)
- `archify` is not copied here: the entry points at the `archify/` subdirectory of [tt-a1i/archify](https://github.com/tt-a1i/archify) (MIT) at a fixed commit (`git-subdir` source with `sha`), with `strict: false` because upstream has no `plugin.json`, and `defaultEnabled: false` so it never shows up as `/archify:archify`. To move to a newer upstream commit, read what changed, then update `sha`

## Requirements

- `mcp-creator-growth` needs [uv](https://docs.astral.sh/uv/) installed (`uvx` launches the server straight from its plugin directory).
- `archify` needs Node.js 18+ and a Chrome or Chromium binary (`ARCHIFY_CHROME`); on macOS wrap the binary so it gets `--use-mock-keychain --password-store=basic`, otherwise headless runs can prompt for the login keychain.
- `mesh` needs Node.js 22+ on each machine, Claude Code 2.1.80+ signed in with a claude.ai account (channels are a research preview), and Docker wherever the relay runs.

## License

Individual plugins keep the licenses of their source repositories (see each
plugin directory).
