#!/bin/sh
# Offline test of claude-mesh.zsh in bash and zsh: stub `claude` and `claude-gw` print where a call landed.
#   sh mesh/plugins/mesh/shell/claude-mesh.test.sh
here=$(cd "$(dirname "$0")" && pwd)
t=$(mktemp -d)
trap 'rm -rf -- "$t"' EXIT
mkdir -p "$t/gw" "$t/nogw"
printf '#!/bin/sh\necho "claude $*"\n' > "$t/gw/claude"
printf '#!/bin/sh\necho "claude-gw $*"\n' > "$t/gw/claude-gw"
cp "$t/gw/claude" "$t/nogw/claude"
chmod +x "$t/gw/claude" "$t/gw/claude-gw" "$t/nogw/claude"
fail=0
n=0
# check <shell> <paired:yes|no> <gateway key file:yes|no> <claude-gw on PATH:yes|no> <command> <expected output>
check() {
  n=$((n + 1))
  home="$t/home$n"
  mkdir -p "$home/.claude" "$home/.claude-mesh"
  [ "$2" = yes ] && : > "$home/.claude-mesh/config.json"
  [ "$3" = yes ] && : > "$home/.claude/magpie-settings.json"
  bin="$t/gw"
  [ "$4" = yes ] || bin="$t/nogw"
  got=$(env -i HOME="$home" PATH="$bin:/usr/bin:/bin" "$1" -c ". '$here/claude-mesh.zsh'; $5" 2>&1)
  if [ "$got" = "$6" ]; then
    echo "ok   $1 paired=$2 key=$3 gw=$4: $5"
  else
    echo "FAIL $1 paired=$2 key=$3 gw=$4: $5 -> '$got', want '$6'"
    fail=1
  fi
}
for sh in bash zsh; do
  command -v $sh >/dev/null || { echo "skip $sh (not installed)"; continue; }
  check $sh yes yes yes "claude" "claude-gw "
  check $sh yes yes yes "claude --resume abc" "claude-gw --resume abc"
  check $sh yes yes yes "claude -p hi" "claude-gw -p hi"
  check $sh yes yes yes "claude mcp list" "claude mcp list"
  check $sh yes yes yes "claude --version" "claude --version"
  check $sh yes yes yes "claude-degw" "claude --channels plugin:mesh@sunkit"
  check $sh yes yes yes "claude-degw -p hi" "claude -p hi"
  # not paired with the mesh: still the gateway; claude-degw without the channel
  check $sh no yes yes "claude" "claude-gw "
  check $sh no yes yes "claude-degw" "claude "
  # no gateway on this machine: direct
  check $sh yes no yes "claude -p hi" "claude -p hi"
  check $sh yes yes no "claude" "claude --channels plugin:mesh@sunkit"
  check $sh no no no "claude" "claude "
done
exit $fail
