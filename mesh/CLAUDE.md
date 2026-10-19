# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`claude-mesh` is a **networked messaging substrate for Claude Code instances**: a self-hosted HTTP relay + per-Claude MCP channel server that lets Claudes on different machines DM, broadcast, thread, and approve tool-permissions for each other. Built on Anthropic's research-preview `claude/channel` MCP extension.

**Status: software-complete and released.** All 33 plan tasks are done; the relay ships as a Docker image (`ghcr.io/pouriamrt/claude-mesh/relay`, published on `v*.*.*` tags). Inbound `<channel>` tag delivery is verified against real Claude Code (v2.1.80+). Outbound permission_request relay is wired and unit-tested but not yet smoke-tested across two live Claude sessions. Remaining known gaps are listed in README §Caveats — keep that section honest when you change them.

The original design docs live in `docs/superpowers/` (spec + 33-task plan) but `docs/` is **gitignored** — local-only. README.md is the public source of truth.

## Commands

The repo is a **pnpm 10 workspace**. Node 22 or 24 (25 lacks prebuilt `better-sqlite3`). Run from the repo root.

```bash
pnpm install                                   # install all workspace deps
pnpm -r build                                  # build every package
pnpm -r typecheck                              # tsc --noEmit across the workspace
pnpm -r exec vitest run                        # full suite (~193 tests; e2e L3 scenarios skip without CLAUDE_DRIVER)
pnpm -r test:ci                                # vitest run + coverage thresholds

# Scope to one package:
pnpm -F @claude-mesh/relay exec vitest run
pnpm -F @claude-mesh/shared exec vitest run channel          # single test file
pnpm -F @claude-mesh/shared exec vitest run -t "round-trip"  # single test name

# L3 end-to-end against a real claude binary:
CLAUDE_DRIVER=cli pnpm -F @claude-mesh/e2e exec vitest run
```

