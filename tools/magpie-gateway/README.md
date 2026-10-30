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

So keep interactive sessions that are already running off the gateway. Since the evening of 2026-10-25, by the owner's decision, the Opus, Sonnet and Haiku groups try the three Claude Team seats first (`claude/claude-opus-5-5` and so on). `stays=session` keeps a conversation on the seat that first answered it, so a gateway session is retold only when its seat reaches its cap and it moves to the next seat, once per move. Each seat is capped at 95% of its windows (`magpie provider account-cap claude "<email> · DuoCode" 95`), the threshold seat-guard and the dispatcher use, so the gateway leaves the last 5% to sessions signed in to that seat directly.

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
$M plugin add /plugins/long-off-seats.middleware.js
$M plugin add /plugins/upstream-compat.middleware.js
$M plugin options /plugins/upstream-compat.middleware.js '{"providers":["bedrock-glm5","deepseek","devin"]}'
$M plugin add /plugins/context-budget.middleware.js
```

## Routing groups

The group ids are Claude's own model names. A request for `claude-opus-5-5` reaches the group, and Claude Code still recognises the model by name, so its effort levels and context window behave as on Anthropic. Since 2026-10-27 every group has `stays=auto`, magpie's default: a conversation stays with the account or key that answered it while its cache there is worth keeping, and is routed afresh after that. With `stays=session` before, a session that fell to GLM-5 or SWE-2 while the seats were full stayed there for the rest of its life (back: `magpie group set <id> stays=session`).

| group | members, in order |
|---|---|
| `claude-opus-5-5` | `claude/claude-opus-5-5` (the three seats) → `kiro/claude-opus-5.5` → `devin/claude-opus-5-5` |
| `claude-sonnet-5-5` | `claude/claude-sonnet-5-5` → `zed/claude-sonnet-5-5` → `kiro/claude-sonnet-5.5` |
| `claude-haiku-5-5` | `claude/claude-haiku-5-5` → `zed/claude-haiku-5-5` → `kiro/claude-haiku-5.5` → `opencode-go/claude-haiku-5-5` |
| `claude-fable-5-1` | `group/claude-opus-5-5` |
| `long-opus` | `kiro/claude-opus-5.5` → `group/long-sonnet` |
| `long-sonnet` | `zed/claude-sonnet-5-5` → `kiro/claude-sonnet-5.5` → `group/frontier` |
| `long-haiku` | `zed/claude-haiku-5-5` → `kiro/claude-haiku-5.5` → `workbuddy/deepseek-v4.1-flash` → `trae-cn/glm-5.3-flash` → `opencode-go/claude-haiku-5-5` |
| `frontier` | `zed/gpt-6.1-sol` → `grok/grok-4.7` → `zed/gpt-6-sol` → `trae-global/gpt-6.1-sol` → Kimi K3.1 Pro, GLM-5.3, DeepSeek V4 Pro (WorkBuddy, Trae CN) → `trae-cn/qwen3.8-max` → `workbuddy/minimax-m3` → `trae-cn/Doubao-Seed-2.1-Pro` → the OpenCode Go copies |

Kiro (1000 credits a month) is kept for Opus, so Sonnet goes to Zed first. Since 2026-10-31 the three Claude groups hold Claude alone (the owner, after a night on GLM-5.3: no GLM unless needed): GLM, Grok, Bedrock GLM-5, `frontier` and `always-up` (both hold GLM) are out of them, and `server/glm-guard.py` puts GLM back at the end only while the seats are about to run out (see below). Members are named `provider/model`: a stored group that names magpie's found `auto-*` groups gets them marked "not served". Copilot exposes only `copilot/auto`, and the `claude` provider (the subscription bridge) exposes only Opus, Sonnet and Haiku 5.5 (`magpie provider models claude claude-opus-5-5 claude-sonnet-5-5 claude-haiku-5-5`), never Fable.

Within `claude/*`, magpie picks the seat by its Smart routing (the seat with room that renews soonest). A 429 "usage limit reached", or a seat's reading at its cap, rests that seat and the same request goes to the next seat at once; with all three resting the group moves on to its next member. Readings of the two seats Claude Code isn't signed in to come only from the answers they give, so they can be hours old until a request lands there. `X-Magpie-Account: <email> · DuoCode` pins a request to one seat for a test.

Measured on the first night (2026-10-25 21:00 to 10-26 01:12): about ten long sessions that had been running on the non-Claude members moved onto a seat as soon as one had room, and each move retold the conversation (up to 1481 messages, 835K tokens written to the cache in one request). weiliu@ went from 0 to used up in 39 minutes (283 gateway requests, 3.41M cache-write tokens), gmail in 34 minutes after six sessions moved onto it within ten seconds (3.25M). New sessions that start on a seat and stay there don't pay this: a five-turn session stayed on one seat with cache writes of 140 to 1,368 tokens a turn.

So since 2026-10-26 the seats take short conversations only. `plugins/long-off-seats` sends a request for one of the Claude groups that it estimates at 200K tokens or more to that group's copy without the seats (`long-opus`, `long-sonnet`, `long-haiku`, the chains the Claude groups had before the seats); a shorter one keeps the seats first. A new Claude Code session starts at about 55K-66K, and every costly move that night was 239K or more. A conversation that grows past 200K on a seat leaves it for the copy, and when every member of the copy is out of its allowance it waits rather than coming back to a seat. As a second fence the three seat models are told to take 200K (`magpie model context claude/claude-opus-5-5 200k`, the same for Sonnet and Haiku), so magpie leaves them out of a longer request; that alone isn't enough, since magpie asks a member it left out as too small after all when every member with room is out of its allowance (a 406K-token request reached a seat that way in testing).

Rollback: `magpie group set claude-opus-5-5 models=kiro/claude-opus-5.5,group/claude-sonnet-5-5`, the same for the Sonnet and Haiku groups without their `claude/*` member, then `magpie provider models claude none`. For the length fence alone: `magpie plugin off /plugins/long-off-seats.middleware.js` and `magpie model context claude/<model> --reset`.

Checked on 2026-10-25 with a three-turn Claude Code session through the gateway: Read and Bash on the client machine, recalling the previous turn with no tool, then a subagent. The hostname and a nonce that exists only in a local file came back right, and the transcript has structured `tool_use` and no `<invoke>` text. `zed/claude-sonnet-5-5` passes with `zed-compat`. A Copilot student account answers only `copilot/auto`; any named model gets 400 "The requested model is not supported".

Checked again after the chains above, with `claude -p --allowedTools Bash` running `echo TOOLCHECK-$((6*7))` on each id: all five groups and 15 single models answered `TOOLCHECK-42` (Zed Claude and GPT-6.1/6 Sol, Grok 4.7, Doubao, WorkBuddy GLM, the `auto/` Kimi, GLM, DeepSeek, Qwen, MiniMax, `copilot/auto`). `claude-opus-5-5` went Kiro 429 (monthly credits used up) → Zed Sonnet. OpenCode Go was out of its weekly allowance and Trae Global was rate-limited. Gemini on Zed fails under Claude Code: the Zed plugin sends the thinking level as `high` and the tool mode as `AUTO`, where Zed wants `HIGH` and `auto` (plugin 0.1.11), so no group carries Gemini.

## Health alerts

`server/fleet-watch.py` runs on the gateway host every 5 minutes (`magpie-fleet-watch.timer`). It reads the day's routing log. A group whose answers to clients in the last 15 minutes hold at least 3 failures, and at least half failures, gets an ntfy saying it is broken (a 499, the client hanging up, isn't a failure), and one more when it recovers. A group with no success for 60 minutes gets one tiny real request ("reply PONG") with its own gateway key, `fleet-watch`, user agent `fleet-watch/1`; two failed probes in a row also count as broken. The groups are busy, so nearly every run sends nothing. The probes go one at a time: with the seats full every group falls to the same paid member, and six probes at once pushed it into 429 on 10-27. The day's probes, tokens and the providers they landed on go into `/var/lib/magpie-fleet-watch/daily.jsonl`. Alerts go through the ntfy relay in `/etc/llm-gateway/ops.env`.

On 10-27, its first evening: down `long-opus` 20:00 and `claude-opus-5-5` 20:06 (68 failures, 57 successes in 15 minutes, every seat at its cap and the fallbacks out of credits), up 20:24 and 20:42. Its 42 probes that day came to 26.7K tokens, 241 of them on the paid GLM-5.

Install: `fleet-watch.py` to `/opt/magpie/monitor/` (root, 700), the key in `/etc/llm-gateway/fleet-watch.key` (600), the two unit files to `/etc/systemd/system`, then `systemctl enable --now magpie-fleet-watch.timer`. Off: `systemctl disable --now magpie-fleet-watch.timer`. Tests: `python3 server/fleet-watch.test.py`.

## GLM overflow guard

`server/glm-guard.py` runs on the gateway host every 5 minutes (`magpie-glm-guard.timer`). It reads every Claude subscription's 5-hour use, reset time and reading time from magpie's cards (`/v1/magpie/quotas/cards` inside the container, kept fresh by seat-refresh; nothing is asked of Anthropic), each seat's cap from `providers.json` (`accountWindowCaps` "5 hours", else `accountCaps`, else 100), and the last 30 minutes of use from `quota-history.json`. An account whose 7-day window is used up counts as having nothing left.

- Open (when closed): every seat has less than 15% left, or at the last 30 minutes' pace what the seats have left before their caps runs out within 30 minutes and before the first seat resets. It runs `magpie provider on zcode` if ZCode is off, then `magpie group set <id> models+=zcode/GLM-5.3` for Opus and Sonnet and `models+=zcode/GLM-5.3-Flash` for Haiku. The groups route in order, so GLM answers only once every Claude member is out.
- Close (when open): a seat read in the last 20 minutes has 50% or more left (it has just reset). The GLM members come out, and ZCode is turned off again only if the guard turned it on. Pace is not looked at here: magpie keeps an active conversation on the member that answered it (`stays=auto`), so while GLM stays in the group the sessions that fell to it stay on it; taking it out sends them back to Claude, and the open rule puts it back 15 minutes later if the pace still calls for it.
- At least 15 minutes between an open and a close. Every run reconciles: while closed, those GLM members are taken out of the three groups even if someone added them by hand.
- Each switch is logged to `/var/lib/magpie-glm-guard/log` and sent over mesh to `feishu-assistant` (else `feishu-assistant-backup`, else the ntfy relay in `/etc/llm-gateway/ops.env`), from a send-only sender `magpie-glm-guard` with its own device token in `/etc/magpie-glm-guard/mesh.env` (600).

Install: `glm-guard.py` to `/opt/magpie/monitor/` (root, 700), `mesh.env` with `MESH_RELAY_URL` and `MESH_TOKEN`, the two unit files to `/etc/systemd/system`, then `systemctl enable --now magpie-glm-guard.timer`. Pause: `touch /etc/magpie-glm-guard/paused` (each run exits without touching anything). Off: `systemctl disable --now magpie-glm-guard.timer`. `glm-guard.py --dry-run` prints what it reads and what it would run. Tests: `python3 server/glm-guard.test.py` (fake cards, relay and magpie on 127.0.0.1).

## Feishu assistant fallback (N150)

The Feishu assistant on N150 is pinned to `provider=magpie`, so a gateway outage took the assistant down with it (the nights of 10-26 and 10-27). Three files keep it reachable:

- `client/gw-fallback.n150.py`, in the container as `/feishu-cc/bin/gw-fallback.py`. Every 5 minutes it sends one tiny request with the assistant's own gateway key, model and address (on a seat about 25 s and 1.7K tokens, about 0.5M seat tokens a day). After a failure it checks every minute. Three failures in a row write the flag `/feishu-cc/gw-fallback/direct`, holding the gateway address, and send an ntfy. When the assistant is idle (its last turn finished and 60 s with nothing new, or 20 minutes into the outage regardless) it ends the claude process still on the gateway, and cc-connect resumes the same session with `--resume` on the next message. Five good checks in a row remove the flag and send an ntfy, and the direct process is ended when idle so the next one is back on the gateway. It never edits `config.toml` or restarts cc-connect or the container. With another provider selected it only checks.
- `client/claude-bypass.n150.sh`, the `cmd` cc-connect starts (`/opt/data/feishu-cc/bin/claude-bypass`). When the flag holds the gateway address the process was given, it drops the gateway variables, so claude goes straight to the seat signed in in the container, a gateway-only model name (`frontier`, `auto/…`) becomes Opus, and `GW_FALLBACK_DIRECT=1` is set.
- `client/gw-fallback.n150.sh`, on the host as `/opt/data/feishu-cc/bin/gw-fallback`, from cron every minute (`* * * * * /opt/data/feishu-cc/bin/gw-fallback >/dev/null 2>&1`). It holds the lock, feeds the container's recent log in for the idle check, and hands the checker's ntfy lines to `/opt/data/sre/notify.sh`. Off: remove the cron line, then delete the flag.

Log `gw-fallback/log`, state `gw-fallback/state.json`; `"drill": true` in the state marks the ntfy titles as a drill until it switches back. Tests: `python3 client/gw-fallback.test.py`.

## Client

```sh
install -m 755 client/magpie-client client/claude-gw client/claude-native ~/.local/bin/
vk run -r "K=个人/magpie 网关 (llm-gateway)/MAGPIE_KEY_<MACHINE>" -- sh -c 'printf %s "$K" | magpie-client setup'
```

- `magpie-client setup` writes `~/.claude/magpie-settings.json` (mode 600): `ANTHROPIC_BASE_URL`, `ANTHROPIC_CUSTOM_HEADERS` (`x-api-key: <gateway key>`), `CLAUDE_CODE_ATTRIBUTION_HEADER=0`, and a `modelPicker` that adds `frontier`, GPT-6.1 Sol, Grok 4.7, Kimi, GLM, DeepSeek, Qwen, MiniMax and Doubao after the built-in rows of `/model`. `magpie-client picker` adds the rows to an existing file. In `/model`, press `s` to switch the session only: Enter also saves the model as the default in `~/.claude/settings.json`, and a plain `claude` session can't use a gateway id. It does not touch the global settings. There is no `ANTHROPIC_AUTH_TOKEN`, so Claude Code keeps its claude.ai sign-in, and mesh channels and claude.ai connectors keep working.
- `claude-gw` adds `--model claude-opus-5-5` unless a model is given. Like the shell's `claude` wrapper, it puts `--channels plugin:mesh@sunkit` last for an interactive session. On Windows, use `client/claude-gw.cmd` with the same settings file in `%USERPROFILE%\.claude`.
- Installed on 2026-10-25 on m4, m2, aws-sin, msi-wsl, MSI (Windows), wrsm, bd and devdesk. Each machine got a reply through the gateway from `claude-gw -p`. N150's Feishu assistant gets the gateway as a second cc-connect provider (`/provider magpie`), with Anthropic kept as the default.
- `magpie-client on` / `off` write the gateway into or out of **the global** `~/.claude/settings.json`. Per the section above, don't. Values a running session already loaded stay until it restarts, so deleting the two keys doesn't take a session off the gateway. Empty strings do, through a hot reload. Empty values in the global file also override a process's own environment, so delete them once every session has restarted.
- The 2026-10-25 fix: the key reaches the writer through the environment. The heredoc is python's stdin, so a piped key was lost, and the old version wrote `x-api-key: ` with an empty key and reported success.
- `claude-native` runs one session straight to Anthropic when the global file points at the gateway.
- `client/cc-compactor.py` (`~/.local/bin/cc-compactor`, config in `~/.config/cc-compactor/config.toml` from `client/cc-compactor.toml`): multi-dimensional weighted context compaction and cross-harness handoff engine. It combines local Claude Code `.jsonl` transcript state (`C_raw`, cache TTL remaining, `r_tool`, `r_edit`) with live gateway pool telemetry (`GET /v1/magpie/quotas`) to score five candidate actions (`STAY_NOOP`, `WAIT_KEEP_WARM`, `WARM_PRECOMPACT`, `BYOK_JSONL_SPLICE`, `CROSS_HARNESS_HANDOFF`) under configurable weight profiles (`balanced`, `cache_first`, `zero_claude_burn`, `speed_first`). `cc-compactor explain` prints the 5D cost table; `cc-compactor compact` extracts deterministic AST/git/file/error ground truth, distills middle turns through the gateway's BYOK chain (`auto-glm-5-3-flash` → `always-up`), backs up the transcript, and splices a native Claude Code `compact_boundary` + `isCompactSummary` pair into the `.jsonl`; `cc-compactor handoff` writes `.claude/handoff/current.md`. Tests: `python3 client/cc-compactor.test.py`.

## Middleware

Each one changes only the requests sent to its own provider.

- `plugins/context-budget`: provider-aware context window budgeting, surgical fallback slimming (`onProvider`), and cache-aware weighted seat strategies (`context-budget/weighted`, `context-budget/ceiling`). Leaves primary `claude` seat prefixes untouched below the 1M ceiling so prompt cache is never invalidated by sliding edits; when a request routes to a smaller-window fallback (`zcode` 200K, `bedrock-glm5` 202,752, `devin` 262,144, `deepseek`/`grok` 131,072), progressively slims that provider attempt only (head+tail truncation of older `tool_result` and text blocks, base64 image eviction, pair-safe middle turn folding that keeps `tool_use` and `tool_result` coupled, and `max_tokens` / `thinking.budget_tokens` clamping). Also tracks per-seat `cacheWrite` and `cacheRead` in `onUsage` so `context-budget/weighted` combines soft/hard quota ceilings (`ceiling=88`, `hardCeiling=98`), expiring-window (`soon`) discounts, and warm-cache stickiness. Tests: `node --test plugins/context-budget/context-budget.test.mjs`.
- `plugins/kiro-harness`: rewrites Claude Code's identity line into `<harness_instructions>`, because Kiro's own prompt already names the model Kiro. It also drops the billing line, which changes every request and spoils Kiro's prompt cache. Tests: `node --test plugins/kiro-harness/kiro-harness.test.mjs`.
- `plugins/long-off-seats` (onRequest, before routing): a request for `claude-opus-5-5`, `claude-fable-5-1`, `claude-sonnet-5-5` or `claude-haiku-5-5` (bare, `group/…` or `[1m]`) estimated at `threshold` tokens or more (200000) goes to `group/long-opus`, `group/long-sonnet` or `group/long-haiku`; a model named with its provider is left as asked. The estimate walks every string in the body, ASCII at 3.5 characters a token, any other character a token, an image 1,600, and stops at the threshold; on two captured Claude Code requests it gave 62K and 79K where the bridge counted about 66K-71K, in about a millisecond. Tests: `node --test plugins/long-off-seats/long-off-seats.test.mjs`.
- `plugins/upstream-compat`: for the providers in its `providers` option (default `bedrock-glm5`, `deepseek`, `devin`), renames any tool name outside `[a-zA-Z0-9_-]{1,64}` in the history and in `tools` (one bad name GLM-5 wrote on 10-27 made every later request fail: Bedrock with a 400 naming `toolUse.name`, Devin with a bare 400 "an internal error occurred", and a 400 of that kind isn't retried); strips Claude Code's deferred-tool blocks for `bedrock-glm5` and `deepseek` (DeepSeek's 422 "unknown variant `tool_definition`"); and for `bedrock-glm5` turns `tool_result` content Bedrock refuses into text. A 3 MB body takes about 27 ms. For `bedrock-glm5` it also lowers `max_tokens` to what the 202,752-token window leaves after the prompt (an estimate that errs high, never under 8,192): Bedrock counts the reply asked for against the window, Claude Code asks for 40,000, so any prompt over about 162K failed with a 400 magpie doesn't retry (10-27 17:20-17:23, when GLM-5 was the only member of `long-opus` with room). `windows` in the options sets a window for another provider. Tests: `node --test plugins/upstream-compat/upstream-compat.test.mjs`.
- `plugins/zed-compat`: drops `context_management` (Zed rejects `clear_thinking_20251015`), wraps a plain-string message into a text block, and moves the tools of `tool_addition` blocks (Claude Code loading deferred tools mid-conversation, sent when it knows the model id, as it does for the `claude-*` groups) into the request's `tools`. Tests: `node --test plugins/zed-compat/zed-compat.test.mjs`.
