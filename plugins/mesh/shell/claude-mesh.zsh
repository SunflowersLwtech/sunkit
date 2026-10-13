# claude-mesh: make plain `claude` join the mesh (cross-account session messaging).
# Adds `--channels plugin:mesh@claude-mesh` to interactive launches only;
# subcommands, print mode, help/version and explicit --channels pass through.
claude() {
  if [[ -f "${MESH_HOME:-$HOME/.claude-mesh}/config.json" ]] \
     && ! [[ $# -gt 0 && "$1" =~ '^[A-Za-z][A-Za-z0-9|_-]*$' ]]; then
    local a
    for a in "$@"; do
      case "$a" in
        -p|--print|-h|--help|-v|--version|--channels|--channels=*|--dangerously-load-development-channels*)
          command claude "$@"; return ;;
      esac
    done
    command claude --channels plugin:mesh@claude-mesh "$@"
  else
    command claude "$@"
  fi
}
