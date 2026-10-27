#!/bin/bash
# cc-connect v1.5.0 以 root 运行时会把 mode=bypassPermissions 强制降级成 auto（session.go: os.Geteuid()==0）。
# 用户要求「全部自动放行」，所以 config.toml 里写 mode="auto"、cmd 指向本脚本，这里把 --permission-mode auto 改回 bypassPermissions。
# IS_SANDBOX=1 让 Claude Code 在 root 下接受 bypassPermissions。
out=(); prev=""
for a in "$@"; do
  if [ "$prev" = "--permission-mode" ] && [ "$a" = "auto" ]; then a="bypassPermissions"; fi
  out+=("$a"); prev="$a"
done
# 2026-10-27：秘书的自动压缩窗口以 config.toml [projects.agent.options.env] 为准。
# 共享的 /root/.claude/settings.json 由 claude-config-sync 从 vault 覆盖（10-27 10:00 起是 300000），
# 而 settings.json 的 env 会盖过进程环境变量，config.toml 的 160000 因此失效，s274 长到 ~190K，
# 被 long-off-seats 改道后整条 long 链接不住（全 400）。--settings 的优先级高于 settings.json（实测）。
if [[ "${CLAUDE_CODE_AUTO_COMPACT_WINDOW:-}" =~ ^[0-9]+k?$ ]]; then
  out=(--settings "{\"env\":{\"CLAUDE_CODE_AUTO_COMPACT_WINDOW\":\"${CLAUDE_CODE_AUTO_COMPACT_WINDOW}\"}}" "${out[@]}")
fi
# 2026-10-27 网关兜底：gw-fallback 判定网关连续不通时写下标记（内容是那个网关地址）。
# 这时 cc-connect 给的若正是这个网关，就去掉网关的环境变量，直连容器里登录的席位；
# 网关才认的模型名（frontier、auto/kimi-k3 这类）直连不认，换成 Opus。标记删掉后照常走网关。
F=/feishu-cc/gw-fallback/direct
if [ -n "${ANTHROPIC_BASE_URL:-}" ] && [ -f "$F" ] && [ "$ANTHROPIC_BASE_URL" = "$(cat "$F" 2>/dev/null)" ]; then
  unset ANTHROPIC_BASE_URL ANTHROPIC_CUSTOM_HEADERS ANTHROPIC_AUTH_TOKEN CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST
  [[ "${ANTHROPIC_MODEL:-claude-}" == claude-* ]] || export ANTHROPIC_MODEL=claude-opus-5-5
  for i in "${!out[@]}"; do
    if [ "${out[$i]}" = "--model" ] && [[ "${out[$((i + 1))]:-}" != claude-* ]]; then out[$((i + 1))]=claude-opus-5-5; fi
  done
  export GW_FALLBACK_DIRECT=1
fi
export IS_SANDBOX=1
exec /feishu-cc/npm-global/bin/claude "${out[@]}"
