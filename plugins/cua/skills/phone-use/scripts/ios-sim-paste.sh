#!/bin/bash
# ios-sim-paste.sh <sim-udid> <text>
# Put any Unicode text (Chinese included) into the focused field of an iOS Simulator.
# `axe type` only sends US-keyboard characters, so this goes through the pasteboard:
#   devicectl pasteboard copy -> Cmd+V via AXe HID -> tap "Allow Paste" if iOS asks.
# Exit: 0 text found in a field afterwards | 1 HID/tap step failed | 2 pasteboard not set
#       3 pasted but no field reads back the text
#
# Why devicectl and not `xcrun simctl pbcopy`: on Xcode 27 pbcopy exits 0 and leaves
# the simulator pasteboard empty (`simctl pbinfo` -> "Pasteboard is empty").
# Note: if describe-ui hits a transport error, AXe 1.8 restarts testmanagerd, which
# ends any other XCUITest/WDA/Maestro session on the same simulator (AXe #76).
set -u
U="$1"; T="$2"
printf '%s' "$T" | xcrun devicectl device pasteboard copy -d "$U" >/dev/null 2>&1 || exit 2
got="$(xcrun devicectl device pasteboard paste -d "$U" 2>/dev/null)"
[ "$got" = "$T" ] || { echo "pasteboard reads back '$got', expected '$T'" >&2; exit 2; }
axe batch --udid "$U" --step "key-combo --modifiers 227 --key 25" --step "sleep 1" >/dev/null || exit 1
ui="$(axe describe-ui --udid "$U" 2>/dev/null)"
if printf '%s' "$ui" | jq -e '[.. | objects | select(.AXLabel=="Allow Paste")] | length > 0' >/dev/null; then
  axe tap --label "Allow Paste" --post-delay 0.5 --udid "$U" >/dev/null || exit 1
  sleep 1
  ui="$(axe describe-ui --udid "$U" 2>/dev/null)"
fi
printf '%s' "$ui" | T="$T" jq -e '[.. | objects | select((.AXValue // "" | tostring) | contains(env.T))] | length > 0' >/dev/null \
  || { echo "no field reads back '$T'" >&2; exit 3; }
echo "pasted: $T"
