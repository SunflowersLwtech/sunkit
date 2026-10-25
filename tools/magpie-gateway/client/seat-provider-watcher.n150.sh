#!/bin/sh
# seat-provider-watcher（2026-10-25，sunkit tools/magpie-gateway；接手飞书秘书 10:52 的计划）
# cc-connect 默认 provider 按三个 Claude 席位 5h 余量自动切换：
#   全部 ≥95% → provider=magpie（llm-gateway 网关；opus 组在网关内 kiro→zed sonnet 兜底）
#   任一 <80% → provider=anthropic（直连；登录席位由 seat-guard tick 负责切到最空的）
#   80–95% 之间不动（滞回）。只翻 config.toml 的 provider 行，其余配置原样保留；
#   换入/空闲重启/失败回滚全部复用 swap-config-when-idle.sh，且只在已空闲时发起，
#   不长期占 /tmp/feishu-cc-restart.lock，不影响秘书自己的重启。
# crontab（N150 主机）：*/2 * * * * /opt/data/feishu-cc/bin/seat-provider-watcher >/dev/null 2>&1
D=/opt/data/feishu-cc
CFG=$D/config.toml
LOG=$D/provider-watcher.log
PY=/root/.claude/tools/uv/bin/python3

log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

# 1) 席位读数与决策在容器内做（seat-guard status --json；活跃席位读不到时用 state.json 兜底，
#    且兜底必须邮箱一致 + 15 分钟内新鲜——12:14 误切 magpie 就是旧席位的 100% 被贴到
#    刚切上的新席位造成的）
DEC=$(docker exec feishu-cc $PY -c '
import json,subprocess,sys,time
HIGH=95.0;LOW=80.0
try:
    out=subprocess.run([sys.executable,"/feishu-cc/bin/seat-guard","status","--json"],capture_output=True,text=True,timeout=120)
    rows=json.loads(out.stdout).get("seats",[])
except Exception as e:
    print("error:"+str(e));sys.exit(0)
try:
    au=json.load(open("/root/.claude/.seat-guard/state.json")).get("active_usage",{})
    if not au.get("email") or not au.get("at") or time.time()*1000-au["at"]>15*60*1000: au={}
except Exception:
    au={}
for r in rows:
    if r.get("active") and r.get("five_hour") is None:
        u=au.get("usage") or {}
        if au.get("email")==r.get("email") and u.get("five_hour") is not None:
            r["five_hour"]=u["five_hour"]
known=[r.get("five_hour") for r in rows if isinstance(r.get("five_hour"),(int,float))]
n=len(rows)
if n==0: print("error:no seats");sys.exit(0)
if any(u<LOW for u in known): print("anthropic")
elif len(known)==n and all(u>=HIGH for u in known): print("magpie")
else: print("keep")
' 2>>"$LOG")
case "$DEC" in
  magpie|anthropic) ;;
  *) log "decision=$DEC (no action)"; exit 0 ;;
esac

# 2) 当前 provider；已一致就什么都不做
CUR=$(grep -E '^provider *= *"(anthropic|magpie)"' "$CFG" | head -1 | sed -E 's/^provider *= *"([a-z]+)".*/\1/')
if [ -z "$CUR" ]; then log "config.toml 的 provider 行读不到，退出"; exit 1; fi
if [ "$CUR" = "$DEC" ]; then exit 0; fi

# 3) 有换入/重启在等就不动；只在不忙时发起（swap 脚本自己还会再判一次）
if [ -d /tmp/feishu-cc-restart.lock ]; then log "want $DEC but restart lock held; skip"; exit 0; fi
recent=$(docker logs --since 90s feishu-cc 2>&1 | grep -v '\[Debug\]' | grep -c -E 'message received|processing message|turn complete|timer:')
[ "$recent" = 0 ] || { log "want $DEC but busy (recent=$recent); skip"; exit 0; }

# 4) 基于当前 config 只翻 provider 行，TOML 校验后交给 swap-config-when-idle.sh
NEW=$D/config.toml.next-watcher
SHA=$(sha256sum "$CFG" | cut -d' ' -f1)
sed -E "s/^provider *= \"(anthropic|magpie)\".*/provider = \"$DEC\"  # seat-provider-watcher $(date '+%F %R') 按席位余量自动切换/" "$CFG" > "$NEW" || { log "sed failed"; exit 1; }
docker exec feishu-cc $PY -c "import tomllib;tomllib.load(open('/feishu-cc/config.toml.next-watcher','rb'))" 2>>"$LOG" \
  || { log "新配置 TOML 校验失败，放弃"; rm -f "$NEW"; exit 1; }
rm -f "$D/config.toml.bak-pre-watcher-$DEC" "$D/config.toml.bak-pre-watcher-$CUR"
log "seats flip: $CUR -> $DEC (sha $SHA)；空闲，交给 swap-config-when-idle.sh"
/opt/data/feishu-cc/bin/swap-config-when-idle.sh "$NEW" "watcher-$DEC" "$SHA" "provider switched\" provider=$DEC" >> "$LOG" 2>&1
log "swap to $DEC exit=$?"
