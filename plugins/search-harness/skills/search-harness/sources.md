# Sources

## 1. Phase 1 ★ adapters(18)

| # | 来源 | 端点 | Auth | 独家信号 |
|---|---|---|---|---|
| 1 | **GitHub** | `https://api.github.com/search/{repositories,code,issues}` + `gh` CLI | `Authorization: token $GITHUB_TOKEN` | `stars` / `forks` / `license` / `topic`;Code Search;Discussions / Gists 走 `api.github.com/graphql` |
| 2 | **GitLab**(多实例) | `https://{gitlab.com,gitlab.gnome.org,gitlab.freedesktop.org}/api/v4/...` | `PRIVATE-TOKEN: $GITLAB_TOKEN` | `stars` / `license` / `pushed_at`;`?license=true` 需 N+1 detail |
| 3 | **Stack Exchange**(多站) | `https://api.stackexchange.com/2.3/search/advanced?site={stackoverflow,dba,serverfault,codereview,ai}` | anon | `vote` / `is_accepted` / `score` |
| 4 | **HN Algolia** | `https://hn.algolia.com/api/v1/search?query=&numericFilters=created_at_i>...,points>...` | anon | `created_at_i>` × `points>` 时间窗 + 票数过滤 |
| 5 | **Reddit** | `https://www.reddit.com/r/{sub}/search.json?q=&t=year&restrict_sr=1` | anon(UA 必填),OAuth 升 60-100 req/min | `subreddit` / `upvote_ratio` / `score` |
| 6 | **arXiv** | `http://export.arxiv.org/api/query?search_query=&start=&max_results=` | anon | `abstract` / `category` / 时间窗;Atom XML;多词须 `%22quote%22` |
| 7 | **OpenAlex** | `https://api.openalex.org/works?search=&filter=...` | anon,UA 加 `mailto:` 进 polite pool | `fwci` + `citation_normalized_percentile.is_in_top_1_percent` + `concepts` + `counts_by_year` + `is_retracted` + `referenced_works` |
| 8 | **OpenReview** | `https://api2.openreview.net/notes/search` → `notes?forum=<id>` | anon | 公开评审 / decision / 反驳;二段抓取 |
| 9 | **libraries.io** | `https://libraries.io/api/{platform}/{name}` + `/api/search?platforms=&q=&api_key=...` | detail anon / `/search` 需 key | `SourceRank` + `dependent_repos_count` |
| 10 | **Hugging Face Hub** | `https://huggingface.co/api/{models,datasets,spaces}?search=` + `/api/daily_papers` | anon | `downloads` + `likes` + `pipeline_tag` |
| 11 | **CVE / NVD** | `https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=&keywordSearch=&pubStartDate=` | anon(key 推荐) | CVSS + CWE + CPE 版本树 + `references[]` |
| 12 | **twitterapi.io** | `https://api.twitterapi.io/twitter/{tweet/advanced_search,user/info,user/last_tweets,tweet/replies}` | `X-API-Key: $TWITTERAPI_IO_API_KEY` | `viewCount` + `isBlueVerified` + `likeCount` + `retweetCount` + `pinnedTweetIds[0]` + `replies[]` |
| 13 | **OSV.dev** | `POST https://api.osv.dev/v1/query` body `{"package":{"name","ecosystem":"PyPI\|npm\|Go\|Maven\|crates.io\|RubyGems\|Hex\|NuGet"},"version"}` + `/v1/querybatch` + `GET /v1/vulns/{id}` | anon | package+version → vulns 反向映射;CVSS 3.1 + `affected[]` 版本树 |
| 14 | **deps.dev**(Google OSI) | `GET https://api.deps.dev/v3/systems/{npm,pypi,maven,go,cargo,nuget,rubygems}/packages/<name>/versions/<ver>` | anon | 7 ecosystem 一个 schema;`licenses`(SPDX)+ `advisoryKeys`(直链 OSV)+ `links.SOURCE_REPO` + `slsaProvenances` + `attestations` |
| 15 | **Lobste.rs** | `https://lobste.rs/{hottest,newest}.json` + `/t/<tag>.json` | anon(UA 推荐) | tag + `score` + `comment_count` + `submitter_user` |
| 16 | **Bluesky**(AT-Protocol) | 1️⃣ `POST https://bsky.social/xrpc/com.atproto.server.createSession` `{identifier,password}` 拿 `accessJwt`<br>2️⃣ `GET /xrpc/app.bsky.feed.{searchPosts,getAuthorFeed,getPostThread}` + `app.bsky.actor.{searchActors,getProfile}` | `Authorization: Bearer $accessJwt`(从 `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD` 换) | `likeCount` + `repostCount` + `replyCount` + `did`;authed searchPosts 无 rate limit |
| 17 | **Sourcegraph stream** | `GET https://sourcegraph.com/.api/search/stream?q=context:global+...` | anon(`Accept: text/event-stream`) | 跨 2M+ OSS repo trigram + facet(`repo:has.topic` / `lang:` / `type:symbol`)+ commit SHA + lineNumber |
| 18 | **Exa** | `POST https://api.exa.ai/search` body `{query, type:"auto\|fast\|instant\|deep-lite\|deep\|deep-reasoning", num_results, contents:{highlights\|text\|summary}, outputSchema?, maxAgeHours?, includeDomains?, excludeDomains?}` + `POST /contents` for known URLs | `x-api-key: $EXA_API_KEY` | neural 语义搜索(非词法);**`outputSchema` 结构化 JSON + 字段级 grounding citations**;`type:deep` multi-hop(WebWalker 81%);`maxAgeHours` 强制 livecrawl freshness;Code/People/Company vertical |

