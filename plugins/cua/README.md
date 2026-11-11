# cua

One entry point for computer / browser / phone automation, packaged as three
Claude Code skills.

- **`cua`** — the router. Routes each GUI request to the right detail skill by
  task shape, and insists on official APIs / CLIs before any GUI work.
- **`macos-harness`** — macOS desktop automation done right: one persistent
  session, PID-targeted input that never steals focus, Accessibility +
  Apple Events, CDP escape hatch for Chromium-backed apps, and the failure
  modes that otherwise cost hours (Electron web views with no AX tree, native
  open/save panels invisible to CDP, input-dead apps, HID-only apps).
- **`phone-use`** — phones and emulators: Android (adb + uiautomator2, scripts
  included), iOS Simulator (AXe/Appium, scripts included), real iOS via
  WebDriverAgent, cloud real devices (BrowserStack / AWS Device Farm), plus
  the etiquette of shared and owner-owned devices.

## Install

```
/plugin marketplace add SunflowersLwtech/sunkit
/plugin install cua@sunkit
```

The `cua` router is the entry point; ask it to open a page, click something,
drive an emulator, or take a screenshot and it will pick the right member.

## What ships and what doesn't

| Piece | Included? | Notes |
|---|---|---|
| Router logic (`skills/cua`) | yes | pure routing, no dependencies |
| `macos-harness` skill | yes (documentation) | documents a six-verb CLI contract (`see`/`key`/`type`/`click`/`ax`/`script`) and its behavioral rules; the CLI wrapper itself is not distributed — assemble it from [Peekaboo](https://github.com/steipete/peekaboo), Quartz `CGEventPost`, `osascript`, `screencapture`, or your own equivalent |
| `phone-use` skill + scripts | yes | working scripts: `droid.py` (Android element control, no root), `ios-sim-paste.sh` (Chinese input into the iOS Simulator), `pinch-probe.html` (zoom calibration), `bs_probe.py` (BrowserStack smoke probe). Needs `adb`, `uv` (for `droid.py`), `brew install axe`, optional `appium` |
| agent-browser | pointer only | [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser) (Apache-2.0): `npm i -g agent-browser && agent-browser install` |
| browser-harness | pointer only | [browser-use/browser-harness](https://github.com/browser-use/browser-harness) (MIT): attaches to the user's own running Chrome |
| agent-desktop | pointer only | [vercel-labs/agent-desktop](https://github.com/vercel-labs/agent-desktop) (Apache-2.0): cross-platform accessibility-tree desktop control |
| cua-driver | pointer only | [trycua/cua](https://github.com/trycua/cua) (MIT): driver-verified input, VM fleets, recording |

## Design notes

- The router's rule of thumb: **API first, GUI last**. If the task lives on an
  external service (mail, verification codes, quota, review status), an
  official API/CLI beats clicking.
- Detail skills are kept small and concrete: every recommended command carries
  its own success criterion, because GUI automation fails silently — tools
  report success while nothing happened.
- Behaviors are documented as invariants ("never restore focus by activating
  another app", "never retry a burst after one verified failure") rather than
  step-by-step recipes, so they survive tool-version drift.
