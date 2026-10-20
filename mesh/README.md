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

> Part of [sunkit](../README.md). Fork of [pouriamrt/claude-mesh](https://github.com/pouriamrt/claude-mesh) (MIT). The relay,
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
git clone https://github.com/SunflowersLwtech/sunkit && cd sunkit/mesh
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
    { "marketplace": "sunkit", "plugin": "mesh" }
  ]
}
```

Setting `allowedChannelPlugins` *replaces* Anthropic's default list, hence the four official
entries. Without this step you can still use the mesh, but every launch needs
`--dangerously-load-development-channels plugin:mesh@sunkit` and shows a confirmation
dialog.

#### Personal Pro / Max accounts (no organization)

A personal Pro or Max login has no organization, so no server-managed settings reach it and
Claude Code checks `--channels` against Anthropic's default channel list, which doesn't include
this plugin: the session starts, but the channel doesn't register. The development flag gets
around that, but it shows a confirmation dialog on every launch, has no "remember" option, and
skips the allowlist altogether.

Put the same two keys in the machine's own managed settings file instead. Claude Code applies
the first managed source that carries a policy key, and it checks the org's server-managed
settings before the machine's MDM profile and `managed-settings.json`
([how Claude Code combines managed sources](https://code.claude.com/docs/en/managed-settings#how-claude-code-combines-managed-sources)):

- signed in to a Team/Enterprise org whose managed settings carry a policy: the org's settings
  apply and the file is ignored;
- signed in with a personal Pro/Max plan: the file applies, and plain `--channels` (or the shell
  wrapper) registers the channel without a dialog.

```bash
M=~/sunkit/mesh/plugins/mesh/server/mesh-cli.mjs
node $M policy install   # prints the merged file and the commands that put it in place
node $M policy status    # which managed source applies here, and whether a session would join
```

`policy install` merges into an existing file: other keys stay, and an existing
`allowedChannelPlugins` only gains the mesh entry (without one, the four official entries come
along). It stages the result in a temp directory and prints the commands that copy it to
`/Library/Application Support/ClaudeCode/` (macOS), `/etc/claude-code/` (Linux) or
`C:\Program Files\ClaudeCode\` (Windows, elevated PowerShell). It never elevates itself;
`--write` writes directly only when you already have write access there.

**What the file means for the machine.** It is an administrator policy for every account and
every OS user on the machine, not a personal preference:

- It turns channels on and replaces Anthropic's default channel list for every login that gets
  no server-managed policy: personal plans, Console API keys, and also Team/Enterprise orgs
  that haven't set any managed settings, whose admins never turned channels on. Sessions still
  opt in one by one with `--channels`.
- It cannot loosen an org's server-managed settings; those win whenever they carry a policy key.
- Whoever can write the system directory controls it. If another tool already owns
  `managed-settings.json`, Claude Code also merges `managed-settings.d/*.json` drop-ins (lists
  union), but `policy install` only edits `managed-settings.json`.

### 3. Each machine

```bash
git clone https://github.com/SunflowersLwtech/sunkit ~/sunkit
claude plugin marketplace add ~/sunkit
claude plugin install mesh@sunkit
```

Pair it. The admin issues a code per person and per extra device:

```bash
M=~/sunkit/mesh/plugins/mesh/server/mesh-cli.mjs
R=http://<relay-tailnet-ip>:8443

# on the admin machine, once
node $M admin bootstrap --token-file mesh-data/admin.token
node $M admin add-user   --handle bob --relay $R     # new person → pair code
node $M admin add-device --handle alice --relay $R   # another machine for an existing person

# on the machine being added
node $M pair MESH-XXXX-XXXX-XXXX-XXXX --relay $R --label laptop
```

Make plain `claude` join the mesh. Interactive launches get
`--channels plugin:mesh@sunkit`; subcommands, `-p`, `--help` and explicit `--channels`
pass through unchanged:

```bash
# zsh / bash
echo 'source ~/sunkit/mesh/plugins/mesh/shell/claude-mesh.zsh' >> ~/.zshrc
```

```powershell
# PowerShell (Windows)
Add-Content $PROFILE '. "$HOME\sunkit\mesh\plugins\mesh\shell\claude-mesh.ps1"'
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
3. the managed settings Claude Code applies will actually accept that channel: the org's cached
   server-managed settings when they carry a policy, otherwise the machine's MDM profile,
   `managed-settings.json` (plus drop-ins) or, on Windows, the HKCU policy value, in Claude
   Code's order. A personal Pro/Max login skips a server-managed cache left behind by another
   login, because Claude Code doesn't deliver server-managed settings to personal plans.

Claude Code tells an MCP server nothing about whether it was opted in as a channel (the
`initialize` handshake is identical either way), and a session without the opt-in silently
drops pushed messages. So the plugin checks the parent process's command line and the same
managed sources Claude Code reads. It also requires `channelsEnabled: true`, which Claude Code
itself skips for personal plans; `policy install` always writes it. Sessions that fail a check
can still **send**; they just don't advertise themselves as reachable.
`MESH_JOIN=always|never` overrides this. With `CLAUDE_CONFIG_DIR` set, the policy cache, the
session registry and the signed-in account are read from that directory.

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
- Workgroups and roles are bound to **tokens**, set by an admin (`PUT /v1/admin/tokens/:id/grant`),
  never by a session. A token with no grant is a `worker` that sees only the `team` workgroup; a
  device paired later inherits its owner's workgroups (never a role). Sessions, tasks, leases,
  machines, presence and `@team` broadcasts are filtered by workgroup on the relay, and a session
  in a workgroup you cannot see can only be reached by answering a message it sent you.
- Dispatching (tasks for other sessions, executor commands) needs the `orchestrator` role on the
  calling token. Give it to a token of its own, in its own `MESH_HOME`: every process that can
  read a device's token file can claim that device's sessions, so a role on a shared device token
  is a role for everything on that machine.

See [SECURITY.md](SECURITY.md) for the full threat model.

## Limitations

- Channels are a **research preview**; the flag syntax and protocol may change.
- The built-in `ListAgents` does not show mesh sessions, and mesh tool names carry the plugin
  prefix (`mcp__plugin_mesh_mesh__send_message`).
- With deferred tool loading, Claude may first look the tools up before its first send.
- In `cmd.exe` on Windows the wrapper does not apply; use PowerShell or pass `--channels`.
- The join check mirrors Claude Code's managed-source ranking, not every corner of it:
  unreadable admin documents count as absent (Claude Code refuses to start on a malformed one),
  WSL's `wslInheritsWindowsSettings` chain and settings delivered by a Claude apps gateway are
  not read.
- There is no "tell me when that session is idle" yet.

## What changed from upstream

| | upstream | this fork |
|---|---|---|
| Addressing | per person; a message fans out to every open session of that person | per **session**, resolved like `SendMessage` (`name` or `name [ref]`) |
| Tools | `send_to_peer`, `list_peers`, `set_summary`, `respond_to_permission` | `list_agents`, `send_message` |
| Sender spoofing | sender `meta.from` overwrote the relay-set `from` | fixed; identity fields are reserved |
| Install | `mesh pair` writes into `~/.claude.json` (every session loads it) | plugin + marketplace; one bundled file, no `npm install` |
| Launch | `--dangerously-load-development-channels server:…` every time | org allowlist (or a machine-level `managed-settings.json` for personal plans) + `--channels`, wrapped so plain `claude` works |
| Non-channel sessions | registered anyway; pushes silently dropped | send-only, not listed |
| Permission relay | optional | removed |
| Session names / status | none | read from Claude Code's session registry |
| Admin | `add-user --force` resets a person's tokens | `add-device` adds a machine without revoking |
| Hosts without channels | not supported | pull mode with `read_messages` (Devin CLI, Antigravity CLI, Grok Build, pi and other MCP hosts), hook notices and busy/idle for Devin CLI, Antigravity, Grok Build and pi (an extension), named send-only senders, `mesh say` |

## Devin CLI, Antigravity CLI, Grok Build, pi and other agents without channels

Claude Code shows mesh messages as they arrive through its channel. Devin CLI, and other agents
that speak MCP but have no channels, can't receive pushed messages, so the peer runs in **pull
mode** for them: the session is listed like any other, marked `pull`, and messages addressed to it
wait in an inbox until the agent calls `read_messages`. Expect replies from a pull session to come
later than from a Claude Code session.

Set it up once per machine. Every host needs `mesh pair` first, and every host has its own
installer, described below:

```bash
M=~/sunkit/mesh/plugins/mesh/server/mesh-cli.mjs
```

A Claude Code session's name comes from Claude Code's own name for it, as before. A pull session
(Devin, Antigravity, Grok Build, pi) is named by the first of: `MESH_SESSION_NAME` as given, then the label of the
Herdr tab it runs in (with its pane id appended when the tab has more than one pane, since the label
then names the tab's main agent), then its working directory's name; the last two are prefixed with
`MESH_HOST` (`agy-1`, `agy-repo`) unless they already start with it. Claude Code's session registry
is never read for a pull session, so one started in a Claude Code session's directory does not
borrow that session's name, and the name does not change while it runs.

### Devin CLI

Devin CLI has lifecycle hooks, and they can add a note to a tool result and keep a turn going, so
it gets the same treatment as the other hosts without channels. Devin supports the events
`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PermissionRequest`, `Stop`,
`PostCompaction` and `SessionEnd`
([docs](https://docs.devin.ai/cli/extensibility/hooks/overview)). User-level hooks live under the
`"hooks"` key of Devin's user config: `~/.config/devin/config.json`, or
`%APPDATA%\devin\config.json` on Windows.

- a session reports `idle` as soon as Devin starts it (its `SessionStart` fires at launch and waits
  up to 3 seconds for the peer, which Devin starts at the same moment), so with `MESH_WAKE=herdr` a
  freshly started session can be woken before its first prompt;
- a prompt marks it `busy`; when mail arrives while it works, the next tool result carries a
  one-line notice naming the senders (once per arrival);
- a turn that ends on its own (`Stop`) while a message that arrived is still unread runs once more
  to read it (`decision: block`);
- `SessionEnd` only forgets the session.

Devin fires no `Stop` when the user interrupts with Esc, so an interrupt is never overridden. It
also means the session keeps showing `busy` after an interrupt, until its next prompt, and
`MESH_WAKE=herdr` does not prompt it in that state.

The notice never contains the message itself; the body still comes back from `read_messages`, under
the same rules as any peer message.

```bash
node $M devin install            # prints what it would do
node $M devin install --write    # devin mcp add … and the hooks in Devin's config.json
```

which amounts to:

```bash
devin mcp remove -s user mesh   # ignored when there is no such server
devin mcp add -s user mesh -e MESH_JOIN=pull -e MESH_HOST=devin -- /path/to/node ~/sunkit/mesh/plugins/mesh/server/mesh-peer.mjs
```

plus `SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Stop` and `SessionEnd` hooks running
`node …/mesh-cli.mjs devin hook <event>` (`SessionStart` with a 10 s timeout, the others 5 s). Every
other setting and every other hook group in that file is kept, and a mesh hook group from an
earlier install (any command ending in `devin hook <event>`) is replaced rather than duplicated;
when the file changes, the previous one is saved as `config.json.bak-mesh-<timestamp>`. Without
`--write` it only prints. `--config <path>` writes another file; `--scope local|project` applies to
the MCP server only.

Name each Devin session when starting it, so others can address it and see who wrote:

```bash
MESH_SESSION_NAME=docs-devin devin
```

Unnamed Devin sessions are `devin-<Herdr tab label>` or `devin-<directory>`; `MESH_HOST=devin` is
what puts the `devin` prefix on them. Devin has no `--append-system-prompt`, so standing rules go
in the first prompt or in the project's `AGENTS.md`.

Devin 3000.11 runs its agent in a child process, `devin acp`, which starts the MCP servers and runs
the hook commands (through `sh -c`; on Windows through Git Bash, which puts two `bash.exe` processes
between the hook and `devin acp`). The hooks find the peer through the same socket under
`MESH_HOME/hooks/` as the agy and Grok hooks, keyed by the `devin acp` process id, and look up to
three levels above themselves. The first hook of a session remembers which process answered in
`MESH_HOME/hooks/devin-<session_id>.pid` (Devin passes a `session_id` to every hook), so later hooks
connect straight to it; on Windows, where looking up a process's parents costs about a second and a
half, that happens once per session. `SessionEnd` deletes that file.

`devin -p …` only sends. It used to join the mesh for the length of the run, because the peer's
parent was `devin acp` rather than `devin -p`; the peer now looks past `devin acp` to the command
the user ran.

Devin also loads Claude Code-format hooks from `~/.claude/settings.json` and `.claude/`
directories. The Claude Code plugin has no hooks, so nothing runs twice; don't add the mesh Devin
hooks there.

To remove: `devin mcp remove -s user mesh`, and delete from Devin's `config.json` the hook groups
whose command ends in `devin hook <event>`.

### Antigravity CLI (agy)

Antigravity CLI runs MCP servers the same way, and it also has lifecycle hooks. The peer uses them,
so a working agy agent does not have to remember to check its inbox:

- before each model call, if messages are waiting, the agent gets a one-line notice naming the
  senders and telling it to call `read_messages`;
- when a turn ends on its own while a message that arrived during it is still unread, the agent is
  kept going once to read it (a stop you asked for with Esc, an error or a limit is never overridden);
- the session shows `busy` or `idle` in `list_agents` instead of `unknown`.

The notice never contains the message itself; the body still comes back from `read_messages`, under
the same rules as any peer message. An idle session is not interrupted unless you opt in: with
`MESH_WAKE=herdr` set before starting agy in a [Herdr](https://herdr.dev) pane, a message to an idle
session prompts that pane once (`herdr agent prompt`), at most every 20 seconds. Leave it off in panes
a person is typing in.

```bash
node $M agy install            # prints what it would do
node $M agy install --write    # agy mcp add … and a "mesh" entry in ~/.gemini/config/hooks.json
```

which amounts to `agy mcp add -e MESH_JOIN=pull -e MESH_HOST=agy mesh -- /path/to/node …/mesh-peer.mjs`
plus `SessionStart`, `PreInvocation` and `Stop` hooks running `node …/mesh-cli.mjs agy hook <event>`. Other named hooks
in that file (Herdr's, for example) are kept, and the old file is saved as `hooks.json.bak-mesh-*`.
Don't put `MESH_SESSION_NAME` into the server's config: agy lets a server's configured `env` override
the session's environment, so every session would get that name. Name sessions when starting them:

```bash
MESH_SESSION_NAME=agy-review agy
```

**Standing rules.** agy has no `--append-system-prompt`. The installed `SessionStart` hook injects
the text in `AGY_SESSION_RULES_B64` (base64 of UTF-8, so a launcher needn't shell-quote it) or the file
named by `AGY_SESSION_RULES_FILE` as a system message when the conversation starts, which agents treat
as trusted, unlike rules pasted into the first prompt:

```bash
AGY_SESSION_RULES_B64=$(printf '%s' 'Report to lead over the mesh when done.' | base64) MESH_SESSION_NAME=agy-review agy
```

Print-mode runs (`agy -p …`, `devin -p …`) start the server too, but only send: they are not listed,
so a one-off `agy -p "/usage"` leaves no row behind.

The hooks find the peer through a socket under `MESH_HOME/hooks/`, keyed by the agy process id (both
are children of that process). To remove: `agy mcp remove mesh` and delete the `mesh` entry from
`~/.gemini/config/hooks.json`.

### Grok Build (grok)

Grok Build starts stdio MCP servers and runs hook commands as children of the `grok` process too,
and its hooks can add a note to a tool result and keep a turn going, so it gets the same treatment:

- a session reports `idle` as soon as grok starts (its `SessionStart` fires at launch), so with
  `MESH_WAKE=herdr` a freshly started session can be woken before its first prompt;
- a prompt marks it `busy`; when mail arrives while it works, the next tool result carries a
  one-line notice naming the senders (once per arrival: Grok keeps these notes in the conversation);
- a turn that ends on its own (`Stop` with reason `end_turn`) while a message that arrived is
  still unread runs once more to read it; interrupts, declined permissions, turn limits
  (`StopCancelled`) and API errors (`StopFailure`) are never overridden and just report `idle`.

```bash
node $M grok install            # prints what it would do
node $M grok install --write    # grok mcp add … and ~/.grok/hooks/mesh.json
```

which amounts to `grok mcp add -e MESH_JOIN=pull -e MESH_HOST=grok mesh -- /path/to/node …/mesh-peer.mjs`
plus a hooks file of our own (Grok loads every `~/.grok/hooks/*.json`; a changed one is kept as
`mesh.json.bak-mesh-*`, which it does not load). As with agy, the server's configured `env` wins over
the session's, so name sessions when starting them, and give standing rules with grok's own flag:

```bash
MESH_SESSION_NAME=grok-review grok --rules 'Report to lead over the mesh when done.'
```

Single-turn runs (`grok -p`, `--single`, `--prompt-file`, `--prompt-json`) only send. Grok Build also
loads Claude Code's plugins, including this one from Claude's plugin cache; if `grok inspect` lists
it, add `"mesh"` to `[plugins] disabled` in `~/.grok/config.toml` so only the pull-mode server runs.
To remove: `grok mcp remove mesh` and delete `~/.grok/hooks/mesh.json`.

### pi (pi-coding-agent)

pi has MCP built in (1.3+) but no channels and no hook commands; its extensions get the session's
lifecycle events instead. `mesh pi install --write` puts a two-line loader in pi's extensions
directory (`~/.pi/agent/extensions/mesh.ts`, or under `PI_CODING_AGENT_DIR`) that imports the
bundled `mesh-pi.mjs` from the checkout, so updating the checkout updates what pi runs:

```bash
node $M pi install            # prints the loader it would write
node $M pi install --write
```

The extension registers the peer as a pull-mode MCP server with `direct` tools
(`mcp__mesh__list_agents`, `mcp__mesh__send_message`, `mcp__mesh__read_messages`), puts the peer's
instructions into a `<mesh>` system prompt section (pi does not show server instructions for direct
tools), and maps pi's events onto the same hook socket the agy and Grok hooks use:

- `session_start` reports `idle`; a run (`agent_start`) reports `busy`, and the end of a run
  (`agent_settled`) `idle` again;
- when mail arrives during a run, the next tool result gets a one-line notice (once per arrival);
- a run that completed on its own (`agent_before_settle` with outcome `completed`) while a message
  that arrived is still unread runs once more to read it; aborted and failed runs never do;
- with `MESH_WAKE` set (any value but `0`), an idle session checks every 3 seconds and starts a turn
  itself when mail arrives, once per arrival: no Herdr needed, and nothing is typed into the pane.

Name a session with `MESH_SESSION_NAME=<name> pi` or `pi --name <name>`; unnamed sessions fall back
to `pi-<Herdr tab label>` or `pi-<directory>`. Print and JSON runs (`pi -p`, `--mode json`) only send,
signed with the name; `MESH_JOIN=never` keeps any session out. Standing rules go in with pi's own
`--append-system-prompt`. To remove: delete `~/.pi/agent/extensions/mesh.ts`.

**Sending without a session.** A script, or an agent that has no MCP connection to the mesh, can
send one message with:

```bash
node $M say --as docs-devin lead "[docs-devin] gates are green"
node $M say --as docs-devin --reply-to msg_… lead -    # message from stdin
```

The name comes from `--as`, else `MESH_SESSION_NAME`. Such a sender is not registered, so it
receives nothing; recipients see `from="docs-devin"` with `sender="send-only"`. Only the
account is verified for these: the name is a label the account chose, the same trust as a session
name, without a `[ref]` that ties it to a session. A peer started with `MESH_JOIN=never` and
`MESH_SESSION_NAME` signs its messages the same way.

| Variable | Effect |
|---|---|
| `MESH_JOIN` | `pull`: join in pull mode (hosts without channels). `never`: send only. `always`: join regardless. Unset: Claude Code's rules above. |
| `MESH_SESSION_NAME` | name for a session that Claude Code doesn't name, and for send-only senders |
| `MESH_HOST` | short host label (`devin`, `agy`, `grok`, `pi`) that prefixes a pull session's fallback name |
| `MESH_WAKE` | `herdr`: wake an idle pull session in a Herdr pane when a message arrives (needs the Devin, agy or grok hooks); for pi, any value but `0` makes the extension start the turn itself |
| `MESH_HOME` | where the pairing lives (default `~/.claude-mesh`) |

The `pull` marker in `list_agents` and the names of send-only senders need a relay and peers from
this version. Against an older relay, pull sessions still work but show no marker, and send-only
senders show their account handle as before; older peers on the receiving side also show the handle.
The inbox holds the 200 most recent messages; anything older is dropped and the next
`read_messages` says how many.

## Ledger: cards, tasks, leases, machines

Besides messages the relay keeps a small ledger, borrowing the vocabulary of A2A (agent card,
task states, artifacts) but not its transport.

- **Cards.** `POST /v1/sessions/self` also takes `agent`, `model`, `repo`, `branch`,
  `herdr {machine, tab, pane}`, `task_id` and `source` (fixed fields, no free-form map;
  rate-limited per token *and* session). `GET /v1/sessions` adds the relay-owned `workgroup`,
  `role`, `dispatched_by`, `updated_at` and `age_s`.
- **Tasks** (`/v1/tasks`, SQLite): A2A states `submitted, working, input_required,
  auth_required, completed, failed, canceled, rejected`. A session may register its own task
  (depth 0); an orchestrator may assign one to another session (depth 1, never deeper). The relay
  assigns `seq` (one counter per team) and accepts `if_seq` as an optimistic lock; terminal states
  are final. Changes are pushed as SSE `event: task` (never stored as a message, so older peers
  skip them) and recovered with `GET /v1/tasks?since_seq=`. Prompts are never stored, only an
  optional `prompt_sha256`. Artifacts are `https://`, `gh://`, vault-relative or `version@time`
  references; receivers must not auto-fetch them.
- **Leases** (`/v1/leases`, SQLite): one holder per name (`deploy/`, `repo/`, `file/`, `device/`,
  `build/`, `cred/`); `409 lease_held` says who holds it and for how long (or only that it is
  held, across workgroups). TTL ≤ 1800 s, 3 per session, 2 h of renewals per session; `deploy/`
  and `cred/` need an active task of the holder. Expiry is judged on read, so a relay restart
  keeps them.
- **Machines** (`/v1/machines`, memory): an `executor` token bound to one machine reports
  agents, seats, load and installed hosts; after 90 s without a report the machine is `stale` and
  its sessions are hidden rather than shown idle. Orchestrators can send it read-only commands
  (`probe`, `read`) over `/v1/machines/:machine/commands`; unanswered ones fail as `no_ack` after
  60 s and are never retried on their own, and only the issuing token can read the answer.

From a shell, `mesh machine list|read|probe`, `mesh task list|show|create|update|artifact` and
`mesh lease list|acquire|renew|release` call these endpoints with the device's pairing (`--session
<id>` or `MESH_SESSION_ID` names the calling session where one is needed; `--relay` overrides the
URL).

### Cards and tasks from host hooks

Each joined session's peer keeps its card and its relay task current; it is the only writer on
the machine, and the host's lifecycle hooks only tell it what happened, over the local hook
socket every joined peer now serves.

- **The card** starts with what the peer can tell itself: the host (`MESH_HOST`, else Claude
  Code), the git repository and branch of its directory, Herdr's tab and pane when it runs inside
  Herdr (with the machine name from `machine` in `~/.claude-mesh/config.json` or `MESH_MACHINE`),
  `MESH_MODEL` and `MESH_TASK_ID`. Hooks add what only the host knows (Claude Code's model). Writes
  are batched (one every 2 s at most, changed fields only) and the whole card is sent again after
  the stream reattaches. `source` says where it came from (`hook`, `poll`).
- **The task** named by `MESH_TASK_ID` follows the host: the first turn makes a dispatched task
  `working`, a permission or input prompt `input_required`, the end of that turn (or the next one)
  `working` again. A turn ending never completes, fails or cancels a task; that stays explicit
  (`mesh task update`, a closeout, the dispatcher). A session restarted or resumed under a new id
  takes its task over (`rebind`) once the old session is gone.
- **Claude Code**: the plugin ships `hooks/hooks.json` (SessionStart, UserPromptSubmit,
  Notification for permission/input prompts, Stop, SessionEnd), each running
  `mesh-cli.mjs claude hook <event>`: exec form, in the background except at session start and
  end, silent, always exit 0. At session start it also exports `MESH_SESSION_ID` through
  `CLAUDE_ENV_FILE`. Once hooks report, the 3 s status poll stops writing busy/idle (it keeps
  following the name and the login). Claude Code has no event for a prompt being answered, so
  `input_required` clears at the end of that turn, not the moment the prompt is answered.
- **agy, Grok Build, Devin CLI, pi** report through the hooks they already have; nothing changes
  in their configuration.
- **Commands run inside a host** (`mesh task …`, `mesh lease …` from a Bash tool) find their
  session by asking the host's peer when neither `--session` nor `MESH_SESSION_ID` is given.
- **Waking** (`MESH_WAKE`) is capped locally: 6 wakes per session and 60 per machine per hour
  (`~/.claude-mesh/wakes.json`), for Herdr wakes and for turns a host starts by itself (pi) alike.
- `MESH_CARD_WRITE=0` turns card and task writes off for a session (busy/idle still flow).

### meshd, the per-machine executor

`plugins/mesh/server/meshd.mjs` reports for one machine every 30 s (herdr's agent list with each
agent's resume handle, installed hosts and versions, Claude seats from `~/.agents/tools/cc-quota`,
load, which dispatch roots exist) and answers `probe` and `read` over its stream. It only calls the
relay, never listens on a port, and runs every external program with a fixed argv. It needs its own
`MESH_HOME` with an `executor` token bound to the machine, never the device token:

```sh
# on the admin machine: a device for the executor, then bind it
mesh admin add-device <handle>                      # prints a pair code
MESH_HOME=~/.claude-mesh-meshd mesh pair <code> --label meshd-<machine>
curl -X PUT $RELAY/v1/admin/tokens/<token id>/grant -H "authorization: Bearer $ADMIN" \
  -H 'content-type: application/json' -d '{"role":"executor","workgroup":"<wg>","machine":"<machine>"}'
# on the machine, under its service manager
MESH_HOME=~/.claude-mesh-meshd MESHD_MAX_ACTIVE=3 node <checkout>/mesh/plugins/mesh/server/meshd.mjs
```

Without `MESH_HOME` it refuses to start. `HERDR_BIN` overrides the herdr path; on macOS it reads
cc-quota's cache instead of calling the usage API again.

Finished tasks and released leases are dropped after 7 days. Everything above is audited
(`task.*`, `lease.*`, `dispatch.*`, `token.grant`) with ids and names only, never content.

## Development

```bash
cd mesh
pnpm install          # Node 22 recommended (better-sqlite3 prebuilds)
pnpm -r build
pnpm -r test:ci       # ~250 tests across shared / relay / peer-agent / e2e
pnpm bundle           # regenerate plugins/mesh/server/*.mjs after peer-agent changes
```

Claude Code runs an installed plugin from its cache (`~/.claude/plugins/cache/sunkit/mesh/<version>`),
not from your checkout. After changing the bundle, bump `version` in
`plugins/mesh/.claude-plugin/plugin.json`, then on every machine:

```bash
git pull && claude plugin marketplace update sunkit && claude plugin update mesh@sunkit
```

Packages: `shared` (envelope schema, `<channel>` rendering), `relay` (Hono + SQLite + SSE),
`peer-agent` (the MCP channel server and the `mesh` CLI), `e2e`.

## License

MIT. Original work © Pouria Mortezaagha; modifications in this fork © their contributors.
