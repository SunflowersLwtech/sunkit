# API Docs Grounding — Strategy(行业横向对照 + search-agent 差异化定位)

**版本**:1.0(2026-05-06)
**对应文档**:[`ground-api-pipeline.md`](./ground-api-pipeline.md)(执行细节)
**对应 §**:`domain-knowledge.md` §5.1 #25(实证基础)、§1.3(ground-api 用例)、§1.8(thin harness 共同体)
**实证工件**:`reference/batch/{firecrawl-openalex,wave2-vendor-probe,five-path-openalex-auth}/`(.gitignore 排除,本地保留)

---

## 1. 问题定义

**用户场景**:LLM coding agent 收到"vendor X 的 docs 找 Y"(典型如 "Anthropic prompt caching 怎么用"、"OpenAlex auth 配额"、"Stripe webhook signature 校验"),需要把 vendor 官方文档**精确**塞进 LLM context,**不能幻觉**(§2.10.1 anti-hallucination)。

这个问题在 **2025-2026 期间已发生标准化**:从"每个工具自己抓"演化到"vendor 主动 ship LLM 友好的索引/全文文件",同时**形成两个不同的 consumer 生态**(IDE 内置 vs MCP 服务 vs skill imperative)。

## 2. 行业现状(2026-Q2 实证)

### 2.1 标准化时间线

