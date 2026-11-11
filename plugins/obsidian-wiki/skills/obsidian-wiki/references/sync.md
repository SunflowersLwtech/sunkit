# Multi-device vault sync — the generic lessons

> Long form for the sync section of SKILL.md. The vault is a plain folder;
> every device that opens it exchanges parts of that folder with a remote copy
> through some sync mechanism. Whatever the exact pieces (a community sync
> plugin, an S3-compatible bucket, a cron'd `rclone`/rsync loop, git), the
> failure modes below are measured and repeatable — read this when a write did
> not arrive, when provisioning a device, or before any bulk rename/delete.

## The mental model: loops, not mirrors

Sync is **eventual**, and different devices have different loops:

| Loop kind | Typical cadence | Properties |
|---|---|---|
| GUI plugin timer (runs inside the app) | minutes, nominal ~5 | runs only while the app is open; **phones/iOS only while the app is foregrounded** |
| Headless cron (rclone/rsync + lock) | minutes | reliable push/pull; **carries its own filter rules**; local deletes often never propagate (the loop re-pulls the file) |
| Pull-only mirror | minutes | never pushes — **a note written there reaches nobody**; say so instead of implying it synced |
| Git-backed | commit/push cycles | conflicts become merge work; history is a safety net |

So there are at least two write paths per endpoint — *guarded* (a tool of yours
that writes remotely first, or applies under a lock) and *loop* (the file lands
locally and waits for the next round). Anything written through the loop path is
**provisional** until the round has run and been verified.

## Verdicts, not vibes

- **Written ≠ synced.** A successful local write says nothing about the remote.
  Verify per file the cheap way that answers the real question — *are my bytes
  on the remote?* A byte/hash or etag comparison (local md5 vs remote ETag) is
  the honest check; **mtime-only checks pass even when another device's later
  write replaced your section**.
- **Status bars lie.** Every sync plugin's status bar reads "synced just now" at
  the end of whatever the run did, including a run that moved nothing or an
  aborted run. Judge by content comparison and by the tool's own records
  (sync logs/plan tables), never by the label.
- **Pending, failing and wedged look identical from outside** — all three print
  nothing. If a file should have pushed: read the tool's own log/verdict first,
  then force one round (a CLI command to the running app if available), then
  the deeper debugging (below).

## Whole-file conflict resolution eats concurrent writes

The common sync design settles a two-sided change by keeping the **newer whole
file**. That means: two sessions (or two machines) appending to the *same
shared file* — an index page, a task list — ends with one side's change
silently dropped. Measured failure: three index lines vanished in a single
morning under exactly this rule.

Practices that survive:

1. **Serialize shared-file writes.** One guarded entry point per shared file
   (a small script that: takes a cross-machine lock or advisory lock, GETs the
   current remote copy, applies the change to *that*, puts it back, verifies
   the read-back hash, then writes the same bytes locally with the remote's
   mtime so the next round sees both sides as equal).
2. If a guarded write must fall back to a plain local write (remote
   unreachable), **report it as provisional** — any other device's whole-file
   push can still silently drop it. Re-verify after the next round.
3. **Re-read shared files after every sync round** when writing to a hot one;
   expect `carried:`-style reconciliation to be the norm, not an error.

## Each endpoint syncs a subset — and every local check sees the whole folder

Filters differ per endpoint: many plugin configs never upload names beginning
with `.` or `_`; headless loops carry their own exclude lists; a credential or
manifest stored in a dotfile exists **only where it was written** until you
have seen it arrive remotely — while `ls`, the editor and every local script
show a complete tree and nothing reports an error. Consequences:

- Keep tool state you care about in a **non-dot path** or a real secret store.
  A payload that requires a dot path is not carried by the vault at all.
- Before trusting that something synced, check the remote yourself for that
  exact path.

## Deletes are the dangerous direction

- A deletion propagates only if a sync **reports it** before another device
  pushes state; otherwise the file comes back (remote copy read as new).
- A device that has been offline for weeks is **chronically behind**, and its
  backlog will not drain in one run. **Never bulk-delete the stale local copy
  to "start fresh"** — the sync propagates deletes to the remote and hence to
  every device. Set the endpoint to skip upload (download-only) until it has
  caught up.
- Bulk deleting on the remote: always **list first**, confirm each doomed key
  has a live counterpart, delete a tiny batch, re-count, then continue. Never
  pass a prefix/bulk mode casually — a wrong flag can mean the entire bucket.
- Files deleted *outside the sync tool* (plain `rm`) are invisible to its
  deletion log and typically **come back on the next pull**. Remove them
  remotely too.

## Renames and bulk reorganisation

- A rename is not atomic to the sync: it looks like one file deleted and one
  created. If the next round runs before the deletion is reported, the old name
  is **pulled back and you have both**. After renaming, compare counts on both
  ends and reconcile.
- **Bulk folder renames = stop sync first, on every device, not just yours.**
  Measured: a large folder reorganisation was reverted minutes later when a
  peer restored hundreds of files from the remote, and both machines converged
  on the broken state. Order: stop every device's sync → verify the new path
  holds all the files → remove the old keys remotely → restart and watch the
  count not climb.
- Only **resolved** wikilinks get rewritten by a link-safe rename; already
  broken links stay broken through renames and compound quietly. Check the
  unresolved list between consecutive renames.

## Provisioning a new device

- **Let the sync tool do the first download.** Pre-populating the folder by
  copying files gives every file an mtime of *now*, the tool reads every file
  as a conflict, and the "change ratio" guard (typically aborting at ~50 %)
  **aborts the sync in silence** — it looks exactly like "there was nothing to
  sync". Diagnose it in the tool's plan/log records; the fix is to deliver
  files with preserved mtimes (e.g. `rsync -a`) or not pre-populate at all.
- Placing a fully-formed `.obsidian/` config folder into the vault directory
  usually works on macOS/Android (the app adopts it on open; grant folder
  access and trust the author). Windows needs the vault registered in the app's
  config; **GUI-first-run dialogs block headless setups** — budget for one
  interactive click, or script via a scheduled task in the interactive session.
- iOS/iPadOS has a closed filesystem: install plugins through the app itself;
  there is no background sync, so the app must be open (and the status visible)
  while catching up. Put the vault under the device's own storage ("On My
  iPhone"), **not** iCloud Drive — iCloud and the sync plugin will fight over
  the same files.
- Decide on **end-to-end encryption before the second device** joins: enabling
  it later means re-uploading the remote with every device sharing one
  password. Without it, whoever holds the storage credentials can read the
  vault — which is one more reason credentials do not live in the vault.

## Debugging a write that did not arrive

1. Verify content, not times: compare local md5 with the remote ETag.
2. Read the sync tool's own records (its status area, plan/log tables, dev
   console) before waiting longer.
3. A **wedge** (runs never complete) is fixed by reloading just the sync
   plugin, not by restarting the app; verify from remote content afterwards.
4. Network probes from inside an embedded web view are CORS-bound — probe with
   the host app's own request facility, not `fetch`.
5. Watch for resolver/endpoint failures that masquerade as remote outages:
   when a host resolves manually but the API client "can't connect", pin the
   resolved IP at the HTTP layer (e.g. `curl --resolve host:443:ip`) rather
   than disabling DNS features.
