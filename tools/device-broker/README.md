# device-broker

Host-local lease registry for shared agent resources: Android emulators, iOS
simulators, browser debug ports and profile directories. Part of
[sunkit](../../README.md). Not a plugin — a small set of bash wrappers in `bin/`.

## The problem it removes

On a machine running several agent sessions, `adb devices` shows
`emulator-5584` — and that serial says only which port answered, not whose it
is or which AVD sits behind it. On 2026-11-16 one session's emulator died and a
neighbour's `fold7` came up on the same port; the first session's
`adb -s emulator-5584 …` then ran against the wrong device and tapped through
its ANR dialog with no error at all. `agent-device` claims (the registry
`device-claim-check.sh` reads) record *which session wants* a device, but bare
`adb`, `emulator`, `xcrun` and every browser launcher bypass it — nothing
stops two sessions landing on the same port, and nothing ties a serial to a
real device identity.

The same shape recurs elsewhere: an `agent-browser close --all` that killed a
neighbour's browser, a `pkill -f "wrangler dev"` that stopped 24 sessions, two
iOS simulators booting together and driving M4 load past 270.

## The idea

**One resource, one lease.** A lease is a directory made with `mkdir` (atomic
on Linux and macOS) containing a `lease.json`: owner key, pid, the pid's start
time (so a reused pid can't inherit the lease), worktree, host, and resource
metadata (avd, port, udid, profile dir).

- **Who owns it** is decided by the registry, never by "the app in front looks
  like mine" — an agent that foregrounded its own app still destroys a
  neighbour's run.
- **Stale is structural**: lease holder's pid dead → stale; pid alive but its
  `lstart` no longer matches the recorded start → the pid was reused → stale.
  Stale leases are reclaimed by the next `acquire` or by `gc`. "Looks long
  idle" is never a reason — a holder sitting quiet is still the holder.
- **Fail closed**: unreadable lease file, missing registry, undeterminable
  ownership, physical-device serial — all refuse.
- **Never kills**: the tool removes lease *files* only. Stopping a device is
  the holder's own job, by the pid it recorded — never `pkill -f`, `killall`,
  `close --all`.

## Commands

```
device-broker acquire <resource> [--meta k=v …] [--ttl s] [--owner-pid p]
                      -> 0 ok · 3 held by other · 5 physical refused ·
                         6 type at cap · 4 undeterminable
device-broker release <resource>            only the live owner may release
device-broker check   <resource> [--require-mine]
                      -> 0 mine-or-free · 3 held by other · 4 undeterminable
device-broker status                        JSON list, live vs stale
device-broker gc                            drop stale lease dirs (kills nothing)
device-broker limits  list | get <type> | set <type> <n>
```

`acquire`'s default owner pid is the calling process (`PPID`), the agent's
shell — it outlives the one-shot `device-broker` call. `--owner-pid` overrides
(e.g. an emulator's real pid once it's known, which `emulator-run` does).

Identity across calls: set `DB_OWNER_KEY` (or `DB_SESSION`) to one value per
task — e.g. `export DB_OWNER_KEY="$(git rev-parse --show-toplevel):$$"` — and
every wrapper inherits it. `OWNER_KEY`/`--owner-key` exists for tests.

### Resource names and caps

| Resource | Cap default | Notes |
|---|---|---|
| `android-emulator:port-<n>` | type cap **1** | the adb console port; on devdesk/aws-sin the rule is one emulator at a time |
| `android-emulator:avd-<name>` | — | an AVD definition when not booting `-read-only` |
| `ios-simulator:udid-<u>` | type cap **1** | one booted simulator |
| `ios-simulator:host` | **1** | machine-wide boot budget (M4: cold boot spikes load to 150–280) |
| `browser:cdp-port-<n>` | 8 | parallel browser sessions on distinct ports |
| `browser:profile-<hash>` | 8 | one agent per profile dir |
| `physical-device:<serial>` | **0** | never auto-acquirable — a human may be holding it |

Caps live in `~/.device-broker/limits.json` (`limits set <type> <n>`). A new
lease of a type already at cap exits 6 and lists the live holders.

## Wrappers (`bin/`)

- **`emulator-run -avd X -port N [args]`** — leases `android-emulator:port-N`,
  starts the emulator, rewrites the lease with the emulator's real pid and the
  AVD name, releases when it exits.
- **`adb-run -s emulator-N <adb args>`** — before running adb, proves (1) a
  live lease exists on the port, (2) it belongs to this owner, and (3)
  `adb -s emulator-N emu avd name` returns the AVD the lease names. Any
  mismatch refuses: this is the check that would have stopped the 11-16
  incident, where the port's device was fold7 and the caller's lease was not.
  Physical serials exit 5.
- **`simctl-run <verb> <udid>`** — `boot` leases both `ios-simulator:udid-<u>`
  and the `ios-simulator:host` budget; other verbs verify the lease before
  running `xcrun simctl`. `shutdown` releases. Shared persistent simulators
  stay booted — release the lease, don't shutdown.
- **`browser-run --cdp-port N [--profile-dir P] -- <cmd>`** — leases the port
  (and profile) before exec'ing the browser; releases on exit.

## Testing

```
bash tests/run-tests.sh
```

13 cases, no real device needed — stubs stand in for `adb`. Covers the three
required counterexamples: a second holder's acquire refused (t1), re-acquire
after the holder's pid dies (t3/t4), and `adb-run` refusing when the device on
the serial isn't the leased AVD (t7). Mutation-checked: disabling the
pid-reuse compare turns t4 red; fail-open on foreign acquire turns t1 red;
dropping the AVD compare turns t7 red.

## What it deliberately does not do

- It is not a daemon and not a broker on port 5037 — adb stays the system adb.
- It cannot see agents that never call it. A bare `emulator`/`adb`/`xcrun`
  still bypasses the registry; the wrappers are the mediation, and the skills
  that drive devices must call them. That is a discipline problem, not a tool
  problem — same conclusion as `device-lease.md` drew for `agent-device`.
- Real hardware stays fail-closed; the human-owner checks in phone-use apply.
