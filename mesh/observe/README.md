# mesh observe

One read-only snapshot of the mesh — who is on it, where, doing what — rendered as a
self-contained page (no deps, no build step). It is the "see it" half of the mesh; the relay is
the "do it" half.

```bash
node mesh/observe/observe.mjs                 # JSON (pipe it anywhere)
node mesh/observe/observe.mjs --html out.html # the page
```

Data comes from two GETs only: `/v1/sessions` and `/v1/machines` on the relay, with the token in
`~/.claude-mesh/token` (`MESH_HOME` and `MESH_RELAY` override). Nothing is written to the mesh.
If a DSH bridge is running for `m4-dsh`, its `bridge.state.json`, inbox cursor and failed-send file
are folded in — that is the only place a delivery *state* exists today.

## The contract it proposes

Any agent-messaging system (claude-mesh, DSH Agent Teams, a community plugin) can fill the same
row if it answers four questions: **who → who, did it arrive, how long, who has read it**.

```json
{ "ts": "…", "system": "mesh",
  "from": { "session": "m4-dsh", "account": "duocode", "device": "duocode-m4" },
  "to":   { "session": "feishu-assistant", "ref": "s7kexj" },
  "msg_id": "msg_…", "bytes": 412,
  "state": "delivered", "latency_ms": 180 }
```

Today: `/v1/sessions` answers *who is where*; the sender's outbox offset answers *sent*; the
receiver's inbox cursor answers *read*; `outbox.failed.jsonl` answers *failed*. The relay keeps no
per-message history, so `latency_ms` is only known to a sender that records it — a relay-side
`/v1/events` (or a shared append-only event log) is the missing piece before the page can show
delivery latency for everyone.

## Refreshing

A page is a snapshot. To keep one current, run it on a timer and republish the same slug:

```bash
*/10 * * * * node …/observe.mjs --html /tmp/mesh-observe.html && foldrender publish /tmp/mesh-observe.html --slug mesh-observe
```

`foldrender publish` updates the page in place when the content changed and says so when it did not.
