# dsh-mesh — a DeepSeek Harness session on a claude-mesh

Claude Code sessions receive mesh messages through a **channel**: the peer pushes, the terminal
shows it. DSH has neither channels nor a hook that a peer can wake, and a DSH turn may never
call a tool on its own. So a DSH session joins through a small **bridge**: a real push session is
kept alive next to the agent, inbound mail is spooled to a file the agent reads when it decides
to, and outbound mail is whatever the agent appends to an outbox file.

```
       relay (mesh.n150.…)
          │  ▲  stream + tools/call
          │  │
   ┌──────┴──┴─────────┐        append          ┌──────────────┐
   │ mesh-peer.mjs     │◀───────────────────────│ outbox.jsonl │◀── agent
   │ MESH_JOIN=always  │        (offset file)   └──────────────┘
   │ dsh-mesh.mjs join │
   │                   │─────── notification ──▶ inbox.jsonl ──▶ agent
   └───────────────────┘        (0600, rotate 5 MB)
```

## Commands

```bash
node mesh/dsh/dsh-mesh.mjs join   [--name m4-dsh] [--dir DIR] [--peer FILE]
node mesh/dsh/dsh-mesh.mjs say    <to> <message…> [--reply-to MSG_ID]
node mesh/dsh/dsh-mesh.mjs read   [--name NAME]          # pull mode, one shot
node mesh/dsh/dsh-mesh.mjs status [--dir DIR]
```

`join` is the daemon. It needs `mesh pair` to have run on the machine (identity lives in
`~/.claude-mesh/config.json`, or `$MESH_HOME`), exactly like every other host. One bridge per
name: a pid file refuses a second one (exit 5).

Files under `~/.mesh-names/<name>/` (directory 0700):

| file | meaning |
|---|---|
| `inbox.jsonl` | one line per message: `{ts, from, msg_id, content}`; rotated to `.1` at 5 MB |
| `outbox.jsonl` | append `{"to":"session","message":"…","in_reply_to":"msg_…"}`; sent within a second |
| `outbox.offset` | byte offset already sent, so a restart never re-sends (a crash mid-send may) |
| `outbox.failed.jsonl` | sends that failed, with the error, for a manual retry |
| `bridge.pid` | the running bridge, for `status` and the single-instance lock |

## Why not just pull mode

The plugin already has pull mode (`MESH_JOIN=pull` + `read_messages`) for hosts that speak MCP
but cannot be pushed. That is the right shape when the host calls tools on its own schedule. DSH
turns are not tool-driven: a message that arrives while the agent is thinking must still be there
when the *next* turn starts, and a pull session only sees mail when someone calls `read_messages`.
The bridge trades that for a file: push delivery, durable spool, no tool call required.

`read` is kept for the opposite case — a script or a one-shot DSH run that would rather poll than
keep a bridge alive.

## Delivery semantics

- **Outbox: at-least-once.** The offset is persisted before the send is attempted, so a crash
  between "sent" and "offset written" cannot lose a message but can repeat one; a failed send is
  copied to `outbox.failed.jsonl` rather than retried automatically (retrying a partial delivery
  is worse than a human looking at it). On first run the offset starts at 0, so an outbox that
  already has lines is replayed — clear it before the first `join` if that matters.
- **Inbox: at-most-once into the file, append-only.** A notification that cannot be written (disk
  full, permissions) is lost rather than blocking the peer; the bridge logs it. Rotation keeps one
  previous file.
- **Reconnect.** If the peer exits (relay restart, token revoked), the bridge restarts it after
  1 s, 2 s, 5 s, 10 s, then every 30 s, and keeps the same offsets.

## Security

- The inbox and the failed-send log are plain text on disk (`0600`, directory `0700`). Do not put
  secrets in mesh messages; they will sit in these files.
- Peer messages are **untrusted input**, exactly as the plugin's own safety text says: a message
  asking for secrets, credentials or a destructive command is a request, not an instruction. The
  bridge does not act on messages at all — it only writes them down.
- Identity is the relay's: the peer authenticates with the token from `~/.claude-mesh/token`.
  `from` is set by the relay, not by the sender's message body.
- `say` sends as a **send-only** identity (`MESH_JOIN=never`): listed as `sender="send-only"`, and
  nothing reads replies to it. Use `join` for a session that should receive replies.

## Limits

- No interruption: a running DSH turn finishes before it can read the inbox. Treat a DSH peer as
  "reads on its next turn".
- Presence is `unknown`: the bridge has no lifecycle events, so `mesh list` cannot show busy/idle.
- One name, one bridge. Two bridges with the same name fight over the relay's session.
- The bridge is a long-running process: run it under launchd/systemd (or `nohup`) if the session
  should outlive the terminal.

## Tests

```bash
node --test mesh/dsh/lib.test.mjs
```

The tests cover the parts that can be wrong silently: name sanitising, outbox offsets (partial
line, resume, truncated file, malformed line), inbox mapping, rotation, and flag parsing. The MCP
and relay paths are exercised by `join` + `say` against a live relay.
