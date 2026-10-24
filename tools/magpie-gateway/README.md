# magpie-gateway

A [magpie](https://github.com/yetone/magpie) gateway on llm-gateway (AWS us-east-1, t4g.large). The subscriptions are signed in on the server only, and magpie is not installed on the client machines.

Part of [sunkit](../../README.md). Not a plugin.

## Use it per process, never as the global default

Interactive Claude Code stays on Anthropic directly on every machine, which keeps mesh channels, claude.ai connectors and Remote Control. Start a single process on the gateway when you need a model you can't reach directly, for example when the Claude seats have hit their limits:

```sh
claude-gw                                  # Opus 5.5 through the claude-opus-5-5 group
claude-gw --model zed/claude-sonnet-5-5
claude-gw -p "…" --model grok/grok-4.7
```

`claude-gw` is `claude --settings ~/.claude/magpie-settings.json`. That file outranks the global settings, so this one session is on the gateway and no other session is.

**Why not the global default** (2026-10-24 incident): magpie answers a Claude subscription with a Claude Code process on the server, which shares the conversation only through a run of its own. Three things send a turn to a run that has not seen the conversation: a session that was already running before the switch, a move to another seat when one hits its limit, and a run evicted for idling or by a gateway restart. Each time, magpie tells the whole conversation to a new run as one block of text ("a new Claude Code is told the whole conversation: 1422 messages"). The model then writes tool calls as plain text, reads the server's container as its own environment, and loses the session's structure. Each retelling also writes the whole history to the cache again, up to about 920K tokens for one turn. A brand-new short session works; so does `claude -p`.

So the routing groups below contain stateless providers only. The Claude seats stay signed in for explicit `claude/claude-opus-5-5` one-shot calls.

## Server

- `compose.yaml` is its own compose project, separate from `/opt/llm-gateway` (the products' LiteLLM). It has `mem_limit 5g`, so it can never take LiteLLM's memory.
- The gateway port 3425 is not opened in the security group, and `MAGPIE_ALLOW_IPS` refuses anything outside Tailscale's ranges before a key is read. Each machine has its own gateway key.
- The web UI on 3430 is bound to 127.0.0.1. Reach it with `ssh -fN -L 127.0.0.1:3430:127.0.0.1:3430 llm-gateway`, then open `http://127.0.0.1:3430/?k=<MAGPIE_WEB_KEY>`.
- `MAGPIE_NO_STATS=1`, not `DO_NOT_TRACK`. Claude Code reads `DO_NOT_TRACK` too, and it turns off Claude Code's feature flags in the runs magpie starts.
- The image is pinned by digest. To upgrade, run `docker pull ghcr.io/yetone/magpie:<version>`, put the new digest in `.env`, then `docker compose up -d`.

```sh
sudo mkdir -p /opt/magpie/config /opt/magpie/plugins
sudo cp compose.yaml /opt/magpie/
sudo cp plugins/*/*.middleware.js /opt/magpie/plugins/
sudo chown -R 65532:65532 /opt/magpie/config
# /opt/magpie/.env from .env.example, chmod 600
cd /opt/magpie && sudo docker compose up -d
M="sudo docker exec magpie-magpie-1 magpie"
$M claude-code install --yes && $M claude-code runs 18
for p in kiro workbuddy trae zed grok; do $M plugin add @magpie-community/opencode-$p-auth; done
$M plugin add /plugins/kiro-harness.middleware.js
$M plugin add /plugins/zed-compat.middleware.js
```

## Routing groups

The group ids are Claude's own model names. A request for `claude-opus-5-5` reaches the group, and Claude Code still recognises the model by name, so its effort levels and context window behave as on Anthropic. `stays=session` keeps a conversation on the account that first answered it.

| group | members, in order |
|---|---|
| `claude-opus-5-5` | `kiro/claude-opus-5.5` → `group/claude-sonnet-5-5` |
| `claude-sonnet-5-5` | `kiro/claude-sonnet-5.5` → `zed/claude-sonnet-5-5` |
| `claude-haiku-5-5` | `zed/claude-haiku-5-5` → `kiro/claude-haiku-4.5` |
| `claude-fable-5-1` | `group/claude-opus-5-5` |

Checked on 2026-10-25 with a three-turn Claude Code session through the gateway: Read and Bash on the client machine, recalling the previous turn with no tool, then a subagent. The hostname and a nonce that exists only in a local file came back right, and the transcript has structured `tool_use` and no `<invoke>` text. `zed/claude-sonnet-5-5` passes with `zed-compat`. A Copilot student account answers only `copilot/auto`; any named model gets 400 "The requested model is not supported".

## Client

```sh
install -m 755 client/magpie-client client/claude-gw client/claude-native ~/.local/bin/
vk run -r "K=个人/magpie 网关 (llm-gateway)/MAGPIE_KEY_<MACHINE>" -- sh -c 'printf %s "$K" | magpie-client setup'
```

- `magpie-client setup` writes `~/.claude/magpie-settings.json` (mode 600): `ANTHROPIC_BASE_URL`, `ANTHROPIC_CUSTOM_HEADERS` (`x-api-key: <gateway key>`), `CLAUDE_CODE_ATTRIBUTION_HEADER=0`. It does not touch the global settings. There is no `ANTHROPIC_AUTH_TOKEN`, so Claude Code keeps its claude.ai sign-in, and mesh channels and claude.ai connectors keep working.
- `claude-gw` adds `--model claude-opus-5-5` unless a model is given. Like the shell's `claude` wrapper, it puts `--channels plugin:mesh@sunkit` last for an interactive session. On Windows, use `client/claude-gw.cmd` with the same settings file in `%USERPROFILE%\.claude`.
- Installed on 2026-10-25 on m4, m2, aws-sin, msi-wsl, MSI (Windows), wrsm, bd and devdesk. Each machine got a reply through the gateway from `claude-gw -p`. N150's Feishu assistant gets the gateway as a second cc-connect provider (`/provider magpie`), with Anthropic kept as the default.
- `magpie-client on` / `off` write the gateway into or out of **the global** `~/.claude/settings.json`. Per the section above, don't. Values a running session already loaded stay until it restarts, so deleting the two keys doesn't take a session off the gateway. Empty strings do, through a hot reload. Empty values in the global file also override a process's own environment, so delete them once every session has restarted.
- The 2026-10-25 fix: the key reaches the writer through the environment. The heredoc is python's stdin, so a piped key was lost, and the old version wrote `x-api-key: ` with an empty key and reported success.
- `claude-native` runs one session straight to Anthropic when the global file points at the gateway.

## Middleware

Each one changes only the requests sent to its own provider.

- `plugins/kiro-harness`: rewrites Claude Code's identity line into `<harness_instructions>`, because Kiro's own prompt already names the model Kiro. It also drops the billing line, which changes every request and spoils Kiro's prompt cache. Tests: `node --test plugins/kiro-harness/kiro-harness.test.mjs`.
- `plugins/zed-compat`: drops `context_management` (Zed rejects `clear_thinking_20251015`) and wraps a plain-string message into a text block. Tests: `node --test plugins/zed-compat/zed-compat.test.mjs`.
