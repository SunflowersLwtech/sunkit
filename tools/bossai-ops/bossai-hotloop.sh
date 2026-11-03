#!/usr/bin/env bash
# bossai-hotloop — start/stop/status a BossAI dev instance on a dedicated
# worktree for the fix→use→throw-back loop.
#
#   bossai-hotloop.sh start  [worktree-path] [branch]
#   bossai-hotloop.sh stop   [worktree-path]
#   bossai-hotloop.sh status [worktree-path]
#
# Conventions proven on sunfl's M4 (2026-11-03):
#   - worktree lives at ../.wt/<name> next to the main checkout
#   - server :3001 (tsx --watch → auto-restart), web :5173 (vite → HMR)
#   - reuse the main checkout's apps/server/.env (cloud url + inference keys)
#   - llama.cpp first-run Gatekeeper check can exceed the prepare timeout once;
#     re-run start, payloads are cached afterwards.
#   - node engines warning (wants 24.20.0) is non-blocking.
set -euo pipefail

WT="${2:-/Users/sunfl/Developer/work/p0620/.wt/hotloop-main}"
REPO="/Users/sunfl/Developer/work/p0620/BossAI"
LOGDIR="$WT/.dev-logs"

case "${1:-status}" in
  start)
    BRANCH="${3:-fix/hotloop-main-$(date +%Y%m%d)}"
    if [ ! -d "$WT" ]; then
      git -C "$REPO" fetch origin --prune
      git -C "$REPO" worktree add "$WT" -b "$BRANCH" origin/main
      cp "$REPO/apps/server/.env" "$WT/apps/server/.env"
      (cd "$WT" && pnpm install --frozen-lockfile | tail -3)
    fi
    mkdir -p "$LOGDIR"
    cd "$WT"
    nohup pnpm dev > "$LOGDIR/dev-$(date +%Y%m%d-%H%M%S).log" 2>&1 &
    echo "started: $WT (log: $LOGDIR)"
    for i in $(seq 1 60); do
      curl -sf --noproxy '*' http://127.0.0.1:3001/health >/dev/null 2>&1 && break
      sleep 3
    done
    curl -s --noproxy '*' http://127.0.0.1:3001/health | head -c 120; echo
    echo "web: http://127.0.0.1:5173/"
    ;;
  stop)
    for port in 3001 5173; do
      pids=$(lsof -tnP -iTCP:$port -sTCP:LISTEN || true)
      [ -n "$pids" ] && kill $pids && echo "port $port: killed $pids"
    done
    sleep 1
    lsof -nP -iTCP:3001,5173 -sTCP:LISTEN | wc -l | tr -d ' ' | xargs echo "listeners left:"
    ;;
  status)
    lsof -nP -iTCP:3001,5173 -sTCP:LISTEN || true
    curl -s --noproxy '*' --max-time 5 http://127.0.0.1:3001/health | head -c 120; echo
    tail -5 "$(ls -t "$LOGDIR"/*.log 2>/dev/null | head -1)" 2>/dev/null || true
    ;;
esac
