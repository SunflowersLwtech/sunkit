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
plugin_command="$plugin_root/commands/$plugin_name.md"

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

if [[ ! -f "$plugin_command" ]]; then
  echo "Missing Codex project plugin adapter command source: $plugin_command" >&2
  exit 1
fi

if command -v ruby >/dev/null 2>&1; then
  ruby -ryaml -e '
    ARGV.each do |path|
      text = File.read(path)
      unless text.start_with?("---\n") && text.include?("\n---\n")
        warn "Skill is missing YAML frontmatter: #{path}"
        exit 1
      end
      frontmatter = text.sub(/\A---\n/, "").split("\n---\n", 2).first
      YAML.safe_load(frontmatter)
    end
  ' "$skill" "$plugin_skill"
fi

python3 - "$manifest" "$marketplace" "$plugin_name" "$plugin_manifest" "$skill" "$plugin_skill" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
marketplace_path = Path(sys.argv[2])
plugin_name = sys.argv[3]
plugin_manifest_path = Path(sys.argv[4])
skill_paths = [Path(sys.argv[5]), Path(sys.argv[6])]

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

try:
    import yaml
except ImportError:
    yaml = None

def extract_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SystemExit(f"Skill is missing YAML frontmatter: {path}")
    body = text[4:]
    if "\n---\n" not in body:
        raise SystemExit(f"Skill is missing closing YAML frontmatter: {path}")
    return body.split("\n---\n", 1)[0]

def parse_frontmatter(path):
    frontmatter = extract_frontmatter(path)
    if yaml is not None:
        data = yaml.safe_load(frontmatter) or {}
    else:
        data = {}
        for line in frontmatter.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    return data

for path in skill_paths:
    data = parse_frontmatter(path)
    name = str(data.get("name") or "")
    description = str(data.get("description") or "")
    if not name:
        raise SystemExit(f"Skill frontmatter missing name: {path}")
    if len(name) > 64:
        raise SystemExit(f"Skill name exceeds Codex limit 64 ({len(name)}): {path}")
    if len(description) > 1024:
        raise SystemExit(
            f"Skill description exceeds Codex limit 1024 ({len(description)}): {path}"
        )

PY

codex_cli="${CODEX_CLI_PATH:-${CODEX_CLI:-}}"
if [[ -z "$codex_cli" ]]; then
  if [[ -x "/Applications/Codex.app/Contents/Resources/codex" ]]; then
    codex_cli="/Applications/Codex.app/Contents/Resources/codex"
  elif command -v codex >/dev/null 2>&1; then
    codex_cli="$(command -v codex)"
  fi
fi

if [[ -n "$codex_cli" ]]; then
  if ! "$codex_cli" plugin --help | grep -Fq "  list"; then
    echo "Codex CLI at $codex_cli does not support plugin list; set CODEX_CLI_PATH to the Codex.app binary." >&2
    exit 1
  fi

  if ! "$codex_cli" plugin list | grep -Fq "$plugin_name@media-x-local  installed, enabled"; then
    echo "Codex CLI does not report $plugin_name@media-x-local as installed, enabled" >&2
    echo "Run: $codex_cli plugin add $plugin_name@media-x-local" >&2
    exit 1
  fi

  version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$plugin_manifest")"
  cache_skill="${CODEX_HOME:-$HOME/.codex}/plugins/cache/media-x-local/$plugin_name/$version/skills/$plugin_name/SKILL.md"
  if [[ ! -f "$cache_skill" ]]; then
    echo "Codex plugin cache is missing the skill file: $cache_skill" >&2
    echo "Reinstall after syncing the project plugin adapter." >&2
    exit 1
  fi
  cache_command="${CODEX_HOME:-$HOME/.codex}/plugins/cache/media-x-local/$plugin_name/$version/commands/$plugin_name.md"
  if [[ ! -f "$cache_command" ]]; then
    echo "Codex plugin cache is missing the command source file: $cache_command" >&2
    echo "Reinstall after syncing the project plugin adapter." >&2
    exit 1
  fi
fi

echo "Codex project plugin registration verified"
