# Claude Desktop Cowork Archived Session Recovery Tool

A cross-platform (macOS & Windows) tool to recover archived **Cowork** sessions that become invisible due to a UI bug in Claude Desktop.

## The Problem

The Cowork tab in Claude Desktop has an **archive button** but **no "Archived" filter** in the sidebar. Once you archive a Cowork session, it disappears permanently from the UI with no way to view or restore it.

Your data is still on disk -- just hidden. This tool finds and restores it.

> **Note**: The Code tab had a similar bug, which was fixed in Claude Desktop build **1.1.3647** (2026-02-19). The Cowork tab remains affected as of February 2026.

## Quick Fix

```bash
git clone https://github.com/SunflowersLwtech/claude-desktop-unarchive.git
cd claude-desktop-unarchive

# No dependencies needed -- pure Python 3
python3 claude_unarchive.py
```

Then **restart Claude Desktop**.

## Usage

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

## How It Works

1. Scans Claude Desktop's local Cowork data directory:
   - **macOS**: `~/Library/Application Support/Claude/local-agent-mode-sessions/`
   - **Windows**: `%APPDATA%\Claude\local-agent-mode-sessions\`
2. Finds all `local_*.json` files with `"isArchived": true`
3. Creates a `.backup` copy of each file before modifying
4. Sets `"isArchived": false` to restore visibility

## Data Paths

| Platform | Cowork sessions | Code sessions |
|----------|----------------|---------------|
| macOS | `~/Library/Application Support/Claude/local-agent-mode-sessions/` | `~/Library/Application Support/Claude/claude-code-sessions/` |
| Windows | `%APPDATA%\Claude\local-agent-mode-sessions\` | `%APPDATA%\Claude\claude-code-sessions\` |

## Related Issues

- [#24534](https://github.com/anthropics/claude-code/issues/24534) - Archived sessions not visible (includes Cowork confirmation in comments)
- [#24184](https://github.com/anthropics/claude-code/issues/24184) - Archived Code sessions not visible (macOS, fixed in 1.1.3647)

## License

MIT
