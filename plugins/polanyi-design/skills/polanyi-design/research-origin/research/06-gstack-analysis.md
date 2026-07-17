# gstack 仓库分析

> 来源: https://github.com/garrytan/gstack
> 作者: Garry Tan (YC CEO)

---

## 这是什么

gstack 是一个开源的 **AI 编码代理工作流系统**——23+ 个专家级 Skill 把 Claude Code 变成一支虚拟工程团队。作者声称单人日产 10,000-20,000 行生产级代码，60 天内交付 600,000+ LOC（35% 测试）。

**核心命题**：一个有品味的人 + 正确的工具 > 一个 20 人团队。瓶颈不再是工程能力，而是判断力和完整性意愿。

## 仓库结构

```
gstack/
├── ARCHITECTURE.md          # 系统设计文档
├── ETHOS.md                 # 建造者哲学（三原则）
├── CLAUDE.md                # 贡献者指南
├── README.md                # 用户指南
├── package.json             # 构建脚本
│
├── scripts/
│   ├── gen-skill-docs.ts    # 模板编译器（核心，55KB）
│   ├── discover-skills.ts   # Skill 发现器
│   └── resolvers/           # 40+ 占位符解析器
│       ├── preamble.ts      # 通用配置 + 遥测 + 学习注入
│       ├── browse.ts        # 浏览器命令参考
│       ├── testing.ts       # 测试引导
│       ├── design.ts        # 设计方法论
│       ├── review.ts        # 审查仪表盘
│       ├── learnings.ts     # 学习搜索/日志
│       ├── utility.ts       # 分支检测/部署引导
│       └── composition.ts   # Skill 路由
│
├── hosts/                   # 8 个 AI 代理宿主配置
│   ├── claude.ts
│   ├── codex.ts
│   ├── cursor.ts
│   └── ...
│
├── 23+ Skill 目录/
│   ├── office-hours/        # 产品想法重构（6 个逼问）
│   ├── plan-ceo-review/     # CEO 级战略审查
│   ├── plan-eng-review/     # 架构 + 数据流锁定
│   ├── plan-design-review/  # 设计评分 0-10，AI slop 检测
│   ├── autoplan/            # 自动审查流水线
│   ├── review/              # 着陆前代码审查 + 自动修复
│   ├── investigate/         # 根因调试（冻结目录，3 次修复限制）
│   ├── qa/                  # 浏览器测试 + 原子提交修复
│   ├── ship/                # 测试 → 推送 → 开 PR
│   ├── land-and-deploy/     # 合并 → CI → 部署 → 金丝雀验证
│   ├── cso/                 # OWASP Top 10 + STRIDE 安全审查
│   ├── learn/               # 管理项目学习
│   ├── retro/               # 每周回顾
│   ├── document-release/    # 自动更新过时文档
│   ├── codex/               # 多 AI 第二意见（跨模型共识）
│   ├── careful/             # 谨慎模式
│   ├── freeze/              # 冻结编辑范围
│   ├── guard/               # careful + freeze 组合
│   └── ...
│
├── browse/                  # Playwright 浏览器守护进程
│   ├── src/cli.ts           # CLI 入口
│   ├── src/server.ts        # Bun HTTP 服务器
│   ├── src/commands.ts      # 命令注册表（~200 个命令）
│   └── src/snapshot.ts      # 无障碍树快照
│
├── design/                  # 设计图生成（OpenAI Image API）
├── bin/                     # CLI 工具
│   ├── gstack-learnings-log
│   ├── gstack-learnings-search
│   ├── gstack-config
│   └── ...
│
├── extension/               # Chrome 扩展（侧边栏 UI）
└── test/                    # 三层测试
    ├── skill-validation.test.ts    # 第 1 层：静态验证
    ├── skill-e2e-*.test.ts         # 第 2 层：真实 Claude 会话
    └── skill-llm-eval.test.ts      # 第 3 层：LLM 作为评委
```

## 核心架构：五层隐性知识编码

### 第 1 层：专家角色（SKILL.md）

每个 Skill 是一个"专家"——有自己的方法论、约束和质量门槛。用 YAML frontmatter 定义元数据：

```yaml
---
name: investigate
preamble-tier: 2
description: |
  Systematic debugging with root cause investigation...
allowed-tools:
  - Bash
  - Read
  - Edit
  - Grep
hooks:
  PreToolUse:
    - matcher: "Edit"
      hooks:
        - type: command
          command: "bash ${CLAUDE_SKILL_DIR}/../freeze/bin/check-freeze.sh"
voice-triggers:
  - "debug this"
  - "fix this bug"
---
```

