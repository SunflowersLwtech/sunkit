# polanyi-skill 仓库分析

> 来源: https://github.com/enzyme2013/polanyi-skill
> 作者: enzyme2013 | 生成工具: [女娲.skill](https://github.com/alchaincyf/nuwa-skill) (alchaincyf)

---

## 这是什么

一个 Claude Code Skill，将 Michael Polanyi 的思维框架"蒸馏"成可运行的角色扮演系统。安装后可以在 Claude Code 中以 Polanyi 的身份回应问题。

**不是代码项目**——纯 Markdown（8个文件，2556行），没有任何代码逻辑。

## 仓库结构

```
polanyi-skill/
├── README.md            # 项目说明 + 效果示例
├── SKILL.md             # 核心：可安装的 Skill 定义文件（276行）
├── LICENSE              # MIT
└── references/research/ # 6 个调研文件（共 2014 行）
    ├── 01-writings.md       # 著作与系统思考（356行）
    ├── 02-conversations.md  # 对话与即兴思考（336行）
    ├── 03-expression-dna.md # 表达风格 DNA（403行）
    ├── 04-external-views.md # 他者视角与批评（291行）
    ├── 05-decisions.md      # 重大决策分析（318行）
    └── 06-timeline.md       # 完整人生时间线（310行）
```

## SKILL.md 核心内容

### 蒸馏了什么

| 维度 | 内容 |
|------|------|
| **6 个心智模型** | 隐性知识、辅助-焦点意识、内居、信托框架、后批判哲学、科学共和国 |
| **8 条决策启发式** | 从具体例子出发、拒绝中央计划、理论实践统一、跨学科探索、承认知识危险性、寻找从-到结构、尊重传统不盲从、区分General/Specific Authority |
| **表达 DNA** | 句式结构、人称、例证方式、术语、对比、确定性、悖论、修辞、论证节奏 |
| **内在张力** | 个人vs客观、传统vs创新、自由vs权威、精英主义指控 |
| **价值观** | 追求：自由>真理>整体性>传统>个人参与 / 拒绝：实证主义、中央计划、绝对怀疑主义 |
| **智识谱系** | 影响源（Gestalt、Adam Smith、Hayek）→ 影响对象（Kuhn、Dreyfus、知识管理） |

### 角色扮演规则

- 以第一人称 Polanyi 身份直接回应
- 首次免责声明，之后不重复
- 不跳出角色做meta分析
- 用户说"退出"恢复正常模式

## 调研质量评估

### 优势
1. **6 个维度全面覆盖** — 著作、对话、表达风格、外部评价、决策、时间线，结构完整
2. **学术引用质量高** — 引用 PhilPapers、ResearchGate、Springer 等学术来源，不依赖知乎/百度百科
3. **保留了内在张力** — 没有脸谱化，诚实呈现 Polanyi 的矛盾和局限
4. **表达 DNA 细致** — 从句式、论证节奏到修辞手法都有具体规则
5. **外部视角有深度** — Polanyi vs Kuhn/Popper/Wittgenstein 的争论都有覆盖

### 不足 / 可改进
1. **没有覆盖 AI 时代应用** — SKILL.md 的诚实边界说"信息截止于1976年"，但这恰恰是最有价值的延伸方向。Polanyi 的框架对当代 AI 辩论的适用性（Polanyi's Paradox、LLM vs 默会知识）完全缺失
2. **没有知识管理维度** — Nonaka/SECI 模型对 Polanyi 的（误）用、Collins 的批评都没有涉及
3. **缺少中文学术脉络** — 郁振华等中国 Polanyi 学者的工作、王阳明"知行合一"的关联未提及
4. **调研深度 vs 广度失衡** — 6 个调研文件主要基于 Polanyi 本人著作和少量二手来源（Nye, Prosch, Jacobs），缺少更广的知识网络
5. **效果示例有局限** — 示例集中在编程/工程场景，缺少医疗、教育、艺术等多元应用场景
6. **安装方式不明** — `npx skills add enzyme2013/polanyi-skill` 是否真的可用？依赖 alchaincyf 的 skills CLI 工具，非标准 Claude Code 功能

## 与我们的研究对比

| 维度 | polanyi-skill | 我们的研究 |
|------|---------------|-----------|
| Polanyi 本人著作 | 7本核心 + 少量论文 | 9本 + 10篇关键论文 |
| 学术二手来源 | ~6位学者 | 30+ 位学者/思想家 |
| AI 时代辩论 | ❌ 缺失 | ✅ 完整（Autor、Brynjolfsson、LeCun、Dreyfus、创业公司） |
| 知识管理脉络 | ❌ 缺失 | ✅ 完整（Nonaka/Collins/Sveiby/Wenger） |
| 哲学谱系 | 简要（Gestalt, Hayek） | 深入（Heidegger, Merleau-Ponty, Ryle, Wittgenstein, Dreyfus） |
| 中文资源 | ❌ 缺失 | ✅ 中文译本 + 学者 + 知乎/CSDN |
| 当代论文 (2024-2026) | ❌ 缺失 | ✅ 30+ 篇含URL |
| 可执行性 | ✅ 可安装为 Skill | ❌ 是资源库，不是 Skill |
| 角色扮演设计 | ✅ 完整的表达DNA/规则 | ❌ 未做 |

## 结论

polanyi-skill 是目前**唯一公开的** Polanyi 思想蒸馏尝试，做得不错但有明显盲区：

1. **它是一个"哲学家模拟器"，不是"认知工具"** — 它模拟 Polanyi 说话，但没有把 Polanyi 的洞见转化为可操作的分析框架
2. **缺少 AI 时代最有价值的部分** — 恰恰是 Polanyi 思想在当代最火的方向（Polanyi's Paradox、AI 与默会知识的交锋），这个 Skill 完全没覆盖
3. **调研扎实但封闭** — 聚焦于 Polanyi 本人，没有连接到更大的知识网络

### 机会

我们有三个方向可以超越它：

**方向A: 增强版 Skill** — 在现有基础上补充 AI 时代模块、知识管理批判、中文语境，做一个"Polanyi 2.0 Skill"

**方向B: 认知分析工具** — 不做角色扮演，而是把 Polanyi 的框架做成分析工具（输入：一个场景/问题 → 输出：隐性/显性知识拆解、从-到结构分析、知识传递策略建议）

**方向C: 默会知识蒸馏平台** — 最具商业价值。用 Polanyi 的理论框架指导"专家知识蒸馏"——帮企业识别、捕获和传递默会知识。结合 VR/AR + AI辅助 + 人类导师的混合方案。Interloom 融了 $16.5M 做类似的事，但他们没有 Polanyi 的理论支撑。
