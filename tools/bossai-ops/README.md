# bossai-ops

BossAI 高频开发/验收工作流的可复用沉淀（2026-11-03 从 p0620 会话收敛）。

## 1. hotloop 开发循环 — `bossai-hotloop.sh`

「修完立马能用」的标准姿势：基于 `origin/main` 的专用 worktree + `pnpm dev`
（server `tsx --watch` 自动重启、web Vite HMR 即存即生效），用户直接用
`:5173`，问题扔回来即改即验。

```bash
./bossai-hotloop.sh start                 # worktree+装依赖+后台起服务+health 等待
./bossai-hotloop.sh status                # 端口/health/最新日志
./bossai-hotloop.sh stop                  # 按端口精确停，不滥杀 node
```

要点（都是踩过的坑）：

- 后台 `nohup` 的 `cd` 会进子 shell，后续命令必须各自 `cd` 或用绝对路径。
- llama.cpp 首次 Gatekeeper 校验可能超过 prepare 超时，重跑一次即可。
- 8GB 内存机器上 dev server + 长跑 run + 全量 tsc/build 叠加必 swap；
  重验证放 gate worktree 或远端机器错峰。

## 2. PR 门禁套路（BossAI 仓库）

```bash
# 干净 gate worktree 跑门禁（不要在被 live-edit 的 dev worktree 里跑）
git worktree add /tmp/bossai-gate <pr-branch>
cd /tmp/bossai-gate && pnpm install --frozen-lockfile
NODE_OPTIONS='--max-old-space-size=8192' pnpm preflight:pr
# 中文描述门禁（gh pr create 前必过）
PR_TITLE='...' PR_BODY='...' node scripts/pr-chinese-description-gate.mjs
```

- `tsc -p tsconfig.test.json` 在 8GB 机器上默认堆必 OOM（exit 2 无可解析行，
  脚本拒报计数）——加 `NODE_OPTIONS` 重跑，属环境基线失败，PR 评论留证据。
- stacked PR：P0 分支先提，P1 分支 base 指 P0；P0 合并后 GitHub 自动改 base。
- 条件门禁（skill-admission/vendored-host/knowledge…）按路径触发，
  纯 `apps/web/**` 改动不命中。

## 3. 远端 herdr worker spawn

已被 `mesh` 的 `create_worker` 工具固化（`mesh/packages/peer-agent/src/spawn-worker.ts`），
MCP 层直接调用；手工等价命令序列：

```bash
ssh <machine> 'herdr workspace create --label <name> --cwd <path>'   # → pane_id
ssh <machine> 'herdr agent start <name> --kind devin --pane <pane_id> -- [agent-args]'
ssh <machine> 'herdr agent prompt <name> "<prompt>"'
ssh <machine> 'herdr agent read|wait|prompt <name> ...'              # 观察/追问
```

- `devin` 非交互跑法：`devin -p "<prompt>" --respect-workspace-trust false \
  --permission-mode smart`（`smart`=快模型判定安全动作自动放行；
  `accept-edits` 只放文件写；`dangerous` 全放，慎用）。
- `devin PATH -- prompt` 不接受 PATH+PROMPT 组合，进目录 `devin -- prompt`。

## 4. 已固化的任务 prompt 模板

`worker-prompt-shellnet.md`：研究 Claude Code bash 网络沙箱 → 设计 BossAI
作用域内放网的调研 prompt，可直接喂给 create_worker / `devin -p`。
