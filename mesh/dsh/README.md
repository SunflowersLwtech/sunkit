# DSH bridge

DeepSeek Harness has no channels and no per-turn hook that can be woken by a peer, so a DSH
session joins the mesh through a small bridge instead of an installer: the peer runs in **push**
mode (a real session, listed like any other), keeps running beside the agent, spools inbound
messages to a file the agent reads, and sends whatever the agent appends to an outbox file.

That is deliberately not `MESH_JOIN=pull`: a pull session only sees mail when it calls
`read_messages`, and a DSH turn may never call a tool. Push + spool means a message that arrives
while the agent is idle is still there on its next turn.

```bash
node mesh/dsh/dsh-mesh.mjs join --name m4-dsh      # daemon; Ctrl-C to leave
node mesh/dsh/dsh-mesh.mjs say feishu-assistant "…" # one-shot, send-only
```

Files, under `~/.mesh-names/<name>/`:

| file | what |
|---|---|
| `inbox.jsonl` | one line per message: `{ts, from, msg_id, content}` |
| `outbox.jsonl` | append `{"to": "name", "message": "…"}`; the bridge sends it within a second |

The session is named `MESH_SESSION_NAME` (here `--name`), so replies to a message it sent come
back to the same session. Identity (relay URL, token, handle) comes from `~/.claude-mesh/config.json`,
the same file `mesh pair` writes for every other host.

Two things this does not do: it cannot interrupt a running turn (a DSH turn polls the inbox when
it chooses to), and `mesh list` shows it as `unknown` rather than `busy`/`idle` — the bridge has no
lifecycle events to report. Treat a DSH peer as "reads on its next turn".