| 日期 | 事件 |
|------|------|
| **2024-09** | Jeremy Howard(Answer.AI) 提出 [llms.txt 标准](https://llmstxt.org) — robots.txt 风格的 LLM 索引 |
| **2024-11** | Mintlify + Anthropic 合作开发 **llms-full.txt**(单文件全文版本)。Mintlify 全 host 客户一夜之间 ship — Anthropic / Cursor / Windsurf / Bolt.new 同步上线 |
| **2025 全年** | Cursor / Continue / Aider 等 dev IDE 工具陆续读 llms.txt;Context7(Upstash)上线 MCP 服务化路线 |
| **2026-Q1** | SE Ranking 测 30 万通用域 llms.txt 命中率 **10.13%**;Google 代表(Mueller)公开声明 AI crawlers 不从 llms.txt 抽。**dev tool 主流玩家在用,但 AI 大厂未承诺生产读** |
| **2026-05** | **本项目实证**:LLM/dev 16 vendor panel `/llms.txt` **87%** + `/llms-full.txt` **56%** —— 远高于通用域 10%,**因为 dev docs SaaS 是这个标准的核心产消生态** |

### 2.2 producer 端三种实现路径

| Producer | 出处 | 特征 |
|----------|------|------|
| **Mintlify hosting auto-gen** | docs SaaS 默认 | `/llms.txt` + `/llms-full.txt` 三件套自动生成,客户:Anthropic / Cohere / Mistral / Together / Fireworks / Firecrawl 自家 / OpenAlex 等。**Wave 2 实证 Mintlify host 18% 但 llms.txt 命中率 87% 反映**:Mintlify 推广了协议,但很多非 Mintlify 客户(Anthropic 自己 / OpenAI / Vercel)也手写实现 |
| **Stainless / Speakeasy / Fern auto-gen** | OpenAPI → SDK + docs + MCP | 输入 OpenAPI YAML,输出 7-9 语言 SDK + docs + MCP server + skill。**OpenAI / Anthropic / Cloudflare / Google** 是 Stainless 客户(§5.1 #23 E)。**vendor 维护 spec → SaaS 转适配器 → host 端再适配** 是 2026 三层产业链 |
| **手写自维护** | 大厂或 dev infra | OpenAI / Stripe / GitHub 历史悠久,有专职 docs eng team。Stripe `/llms.txt` 命中、`llms-full.txt` 不命中 = 介入但未全面 ship 巨型版本 |

### 2.3 consumer 端三种集成路径

| Consumer | 例子 | 集成方式 | 优劣 |
|----------|------|----------|------|
| **IDE 内置** | Cursor / Continue / Aider / GitHub Copilot | `@docs <url>` 触发抓取 + 本地索引 + hybrid lexical-semantic 检索(Cursor 14.7% context 利用率) | 用户绑死 IDE,跨工具不可移植;dynamic context discovery > static injection |
| **MCP 服务化** | Context7(Upstash)/ DeepWiki(Cognition) | 中央服务从 vendor 抓 + 自家 LLM 友好转换 + 任意 host 接 MCP 协议 | 标准化好但**MCP 4-32× token 浪费**(§5.1 #23 元教训) + 受 vendor 服务方限速。Context7 65% 准确率 vs Deepcon 90% |
| **skill imperative**(我们) | search-agent ground-api skill | 教 host LLM 用 bash + curl 直查官方 ship 的 llms.txt,失败时降级 jina/Firecrawl | 0 中间层 / 0 token 占用 / host-agnostic;命中率 94%(Wave 2 实证 1-3 路径累计);**vendor 升级时 skill 自动跟随**(因为只是 curl) |

### 2.4 行业最佳实践 cross-ref(2026 共识)

我们 PIPELINE 的设计与 5 个独立行业实践对齐:

| 共识 | 来源 | 我们的对应实现 |
|------|------|--------------|
| **静态 docs 本地 indexed,而非每 query 重抓** | DigitalOcean grounding 教程 / NVIDIA blog | PIPELINE §8 缓存层(为高频 vendor 周更 llms-full.txt) |
| **dynamic context discovery > static prompt injection** | Cursor "dynamic context discovery"(ZenML LLMOps DB) | Skill 是 imperative 教 LLM **运行时按 query 选 path**,不是预填 prompt |
| **vendor 官方源胜于二手聚合** | Context7 文档 | 5 路径 100% 走 vendor 自有 URL,不走二手聚合 |
| **降级机制必须**(命中失败 graceful degrade) | LangGraph / AutoGen 最佳实践 | 5 级降级链,从 0-cost path 1 一路到 1-credit/页 path 5 |
| **probe 必严格验证**(content-type / size / body shape) | OpenAI grounding 文档 / Microsoft FastTrack | PIPELINE §3 严格验证规则(Wave 2 实证 25% 假阳率非如此不可) |

### 2.5 行业 limitations(我们要承担的)

3 个公开批评 / 限制,**我们的 strategy 必须有应对**:

1. **llms.txt 不是 IETF/RFC 正式标准**(SE Ranking / SearchSignal 多家批评):格式分散(per-page / llms-full / script-embed)
   - **我们的应对**:probe 4 候选路径 + 严格 content-type 验证;不依赖单一格式假设
2. **AI crawlers 不自动消费**(John Mueller 声明):必须 host 主动喂
   - **我们的应对**:正是这个角色 — search-agent 是"主动喂"的 skill 实现
3. **大厂未承诺生产读**(PPC.land "adoption stalls"):未来 vendor 可能撤销
   - **我们的应对**:PIPELINE §9 季度复测 + 失败计数器,vendor 撤销时立即降级到 path 3-4

## 3. search-agent 的差异化定位

### 3.1 在 consumer 拓扑里的位置

```
                         vendor 官方源(producer)
                                 ▲
         ┌───────────────────────┼─────────────────────────┐
         │                       │                         │
  IDE 内置 consumer       MCP 服务 consumer        skill imperative consumer
  (Cursor / Continue)    (Context7 / DeepWiki)    (search-agent / 我们)
         │                       │                         │
       绑死 IDE                绑 MCP host             host-agnostic
       (用户预算)            (token 浪费 4-32×)          (0 中间层)
       本地 indexed          中央服务限速            curl 直接,vendor 官源
       hybrid retrieval     hosted RAG             lexical only(暂)
       14.7% ctx util       Context7 65% acc       95% native ground truth
```

### 3.2 取舍(被 §1.8 / §5.1 #25 锁定)

**做**:
- skill imperative,bash + curl + grep,host-agnostic(任何 host LLM 自己跑)
- 4 probe + 严格验证 + 5 路径降级,**100% 静态 docs 覆盖**(94% by path 1-3)
- 季度 panel 复测 + 失败计数,**纪律性维护命中率**

**不做(明确)**:
- ❌ MCP 服务(§5.1 #23 元教训:MCP 4-32× token 浪费,且 Anthropic / Microsoft 自己已转向 CLI)
- ❌ IDE 内置(我们是给 IDE 用的 skill,不是另一个 IDE)
- ❌ vector embedding RAG(§5.3 开放问题:lexical + jina 已 95% 用例;vector 是 ROI 信号到了再加)
- ❌ 静态全 cache 预加载(运行时 curl 已 < 1s,缓存反而有 staleness 风险;只对高频 vendor 周更)
- ❌ 自家 docs hosting(我们 consumer,不是 producer)
- ❌ 跨 vendor synthesis(§3.5 我们 ground 即 cite,不 synthesize)

### 3.3 与 Context7 的精确比较(直接竞品)

| 维度 | Context7 | search-agent ground-api skill |
|------|----------|------------------------------|
| 形态 | MCP 服务 | bash skill imperative |
| 调用成本 | MCP 协议 token 占用(每个 ctx7 调用增加 ~3-5K context) | 0(纯 curl,host LLM 自己跑) |
| 覆盖 | 主要 OSS 库(npm / Python pkg / 等) | LLM/dev vendor docs(panel 16 站) |
| 命中率 | 65% accuracy(20 real-world scenarios benchmark) | 94% URL 覆盖(path 1-3 累计) |
| 更新机制 | hosted refresh,auto | runtime curl,vendor ship 即时反映 |
| 失败模式 | Context7 服务 down / 限速 / 缺这个库 | vendor 完全屏蔽(< 5%) |
| 用户绑定 | 需 MCP host | 任何 bash + curl host |
| 实施成本 | 0(install MCP) | ~50 行 skill(我们要写) |

**两者并存价值**:Context7 适合"OSS 库 / framework 的 API 用法",search-agent 适合"vendor 自家 API docs"。**用户场景不同 ⇒ co-install 而非互斥**(参 §5.1 #19 last30days-skill 同样定位结论)。

## 4. roadmap 影响(怎么落)

### 4.1 短期(Phase 1 收尾)

1. **写 `.claude/skills/ground-api/SKILL.md`** — 用 ground-api-pipeline.md §2 bash 做 imperative 骨架,加 §1.3 ground-api 用例触发器
2. **不建 adapter** — 100% skill 能 cover(§2.11 档 1)
3. **panel 锚定** — 把 wave2 16 vendor panel 加进 `.claude/skills/ground-api/PANEL.md`,作为复测基线

### 4.2 中期(Phase 2 触发条件)

1. **缓存层**(若高频 vendor query > 3次/周) — 周 cron 拉 Anthropic / OpenAI / Cohere 等大厂 llms-full.txt 到 `cache/llms-full/<vendor>.txt`,query 时 grep 缓存优先
2. **vector embedding**(若 lexical grep 失败 > 10%) — 加 sentence-transformers 本地 embedding,但**先量化失败率**

### 4.3 长期(若行业演化)

1. **llms.txt v2 / 替代标准**:订阅 [llmstxt.org](https://llmstxt.org) + 季度 panel 复测发现新格式
2. **AI 大厂转向直接读**:若 OpenAI / Google / Anthropic 公开承诺,可减少 panel 复测频次
3. **vendor 撤销 ship**:失败计数器 > 3% 触发立即重 probe + path 重排

## 5. 风险与未决

| 风险 | 概率 | 缓解 |
|------|------|------|
| Mintlify 改 llms-full.txt 格式 | 中 | 季度 panel 复测 + 严格验证 |
| Anthropic 撤 58MB(诉讼 / 政策)| 低-中 | path 2(llms.txt)兜底,加 path 3 自抓 |
| llms.txt 标准死亡(主流厂全撤)| 低 | path 3-4 路径与 llms 协议无关,降级 0 ROI 损失 |
| Jina anon 配额收紧或停服 | 中 | 已写到 PIPELINE §6 trap,可切 r.jina.ai 替代或 Firecrawl 覆盖 |
| Firecrawl 涨价或 free tier 取消 | 中 | path 5 是 ≤10% 用例,可切 Crawl4AI 自托管(§5.1 #23 D 候选) |

未决问题(进 §5.3):
1. **vector embedding 入场时机** — 失败率多少触发?需要先打点 lexical 失败率
2. **panel 是否扩展到 100 vendor** — Wave 2 16 已够 strategic,但实战长尾可能需扩
3. **跨 vendor schema 归一** — §1.4 ranking 信号统一是 adapter 层活,不在 ground-api 范围

## 6. 一句话定位

**`search-agent ground-api` = 站在行业 2024-11 起 vendor 主动 LLM 友好化的肩膀上,用 50 行 skill imperative 把 4 probe + 5 path 包成 host-agnostic 的精确 ground 通道,在 IDE 内置(用户绑死)和 MCP 服务(token 浪费)之外占住第三个差异化生态位**。

---

## 附:行业一手资料

- 标准本身:[llmstxt.org](https://llmstxt.org)
- Mintlify 实施:[Simplifying docs for AI with /llms.txt](https://www.mintlify.com/blog/simplifying-docs-with-llms-txt)
- 现状评估:[ppc.land "llms-txt adoption stalls"](https://ppc.land/llms-txt-adoption-stalls-as-major-ai-platforms-ignore-proposed-standard/) / [aeo.press "State of llms.txt 2026"](https://www.aeo.press/ai/the-state-of-llms-txt-in-2026)
- 竞品 Context7:[Upstash blog](https://upstash.com/blog/context7-llmtxt-cursor) / [Thoughtworks Tech Radar trial 状态]
- IDE 集成:[Cursor docs - llms.txt](https://cursor.com/docs/llms.txt) / Continue / Aider 文档
- 学术:[NVIDIA "Build an LLM-Powered API Agent"](https://developer.nvidia.com/blog/build-an-llm-powered-api-agent-for-task-execution/) / DigitalOcean grounding 教程
