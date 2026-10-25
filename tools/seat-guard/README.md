# seat-guard

When the Claude seat a machine's Claude Code is signed in to runs out, `seat-guard` moves every session on that machine to the saved seat with the most room. Requests still go straight to Anthropic, so conversations, tools, mesh channels and Remote Control are unaffected.

Part of [sunkit](../../README.md). It is not a plugin. It is a single Python file with no dependencies, for Claude Code that keeps its sign-in in `<config dir>/.credentials.json`: Linux, containers and WSL. On macOS the sign-in is in the keychain, so use cc-switch there.

## The rule

`seat-guard tick` runs from cron every 2 minutes. When the active seat's 5-hour window reaches **95%**, or its 7-day window 99%, it switches to the saved seat with the least 5-hour use, if that seat is under **80%**. Set `SEAT_GUARD_HIGH` and `SEAT_GUARD_LOW` to change the thresholds. It never switches twice within 5 minutes.

It reads every seat from Anthropic's `/api/oauth/usage`, the same endpoint cc-switch uses. magpie's own "used-up switch" can't do this for Claude Code that talks to Anthropic directly: magpie reads only the seat Claude Code is signed in to (its docs say "A saved Claude account that isn't signed in is never read"), so it never knows what the spare seats have left.

## How a switch lands

Before each API request, a running Claude Code checks whether `.credentials.json` changed (its mtime). Running and future sessions therefore move on their next request. A request already in flight finishes on the old seat. A turn that already stopped on "usage limit reached" needs any next message.

Refresh tokens are single-use, so each seat's token family lives in exactly one place:

- the active seat in `.credentials.json`;
- the others in `<config dir>/.seat-guard/<email>.json`.

A switch first saves the outgoing family to its own file, under Claude Code's own refresh and storage locks, then loads the incoming one. If a write fails partway, it restores both files. A saved seat whose access token has expired is refreshed by seat-guard, which is its only holder.

The active seat is identified by its token, through `/api/oauth/profile`, not by the `oauthAccount` label in `.claude.json`. A running Claude Code can write its old label back after a switch, and a family saved under the wrong name would overwrite another seat's. `tick` repairs a label that disagrees with the token.

When `.claude.json` is a file bind-mounted on its own into a container, renaming over it fails with EBUSY, so seat-guard writes it in place.

## Setup on a machine

```sh
install -m 755 seat-guard ~/.local/bin/
# each spare seat: a separate sign-in, made on this machine
CLAUDE_CONFIG_DIR=~/.claude/.seat-guard/login-x claude auth login --claudeai
seat-guard import ~/.claude/.seat-guard/login-x && rm -rf ~/.claude/.seat-guard/login-x
seat-guard status
( crontab -l; echo '*/2 * * * * $HOME/.local/bin/seat-guard tick >> $HOME/.claude/.seat-guard/cron.log 2>&1' ) | crontab -
```

`seat-guard import-magpie` takes the spare Claude seats out of a magpie `logins.json` instead.

Each machine signs in to each seat on its own. Never copy a token family between machines.

Running on (2026-10-25):

- aws-sin;
- N150, where feishu-cc, pi and the workers share `/opt/data/claude/dot-claude`. Cron runs `docker exec feishu-cc …/python3 /feishu-cc/bin/seat-guard tick`.

## Tests

`python3 -m unittest test_seat_guard` runs 8 tests against a fake Anthropic on localhost:

- a switch to the emptiest seat, with an expired saved token refreshed first;
- no second switch within 5 minutes;
- staying put when no seat is under the low mark, or when the active seat has room;
- an EBUSY global config written in place;
- a failed credentials write rolled back;
- a stale label never naming the saved family;
- `tick` repairing a stale label.
