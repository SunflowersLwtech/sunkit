#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

npm run lint
npm run agent-plugin:check
jq empty package.json config/searchpo_policy.json data_prep/source_registry.json data_prep/schemas/*.json contracts/schemas/*.json public/searchpo-content.json
python3 -m compileall -q data_prep agent_harness render scripts
bash -n scripts/*.sh
python3 scripts/no_live_guard.py

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck scripts/*.sh
fi
