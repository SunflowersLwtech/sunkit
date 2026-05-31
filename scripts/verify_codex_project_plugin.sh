#!/usr/bin/env bash
set -euo pipefail

root="${1:-$(pwd)}"
plugin_name="github-repo-to-x-threads"
manifest="$root/.codex-plugin/plugin.json"
marketplace="$root/.agents/plugins/marketplace.json"
skill="$root/skills/$plugin_name/SKILL.md"
plugin_root="$root/plugins/$plugin_name"
plugin_manifest="$plugin_root/.codex-plugin/plugin.json"
plugin_skill="$plugin_root/skills/$plugin_name/SKILL.md"

if [[ ! -f "$manifest" ]]; then
  echo "Missing Codex plugin manifest: $manifest" >&2
  exit 1
fi

if [[ ! -f "$marketplace" ]]; then
  echo "Missing project-level Codex marketplace: $marketplace" >&2
  exit 1
fi

if [[ ! -f "$skill" ]]; then
  echo "Missing canonical skill: $skill" >&2
  exit 1
fi

if [[ ! -f "$plugin_manifest" ]]; then
  echo "Missing Codex project plugin adapter manifest: $plugin_manifest" >&2
  exit 1
fi

if [[ ! -f "$plugin_skill" ]]; then
  echo "Missing Codex project plugin adapter skill: $plugin_skill" >&2
  exit 1
fi

python3 - "$manifest" "$marketplace" "$plugin_name" "$plugin_manifest" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
marketplace_path = Path(sys.argv[2])
plugin_name = sys.argv[3]
plugin_manifest_path = Path(sys.argv[4])

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
plugin_manifest = json.loads(plugin_manifest_path.read_text(encoding="utf-8"))

if manifest.get("name") != plugin_name:
    raise SystemExit(f"Codex manifest name mismatch: {manifest.get('name')} != {plugin_name}")
if manifest.get("skills") != "./skills/":
    raise SystemExit(f"Codex manifest skills must be './skills/': {manifest.get('skills')}")
if plugin_manifest.get("name") != plugin_name:
    raise SystemExit(f"Plugin adapter manifest name mismatch: {plugin_manifest.get('name')} != {plugin_name}")
if plugin_manifest.get("skills") != "./skills/":
    raise SystemExit(f"Plugin adapter manifest skills must be './skills/': {plugin_manifest.get('skills')}")

plugins = marketplace.get("plugins")
if not isinstance(plugins, list):
    raise SystemExit("marketplace.plugins must be a list")

matches = [item for item in plugins if item.get("name") == plugin_name]
if len(matches) != 1:
    raise SystemExit(f"Expected exactly one {plugin_name} marketplace entry, found {len(matches)}")

entry = matches[0]
source = entry.get("source") or {}
expected_path = f"./plugins/{plugin_name}"
if source.get("source") != "local" or source.get("path") != expected_path:
    raise SystemExit(f"Marketplace source must be local path {expected_path!r}: {source}")
if (entry.get("policy") or {}).get("installation") != "AVAILABLE":
    raise SystemExit("Marketplace installation policy must be AVAILABLE")

PY

if command -v codex >/dev/null 2>&1; then
  if ! codex plugin list | grep -Fq "$plugin_name@media-x-local  installed, enabled"; then
    echo "Codex CLI does not report $plugin_name@media-x-local as installed, enabled" >&2
    echo "Run: codex plugin add $plugin_name@media-x-local" >&2
    exit 1
  fi

  version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$plugin_manifest")"
  cache_skill="${CODEX_HOME:-$HOME/.codex}/plugins/cache/media-x-local/$plugin_name/$version/skills/$plugin_name/SKILL.md"
  if [[ ! -f "$cache_skill" ]]; then
    echo "Codex plugin cache is missing the skill file: $cache_skill" >&2
    echo "Reinstall after syncing the project plugin adapter." >&2
    exit 1
  fi
fi

echo "Codex project plugin registration verified"
