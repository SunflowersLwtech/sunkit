#!/usr/bin/env python3
"""
Claude Desktop Cowork Archived Session Recovery Tool

Recovers archived Cowork sessions that become invisible due to a UI bug
in Claude Desktop (macOS & Windows). The Cowork tab has no "Archived"
filter, so once a session is archived, it disappears with no way to
view or restore it from the UI.

Note: The Code tab's archive filter bug was fixed in Claude Desktop
build 1.1.3647 (2026-02-19). This tool focuses on Cowork sessions,
which remain affected. Use --include-code to also scan Code sessions.

Bug references:
  - https://github.com/anthropics/claude-code/issues/24534

Usage:
  python3 claude_unarchive.py                # Interactive: list & choose
  python3 claude_unarchive.py --list         # List archived sessions only
  python3 claude_unarchive.py --restore-all  # Restore all at once
  python3 claude_unarchive.py --dry-run      # Preview without changes
  python3 claude_unarchive.py --include-code # Also scan Code sessions
"""

import json
import os
import platform
import sys
import shutil
from datetime import datetime
from pathlib import Path


def get_claude_data_dir() -> Path:
    """Get the Claude Desktop data directory for the current platform."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            print("Error: APPDATA environment variable not found.")
            sys.exit(1)
        return Path(appdata) / "Claude"
    else:
        print(f"Error: Unsupported platform '{system}'. This tool supports macOS and Windows.")
        sys.exit(1)


def find_archived_sessions(base_dir: Path, include_code: bool = False) -> list[dict]:
    """Scan for archived session JSON files in Cowork (and optionally Code) directories."""
    archived = []

    search_dirs = {"Cowork": base_dir / "local-agent-mode-sessions"}
    if include_code:
        search_dirs["Code"] = base_dir / "claude-code-sessions"

    for mode, search_dir in search_dirs.items():
        if not search_dir.exists():
            continue

        for json_file in search_dir.rglob("local_*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if data.get("isArchived") is not True:
                    continue

                title = data.get("initialMessage", data.get("title", data.get("name", "")))
                if isinstance(title, str) and len(title) > 80:
                    title = title[:77] + "..."
                if not title:
                    title = "(Untitled)"

                created = data.get("createdAt", "")
                if isinstance(created, (int, float)):
                    try:
                        created = datetime.fromtimestamp(created / 1000).strftime("%Y-%m-%d %H:%M")
                    except (OSError, ValueError):
                        created = str(created)

                archived.append({
                    "path": json_file,
                    "mode": mode,
                    "title": title,
                    "created": created,
                    "data": data,
                })
            except (json.JSONDecodeError, PermissionError, OSError):
                continue

    return archived


def restore_session(session: dict, dry_run: bool = False) -> bool:
    """Restore a single archived session by setting isArchived to false."""
    path = session["path"]

    if dry_run:
        print(f"  [DRY RUN] Would restore: {path.name}")
        return True

    backup_path = path.with_suffix(".json.backup")
    try:
        shutil.copy2(path, backup_path)
    except OSError as e:
        print(f"  Warning: Could not create backup: {e}")

    try:
        data = session["data"]
        data["isArchived"] = False

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

        print(f"  Restored: {path.name}")
        return True
    except (PermissionError, OSError) as e:
        print(f"  Error restoring {path.name}: {e}")
        if backup_path.exists():
            try:
                shutil.copy2(backup_path, path)
                print(f"  Rolled back from backup.")
            except OSError:
                pass
        return False


def print_session_list(sessions: list[dict]) -> None:
    """Pretty-print the list of archived sessions."""
    if not sessions:
        print("\nNo archived sessions found. Everything looks good!")
        return

    print(f"\nFound {len(sessions)} archived session(s):\n")
    print(f"{'#':<4} {'Mode':<8} {'Created':<18} {'Title'}")
    print("-" * 80)
    for i, s in enumerate(sessions, 1):
        print(f"{i:<4} {s['mode']:<8} {s['created']:<18} {s['title']}")


def interactive_restore(sessions: list[dict]) -> None:
    """Interactive mode: let user pick which sessions to restore."""
    print_session_list(sessions)

    if not sessions:
        return

    print(f"\nOptions:")
    print(f"  Enter number(s) to restore (e.g., '1' or '1,3,5')")
    print(f"  Enter 'all' to restore all")
    print(f"  Enter 'q' to quit\n")

    choice = input("Your choice: ").strip().lower()

    if choice == "q":
        print("Exiting without changes.")
        return

    if choice == "all":
        indices = list(range(len(sessions)))
    else:
        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
            for idx in indices:
                if idx < 0 or idx >= len(sessions):
                    print(f"Error: Invalid number {idx + 1}. Valid range: 1-{len(sessions)}")
                    return
        except ValueError:
            print("Error: Invalid input. Enter numbers separated by commas.")
            return

    restored = 0
    for idx in indices:
        if restore_session(sessions[idx]):
            restored += 1

    print(f"\nDone! Restored {restored}/{len(indices)} session(s).")
    print("Please restart Claude Desktop to see the restored sessions.")


def main():
    args = sys.argv[1:]

    dry_run = "--dry-run" in args
    list_only = "--list" in args
    restore_all = "--restore-all" in args
    include_code = "--include-code" in args

    if "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)

    base_dir = get_claude_data_dir()

    if not base_dir.exists():
        print(f"Error: Claude data directory not found at {base_dir}")
        print("Make sure Claude Desktop is installed.")
        sys.exit(1)

    scope = "Cowork + Code" if include_code else "Cowork only"
    print(f"Scanning: {base_dir} ({scope})")
    if not include_code:
        print("Tip: Use --include-code to also scan Code sessions.\n"
              "     (Code tab archive filter was fixed in build 1.1.3647)")
    sessions = find_archived_sessions(base_dir, include_code=include_code)

    if list_only:
        print_session_list(sessions)
        sys.exit(0)

    if dry_run:
        print(f"\n[DRY RUN MODE] No files will be modified.\n")
        print_session_list(sessions)
        if sessions:
            print()
            for s in sessions:
                restore_session(s, dry_run=True)
        sys.exit(0)

    if restore_all:
        if not sessions:
            print("\nNo archived sessions found. Nothing to restore.")
            sys.exit(0)
        print_session_list(sessions)
        print()
        restored = 0
        for s in sessions:
            if restore_session(s):
                restored += 1
        print(f"\nDone! Restored {restored}/{len(sessions)} session(s).")
        print("Please restart Claude Desktop to see the restored sessions.")
        sys.exit(0)

    interactive_restore(sessions)


if __name__ == "__main__":
    main()
