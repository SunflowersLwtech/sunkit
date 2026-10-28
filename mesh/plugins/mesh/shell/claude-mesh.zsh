# claude-mesh: plain `claude` goes through the magpie gateway (claude-gw) and joins the mesh
# (cross-account session messaging) when this machine is paired.
# `claude-degw` is the same session straight to Anthropic, no gateway.
# Subcommands (mcp, update, …) and help/version run the claude binary as is.
# Sourced from .zshrc / .bashrc; works in both shells.

# Gateway by default, print mode (-p) included. claude-gw adds --channels itself for
# interactive sessions on a paired machine. A machine without the gateway set up
# (no claude-gw on PATH, or no ~/.claude/magpie-settings.json) gets claude-degw instead.
claude() {
  local subcmd_re='^[A-Za-z][A-Za-z0-9|_-]*$'   # unquoted below: bash and zsh both treat it as a regex
  if [[ $# -gt 0 && "$1" =~ $subcmd_re ]]; then
    command claude "$@"; return
  fi
  local a
  for a in "$@"; do
    case "$a" in
      -h|--help|-v|--version) command claude "$@"; return ;;
    esac
  done
  if command -v claude-gw >/dev/null 2>&1 && [[ -f "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/magpie-settings.json" ]]; then
    command claude-gw "$@"
  else
    claude-degw "$@"
  fi
}

# Direct mode: bypass the gateway, keep the mesh channel.
claude-degw() {
  local subcmd_re='^[A-Za-z][A-Za-z0-9|_-]*$'
  if [[ -f "${MESH_HOME:-$HOME/.claude-mesh}/config.json" ]] \
     && ! [[ $# -gt 0 && "$1" =~ $subcmd_re ]]; then
    local a
    for a in "$@"; do
      case "$a" in
        -p|--print|-h|--help|-v|--version|--channels|--channels=*|--dangerously-load-development-channels*)
          command claude "$@"; return ;;
      esac
    done
    # Appended, not prepended: --channels is variadic and would swallow a following prompt.
    command claude "$@" --channels plugin:mesh@sunkit
  else
    command claude "$@"
  fi
}
