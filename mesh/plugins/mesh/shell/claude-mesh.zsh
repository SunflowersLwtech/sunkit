# claude-mesh: make plain `claude` join the mesh (cross-account session messaging).
# Adds `--channels plugin:mesh@sunkit` to interactive launches only;
# subcommands, print mode, help/version and explicit --channels pass through.
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
    command claude "$@" --channels plugin:mesh@sunkit
  else
    command claude "$@"
  fi
}
