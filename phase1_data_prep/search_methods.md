# Search Methods

This document defines how the daily scan should search before scoring. It is intentionally source-specific because each platform exposes different signal quality.

## Search Layers

### 1. Native Trend Pull

Use source-native freshness or trend endpoints first:

- GitHub Trending daily page.
- HN Algolia `search_by_date`.
- Product Hunt Atom feed.
- Hugging Face public model API sorted by likes or last modified.
- arXiv Atom API sorted by submitted date.
- V2EX hot topics API.
- 36Kr RSS feed.

This layer is cheap and should not involve LLM calls.

### 2. Query Expansion Pull

Run a controlled keyword set only after native trend pull. The MVP keyword families are:

| Family | English Queries | Chinese Queries | Purpose |
| --- | --- | --- | --- |
| Agent / workflow | AI agent, coding agent, browser agent, workflow automation, autonomous agent | 智能体, 自动化, 工作流, 代码助手 | Find agentic products and repos |
| OSS / infra | open source AI, local LLM, MCP, RAG, vector database, evals, observability | 开源, 本地大模型, 知识库, 向量数据库, 评测, 可观测性 | Find infrastructure opportunities |
| Demo signal | demo, playground, live preview, try it, screenshot, GIF, video, examples | 演示, 试用, 截图, 视频, 案例 | Detect 45-60 second video feasibility |
| Buyer pain | automate, reduce cost, replace, faster, privacy, self-hosted, no-code | 降本, 提效, 替代, 私有化, 自托管, 无代码 | Detect practical workflow pain |
| Commercial | SaaS, API, pricing, launch, beta, waitlist, sponsor, affiliate | 付费, 融资, 商业化, 企业服务, SaaS | Map ad proximity and buyer category |

### 3. Cross-Source Validation

For each Stage 1 survivor, search for the same entity across at least two other source families:

- repo name or domain in HN;
- repo/product name in Product Hunt;
- model/paper title in Hugging Face or arXiv;
- project/product name in V2EX or 36Kr for Chinese-market relevance.

Do not require two independent sources for all candidates. Require it only when a claim is strong enough to appear in the final video.

### 4. Entity-Seeded Search

When a source yields a strong item, generate stable entity keys:

- GitHub: `owner/repo`, repo name, domain from homepage.
- Product Hunt: product slug, product domain, maker name.
- Hugging Face: `author/model`, model family, paper link.
- arXiv: arXiv ID, title noun phrases, author group.
- HN/V2EX/36Kr: canonical URL domain, exact title, named product.

Use these keys to look for duplicate or corroborating records.

## Source-Specific Methods

### GitHub

Primary:

- scrape daily Trending for repository name, description, language, stars, forks, stars today;
- query GitHub Search API for new repositories by topic and creation date.

Fallback:

- Search API query examples:
  - `topic:ai created:>{date_minus_7d}`
  - `topic:agents created:>{date_minus_14d}`
  - `topic:mcp created:>{date_minus_30d}`
  - `browser agent in:name,description,readme`

Notes:

- Unauthenticated Search API has a low limit. Use it only for expansion or fallback.
- Readme fetch should happen only for Stage 1 survivors.

### Hacker News

Primary:

- `search_by_date` with keyword batches and a 48-hour window.

Ranking hints:

- `points`, `num_comments`, and title phrasing are useful.
- `Show HN` and `Launch HN` are stronger demo signals than generic discussion posts.
- A high comment count with skeptical comments can still be useful as a pain or caveat signal.

### Product Hunt

Primary:

- use Atom feed for no-auth MVP.

Later:

- GraphQL API if API credentials are available and upvote/comment fields are needed.

Ranking hints:

- Treat launch copy as marketing-biased.
- Prefer products with live demo, public pricing, screenshots, or a visible workflow.

### Hugging Face

Primary:

- model API with `sort=likes`, `sort=lastModified`, and targeted searches.

Ranking hints:

- Likes and downloads are engagement signals, not proof of practical value.
- Spaces, demos, Gradio links, model cards, and examples raise demo availability.

### arXiv

Primary:

- query `cs.AI`, `cs.LG`, `cs.CL`, `cs.CV` by submitted date.

Ranking hints:

- Papers without code, demo, benchmark table, or public model link should rarely pass demo scoring.
- Treat performance numbers as claim-risk until checked against the paper or official project page.

### V2EX

Primary:

- hot topics API.

Ranking hints:

- Questions, complaints, and tool-replacement discussions are useful pain signals.
- Replies count is useful engagement but not authority.

### 36Kr

Primary:

- RSS feed.

Ranking hints:

- Useful for business and funding context.
- Funding, revenue, customer, and adoption claims must be verified before script use.

## Stop Conditions

Stop expanding a daily scan when:

- 100 raw candidates have been collected; or
- 30 normalized candidates survive cheap filters; or
- all P0/P1 sources have been scanned and fewer than 30 candidates remain.

The MVP should prefer a reliable 30-item daily pool over a fragile 300-item crawl.
