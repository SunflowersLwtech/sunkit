---
name: search
description: >-
  Single entry point for finding things on the web and reading web pages: quick
  lookups, current facts and news, filtered or site-specific search, reading or
  quoting a URL, multi-step research, list-building, enrichment and
  structured-output research. Fires on
  「搜一下」「查一下网上」「最新的…是什么」「帮我找资料」「调研一下」「深挖」「找出所有」
  「给我讲讲这个链接」「这篇文章讲了什么」「原文怎么写的」「逐字」「核对这句引用」
  「verbatim」「股价/行情/财报/汇率/宏观数据」「这个 CVE / IP / 域名安全吗」「查专利/法条/判例」
  「论文引用/PubMed」「查这家公司/工商/招聘」「航班/航班动态」「空气质量」「Steam 价格」,
  any x.com or twitter.com URL, "search the web", "look up", "latest news on",
  "research this", "find everything about", "find me all", "deep dive on",
  "literature review", "competitive analysis", "lead generation",
  "explain this link", "is this quote real". Not for the user's own notes or
  past decisions (obsidian-wiki), pages that need a login, or calling an
  API endpoint (curl/xh).
metadata:
  role: domain-router
---

# search — 统一入口 / router

唯一职责：按任务形态选工具，需要细节时再读对应成员的 SKILL.md，然后退出。分工铁律：
**有结构化答案或标识符的问题归 anysearch，开放网页的问题归 Exa**。一方不可用就用另一方，
不要问用户；在回答里说明用了哪个。

| 任务形态 | 用什么 |
|---|---|
| **有结构化答案或标识符**：行情/财报/宏观/汇率、CVE 与 IP/域名/哈希情报、专利、法条/判例/立法、论文/引用/PubMed/临床试验/药品、公司工商/招聘/人脉、航班与航班动态、空气质量、Steam、农业数据 | `skills/anysearch/SKILL.md`：先 `get_sub_domains`，再带 `--tag`/`--params` 搜（17 个领域 40 个子领域） |
| 拿不准算通用还是垂直 | anysearch `batch_search` 混合：1 条通用 + N 条垂直并行 |
| 开放网页：一般搜索、最新新闻、找某类页面 | `mcp__exa__web_search_exa`（anysearch 的通用搜索是同级替补） |
| 限定站点/日期/类别、排除某站、抓一个站的子页面 | `mcp__exa__web_search_advanced_exa` |
| 读一个 URL 的内容（只取事实） | `mcp__exa__web_fetch_exa`，`maxCharacters` 设得远大于页面（默认 3000 静默截断） |
| **要引用、复述论证、核对原话**、x.com 链接 | 先读 `skills/verbatim-fetch/SKILL.md`（哪一级取原文、各级丢什么） |
| 一次搜索不够：调研、文献综述、「找出所有 X」、竞品分析 | `skills/exa-research/SKILL.md`（派子 agent 编排） |
| 要结构化输出、清单构建/补全字段、外部数据源（fiber、financial_datasets 等） | `skills/exa-agent/SKILL.md`（`agent_run`，按量计费） |
| 需要登录的页面 | 交给真实浏览器会话（你的浏览器自动化 skill，如有） |
| 一方不可用（报错/429/没加载） | Exa ⇄ anysearch 互为兜底 → 再不行内置 `WebSearch`/`WebFetch` |

## 边界

- 上表的成员 skill 在 skill 列表里是隐藏的（frontmatter 带 `disable-model-invocation`）：
  **按路径 Read 它们的 SKILL.md，不要用 Skill 工具调**。
- `WebFetch` 返回的是小模型的摘要，不是原文——任何要引用的场合都走 verbatim-fetch。
- **实时数值别从网页搜索结果里读**：搜索索引给的是页面快照，实测查一只股票的收盘价
  会拿到两页停留在不同历史日期的结果，其中一页还标着「今天」；垂直接口返回的是结构化
  日线（约一个交易日延迟）。

## 接入（用户自己配，本插件不内置任何账号或 key）

- **Exa**：在你自己的 MCP 配置里加 Exa 的 MCP server——hosted 地址
  `https://mcp.exa.ai/mcp`（OAuth 登录），或自带你的 API key 的自托管/代理方式。Auth 或
  限流出错时把修法（优先 OAuth）报给用户，不要默默降级成普通网页搜索。Exa MCP 没配也不影响
  其它行：anysearch 加内置 `WebSearch`/`WebFetch` 仍然可用。
- **anysearch**：匿名可用（限速较低）；要更高限速按 anysearch skill 自己的说明配置
  `ANYSEARCH_API_KEY`。key 不要贴在对话里。

成员来源见插件 README（verbatim-fetch 是本仓库自己的，anysearch 与
exa-research / exa-agent 是 vendored，各自带 LICENSE 和出处说明）。
