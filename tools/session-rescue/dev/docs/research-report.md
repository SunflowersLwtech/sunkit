# Claude Desktop Cowork Archive Bug - Research Report

**Date**: 2026-02-21
**Researcher**: @SunflowersLwtech

---

## Bug Summary

Claude Desktop's **Cowork** tab has an archive button but **no "Archived" filter** in the sidebar. Once a Cowork session is archived, it disappears permanently from the UI. The session data remains on disk at `local-agent-mode-sessions/` with `"isArchived": true`, but there is no UI path to view or restore it.

### Status by Module

| Module | Archive Button | Archive Filter in UI | Bug Status |
|--------|---------------|---------------------|------------|
| Chat | Yes | Yes (works) | No bug |
| Code | Yes | Yes (was broken) | **Fixed in build 1.1.3647 (2026-02-19)** |
| Cowork | Yes | **Does not exist** | **Still broken as of 2026-02-21** |

---

## Key Finding: Code Tab Bug Was Fixed

Claude Desktop build **1.1.3647** (released 2026-02-19) fixed the Code tab's archived session filter. The session query was incorrectly filtering out archived sessions -- this has been corrected.

Current user version: **1.1.3541** (needs update for Code fix).

**The Cowork tab was NOT included in this fix.** The Cowork sidebar has no "Archived" filter at all, which is a separate UI gap.

---

## Existing GitHub Issues

### Issue #24184 (macOS, Code tab) -- Effectively Fixed
- **URL**: https://github.com/anthropics/claude-code/issues/24184
- **State**: OPEN (but fix shipped in 1.1.3647)
- **Description**: Archived Code sessions show "No sessions found" in Archive filter. 169 files exist on disk.

### Issue #24534 (Windows, Code tab + Cowork mention)
- **URL**: https://github.com/anthropics/claude-code/issues/24534
- **State**: OPEN
- **Key comment from @rsfuruya (2026-02-11)**: Confirmed same issue on macOS with **Cowork sessions** -- "Archived" filter does not appear at all in the Cowork tab's sidebar.
- This is the only place the Cowork-specific bug is mentioned; no standalone issue exists.

---

## Existing Tools (None cover Cowork)

| Tool | Handles Cowork archive? | Notes |
|------|------------------------|-------|
| [Session Extract (gchamon)](https://gist.github.com/gchamon/0949dc427086d387e9164b229271288b) | No | Session search/restore for `claude -r`, no isArchived handling |
| [Session Restore (ZENG3LD)](https://github.com/hesreallyhim/awesome-claude-code/issues/556) | No | Context restoration from git history, no archive recovery |
| Manual JSON edit | Yes (workaround) | Requires knowing file paths and JSON editing |
| **This tool** | **Yes** | **First automated Cowork archive recovery** |

---

## Recommendation

1. **Publish recovery tool** to GitHub -- the only automated solution for Cowork archive recovery
2. **Comment on Issue #24534** with tool link, specifically for Cowork users
3. **Optionally file a new Cowork-specific issue** since #24534's title only mentions Code tab