Coverage thresholds (enforced in each package's `vitest.config.ts`): 95% lines on `shared`, 85% on `relay`; `peer-agent` gates are lower (CLI entry points + SSE client excluded — exercised by the L3 harness instead).

## Architecture (big picture)

```
Claude Code ──stdio──▶ peer-agent (MCP channel server) ──HTTPS/SSE──▶ relay (Hono + SQLite)
```

1. **`@claude-mesh/shared`** — zod envelope schema (the wire format), `<channel>` serializer, monotonic ULID helpers, constants. Pure types/validators, no IO.
2. **`@claude-mesh/relay`** — Hono + better-sqlite3 + SSE. Routes: `POST /v1/messages` (Idempotency-Key), `GET /v1/stream?since=<ulid>`, `POST /v1/presence`, `GET /v1/peers`, `POST /v1/auth/pair`, `POST /v1/permission/respond`, `/v1/admin/*`. In-memory fanout registry; SQLite for durable buffering.
3. **`@claude-mesh/peer-agent`** — stdio MCP server declaring `experimental['claude/channel']` (+ `claude/channel/permission` when enabled). Inbound: SSE → `InboundDispatcher` → `notifications/claude/channel*`. Outbound: MCP tools `list_agents` and `send_message` (session-addressed; `resolve-target.ts`). It joins the mesh only when its parent Claude Code process opted it in as a channel and the org policy cache allows it (`join-policy.ts`); otherwise it is send-only. With `MESH_JOIN=pull` it joins in pull mode for hosts without channels (Devin CLI, Antigravity CLI, Grok Build, pi): no channel capability, inbound chat goes to a bounded inbox (`inbox.ts`) read with the `read_messages` tool, the name comes from `probeHostSession` (never Claude's registry), and a local socket (`hook-socket.ts`) lets the host's lifecycle hooks (`mesh agy hook`, `mesh grok hook`, and for pi the extension in `pi-extension.ts`, bundled as `mesh-pi.mjs`) see the inbox and report busy/idle. Permission relay is never declared. Also home of the `mesh` CLI (`pair`, `send`, `say`, `devin install`, `agy install`, `agy hook`, `grok install`, `grok hook`, `pi install`, `admin ...`). `pnpm bundle` builds the peer, the CLI and the pi extension into `plugins/mesh/server/` for the Claude Code plugin.
4. **`@claude-mesh/e2e`** — L3 harness: in-memory relay + paired humans; scenario tests gated behind `CLAUDE_DRIVER`.

### Key invariants to preserve

- **`from` is server-populated from the token** on every message. Peer-agents cannot set it. Primary anti-impersonation defense.
- **ULIDs are monotonic** (`shared/src/ulid.ts` uses `monotonicFactory()`). The SSE resume cursor is `WHERE id > ?` and relies on strict ordering within a millisecond.
- **`<channel>` body escaping** (`shared/src/channel.ts`) prevents forged sibling tags; a 500-run property test asserts escaped bodies never contain `</channel>`.
- **Envelope is *the* wire format.** One `EnvelopeSchema`, four kinds (`chat`, `presence_update`, `permission_request`, `permission_verdict`). `permission_verdict` requires `in_reply_to` (enforced via `superRefine`).
- **Permission outbound never throws.** `relayPermissionRequest` swallows bad params and relay outages — the local approval dialog must survive anything the mesh does.

### Prompt-injection threat model

Peer messages land in Claude's context. The `instructions` string in `packages/peer-agent/src/instructions.ts` downgrades peer content to "untrusted user input" with a four-point safety charter. **Do not weaken this wording.** Sender gating (roster check), `claude/channel/permission` off by default, and `approval_routing = never_relay` by default are layered defenses (spec §6, summarized in README §Security model).

## TDD discipline

Every change is a TDD cycle: **failing test → RED → implement → GREEN → one atomic conventional commit** (`feat(scope):`, `fix:`, `docs:` ...). Don't batch unrelated changes. If a change breaks an existing test, fix the root cause — never weaken the test.

## Windows-specific notes

- `warning: LF will be replaced by CRLF` on `git add` is cosmetic.
- Forward slashes in paths inside commands; `\` breaks Git Bash tools.
- Node's `homedir()` reads `USERPROFILE` on Windows. To run two mesh identities on one machine, set `MESH_HOME` for one of them.
- `better-sqlite3` needs MSVC Build Tools if no prebuilt binding matches your Node.

## Gotchas already paid for (don't re-hit)

1. **`ulid()` default export is not monotonic** — use `monotonicFactory()` (done in `shared/src/ulid.ts`). SSE resume depends on it.
2. **TS 5.7+ needs `allowImportingTsExtensions` + `rewriteRelativeImportExtensions`** for the `import './foo.ts'` convention (set in `tsconfig.base.json`).
3. **MCP SDK ≥1.29 is typed against `zod/v4`.** Extending SDK schemas (e.g. `NotificationSchema.extend`) requires `import { z } from 'zod/v4'` — the v3 root export fails typecheck with a missing `_zod` property.
4. **Channel notifications are silently dropped** unless Claude Code launches with `--channels plugin:mesh@sunkit` (org allowlist) or the dev flag, and the managed settings Claude Code applies allow it (the org's server-managed cache first, then the machine's MDM profile / `managed-settings.json`; see `managed-policy.ts`). The only trace is a "Channel notifications skipped" line in `~/.claude/debug/*.txt`. The `initialize` handshake is identical either way, which is why `join-policy.ts` reads the parent command line.

## What *not* to do

- **Don't commit tokens, `admin.token`, `*.paircode`, or `.claude-mesh/` dirs.** `.gitignore` covers them; the peer-agent refuses to start if its token file sits in a git worktree with a remote.
- **Don't change the `<channel>` tag shape or the `instructions` string** without re-reading the threat model. Both are security-critical surfaces.
- **Don't skip typecheck / test gates.** They have caught real bugs at every phase.
- **Don't assume `claude/channel` behavior from training data.** Research-preview; authoritative reference is <https://code.claude.com/docs/en/channels-reference>. v2.1.80+ (v2.1.81+ for permission relay), claude.ai login required.
