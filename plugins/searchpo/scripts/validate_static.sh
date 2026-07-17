#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

resolve_node_bin() {
  local candidates=(
    "${SEARCHPO_NODE_BIN:-}"
    "${NODE_BIN:-}"
    "/opt/homebrew/bin/node"
    "/usr/local/bin/node"
    "$(command -v node || true)"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -n "$candidate" && -x "$candidate" ]]; then
      echo "$candidate"
      return
    fi
  done
}

NODE_BIN="$(resolve_node_bin)"

run_npm_or_node() {
  local script="$1"
  if command -v npm >/dev/null 2>&1; then
    npm run "$script"
    return
  fi
  if [[ -z "$NODE_BIN" ]]; then
    echo "npm is unavailable and node was not found for direct script execution: $script" >&2
    exit 1
  fi
  case "$script" in
    lint)
      "$NODE_BIN" node_modules/typescript/bin/tsc --noEmit
      ;;
    agent-plugin:check)
      "$NODE_BIN" tools/check-agent-plugin.js
      ;;
    *)
      echo "No direct node execution registered for script: $script" >&2
      exit 1
      ;;
  esac
}

run_npm_or_node lint
run_npm_or_node agent-plugin:check
jq empty package.json config/searchpo_policy.json data_prep/source_registry.json data_prep/schemas/*.json contracts/schemas/*.json public/searchpo-content.json
python3 -m compileall -q data_prep agent_harness render scripts
python3 -m unittest discover -s tests
bash -n scripts/*.sh
python3 scripts/no_live_guard.py

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck scripts/*.sh
fi
