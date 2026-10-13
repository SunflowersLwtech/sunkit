# claude-mesh

**`ListAgents` / `SendMessage` for Claude Code sessions on _different accounts_ and _different machines_.**

Claude Code's built-in cross-session messaging only reaches sessions signed in to the same
claude.ai account. claude-mesh adds the missing piece: a small self-hosted relay plus a Claude
Code plugin, so any interactive session on your team can list the others and message them, and
inbound messages appear in the receiving terminal on their own:

```
← mesh: tests on main are red since 4f2c1e; your branch is fine, don't rebase yet
```

It is built on Claude Code [channels](https://code.claude.com/docs/en/channels) (research
preview). Nothing about how Claude talks to Anthropic changes: no proxy, no API base URL, no
shared credentials. Remote Control keeps working.

> Part of [claude-code-toolkit](../README.md). Fork of [pouriamrt/claude-mesh](https://github.com/pouriamrt/claude-mesh) (MIT). The relay,
> wire format and pairing model come from upstream. This fork addresses individual **sessions**
> instead of people, ships as a plugin, and fixes a sender-spoofing bug. See
> [What changed from upstream](#what-changed-from-upstream).

## How it looks

Claude gets two tools, named and shaped after the built-in ones:

```
list_agents
  api-refactor [3wga61] (this session) — alice@example.com (mesh alice@laptop) · busy · ~/src/api
  web-ui [09r4cq] — alice.research@gmail.com (mesh alice@desktop) · idle · ~/src/web
  infra [dx10an] — bob@example.com (mesh bob@workstation) · idle · E:\infra

send_message(to: "infra", message: "staging DB creds rotated; re-run migrations before deploy")
  → delivered to infra [dx10an]
```

- `to` is a session name, or `name [ref]` when two sessions share a name, exactly like
  `SendMessage`. Session names and busy/idle status are read from Claude Code's own session
  registry, so they match what you see natively.
- Replies go to the incoming message's `from` attribute. The relay sets `from` and `account`;
  senders cannot forge them.
- Each row also shows the claude.ai login that machine's Claude Code is signed in with (read from
  its local config, updated within seconds of a `/login`). It is self-reported and for display;
  the paired mesh identity is what the relay authenticates.
- A message reaches exactly one session — never every session of that account.

## Requirements

- Claude Code **v2.1.80+** signed in with **claude.ai** (channels do not work with API keys,
  Bedrock, Vertex or Foundry). Tested on v2.1.296 on macOS and Windows.
- Node.js 20+ on every machine that runs Claude Code. No `npm install`: the plugin ships a
  single bundled file.
- One always-on machine for the relay (Docker), reachable from the others. A Tailscale tailnet
  is the intended setup.
- On a **Team or Enterprise** plan, an Owner must turn channels on (see step 2).

## Setup

### 1. Run the relay (once)

```bash
git clone https://github.com/SunflowersLwtech/claude-code-toolkit && cd claude-code-toolkit/mesh
docker build -f docker/Dockerfile.relay -t claude-mesh/relay:local .

mkdir -p mesh-data && sudo chown 65532:65532 mesh-data   # the image runs as nonroot
docker run --rm -v "$PWD/mesh-data:/data" \
  -e MESH_TEAM_NAME=myteam -e MESH_ADMIN_HANDLE=alice \
  claude-mesh/relay:local init        # writes admin.token and alice.paircode into mesh-data/

MESH_BIND=$(tailscale ip -4) MESH_DATA_DIR=$PWD/mesh-data \
  docker compose -f docker/docker-compose.tailnet.yml up -d
curl http://$(tailscale ip -4):8443/health      # {"ok":true}
```

`docker-compose.tailnet.yml` listens on one address only (your tailnet IP), so the relay is
not exposed on the LAN or the internet. Building behind a proxy? Add
`--network host --build-arg HTTPS_PROXY=…` to `docker build`.

### 2. Allow the channel for your organization

Team/Enterprise: **claude.ai → Admin settings → Claude Code → Managed settings**. Keep the
official channel plugins if you use them, and add this one:

```json
{
  "channelsEnabled": true,
  "allowedChannelPlugins": [
    { "marketplace": "claude-plugins-official", "plugin": "telegram" },
    { "marketplace": "claude-plugins-official", "plugin": "discord" },
    { "marketplace": "claude-plugins-official", "plugin": "imessage" },
    { "marketplace": "claude-plugins-official", "plugin": "fakechat" },
    { "marketplace": "claude-mesh", "plugin": "mesh" }
  ]
}
```

Setting `allowedChannelPlugins` *replaces* Anthropic's default list, hence the four official
entries. Without this step you can still use the mesh, but every launch needs
`--dangerously-load-development-channels plugin:mesh@claude-mesh` and shows a confirmation
dialog.

### 3. Each machine

```bash
git clone https://github.com/SunflowersLwtech/claude-code-toolkit ~/claude-code-toolkit
claude plugin marketplace add ~/claude-code-toolkit/mesh
claude plugin install mesh@claude-mesh
```

Pair it. The admin issues a code per person and per extra device:

```bash
M=~/claude-code-toolkit/mesh/plugins/mesh/server/mesh-cli.mjs
R=http://<relay-tailnet-ip>:8443

# on the admin machine, once
node $M admin bootstrap --token-file mesh-data/admin.token
node $M admin add-user   --handle bob --relay $R     # new person → pair code
node $M admin add-device --handle alice --relay $R   # another machine for an existing person

# on the machine being added
node $M pair MESH-XXXX-XXXX-XXXX-XXXX --relay $R --label laptop
```

Make plain `claude` join the mesh. Interactive launches get
`--channels plugin:mesh@claude-mesh`; subcommands, `-p`, `--help` and explicit `--channels`
pass through unchanged:

```bash
# zsh / bash
echo 'source ~/claude-code-toolkit/mesh/plugins/mesh/shell/claude-mesh.zsh' >> ~/.zshrc
```

```powershell
# PowerShell (Windows)
Add-Content $PROFILE '. "$HOME\claude-code-toolkit\mesh\plugins\mesh\shell\claude-mesh.ps1"'
```

**First launch after changing managed settings:** Claude Code checks its *cached* copy of the
org settings at startup, so the very first launch may still say the plugin is "not on the
approved channels allowlist". Run any `claude -p "ok"` once (or just restart) to refresh the
cache.

## Which sessions join

A session is listed (and can receive) only when **all** of these hold:

1. it is interactive (not `claude -p`, not an SDK run);
2. its Claude Code process was launched with the mesh channel (`--channels plugin:mesh@…`, or
   the dev flag);
3. Claude Code's cached org policy will actually accept that channel.

Claude Code tells an MCP server nothing about whether it was opted in as a channel (the
`initialize` handshake is identical either way), and a session without the opt-in silently
drops pushed messages. So the plugin checks the parent process's command line and the same
policy cache Claude Code uses. Sessions that fail a check can still **send**; they just don't
advertise themselves as reachable. `MESH_JOIN=always|never` overrides this.

## Security model

- **Read this if you run with `--dangerously-skip-permissions` / bypass mode:** a message from
  any paired account lands in your session's context, and a session in bypass mode acts without
  asking. Pair only accounts you would let type into your terminal.
- Identity: each device holds a bearer token. The relay stamps `from` / `account` from the
  token and the session the token owns; a session id can't be claimed or spoken for by another
  token. Sender-supplied metadata cannot override these fields.
- Peer content is marked as untrusted input in the server instructions, and `<channel>` bodies
  are escaped against tag injection (property-tested).
- Permission relay (approving tool prompts remotely) is **never** offered by this plugin.
- A loop guard limits rapid replies to the same sender, and the instructions tell Claude not to
  answer acknowledgements.
- The relay is a trust anchor: whoever controls it can forge messages. Keep it on a private
  network. Pair codes are single-use, expire after 24 h, and `/v1/auth/pair` is rate-limited.

See [SECURITY.md](SECURITY.md) for the full threat model.

## Limitations

- Channels are a **research preview**; the flag syntax and protocol may change.
- The built-in `ListAgents` does not show mesh sessions, and mesh tool names carry the plugin
  prefix (`mcp__plugin_mesh_mesh__send_message`).
- With deferred tool loading, Claude may first look the tools up before its first send.
- In `cmd.exe` on Windows the wrapper does not apply; use PowerShell or pass `--channels`.
- There is no "tell me when that session is idle" yet.

## What changed from upstream

| | upstream | this fork |
|---|---|---|
| Addressing | per person; a message fans out to every open session of that person | per **session**, resolved like `SendMessage` (`name` or `name [ref]`) |
| Tools | `send_to_peer`, `list_peers`, `set_summary`, `respond_to_permission` | `list_agents`, `send_message` |
| Sender spoofing | sender `meta.from` overwrote the relay-set `from` | fixed; identity fields are reserved |
| Install | `mesh pair` writes into `~/.claude.json` (every session loads it) | plugin + marketplace; one bundled file, no `npm install` |
| Launch | `--dangerously-load-development-channels server:…` every time | org allowlist + `--channels`, wrapped so plain `claude` works |
| Non-channel sessions | registered anyway; pushes silently dropped | send-only, not listed |
| Permission relay | optional | removed |
| Session names / status | none | read from Claude Code's session registry |
| Admin | `add-user --force` resets a person's tokens | `add-device` adds a machine without revoking |

## Development

```bash
cd mesh
pnpm install          # Node 22 recommended (better-sqlite3 prebuilds)
pnpm -r build
pnpm -r test:ci       # ~250 tests across shared / relay / peer-agent / e2e
pnpm bundle           # regenerate plugins/mesh/server/*.mjs after peer-agent changes
```

Packages: `shared` (envelope schema, `<channel>` rendering), `relay` (Hono + SQLite + SSE),
`peer-agent` (the MCP channel server and the `mesh` CLI), `e2e`.

## License

MIT. Original work © Pouria Mortezaagha; modifications in this fork © their contributors.
