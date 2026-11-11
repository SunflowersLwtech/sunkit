#!/bin/bash
# closeout-scan.sh — mechanical half of a session closeout.
#
# Reports, for every git repo under the scan roots: branch, dirty count,
# ahead/behind origin, untracked paths — plus a plaintext-secret residue
# pass over scratch dirs. Judgement about findings stays in SKILL.md.
#
# Usage: closeout-scan.sh [--no-fetch] [--scratchpad DIR] [root ...]
#   root  repo roots to scan. Default: $CLOSEOUT_SCAN_ROOTS (space-separated),
#         else the current working directory.
#   --scratchpad DIR  extra dir to sweep for credential-shaped residue
#                     (default: $CLOSEOUT_SCRATCHPAD, else none).
#   Notes-vault health check: set CLOSEOUT_NOTES_DOCTOR to a command;
#                     it runs last and its failure fails the scan.
set -u
FETCH=1 SCRATCH="${CLOSEOUT_SCRATCHPAD:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --no-fetch) FETCH=0; shift;;
    --scratchpad) SCRATCH="${2:-}"; shift 2;;
    *) break;;
  esac
done
ROOTS=()
for r in "$@"; do ROOTS+=("$r"); done
if [ ${#ROOTS[@]} -eq 0 ] && [ -n "${CLOSEOUT_SCAN_ROOTS:-}" ]; then
  # shellcheck disable=SC2086
  set -- $CLOSEOUT_SCAN_ROOTS; for r in "$@"; do ROOTS+=("$r"); done
fi
[ ${#ROOTS[@]} -eq 0 ] && ROOTS+=("$PWD")

echo "== git repos (branch | dirty | ahead/behind)"
SEEN=""
for root in "${ROOTS[@]}"; do
  [ -d "$root" ] || { echo "skip (not a dir): $root"; continue; }
  while IFS= read -r g; do
    d=$(dirname "${g%/}")
    real=$(cd "$d" && pwd -P)
    case " $SEEN " in *" $real "*) continue;; esac
    SEEN="$SEEN $real"
    br=$(git -C "$real" branch --show-current 2>/dev/null)
    [ $FETCH = 1 ] && git -C "$real" fetch -q --no-tags 2>/dev/null
    dirty=$(git -C "$real" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    ab=$(git -C "$real" rev-list --left-right --count "@{upstream}...HEAD" 2>/dev/null \
         | awk '{print "+"$2"/-"$1}') || ab="+?/-?"
    printf '%-48s %-14s dirty:%-4s %s\n' "$(basename "$real")" "${br:-DETACHED}" "$dirty" "${ab:-no-upstream}"
  done < <(find "$root" -maxdepth 3 -name .git \( -type d -o -type f \) 2>/dev/null)
done

echo
echo "== plaintext residue (scratch dirs)"
PAT='ghp_[A-Za-z0-9]{20}|github_pat_|sk-[A-Za-z0-9_-]{20}|AKIA[0-9A-Z]{16}|BEGIN( RSA)? PRIVATE KEY|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.|(refresh_token|access_token|id_token)"?[[:space:]]*[:=]'
if [ -n "$SCRATCH" ] && [ -d "$SCRATCH" ]; then
  hits=$(grep -rE -l "$PAT" "$SCRATCH" 2>/dev/null | head -20)
  if [ -n "$hits" ]; then
    echo "DELETE OR JUSTIFY:"
    echo "$hits" | sed 's/^/  /'
  else
    echo "clean (text files; binaries and >64k bulk exports are UNJUDGED by design)"
  fi
else
  echo "skipped (pass --scratchpad DIR or set CLOSEOUT_SCRATCHPAD)"
fi

echo
if [ -n "${CLOSEOUT_NOTES_DOCTOR:-}" ]; then
  sh -c "$CLOSEOUT_NOTES_DOCTOR" || { echo "notes doctor FAILED"; exit 1; }
else
  echo "notes doctor: not configured (set CLOSEOUT_NOTES_DOCTOR)"
fi
echo "scan done"
