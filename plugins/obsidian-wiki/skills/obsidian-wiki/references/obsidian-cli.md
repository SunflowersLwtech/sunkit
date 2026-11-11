# The official `obsidian` CLI — reference (optional accelerator)

> Ships with recent Obsidian desktop builds (a small binary next to the app
> itself; on Windows `Obsidian.com`, on macOS inside the app bundle). An IPC
> client to the **running desktop app**: no app, no answers. Everything this
> file describes has a plain-file fallback named inline — the CLI's irreplaceable
> jobs are link-safe rename and app-state `eval`.

## Invocation and sharp edges

```
obsidian [vault=<name>] <command> key=value [flags]
```

- `file=<name>` resolves wikilink-style; `path=<path>` is exact from vault root.
- Values with spaces need quoting; `\n` and `\t` expand inside `content=`.
- **Parameter names are not guessable** (`property:read` wants `name=` not
  `key=`; `move` wants `to=` not `path=`). Run a command with no arguments and
  the error prints the exact usage line.

  **Except `delete`: never run `delete` with no arguments.** It does not print
  usage — it deletes the note currently open in the app, and reports
  `Moved to trash: <path>` for a file you never named. Any mutating command
  gets its usage from `obsidian --help | grep -A2 '^  delete'`, never from a
  bare invocation.

### Always wrap in a timeout

```bash
obsidian() { command timeout 20 obsidian "$@"; }   # macOS lacks timeout(1); use perl -e 'alarm …' there
```

Commands can block forever when the app is in a bad state. An unwrapped call
burns the whole tool-call budget.

### Exit code is always 0 — even on failure

```
$ obsidian read file=DoesNotExist ; echo $?
Error: File "DoesNotExist" not found.
0
```

`$?` is worthless. **Detect failure by matching `^Error:` on stdout.**

### `format=json` is per-command, not global

| Command | `format=json` | Shape |
|---|---|---|
| `backlinks` | yes | `[{"file": "path/to/note.md"}]` |
| `tags` | yes | `[{"tag": "#name"}]` |
| `search` | yes | `["path.md", ...]` |
| `files` | **silently ignored** | newline-separated paths |

Never assume a command honours the flag; check the output before parsing.

## The query commands worth knowing

```bash
obsidian vault                        # name, path, file count, folder count, size
obsidian files                        # every file, vault-relative paths
obsidian search query="prompt cache"  # matching paths
obsidian search:context query="..."   # path:line: matching text  ← use this one
obsidian read file=Note               # full file content
obsidian outline file=Note            # heading tree
obsidian backlinks file=Note format=json
obsidian links file=Note              # outbound; unresolved ones marked "(unresolved)"
obsidian unresolved                   # bare link names with no file  ← knowledge gaps
obsidian orphans                      # files nothing links to        ← disconnected
obsidian tags                         # merged frontmatter + inline
obsidian wordcount file=Note
```

`unresolved` and `orphans` are the two commands that make an agent-maintained
wiki self-correcting: one is a to-write list, the other a to-link list. Check
both at the end of any session that added pages.

### `eval` is the escape hatch

```bash
obsidian eval code="app.vault.getMarkdownFiles().length"
obsidian eval code="JSON.stringify(app.metadataCache.getFileCache(app.vault.getAbstractFileByPath('note.md')).frontmatter)"
```

Full app API, result prefixed with `=> `. Prefer a real command when one exists
— `eval` output is unstructured and the API is not stable across versions. The
same channel supports debugging (plugin state, console) — treat anything that
mutates the app or the visible window as off-limits for agents: no `reload`,
`restart`, `devtools` or window manipulation; app state is the user's
workspace.

## Writing through it

Writing files directly (Write tool / heredoc) is the default — see SKILL.md.
The CLI's writing commands (`create`, `append`, `property:set`) also work:

- `obsidian append file=Note content="..."` / `prepend` are cheaper than a
  read-modify-write for index pages, but note they start a new paragraph (a
  blank line precedes the text — enough to split a table).
- `obsidian property:set` rewrites the whole frontmatter block canonically
  (inline arrays become block lists). Harmless but do not use it where the
  frontmatter formatting matters.

## Rename — the trap

`obsidian rename file=Old name="New"` rewrites every inbound `[[Old]]` to
`[[New]]` — which bare `mv` never does, leaving the link graph broken.

**But only when `alwaysUpdateLinks: true` is set in `.obsidian/app.json`.**
Obsidian ships with it off. Measured, both ways:

| `alwaysUpdateLinks` | File renamed | Inbound links | Command behavior |
|---|---|---|---|
| `true` | yes | rewritten | returns instantly, prints `Renamed: old -> new` |
| `false` (default) | yes | **left broken** | **hangs, prints nothing** |

The failure is silent in the worst way: the rename appears to do nothing (no
output, no exit) while on disk the file moved and every link to it died.
Verify the setting before any rename:

```bash
grep -q '"alwaysUpdateLinks": true' "$VAULT/.obsidian/app.json" || { echo "refuse"; exit 1; }
```

Second-order trap: only **resolved** links get rewritten. A link that was
already broken stays broken through a rename. Check `unresolved` between
consecutive renames.

## Deleting — treat as permanent and sync-aware

- A CLI-reported "Moved to trash" does not guarantee the OS trash received the
  file. Take a copy first if the content is not reproducible.
- If the vault syncs, a delete made **outside the sync tool** is invisible to
  its deletion log and typically comes back on the next pull. Make deletions
  stick by removing the remote copy as well; conversely, a "lost" note may
  still exist remotely — check there before concluding anything is gone.

## Failure modes that are not bugs

| Looks like | Actually |
|---|---|
| Command hangs forever | App unfocused or wedged → activate the window (or `open -a Obsidian`), do not `reload` |
| `rename` does nothing | `alwaysUpdateLinks` is off — file DID move, links DID break |
| Script "succeeds" but nothing happened | Exit code is always 0; grep stdout for `^Error:` |
| `format=json` returns plain text | That command does not implement it |
| `Missing required parameter` | Parameter name differs from the obvious guess; read the usage line |
| New page invisible in the graph | Nothing links to it — check `orphans`, link from an index page |
| `[[Link]]` shows as broken | Intended for a not-yet-written page; it is the `unresolved` queue |
| `move` says `ENOENT ... rename` | Destination folder does not exist — `move` never creates it. `mkdir -p` first |
| Moved files vanish from `files`/`orphans`/search | App index didn't see the move; re-open the vault in the app or restart it |
| `sort \| uniq -c` over CJK paths gives wrong counts | macOS collation merges **distinct** CJK strings under one label. Use `LC_ALL=C` or count in Python. Any per-folder statistic taken this way is void |

## Session close-out

After adding or reorganising pages, run (CLI) or its grep fallbacks (SKILL.md):

```bash
obsidian unresolved      # anything worth writing next?
obsidian orphans         # anything that should be linked from an index?
obsidian files | wc -l   # compare against the disk: count sync/index desync
```

and link or note the results. Skipping this is how a wiki turns back into a
pile of files.
