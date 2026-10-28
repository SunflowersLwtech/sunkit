#!/bin/sh
# gw-fallback 的宿主机入口（2026-10-27，sunkit tools/magpie-gateway）：逻辑全在容器里的 gw-fallback.n150.py，
# 这里只做三件容器里做不了的事：单实例锁、把 feishu-cc 最近的日志喂给它判空闲、把它的 NOTIFY 行交给 ntfy/Discord。
# N150 crontab：* * * * * /opt/data/feishu-cc/bin/gw-fallback >/dev/null 2>&1
# 停用：注释掉这一行，再 rm /opt/data/feishu-cc/gw-fallback/direct（有标记时秘书新起的进程会直连）。
D=/opt/data/feishu-cc
PY=/root/.claude/tools/uv/bin/python3
exec 9>/tmp/gw-fallback.lock
flock -n 9 || exit 0
mkdir -p $D/gw-fallback
# --since 在这个容器上坏过（10-25，daemon 侧返回空），所以用 --tail
docker logs --tail 800 feishu-cc 2>&1 | grep -v '\[Debug\]' \
  | docker exec -i feishu-cc $PY /feishu-cc/bin/gw-fallback.py 2>>$D/gw-fallback/log \
  | while IFS="$(printf '\t')" read -r tag title body prio; do
      [ "$tag" = NOTIFY ] && /opt/data/sre/notify.sh "$title" "$body" "$prio"
    done
L=$D/gw-fallback/log
[ "$(wc -c < $L 2>/dev/null || echo 0)" -gt 1000000 ] && tail -n 3000 $L > $L.tmp && mv $L.tmp $L
exit 0
