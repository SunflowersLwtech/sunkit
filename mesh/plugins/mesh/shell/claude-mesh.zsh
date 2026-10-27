# claude-mesh: make plain `claude` join the mesh (cross-account session messaging) AND use the gateway.
# Adds `--channels plugin:mesh@sunkit` and routes through magpie gateway by default.
# Use `claude-degw` for direct Anthropic connection (no gateway).
# Subcommands, print mode, help/version and explicit --channels pass through.

# Gateway mode: wrap claude-gw for mesh + gateway
claude() {
  local subcmd_re='^[A-Za-z][A-Za-z0-9|_-]*$'   # unquoted below: bash and zsh both treat it as a regex
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
    # Use gateway by default: claude-gw adds magpie-settings.json and mesh channel
    command claude-gw "$@"
  else
    command claude "$@"
  fi
}

# Direct mode: bypass gateway, keep mesh channel only
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
    command claude "$@" --channels plugin:mesh@sunkit
  else
    command claude "$@"
  fi
}
