# Domain Knowledge — Search Agent / Harness 领域

> **用途**:沉淀对话中已经积累的领域知识,作为后续决策、回顾、向他人介绍项目时的**参考手册**。
>
> **不是**:源清单(看 `sources.md`)。原 `architecture.md` / `adapter-vs-skill.md` / `adapter-empirical-test-report.md` / `sources-active.md` 均已合并入 `sources.md` + 本文档,删除。
>
> **结构**:产品 inventory → 概念与机制(含 DeerFlow 实证)→ 文献引用 → 商业/合规 → 我们的判断与翻车 → DeerFlow 工程框架交叉分析 → 元规则。
>
> **结构**:产品 inventory → 概念与机制 → 文献引用 → 商业/合规 → 我们的判断与翻车 → URL 索引。

---

## 1. 产品 / 项目 inventory

按"承担什么角色"分类。**不预判取舍,只描述客观事实**。

### 1.1 完整 Agent search / Research orchestrator(同类竞品)

这一类是**用户产品 / standalone agent**,不是给我们调的依赖。架构高度收敛于 **Planner → 并行 Executor → Compressor → Writer**。

| 项目 | 一句话定位 | 关键设计 | 链接 |
|---|---|---|---|
| **GPT Researcher**(assafelovic) | OSS deep research,**唯一完整封装成 MCP server** 的 | Planner-Executor-Publisher 三段;**`gptr-mcp` 暴露 `deep_research`/`quick_search`/`write_report`/`get_research_sources` 4 工具**——值得抄接口形态 | [GitHub](https://github.com/assafelovic/gpt-researcher), [MCP](https://github.com/assafelovic/gptr-mcp) |
| **Stanford STORM / Co-STORM** | 学术 deep research,sentence-level grounding | Perspective-Guided Question Asking + Simulated Conversation;严格句级引用 | [GitHub](https://github.com/stanford-oval/storm) |
| **MindSearch**(InternLM) | 经典 planner+并发 searcher 范式 | WebPlanner 拆 DAG + 并行 WebSearcher;3 分钟读 300+ 页 | [GitHub](https://github.com/InternLM/MindSearch), [paper](https://arxiv.org/abs/2407.20183) |
| **HuggingFace Open Deep Research** | smolagents 极简实现(~1000 行) | ReAct + code-as-action;参考价值在 minimalist agent loop | [smolagents](https://github.com/huggingface/smolagents/tree/main/examples/open_deep_research) |
| **LangChain Open Deep Research** | LangChain 旗舰示例,代码组织最干净 | Supervisor + parallel sub-agents,sub-agent context 隔离 + 压缩回传 | [GitHub](https://github.com/langchain-ai/open_deep_research) |
| **LangChain DeepAgents** | 通用长任务 agent 模板 | `write_todos` + 虚拟 filesystem + subagent + memory | [GitHub](https://github.com/langchain-ai/deepagents) |
| **Bytedance DeerFlow** | 通用 super agent harness(2.0)/ deep research(1.x) | 16+ middleware 链 / subagent / sandbox / skills(2.0);静态 graph(1.x) | [GitHub](https://github.com/bytedance/deer-flow) |
| **Vane**(ItzCrazyKns) | Perplexica 升级版,自托管 Perplexity 克隆 | SearxNG 后端 + Next.js 前端 + 任意 LLM provider;**search 部分是 wrapper,无垂直 ranking** | [GitHub](https://github.com/ItzCrazyKns/Vane) |
| **Perplexity** | 商业 answer engine | 自建爬虫 + 索引;Perplexity Computer 启用并发 sub-agent | [perplexity.ai](https://www.perplexity.ai) |
| **last30days-skill**(mvanhorn,24k★ [2026-04]) | "AI agent-led search engine scored by upvotes, likes, and real money — not editors";**纯 Claude Code skill** 形态(非 CLI) | Pre-resolver Python brain(entity → @handle/subreddit/hashtag 映射,fan-out 前做)+ 13 平台 fan-out(R/X/YT/TikTok/HN/Polymarket/...)+ **双判官**(relevance + wit/virality)+ cross-source cluster merging;**与我们位于不同 Tier**(它做 synthesis,我们做 citations) | [GitHub](https://github.com/mvanhorn/last30days-skill) |
| **Agent-Reach**(Panniantong,18k★ [2026-04]) | "给 AI Agent 装上互联网能力";**Python CLI**,16+ platform reader/searcher | Wraps OSS tools(yt-dlp / twitter-cli / **rdt-cli for Reddit** / Jina Reader)+ Cookie-based auth + **`agent-reach doctor` 自诊** + 自安装(用户粘 install URL 给 Agent);**重 CN 平台覆盖**(小红书 / B 站 / 微博 / V2EX / 雪球 / 小宇宙 / 抖音 / 微信公众号);llms.txt 第一公民 | [GitHub](https://github.com/Panniantong/Agent-Reach) |

### 1.2 RL 训练的 search agent(学术热点,不直接借鉴)

| 项目 | 一句话 | 链接 |
|---|---|---|
| Search-R1 | veRL 上 RL 训 multi-turn search,7 datasets +41% over RAG (COLM 2025) | [GitHub](https://github.com/PeterGriffinJin/Search-R1) / [paper](https://arxiv.org/abs/2503.09516) |
| Search-O1 | 给 reasoning model 加 agentic RAG + Reason-in-Documents (EMNLP 2025) | [GitHub](https://github.com/RUC-NLPIR/Search-o1) |
| R1-Searcher | 两阶段 outcome-based RL,纯 RL 无 SFT | [GitHub](https://github.com/RUCAIBox/R1-Searcher) |

→ 都是**训练范式**,需要 RL pipeline,对"无训练、纯 prompt orchestration"路线参考度低。

### 1.3 Doc grounding(防 API 幻觉)

| 工具 | 模式 | 关键差异 |
|---|---|---|
| **Context7**(Upstash) | MCP server,**预索引**主流库 | 0 配置免费,主流库 80% 命中,小众/私有库不行 |
| **Ref.tools** | MCP server,**agentic search+read** | session-aware,**95% 省 token**,**私有 repo 索引免费**,带 web fallback |
| **docs-mcp-server**(arabold) | OSS 自托管 MCP | 完全可控覆盖范围,自己运维 |
| **Jina Reader**(`r.jina.ai`) | URL → markdown reader | 0 配置免费,无索引,按需抓 |
| **Firecrawl** | 商业 scraping + search | JS 渲染 + 结构化抽取,JS-heavy 站点必备 |

### 1.4 Browser automation

| 工具 | 形态 | 内部 LLM | 维护方 |
|---|---|---|---|
| **`@playwright/mcp`**(Microsoft) | MCP server,zero config | ❌ 纯工具 | Microsoft,31.4k stars |
| **`@playwright/cli`**(Microsoft 2026) | CLI(给 host 写 bash 调用),最 token 效率 | ❌ | Microsoft |
| **browser-use** library | Python lib,内置 agent loop | ✅ 需配 LLM key | 社区,~3k stars |
| **Vercel agent-browser** | Rust CLI + Node daemon hybrid | 部分 | Vercel |
| **Browser DevTools MCP** | MCP,声称比 Playwright MCP 省 78% token | ❌ | 社区 |
| **Claude in Chrome** | Chrome extension | host LLM | Anthropic |

**关键事实**:browser-use ≠ Playwright 的替代品,**它建在 Playwright 上**。它们之间的真正差异是"内置 LLM 决策" vs "host LLM 决策"。

### 1.5 商业 AI search API

| API | 索引来源 | 输出特点 | 编程友好度 |
|---|---|---|---|
| **Tavily** | 自家爬虫 | 清洗后内容,RAG-ready,有 answer 端点 | 一般 |
| **Exa** | 自家 neural index | 语义匹配,有 People/Company/**Code** vertical | **强**(Exa Code 端点) |
| **Brave Search API** | 自家完整索引(2025 已脱离 Bing) | 标准 SERP + LLM Context endpoint | 一般 |
| **Serper.dev** | Google SERP scraping | Google 真排序 JSON | 借 Google ranking,适合长尾 |
| **SerpAPI** | 多引擎 SERP scraping | 同上 + 多引擎 | 同 Serper 但贵 5-10× |
| **Linkup** | 爬虫 + 出版商授权 | `/fast` + `/deep`,EU 合规 | 复杂多跳强项 |
| **Perplexity Sonar** | 黑盒(疑似套 Brave/Serper) | synthesized answer | **不适合 harness**(替宿主 LLM 做了 synthesis) |
| **Kagi Search API** | 多源融合 | 标准 + FastGPT + Summarizer | **closed beta,不可商业依赖** |
| **You.com API** | 混合 | Web Search / Contents / Research 三档 | 无差异化 hook |
| **Google Programmable Search** | Google 索引(限站点) | 标准 SERP JSON | **2025 停止新签约,2027/01 全面下线** |
| **Bing Web Search API** | — | — | **2025-08-11 已退役** |

**第三方 benchmark**(AIMultiple 8-API 测试):
- Agent Score 排名:Brave 14.89 > Firecrawl 14.58 > Exa 14.39 > Tavily 13.67 > Perplexity 12.96 > SerpAPI 12.28
- Tavily 自报 SimpleQA 93.3% / Exa Research 94.9% / Linkup 91% — **几乎所有"vs Google"benchmark 都来自厂商自家 blog**,需打折看
- WebWalker 多跳:**Exa 81% > Tavily 71%**
- p95 延迟:**Exa 1.4-1.7s vs Tavily 3.8-4.5s**

#### 1.5.1 X / 社交媒体数据通道(2026 实证 [2026-04-30])

X 数据通道单独成栏,因 path economics 与 web search API 完全不同——**LLM-mediated 路径(xAI X Search)单次 cost 反而最低**,颠覆"premium 假设"。

| 通道 | 形态 | 单次实测成本 | 字段丰富度 | 最佳用例 |
|---|---|---|---|---|
| **X 官方 API**(PPU + Bearer Token) | raw tweets,you-control-query | **$0.05 / 10 reads** | 中(`public_metrics`) | **合规背书 / 法务必需场景** |
| **twitterapi.io**(advanced search) | raw tweets,Top/Latest 可选 | **$0.003 / 20 raw**(标价 $0.15/1K bulk) | **高**(`viewCount` + `isBlueVerified` + 完整 author profile) | **raw 数据通道首选** |
| **xAI Grok X Search**(server-side tool) | LLM-mediated synthesized answer + citations | **$0.03 / 1 query**(grok-4.20-reasoning 5 内部 search) | n/a(已是 prose) | **one-shot 分析问题首选** |

**核心 economics 反转(三家 dashboard 真实数据)**:
1. **xAI X Search 单次 $0.03 比 X 官方 API 单次 $0.05 还便宜**——前一日 prior 估算 $0.56/call 高估 18× (见 §5.2)。Grok 后端"5 内部 X search + 5 点结构化总结 + 16 引用"全包 $0.03,完全推翻"premium fallback"框架
2. **要 LLM-mediated 答案直接走 xAI X Search 更划算**:不必"X API 拿 raw + 自家 LLM 总结"两步走;Grok 后端可能享 X 内部数据通道(xAI 是 X 子公司)
3. **要 raw 入库 twitterapi.io 比官方便宜 ~17×** + 字段更全
4. **X 官方 PPU 两端都不是最优**——除非合规

**xAI `usage.cost_in_usd_ticks` 单位实证**:`564,020,500 ticks → $0.03` → **1 tick ≈ $5.3×10⁻¹¹** ≈ **1 USD = 188 亿 ticks**。docs 没写,生产必知。

**reasoning 模型多搜索特性**:`grok-4.20-reasoning` 单次 prompt 自动发起 **5 次 X Search**(`usage.server_side_tool_usage_details.x_search_calls=5`)。预算 hook 计数应跨 reasoning 步骤(配 §2.12.4 hook 配方)。

**反爬 / 封号风险定调**:反代 web 端 X 或 Grok 在 2026 防御现状(JA4 TLS 指纹 AUC 0.998 / Cloudflare WAF / 每 2-4 周防御更新)下 = **合规 commercial API 价格已便宜到反代不划算**。
- twitterapi.io 注册 bonus 10K credits ≈ $0.10 等值,**够白测半个月**,vendor 的"上瘾陷阱"反向变成我们做实证的福利
- 实测路径见 `runs/{x-api,xai-x-search,twitterapi-io}/2026-04-30T*_*.json`

**twitterapi.io free-tier 硬约束(实测 [2026-05-01])**:
- **QPS 1 req / 5 秒**(429 message 原文:"For free-tier users, the QPS limit is one request every 5 seconds")
- docs 宣传 200 QPS / client = 付费层,**免费层实际 0.2 QPS = 12 req/min 上限**
- **影响**:fan-out 并行多 endpoint 调用 free tier 不可用 → 要 sleep 5s 串行,或合并到 advanced_search 一次拿够 20 条
- **覆盖 endpoints 实测**(详见 `.claude/skills/twitterapi-io/SKILL.md` + §5.1 #22):`advanced_search` / `user/info` / `user/last_tweets` / `tweet/replies` 全 ✓
- **隐藏高价值字段**:`pinnedTweetIds[0]`(entity resolution 单点最高信号)、`data.pin_tweet`(免一次调用)、`replies[]`(sentiment 金矿,纯 search 拿不到)

**xAI grok-cli 包装的 search_x 是二级 LLM 调用,不是 passthrough(实测 [2026-05-01])**——grok-cli 源码 `dist/grok/tools.js` 直接 hard-code 了 sub-model `grok-4-1-fast-non-reasoning`,agent 调一次 `search_x` 触发一次 sub-LLM,后者再调 N=1-2 次 xAI server-side `x_search`。**成本模型**:1 agent search_x ≠ $5/1K calls,而是 `sub-LLM tokens + N × $5/1K calls`。详见 §5.1 #22。

### 1.6 AI-Augmented 二级源(白嫖别人 LLM 算力)

| 源 | 价值 | 关键 |
|---|---|---|
| **DeepWiki**(Cognition / Devin 团队) | **50k+ 主流 repo 已预生成 AI wiki + Q&A** | **官方 MCP,完全免费无 auth**:`ask_question`/`read_wiki_contents`/`read_wiki_structure` |
| **deepwiki-open**(AsyncFuncAI) | OSS 自托管 | 可指向**私有 repo / 内网 GitLab** |
| **OpenDeepWiki**(AIDotNet) | C#/TS 实现 | 模块化,适合企业内集成 |
| **Phind** | coding 垂直 AI 搜索 | Perplexity-for-devs |
| **gitingest** | repo→LLM-ready 文本 | URL 替换:`gitingest.com/<owner>/<repo>` |
| **Repomix** | CLI:打包 repo 成单文件 | 支持过滤/格式 |
| **GitMCP** | repo → MCP server | 暴露给 agent |
| **uithub** | URL trick:`uithub.com/x/y` 取全 repo Markdown | 0 配置 |

### 1.7 编程领域专用工具(supporting cast)

| 工具 | 角色 |
|---|---|
| **Aider repo map** | 本地 codebase grounding 金标准:**tree-sitter + symbol 图 + personalized PageRank** |
| **Sourcegraph Cody** | 跨仓库符号搜索,zoekt + 远端代码主机 |
| **Continue.dev** | 自定义 Context Providers,有 repo-map provider |
| **SWE-Search / Moatless** | MCTS + 双 agent (Value/Discriminator),SWE-bench +23% |
| **Serena MCP** | LSP-based symbolic code search,MCP 形态 |
| **Claude Context**(Zilliz) | 向量代码检索 MCP |
| **GitHub MCP server**(官方) | repo/issue/PR 操作 |

### 1.8 "Thin Harness, Fat Skills" 共同体(Garry Tan + Anthropic 系)

三个项目共享同一种哲学,且彼此设计成可组合:

| 项目 | 作者 | 一句话 | 形态 |
|---|---|---|---|
| **[gstack](https://github.com/garrytan/gstack)** | [Garry Tan](https://github.com/garrytan)(YC CEO) | "把 Claude Code 变成虚拟工程团队"——23 个专家角色 + 8 个工具(CEO/Eng/Designer/QA/Security/Release) | CLI + skills,装在 ~/.claude/skills/ |
| **[gbrain](https://github.com/garrytan/gbrain)** | Garry Tan | "Your AI agent is smart but forgetful. GBrain gives it a brain"——29 skills 的个人知识 brain + 自连知识图,PGLite/Postgres+pgvector | CLI + MCP server + skills |
| **[superpowers](https://github.com/obra/superpowers)** | [obra](https://github.com/obra) (Jesse Vincent, Anthropic) | "完整的 software development methodology for your coding agents",TDD + subagent-driven 开发 | Anthropic 官方 plugin marketplace |

**关联(三层)**:

1. **共同哲学**:三者都明确宣称 "**Thin harness, fat skills**" 原则——把智能放在 skills(markdown 工作流),runtime 极薄。gbrain 有专门一篇 [`docs/ethos/THIN_HARNESS_FAT_SKILLS.md`](https://github.com/garrytan/gbrain) 论述
2. **gstack ↔ gbrain 显式联动**:`gstack/setup-gbrain` 命令、`USING_GBRAIN_WITH_GSTACK.md` 文档、gstack 把 gbrain 当 host 注册——**gstack 管"如何 ship",gbrain 管"如何 remember"**
3. **多 host 兼容设计**:三者都通过 CLI + skills 形态自然兼容 Claude Code、Codex CLI、Cursor、OpenCode、OpenClaw 等多个 agent runtime

**对我们 harness 的直接意义**:
- 三者验证了我们最近的 "**CLI + skills**" 架构选择(§5.1 #4)
- gbrain 可以是我们 harness 的 **memory 层**——存用户搜索 candidates / 技术栈偏好 / 过往项目选择
- gstack 的 `/setup-X` 一键安装模式是 README 的样板
- superpowers 的 **94% PR rejection rate** + "**If You Are an AI Agent**" 反 slop 守则值得抄到我们 CONTRIBUTING

**关于 OpenClaw**:gstack/gbrain 重度提到 [OpenClaw](https://github.com/openclaw/openclaw)(247k stars,Peter Steinberger 主导)。这是开源 agent runtime 生态的核心节点之一。**我们 CLI + skills 形态自然兼容,不需要专门适配**。

#### 1.8.1 "Fat Harness" 反极:grok-cli / Codex / OpenAI 系 [2026-05-01]

为标定 §1.8 的方位,把 [`grok-dev@1.1.5`](https://github.com/superagent-ai/grok-cli) 项目本地装好后**反编译 dist/**,确认它是 fat-harness 路线的标准品(详见 §5.1 #22)。

| 维度 | Thin Harness 共同体(我们 + §1.8 三家) | Fat Harness(grok-cli / Codex 系) |
|---|---|---|
| **bundled 子系统** | runtime 极薄,智能在 skills | 16 子系统 / 519 文件 / 70MB 二进制(telegram + iMessage + Coinbase x402 + audio STT + 桌面控制 + image/video gen + scheduler) |
| **subagent type 数** | 多种(general / Explore / Plan / Code Reviewer / ...) | 1 种(`explore`),但 schema 内置 `maxToolRounds + maxTokens + sandboxMode` 强约束 |
| **hook 事件** | Claude Code 9 个 | grok-cli **17 个**(分流 PostToolUseFailure / StopFailure / TaskCreated / TaskCompleted / PostCompact / InstructionsLoaded / CwdChanged) |
| **hook 安全模型** | 项目级 + 用户级,可配置 | **拒绝项目级 hooks**(防 malicious repo 注入)→ 用户级专享 |
| **Instructions 文件** | `CLAUDE.md`(根目录) | `AGENTS.md` 层级链(`~/.grok/AGENTS.md` → git root → cwd 沿途每层),支持 `AGENTS.override.md` 替换父级 |
| **distribution 边界** | 工具/skill 可逐项授权,企业合规友好 | 一站式 bundle,合规白名单几乎不可能过(Coinbase x402 / Telegram remote 一票否决) |
| **server-side search 工具实现** | passthrough(host LLM 直接调) | **二级 LLM 包装**(grok-cli 内 hard-code `grok-4-1-fast-non-reasoning` sub-LLM 跑 x_search,1×→N× 放大) |

**对我们 search-agent 的直接意义**:
- **方位明确**:thin harness 路线,**不抄 grok-cli**(也不抄 Codex)。任何 "bundled subsystem" 提案都要先回答"为什么不能放 skill 或 co-install MCP?"
- **能抄的具体几条**(进 §5.1 #22 的"借鉴清单"):
    1. **hook 事件分流**:`PostToolUseFailure`/`StopFailure` 分专属 channel —— 失败重试逻辑用单独 hook 比硬塞 PostToolUse 干净
    2. **Hook block 返回结构**:被拦的 tool 调用返回 `{ success: false, output: "[Hook blocked] ${reason}" }` 给 LLM,**不抛异常**——模型 replan 质量更高
    3. **subagent 结构性预算**:`maxToolRounds + maxTokens` 写入 subagent invocation schema 而非 prompt(模型不能"忘")
- **必须避开的几条**:
    - 二级 LLM 包装:**不要**为求"更好的 search 体验"在 host 之外起一个 sub-LLM 跑工具——成本不透明 + 跨 host 不 portable + 失去用户对 query 的控制权
    - 项目级 hooks 当唯一约束:跨 host 不 portable(grok-cli 不接),**预算/约束逻辑要下沉 adapter 层**作为兜底,hook 当锦上添花

---

## 2. 概念与机制

### 2.1 LLM Web Search 真实拓扑

**LLM 自己不会搜索**。任何号称"有 web search"的模型,本质都是三件东西的组合:

```
┌────────────────────────────────────────────┐
│  ① 后端搜索引擎(真正干活的)              │
│  Gemini → Google Search 自家索引(独占)   │
│  ChatGPT → Bing → SearchGPT 自建爬虫       │
│  Claude → Brave Search API                  │
│  Perplexity → 完全自建爬虫和索引            │
│  Qwen/MiniMax/DeepSeek → 多数租 Bing/百度   │
├────────────────────────────────────────────┤
│  ② 模型侧的三件后训练能力                  │
│  - 何时搜(知识截止 + 置信度判断)         │
│  - 怎么搜(query rewriting / decomposition)│
│  - 怎么读(snippet → grounded answer)     │
├────────────────────────────────────────────┤
│  ③ 工程胶水(决定体验上限)                │
│  snippet vs 全文抓取 / rerank / browse loop │
└────────────────────────────────────────────┘
```

**全球真正"自己爬网建索引"的引擎不超过 5 家**:Google、Bing、Brave、Perplexity、Yandex/Baidu。其他都是套壳或复用。**索引层是真正护城河**。

### 2.2 浏览器 vs 搜索引擎(易混淆)

```
┌─ AI 答题引擎  →  Perplexity / ChatGPT / Claude
├─ 浏览器(UI)→  Chrome / Firefox / Brave / Safari / Edge
└─ 搜索引擎(索引)→ Google / Bing / Brave Search / DuckDuckGo
```

- **浏览器 ≠ 搜索引擎**。Chrome 自己不搜索,只是把 query 发给 Google
- **Chromium 提供**:Blink 渲染引擎、V8 JS 引擎、Network stack、Web API 实现、沙箱、扩展 API、DevTools
- Chrome / Edge / Brave / Opera / Arc / Vivaldi 都是 Chromium 上加产品壳;Firefox(Gecko)/ Safari(WebKit)是另两个独立内核
- **DuckDuckGo 严格说是搜索引擎**(虽然主要复用 Bing 索引);**Brave 既是浏览器也有自家 Brave Search**

### 2.3 网站发布即被搜到的原理

**"被搜到"不是浏览器干的,是搜索引擎爬虫干的**。爬虫发现新站靠 5 条路径:
1. **Backlinks**(主流)— 已索引网站链向你
2. **Sitemap 主动提交**(最快,几小时到几天)
3. **Certificate Transparency 日志**(申请 HTTPS 证书会触发)
4. **WHOIS 监控**(部分爬虫)
5. **随机扫描**(极少)

只要你的站满足"公开 DNS + 可 HTTP 抓取 + 不在 robots 里禁",**世界上任何人都可以爬你**——爬虫不需要你授权。这就是"开放 Web"的基础。

### 2.4 多模态信噪比的 4 种细分

把"multimodal"拆开,4 种问题完全不同:

| 类型 | 例子 | 难度 | SNR |
|---|---|---|---|
| 多模态作为内容类型 | "找一个讲 React Server Components 的视频" | 中 | **高**(只检索) |
| 多模态作为消费内容 | "把这 30 分钟视频里讲 hooks 的部分总结" | 高 | **低**(全 transcribe) |
| 多模态作为输入理解 | "我截屏了报错,告诉我哪里不对" | 中 | **高**(单图 vision) |
| 多模态作为 ranking 信号 | "看页面截图判断结果相不相关" | 高 | **极低**(token 巨大) |

**关键 insight**:多模态的"高 SNR 用法"是**消费平台预处理过的文本元数据**(YouTube transcript / 播客文字版 / slides PDF),而不是自己跑 ASR/OCR/Vision。

**Long-tail 框架**:80% query 在 text 层够 / 15% 在准多模态(transcript)够 / 5% 真需要 raw video/image。**架构原则**:为 80% 优化默认路径,为 15% 加廉价层,为 5% 留昂贵但可达的 escape hatch。**不要把 5% 的成本均摊到所有 query**。

### 2.5 Skills vs MCP 的 Token 经济(2026 已收敛的共识)

[Anthropic 工程博客《Code execution with MCP》](https://www.anthropic.com/engineering/code-execution-with-mcp) 的核心发现:

- **150K tokens → 2K tokens**(同任务,代码执行 vs MCP 调用),**节省 98.7%**
- "Tool definitions 在 Anthropic 内部曾消耗 134K tokens"——光 schema 就把 context 烧了大半
- 简单任务上 **MCP 用 32× 于 Skills 的 token**

[Playwright 官方 benchmark](https://testcollab.com/blog/playwright-cli):
- **Playwright MCP 114K tokens vs Playwright CLI 27K tokens**,~4× 减少
- 关键机制:**完整 DOM 或图片二进制不进入 LLM context,除非 agent 显式 read 那些文件**

| 维度 | MCP | Skills + Bash CLI |
|---|---|---|
| Tool 描述驻留 context | 全部 schema 永久占,N×几千 token | **Progressive,按需载入** |
| 输出处理 | 全部塞回 LLM | **落文件,grep/jq/head 按需读** |
| 多步组合 | 每步 round-trip 给 host LLM | **管道直接 pipe**,中间不进 LLM |
| 训练分布 | MCP 是 2024 才有 | **bash/curl/jq/grep 是 30 年训练数据基底** |
| 状态管理 | server 自己存 state | **文件系统 = 0 cost state** |

**MCP 仍有价值的少数场景**:
- 需要 host **直接看到结构化 schema** 才能调对的工具
- **持久状态/会话**(如长 session 的 browser context)
- **跨 agent 标准化协议**(给别人用)

### 2.6 多源路由:Flooding vs Routing(20 年 IR 文献已收敛)

**经典 IR 文献**:
- **Si & Callan ReDDE (SIGIR 2003)**:routing 在源 >10 且大小不均时显著优于 flooding
- **Thomas & Shokouhi SUSHI (SIGIR 2009)**:同上
- **Shokouhi & Si 2011 综述**:**候选源 ≤ 6 且都是高质量精选源时,flooding 与 routing 几乎打平,且实现简单得多**(routing 的分类误差吃掉节省)

**LLM 时代实证**:
- **Toolformer / Gorilla**:工具空间 ≥1600 时,**学过 routing 远胜 flooding**
- **Self-RAG**:"按需 retrieve" 比 "always retrieve" 好——但前提是判得准
- **MindSearch**:planner 拆 DAG,**每个子问题内部并发 fan-out**(3 分钟读 300 页)
- **Anthropic Contextual Retrieval**:BM25+embedding+rerank **hybrid 把检索失败率砍 67%**

**业界共识(2024-2026)**:**没有任何严肃产品做"纯智能 routing 选一个源"或"无脑 flood 所有源"**。共识是 **三段式混合**:
```
Decompose query → Parallel fan-out within source-class
                → RRF fusion + dedup → LLM rerank top 20-30
```

**对小 N(4-6 源)场景**:**flood + 廉价启发式 gate + RRF + LLM rerank** 是当前最优。学过的 router 留到 >15 源再说。

### 2.7 AI 搜索为什么有时不如自己 Chrome

**多层有损变换**,每层都丢信息:

1. **Query 层**:LLM 改写后精度被稀释("OpenAI API rate limiting" 替代 "ChatGPT API 429 retry-after")
2. **检索层**:后端弱(Brave < Bing < Google)+ Top-K 太小(3-5 vs 10+)+ 抓不到 JS/login + 走通用而非垂直站
3. **综合层**:5 个结果合成成一段,失去源归属、冲突信号、原文结构、recency,可能 paraphrase 出错
4. **UX 层**:人扫 10 条标题 5 秒,自带"哪些站靠谱"的品味,LLM 没有
5. **框架层**:AI 给"答案",但很多任务实际要"地图"

→ **设计 harness 的反推原则**:pass-through 模式 / top-K 给大 / 结构保留 / 不做 synthesis / 垂直直连 / recency 显式化

### 2.8 垂直站的真正价值 = 它的 API,不是它的域名

每个垂直站有**两套东西**:
- 它的 **网页**(被 Google 索引的部分)
- 它**自己**的搜索/API(带原生 ranking 信号:vote/stars/citation/published_at)

**Google 索引只抓到第一列**。即使你 `site:stackoverflow.com xxx`,你也拿不到 SO 自己的 vote/accepted ranking。**真正"原生搜索"是用站方自己的 API**。

→ harness 价值 = "**绕开通用 web 索引,直接走垂直站的原生 API,拿到原生 ranking 信号和结构化数据**"。Chrome 能做这件事是因为人会手动切站;AI 默认做不到,harness 把这件事自动化。

### 2.9 Adapter vs Skill 边界测试(派生自 2.8)

**原则**:**adapter 的存在意义是"web_search 替代不了它的 ranking/字段",不是"它内容值得"**。

否则就只是 wrapper(给 web_search 套个 Pydantic schema 而已,无新增价值)。

**4 问决策树**:

```
Q1. Web search 能找到这个站的内容吗?
    ├─ 不能(login wall / API only)→ adapter 或 drop
    └─ 能 →  Q2

Q2. Web search 能拿到它的核心 ranking 信号吗?
    ├─ 不能(stars/votes/citation/downloads 等)→ adapter
    └─ 能 → Q3

Q3. 它已经有免费 MCP / API 暴露给 agent 了吗?
    ├─ 是 → co-install,不算 adapter
    └─ 否 → Q4

Q4. agent 知道这个站存在吗?
    ├─ 不知道 → 加进 skill 的 cross-reference 段(教 agent 用 web_search + `site:`)
    └─ 知道 → 不需要任何动作
```

**实际应用结果**:把 sources.md 数百个候选源筛到 12 个核心 adapter + 5-7 个可选 + 数十个 skill-only。详见 `adapter-vs-skill.md`(已合并废弃)。

**Skill 双重职责**(派生洞察):
- 教 host 怎么调 adapter(路线图)
- **教 host 还应该 web_search 哪些 site**(awareness 教学)——这是 skill 真正的杠杆,把数十个 skill-only 站集中暴露

### 2.10 防幻觉 / 防偷懒 / 灵活切换 三套机制(DeerFlow 实证)

**对应 architecture.md §11 工程纪律**。这一节梳理"业界主流 agent harness 在三个研究关键问题上是怎么做的",作为我们设计自己机制时的参考库。

#### 2.10.1 防幻觉(anti-hallucination)

DeerFlow 的实际做法(以中间件为主):

| 机制 | 文件 | 原理 |
|---|---|---|
| **ClarificationMiddleware** | `agents/middlewares/clarification_middleware.py` | agent 调 `ask_clarification` 工具→直接 `Command(goto=END)` 中断,强制用户介入。**不让模型在信息不全时硬猜** |
| **ToolErrorHandlingMiddleware** | `agents/middlewares/tool_error_handling_middleware.py` | tool 抛 exception → 转成 ToolMessage 注入 context。**模型不会"以为成功了"** |
| **DanglingToolCallMiddleware** | `agents/middlewares/dangling_tool_call_middleware.py` | AI 发了 tool_call 但被打断没结果?注入占位 ToolMessage,**强制 thread 一致** |
| **MemoryMiddleware 的 prompt injection** | `agents/memory/` | 把已知事实灌进 system prompt 的 `<memory>` 标签,**让模型看到 ground truth 而非编造** |
| **Pydantic schema 全栈** | `app/gateway/routers/*.py` 的 response_model | 任何 API 返回必走 schema 校验,**字段不对就 fail loud** |
| **Skill 强制 citation** | 各 `skills/*/SKILL.md` | skill markdown 里写死"必须引用源,格式 `[file:line]`",**模型遵守 skill 就是遵守 citation 纪律** |

#### 2.10.2 防偷懒(anti-laziness)

| 机制 | 文件 | 原理 |
|---|---|---|
| **LoopDetectionMiddleware**(双层) | `agents/middlewares/loop_detection_middleware.py` | hash-based(同 tool calls 重复) + frequency-based(同 tool 类型 30 次警告/50 次硬停)。**catch 模型卡死或刷量** |
| **TodoListMiddleware** | `agents/middlewares/todo_middleware.py` | plan_mode 下,模型必须维护 todo list,**不能"忘记"中间步骤** |
| **SubagentLimitMiddleware** | `agents/middlewares/subagent_limit_middleware.py` | 截断超额并发 task 调用(MAX_CONCURRENT=3),**防止一次喷 20 个 subagent 然后躺平** |
| **recursion_limit + max_turns** | `subagents/executor.py:303` | 硬上限,模型刷再多步也被掐 |
| **SummarizationMiddleware** | `agents/middlewares/summarization_middleware.py` | context 接近上限时自动总结,**模型不能用"context 满了"当借口偷懒** |

**关键洞察**:DeerFlow 的 anti-laziness 主要是"防过度行动"(loop detection),**对"做得不够"的防御主要靠 skill 文件里的 imperative prompt**。这点 gstack/superpowers 做得更狠——命令式 skill 语气、verifiable 步骤。**我们综合吸收**(见 architecture.md §11.2)。

#### 2.10.3 灵活切换(flexible switching)

| 机制 | 文件 | 原理 |
|---|---|---|
| **Reflection-based class resolution** | `reflection/` (resolve_variable, resolve_class) | config.yaml 写 `use: langchain_openai:ChatOpenAI`,代码 `resolve_class(path, BaseModel)` 动态加载。**换 backend 改 1 行 yaml** |
| **Provider pattern** | `sandbox/sandbox_provider.py`、`models/factory.py` | 抽象接口 + 多实现(LocalSandbox/AioSandbox / 多 model)。**新 provider 只实现接口** |
| **`get_available_tools()` 动态组合** | `tools/__init__.py` | 启动时根据 config + MCP + builtins + subagent 配置组合工具集。**enable/disable 单 tool 不重启** |
| **MCP 外挂** | `mcp/` + `extensions_config.json` | 外部工具一律 MCP 接,**新工具不改主代码** |
| **Skills as markdown** | `skills/{public,custom}/` | 加 skill = 加 markdown 文件 + 一行 enabled state,**0 代码扩展** |
| **Config 自动 reload** | `config/app_config.py` 的 mtime 检查 | 改 yaml 不重启 server,**热切换** |
| **Lazy init** | 所有 middleware 默认 `lazy_init=True` | 不用就不构造,**启动快** |

#### 2.10.4 轻量化的工程约束

| 约束 | 实施方式 |
|---|---|
| Harness/App 边界 | CI grep 测试:`tests/test_harness_boundary.py` 检查 `packages/harness/` 不出现 `import app.*` |
| TDD | CLAUDE.md 第一条强制每个 feature 必有测试,~110 个测试文件实测 |
| Trace ID 贯穿 | 每个 SubagentExecutor 一个 8-hex trace_id,所有 log 带它 |
| 配置版本化 | `config_version: 8` 字段 + `make config-upgrade` 自动迁移 |
| 类型严格 | 全栈 Pydantic + Python 3.12 type hints + ruff 240 字符 |

### 2.11 Adapter 真价值在跨源中间层,不在 per-source 代码 [2026-04-29]

**触发观察**:跑完 22 adapter 实测后,用户问 "我看你调用都很简单,那对于这种 adapter 是不是可以完全 skills 化?" ——观察是对的,值得正面打。

**这一节是 §2.5(MCP vs Skills 的 token 经济)和 §2.9(adapter vs skill 边界)的合并修正**——前两节给的是"何时用 skill / 何时用 adapter",本节解决"adapter 这层到底是什么"。

#### 2.11.1 实测结论:per-source 调用平均 = 10 行 bash

22 source 全测下来,每个 source 的核心调用是同一种结构:

```bash
xh GET <URL> <params> <auth-header> | jq '<filter>'
```

差异 = URL 模板 + 1-2 个 header + jq 选字段。**这部分写 Python 类纯属过度工程**——和用户洞察一致。

#### 2.11.2 但 adapter 不为单 source 存在,为这 7 个跨源中间层服务存在

| 功能 | 单条 bash | 多 bash 拼接 | core 代码 |
|---|---|---|---|
| 多 source 并发 fan-out + per-source 超时 | ❌ | `xargs -P` + 子进程错误捕获,可写但脆 | trivial (`asyncio.gather`) |
| **RRF 融合**(GitHub stars + arXiv citations + HN points 合并) | ❌ | 让 LLM 每次重写算法,token + 错率双高 | ~30 行 |
| URL 去重 / canonical 化(同仓在 GH+DeepWiki+libraries.io 出现 3 次) | ❌ | 重复劳动 | ~20 行 |
| **schema 归一**(`stargazers_count` ↔ `points` ↔ `citationCount` → 统一 `ranking_score`) | ❌ | 重复劳动,字段名易漂 | per-source 字段映射 |
| **cache + cache_key 派生**(同 query 5 min 内返同结果) | ❌ | 文件缓存可写在 skill 里,但状态管理脆 | ~50 行(参考 DeerFlow `_stable_tool_key()` §2.10.2) |
| 错误 → ErrorResult(host 看到 explicit error 不脑补) | ❌ | 每条 bash 错误让 LLM 解析,代价高 | trivial |
| Rate-limit 保护(S2 burst 即 429,GH 60→5000)| ❌ | 状态全靠 LLM 记,几乎必崩 | per-source 配额 + retry |

→ 这 7 件事是 search harness 的**真正价值**——不是"per-source 代码",是"**所有 source 共享的中间层**"。

#### 2.11.3 三档架构(按 LoC 砍)

**档 1 — adapter-heavy**(原 architecture.md 的隐含假设):
- 19 个 adapter Python 类 × 各 100-200 LoC + core ~500 LoC = **~3-5K LoC 总**
- 优:per-source 单测、quirk 编入代码、host 完全无脑
- 缺:重;source 漂移按月算,跟不上节奏

**档 2 — config-driven engine**(推荐):
- 1 个 generic `SearchEngine` core(fan-out / RRF / cache / errors / schema 校验)
- + 19 个 YAML config,每文件 ~10-30 行
- 总 **~1-2K LoC**,per-source 工作量 ~10 分钟
- 加新 source = 1 个 config,**0 代码**

YAML 例(GitHub):
```yaml
name: github
url_template: "https://api.github.com/search/repositories?q={query}&sort=stars"
headers:
  Authorization: "Bearer ${GITHUB_TOKEN}"
  Accept: "application/vnd.github+json"
field_map:
  title:         ".items[].full_name"
  url:           ".items[].html_url"
  ranking_score: ".items[].stargazers_count"
  snippet:       ".items[].description"
  source:        "github"
quirks:
  require_token: true     # adapter 启动时检测 PAT 缺失则跳过
  rate_limit:    "30/min search; 5000/hr core"
```

**90% quirks 可表达为 config**(加 header / param / 二段 fetch 模式),**剩 10% 重 quirks**(GitLab N+1 license / CRAN cranlogs 配对 / arXiv Atom XML 解析)写成 core 里的 **named hooks**,config 通过 `hook: <name>` 引用。

**档 3 — pure skill**(无 CLI binary):
- 0 个 adapter,0 个 CLI
- 5-7 个 skill 教 host 直接 bash
- 跨源 fan-out → host 自己开并发 + 自己 RRF + 自己 dedup

#### 2.11.4 档 3 的致命缺陷:token 经济**反向**

§2.5 引用 Anthropic *Code execution with MCP* 的 98% token reduction——**前提是 "让 LLM 调一个本地命令做完所有 fan-out + 过滤"**。pure-skill 把这个反过来打:

| 场景 | 档 2(config engine) | 档 3(pure skill) |
|---|---|---|
| `find-repo` 4 source 并发 | host 调 1 个 CLI,**返回 ~2KB top-10 候选** | host 跑 4 bash,**4 × ~30KB raw JSON 进 context** ≈ 30K+ tokens |
| RRF 融合 | core 几毫秒做完 | host 在 LLM context 里写算法,**token + 错率双高** |
| 重复 query | core cache 命中,~0ms | host 每次重跑 |

**关键认识**:CLI binary 不是"对抗 MCP",是"**对抗让 LLM 直接消费 raw API 响应**"。两件事。pure-skill 把这个分界拆穿了——它把所有 fan-out + 解析推回 LLM context,**让 §2.5 的 token 优势反向**。这是档 3 的死因,不是工程口味。

#### 2.11.5 对 §2.9 决策树的修正

§2.9 决策树问 "需不需要 adapter"——给的是 source-level 答案("有特殊 ranking 信号 → adapter")。**本节修正了 adapter 的定义本身**:

| 维度 | 旧定义(隐含) | 新定义 |
|---|---|---|
| Adapter 是什么 | 每个 source 一份 Python 代码 | source 在 generic engine 里的一份 config |
| 加新 source 的成本 | 100-200 LoC + 单测 | 10-30 行 YAML |
| 共享中间层在哪 | core(隐式)+ 19 个 adapter 重复实现 | core(显式)|

→ §2.9 的 source-级决议(22 个进 Tier 1)不变,**实施形态**从"22 个 Python 类"降级为"22 个 source config + 1 个共享 engine"。

### 2.12 Framework vs instruction+hooks 在 Claude Code 上的取舍 [2026-04-30]

**起点疑问**:Claude 已经原生支持 [parallel tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use) + subagent (Agent tool) + TaskCreate/Plan,我们的 search-agent 还需要 LangGraph / DeerFlow 那种 graph + state schema 吗?

**核心判断**:跑在 Claude Code 上的 agent **多数情况下不需要重型框架**。但"不要框架"≠"裸提示词"——需要的是**薄 adapter 层 + hooks 兜底约束**,把编排留给模型。

#### 2.12.1 两条路线的优缺点

**路线 A:instruction + 原生能力(CLAUDE.md / skill / Agent / 并行 tool_use)**

| 优点 | 缺点 |
|---|---|
| 与模型规划能力对齐;parallel tool use / subagent fan-out / TaskCreate 是一等公民 | **非确定性**:同样输入路径不同,可能 3 步可能 8 步 |
| 零抽象税:无 state schema / reducer / edge | 难强约束顺序("必须先 A 再 B"靠 prompt 不可靠) |
| 调试直接:transcript 即真实推理路径 | 预算控制弱:rounds / fan-out / token 写在 prompt 里模型会"忘" |
| skill / subagent 易复用 | 跨会话不可恢复:无原生 checkpoint |
| - | 观测性靠外挂(hooks / 日志),不像 graph 节点天然是 trace 锚点 |

**路线 B:framework(LangGraph / DeerFlow 风格 supervisor + worker graph)**

| 优点 | 缺点 |
|---|---|
| 确定性流程,路径可复现 | **常常与模型规划能力打架**:模型想并行 3 个搜索,被 graph 强制线性 |
| 显式 state,天然支持 checkpoint / resume / 重放 | 维护成本真实:需求一变图就改,state schema 迁移痛苦 |
| 预算与策略好落地(写在边上模型绕不过去) | 隐藏推理:debug 看到节点跳转,不是模型决策 |
| 节点级 trace 便于评测 | 对"研究式"任务(搜索 agent 是典型)水土不服 |
| 多 agent 协作有标准结构 | 在 Claude Code 上重复造轮:subagent / Plan / Task 已覆盖 80% 编排需求 |

#### 2.12.2 Hooks 把非确定性变成"自由规划 + 硬性 reject"

Claude Code hooks(`PreToolUse` / `PostToolUse` / `Stop` / `SubagentStop` / `UserPromptSubmit` / `SessionStart` 等)在 settings.json 配置,由 harness 执行——**模型不能绕过**。

**Hooks 能搞定的(确定性约束)**:

- **预算硬上限**:PreToolUse 计数,超 N 次直接 block(prompt 写"最多 5 次"会忘,hook 不会)
- **强制顺序**:hook 读状态文件,"A 没跑过就不许调 B"
- **输入校验**:tool 入参 schema 不合规直接 reject
- **输出归一化 / 去重**:PostToolUse 改写返回值再喂回模型
- **强制不停**:Stop hook 拒绝停止,直到引用数 ≥ 3 / 关键问题已答
- **可观测性**:每个 hook 都是天然 trace 点,落 jsonl 即可获得 graph 节点级可见性
- **副作用兜底**:模型不调 X 时,hook 在某些事件上自己跑 X

**Hooks 解决不了的**:

1. **跨会话 / 跨进程恢复**:hook 只在活进程 fire,crash 后无 resume。Durable workflow 仍需真框架(WDK / Temporal)或自写 checkpoint
2. **规划非确定性本身**:hook 是**事后拒绝**,模型仍先发起调用→被拦→再 replan。拒绝率高 = round-trip + token 烧得快
3. **多 subagent 间仲裁**:hook 在当前进程 tool 边界 fire,无法直接协调兄弟 subagent 的资源竞争
4. **质量层面的确定性**:hook 保证结构合规,保证不了两次跑出来的总结一致
5. **复杂条件下的 replan 质量**:拒绝越频繁,模型越容易"反复试错—被拒—再试"。拒绝消息必须明确**为什么**和**该怎么改**

#### 2.12.3 关键取舍:拒绝是有成本的

把 hook 当**罕见护栏**用,不是主控制流。判断标准:

| Hook 拒绝频率 | 信号 |
|---|---|
| 平均每会话 1-3 次 | **健康**,纯护栏 |
| 平均每会话 10+ 次 | 在和模型对抗,prompt 没设计好——**改 instruction,不是加更多 hook** |
| 80% tool 调用都被改写 | 实际在用 hook 写 graph——**该上真框架** |

反向定理:**当 prompt 已让模型 90% 时间做对的事,hook 兜底剩下 10% 是性价比最高的组合**。

#### 2.12.4 落到 search-agent 的具体配方

针对 §2.11 / §2.9 提到的 4 个硬问题(adapter 质量 / 预算 / 去重 + 引用 / 可评测),hook 怎么用:

| 问题 | 解法 | Hook 类型 |
|---|---|---|
| 预算(总调用数 / fan-out 宽度) | 计数 + 拒绝;状态写 `.claude/state/budget.json` | PreToolUse |
| 强制流程(必须 plan→search→read→cite) | 检查"已产出 ≥ N 条带引用结论",否则拒绝停止 | Stop |
| 去重 + 引用归一化 | 每次 search/fetch 后做 url canonicalize、dedup、字段标准化 | PostToolUse |
| 评测可观测 | 所有 hook 写 jsonl,离线跑指标 | 全部 |

加上 adapter 层做 rate limit / retry,**这套组合在 Claude Code 上等价于 DeerFlow 80% 的编排能力,复杂度低一个数量级**。

剩下 20%(跨会话恢复、长任务 checkpoint):search-agent 若是单次请求→单次输出形态根本用不到;若是后台长跑型(订阅式爬取、增量更新),才考虑真框架。

#### 2.12.5 与 §7 DeerFlow 分析的衔接

§7.1 列出的"应该抄"项(harness/app 边界、stable key、错误转消息、trace_id)——这些**全部能用 hooks + adapter 层实现**,不需要 LangGraph。
§7.2 列出的"不抄"项(17 middleware / SubagentExecutor / ThreadState / Memory / Sandbox)——本节给出了**为什么不抄的理论依据**:那些是 framework 层为解决"agent 长跑生命周期"造的轮子,Claude Code 原生 + hooks 已覆盖等价能力。

→ **元规则**:在 Claude Code 上做 agent,**默认不上 graph framework;用 prompt + hooks 把模型自由度约束到可接受范围**,只在确实需要 durable workflow / 非 LLM 重活节点时才考虑框架(且优先 WDK 这类轻量方案,不是 LangGraph)。

---

## 3. 关键论文 / 文献(可直接 cite)

### 3.1 经典 IR(federated search / source selection)

| 文献 | 链接 |
|---|---|
| ReDDE — Si & Callan SIGIR 2003 | http://www.cs.cmu.edu/~lsi/Sigir_2003.pdf |
| SUSHI — Thomas & Shokouhi 2009 | https://www.researchgate.net/publication/221299793_SUSHI |
| Federated Search 综述 — Shokouhi & Si 2011 | https://www.microsoft.com/en-us/research/wp-content/uploads/2011/01/now.pdf |
| Resource Selection on the Web — Dai et al. 2016 | https://arxiv.org/abs/1609.04556 |

### 3.2 LLM 时代 search agent

| 论文 | 链接 |
|---|---|
| WebGPT (2021) | https://arxiv.org/abs/2112.09332 |
| ReAct (2022) | https://arxiv.org/abs/2210.03629 |
| Toolformer (2023) | https://arxiv.org/abs/2302.04761 |
| Gorilla (2023) | https://arxiv.org/abs/2305.15334 |
| ToolLLM (2023) | https://arxiv.org/abs/2307.16789 |
| Self-RAG (2023) | https://arxiv.org/abs/2310.11511 |
| FreshLLMs (2023) | https://arxiv.org/abs/2310.03214 |
| Self-Discover (2024) | https://arxiv.org/abs/2402.03620 |
| MindSearch (2024) | https://arxiv.org/abs/2407.20183 |
| Search-R1 (2025) | https://arxiv.org/abs/2503.09516 |
| SWE-Search / Moatless (2024) | https://arxiv.org/abs/2410.20285 |

### 3.3 工程实践博客 / 经验贴

| 来源 | 链接 |
|---|---|
| Anthropic — Code execution with MCP | https://www.anthropic.com/engineering/code-execution-with-mcp |
| Anthropic — Contextual Retrieval(-67% failure) | https://www.anthropic.com/news/contextual-retrieval |
| Anthropic — Advanced tool use | https://www.anthropic.com/engineering/advanced-tool-use |
| LlamaIndex — Router Query Engine | https://developers.llamaindex.ai/python/framework/module_guides/querying/router/ |
| Tavily — WebLangChain post-mortem | https://blog.tavily.com/building-and-breaking-weblangchain/ |
| Perplexity Computer 介绍 | https://www.perplexity.ai/hub/blog/introducing-perplexity-computer |
| AIMultiple — 8-API Agentic Search benchmark | https://aimultiple.com/agentic-search |

---

## 4. 商业 / 合规

### 4.1 API key 经济(免费 vs 付费源)

**对 coding 场景,80% 的核心源完全不需要 key**:

| 门槛 | 源 |
|---|---|
| **零 key,直接用** | GitHub(匿名 60/hr)/ arXiv / **OpenAlex**(UA+mailto: polite pool,~26 req/min)/ HN Algolia / Wikipedia / npm/PyPI/crates / Stack Exchange / DuckDuckGo 爬虫库 / Hugging Face Hub(只读)/ DeepWiki MCP |
| **免费 key,30 秒注册** | GitHub PAT(60→5000/hr)/ Brave(2k/月免费)/ Tavily(1k/月免费)/ Reddit OAuth / NVD / libraries.io |
| **结构性拒批 / 不可达** | ~~Semantic Scholar~~(2024-09 起拒收 free domain email + 第三方 app,见 §5.1 #20)|
| **付费才好用** | Exa / Serper / Linkup / Firecrawl |

→ "需要配 N 个 key" 的担忧被高估。**默认零 key 完整能跑,GitHub PAT 是唯一实质必需的升级**(其它 key 都是纯增益 buff)。**学术 vertical [2026-04-30 五] 已切到 OpenAlex,无 key 即可拿到比 S2 更广的字段**(见 §5.1 #20)。

### 4.2 爬虫合法性(给选型用的判断)

**通常合法的**:
- 爬公开页面、不绕过登录
- 遵守 robots.txt(礼仪非法律)
- 合理 rate limit(不构成 DOS)
- 在 User-Agent 注明身份

**通常不合法**:
- 绕过认证 / 付费墙(违反 CFAA 或类似)
- 违反 ToS 用于商业竞争(灰色)
- 转发盗用版权内容
- 极高频率致服务降级

**各源风险等级**:

| 源 | 风险 | 建议 |
|---|---|---|
| GitHub / SO / arXiv / HN | 低 | 用 API,SO 内容是 CC-BY-SA 可大量使用 |
| Reddit | 中 | API,非要爬就低速 |
| DuckDuckGo | 低-中 | 社区一直爬,不商用大规模 |
| Google / Bing SERP | **高** | **别自己爬,用 Serper/SerpAPI 转嫁** |
| X/Twitter / LinkedIn | **极高** | **别碰** |
| 各官方 docs / engineering blog | 极低 | 随便爬 |

**OSS 项目模板免责声明**:"This tool fetches public web content. Users are responsible for compliance with target sites' terms of service."

### 4.3 开源 vs 闭源 SaaS(对此项目)

**结论:开源压倒性合适**。理由:
1. 一个人扛不住 SaaS 的销售/客服/合规/SLA
2. 潜在用户(coding agent 开发者)是技术人群,**喜欢能看代码的工具**
3. 开源项目可以"半死不活"还有价值;闭源 SaaS 半死就死
4. 现在 dev tool 高 stars 几乎都开源(Aider/Continue/Cline/browser-use/LangChain)
5. 后期可走 **Plausible / Sentry / Supabase 模式**——开源核心 + hosted 服务变现

---

## 5. 我们做出的判断 + 反例

### 5.1 已经验证的判断(可作为后续决策锚点)

1. **不内置 LLM**——harness 是宿主 LLM 的工具,不要重复 LLM 能力
2. **Output 只给 citation,不做 synthesis**——synthesis 在 host(完整 user context)发生,损耗最小
3. **Flood + RRF 而非 routing**(at 4-6 源)——20 年 IR + 2024-2026 业界实证支持
4. **CLI + skills 而非 MCP server**(对我们 harness 自身)——Anthropic / Microsoft 自己的转向
5. **零 key 默认 + 渐进升级**——80% coding 场景免费源够用
6. **Browser 用 Playwright CLI 而非 browser-use**——4× token + Microsoft 维护 + host 主导决策
7. **Browser 不集成进 harness,co-install 推荐**——Microsoft 帮我们维护
8. **DeepWiki 等 AI 二级源直接白嫖**——别自己跑别人已经做过的 LLM 处理
9. **多模态分 5 Tier,buff 思路**——长尾价值不能用 ROI 均摊算
10. **开源,不闭源**——见 §4.3
11. **Adapter vs Skill 严格分边界**——adapter 只在 web_search 替代不了 ranking/字段时才写;只是"agent 不知道有这站"的问题用 skill 的 cross-reference 段解决。**结果**:Tier 1 收敛到 **15 个核心 ★ + 4 个 ◇ Phase 2 opt-in**([2026-04-26] 可选 adapter 全部纳入到 23 → **[2026-04-29 一] PwC 死 drop** → **[2026-04-29 二] Conda /search spam drop + ProductHunt OAuth 重 drop + RubyGems/NuGet/Hex/CRAN 降 Phase 2** → **[2026-04-30 三] pkg.go.dev 无 native JSON API drop** → **[2026-04-30 五] #7 S2 → OpenAlex 替换**(S2 key 结构性拒批))。数十个 site 转 skill-only,见 `adapter-vs-skill.md`(已合并废弃) + `adapter-empirical-test-report.md`(已合并废弃)
12. **三源吸收工程纪律**——DeerFlow 提供工程骨架(provider 抽象、reflection、boundary、lazy init、Pydantic 全栈、trace_id),gstack/superpowers 提供 skill 写作纪律(命令式语气、verifiable 步骤、reject slop 文化),gbrain 提供 "fat skills" prompt 强度。**三者综合,而非单一参考**(见 §1.8 + architecture.md §11)
13. **防偷懒主要靠 skill prompt**——DeerFlow 实证:防过度行动靠 LoopDetection 中间件,**防"做得不够"主要靠 skill 文件里的 imperative prompt**。研究质量分水岭在 skill 文本如何写,不是代码逻辑(见 §2.10.2)
14. **GitHub 检索能力实测结论 [2026-04-26]**——同一道 repo-discovery 题(`Rust full-text search engine library`)并行打了 GitHub API / Sourcegraph 匿名 / grep.app / searchcode.com / DeepWiki MCP,再做 SG 免费匿名层 vs GH+PAT 5 任务 head-to-head 对比。建设性结论:
    - **不存在"GitHub 检索 SOTA"产品**——能力按 4 档(词法 / 语义 / 符号 / 仓 Q&A)分散在不同栈,任一单引擎都漏头部答案。**meilisearch(50k+ stars)在 GH 和 SG 关键词搜索都没进 top 10**,因为它描述写"search API"不是"library";纯词法 AND 匹配从底层够不到措辞差异——这是任何"基于 description"的引擎的通病
    - **GitHub PAT 从"推荐升级"升为实质必需**——匿名 code search 直接 401,architecture.md §3.2 / §7 的措辞要相应改
    - **Sourcegraph 免费匿名层只剩 3 个 niche 价值**(进 skill imperative,不进 adapter):
      - `type:symbol` 跨仓符号搜索(带 kind/containerName/行号,GH 无对应原语)
      - `type:commit` / `type:diff` + `after:` `before:` `author:`(GH gh CLI 也能但语法分裂)
      - `repo:has.file(path:X content:Y) select:repo` 反查依赖(独家)
    - **SG 工程坑**:杀手锏 structural search 在免费层 shard timeout 静默失败(实测 60s 0 结果),误以为可用反而踩坑;`repo:has.meta(stars)` 是 enterprise-only;GraphQL anon 硬封顶 30 必须用 stream API(`/.api/search/stream`);**要主动检查 `progress.skipped[reason=shard-timeout]`**,否则会无声漏 torvalds/linux 这种大库;覆盖偏 GitHub,Codeberg/forgejo 不指望
    - **grep.app + searchcode.com 双双对 agent 失效**——前者被 Vercel Turnstile 反爬墙隔离 plain HTTP 完全打不通,得 Playwright 解 challenge;后者 legacy API 已 404 下线,转付费 MCP。**两者从 sources.md §1.2 直接 drop**
    - **DeepWiki 严格定位"orient,不 cite"**——LLM-on-RAG 不稳定是通病(生成温度 + 检索 tie-breaker + 缓存 TTL + index 增量重建 4 层叠加),不是 DeepWiki 单家做不好。精确 API 签名 / 行号 / license 必须回 GitHub raw API,不走任何生成式管道
    - **真正的工程杠杆**(任何检索引擎都解决不了,只能在我们这层做):
      - skill 层强制 query rewriting:`library` 这种缩窄词要扩成 `(library OR engine OR backend OR crate OR sdk)`——实测把 GH 命中从 41 砍到 3 的元凶就是这一个词
      - skill 层强制 multi-source fusion + **社区 sentiment cross-ref**(HN/Reddit/掘金/Zenn 的 `site:`)——补"description-keyword 漏大鱼"的唯一便宜手段
      - adapter 层把 `progress.skipped` 等 silent-failure 字段当一等公民,纳入 result-quality 信号
    - **元教训**:**"SOTA" 是营销词,不是工程词**——这个领域产品迭代极快(grep.app 半年内被反爬墙、searchcode 转付费、SG 转 fair-source),凡判断"X 是 SOTA"必须实测,文档过期速度按月算
    - **待落变更**:architecture.md §3.2 / §7 改 PAT 措辞;sources.md §1.2 drop grep.app + searchcode.com;adapter-vs-skill.md §5.1 把 SG 的 skill 教法从"模糊跨仓代码搜索"改成 3 条具体 niche imperative

15. **22 adapter 实测全量验证 [2026-04-29]**——把 §5.1 #11 锁定的 23 个 ★ adapter 分 6 类目(Repo/Q&A/学术/主流PM/小众PM/特殊),并行 6 subagent 各自跑 instant + long-tail query 真接 API,产出 `adapter-empirical-test-report.md`(已合并废弃)。建设性结论:
    - **Papers with Code 已死** — 域名 302 全跳到 `huggingface.co/papers/trending`,`/api/v1/*` 全 404。Phase 1 23 → 22。这是 §5.1 #11 决议后第一次"必做 scope 缩减",也是文档**至少需要季度复测**的实证(产品死亡按月算)
    - **`api.deps.dev`(Google Open Source Insights)浮现为隐藏主角** — pkg.go.dev `/api/v1/*` 全返 HTML 是死胡同,Go/Maven/PyPI 的 license + version metadata 真路径在 deps.dev。**Phase 1 后期或 Phase 2 考虑作为 cross-cut helper**(类似 libraries.io 角色,服务多 PM adapter 内部 fallback)。这是新发现的"白嫖大厂 metadata 后端"案例,符合 §8 元规则 #3
    - **"无搜索 API" 三家**(PyPI / Maven / pkg.go.dev)长尾发现完全依赖 libraries.io。**libraries.io 不是"兜底"而是"结构性必需"**。同时 libraries.io 实测仍活着(数据 2026-03 新鲜),package-detail 端点匿名可用,`/search` 需 30s key — **混合 auth 双层** 现实要写进 adapter
    - **GitHub PAT + S2 key 升为实质必需**(同 §5.1 #14 GitHub PAT 结论一致,S2 是新发现):S2 匿名 burst 即触发 429。零配置叙事不能装作没这层成本——architecture.md §3.2 / §7 已改
    - **三家"零下载量"包管理器**(PyPI / Maven / CRAN)+ Conda `/search` 充斥镜像 spam(实测 `jjhelmus/_pytorch_select` 这种)— 这一组的长尾全部需要外部数据源(libraries.io / cranlogs / 频道白名单)。**没有原生 popularity 信号 = 长尾必须兜底**,不是可选
    - **多实例 / 多站点 adapter 隐藏成本对称**:SE 一份代码 5 站(SO/DBA/SF/CR/AI.SE)= 正向规模效应;GitLab 多实例(.com / .gnome.org / .freedesktop.org)+ N+1 license 调用 = 负向规模成本。设计前要分清
    - **匿名能用 vs 匿名跑得动**:13/22 adapter 完全匿名可用,但 GitHub / S2 / Reddit 三家"匿名跑得动但要立刻配 key"——零配置叙事要诚实,**不能装作 GitHub PAT 是 optional**
    - **元教训**(同 §5.1 #14):"有 API 文档不等于有 API"—— pkg.go.dev `/api/v1/*` 是教科书反例(网页明文列着,实测全返 HTML)。**永远 curl 真接,别只读 docs**;adapter scope 文档**至少季度复测**

16. **Adapter 真价值在跨源中间层,不在 per-source 代码 [2026-04-29]**——22 source 实测后用户提的尖锐问题:"我看你调用都很简单,那这种 adapter 是不是可以完全 skills 化?" 推动梳理三档架构(adapter-heavy / config-driven engine / pure skill)和 7 项跨源中间层职责(fan-out / RRF / dedup / schema 归一 / cache / error / rate-limit)。**结论框架** 见 §2.11。**核心认识**:
    - per-source 调用的确简单(≈10 行 bash),为每个 source 写一份 Python 类是过度工程
    - adapter 的真价值在 **7 项跨源中间层**——这部分必须 core 代码,不是 skill 能省的
    - pure-skill 模式让 raw API JSON(每 source ~30KB)灌进 LLM context,**反向打 §2.5 的 token 经济** —— 死因不是工程口味,是数学
    - 推荐**档 2 config-driven**:1 个 SearchEngine core + 19 个 YAML config,~1-2K LoC,加 source = 加 config 文件 + 0 代码
    - **§2.9 的 source-级决议(22 个进 Tier 1)不变,实施形态从 "19 Python 类" 降级为 "19 YAML config"**
    - **实施决定状态**:架构层认知已对齐,具体落 architecture.md §3.10 / §6.1 重写后 commit(待拍板)

17. **Tier 4(find-talk)实施路径锁定到 invidious `/api/v1` [2026-04-30]**——读 GitHub trending 5 项目分析后,发现 invidious 报告里 §7 明示 `/api/v1` 是 "当前性价比最高的无密钥 YouTube API",FreeTube/LibreTube 已把它当事实标准依赖。建设性结论:
    - **Tier 4 不是技术难,是"找对中间件"难** —— invidious + Companion 二元架构(主仓库 + Deno/TS 反爬 sidecar)已经在 fight YouTube 的反爬升级,2024-2025 期间 Piped / yt-dlp / NewPipe 都遭周期性"血洗",**自己写 youtube-transcript-fetcher 6 个月内必崩**
    - **find-talk vertical 实施 = 三层 fallback**:Layer 1 公共 invidious 实例池(`docs.invidious.io/instances/`)+ multi-instance round-robin + 健康检查;Layer 2 用户 self-host invidious + companion(docker-compose 一行起);Layer 3 yt-dlp CLI 兜底
    - **关键 endpoints**:`/api/v1/search?q=...&type=video`、`/api/v1/captions/<videoId>`(transcript)、`/api/v1/videos/<videoId>` —— 全部 anon、零 key、JSON
    - **范畴**:不进 Phase 1 ★ 16 adapter scope(那是 Tier 1);**是 Tier 4 的实施 anchor**;启动时机仍可放 Phase 2,但实施门槛大幅下降
    - **元洞察**:invidious + Companion 是 architecture.md §3.7 "co-install 而非 bundle" + §11.4 "single binary" 哲学的实证案例 —— 别人帮我们维护脏活,两层间接但每层都已稳定运营。这是"白嫖大厂中间件"原则的另一个支柱
    - **⚠️ [2026-05-02 推翻]** 实测公共 invidious 实例池基本塌——`api.invidious.io/instances.json` 只列 1 个 active 实例,实测 `inv.nadeko.net` HTTP 403(Cloudflare 拦)。Layer 1 + Layer 2 都不实用。**Layer 3 yt-dlp 实测全 ✓**:`yt-dlp "ytsearch5:..."` 搜索 / `--dump-single-json` 元数据(view/like/upload + 160 种 caption)/ `--write-auto-sub --sub-format vtt` transcript 三件套全工作,brew/pip 一行装,**无 docker 无 instance 池**。**sources.md §2 已切换 invidious docker → yt-dlp CLI**。原"三层 fallback"折叠为"yt-dlp 单层"——同时 yt-dlp 还覆盖 1000+ 视频站(不只 YouTube),价值更广。元教训同 §5.1 #14:**任何中间件方案都要季度复测,公共实例池死亡按月计**

18. **"API 无建设性数据" 标准应用 → pkg.go.dev 降为 skill [2026-04-30 三]**——用户提"API没有返回建设性数据的放到 skills 分类里面"。逐项重审 16 ★ + 4 ◇ adapter,只有 **pkg.go.dev** 严格命中(`/api/v1/*` 全返 HTML,native JSON API 不存在;所谓 "pkg.go.dev adapter" 一直是 deps.dev wrapper 的 mislabeling)。**Phase 1 16 → 15 ★**。Go packages 改走 §5.1 skill imperative 直查 `https://api.deps.dev/v3/systems/go/packages/<encoded-path>`,长尾排序经 GitHub stars(deps.dev project 带 `SOURCE_REPO` link 二次调 GitHub adapter)。
    - **PyPI / Maven 边缘但保留**:都返了一些 deps.dev 没有的 native 字段(PyPI 的 `classifiers` + `requires_python`;Maven 的 `versionCount` + GAV 时间线)。判定为"弱但非零 constructive data",保留 adapter
    - **⚠️ [2026-05-01 二] 此判定已推翻**——用户指出"必做还有那么多 PM only 无信号的东西呢" 触发标准对齐审视:`classifiers / requires_python / GAV timestamp` 是 metadata 不是 ranking 信号,与 [2026-04-30 三] pkg.go.dev 降级标准完全同构。**PyPI / Maven Central 同降 skill imperative**,native metadata 走 skill 直查 `pypi.org/pypi/<pkg>/json` + `search.maven.org/solrsearch`,ranking + license 走 `api.deps.dev` + `libraries.io`(同 Go 路径)。Phase 1 ★ 15 → 13。详见 sources.md drop list + 本文档 §5.1 #23(`adapter-vs-skill.md` 已合并废弃)
    - **元洞察**:这是 §2.9 决策树的反向应用 —— Q1(web_search 能找到吗?能,通过 deps.dev)+ Q2(能拿到 ranking 信号吗?deps.dev 自己也没 popularity)+ Q3(已是免费 MCP 吗?api.deps.dev 是 Google 公开 API,等同 "third-party 替我们维护")→ **adapter 不该写,skill imperative 教 agent 直调即可**
    - **副效应**:用户的"API 没有返回建设性数据 → skill"标准比 §2.9 决策树更尖锐——decision tree 看的是"web_search 能不能拿到",新标准看的是"native API 自己有没有"。**两个标准互补**,前者管 source-level 边界,后者管 implementation-level 健全

19. **last30days-skill (24k★) + Agent-Reach (18k★) 实测分析:thin-skill / OSS-wrapper 两条路线在我们象限之外 [2026-04-30 四]**——用户问"Reddit 读取在 GitHub 社区有没有比较好的实现",顺势调研到这两个高 star 项目并 clone 实测(`/tmp/last30days-skill` + `/tmp/agent-reach`)。建设性结论:
    - **last30days-skill 不是竞品,是 thin-skill 路线的事实样板**——它做 **synthesis**(brief writing + Best Takes 双判官 + cluster merging),我们做 **structured citations**(no synthesis,§3.5)。**两者位于不同 Tier,可 co-install 并存**:用户用我们 harness 做底层检索,用 last30days 做上层 brief 写作
    - **Agent-Reach 是平台覆盖广度路线**(16+ platform reader,Wraps yt-dlp / Jina / rdt-cli);我们是 ranking 信号深度路线(stars / votes / citations / downloads)。**重心维度不同,不冲突**
    - **5 条可借鉴的工程模式**(暂记录,待落地决定):
        - **last30days pre-resolver Python brain**(@j-sperling 写)——entity resolution(`/last30days OpenClaw` → `@steipete + r/openclaw + r/ClaudeCode + YT channel + TikTok hashtag`)在 fan-out 前完成。**§3.4 heuristic gate 的进阶设计参考**,值得加进 §10 未决问题
        - **last30days 双判官**(relevance + wit/virality 第二维度)——架构上不直接抄(我们 §3.5 不做 synthesis),但**思路可移植到 RRF fusion 之上加一层 secondary ranking signal**(如 freshness / authority);search-discuss skill imperative 可借鉴
        - **Agent-Reach `doctor` 自诊命令**——`agent-reach doctor` 一行查所有 source 健康 + 配置缺失。**`search-harness doctor` 是 §11.4 工程纪律应加的一条**
        - **Agent-Reach CN 平台覆盖**(小红书/B 站/微博/V2EX/雪球/小宇宙/抖音/微信公众号)——我们 sources.md 完全空白。**针对 CN 用户群可 co-install Agent-Reach**(类似 invidious sidecar 模式,§4 Co-install MCP 候选)
        - **Agent-Reach OSS-wrapper 哲学**(yt-dlp / Jina / rdt-cli 全部不重新发明,只 wrap)——和我们 §3.7 "co-install 不 bundle" + §11.4 "single binary" 完全对齐,**是个外部验证而非新动作**
    - **元洞察:真正威胁不在这两个,在 Anthropic 自己**——如果 Claude Code default 把"cross-source research skill"做进 plugin,search-discuss skill 会被 commodity 化;**但 find-repo / ground-api / search-paper 这些带 ranking 信号的垂直 vertical 仍是 Anthropic 不会做的、有结构 moat 的事**。我们的差异化必须押在"垂直 ranking 信号深度",不是"平台覆盖广度"或"上层 synthesis"
    - **意外发现:Reddit 的实际可用方案**——last30days 和 Agent-Reach 都用 wrapper 路线(后者直接调 `rdt-cli`),没人写自己的 PRAW + OAuth adapter。**我们 Phase 1 #5 Reddit adapter 也应该 wrap 现成的 reddit-mcp-buddy(630★)而非自实现**(待 §1.6 / §4 决策)
    - **`reddit-mcp-buddy` 深度实测 [2026-04-30 四]**(`/tmp/reddit-mcp-test/client.py` Python MCP stdio client,5 个 tool 调用,全 200):
        - **数据质量 EXCELLENT**:`search_reddit "rust async runtime"` 返 score=913 / upvote_ratio=0.89 / num_comments=382 / link_flair_text="💡 ideas & proposals" / created_utc / 全部 LLM-friendly 结构化字段
        - **加值亮点:`insight` 字段是 mcp-buddy 自加工的 LLM 语义标签**(`👮 Official post` / `🔥 Controversial - high discussion ratio`)——不是 Reddit API 原生字段,是 server 端基于 score+comments+ratio 算出的语义标注。**这是 MCP 加值的范例,值得抄进我们 SearchCandidate schema**
        - **警告 ①:`content` 字段返完整正文**(一条 search 结果 1500+ chars,3 条 ~5K chars)——**与我们 §11 "索引+snippet,全文落 disk" 契约冲突**。skill imperative 要教 host"先看 score/title 再决定是否 read content"
        - **警告 ②:Reddit search 是 keyword match 非 semantic**——查 "clickhouse vs duckdb" 命中无关帖子(正文提到 duckdb 即可)。**这是 Reddit 平台限制,不是 mcp-buddy 问题**;`search-discuss` skill 必须显式告知 host 措辞尖锐 + 二次过滤
        - **Anon 限流实测**:30s 内 4 个 tool calls 全 200,**没碰 429**。匿名 10 req/min 对单次 fan-out(4-6 source 一次)够用,**问题在连续多轮 burst**(才需 OAuth 上 60-100 req/min)
        - **修正前一轮 scope 建议**:从"建议推荐"升为"**强烈推荐 co-install**";Phase 1 #5 Reddit adapter 改为 §4 Co-install MCP 表条目,与 invidious / DeepWiki 同档

20. **#7 Semantic Scholar → OpenAlex 替换 [2026-04-30 五]**——用户提"Semantic Scholar 的 key 很难申请啊 有没有社区解决方案"。调研 + 实测后建设性结论:
    - **S2 key 不是"难申请",是结构性拒批**:[`@SemanticScholar 2024-09 X 推文`](https://x.com/SemanticScholar/status/1834334430237958546)官方明确"no longer accept API key requests from **free domain email addresses** / no longer approving key requests for **third-party apps**"——Gmail/Outlook 邮箱拒,"build third-party tool"用例拒。**对我们 OSS 项目和大多数普通用户路径完全堵死**
    - **OpenAlex 是干净的全替代**——Allen AI 系外的独立项目(原 Microsoft Academic Graph 接班),250M+ works,完全无 key,UA 加 `mailto:` 进 polite pool 即可,实测 ~26 req/min 稳定(对比 S2 anon ~1 req/sec burst-fragile)
    - **OpenAlex 字段实测比 S2 更广**(50+ 字段 vs S2 ~30):
        - `cited_by_count`(等同 S2 `citationCount`)
        - **`fwci`** Field-Weighted Citation Impact(等同 S2 `influentialCitationCount` 的同档信号)
        - **`citation_normalized_percentile.is_in_top_1_percent` boolean**(LLM 友好度强于 raw count)
        - `referenced_works[]`(引用图遍历,等同 S2 `/references`)
        - `concepts` 5 级 taxonomy(S2 没有)
        - `counts_by_year` 引用时间线(S2 没有)
        - `is_retracted` 撤稿警告(S2 没有)
        - `has_fulltext` / `open_access.is_oa`
    - **实测 anon 限流真相**:`x-ratelimit-limit: 10000` per `x-ratelimit-reset: 22592` 秒(~6.3 小时)= **~1587 req/h ≈ 26 req/min 稳定**;S2 anon 的 burst 即 429 体验完全消失
    - **trade-off 诚实说**:OpenAlex 对 AIAYN 的 `cited_by_count` 是 6530,S2 是 174k——索引覆盖不同导致绝对数差距大,**但 ranking 信号(percentile / fwci)仍正确反映影响力**(AIAYN 在 OpenAlex `is_in_top_1_percent: true`)
    - **S2 处理**:降级到 §5.1 skill cross-reference,**给已有 .edu 邮箱 + 已申请到 key 的用户**保留作 OpenAlex `fwci` 的二次验证,不是默认路径
    - **元洞察**:这是 §5.1 #11 决策树的活案例——一个 Phase 1 ★ adapter 从"key 强推 prerequisite"降级为"对 OSS 项目结构性不可达",触发**整体替换**而不是修补。**adapter scope 文档至少季度复测**(同 §5.1 #14 元教训)再次得到验证

21. **X 三方数据通道实测,economics 颠覆 + xAI 单位实证 [2026-04-30]**——把同一 customer-agent query(`Intercom Fin OR Decagon OR Sierra customer service AI`)并行打到 X 官方 PPU / twitterapi.io / xAI Grok X Search,对照三家 dashboard 真实费用数据,产出 `runs/{x-api,xai-x-search,twitterapi-io}/2026-04-30T*_intercom-fin-decagon-sierra.json`。建设性结论(详见 §1.5.1):
    - **真实 cost(三家 dashboard 实数据)**:
        - **X 官方 PPU**:$0.10 / 20 posts(2 calls 跨 Apr 30 + May 1)= $0.05/10-post call,与标价 $0.005/read 完全吻合
        - **twitterapi.io**:2 calls 消耗 600 credits / 10000 starter(剩 9400),~$0.06 等值;starter bonus 6/1/2026 过期
        - **xAI**:prepaid $5.00 → 剩 $4.97 → **单次 grok-4.20-reasoning + 5 内部 X Search 全包 $0.03**,产出 5 点结构化分析 + 16 citations
    - **economics 颠覆**:**xAI X Search 单次 $0.03 比 X 官方 API 单次 $0.05 还便宜** → 前一日"$0.56 / call"估算高估 18×(进 §5.2)。"premium LLM-mediated fallback" 框架被推翻——one-shot 分析场景下 xAI 是性价比最高的选择,不是兜底
    - **三种正确用法**(从 economics 反推):
        - **raw 数据入库** → twitterapi.io($0.15/1K bulk),Top mode 天然过滤噪声,字段比 X 官方更全(`viewCount` + `isBlueVerified` + 完整 author profile)
        - **one-shot LLM-mediated 分析** → xAI X Search,**不用经"X API + 自家 LLM"两步走**,Grok 后端可能享 X 内部数据通道
        - **合规背书 / 法务必需** → X 官方 PPU,**仅此场景**;两端非最优
    - **xAI `usage.cost_in_usd_ticks` 单位实证**:`564,020,500 ticks → $0.03` → **1 tick ≈ $5.3×10⁻¹¹** ≈ **1 USD = 188 亿 ticks**。docs 没写,生产必须知道
    - **reasoning 模型多搜索特性**:grok-4.20-reasoning 单次 prompt 自动发起 **5 次 X Search**(`usage.server_side_tool_usage_details.x_search_calls=5`)。**budget hook 计数应跨 reasoning 步骤**(配 §2.12.4 hook 配方),不能假定"1 prompt = 1 tool call"
    - **未决:多源融合时的 economics**:本次只测了"单次 query 三方各跑一次"。**实际 search-agent 用 fan-out + RRF 融合**,xAI X Search 输出已是 prose 不能直接入 RRF;真问题是"同一 query 是否同时调 twitterapi.io(raw 入库)+ xAI(synthesis)?"——待 §5.3 router 设计回答
    - **元教训**:
        - **任何成本估算未实测前都打折看**——前一日 $0.56 vs 实测 $0.03 差 18×,完全推翻架构定位。**永远 dashboard 实数据 > 文档 / 推算**(同 §5.1 #14/#15 元教训)
        - **bonus credits 让 raw 路径压力为零**:twitterapi.io 10K credits = ~$0.10 等值 = 半月白测;vendor 的"上瘾陷阱"反向是我们做实证的福利
        - **永远问 vendor 的内部计费单位**:cost_in_usd_ticks 这种字段不实测就当陷阱(数量级歧义可达 100×)

22. **grok-cli 深度反编译 + twitterapi.io 全 endpoint 探索 [2026-05-01]**——为对比 fat-harness 路线 + 完成项目级 skill,把 `grok-dev@1.1.5` 项目本地装到 `tools/grok-cli/`,扒了 dist/ 全 519 文件 + 70MB 编译二进制,同时实测 twitterapi.io 5 个 endpoint 摸 schema。建设性结论分两条线:

    **A. grok-cli 架构(直接对手实证)**

    - **完全的 fat-harness 反例**:dist/ 16 个子系统包括 telegram (58 文件) / iMessage (21) / Coinbase x402 wallet+payments (21+6) / 音频 STT(whisper-cpp + grok-stt) / 桌面控制(11+ computer_* 工具) / 图像视频生成 / scheduler daemon / LSP server / React 终端 UI(@opentui/core)。**与我们(及 Claude Code)的"thin harness, fat skills"路线完全相反**。这是 §1.8 共同体之外的另一极:**Codex/grok-cli 押"all-in-one agent platform"**
    - **hook 系统比 Claude Code 更丰富**:17 个事件 vs Claude Code 的 9 个。**新增的 8 个**:`PostToolUseFailure`(成功失败分流)、`StopFailure`、`SubagentStart`(Claude Code 只有 stop)、`TaskCreated/TaskCompleted`(明确生命周期)、`PostCompact`(Claude Code 只有 PreCompact)、`InstructionsLoaded`、`CwdChanged`。对 §2.12 配方设计:**事件分流粒度更细 = 预算/质量约束更精准**(失败有专属事件,不必和成功路径同 hook 处理)
    - **关键安全模型差异**:grok-cli **拒绝 project-level hooks**——只读 `~/.grok/user-settings.json`。源码 comment 明示:"a malicious repository could execute arbitrary unsandboxed commands on a developer's machine via hook definitions"。**意味着我们 §2.12.4 的 `.claude/settings.json` hook 配方在 grok-cli host 上完全不可用**。**架构含义**:hooks 不可跨 host portable,如果未来要支持 grok-cli host,**预算/约束逻辑必须下沉到 adapter 层**(用户级 hooks 不是产品分发可控的)
    - **`search_x` 是二级 LLM 包装,不是 passthrough**——这是本次最关键的反编译发现。源码 `dist/grok/tools.js`:
        ```js
        const RESPONSES_SEARCH_MODEL = "grok-4-1-fast-non-reasoning";
        const runResponsesSearch = async (query, toolName) => {
          const { text } = await generateText({
            model: provider.responses(RESPONSES_SEARCH_MODEL),
            tools: { x_search: provider.tools.xSearch() },
          });
          return text;
        };
        ```
        即:agent 调一次 `search_x` → 触发一次 `grok-4-1-fast-non-reasoning` 的 sub-LLM 调用 → 后者再调用 N 次 xAI server-side `x_search` 工具。**这解释了 §5.1 #21 中 grok-cli 实测 10 search_x calls vs 直 API 5 calls 的差异**——不是模型更勤奋,是**架构上有 1×→N× 的二级放大**。**成本模型须改写**:1 agent search_x 不是"1 次 $5/1K calls",而是"sub-LLM tokens + N × $5/1K calls",N 实测约 1-2
    - **subagent 系统更保守**:只有一个 agent type(`"explore"`),vs Claude Code 的 14+ 种。但**结构性预算嵌入**:`StoredDelegation` 内置 `maxToolRounds` + `maxTokens` + `sandboxMode` + `batchApi` 字段。**这是 hook 之外的"另一种约束工程"** —— 把预算上限做进 schema 而不是 prompt
    - **Hook block 返回模式可抄**:被拦的 tool 调用返回 `{ success: false, output: "[Hook blocked] ${reason}" }` 给 LLM,**不抛异常**。**好实践,值得我们 §2.12.4 的 hook 设计抄过来** —— 模型看到结构化失败 + 明确原因比看到 stack trace replan 质量高
    - **`AGENTS.md` not `CLAUDE.md`**:grok-cli 走 OpenAI/Codex/Cursor 那套 emerging standard。**层级加载**:`~/.grok/AGENTS.md`(全局)→ git root 走到 cwd 沿途每层 AGENTS.md。**支持 `AGENTS.override.md` 替换父级**(vs 默认累加)——Claude Code 的 CLAUDE.md 没这个语义。**对 search-agent**:若想跨 host 中立,等于得双备份;**项目 commit 用 CLAUDE.md(我们用),AGENTS.md 视情符号链接**

    **B. twitterapi.io endpoint 全测**

    - **实测 endpoints**:`advanced_search` ✓ / `user/info` ✓ / `user/last_tweets` ✓ / `tweet/replies` ✓
    - **关键 free-tier 限制**:**1 req per 5 seconds**(实测 429 message 原文:"For free-tier users, the QPS limit is one request every 5 seconds")。**docs 标榜的 200 QPS / client 是付费层**,免费层实际 0.2 QPS,12 req/min 上限。**对 fan-out 模式的影响**:并行多 endpoint 调用 free tier 不可用,要 sleep 5s 串行,或合并到 advanced_search 一次拿够
    - **隐藏高价值字段**:
        - `user/info.pinnedTweetIds[0]` = 用户自选 canonical post —— **entity resolution 单点最高信号**
        - `user/last_tweets.data.pin_tweet` = 同上但带完整 tweet 对象 —— 免一次额外调用
        - `tweet/replies.replies[]` = sentiment 金矿(质疑 / 验证 / 共鸣)—— **纯 search 拿不到**(search 命中的是发推方,replies 才是观众反应)
    - **schema 文档误导 1 处**:`user/last_tweets` 的 `data` **是 object 不是 array**(`{pin_tweet, tweets[]}`)。看 docs 写代码会跑空,实测才知道
    - **架构含义**:project-level skill `.claude/skills/twitterapi-io/SKILL.md` 现在含完整 endpoint 表 + 5/s QPS 警告 + schema 修正 + 高价值字段强调,可作为**首个完整 source skill 的范例**——尺寸 ~7K,密度高,imperative,无 slop。**这是"thin harness, fat skills"在 source 层的实证**

    **元洞察(贯穿 A + B)**:
    - **生产级 agent harness 路线分两极**:thin(Claude Code / 我们)押**协议中性 + skill 为最小可复用单元**;fat(grok-cli / Codex)押**所有能力一站式 bundled**。**两条路线都活,但 distribution + 合规边界完全不同** —— grok-cli 这种把 Coinbase x402 / Telegram remote / iMessage 全 bundle 的产品在企业合规白名单审批上几乎不可能过,而 thin harness 的工具/skill 可逐项授权
    - **反编译装好的对手 = 极高 ROI**:7 分钟 npm install + 30 分钟扒源码(dist/agent/, dist/hooks/, dist/grok/tools.js)拿到的架构知识,比读 README + blog 30 篇都密。**元规则补一条**:**competitor 的 npm/pypi 包是低成本侦察源**,只要他们 ship dist/(几乎都 ship)
    - **跨 host portability 不是"理想",是 explicit 取舍**:hooks(Claude Code 项目级 vs grok-cli 仅用户级)、instructions 文件名(CLAUDE.md vs AGENTS.md)、subagent 类型(开放 vs 单 explore)三处不可调和。**我们 search-agent 现阶段押 Claude Code,这没错;但需要明确**"AGENTS.md / 用户级 hooks 兜底"作为 backup distribution path,留给未来看(进 §5.3 开放问题)

23. **MCP→CLI 全面切换 + sources.md 演化到 20★ + Stainless / OpenAPI 现实 + 三层蒸馏工具栈实证 [2026-05-01 → 02]**——一周内多轮 push 把 sources.md 从 14 ★ 演到 20 ★ + 折叠 / 重写 / 实证多个工具决策。建设性结论:

    **A. MCP→CLI 全面切换**
    - 装了 5 个 MCP 又卸 4 个:Sentry(用户自家 deployment 不是 source)、github-official(token 4-32× 浪费 / 72% 成功率 / 41 工具 schema 立即占 context)、playwright(MCP 4× token vs CLI)、sourcegraph(anon stream API + free PAT 实测命中数 1:1 → free PAT 在 search 上无优势,MCP 多余)
    - **唯一保留的 MCP**:DeepWiki(无 CLI 替代,服务端 AI wiki + 3 工具 schema 小,token 损失可接受)
    - Context7 切到 CLI 形态(`npm install -g ctx7`),实测 token 4-32× 优化 + skill mode 触发率 98%(Upstash 自家 benchmark)
    - **元规则补 §8 #11**:**MCP 仅作"无 CLI 替代且工具 schema <5"的例外**,默认 CLI 优先

    **B. invidious docker → yt-dlp**
    - 实测 `api.invidious.io/instances.json` 只列 1 active 实例,`inv.nadeko.net` HTTP 403(Cloudflare 拦),Layer 1 公共池实质塌
    - Layer 2 self-host docker-compose 维护成本高
    - **Layer 3 yt-dlp brew 一行装** + search/`--dump-single-json`/`--write-auto-sub --sub-format vtt` 三件套全工作 + 1000+ 视频站不只 YouTube
    - **§5.1 #17 Tier 4 路径全推翻**:折叠为 yt-dlp 单层,docker 路线弃用

    **C. sources.md 新增 source 实证(20 ★)**
    - **#18 Bluesky** authed:`searchPosts` anon **403**(compass artifact 假设部分失效,需注册账号 + app password)→ `createSession` 拿 accessJwt → searchPosts 200,实测 5 连发无 429,**rate limit 远好于 twitterapi.io 1/5s**;AI/Rust core 已迁(Simon Willison / Anthropic / HF / Rust core)。twitterapi.io #14 仍保留(中文圈 / pinnedTweetIds 等 X-only 字段)
    - **#19 Sourcegraph stream**:anon `https://sourcegraph.com/.api/search/stream?q=context:global+...` 直接可用,event-stream 形态,跨 2M+ OSS repo trigram + facet(`repo:has.topic` / `lang:` / `type:symbol`)+ commit SHA + lineNumber。**PAT vs anon 实测命中 1:1**(`Rust+tokio` query),free PAT 在 search 上无功能加成,**stream API anon 即可**
    - **#20 Exa**:实测三独家能力全 ✓:**`outputSchema` 结构化 + 8 字段 grounding citations**($0.007 / 5 hits)、**`/contents` URL → 干净 markdown**($0.001 / URL,SPA Anthropic blog 完美抓 SWE-bench 数字 + 价格 + Cursor 引用)、**`type:deep` multi-hop**($0.012,补 BP §6 pricing 轴)。三种集成方式(REST / MCP / Anthropic tool calling),我们用 REST(token 0 预占)
    - **架构含义**:§1 从 14 ★ 到 20 ★,信号源全覆盖(Repo/QA/学术/PM/AI/Vuln/Social/Code-search/通用 web)

    **D. 三层 docs 蒸馏工具栈实证**
    - **类 1 预蒸馏 SaaS**(Context7 / Ref.tools $9/1000q vs Context7 $10/500q / Deepcon 90% vs Context7 65% / DeepWiki / GitMCP 读 llms.txt)
    - **类 2 OpenAPI → SKILL.md 自动生成**(neutree-ai/openapi-to-skills v0.3.0 ✓ 实测,petstore → 19 ops + 171 文件 progressive disclosure;OpenAI Stainless YAML → 241 ops + 1369 文件)
    - **类 3 通用 web → markdown**:
        - **Firecrawl**(AGPL-3.0 OSS 113k★ + SaaS):**SPA 之王**,Anthropic Mintlify SPA → 478KB 完整 API schema(B Jina 同 URL timeout)、deps.dev docs → 1.3KB 干净
        - **Jina Reader**(零 key):静态站完美(RFC 7231 → 200KB 完整),**SPA 风险**(同 URL 一次 ✓ 一次 timeout)
        - **Crawl4AI**(本地 OSS,Playwright 后端,免费)— 候选,未实测
    - **§3 sources.md 升级**:从一段空表升级为 4 行表(Context7 / Jina / Firecrawl / openapi-to-skills),覆盖输入形态全谱(主流库 / 静态 URL / SPA / OpenAPI YAML)〔→ #24 复测后 openapi-to-skills 删除,回 3 行〕

    **E. Stainless 画像 + OpenAI canonical 在 SaaS 上的现实**
    - OpenAI canonical OpenAPI YAML **已迁出 GitHub**:`app.stainless.com/api/spec/documented/openai/openapi.documented.yml`(2.6MB / OpenAPI 3.1 / 241 operations / 151 schemas),master branch 只剩 LICENSE+README 指 Stainless
    - Stainless 客户:**OpenAI / Anthropic / Cloudflare / Google**(LLM 顶级 vendor 全包),价格 $250/月/SDK,team 来自 Stripe/Heroku/Twilio
    - **三件套**:OpenAPI YAML → SDK(7-9 语言)+ Docs Platform(Astro)+ MCP Servers(自动生成给 Claude/Cursor)
    - **OSS 工具可白嫖**:`mcp-front`(44★ Apache,MCP server auth proxy)、`stl-api`(157★ TS framework)
    - **元洞察**:**vendor 维护 spec → Stainless / Speakeasy / Fern 等 SaaS 平台做 SDK + docs + MCP/skill 适配 → host 端再适配** 是 2026 三层产业链。**vendor 不发 SKILL.md 而发 OpenAPI 是结构性合理**(SKILL.md 只能给 LLM 一种,OpenAPI 一份产 30+ SDK + docs + mock + test + portman + skill;改一处自动同步;host 碎片化 vendor 不押单一)。**search-agent 处于 host 端 adapter 角色,不与 Stainless 竞争,消费它产出的 spec**
    - **Google 部分例外**:Google 自家发 Discovery Document(513 APIs 自家 JSON 标准,非 OpenAPI),只 Maps 一家发真 OpenAPI YAML;**第三方 APIs-guru/openapi-directory mirror 299 个 Google API**(Discovery → OpenAPI 转换),实测 Google Chat API → openapi-to-skills → 171 个 markdown 文件 ✓

    **F. 轻量 vs 工程约束的 cut line(用户提的核心问题)**
    - **必须 wrapper(模型做不了的"数学操作 + 强制约束"类)**:RRF 融合 / schema 归一(20 source × 不同字段)/ 预算 cap(case_study 一跑 $0.51,无控易爆)/ eval 回归
    - **可以 skill 顶(模型做得了的"知识 + 决策"类)**:query rewriting / source 选择 / awareness / trace 落盘 / source 何时调
    - **最小 viable wrapper = 4 件 ~400 行 Python**(SearchCandidate Pydantic / Fan-out + RRF / Budget hook / Eval)+ 8 个复杂 source 的 thin shell wrapper(~50 行 bash 各)
    - **复杂 source(8 个待写脚本)**:Bluesky auth / twitterapi.io 默认套餐+sleep / PM 三源融合(PyPI/Maven/Go) / Sourcegraph stream SSE / Reddit OAuth / OpenReview 二段抓取 / OSV+references 跟踪 / Exa outputSchema 模板。**简单 source(14 个)**保持 raw curl

    **元教训**:
    - **CLI vs MCP 不是品味,是 token 经济**:GitHub 75-runs benchmark MCP 比 REST/CLI 贵 4-32× / 成功率 72% vs 100% / 月成本 $55 vs $3.20。**MCP 仅作"无 CLI 替代且工具 schema <5"的例外保留**
    - **vendor 把 spec canonical 迁出 GitHub 是 2026 趋势**(OpenAI 已经走完):未来加 vendor source 时,**先去 vendor docs 找 canonical OpenAPI URL**,不一定在 GitHub
    - **三层蒸馏工具栈非竞争而是分工**:Context7(预蒸馏 SaaS)/ Jina(静态)/ Firecrawl(SPA)/ openapi-to-skills(OpenAPI YAML)各占独立生态位,组合用而非择一〔→ #24:openapi-to-skills 在 search-agent ground-api 用例上落不下来,2026-05-02 demote 出 §3 sources〕
    - **Sentry MCP / grok-cli 同样错位归零**:这些是"用户自家 deployment 的工具",不是 search-agent 的 source。**search-agent 的 source 是外部世界,不是用户自家系统**——这条边界是 §1 决策树的隐含前提

24. **openapi-to-skills 从 §3 sources 删除 [2026-05-02]**——昨天加进 §3 第 4 行,今天用同一目标(Anthropic prompt caching docs,即 §1.3 ground-api 实际用户 query)+ 主流 SaaS YAML 公开率两个维度复测,demote。建设性结论:

    **A. YAML 公开率致命**(16 个主流 SaaS HEAD probe):
    - LLM 厂商:OpenAI / Anthropic / Cohere / SendGrid **全 404**(Stainless 客户中只 OpenAI 有公开 GitHub,且 master 分支已被搬空,canonical 在 Stainless 自家 URL,需 OAuth)
    - 200:GitHub / Stripe / Twilio / Slack / Discord(5 家)
    - 404:Google Maps / api.openai.com / api.anthropic.com / api.cohere.ai
    - APIs-guru/openapi-directory mirror **2529 个 spec 看似多,但 60% 是 Azure(653)/ Google(281)/ AWS(271) 基础设施 API**——和 search-agent 用户实际在问的 LLM/dev SaaS 不重叠

    **B. 即使有 YAML,也未必 > 渲染文档**(Stripe `POST /v1/charges` 实测):
    - openapi-to-skills 产出 `PostCharges.md` 只有 24 行(operation id + status code 壳),**请求参数细节 ❌ 不在 operation 文件**——Stripe 用 `application/x-www-form-urlencoded`,JSON schema requestBody 缺失
    - schema 里的 `charge.md` 71 行漂亮字段表是 **response object,不是 request body**;Stripe API 的真实请求参数仅在 hand-curated docs 页存在
    - 同 endpoint Jina 抓 `docs.stripe.com/api/charges/create` 539 行,135 行 nav noise,**42 行真实参数描述齐全**
    - **YAML 不是 ground truth,hand-curated docs 才是**——这条对所有"YAML 不完整 / form-encoded / 隐藏参数"的 vendor 都成立

    **C. 用例错位才是根本**:
    - openapi-to-skills 解决:"**给我 API 全 endpoint 地图 + schema 字段**"(代码生成 / SDK builder 任务,Stainless / Speakeasy / Fern 的市场)
    - search-agent ground-api 用户问:"**Anthropic prompt caching 怎么用 + cite 一段精确引文**"(quote-and-cite NOT summarize,§3.1 设计原则)
    - **两个用例对输出形态的需求不重合**——前者要全图 19/587/2992 ops + 字段表,后者要单页 markdown + 示例代码 + 版本号

    **D. 决策**:
    - 从 §3 sources.md 删除 openapi-to-skills 行,§3 表回到 3 行(Context7 / Jina / Firecrawl)
    - **ground-api skill 默认路径 = Jina,SPA fallback = Firecrawl,Context7 仅作"先模糊定位库"预检**(violates §3.1 quote-and-cite 时不直接用)
    - 工具本身不删,只是不进 search-agent 的默认路径——若未来"为某 vendor 生成 SDK wrapper"需求出现,再单独引入

    **E. 元教训**:
    - **新工具加 sources.md 前必须用本项目实际目标(LLM API docs / Stripe / GitHub 等用户真在问的)实测,不只看工具自家 demo**
    - petstore + 一份 Stainless YAML 给的"19 ops + 1369 文件"印象偏差极大——那是**工具能力天花板,不是用户实际需求面命中率**;**命中率 = YAML 公开率 × 用例匹配度 × YAML 完备度**,三者乘起来本项目命中率近 0
    - 与 §5.1 #23 D"三层蒸馏工具栈非竞争而是分工"对照:**生态位独立 ≠ 本项目都需要**;一个 source 在 inventory 里站得住的标准是"本项目用户的 query 形态命中它",不是"它在抽象空间占一格"

25. **Firecrawl vs Jina Reader 实测后纠偏:静态站 agent DIY 完全够,Firecrawl 真正独有的是 SPA / CF 墙 / 大规模 [2026-05-05]**——把两个 repo 拉到 `upstream/` 做源码层比对,用同一目标(`docs.deps.dev`)跑 `/map` + `/scrape` + `/crawl` + `r.jina.ai` + **DIY curl+grep**,产出 `/tmp/fc-vs-jina/{01..06}*` 工件。**首版结论被自己实测推翻一次,留作主要教训**。建设性结论:

    **A. 源码层(Public API surface 决定能力上限)**
    - **Jina Reader `src/api/crawler.ts`** 仅 3 个 `@Method` 全单 URL 入口(`getIndex` `GET /`、`crawlByPostingToIndex` `POST /`、`crawlByGetting` `GET\|POST /::url`)。**无 frontier / sitemap 解析 / job state / status 端点**。`cachedScrap()` 只是 fetch 层(curl/browser/CF rendering)。`s.jina.ai`(`searcher.ts` `SearcherHost`)是"SERP + 每结果调 Reader",仍是单 URL × N
    - **Firecrawl `apps/api/src/controllers/v2/crawl.ts`** `crawlController` 把 `includePaths/excludePaths/maxDiscoveryDepth/limit/allowExternalLinks/sitemap` 定义为 zod schema,创建 crawl group + `StoredCrawl` + robots.txt + kickoff job。worker 抽链接 + `crawl-redis.ts` URL 5-轴归一去重(`index.html`/`www`/scheme/hash/query)+ 入队
    - Jina README 写 "adaptive crawler / full website Colab" 是 notebook demo,**不是 public service endpoint**;vendor README 文案 ≠ API surface

    **B. 三路径在同一目标实跑(2026-05-05,docs.deps.dev,7 URL,5 页 markdown 比较)**
    | 路径 | URL 发现 | 单页抓取 | 全站(5 页) | 工程量 | 成本 |
    |---|---|---|---|---|---|
    | **Firecrawl** | `/v2/map` 8s 拿 7 URL | `/v2/scrape` 3.8s/59k chars | `/v2/crawl` limit=5 → 1 kickoff + status poll → **73s / 5 credits / 103k chars** | 6 行 bash | 0.5 美分/页量级 |
    | **Jina Reader** | ❌ 无 endpoint —— `r.jina.ai/<root>` 仅露 3 个内链(缺 `/glossary` `/faq` `/api/v3`)| `r.jina.ai/<url>` 2.2s/47k chars | 不可独立完成 | 0 行(被堵在 step 1)| 0 |
    | **Agent DIY**(curl + grep 一层递归 + Jina) | **`curl + grep -oE 'href' \| sed`** **3s** 拿 7 URL ✓ | `r.jina.ai/<url>` 2.2s | **3s + 5×2.2 ≈ 14s** | **~20 行 bash** | 0 |

    关键观察:
    - `docs.deps.dev` **没有 `sitemap.xml` / `sitemap_index.xml` / `.gz`**(全 404),`robots.txt` 也无 `Sitemap:` 声明 —— Firecrawl `/map` 拿到的 7 URL **走的是 root HTML `<a href>` 抽取 + 一层递归**(`/api/` 子页里挖出 `/api/v3` `/api/v3alpha`),agent 自己 `curl | grep | sed` 完全等价
    - DIY 结果 vs `/map`:**逻辑等价**,差异仅在 trailing-slash 归一(Firecrawl 做了,DIY 没做,9 → 7 去重)
    - 单页 markdown:Firecrawl 比 Jina 长 26%(59k vs 47k,保留更多 anchor / TOC / table 结构);Jina 快 1.7s/页

    **C. 首版错误结论(留作教训)**
    - 第一稿写 "全站 docs 索引 → only Firecrawl,Jina 结构上不可达,等于自己写半个 Firecrawl",**被用户一句"sitemap agent 自己也可以发现的吧 firecrawl 提供了什么"打脸,DIY 实测 3 秒等价复现**
    - 失误点:把 "Jina 没有全站原语" 错放大成 "全站采集只能用 Firecrawl",忽略了 **agent + bash + Jina 才是真竞品**,而非 "光 Jina"
    - 元教训(承袭 §2.11):**当一个工具看似 differentiated 时,先问"agent 自己 + 通用工具能不能做",再问"做不了的部分有多大"**——这是档 1(skill imperative)vs 档 3(full wrapper)边界的同一道闸

    **D. Firecrawl 真正独有(agent DIY 做不了或不愿做)**
    1. **SPA / JS 渲染**:静态站 curl 够用,SPA 站(Mintlify / GitBook)agent 要 Playwright + JS-aware link 抽取,工程量翻倍。**Firecrawl 内置浏览器池 + 实测 §5.1 #23 D Anthropic Mintlify 478KB 完整**
    2. **Cloudflare / 反爬绕过**:hosted stealth + proxy 通道,DIY 这个要烧 proxy 服务费 + Playwright stealth 插件,**工程级**
    3. **URL 5-轴归一**(`crawl-redis.ts`):`index.html` / `www` / scheme / hash / query 全归一,DIY 容易写漏(本次 9 条要去重到 7 条已经踩过)
    4. **`includePaths/excludePaths/maxDiscoveryDepth/limit/allowExternalLinks` 参数化 frontier**:DIY 要 if/else 一堆
    5. **Hosted job state + 分页 `next`**:跑 1000+ 页大站状态机 + 断点续传,百页内不必
    6. **多页并发 + 重试 + 速率自动**:DIY 写也不难,但累

    **E. 真实选型矩阵(对 search-agent 实际 vendor docs 用例)**

    [2026-05-05 OpenAlex 单 case → Wave 2 16 vendor panel,见 `reference/batch/meta/REPORT.md` + `reference/batch/wave2-vendor-probe/REPORT-wave2.md`] **第一版"Mintlify 行" 命名错** —— Wave 2 16 vendor 实证 Mintlify host 仅 18%(3/16),但 `llms.txt` 87%(14/16)、`llms-full.txt` 56%(9/16)。**`llms.txt` 是 2025-2026 期间形成的社区事实标准([llmstxt.org](https://llmstxt.org)),非 Mintlify 专利**。Anthropic / Cohere / OpenAI / Mistral 都不是 Mintlify host 但 ship。

    优先级矩阵(替代第一版,数字是 16 vendor panel 严格 verified 命中率):

    | # | 路径 | 命中率 | 单调用 | 适用场景 |
    |---|---|---|---|---|
    | **1** | `curl <root>/llms-full.txt`(< 5MB) | **44%** 实用区间(9/16 ship 减去 Anthropic/Cloudflare 巨型 + Vercel 假阳) | 1×curl,1-3s | 中型 vendor 直接入 LLM context |
    | **2** | `curl <root>/llms.txt` 索引 + 选择性 jina 单页 | **87%** | 1+N curl | **巨型 llms-full.txt 的切片入口**(Anthropic 58MB + Cloudflare 49MB) |
    | 3 | `robots.txt` → `sitemap.xml` + jina 每页(2 worker + backoff) | **88%** | 1+N curl | 1-2 都 miss 时(Stripe/Vercel/GitHub-style) |
    | 4 | root HTML 抽 `<a href>` 一层递归 + jina | 100%(任何静态可访问站) | 1+N curl | 3 也 miss(Groq:sitemap 在根域不在 docs root) |
    | 5 | Firecrawl `/scrape` `/crawl` | 100% | 1 credit/页,99/100 页 panel | 1-4 都失败 + 真 JS-only / 反爬 / 大规模 |

    **Firecrawl 的真实差异化场景缩到** ≤ 10% 用户用例(JS-only + 反爬 + 上述 4 路径都不行)。**§5.1 #25 第一版 "SPA = Firecrawl 独有" 进一步收紧**:Mintlify SPA 因 Next.js SSG pre-render,Path 1-2 全部覆盖;真正"Firecrawl 必须"是 client-only React/Vue + 无 LLM-aware 文件 + 无 sitemap 的极端站,该子集小到不值得为它在 sources.md 默认链路里加复杂度。

    **额外:`llms-full.txt` 的两种实践流派**(实测下载 9 vendor):
    - **per-page Source: marker 流派**:每段开头 `# Title\nSource: <URL>` 精确对齐 sitemap(OpenAlex/Mistral/Fireworks/Together/Exa/Firecrawl,~1-1.7MB 区间)
    - **整文 markdown 流派**:无 Source 标记,纯 h1 拼接(Anthropic 58MB / Cloudflare 49MB / OpenAI 1.7MB / Cohere 3MB)。**巨型流派的实际意义**:**vendor 给开发者一个 single-file backup,自切片缓存复用** —— Firecrawl /crawl 跑 Anthropic 站不仅多余,而且漏掉 vendor 自己提供的 100× 大 superset

    **`openapi.json` 真 JSON 命中率仅 6-13%(Wave 2 strict 验证)**:OpenAlex `/api-reference/openapi.json` 是甜区特例,**不能作为默认路径**。多数 Mintlify SPA 的 `/api-reference/openapi.json` 路由到 SPA shell HTML,假阳性 25%。要时单独 try `/openapi.{json,yaml,yml}`、`/api/openapi.json`、`/api-reference/openapi.json` 三路,**严格验 Content-Type = application/json**

    **DIY 路径的真实工程成本(OpenAlex 整站实测补的细节)**:
    - **Jina anon 6 并发立刻 429**:首轮 94 URL 只成功 20,降到 2 worker + exponential backoff 后 92/94,余 2 timeout 需手动重试。**单 IP free-tier 配额是 DIY 路径的隐藏税**(同 §5.1 #21 X 三方 free-tier 现象)
    - **xh 处理大 JSON response 时疑似动 body**:`/v2/crawl` status 1.3MB 包含未转义 `\` 致 `json.loads` invalid escape;改 raw `curl` 同 URL 后 valid。**默认工具链是 curl,不是 httpie/xh**

    **F. 对 sources.md §3 的修订**(Wave 2 后再次更新)
    - §3 表保持 3 行(单页输入形态分类),不动
    - Tip 区按 Wave 2 panel 数据重写为 5 级优先级,见 `sources.md` §3 实测命中率注脚
    - §5.1 #24 demote openapi-to-skills 决议加固:Wave 2 strict 验证 `openapi.json` 真命中率 6-13%,远低于 §5.1 #24 测试主仓库 OpenAPI 公开率(31%/16),**docs 站层面比 GitHub 主仓库还低**

    **H. 对 ground-api skill 的具体 imperative**(Wave 2 重写)
    收到"vendor X docs 找 Y"请求时,**3s 内 4 个 curl 决定路径**(probe + 严格验证):
    ```bash
    # 1. llms-full.txt size 判
    SIZE=$(curl -sI "$ROOT/llms-full.txt" | grep -i 'content-length' | awk '{print $2}' | tr -d '\r')
    [ -n "$SIZE" ] && [ "$SIZE" -gt 500 ] && [ "$SIZE" -lt 5000000 ] && echo "PATH=1.1 中型直入" && exit 0

    # 2. llms.txt 索引(可能巨型 llms-full.txt 的 chunk 入口)
    curl -sI "$ROOT/llms.txt" | grep -q '200' && echo "PATH=1.2 索引导航" && exit 0

    # 3. robots.txt → sitemap.xml(注意:不一定在 /docs/ 下)
    curl -sSL "$ROOT/robots.txt" | grep -i '^Sitemap:'  # 找真路径

    # 4. SPA 必有的: root HTML <a href>(Wave 1 deps.dev 模式)
    # 5. 都失败 → Firecrawl
    ```
    Wave 2 16 vendor panel 实测路径分布:1.1=44%,1.2=13%,1.3=19%,1.4=6%,1.5=≤10%。**Firecrawl 落到≤10% 用例 ≠ "无差异化",而是 ≤10% 的 niche valuable**(client-only React/Vue + 无 LLM-aware + 无 sitemap 的极端站);搜索代理 ROI 上不值得做默认路径,但保留兜底

    **I. Mintlify 是什么 + 5 条路径每条返回的具象形态**(从 Wave 1+2 工件实采,2026-05-05)

    ### Mintlify

    **是什么**:docs hosting SaaS,Next.js SSG/SSR 后端。客户:Anthropic、Cohere、Mistral、Together、Fireworks、Firecrawl 自己、OpenAlex 等(参 §5.1 #23 E Stainless 画像里的 SDK + docs 三层产业链)。
    **行为特征**:
    - 路由是 catch-all —— 任何未命中静态资源的 path 都返同一 SPA shell HTML(200 + `Content-Type: text/html`)。**这是 Wave 2 假阳性 25% 的根因**:probe `/api-reference/openapi.json` 返 200,但 body 是 SPA HTML,只有 `application/json` Content-Type 才是真 spec
    - 默认 ship `/sitemap.xml` + `/llms.txt` + `/llms-full.txt` 三件套(社区 [llmstxt.org](https://llmstxt.org) 标准的事实化推手之一,但**不是发明者**)
    - HTML 里有 SSG 预渲染文本(curl + 解析就能拿正文,不需 Playwright);bundle 含 `mintlify-assets/_next/static/chunks/` 标记
    - 部分客户配 `/api-reference/openapi.json` 真 JSON(OpenAlex 是),多数路由到 SPA shell

    ### Path 1:`/llms-full.txt`

    **是什么**:全站 markdown 内容拼成单文件。
    **Content-Type**:`text/plain` 或 `text/markdown`(Mintlify 默认前者)
    **大小区间**:298B(假阳性 "Page Not Found")→ **1-3MB(实用甜区,7/16 vendor)** → 49-58MB(Cloudflare/Anthropic 巨型,故意 ship 全文)
    **两种格式流派实采**:

    **流派 A — per-page `Source:` marker**(OpenAlex / Mistral / Fireworks / Together / Exa / Firecrawl):
    ```markdown
    # Authentication & Pricing
    Source: https://developers.openalex.org/api-reference/authentication

    API keys, pricing tiers, and usage limits

    OpenAlex data is and will remain available at no cost...

    ## Getting an API Key
    ...

    # Authors
    Source: https://developers.openalex.org/api-reference/authors
    ...
    ```
    每段开头 `# Title\nSource: <URL>`,精确对齐 sitemap.xml。**用 `^Source: ` grep 即可拆页** —— OpenAlex 实测 `grep -c '^Source: '` = 94,与 sitemap URL 数完全匹配。这种格式 LLM 友好(每段头部告诉模型这段来自哪个 URL,citation 直接拿)

    **流派 B — 整文 markdown(无 Source: marker)**(Anthropic / Cloudflare / OpenAI / Cohere):
    ```markdown
    # Anthropic Developer Documentation - Full Content

    This file provides comprehensive documentation with full rendered content.

    ## Root URL
    Claude Developer Platform Console (Requires login)
    https://platform.claude.com

    ## Available Languages on Website
    - English (en) - 1284 pages - ✓ Full content included below
    - German (de) - 132 pages - Visit website for content
    ...
    ```
    无 Source: 标记,纯 h1/h2/h3 拼接。Anthropic 的更进一步加了 meta 段(语言列表 / root URL)。**好处**:vendor 给开发者一个 single-file 全文 backup;**坏处**:agent 切片要自己按 h1/h2 推断 URL 边界,citation 不稳

    ### Path 2:`/llms.txt`

    **是什么**:LLM-aware 索引文件(简介 + 路径列表),[llmstxt.org](https://llmstxt.org) 标准。
    **Content-Type**:`text/plain` / `text/markdown`
    **大小**:典型 1-10KB
    **格式**(OpenAlex 实采):
    ```markdown
    # OpenAlex API - LLM Reference

    OpenAlex is an open catalog of the global research system with 270M+ works...

    ## Quick Start
    Base URL: https://api.openalex.org
    Auth: api_key parameter (free at openalex.org/settings/api)
    Rate limit: $1/day free usage with key, $0.01/day without

    ## Entity Endpoints
    GET /works - Scholarly documents (articles, books, datasets, theses)
    GET /works/{id} - Single work by OpenAlex ID (W2741809807) or DOI
    ...

    ## CRITICAL: Always Resolve Names to IDs
    WRONG: /works?filter=authorships.author.display_name:Einstein
    RIGHT:
      1. /authors?search=Einstein → get id "A5012345678"
      2. /works?filter=authorships.author.id:A5012345678
    ```
    **关键观察**:不是单纯的 URL 列表,**有 vendor 自己写的"使用模式 + 反模式"导引**(看 OpenAlex 的 "CRITICAL: Always Resolve Names to IDs")。这是 sitemap.xml 没有的、**对 ground-api skill 极其有用的语义信息**。87% 命中率使其成为最稳的入口

    ### Path 3:`/sitemap.xml`(robots.txt → Sitemap: 行)

    **是什么**:SEO 标准 XML,纯 URL 列表。
    **Content-Type**:`application/xml`
    **大小**:1-100KB 典型
    **格式**(OpenAlex 实采):
    ```xml
    <?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://developers.openalex.org/api-reference/authentication</loc>
        <lastmod>2026-02-24T19:03:05.134Z</lastmod>
      </url>
      <url>
        <loc>https://developers.openalex.org/api-reference/authors</loc>
        <lastmod>2026-02-17T21:58:02.285Z</lastmod>
      </url>
      ...
    </urlset>
    ```
    只有 URL + lastmod + 偶尔 changefreq/priority。**没有任何描述、内容**,要拿到正文必须**逐 URL 再 fetch**(走 `r.jina.ai/<url>` 或 curl + 解析)。Wave 2 教训:Groq 的 sitemap 在根域(`https://console.groq.com/sitemap.xml`)不在 `/docs/sitemap.xml`,**先读 `robots.txt`** 找 `Sitemap:` 真路径

    ### Path 4:root HTML 抽 `<a href>` 一层递归

    **是什么**:vendor docs 首页的 HTML body,内有所有内部 nav 链接。
    **Content-Type**:`text/html`(SSG 站含正文,纯 SPA 站只有 shell)
    **抽链方法**(OpenAlex 实采):
    ```bash
    curl -sSL https://developers.openalex.org/ \
      | grep -oE 'href="[^"]+"' \
      | grep -E '^href="(/|https://developers.openalex.org)' \
      | sed 's/^href="//;s/"$//' \
      | sort -u
    ```
    **返回**:
    ```
    /
    /api-reference/authors
    /api-reference/funders
    /api-reference/institutions
    /api-reference/introduction
    /api-reference/publishers
    /api-reference/sources
    /api-reference/topics
    /api-reference/works
    /download/overview
    ```
    一层抽到 10 个一级链接,**每个再 curl 一次抽其 href** = 二层递归 = 完整 frontier(deps.dev 实测 2 层够,3 层多余)。**Mintlify SSG 站抽链命中率 100%**(因为 nav 的 `<a>` 是 pre-render 的,不依赖 JS 运行时)。客户端 React/Vue SPA 这一步会失败 —— 落到 Path 5

    ### Path 5:Firecrawl

    **`/v2/map` 返回**(OpenAlex 实采):
    ```json
    {
      "success": true,
      "links": [
        {
          "url": "https://developers.openalex.org/guides/key-concepts",
          "title": "Key Concepts - OpenAlex Developers",
          "description": "Understand entities, IDs, and data structures in OpenAlex"
        },
        {
          "url": "https://developers.openalex.org/api-reference/works/list-works",
          "title": "List works - OpenAlex Developers",
          "description": "Get a list of scholarly works with optional filtering, searching, sorting, and pagination..."
        },
        ...
      ]
    }
    ```
    比 sitemap.xml 多 `title` + `description`(从 og 标签 / meta 抽),**这是 sitemap 没有的纯 SEO 信号**

    **`/v2/scrape` 返回**(Groq 单页实采):
    ```json
    {
      "success": true,
      "data": {
        "markdown": "# Supported Models...\n\n[![Groq](https://...)](...)\n\n[Docs](...) [Login](...)\n\n...",
        "metadata": {
          "title": "Supported Models - GroqDocs",
          "og:title": "Supported Models - GroqDocs",
          "ogSiteName": "GroqDocs",
          "twitter:title": "Supported Models - GroqDocs",
          "ogImage": "https://console.groq.com/og_cloudv5.jpg",
          "viewport": "...",
          "statusCode": 200,
          "sourceURL": "https://console.groq.com/docs/models"
        }
      }
    }
    ```
    单页 markdown + 全套 og/twitter/seo metadata + 原 statusCode

    **`/v2/crawl` 异步 status 返回**(OpenAlex 99 页实采):
    ```json
    {
      "success": true,
      "status": "completed",          // "scraping" / "completed" / "failed" / "cancelled"
      "completed": 99,
      "total": 99,
      "creditsUsed": 99,
      "expiresAt": "2026-05-06T04:08:09.000Z",
      "data": [
        {
          "markdown": "[Skip to main content](...)\n\n[OpenAlex Developers home page![light logo](https://...)]...",
          "metadata": {
            "og:title": "Overview - OpenAlex Developers",
            "language": "en",
            "ogUrl": "https://developers.openalex.org",
            "sourceURL": "https://developers.openalex.org",
            "statusCode": 200,
            ...
          }
        },
        ... // 99 items
      ],
      "next": null  // 分页:总返回 > 10MB 时这里是下一页 URL
    }
    ```
    **完整状态机**:`POST /v2/crawl` 返 `{success, id, url}` kickoff → 多次 `GET <url>` polling 直到 `status === "completed"` → 一次性拿全部 markdown。**注意**:`expiresAt` 是 24h 后(crawl 结果只缓存一天)

    **G. 元教训**
    - **当一个 SaaS 工具看似独有,先做 "agent + 通用 CLI 能否复现" 的反向测试**——本次 Firecrawl `/map` vs `curl|grep` 实跑等价,直接推翻自己首版结论。这是 §2.11 / §5.1 #11 / #18 反复说的"adapter 真价值在跨源中间层,不在 per-source 代码"在工具选型上的同形应用
    - **Vendor README 文案 + 工具能力天花板 ≠ 本项目命中率**:Firecrawl 的差异化能力(SPA / CF 绕过)真实存在,但本项目大多 vendor docs 站(deps.dev / OSV / GitHub Pages / MkDocs)都是静态的,**真正用得上 Firecrawl 杀手能力的子集 < 30%**(§5.1 #23 列的 Mintlify / SPA 类才命中)
    - **源码层 + 实测层 + 反向 DIY 三线验证**:今天的循环就是这个——单读 README 给"两者位于不同生态位"印象;扒源码确认 Jina 无 frontier 公开端点;实跑 Firecrawl /crawl 确认能用;**反向跑 DIY** 才发现"独有"被高估。**没有第三步,就会落锚到错配置**
    - **跑通 ≠ 写完**:今天验证 step 1-2(URL 发现 + markdown 拉取);step 3-5(LLM 抽 endpoint/schema/auth + 生成 OpenAPI + 真实请求校验)未实跑,留 §5.3 开放问题
    - 承袭 §5.1 #14/#15/#20:产品迭代按月,Jina/Firecrawl 都活在 active dev,**至少季度复测端点 + 价格 + rate limit**

    **J. 行业 cross-ref 与 strategy/pipeline 落盘 [2026-05-06]**

    在 5 路径对照基础上做了行业横向调研,把 strategy + pipeline 落到 repo 根级 git tracked 文件:

    - **`ground-api-strategy.md`**(repo 根) — 高层定位 + 行业拓扑 + 与 Context7 / Cursor 的精确对比 + 风险与未决
    - **`ground-api-pipeline.md`**(repo 根) — 4 probe + 5 路径降级的可执行 bash + 严格验证 + trap 列表 + 命中率累计
    - 实证工件继续保留 `reference/batch/`(.gitignore 排除,本地)

    行业 cross-ref 关键数据(strategy.md §2 详):
    - **llms.txt 时间线**:Jeremy Howard(Answer.AI) 2024-09 提出 → Mintlify + Anthropic 2024-11 合作开发 llms-full.txt → 2026-Q1 通用域 10% 命中(SE Ranking 30 万站) **vs LLM/dev 16 vendor panel 87%**(我们 Wave 2)。**dev tool 子集是这个标准的核心产消生态**
    - **Anthropic ship 58MB llms-full.txt 不是巧合**:他们和 Mintlify 共同设计了 llms-full.txt 协议,自然是首批最大 producer
    - **AI 大厂未承诺生产读 llms.txt**(Google Mueller 公开声明 / PPC.land "adoption stalls"),**但 dev IDE 工具(Cursor / Continue / Aider / Context7)在用** — 这正是 search-agent 的目标用户群,与通用 AI search 的结论无关
    - **三种 consumer 拓扑**:IDE 内置(Cursor 14.7% ctx util,绑死 IDE)/ MCP 服务(Context7 65% acc,token 4-32× 浪费)/ skill imperative(我们,host-agnostic 0 中间层)
    - **5 项行业最佳实践共识**全部对齐我们 PIPELINE:静态 docs 本地缓存 / dynamic > static context / vendor 官源胜二手聚合 / 降级机制必须 / probe 严格验证

    元教训:**做一轮单 case 实证(Wave 1) → 单点 panel 验证泛化(Wave 2) → 行业 cross-ref 锚定坐标(本段) 三步法**。第三步成本最低(几次 web search + WebFetch)但回报最高:把"我们的实测结论"和"行业演化轨迹"拼到一起,strategy 才稳;否则容易闭门造车 anchor 在 OpenAlex 单 case 的特殊性上

### 5.2 我们一开始想错被纠正的(避免重蹈)

| 早期判断 | 纠正 | 触发 |
|---|---|---|
| "1.x 的 graph 比 2.0 简单,从 1.x 起步" | 改:2.0 的 skill 模型更适合多 vertical;但**两者 search 部分都是 wrapper,不能直接抄** | 用户清晰说"是 harness for agents",且实读 DeerFlow 代码后 |
| "用 MCP server 暴露 harness 给 host" | 改:**CLI + skills 更好**(Anthropic 自己证明 98% token 减少) | 用户 push,实证查了 Anthropic / Microsoft 转向 |
| "browser-use vs Playwright 二选一" | 纠正:**browser-use 建在 Playwright 上**,真正选择是 zero-config 偏好 | 实读 browser-use 文档 |
| "推荐 browser-use" | 改:**Playwright MCP 更适合 zero-config + no internal LLM 原则** | 用户偏好梳理后 |
| 之后 "推荐 Playwright MCP" | 再改:**Playwright CLI + skills 更好**(用户实证 push) | 查 Anthropic Code-execution + Playwright 自家 benchmark |
| "做 MVP 就拼 Tavily + Exa + Serper + Brave 几个 web search" | 纠正:**这是 wrapper 思路**,真正价值在 ranking / fit / 深度处理 / 验证 | 用户明确 push 反 wrapper |
| 漏了 AI-augmented 二级源类(DeepWiki 等) | 加 §0 进 sources.md | 用户 catch |
| "xAI X Search 是 premium fallback,~$0.56/call,贵" | 改:**实测单次 $0.03**(prepaid $5 → 剩 $4.97),**比 X 官方 PPU 单次 $0.05 还便宜**——是 one-shot 分析最优路径,不是兜底 | dashboard 实费用打脸 [2026-04-30],详见 §5.1 #21 |
| "compass artifact 推 Sentry MCP 进 §2 Co-install"(Tier 1 grounding) | 改:**Sentry / grok-cli 都属于"用户自家 deployment 的 introspection",不是 source-agent 的 source**。装了又卸 | 实测 Sentry MCP 0 projects(BP 阶段无部署),架构错位明显 [2026-05-01];详见 §5.1 #23 |
| "compass artifact 推 Bluesky 替 twitterapi.io(无 rate limit anon search)" | 改:**`searchPosts` anon 现 403**(2024 后政策),需注册 + app password 拿 accessJwt 才能搜;authed 后 200 + 5 连发无 429 ✓ | curl 实测 [2026-05-01];详见 §5.1 #23 |
| "Sourcegraph free PAT 能解锁额外功能" | 改:**PAT vs anon stream search 命中 1:1**(`Rust+tokio` query),**free PAT 在 search 上无优势**,anon stream API 即可 | 直接 curl 对比实测 [2026-05-01];MCP 已卸 |
| "GitHub 官方 MCP 给我们补 Discussions/Gists/code scanning"(compass artifact 推) | 改:**41 工具 schema 立即占 ~55K context**;benchmark MCP 比 REST 贵 4-32× / 成功率 72% vs 100%。**REST + GraphQL 直查 Discussions 即可**,MCP 已卸 | 装后 list MCP 可见 token 占用问题 [2026-05-01];详见 §5.1 #23 元教训 |

**反思的 meta-pattern**:每次"按业界主流推"的判断都被实证 push 反了。**这个领域是被旧范式的惯性绑架的**——"MCP 才现代"、"agent loop 是趋势"、"自托管 search engine 是 cool"——但实证一查,几乎都在被新模式替代。**保持反 anchoring 警觉**。

**新增 meta-pattern(成本类) [2026-04-30]**:**任何"premium / fallback"框架未跑实证 dashboard 前都不要落地**。文档定价 + token 估算 + tool 调用次数三个变量任一估错,数量级就翻——本次 18× 偏差就是 token 单价(grok-4.20-reasoning 实际走 fast-tier 而非 reasoning 标价)+ ticks 单位双重误判叠加。规则:**所有定价判断必须有 dashboard 实费用截图回填**才能进 §5.1 锚点。

### 5.3 留作未决的开放问题

1. **Router 设计**——gate 层精确逻辑、决策粒度(用户明确说"我还需要时间思考")
2. **Long-tail 任务路由**——多模态(Tier 4-5)、browser(Tier 5)的触发条件、降级策略(用户明确说"我还需要时间思考")
3. **Adapter / skill 的精细化平衡**——边界已定(§2.9 决策树),但具体 case 还需 case-by-case(用户明确说"我还需要时间思考")
4. **Skill 设计粒度**——每个 vertical 一个,还是按"任务模式"分?skill 文件的篇幅、imperative tone 力度(用户明确说"我还需要时间思考")
5. Cache TTL 策略(各 source 时效性差异大)
6. Citation schema 在不同 Tier 间如何统一最小公共集
7. Tier 3 web search backend 默认选哪个
8. ~~sources.md 用户筛选保留哪些~~ → **已通过 adapter-vs-skill.md(已合并废弃) 解决**
9. ~~可选 adapter(libraries.io / OpenReview / HF Hub / CVE 等)是否进 Phase 1~~ → **[2026-04-26] 全部纳入**(23 adapter,见 §5.1 #11 + adapter-vs-skill.md §2)
10. 是否需要 result memory(同 query 第二次触发不重复 fan-out)—— **gbrain 是天然候选**(见 §1.8)
11. 中日社区站的 web_search 命中率到底如何(需要实测验证 skill-only 假设)

12. **Benchmark target 选择**(为系统做完后跑实验用)— 现成 candidate 已扫,**search-agent 用例 1:1 对应**:
    - **CoReQA**(arXiv 2501.03447,2025-01)— Code Repository-level Question Answering,**专补 QA 缺口**(现有都偏 generation)
    - **CodeRAG-Bench**(NAACL 2025 Findings)— 直接测 retrieval + generation 联合,covers basic / open-domain / repo-level 三档
    - **InfiBench**(NeurIPS 2024 Datasets & Benchmarks Track)— 234 真实 Stack Overflow 风格 Q&A,多语言,**主流 Q&A baseline**
    - **SimpleDevQA**(arXiv 2512.08867,2025-12)— Development Knowledge QA
    - **ExecRepoBench**— repo 级别 + 执行验证
    
    主流 coding agent benchmark(做 baseline 用,我们 thin-harness 路线对照):
    - **SWE-bench Verified / Pro / Live**(2026-04 SOTA: Claude Mythos Preview 93.9% / GPT-5.3 Codex 85% / Claude Opus 4.5 80.9%)
    - **Terminal-Bench 2.0**(2026-01 出,89 真实 terminal task,Codex CLI + GPT-5.2 63%)
    - **BigCodeBench / LiveCodeBench / SWE-Lancer**
    
    **关键 ammunition for thin-harness 论点**:**Cline autonomous (Claude Sonnet 4.5) 59.8% vs SWE-agent v1 同模型 43.2% on SWE-bench Verified — 差 16pp 来自 orchestration alone**(同模型不同 harness)。这条直接证明 thin-harness 路线的价值,可作 paper §1.
    
    多模态 / Tool use / CUA(对应 roadmap 后期):
    - **API-Bank / ToolBench / MetaTool / ToolEyes** — 对应"agent orchestration skills 多智能体 fit search"
    - **OSWorld / RealWorld-CUA / WebArena / WebShop** — 对应"CUA 完全端到端测试"co-install
    - **SWE-bench Multimodal** — 对应"原生多模态 plugin"
    
    A/B test 学术先例(走 SE / HCI 顶会,不是 NeurIPS/ICLR main):
    - N=20-50 dev user study(我们工具 vs baseline)→ **CHI / UIST**
    - dev workflow 改进 SE empirical study → **ICSE / FSE / ASE**
    
    **行动建议**:**优先跑 CoReQA + CodeRAG-Bench + InfiBench 三联** + 我们 thin-harness 多源融合,显示 N% 提升 → NeurIPS D&B / ACL Findings / NAACL 有真路径。如果造一个新 benchmark("Professional Dev Search Bench",N>>500 真实 dev query × 多源 × 多模态 GT),NeurIPS Datasets & Benchmarks Track 直接 target。

---

## 6. URL 索引(快速跳转)

### 我们项目的同类参考
- [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | [GPTR MCP](https://github.com/assafelovic/gptr-mcp)
- [Stanford STORM](https://github.com/stanford-oval/storm)
- [MindSearch](https://github.com/InternLM/MindSearch)
- [LangChain Open Deep Research](https://github.com/langchain-ai/open_deep_research) | [DeepAgents](https://github.com/langchain-ai/deepagents)
- [Bytedance DeerFlow](https://github.com/bytedance/deer-flow)
- [Vane](https://github.com/ItzCrazyKns/Vane) | [Perplexica](https://github.com/ItzCrazyKns/Perplexica)
- [HuggingFace smolagents](https://github.com/huggingface/smolagents)
- [last30days-skill](https://github.com/mvanhorn/last30days-skill)(mvanhorn,24k★;Claude Code skill 形态,**13 平台 + 双判官 + pre-resolver brain**;2026-04 上 GitHub Trending #1)
- [Agent-Reach](https://github.com/Panniantong/Agent-Reach)(Panniantong,18k★;Python CLI,**16+ platform reader + CN 平台广覆盖 + `doctor` 自诊**;2026-04 GitHub Trending)

### Thin Harness Fat Skills 共同体
- [gstack](https://github.com/garrytan/gstack)(Garry Tan / YC CEO)
- [gbrain](https://github.com/garrytan/gbrain)(Garry Tan)
- [superpowers](https://github.com/obra/superpowers)(Jesse Vincent / Anthropic)
- [OpenClaw](https://github.com/openclaw/openclaw)(Peter Steinberger,247k stars 开源 agent runtime)

### Doc grounding
- [Context7](https://context7.com)
- [Ref.tools](https://ref.tools) | [GitHub](https://github.com/ref-tools/ref-tools-mcp)
- [docs-mcp-server](https://github.com/arabold/docs-mcp-server)
- [Jina Reader](https://jina.ai/reader/)
- [Firecrawl](https://firecrawl.dev/)

### Browser automation
- [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp)
- [Playwright CLI 介绍](https://testcollab.com/blog/playwright-cli)
- [browser-use](https://github.com/browser-use/browser-use)

### AI 二级源
- [DeepWiki](https://deepwiki.com) | [MCP Server](https://cognition.ai/blog/deepwiki-mcp-server)
- [deepwiki-open](https://github.com/AsyncFuncAI/deepwiki-open)
- [OpenDeepWiki](https://github.com/AIDotNet/OpenDeepWiki)
- [gitingest](https://gitingest.com) | [Repomix](https://github.com/yamadashy/repomix) | [GitMCP](https://github.com/idosal/git-mcp) | [uithub](https://uithub.com)

### 编程领域
- [Aider repo map](https://aider.chat/docs/repomap.html)
- [Sourcegraph Cody](https://sourcegraph.com/docs/cody)
- [Continue.dev](https://docs.continue.dev/customize/deep-dives/custom-providers)
- [Serena MCP](https://github.com/oraios/serena)
- [SWE-Search / Moatless](https://github.com/aorwall/moatless-tree-search)
- [GitHub MCP server](https://github.com/github/github-mcp-server)

### 关键工程博客
- [Anthropic — Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
- [Anthropic — Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
- [LlamaIndex Routers](https://developers.llamaindex.ai/python/framework/module_guides/querying/router/)
- [AIMultiple agentic search benchmark](https://aimultiple.com/agentic-search)

### Search API 商业
- [Tavily](https://tavily.com) | [Exa](https://exa.ai) | [Brave Search API](https://brave.com/search/api/)
- [Serper](https://serper.dev) | [SerpAPI](https://serpapi.com) | [Linkup](https://linkup.so)
- [Perplexity Sonar](https://docs.perplexity.ai/) | [Kagi API](https://help.kagi.com/kagi/api/search.html)

### Cross-cut metadata backend
- [api.deps.dev](https://api.deps.dev)(Google Open Source Insights)— Go / Maven / PyPI / npm / crates / NuGet / RubyGems 的 license + version + advisoryKeys 元数据统一来源。**pkg.go.dev `/api/v1/*` 名存实亡后浮现为真路径**(见 §5.1 #15)

### 学术 API
- [OpenAlex](https://openalex.org/) | [API docs](https://docs.openalex.org/) — 250M+ works,**完全无 key**(UA 带 mailto: 进 polite pool,~26 req/min);Phase 1 ★ #7,2026-04-30 替换 Semantic Scholar(详见 §5.1 #20)
- [arXiv API](https://info.arxiv.org/help/api/) — Phase 1 ★ #6,Atom XML
- [OpenReview API2](https://docs.openreview.net) — Phase 1 ★ #8,公开评审/decision/rebuttal
- [Semantic Scholar](https://api.semanticscholar.org)(降级 skill cross-ref,见 §5.1 #20)
- [Crossref REST](https://api.crossref.org)(DOI 元数据,无 key,可作 OpenAlex 的二次验证)
- [OpenCitations](https://opencitations.net/index/coci/api/v1)(引用关系专项,无 key)

### Tier 4 反爬中间件(YouTube 等平台)
- [Invidious](https://github.com/iv-org/invidious) | [`/api/v1` 文档](https://docs.invidious.io/api/) | [公共实例列表](https://docs.invidious.io/instances/)(Tier 4 find-talk vertical 实施 anchor,见 §5.1 #17)
- [Invidious Companion](https://github.com/iv-org/invidious-companion)(Deno/TS,反爬 sidecar)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)(Tier 4 兜底,周期性遭 YouTube 血洗)

---

## 7. DeerFlow 工程框架交叉分析(详细)

> **§2.10 给的是 DeerFlow 的具体机制**(防幻觉/防偷懒/灵活切换)。本节给"我们应该抄什么、明确不抄什么、缺什么"的判断。**作为 architecture.md §11 的依据材料**。

### 7.1 直接可用的工程模式(应该抄)

#### Harness/App 边界防火墙(最值钱)

DeerFlow 把代码严格分两层:
- `packages/harness/deerflow/` — 可发布核心(纯库,import 前缀 `deerflow.*`)
- `app/` — 应用层(FastAPI gateway / IM channels,import 前缀 `app.*`)

规则:`app` 可 import `deerflow`,但 `deerflow` **绝不能** import `app`。**用 CI 测试强制**(`tests/test_harness_boundary.py`)。

→ 我们的等价:
```
search-harness/
├── core/        ← source adapters / gate / fusion(纯库,无 CLI/skill 知识)
├── cli/         ← argparse / 输出格式化 / 文件 IO(import core)
└── skills/      ← markdown 文件
```
+ CI test 检查 `core/*.py` 不出现 `import cli` / `import skills`。

**为什么值得**:让我们以后可以**给 core 加任意 surface**(Python lib / MCP server / 长驻 daemon)而无需重构。

#### LoopDetectionMiddleware 的"稳定键"思想(不是 loop detection 本身)

DeerFlow `_stable_tool_key()` 函数:**针对不同工具类型,用不同策略派生稳定 key**。

```python
# read_file: 把 line range 按 200 行分桶
#   → "src/foo.py:0-1" 而不是 "src/foo.py:1-37"
# write_file/str_replace: 内容敏感,hash 全 args
# 通用: 取 (path, url, query, command) 这些 salient 字段
```

**对我们 cache/dedup**:
- GitHub: `query + filters` 是 key,**不进 max_results**
- arXiv: `query + date_bucket(week)`,不要 exact timestamp
- web search: `query` only(snippet 在变,但同 query 拿同批 URL 是合理的)

→ **每个 source adapter 必须实现 `cache_key(query, filters) -> str` 策略函数,不能用通用 dict-hash**。

#### 工具错误 → 消息

DeerFlow 的 `ToolErrorHandlingMiddleware` 把 tool 抛出的 Exception 转换成 ToolMessage,让 agent loop 能继续。

**对我们的等价**:任何 source 的 exception **绝不能传播出 fan-out 阶段**。每个 source 的失败 → 一条带 `error` 字段的空 result,fusion 阶段感知到但不阻塞其他 source。

→ "**Adapter 强制契约**":每个 adapter 必须实现 `async def search(query) -> SearchResult | ErrorResult`,**不允许 raise**。CI 加测试验证。

#### Trace ID 贯穿全链路

DeerFlow 给每次调用生成 `trace_id = str(uuid.uuid4())[:8]`,**所有 log 都带这个 ID**。

**对我们**:
- CLI 入口生成 `query_id`(8 位 hex)
- 透传到每个 source adapter 的 logger
- Output JSON 也带 `query_id` 字段

**好处**:用户报 bug 时贴 `query_id`,你立刻能在 log 里筛出整条流水线。

### 7.2 自觉不抄的 over-engineering(明确不做)

| DeerFlow 有的 | 为什么我们不做 |
|---|---|
| **17 个 middleware 链** | 大部分是 agent loop 概念(Title/Memory/Sandbox/Subagent…),CLI 不需要 |
| **SubagentExecutor + 双 thread pool** | 我们不 spawn agent,只在 source 间并发,asyncio.gather 就够 |
| **ThreadState 自定义 reducer** | 无状态 |
| **Memory 系统 + queue debounce** | CLI 之间无 cross-call memory(host LLM 自己管)。**真要长期 memory → 集成 gbrain** |
| **Sandbox 双 provider(Local/Aio)** | 不执行代码 |
| **Channels(Slack/Feishu/Telegram…)** | 不在 search 范畴 |
| **LangGraph Server** | 不要 long-running server |
| **Streaming bridge** | CLI stdout 自带流式 |
| **Config versioning + 自动 reload** | MVP 阶段 yaml 改了就重启 CLI |

**总原则**:DeerFlow 解决的"agent 长跑生命周期"问题,我们大多数不存在。**借鉴的是底层工程纪律,不是上层 agent 框架**。

### 7.3 我们可能缺的(应该补)

#### TDD 文化

DeerFlow 的 CLAUDE.md 第一条:"**Every new feature or bug fix MUST be accompanied by unit tests. No exceptions.**"——~110 个测试文件实测。

→ 对我们:
- 每个 source adapter 必须有 mock-based 单元测试(模拟 API 响应)
- gate / fusion 必须有 property-based 测试(给定 N 个 source 输出,验证 RRF 性质)
- end-to-end 测试用 VCR/cassette 录制真实 API 响应

#### Adapter 的"契约测试"

DeerFlow `TestGatewayConformance`:**用 Pydantic model 验证每个 client 方法的返回**。Gateway 加新字段而 client 没跟上,CI 立刻 fail。

→ 对我们:每个 source adapter 应该返回统一的 `SearchCandidate` schema(pydantic),CI 跑契约测试确认所有 adapter 都满足。

#### Lazy initialization

DeerFlow 的 middlewares 默认 `lazy_init=True`——只在被实际用到时才构造。

→ 对我们:source adapter 应该**懒加载**——不调 GitHub 就不 import `httpx + GitHub SDK`。**这对零配置体验很关键**(`search-harness --help` 不应该花 2 秒加载所有依赖)。

### 7.4 关键文件参考(DeerFlow)

| 文件 | 作用 |
|---|---|
| `backend/packages/harness/deerflow/agents/lead_agent/agent.py:241` | `_build_middlewares()` — 中间件组装顺序 |
| `backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py` | LoopDetection 完整实现 + stable key 思想 |
| `backend/packages/harness/deerflow/subagents/executor.py:128` | SubagentExecutor — 后台并发任务 + cancellation |
| `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py` | 错误 → message 转换 |
| `backend/tests/test_harness_boundary.py` | CI 边界防火墙测试 |
| `backend/CLAUDE.md` | 工程规范全集(TDD + 边界规则) |

### 7.5 一句话总结

> **DeerFlow 解决的是"agent 长跑生命周期"问题,我们解决的是"垂直检索 + 高质量 ranking"问题。两者完全不同,但 DeerFlow 在工程纪律上有几个真正值得抄的细节(harness/app 防火墙、stable key 派生、错误转消息、trace_id),其余 17 middleware 大部分对我们是 over-engineering。**

---

## 8. 元规则(给未来的自己)

1. **任何"业界主流"判断都要实证 push**(我们已经翻车 5 次,见 §5.2)
2. **Wrapper 思路不会创造价值**(差异化在 ranking / fit / 深度处理 / 验证 / 个性化)
3. **每次新需求出现,先问"这件事别人是不是已经替我做了 AI 处理"**(白嫖原则)
4. **保持工具表面薄,把复杂留在 Pipeline 层**——工具表面变了 = host 重学;Pipeline 内部变了 = 用户无感
5. **Token 经济 > 任何架构美感**——MCP schema 太重就不用 MCP,bash 老土但训练分布满
6. **加新源前先过 §2.9 的 4 问决策树**——不满足"web_search 替代不了"就不写 adapter,只是"agent 不知道"就 skill 解决
7. **三源吸收**——DeerFlow(工程骨架)+ gstack/superpowers(skill 写作纪律)+ gbrain(fat skills)三方综合,不押单一参考
8. **Claude Code 上默认不上 graph framework**——用 prompt + hooks 把模型自由度约束到可接受范围;只在 durable workflow / 非 LLM 重活节点时才考虑框架(详见 §2.12)
9. **Competitor 的 npm/pypi/cargo 包是高 ROI 侦察源**——反编译 dist/ 拿到的架构知识比读 README + blog 30 篇都密。**前提:本地装,不全局污染**(项目级 `tools/{name}/` + 配 wrapper 脚本翻译 env / config)。30 分钟扒源码 = 一篇 architecture blog 的全部内容 + 看不到的实现细节(成本上限、二级 LLM 调用、安全模型差异)。详见 §5.1 #22(grok-cli 反编译实证)
10. **所有定价判断必须 dashboard 实费用截图回填才能进 §5.1 锚点**——文档定价 + token 估算 + tool 调用次数三个变量任一估错,数量级就翻。参考 §5.2 中 xAI X Search 18× 高估纠错 / §5.1 #21 cost_in_usd_ticks 单位实证(详见 §5.2 末尾)
11. **MCP 仅作"无 CLI 替代且工具 schema <5"的例外**——默认 CLI / REST 直调优先。GitHub 75-runs benchmark:MCP 比 REST 贵 4-32×、成功率 72% vs 100%、月成本 $55 vs $3.20。Playwright Microsoft 自家 bench:MCP 114K tokens vs CLI 27K(4× 差)。Context7 自家 bench:CLI mode 比 MCP 节省 65% tokens / 38% latency。**当前 §2 全 CLI(Context7/Playwright/yt-dlp)+ DeepWiki 1 个 MCP 例外**(无 CLI 替代,3 工具 schema 小)。详见 §5.1 #23 A
12. **Vendor 维护 OpenAPI canonical 是 2026 趋势 + Stainless / Speakeasy / Fern 是 SDK 工厂层**——OpenAI master branch 空了,canonical 在 `app.stainless.com/api/spec/documented/openai/openapi.documented.yml`。**搜 vendor source 时,先去 vendor docs 找 "canonical OpenAPI URL",不一定在 GitHub**。三层产业链:**vendor 维护 spec → Stainless / Speakeasy / Fern SaaS 平台产 SDK + docs + MCP/skill 适配 → host 端 adapter 再适配**。search-agent 处于 host 端 adapter 角色,**不与 SDK 工厂竞争,消费它产出的 spec**。详见 §5.1 #23 E
13. **三层 docs 蒸馏工具栈是分工不是择一,但本项目只用类 1+3**:类 1 预蒸馏 SaaS(Context7 / Ref.tools / Deepcon / DeepWiki / GitMCP)/ 类 2 OpenAPI → SKILL 自动生成(`openapi-to-skills` / Speakeasy / openapi-llm)/ 类 3 web → markdown(Firecrawl SPA 之王 / Jina 静态零 key / Crawl4AI 本地)。**抽象上任意输入形态对应一个最优工具**,详见 §5.1 #23 D。**但类 2 在 search-agent ground-api 用例上落不下来**(LLM 厂商 YAML 公开率 0、有 YAML 也不一定优于渲染 docs、用例本身要 quote-and-cite 不要全 endpoint 地图)——见 §5.1 #24,**ground-api 默认路径 = Jina + Firecrawl 两件套**
14. **search-agent 的 source 是外部世界,不是用户自家 deployment**——这是 §1 决策树的**隐含前提**。Sentry / grok-cli 都因架构错位被剔除(它们是 user 自家 introspection 工具,不是 search-agent 的 source)。判断新候选时多问一句:"这是查别人,还是查我自己?"

---

## 9. Sourcegraph 免费匿名层独家原语深挖

> 原 `learning-sourcegraph-niches.md`,合并入此 [2026-05-02]。写于 2026-04-26 · 实测 + 综合多轮分析。
>
> **学习目标**:1) 搞清 SG 免费匿名层"独家"的两条能力;2) 知道**什么时候用、什么时候别用、踩什么坑**;3) 能上手跑 demo,验证手感。
>
> **前置阅读**:`adapter-vs-skill.md`(已合并废弃) §2 / 本文 §5.1 #14 / `architecture.md`(已合并废弃) §3.9

### 9.0 TL;DR(回头先看这一段)

Sourcegraph 公网免费匿名层(无 auth、无登录)只有 **2 条原语**真正值得为它写 skill:

1. **`type:symbol`** — 跨所有 OSS 找一个名字的**定义**,带 `kind` / `containerName` / `file:line` 结构化字段
2. **`repo:has.file(path:X content:Y) select:repo`** — 找所有"有路径=X 且文件内容含 Y"的 **repo**(不是 file)

其他能力都不值得依赖(structural search 在免费层 timeout 残废、stars 过滤墙、关键词 ranking 烂)。

**经济价值**:这两条都把"agent 拿到结果后还要 LLM 二次判断"这一轮省掉了——具体省 token 数量见 §9.6。

**端点**:`https://sourcegraph.com/.api/search/stream`(SSE),不要用 GraphQL(anon 硬封顶 30)。

### 9.1 背景:为什么这两条特别?

任何代码搜索引擎本质做两件事之一:

| 类型 | 索引内容 | 返回什么 |
|---|---|---|
| **Content match**(GitHub Code Search、grep.app、searchcode) | 文件全文倒排 | "包含字符串 X 的文件" |
| **Symbol-aware**(SG `type:symbol`) | 通过 SCIP indexer 解析后的 AST 节点 | "X 这个符号被定义/引用的位置,带 kind 元数据" |
| **Repo-topology**(SG `repo:has.*`) | repo 元数据 + 文件路径×内容 | "满足复合 file/content 条件的 **repo 列表**" |

GitHub Code Search 始终是 Content match 一类。Sourcegraph 是少数公开提供 Symbol-aware 和 Repo-topology 的服务,而且免费匿名能用。

**这两类做的是 Content match 做不到的"结构化"事**——所以才独家。

### 9.2 原语 1:`type:symbol` 跨仓符号定义

#### 9.2.1 它返回什么

实测一例(查 `Tokenizer` 在 Rust 里的定义):

```bash
curl -sN "https://sourcegraph.com/.api/search/stream?q=$(printf %s 'type:symbol Tokenizer lang:rust' | jq -sRr @uri)"
```

事件流里关键的 `event: matches` 包含的字段(每个匹配):

```json
{
  "type": "symbol",
  "repository": "github.com/awslabs/duvet",
  "path": "tokenizer.rs",
  "branches": ["main"],
  "symbols": [
    {
      "name": "Tokenizer",
      "kind": "STRUCT",
      "containerName": "duvet::markdown::tokenizer",
      "url": "/github.com/awslabs/duvet/-/blob/...#L38:13-38:22",
      "line": 38
    }
  ]
}
```

**关键信号**:
- `kind`:`STRUCT` / `METHOD` / `FUNCTION` / `INTERFACE` / `CLASS` / `TYPE` / `FIELD` / `CONSTANT` 等
- `containerName`:这个符号在哪个 module / class / namespace 里
- `line` + `url`:精确到行号的跳转链

agent 拿到这些**不需要再 LLM 判断"这是不是定义"**——已经标注好了。

#### 9.2.2 GitHub 同题给什么(对比)

```bash
gh search code "Tokenizer" --language Rust
```

返回:

- `crates/foo/src/lib.rs` 第 12 行 — `use crate::tokenizer::Tokenizer;`(import 行)
- `crates/foo/src/main.rs` 第 87 行 — `let t = Tokenizer::new(...);`(调用方)
- `crates/foo/Cargo.toml` 第 5 行 — `tokenizer = "0.3"`(依赖声明)
- `crates/foo/tests/tok.rs` 第 23 行 — `// Tokenizer should handle UTF-8`(注释)
- `crates/foo/src/tokenizer.rs` 第 38 行 — `pub struct Tokenizer { ... }`(**真正的定义**)

agent 拿到这堆,要么二次 LLM 判断"这条是定义吗"(每条 ~200 token,5 条 1000 token,加上模型推理),要么瞎挑——实战通常瞎挑挑错。

#### 9.2.3 5 个真实 coding-agent 场景

| 场景 | query 模板 | agent 拿到能干嘛 |
|---|---|---|
| **API archaeology**——"我看到 stack trace 里 `Tokenizer::new`,这是哪个库?" | `type:symbol Tokenizer kind:struct lang:rust` | 一次列出所有 candidate 库;`containerName` 区分 `tantivy::tokenizer::Tokenizer` vs `huggingface::tokenizers::Tokenizer` |
| **Idiom 调研**——"我要写自己的 BloomFilter,看 5 个真实开源实现作参考" | `type:symbol BloomFilter kind:struct lang:rust` | 各 crate 实现一次性铺出来,直接拉源码对比 |
| **命名冲突 triage**——"两个 crate 都 export `Result`,出 trait conflict" | `type:symbol type Result kind:type lang:rust` | 看每个 crate 的 Result 各是什么 alias |
| **迁移辅助**——"我从 serde_json 迁到 simd-json,前者的 `Value::as_str()` 在后者怎么实现的?" | `type:symbol fn as_str lang:rust repo:^github\.com/simd-lite/.*$` | 直接跳到对应方法定义,看签名差异 |
| **学习"X 框架的标准用法"** | `type:symbol trait Handler lang:rust repo:^github\.com/tokio-rs/axum$` | 跨多个版本 / feature flag 的实现一次性可见 |

#### 9.2.4 Footgun(写 skill 时必须告诉 agent)

| 坑 | 现象 | 正确写法 |
|---|---|---|
| 加 `fn` 前缀 | `type:symbol fn parse_yaml` 返回 0 | 直接 `type:symbol parse_yaml`,kind 通过 `kind:function` 表达 |
| `kind:` 拼写 | 大小写敏感,`kind:Struct` 可能不命中 | 用全大写 `kind:STRUCT` 或全小写 `kind:struct`(实测两者都成,但保持一致) |
| 多语言一次查 | `type:symbol parse_yaml` 不带 `lang:` 时混杂 Ruby/Python/JS,signal 稀释 | 加 `lang:<X>` 收窄 |
| SCIP 覆盖偏科 | Java/TS/Python/Rust/Go/C++ 较成熟,Elixir/OCaml/Zig 稀疏 | 写 skill 时**显式说明覆盖语言**,小语种 fallback GH grep |

### 9.3 原语 2:`repo:has.file(path:X content:Y) select:repo` 反向依赖审计

#### 9.3.1 它返回什么

查"所有 Cargo.toml 里依赖 tantivy 的 repo":

```bash
curl -sN "https://sourcegraph.com/.api/search/stream?q=$(printf %s 'repo:has.file(path:Cargo\.toml content:tantivy) select:repo' | jq -sRr @uri)"
```

返回 35 个 repo 名单(实测),每条只有 repo URL + description + stars(如果 SG 有缓存)。**不是文件命中,是 repo 命中**——`select:repo` 是关键。

#### 9.3.2 GitHub 同题做不了的原因

| 工具 | 能做啥 | 缺啥 |
|---|---|---|
| `gh search code "tantivy" --filename Cargo.toml` | 单条件搜内容 + filename 过滤 | 返回 **file 命中**——同 repo 几十个文件占满 top-N;agent 要自己 dedupe |
| `gh search code` 多条件 | 不支持"路径=A **且** 内容=B"复合 | path 和 content 是同一个搜索字段,无法精确组合 |
| GitHub Dependents tab | repo X 被谁依赖 | UI-only **没 API**;只覆盖在 GitHub 上发布过 release 的包;精度差 |
| **libraries.io / deps.dev** | "X 依赖 Y" 但只看包管理器声明字段 | 不看文件里具体 content / 锁定版本 / feature flag;**只能查 manifest 类文件** |

#### 9.3.3 8 个真实 coding-agent 场景

| 场景 | query | 价值 |
|---|---|---|
| **CVE 影响审计**——"openssl-sys 0.9.x 有 CVE,Rust 生态谁中招?" | `repo:has.file(path:Cargo\.lock content:openssl-sys.0.9) select:repo` | 直接给受影响 repo;libraries.io 只看声明依赖,看不到锁定版本 |
| **库采用度调研**——"我开发的 crate 真实用户有哪些?" | `repo:has.file(path:Cargo\.toml content:my-crate) select:repo` | 比 crates.io 的 dependents tab 更广(含 fork、私有投影到 GH 的) |
| **Pattern mining**——"用 Next.js 14 server actions 的真实配置长什么样?" | `repo:has.file(path:next\.config\.js content:experimental.serverActions) select:repo` | 看真实生产项目怎么开 experimental 特性 |
| **Migration 评估**——"我要重命名公共 API,谁会爆?" | `repo:has.file(path:.+ content:my_old_function_name) select:repo` | 给 downstream 影响清单 |
| **CI/CD 模式调研**——"用 Cloudflare Workers 的 GH Actions 怎么写?" | `repo:has.file(path:\.github/workflows/.+\.ya?ml content:wrangler.deploy) select:repo` | path + content 复合,GH 做不到 |
| **Dotfiles archaeology**——"用 NixOS + Home Manager 配 nvim 的人怎么组织?" | `repo:has.file(path:flake\.nix content:home-manager) select:repo` | 找特定栈的配置模板 |
| **License 审计**——"哪些 repo 同时有 MIT 和 Apache 双授权?" | `repo:has.file(path:LICENSE-MIT) repo:has.file(path:LICENSE-APACHE) select:repo` | 多个 has.file 子句叠加 |
| **Security templating**——"业界 .env.example 怎么写 OPENAI_API_KEY?" | `repo:has.file(path:\.env\.example content:OPENAI_API_KEY) select:repo` | 调研标准模板 |

#### 9.3.4 Footgun

| 坑 | 现象 | 处理 |
|---|---|---|
| **shard timeout** | 大查询(如 `path:.+ content:<common keyword>`)20s+ 后只返回部分仓 | **必须解析响应里的 `progress.skipped[reason=shard-timeout]`**,告诉 host"这次没查全";否则 agent 把"漏的"当"没有的" |
| `repo:has.meta(stars >= N)` 不可用 | 免费匿名层返回 0 | 只能拿到 repo 列表后用 GitHub API 拉 stars;skill 文档要明说 |
| 路径正则要转义 | `path:Cargo.toml` 把 `.` 当通配,误命中 `Cargolytoml` | 用 `path:Cargo\.toml` |
| content 大小写敏感 | `content:tantivy` vs `content:Tantivy` 实测命中量不同 | 加 `case:no` 或用 `(?i)` 正则 |
| 复合子句 ≥3 个会显著变慢 | `repo:has.file(...)` × 4 可能 30s+ 或 timeout | 拆成两次,本地求交 |

### 9.4 端点 / 协议(用之前先搞清)

#### 9.4.1 必须用 stream API,不要用 GraphQL

| 维度 | Stream API | GraphQL `search` |
|---|---|---|
| URL | `https://sourcegraph.com/.api/search/stream` | `https://sourcegraph.com/.api/graphql` |
| 协议 | SSE(`event: matches\ndata: {...}\n\n`) | JSON-RPC over HTTPS |
| 匿名 result cap | **`count:all` 真有效**(实测 1.5M matches/19.8k repos) | **硬封顶 30**,无 cursor 可分页 |
| 包含 progress 元数据 | ✅(`event: progress` 里有 `skipped[]`) | ❌ |
| 解析复杂度 | 中(SSE,要按 event type 分发) | 低(标准 JSON) |

**结论**:agent harness 的 SG adapter 必须基于 stream API,不要被 GraphQL 简单性诱惑。

#### 9.4.2 Stream 事件类型

```
event: matches      ← 实际命中,你要的
data: {"type":"symbol","repository":"...","symbols":[...]}

event: progress     ← 关键!里面有 skipped[]
data: {"matchCount":1234,"skipped":[{"reason":"shard-timeout","title":"...big repo missing..."}]}

event: filters      ← 提供给 UI 的 facet,可忽略
data: [...]

event: done         ← 流结束
data: {}
```

agent 必须收集所有 `matches` + 检查最后的 `progress.skipped`,才能给 host 报"是否查全"。

### 9.5 Skill 文件应该怎么写(参考模板)

```markdown
# When to use Sourcegraph (free anonymous tier only)

You **MUST** use the Sourcegraph stream API
(`https://sourcegraph.com/.api/search/stream`) — never the GraphQL endpoint
(it caps anonymous results at 30 with no usable cursor).

## Trigger 1 — Cross-repo SYMBOL DEFINITION lookup

If user asks "where is X defined" / "show me implementations of X" /
"find all definitions of <name>" — across multiple repos or all of OSS:

  q = `type:symbol <name> [kind:STRUCT|METHOD|FUNCTION|TYPE] [lang:<X>] [repo:^...$]`

DO NOT prefix with `fn`/`def`/`class` — that breaks the symbol parser.
Use `kind:` filters instead.

After parsing matches, present `name + kind + containerName + file:line + url`
to the user. Do NOT additionally guess what's a definition; SCIP already classified.

## Trigger 2 — Reverse dependency / topology query

If user asks "which repos depend on X" / "which repos use file pattern Y with
content Z" / "find all CI configs that ..." / "find all repos that contain
both file A and file B":

  q = `repo:has.file(path:<regex> content:<keyword>) [repo:has.file(...)]* select:repo`

Always pass `select:repo` to fold to repo-level results (otherwise you get
file-level which causes deduplication overhead).

## MUSTs and DO-NOTs

MUST:
- Always check `progress.skipped[]` in the final progress event.
  If reason is `shard-timeout`, warn the host: results may be incomplete.
- Always escape regex chars in `path:` (e.g., `Cargo\.toml` not `Cargo.toml`).
- Pass `case:no` if case-insensitive matching is desired.

DO NOT:
- Use `patterntype:structural` on the public anonymous tier — it silently
  shard-times-out at scale (~60s, 0 results returned).
- Use `repo:has.meta(stars >= N)` — it returns 0 on free anon (enterprise feature).
  For star-filtered repo discovery, fall back to the GitHub adapter.
- Use Sourcegraph for general code search ("find files containing X") —
  GitHub Code Search via PAT is faster (1-3s vs 7-19s) and more reliable.
- Promise non-GitHub platform coverage. Codeberg / SourceHut /
  GitLab self-hosted forges are not indexed.
```

约 50 行,包含全部触发 + 4 个硬约束 + 4 个反模式。Progressive 加载,只在相关 query 触发时进 host context。

### 9.6 经济性论证(为什么 30-50 行 markdown 划算)

设一次"查 `parse_yaml` 在哪里定义的"任务在 agent 里的 token 成本(粗估,Claude Sonnet 4.6 单价):

**不用 SG 的路径**
1. agent 调 `gh search code "def parse_yaml" --language Python` → 返回 30 条 file 命中,大约 5K tokens(JSON)
2. agent 用 LLM 判断每条"是定义还是引用",30 条 × 200 tokens prompt = 6K tokens 输入
3. LLM 输出筛选结果 ~500 tokens
4. **总:~12K tokens + 2 轮 round-trip**

**用 SG 的路径**
1. agent 调 SG stream `type:symbol parse_yaml lang:python` → 返回 20 条已分类的 symbol,~2K tokens
2. agent 直接挑 `kind:METHOD` 的几条返回给 user,无需 LLM 二次判断
3. **总:~2K tokens + 1 轮 round-trip**

**差**:大约 10K token + 1 轮延迟 / 任务。

如果一周用到 10 次这类 query,就是 100K token / 周。skill 文档约 1.5K token(progressive 加载,只在 trigger 命中时进 context)。**净收益约 50-60x**。

反向依赖审计同理,而且因为 GH 没有等价能力(只能逐 file 自己 dedupe),省的 token 更多。

### 9.7 何时**不**用 SG(也很重要)

| 任务 | 用啥 | 理由 |
|---|---|---|
| 通用 keyword 代码搜索("含某字符串的文件") | **GitHub Code Search + PAT** | 1-3s vs SG 7-19s,且 GH 有 stars/license/size 过滤 |
| Repo discovery 按"概念/意图"找 repo | **GitHub Search API + skill 教 query rewriting + HN/Reddit cross-ref** | SG 关键词 ranking 烂(实测漏 tantivy/meilisearch) |
| 找带 stars 阈值的 repo | **GitHub adapter** | SG 免费匿名 stars 过滤完全无效 |
| 重度 structural pattern(`Result<:[T], :[E]>` 这种) | **本地 ast-grep / semgrep** | SG 免费层 structural search shard timeout 不可用 |
| 深度 repo Q&A | **DeepWiki MCP** | SG 没这能力 |
| 非 GitHub 平台(Codeberg / SourceHut) | **直接调对应平台 API** | SG 不索引 |

### 9.8 上手 demo(回头自己跑一遍验证手感)

#### 9.8.1 Symbol search 实跑

```bash
# 跨仓找 BloomFilter 的 Rust 定义
Q='type:symbol BloomFilter kind:struct lang:rust'
curl -sN "https://sourcegraph.com/.api/search/stream?q=$(printf %s "$Q" | jq -sRr @uri)" \
  | grep -E '^(event|data):' | head -50
```

预期看到 `event: matches` + `data: {"type":"symbol","symbols":[...]}` 多条,以及最后 `event: progress` 包含 matchCount。

#### 9.8.2 反向依赖审计实跑

```bash
# 找所有 Cargo.toml 里依赖 tantivy 的 repo
Q='repo:has.file(path:Cargo\.toml content:tantivy) select:repo'
curl -sN "https://sourcegraph.com/.api/search/stream?q=$(printf %s "$Q" | jq -sRr @uri)" \
  | grep -E '^data:' | head -30
```

预期返回 ~30+ repo 列表。注意检查最后的 `progress` 事件里有没有 `skipped`——大概率有,会包含若干被 shard timeout 的大库。

#### 9.8.3 复合反向依赖(进阶)

```bash
# 找所有有 LICENSE-MIT 又有 LICENSE-APACHE 的 repo(双授权)
Q='repo:has.file(path:LICENSE-MIT) repo:has.file(path:LICENSE-APACHE) select:repo'
curl -sN "https://sourcegraph.com/.api/search/stream?q=$(printf %s "$Q" | jq -sRr @uri)" \
  | grep -E '^data:' | wc -l
```

预期一个数字——双授权在生态里其实很常见,看看到底多少。

#### 9.8.4 footgun 验证

跑这一条**应该返回 0**(`fn` 前缀坏掉):

```bash
Q='type:symbol fn parse_yaml lang:python'
curl -sN "https://sourcegraph.com/.api/search/stream?q=$(printf %s "$Q" | jq -sRr @uri)" \
  | grep matchCount
```

vs 这一条(去掉 `fn` 前缀)应该返回多条:

```bash
Q='type:symbol parse_yaml lang:python'
curl -sN "https://sourcegraph.com/.api/search/stream?q=$(printf %s "$Q" | jq -sRr @uri)" \
  | grep matchCount
```

亲手验证 footgun 是真实的——印象会比看文档深得多。

### 9.9 延伸学习(如果想再深一层)

| 话题 | 资源 |
|---|---|
| SCIP 协议本身(SG 的符号搜索之所以能工作的协议) | https://github.com/sourcegraph/scip |
| 各语言的 SCIP indexer | scip-java / scip-typescript / scip-python / scip-clang(Apache-2.0,见 §5.1 #14) |
| zoekt(SG 用的 trigram 搜索引擎) | https://github.com/sourcegraph/zoekt |
| Sourcegraph 查询语法完整文档 | https://docs.sourcegraph.com/code_search/reference/queries |
| `repo:has.*` 全集 | https://docs.sourcegraph.com/code_search/reference/queries#repo-has-predicate |
| Stream API 协议 | https://docs.sourcegraph.com/api/stream_api |

### 9.10 一句话回顾

> **SG 免费匿名层,只为这两条原语而留:`type:symbol`(替你做了符号 vs 引用的判断)和 `repo:has.file(path:X content:Y) select:repo`(独家的 repo 拓扑过滤)。其余 95% 的代码搜索需求走 GitHub。这两条用 stream API、解 `progress.skipped`、躲 4 个 footgun,就完整覆盖。**
