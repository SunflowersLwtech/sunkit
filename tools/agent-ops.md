# Agent 生态 durable 资产地图

> 收敛原则：**不搬已同步的，只收散件、重复工作流和新场景**。
> `~/.agents/tools/` 本身就是跨六端 vault 同步的工具枢纽——里面的脚本
> 留在原地当唯一事实源，不要再拷贝进 sunkit 形成第二份。

## 唯一事实源归属

| 资产 | 真源位置 | 状态 |
|---|---|---|
| mesh `create_worker` 工具 | `sunkit: mesh/packages/peer-agent/src/spawn-worker.ts`（bundle 进 `plugins/mesh/server/`） | ✅ 已固化 |
| BossAI hotloop 启停 + PR 门禁 runbook + worker prompt | `sunkit: tools/bossai-ops/` | ✅ 已固化 |
| 各 agent 日常工具脚本（vault-env/vk/cc-switch/ob/cost-watch/clash-*/gauth-export…） | `~/.agents/tools/`（六端同步枢纽） | ✅ 保持原位，勿搬 |
| 凭据 | Vaultwarden（`vk`）→ 旧 hub（只读） | ✅ 已有制度 |
| BossAI 运维文档 | `BossAI/docs/operations/` + `BossAI-后续维护文档/private/` | ✅ 已有制度 |

## 待收敛/收集

| 项 | 状态 |
|---|---|
| 飞书助理（feishu-assistant）高频工作流清单 | 已发 mesh 征集，回复到达后评审入 sunkit |
| p0620 工作区散件（`_transfer/` 归档、`utility/`、`agent-browser-e2e-kit/`、`bossai-cua/` 等） | 待逐项判定：该进 sunkit `tools/` 的收，纯归档不动 |
| devdesk worker 产出（shell-network 沙箱调研） | 报告落 `BossAI/tasks/` 后回填链接 |

## 新散件入 sunkit 的门槛

1. 是**重复出现的工作流/命令序列**，不是一次性操作。
2. 不是 `~/.agents/tools` 已覆盖的能力。
3. 落地形态：脚本放 `tools/<name>/`，说明写 README；纯知识写进对应 runbook。