**关键设计**：Skill 不是手写的——通过 `.tmpl` 模板 + 元数据自动生成，避免文档漂移。

### 第 2 层：建造者信条（ETHOS.md）

三个原则注入每个 Skill 的行为：

1. **Boil the Lake（煮沸湖水）** — AI 让完整性变得廉价，不要偷工减料
2. **Search Before Building（先搜索再建造）** — 三层搜索：成熟方案 → 新兴方案 → 第一性原理
3. **User Sovereignty（用户主权）** — 模型推荐，用户决定，永远不跳过验证

### 第 3 层：跨 Skill 状态流

```
/office-hours → 设计文档 → /plan-ceo-review → 审查意见
    → /plan-eng-review → 测试计划 → /qa → 缺陷报告
    → /review → 审查结论 → /ship → PR → /land-and-deploy
```

没有手动交接。状态通过文件和 JSONL 在 Skill 之间自动流动。

### 第 4 层：持久化学习（JSONL）

```jsonl
{"key":"n-plus-one","type":"pitfall","insight":"...","confidence":8,"source":"observed","ts":"2026-04-06"}
{"key":"react-hydration","type":"pattern","insight":"...","confidence":9,"source":"inferred","ts":"2026-04-05"}
```

- **去重**：同一 (key, type) 的最新条目获胜
- **衰减**：观察/推断类学习每 30 天信心值 -1
- **跨项目**：可搜索最多 5 个其他项目的学习
- **注入**：每个 Skill 启动时自动加载 top 3 相关学习

### 第 5 层：前言注入（Preamble）

每个 Skill 启动前执行 ~500 行 bash 脚本：

1. 检查更新
2. 统计并发会话数（3+ 时进入 ELI16 模式，重新锚定上下文）
3. 加载项目学习
4. 读取配置状态
5. 检查路由规则（CLAUDE.md 中的 `## Skill routing` 段）

四个 preamble 层级（tier 1-4），按 Skill 需求选择注入量。

## 浏览器守护进程架构

不冷启动 Chromium，而是运行**长驻守护进程**：

```
Claude Code → HTTP (token auth) → Bun.serve() → CDP → Chromium daemon
```

- 首次调用 ~3s，后续 ~100-200ms
- 状态（cookies、tabs、localStorage）跨命令持久化
- **Ref 系统**：`@e1` `@e2` 通过无障碍树定位元素，避免 CSP 冲突

## 三层测试体系

| 层级 | 内容 | 成本 | 速度 |
|------|------|------|------|
| 1 - 静态验证 | 解析 SKILL.md 命令，校验浏览器注册表 | 免费 | <2s |
| 2 - E2E | 生成真实 Claude 会话，运行 Skill，扫描错误 | ~$3.85 | ~20min |
| 3 - LLM 评委 | Sonnet 对文档打分：清晰度/完整性/可操作性 | ~$0.15 | ~30s |

基于 diff 的选择性测试：只运行涉及变更文件的测试。

## 多宿主支持

支持 8 个 AI 代理：Claude Code、Codex CLI、OpenCode、Cursor、Factory Droid、Slate、Kiro、OpenClaw。每个宿主有独立的 HostConfig，解析器系统按宿主适配占位符。

## 对隐性知识研究的启示

gstack 展示了**工业级**的隐性知识编码方案：

| 维度 | gstack 的做法 | 知识类型 |
|------|-------------|---------|
| 工作流序列 | Think → Plan → Build → Review → Test → Ship → Reflect | 过程性知识 |
| 专家角色 | 23+ SKILL.md，每个有独立方法论和约束 | 角色知识 |
| 质量门槛 | hooks (PreToolUse)、freeze、guard | 判断性知识 |
| 经验积累 | JSONL learnings + 信心衰减 + 跨项目搜索 | 经验性知识 |
| 品味标准 | ETHOS.md + design-review 0-10 评分 | 审美知识 |
| 安全边界 | /cso (OWASP + STRIDE)、freeze 目录锁定 | 风险知识 |
| 跨模型共识 | /codex 调用多个 AI 进行交叉验证 | 验证性知识 |

**核心洞察**：隐性知识不是一个单体 prompt，而是：
- 结构化工作流（强制序列）
- 持久化状态（经验随时间积累和衰减）
- 跨代理共识（多模型同意时升级为用户决策）
- 完整性规范（"煮沸湖水"——AI 让完整性变得廉价）
- 用户主权（推荐，不决定）

这是从"个人技能"到"可复用工厂"的范式转换。
