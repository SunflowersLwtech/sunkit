# mesh observe

The mesh as the desk's Mesh page shows it (`foldrender.dev/desk/mesh`): who is on it, on which
machine, with which harness and model, busy or idle, and each message it carried — who to whom,
how long it took to arrive, or that it is still waiting. The relay is the "do it" half; this is
the "see it" half.

```bash
node mesh/observe/observe.mjs                          # what would be sent, as JSON; nothing sent
node mesh/observe/observe.mjs --desk-feed              # send one snapshot to the desk
node mesh/observe/observe.mjs --desk-feed --every 60   # and again every minute, until stopped
```

Data comes from two GETs only — `/v1/sessions` (who is on) and `/v1/events` (the delivery log,
read from where the last read stopped) — with the mesh token in `~/.claude-mesh/token`
(`MESH_HOME`, `MESH_RELAY`, `MESH_TOKEN_FILE` override). The snapshot goes to the desk as one
feed replace (`PUT <api>/desk/<desk>/feed/<source>`, a desk feed token from a 600 file). Nothing
is written to the mesh, and no message's words are read or sent.

## What it sends

One `peer` thing per session (key its ref): state `busy`/`idle`/`away`/`unknown`, body `machine`,
`account`, `ref`, `harness`, `model`, `mode` (`push`/`pull`) and `where` (the repository). One
`message` thing per message (key its id): state `sent` or `delivered`, body `msg_id`, `from`,
`to`, `sent_at`, and when delivered `at`, `latency_ms` (the relay's own number, copied) and
`via`. A body carries only what changes with the state — no ages, no last-seen times — so a
snapshot with no news writes nothing on the desk.

The desk's names for machines are `MESH_DESK_MACHINES`, a JSON file of `{"<device or herdr
machine>": "<the desk's name>"}`; `desk-machines.json` is the mapping the N150 pusher runs with.

A relay that does not answer for its sessions sends nothing (the page is never emptied); a relay
without the delivery log still sends the sessions; a thing the desk refuses is dropped and the
rest sent; a `429` from the log is read again on the next send.

## Running it here

On N150 the pusher runs beside the relay as its own small container (`mesh-observe`), host
network, 128 MB, the repository read-only at /app and the two tokens read-only at /secrets:

```bash
docker run -d --name mesh-observe --restart unless-stopped --network host --memory 128m \
  -v /opt/data/mesh/observe:/app:ro -v /opt/data/mesh/observe/secrets:/secrets:ro \
  node:22-bookworm-slim node /app/observe.mjs --desk-feed --every 60
```

with `MESH_TOKEN_FILE=/secrets/mesh-token`, `FOLDRENDER_DESK_TOKEN_FILE=/secrets/desk-feed-token`
and `MESH_DESK_MACHINES=/app/desk-machines.json` in the environment.

## The contract it proposes

Any agent-messaging system (claude-mesh, DSH Agent Teams, a community plugin) can fill the same
row if it answers four questions: **who → who, did it arrive, how long, who has read it**. The
desk's `message` kind is that row; `/v1/events` answers *arrived, and how long* for every message
the relay carried.
