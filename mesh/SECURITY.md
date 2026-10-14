# Security Policy

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/SunflowersLwtech/sunkit/security/advisories/new)
for anything sensitive. Please don't open a public issue for exploitable bugs.
Fixed advisories are published to
[GitHub Security Advisories](https://github.com/SunflowersLwtech/sunkit/security)
with credit unless you ask otherwise.

## Supported versions

Only the latest `v0.x` release receives security fixes. Pin the relay image to
the newest tag and upgrade promptly; data in the `mesh-data` volume survives
upgrades.

## Threat model (v1)

| # | Threat | v1 mitigation |
|---|---|---|
| 1 | Peer impersonation | Relay stamps `from`/`account` from the authenticated bearer token and the sending session from the session that token owns; sender-supplied metadata can no longer override them (an upstream bug let `meta.from` overwrite the relay value). A session id cannot be attached or spoken for by another token. |
| 2 | Outsider injection | Bearer auth + team-scoped tokens on every route. |
| 3 | Relay compromise | **Out of scope in v1.** The relay is a trust anchor — a compromised relay could forge `from`. Client-side signatures are the planned v2 answer. Host it accordingly (Tailscale/private network, not the open internet). |
| 4 | Compromised peer machine | Containment + no permission relay + reply-storm limiter. **Under `--dangerously-skip-permissions` a paired peer can effectively drive your session; pair only accounts you trust that far.** |
| 5 | Prompt injection through legitimate peer content | `<channel>` structural containment (bodies escaped, sibling-tag forgery prevented, property-tested) + server `instructions` downgrading peer content to untrusted user input. |

## Layered defenses

1. **Relay-enforced identity** — `from` is authoritative.
2. **Sender gate** — inbound messages from handles missing on the `/v1/peers` roster are dropped silently.
3. **`<channel>` containment** — `<` / `>` / `&` escaped in bodies; a 500-run property test asserts escaped bodies never contain a literal `</channel>`.
4. **Action-tier gating** — this fork never declares the permission-relay capability; `send_message` is capped at 2 replies to the same sender within 10 s of an inbound message.
5. **Audit** — every message and permission event persisted; JSON access logs.

## Operational defaults worth knowing

- Token files are written mode `0600`; the peer-agent refuses to start if its token sits inside a git worktree with a remote (anti-`git push` leak).
- Tokens are never logged, never passed to child processes via env, never shown to the model.
- No remote approvals: the plugin never relays permission prompts.
- Delivery is per session: a message addressed to one session is never surfaced in a sibling session of the same account.
- Revocation is immediate: `mesh admin disable-user <handle>`.

## Known limitations

- `claude/channel` is a research preview; the wire contract may move under us across Claude Code releases.
- The admin token is a single-secret failure mode. Rotate it; keep it off teammate laptops.
- Single region, no HA.
