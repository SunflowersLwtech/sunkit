#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <bundle-root>" >&2
  echo "Example: $0 /Users/sunfl/Documents/media/X" >&2
  exit 2
fi

bundle_root="${1%/}"
skill_name="github-repo-to-x-threads"
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
skill_src="$source_root/skills/$skill_name"

case "$bundle_root" in
  /tmp/*|/private/tmp/*|/var/folders/*)
    echo "Refusing disposable install target: $bundle_root" >&2
    echo "Use the real agent bundle root; temporary targets are not valid verification." >&2
    exit 2
    ;;
esac

canonical_skill_dir="$bundle_root/skills/$skill_name"
shared_skill_dir="$bundle_root/skills"
claude_project_skill_dir="$bundle_root/.claude/skills/$skill_name"
claude_project_command_dir="$bundle_root/.claude/commands"
plugin_command_dir="$bundle_root/commands"
runbook_dir="$bundle_root/runbooks"
codex_project_plugins_dir="$bundle_root/.agents/plugins"
codex_project_marketplace="$codex_project_plugins_dir/marketplace.json"
codex_project_plugin_root="$bundle_root/plugins/$skill_name"

codex_user_skill_dir="${AGENTS_HOME:-$HOME/.agents}/skills/$skill_name"
codex_legacy_skill_dir="${CODEX_HOME:-$HOME/.codex}/skills/$skill_name"
claude_home="${CLAUDE_HOME:-$HOME/.claude}"
claude_user_skill_dir="$claude_home/skills/$skill_name"
claude_user_command_dir="$claude_home/commands"

if [[ ! -f "$skill_src/SKILL.md" ]]; then
  echo "Missing canonical skill: $skill_src/SKILL.md" >&2
  exit 1
fi

copy_skill() {
  local dest="$1"
  if [[ -L "$dest" ]]; then
    rm "$dest"
  fi
  mkdir -p "$dest"
  if [[ "$(cd "$skill_src" && pwd)" == "$(cd "$dest" && pwd)" ]]; then
    return 0
  fi
  COPYFILE_DISABLE=1 rsync -a --delete --delete-excluded \
    --exclude='.env' \
    --exclude='repo-to-x-workspace' \
    --exclude='repo-to-x-output' \
    --exclude='repo-to-x-runs' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='._*' \
    "$skill_src/" "$dest/"
}

copy_file_if_different() {
  local src="$1"
  local dest="$2"
  mkdir -p "$(dirname "$dest")"
  if [[ -L "$dest" ]]; then
    rm "$dest"
  fi
  if [[ -e "$dest" ]] && [[ "$(cd "$(dirname "$src")" && pwd)/$(basename "$src")" == "$(cd "$(dirname "$dest")" && pwd)/$(basename "$dest")" ]]; then
    return 0
  fi
  cp "$src" "$dest"
}

copy_dir_if_different() {
  local src="$1"
  local dest="$2"
  [[ -d "$src" ]] || return 0
  local src_abs
  src_abs="$(cd "$src" && pwd)"
  local dest_abs=""
  if [[ -d "$dest" ]]; then
    dest_abs="$(cd "$dest" && pwd)"
  fi
  if [[ "$src_abs" == "$dest_abs" ]]; then
    return 0
  fi
  mkdir -p "$dest"
  COPYFILE_DISABLE=1 rsync -a --delete \
    --exclude='.env' \
    --exclude='repo-to-x-workspace' \
    --exclude='repo-to-x-output' \
    --exclude='repo-to-x-runs' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='._*' \
    "$src/" "$dest/"
}

mkdir -p \
  "$bundle_root/.codex-plugin" \
  "$bundle_root/.claude-plugin" \
  "$codex_project_plugins_dir" \
  "$codex_project_plugin_root/.codex-plugin" \
  "$codex_project_plugin_root/skills" \
  "$plugin_command_dir" \
  "$claude_project_command_dir" \
  "$shared_skill_dir" \
  "$runbook_dir"

copy_skill "$canonical_skill_dir"
copy_skill "$claude_project_skill_dir"
copy_skill "$codex_user_skill_dir"
copy_skill "$claude_user_skill_dir"

copy_file_if_different "$source_root/skills/RESOLVER.md" "$shared_skill_dir/RESOLVER.md"
copy_file_if_different "$source_root/skills/_AGENT_README.md" "$shared_skill_dir/_AGENT_README.md"
copy_file_if_different "$source_root/skills/manifest.json" "$shared_skill_dir/manifest.json"
copy_file_if_different "$source_root/.codex-plugin/plugin.json" "$bundle_root/.codex-plugin/plugin.json"
copy_file_if_different "$source_root/.codex-plugin/plugin.json" "$codex_project_plugin_root/.codex-plugin/plugin.json"
copy_dir_if_different "$source_root/skills" "$codex_project_plugin_root/skills"
copy_file_if_different "$source_root/.claude-plugin/plugin.json" "$bundle_root/.claude-plugin/plugin.json"
copy_file_if_different "$source_root/commands/$skill_name.md" "$plugin_command_dir/$skill_name.md"
copy_file_if_different "$source_root/commands/$skill_name.md" "$claude_project_command_dir/$skill_name.md"
copy_file_if_different "$source_root/commands/$skill_name.md" "$claude_user_command_dir/$skill_name.md"
copy_file_if_different "$source_root/README.md" "$bundle_root/README.md"
[[ -f "$source_root/AGENTS.md" ]] && copy_file_if_different "$source_root/AGENTS.md" "$bundle_root/AGENTS.md"
[[ -f "$source_root/INSTALL_FOR_AGENTS.md" ]] && copy_file_if_different "$source_root/INSTALL_FOR_AGENTS.md" "$bundle_root/INSTALL_FOR_AGENTS.md"
[[ -f "$source_root/CLAUDE.md" ]] && copy_file_if_different "$source_root/CLAUDE.md" "$bundle_root/CLAUDE.md"
[[ -f "$source_root/llms.txt" ]] && copy_file_if_different "$source_root/llms.txt" "$bundle_root/llms.txt"
[[ -f "$source_root/skillpack.json" ]] && copy_file_if_different "$source_root/skillpack.json" "$bundle_root/skillpack.json"
[[ -f "$source_root/openclaw.plugin.json" ]] && copy_file_if_different "$source_root/openclaw.plugin.json" "$bundle_root/openclaw.plugin.json"
copy_dir_if_different "$source_root/runbooks" "$runbook_dir"

cat >"$codex_project_marketplace" <<'JSON'
{
  "name": "media-x-local",
  "interface": {
    "displayName": "Media X Local"
  },
  "plugins": [
    {
      "name": "github-repo-to-x-threads",
      "source": {
        "source": "local",
        "path": "./plugins/github-repo-to-x-threads"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
JSON

rm -f "$bundle_root/$skill_name.skill"
rm -rf "$bundle_root/.claude/skills/$skill_name/.claude" "$bundle_root/.claude/skills/$skill_name/.claude-plugin"
rm -rf "$bundle_root/.agents/skills/$skill_name"
rmdir "$bundle_root/.agents/skills" "$bundle_root/.agents" 2>/dev/null || true
rm -rf "$codex_legacy_skill_dir"

# Keep user-governed bundle-root artifacts such as:
#   $bundle_root/.env
#   $bundle_root/repo-to-x-workspace/
# Only clean generated junk inside install/adaptor surfaces.
cleanup_roots=(
  "$canonical_skill_dir"
  "$claude_project_skill_dir"
  "$claude_user_skill_dir"
  "$plugin_command_dir"
  "$claude_user_command_dir"
  "$bundle_root/.codex-plugin"
  "$codex_project_plugin_root"
  "$bundle_root/.claude-plugin"
  "$runbook_dir"
)
for cleanup_root in "${cleanup_roots[@]}"; do
  [[ -e "$cleanup_root" ]] || continue
  find "$cleanup_root" -name 'repo-to-x-workspace' -type d -prune -exec rm -rf {} +
  find "$cleanup_root" -name 'repo-to-x-output' -type d -prune -exec rm -rf {} +
  find "$cleanup_root" -name 'repo-to-x-runs' -type d -prune -exec rm -rf {} +
  find "$cleanup_root" -name '__pycache__' -type d -prune -exec rm -rf {} +
done

find "$bundle_root" -name '.DS_Store' -delete
find "$bundle_root" -name '._*' -delete
find "$codex_user_skill_dir" -maxdepth 8 -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$claude_user_skill_dir" -maxdepth 8 -name '__pycache__' -type d -prune -exec rm -rf {} +

if command -v xattr >/dev/null 2>&1; then
  xattr -cr "$bundle_root" "$codex_user_skill_dir" "$claude_user_skill_dir" 2>/dev/null || true
  find "$bundle_root" -name '._*' -delete
  find "$codex_user_skill_dir" -maxdepth 8 -name '._*' -delete
  find "$claude_user_skill_dir" -maxdepth 8 -name '._*' -delete
fi

if command -v dot_clean >/dev/null 2>&1; then
  dot_clean -m "$bundle_root" 2>/dev/null || true
  find "$bundle_root" -name '._*' -delete
fi

echo "Installed canonical plugin skill: $canonical_skill_dir"
echo "Installed skill resolver: $shared_skill_dir/RESOLVER.md"
echo "Installed agent README: $shared_skill_dir/_AGENT_README.md"
echo "Installed skills manifest: $shared_skill_dir/manifest.json"
echo "Installed Codex plugin manifest: $bundle_root/.codex-plugin/plugin.json"
echo "Installed Codex project marketplace: $codex_project_marketplace"
echo "Installed Codex project plugin adapter: $codex_project_plugin_root"
echo "Installed Claude plugin manifest: $bundle_root/.claude-plugin/plugin.json"
echo "Installed skillpack manifest: $bundle_root/skillpack.json"
echo "Installed OpenClaw plugin manifest: $bundle_root/openclaw.plugin.json"
echo "Installed agent protocol: $bundle_root/INSTALL_FOR_AGENTS.md"
echo "Installed plugin command: $plugin_command_dir/$skill_name.md"
echo "Installed Claude project adapter: $claude_project_skill_dir"
echo "Installed Codex user skill: $codex_user_skill_dir"
echo "Installed Claude Code user skill: $claude_user_skill_dir"
echo "Installed Claude Code user command: $claude_user_command_dir/$skill_name.md"
echo "Removed duplicate Codex repo adapter: $bundle_root/.agents/skills/$skill_name"
echo "Removed duplicate Codex legacy user skill: $codex_legacy_skill_dir"
