---
name: macos-harness
description: >-
  macOS desktop automation protocol, companion detail skill of the `cua`
  router — whole-Mac control from one persistent session: screenshots,
  PID-targeted input, virtual pointer, Apple Accessibility, Apple Events, and
  a CDP escape hatch for Chromium-backed apps; without moving the physical
  cursor or forcing apps into the foreground. Includes the failure modes that
  cost real debugging time: Electron web views with no accessibility tree,
  native open/save panels invisible to CDP, input-dead apps, HID-only apps.
---

# macOS Harness

Control a Mac from one persistent scripting session: **one CLI call per decision
point, not per primitive.**

```bash
macos-harness <<'PY'
app = "Spotify"
mac.see(app)
mac.key("cmd+k", app=app)
mac.type("Alessia Cara", app=app)
print(mac.see(app))
PY
```

The CLI preloads `mac`, `browser`, `Path`, and `subprocess`. Prefer bounded stdin
programs; reserve `macos-harness repl` for manual exploration and always exit it.

> **The CLI itself is not part of this plugin.** This skill documents its
> six-verb contract — `see`, `key`, `type`, `click`, `ax`, `script` — and, more
> importantly, the behavioral rules and failure modes that any macOS automation
> stack hits. A thin Python wrapper over standard pieces reproduces it:
> screenshots plus the accessibility tree (e.g.
> [Peekaboo](https://github.com/steipete/peekaboo)), Quartz event posting
> (`CGEventPost`) for PID-targeted input, `osascript` for Apple Events,
> `screencapture`, and raw CDP for Chromium surfaces. The sections below tell
> you exactly when each piece is the right one and where each one silently
> fails.

## Minimize round trips

- Bundle deterministic, reversible steps into one program, then verify once. Opening
  search, typing a query, and capturing the results is one burst—not three calls.
- Stop at a genuine decision boundary: ambiguous identity, new coordinates, an
  irreversible action, or unexpected state. Inspect once, then run the next burst.
- Do not screenshot merely to confirm that a known shortcut opened a text field
  before typing. Let the final screenshot verify the whole sequence.
- Poll exact AX or Apple Events state inside the same program when possible;
  do not make the agent repeatedly ask whether a transition finished.
- Use the cheapest strong end-state check. Prefer one screenshot for visible state
  or one exact API/AX query for semantic state; use both only when they prove
  different things.

## Use the small surface

Think in six verbs: `see`, `key`, `type`, `click`, `ax`, `script`.

```python
frame = mac.see("Spotify")
mac.key("cmd+k", app="Spotify")
mac.type("Alessia Cara", app="Spotify")
mac.click(640, 420, app="Spotify")

item = mac.ax.at(640, 420, app="Spotify")
mac.ax.perform(item["element_index"], "AXPress")

mac.script('tell application "Spotify" to play')
```

Use ordinary Python for local context and one-off logic. Do not add app-specific
helpers when a short program can resolve the task.

## Choose the lowest useful mode

1. When identity depends on local context (`my`, `friend`, or prior activity),
   inspect that context and correlate stable fields; a loose text hit is not enough.
2. Use `mac.script()` for a known exact, focus-safe app command.
3. Otherwise use `mac.see(app)` and vision.
4. Prefer a known keyboard route; use a verified coordinate for a visible,
   low-risk target.
5. Use targeted `mac.ax` only when semantic identity or state matters. Do not dump
   a full AX tree before trying the direct route.

After a failed verified burst, switch mode or stop. Never repair uncertainty with
repeated keys, clicks, deletion loops, or bulk input.

## Keep the invariants

- Input targets an already-running app PID and never requests activation or raise.
- A background target becoming frontmost raises `FocusChangedError`; never
  manipulate focus to restore it.
- `mac.click()` is raw PID-targeted input. It never guesses an AX action.
- The animated pointer is click-through and never moves the physical cursor.
- `mac.move()` moves only that pointer; it cannot produce native hover.
- Inactive apps may reject raw clicks. After one verified failure, switch mode.
- Never launch a closed app or use a custom URL scheme when focus is forbidden.
- Screenshot coordinates come from the latest `mac.see()` and preserve window
  bounds and Retina scaling.

Secondary primitives are `mac.move`, `drag`, `scroll`, `show_pointer`, and
`hide_pointer`. `mac.ax.query()` returns compact matches and bounds fallback
traversal; lower `max_nodes` for especially large apps.

## Electron and other Chromium-backed apps

`mac.see` reads these fine; input does not reach them. The window is a web page,
so the AX tree collapses to a single `AXScrollArea` exposing no actions, and
`mac.click` produces a hover outline with no state change. That is structural,
not a focus problem — retrying, activating, or falling back to `mac.ax` all fail
the same way. Spend one verified failure, then leave the harness for CDP
(`agent-browser`, `browser-harness`, or raw CDP — see the `cua` router for the
options).

Native panels those apps open are the exception: an Open/Save sheet is AppKit,
so `mac.ax` drives it in the background while CDP cannot see it. Open: `AXOpen`
on the file's `AXTextField`; Save: set `AXValue` on identifier
`saveAsNameTextField`, then `AXPress` on `OKButton`. An `AXError -25205` can
arrive after the panel already acted, so judge by the app's state, not the call.
A folder picker has no file to open: set `AXSelected` on the folder's `AXRow`,
then `AXPress` the `Open` button. Moving the panel elsewhere is the trap. It
runs in `openAndSavePanelService`, so `mac.key` aimed at the app never reaches
it; filling the Go-to sheet's field by AX and `AXConfirm`/`AXOpen` on its path
items report success and do not move it, nor does writing `NSNavLastRootDirectory`
into the app's defaults; and keys posted at the HID level go to
whichever app owns that combo globally (Cmd+Shift+G opened another app's
screen-capture overlay and a macOS screen-recording prompt). Put the folder
where the panel already is (it opens at the last folder used), and do not
screenshot it there: it lists the user's own files. A signed, hardened app's
panel may expose no AX nodes at all.
Some apps refuse a debugging port by policy (Feishu/Lark sets
`RemoteDebuggingAllowed` off); there CDP is not an option at all.

Such apps usually expose no debugging port; check before assuming one
(`lsof -nP -p <pid> -iTCP -sTCP:LISTEN`). Relaunch the app yourself with one:

```bash
open -a <App> --args --remote-debugging-port=9333
curl -s http://127.0.0.1:9333/json      # pick the target whose type == "page"
```

Then drive that port directly (`Runtime.evaluate`, `Input.dispatchMouseEvent`,
`Page.captureScreenshot`). **The port is a live remote-control channel into the
user's app**: relaunch without the flag when done and confirm it stopped
answering — same discipline as unloading any other injected runtime state.

Relaunching restarts an app someone may be using, so it is a decision to surface,
not a step to slip in — say so first when the app was already running, and on a
machine that is not yours, ask before quitting anything.

Three traps once you are inside the page:

- **`element.click()` often does nothing.** React/Radix menus and popovers open on
  real pointer events. Read `getBoundingClientRect()`, then dispatch
  `Input.dispatchMouseEvent` mouseMoved → mousePressed → mouseReleased.
- **Never filter visibility with `offsetParent !== null`.** It is `null` for every
  `position: fixed` element, so headers and toolbars drop out of your query and
  the page reads as empty. Use `checkVisibility()` plus a rect test.
- **The control may live in a cross-origin iframe**, where the parent document
  really does contain none of them. Locate the frame in `Page.getFrameTree`, call
  `Page.createIsolatedWorld` passing `frameId` = that frame's **`.id`** (frame
  objects carry no `.frameId`), and evaluate against the returned
  `executionContextId`.

## Input-dead but screenshot-live apps (WeChat class)

WeChat for Mac (`com.tencent.xinWeChat`) is not Chromium but fails the same way:
`see` captures fine while `click`, double-click, and `scroll` all no-op — observed
even with the window fully visible. Its data lives in a sandboxed container
(`~/Library/Containers/com.tencent.xinWeChat/Data`) that reads
`Operation not permitted` without Full Disk Access, so files are not a fallback.
Two extra quirks:

- The process you want may not own the visible window. WeChat runs two PIDs
  (main + `WeChatAppEx` renderer) with overlapping windows; resolve by
  `CGWindowListCopyWindowInfo` and capture each candidate with
  `screencapture -o -x -l <window_id>`, which works for off-screen/occluded
  windows that `mac.see` cannot reach.
- Its photo viewer ("Photos and Videos") is a separate window id — screenshot it
  directly, but its toolbar arrows need real clicks too.

When input is dead, the working loop is: ask the user to scroll/flip, poll
`screencapture -l <id>` every ~2s and save on checksum change. One verified input
failure, then switch to this — do not retry bursts.

## HID-only apps (ToDesk / Flutter class)

ToDesk (`com.youqu.todesk.mac`) only forwards HID-level input: PID-targeted
`mac.click` moves the remote pointer but never presses, and `mac.key` never
arrives. Custom-rendered UIs (Flutter, e.g. a proxy client's window) fail the
same way from the other side: `mac.ax` exposes only the menu bar, so `ax.at()`
returns `AXMenuBar` for every point, and PID clicks no-op even when frontmost.
One such failure is enough — do not retry. What works, with the user's
consent (it takes over their real keyboard and mouse):

- Bring the viewer frontmost and post Quartz events with
  `CGEventPost(kCGHIDEventTap, …)`. Run them under your automation
  environment's own `sys.executable`; a plain `python3` may lack `Quartz`.
  Map screenshot coordinates to screen with `bounds` and `scale_x`/`scale_y`
  from `mac.see`.
- Modifier combos lose their modifiers (`ctrl+shift+v` lands as a bare `V`).
  Paste through the remote's right-click menu instead; the Mac clipboard syncs
  to the remote. Clear it afterwards if it carried a secret.
- Use the GUI once to get a shell (e.g. install an SSH path), then leave it.

## Browser and permissions

Use a CDP-based tool for DOM, tabs, network, downloads, and uploads. Do not
substitute AX for CDP inside a web page. When a CDP client first attaches to the
user's own Chrome, the browser shows an `Allow remote debugging?` sheet — accept
that exact prompt once through system-wide AX. Never activate Chrome or emit a
mouse event to do it.

Before real work, check permissions without prompting (`doctor --request` asks
the OS to prompt, so run it only with user approval). Accessibility, screen
recording, and event posting are global; Apple Events Automation is per target.
