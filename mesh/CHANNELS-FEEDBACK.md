# Field notes on `claude/channel` from building claude-mesh

Notes for the Claude Code team, written after taking the research-preview
[`claude/channel`](https://code.claude.com/docs/en/channels-reference) MCP
extension from zero to a working cross-machine mesh. Everything below comes
from things we actually hit; file paths reference this repo so each claim can
be checked.

**What we built:** a self-hosted HTTP relay (Hono + SQLite + SSE) plus a
per-machine MCP stdio server, so Claude Code instances on different laptops
can DM, broadcast, thread, and route permission approvals to each other.
Inbound peer traffic reaches the model as `<channel source="peers" ...>` tags;
outbound goes through three MCP tools (four with permission relay on). One zod
envelope schema is the wire format end to end. See [README](./README.md) for
architecture and the five-layer injection defense.

**Test environment:** Claude Code v2.1.80–2.1.81, Windows 11, claude.ai
login, Node 22/24. Inbound delivery (CLI → relay → SSE → peer-agent →
`<channel>` tag in a live session) verified 2026-04-18.

---

## What worked well

- **The containment model.** Channel bodies arriving as structured
  `<channel>` tags (rather than as tool results or user turns) gave us a
  clean place to hang the "untrusted user input" framing. Our whole L4/L5
  defense (body escaping + server `instructions` charter) builds on it.
- **`instructions` as a defense surface.** The server-level `instructions`
  string turned out to be load-bearing for the injection threat model. The
  guidance in the channels reference was a solid starting text; we adapted it
  in `packages/peer-agent/src/instructions.ts`.
- **First-answer-wins on permission relay.** Remote verdict and local dialog
  racing, first one resolving the request, is exactly the right semantic for
  "ask a teammate but never lock out the local human."
- **The notification surface is small and learnable.** Three methods
  (`notifications/claude/channel`, `.../permission_request`,
  `.../permission`) covered everything a full mesh needed.

## Friction log

Ordered by how much time each one cost us.

### 1. Channel notifications drop silently without the CLI flag

The single hardest debugging session of the project. The MCP server loads,
tools list and work, `initialize` succeeds. But every
`notifications/claude/channel` vanishes unless Claude Code was launched with
`--dangerously-load-development-channels server:<name>`. The only evidence is
one line in `~/.claude/debug/*.txt`:

```
MCP server "claude-mesh-peers": Channel notifications skipped: server claude-mesh-peers not in --channels list for this session
```

Nothing in `/mcp`, no handshake warning, no server-visible signal. It took
multiple diagnosis rounds to connect "tools work" with "notifications don't."

**Suggestions:** surface the skipped state in `/mcp` output next to the
server; and/or allow enabling per-server channels in `settings.json` so teams
can roll a channel server out without wrapping the `claude` launch command.

### 2. The server can't tell whether channels are live

The server declares `experimental['claude/channel']` in its capabilities, but
the `initialize` exchange gives no indication back whether this session will
actually deliver channel notifications. Our peer-agent would happily stream
messages into the void; users saw "delivered" on the sender side (relay-level
delivery) and nothing in the recipient's session. If the client echoed channel
enablement in the `initialize` result, the server could log a loud warning —
or a bridged UI could tell the user exactly what flag is missing.

### 3. claude.ai-auth-only keeps channels out of CI

Channels don't work on API-key auth, so no headless environment can exercise
delivery. Our end-to-end scenario tests
(`packages/e2e/src/scenarios/dm.test.ts`, `broadcast.test.ts`) drive a real
`claude --print` binary and therefore skip by default (`CLAUDE_DRIVER` gate) —
which means the part of the stack most exposed to wire-format drift is the
part CI can't watch. Any headless-capable path (API-key opt-in, a test mode,
or a published notification-schema fixture set) would close that hole.

### 4. Escaping and rendering guarantees are underspecified

Peer content is attacker-controlled in our model, so we needed to know exactly
how `<channel>` tags render into context to prevent a peer from forging a
sibling tag or breaking out of the body. The reference doesn't pin this down;
we ended up property-testing our own escaping (500-run fuzz in
`packages/shared/src/channel.test.ts` asserting escaped bodies can never
contain a literal `</channel>`). A short "here is how tag bodies are
escaped/rendered, here is what the client guarantees" section would let
builders rely on the platform instead of re-deriving it.

### 5. Version gates are discoverable only by testing

Base channels need v2.1.80, permission relay needs v2.1.81. We found the
split empirically. A small capability/version matrix in the reference (and
ideally a runtime error naming the required version) would save the next
builder the bisect.

## What we'd ask for next

1. **A stability signal.** Even "the notification method names and
   `<channel>` attribute set won't change without a minor-version note" would
   let projects like this one leave research-preview caveats behind.
2. **Settings-based channel enablement** (see #1).
3. **Capability echo in `initialize`** (see #2).
4. **A headless/CI story** (see #3).
5. **Multi-server channels ergonomics.** `server:<name>` per launch works for
   one server; composing several channel servers (mesh + Telegram bridge +
   ...) is where the flag approach gets unwieldy.

## Pointers

- Wire format: `packages/shared/src/envelope.ts` (one schema, four kinds,
  `superRefine` ties verdicts to requests)
- Injection defenses: README §Security model (L1–L5), spec-level detail in
  `packages/peer-agent/src/instructions.ts`
- Permission relay, both directions:
  `packages/peer-agent/src/permission-outbound.ts` (Claude Code → mesh) and
  `packages/peer-agent/src/inbound.ts` + `cli/respond.ts` (mesh → verdict)

Questions, repro requests, or "please stop doing X with our preview API":
open an issue on this repo. Happy to run experiments against new builds.