twitterapi.io free-tier QPS = 1 req / 5s,串行 + sleep 5s。

---

## 2. Co-install(全局 CLI 优先 / MCP 仅在无 CLI 替代时)

| 工具 | 维护方 | 形态 | 用途 | 安装 |
|---|---|---|---|---|
| **Context7 CLI**(`ctx7`) | Upstash | CLI | 主流库 docs grounding;`ctx7 library <name> <q>` + `ctx7 docs <libId> <q>` | `npm install -g ctx7 && npx ctx7 setup` |
| **Playwright CLI** | Microsoft | CLI | browser automation / JS-rendered scrape / login walls | `npm install -g playwright && npx playwright install chromium` |
| **DeepWiki MCP** | Cognition / Devin | MCP | 50k+ OSS repo AI wiki + Q&A | `claude mcp add --transport http deepwiki https://mcp.deepwiki.com/mcp` |
| **yt-dlp** | yt-dlp 团队 | CLI | `yt-dlp "ytsearch5:..."`(搜)+ `--dump-single-json <url>`(metadata)+ `--write-auto-sub --sub-langs en --sub-format vtt`(transcript);1000+ 视频站 | `brew install yt-dlp` |

---

## 3. 官方开发者文档

| 输入形态 | 工具 | 端点 / 命令 | Auth |
|---|---|---|---|
| 主流库 docs grounding | Context7 CLI(§2) | `ctx7 docs <libId> <q>` | OAuth |
| 任意静态 URL → markdown(RFC / mkdocs / sphinx / 静态 HTML) | **Jina Reader** | `curl https://r.jina.ai/<url>` | 无 key |
| SPA / login wall / JS-heavy 站(Mintlify / GitBook 类) | **Firecrawl** | `POST https://api.firecrawl.dev/v1/scrape` body `{url, formats:["markdown"]}` | `Authorization: Bearer $FIRECRAWL_API_KEY` |

> **整站索引 / vendor docs 抓取的 ground-api skill 优先级**(2026-05-05 Wave 2 16 vendor panel 严格命中率,详见 `reference/batch/wave2-vendor-probe/REPORT-wave2.md`):
>
> | # | 路径 | 命中率 | 说明 |
> |---|---|---|---|
> | 1 | `curl <root>/llms-full.txt`(< 5MB)| **44%** 实用区间 | 中型 vendor 单 curl 直入 LLM context (OpenAlex 218KB/Mistral 1MB/Exa 1.1MB/Firecrawl 1.5MB/OpenAI 1.7MB/Cohere 3MB) |
> | 2 | `curl <root>/llms.txt` 索引 + 选择性 jina | **87%** | 巨型 llms-full.txt 切片入口 (Anthropic 58MB / Cloudflare 49MB) |
> | 3 | `robots.txt` → `sitemap.xml` + jina(2 worker + backoff)| **88%** | Stripe / Vercel / GitHub 类。**注意 Groq 的 sitemap 在根域,要看 robots.txt** |
> | 4 | root HTML 抽 `<a href>` 一层递归 + jina | 100% | sitemap 也 miss(罕见) |
> | 5 | Firecrawl `/scrape` `/crawl` | 100% | 1-4 都失败 + JS-only / 反爬。99 credits/100 页 |
>
> **`llms.txt` 是 [llmstxt.org](https://llmstxt.org) 社区事实标准**(2025-2026 形成),非 Mintlify 专利 —— Anthropic/Cohere/OpenAI/Mistral 等非 Mintlify host 也 ship。**Mintlify host 命中率 18%,llms.txt 命中率 87%,后者 4.8× 前者**
>
> **`/api-reference/openapi.json` 真 JSON 命中率仅 6%**(16 vendor 中只 OpenAlex 真 ship JSON;Anthropic/Cohere/Vercel 都返 SPA HTML 假阳性)。要时单独 try `/openapi.{json,yaml,yml}`、`/api-reference/openapi.json`,严格验 `Content-Type: application/json`,命中即用
>
> **DIY Jina anon 单 IP 配额警示**:6 并发立即 429,需 2 worker + exponential backoff(实测 OpenAlex 94 页 ~5min,Groq 10 页 37s)。Firecrawl hosted 跨用户 IP 池一次拿全站,但烧 credits

---

## 4. Agent 自带 web search(last-resort fallback)

§1 #18 Exa 失败时,host LLM 自带 `web_search` 工具承接(Claude / Gemini / GPT 都自带)。**不在我们调用清单**——search-agent 用尽时的 graceful degradation。
