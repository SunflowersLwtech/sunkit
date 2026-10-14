# claude-code-toolkit

Tools for working with Claude Code sessions: get stuck or archived sessions back, and let sessions on different accounts and machines talk to each other.

(Formerly `claude-session-rescue` / `cowork-archive-recovery`; old links redirect here.)

| Tool | For | What it does |
|------|-----|--------------|
| [`claude_rescue.py`](#claude-code-stuck-session-rescue-claude_rescuepy) | Claude Code CLI (macOS / Linux) | Finds interactive sessions stuck on repeated `API Error: Connection refused` and restarts them in place with `--resume` |
| [`claude_unarchive.py`](#claude-desktop-cowork-archived-session-recovery-claude_unarchivepy) | Claude Desktop (macOS / Windows) | Restores archived Cowork sessions that the UI can no longer show |
| [`mesh/`](mesh/README.md) | Claude Code CLI (macOS / Linux / Windows) | `list_agents` / `send_message` between sessions on **different accounts and machines**, via a self-hosted relay and a Claude Code channel plugin |

The two Python scripts are single files with no dependencies. `mesh/` is a separate Node/TypeScript project with its own [README](mesh/README.md).

## Claude Code Stuck Session Rescue (`claude_rescue.py`)

### The Problem

A single long-running interactive `claude` session starts answering every prompt with

```
API Error: Connection refused — a firewall or proxy may be blocking it (ECONNREFUSED)
```

and keeps doing so (observed for about 25 minutes), while other Claude Code sessions on the same machine, using the same network and the same account, keep working normally. Retrying in that session does not help.

Observed on macOS with the native install of Claude Code 2.1.295. What was ruled out at the time: the network and proxy (other sessions were fine through them), and the account (same login). **The root cause is unknown.** It looks like the stuck process holds on to some broken connection state, but that has not been confirmed.

What brings the session back, with its full history:

1. In the same terminal, type `/exit`.
2. If background shell tasks are running, a confirmation dialog appears; choose **Exit and stop tasks** (option 1, Enter).
3. Run `claude --resume <sessionId>`.
4. Send a prompt such as "continue".

`claude_rescue.py` detects sessions in this state and does those four steps for you in the pane where the session runs.

Upstream issue: [anthropics/claude-code#101687](https://github.com/anthropics/claude-code/issues/101687)

### Install

No dependencies, Python 3.8+:

```bash
curl -O https://raw.githubusercontent.com/SunflowersLwtech/claude-code-toolkit/main/claude_rescue.py
python3 claude_rescue.py
```

or clone the repository.

### Usage

```bash
# List live sessions and flag the stuck ones (default command)
python3 claude_rescue.py scan
python3 claude_rescue.py scan --json      # machine-readable
python3 claude_rescue.py scan --all       # include dead / non-interactive sessions

# Show what a restart would do, without touching anything
python3 claude_rescue.py revive my-session --dry-run

# Restart one session (by name, pid, session id, or an id prefix of 6+ chars)
python3 claude_rescue.py revive my-session
python3 claude_rescue.py revive 4ab1c2d3

# Restart every STUCK session
python3 claude_rescue.py revive --all-stuck

# Custom follow-up prompt, or none
python3 claude_rescue.py revive my-session --prompt "Continue with the migration."
python3 claude_rescue.py revive my-session --no-prompt

# Re-scan every 60 s; with --auto, revive stuck sessions
# (at most once per session per 10 min, at most 3 revives per hour)
python3 claude_rescue.py watch --interval 60
python3 claude_rescue.py watch --interval 60 --auto
```

Example `scan` output:

```
STATE  NAME           PID    VERSION   AGE  LAST  ERRS            SESSION
STUCK  api-worker     38726  2.1.290*  7d   2m    6 ECONNREFUSED  3f2a9c1e-5b7d-4e8a-9c61-2d0e8b4f7a13
OK     docs           88121  2.1.296   10m  1m    0               8c41d0b2-9e3f-4a76-b215-6f9e0c3d8a54
ERROR  frontend       41712  2.1.296   33m  22m   1 ECONNREFUSED  d7e95a40-1c2b-4f83-a6d9-0b5e7f2c9e81

* older than the installed version (2.1.296)
```

| State | Meaning |
|-------|---------|
| `STUCK` | 2 or more connection-type API errors (`ECONNREFUSED`, `ECONNRESET`, `ETIMEDOUT`, `ENOTFOUND`, `EPIPE`, connection error) since the last successful reply |
| `ERROR` | the latest replies are API errors, but not enough connection errors to call it stuck (e.g. a single error, or `overloaded` / rate limit, which affect every session alike) |
| `OK` | the latest reply succeeded |
| `DEAD` | the process is gone or the pid now belongs to another process (`--all` only) |

`VERSION*` marks a session running an older Claude Code than the one `~/.local/bin/claude` points at. That is informational; it is not evidence of the problem.

### How It Works

- Sessions come from `~/.claude/sessions/<pid>.json` (or `$CLAUDE_CONFIG_DIR/sessions`). A session is live when its pid exists and its start time matches the recorded `procStart`, so a reused pid is not mistaken for the session.
- The transcript is `~/.claude/projects/<cwd-slug>/<sessionId>.jsonl`. The same id can appear under more than one project directory; the most recently modified file is used. It is read backwards and stops at the last successful main-thread assistant reply, so large transcripts are cheap. Subagent (sidechain) replies are ignored.
- API failures are the assistant records flagged `isApiErrorMessage` or whose text starts with `API Error:`.
- The terminal pane is found through [herdr](https://herdr.dev) (`herdr pane list`, matched on the session id) or tmux (matched on the session's tty).

### Safety

`revive` only types into the one pane that runs the matched session, in this order:

1. `/exit` + Enter
2. Enter, only if the pane shows the **1. Exit and stop tasks** dialog (otherwise nothing; if the dialog's first option is something else it stops)
3. `claude --resume <sessionId>` + Enter, only after the old pid has exited
4. the follow-up prompt + Enter, only after a new `claude` process appears on that tty

It never sends signals or kills processes. A session that is not `STUCK` is left alone unless you pass `--force`. Use `--dry-run` to print the exact plan first. Note that step 2 stops the session's background shell tasks, exactly as choosing that option by hand would.

### Limitations

- macOS and Linux only; needs `ps`.
- Automatic restart needs the session to run inside herdr or tmux. Otherwise `revive` prints the manual steps and exits with status 2.
- Detection depends on the transcript and session-file formats of current Claude Code releases (verified with 2.1.29x); a format change can make it miss stuck sessions.
- If the pane has unsent text in the prompt box, `/exit` is appended to it; clear the box first.
- Restarting fixes the symptom only. The cause is still unknown.

## Claude Desktop Cowork Archived Session Recovery (`claude_unarchive.py`)

A cross-platform (macOS & Windows) tool to recover archived **Cowork** sessions that become invisible due to a UI bug in Claude Desktop.

### The Problem

The Cowork tab in Claude Desktop has an **archive button** but **no "Archived" filter** in the sidebar. Once you archive a Cowork session, it disappears permanently from the UI with no way to view or restore it.

Your data is still on disk -- just hidden. This tool finds and restores it.

> **Note**: The Code tab had a similar bug, which was fixed in Claude Desktop build **1.1.3647** (2026-02-19). The Cowork tab remains affected as of February 2026.

### Quick Fix

```bash
git clone https://github.com/SunflowersLwtech/claude-code-toolkit.git
cd claude-session-rescue

# No dependencies needed -- pure Python 3
python3 claude_unarchive.py
```

Then **restart Claude Desktop**.

### Usage

```bash
# Interactive mode - list archived sessions and choose which to restore
python3 claude_unarchive.py

# Just list archived sessions (no changes)
python3 claude_unarchive.py --list

# Preview what would be restored
python3 claude_unarchive.py --dry-run

# Restore all archived sessions at once
python3 claude_unarchive.py --restore-all

# Also scan Code sessions (usually not needed after build 1.1.3647)
python3 claude_unarchive.py --include-code
```

### How It Works

1. Scans Claude Desktop's local Cowork data directory:
   - **macOS**: `~/Library/Application Support/Claude/local-agent-mode-sessions/`
   - **Windows**: `%APPDATA%\Claude\local-agent-mode-sessions\`
2. Finds all `local_*.json` files with `"isArchived": true`
3. Creates a `.backup` copy of each file before modifying
4. Sets `"isArchived": false` to restore visibility

### Data Paths

| Platform | Cowork sessions | Code sessions |
|----------|----------------|---------------|
| macOS | `~/Library/Application Support/Claude/local-agent-mode-sessions/` | `~/Library/Application Support/Claude/claude-code-sessions/` |
| Windows | `%APPDATA%\Claude\local-agent-mode-sessions\` | `%APPDATA%\Claude\claude-code-sessions\` |

### Related Issues

- [#24534](https://github.com/anthropics/claude-code/issues/24534) - Archived sessions not visible (includes Cowork confirmation in comments)
- [#24184](https://github.com/anthropics/claude-code/issues/24184) - Archived Code sessions not visible (macOS, fixed in 1.1.3647)

## License

MIT
