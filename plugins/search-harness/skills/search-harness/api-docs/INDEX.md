# API Docs Index — sources.md → ./api-docs/

抓取于 2026-05-04，覆盖 sources.md §1+§2+§3 全部 24 个 source。Agent 通过 CLI / HTTP 调用时需要的端点、参数、auth、rate-limit 信息都在各文件里。

主要 fetcher：TinyFish `fetch_content`。失败回退：`r.jina.ai`。

---

## §1 Adapters (18)

| # | File | Source | Auth | bytes | Quality |
|---|---|---|---|---|---|
| 1 | `01-github.md` | GitHub Search REST API | `$GITHUB_TOKEN` | 56k | ✅ full |
| 2 | `02-gitlab.md` | GitLab REST API index | `$GITLAB_TOKEN` | 18k | ✅ full |
| 3 | `03-stackexchange.md` | Stack Exchange `/search/advanced` | anon | 3k | ⚠ thin — 单端点页，sites 列表/filter encoding 见 https://api.stackexchange.com/docs |
| 4 | `04-hn-algolia.md` | HN Algolia search | anon | 5k | ✅ enough |
| 5 | `05-reddit.md` | Reddit dev API | anon (UA) / OAuth | 74k | ✅ full |
| 6 | `06-arxiv.md` | arXiv API user manual | anon | 41k | ✅ full |
| 7 | `07-openalex.md` | OpenAlex `/works` search | anon (mailto polite pool) | 13k | ✅ full |
| 8 | `08-openreview.md` + `08c-openreview-py.md` | OpenReview docs root + openreview-py SDK index | anon | 6k+8k | ⚠ docs site 是 SPA，REST 字段稀疏；SDK reference 是主用 |
| 9 | `09-libraries-io.md` | libraries.io API | `?api_key=` | **3.1M** | ⚠ 单页 SPA full dump，需后续切分 |
| 10 | `10-huggingface.md` | HF Hub API root | anon / `$HF_TOKEN` | 2k | ⚠ shallow — 主子页 `/docs/hub/api` 跳转后内容少；可能需 /docs/api-inference 补 |
| 11 | `11-nvd.md` | NVD CVE 2.0 API | anon (key 推荐) | 51k | ✅ full (via r.jina.ai — TinyFish proxy_error) |
| 12 | `12-twitterapi.md` | twitterapi.io | `X-API-Key: $TWITTERAPI_IO_API_KEY` | 2k | ⚠ thin — `/introduction` 页；具体端点 (`/twitter/tweet/advanced_search` 等) 需逐一 fetch |
| 13 | `13-osv.md` + `13b-osv-query.md` | OSV.dev API root + `POST /v1/query` | anon | 1k+7k | ✅ 13b 是核心端点 doc |
| 14 | `14-deps-dev.md` | deps.dev v3 API | anon | 58k | ✅ full |
| 15 | `15-lobsters.md` | Lobste.rs (.json convention) | anon (UA) | 9k | ✅ enough — README，无正式 API doc |
| 16 | `16-bluesky.md` | Bluesky AT Protocol HTTP reference | `$BLUESKY_HANDLE` + `$BLUESKY_APP_PASSWORD` → `accessJwt` | 76k | ✅ full |
| 17 | `17-sourcegraph.md` | Sourcegraph stream search API | anon | 9k | ✅ full |
| 18 | `18-exa.md` | Exa `/search` reference | `x-api-key: $EXA_API_KEY` | 10k | ✅ full |

## §2 Co-install (4)

| # | File | Tool | bytes | Quality |
|---|---|---|---|---|
| 19 | `19-context7.md` | Context7 CLI (`ctx7`) | 6k | ✅ enough — GitHub README |
| 20 | `20-playwright.md` | Playwright Test CLI | 23k | ✅ full |
| 21 | `21-deepwiki.md` | DeepWiki MCP | 2k | ⚠ thin — 单页介绍；具体 tools 已在 MCP server instructions 里 |
| 22 | `22-yt-dlp.md` | yt-dlp | 174k | ✅ full README |

## §3 Docs scrapers (2)

| # | File | Tool | bytes | Quality |
|---|---|---|---|---|
| 23 | `23-jina-reader.md` | Jina Reader (`r.jina.ai/<url>`) | 29k | ✅ full |
| 24 | `24-firecrawl.md` | Firecrawl `/scrape` | 12k | ✅ full |

---

## 待跟进（转 skills 前）

1. **§1 #3 Stack Exchange** — 补 `/docs` 根页（sites 列表 / filter system / quota）
2. **§1 #9 libraries.io** — 3.1M 单页需切分（目前是全 SPA 渲染输出）
3. **§1 #10 HuggingFace** — `/docs/hub/api` 太浅，补 `/docs/api-inference` 等子页
4. **§1 #12 twitterapi.io** — 仅有 `/introduction`；逐一抓取每个端点页（`get_tweet_advanced_search` URL pattern 待确认）
5. **§1 #8 OpenReview** — REST 端点参数稀疏；考虑直接读 openreview-py 源码或 GitHub schema

## Auth 现状（用户已配置）

- API key:  `$GITHUB_TOKEN` `$GITLAB_TOKEN` `$TWITTERAPI_IO_API_KEY` `$EXA_API_KEY` `$FIRECRAWL_API_KEY` `$NVD_API_KEY`(推荐) `$HF_TOKEN`(可选) `$LIBRARIES_IO_API_KEY`(`/search` 端点必需)
- Session: `$BLUESKY_HANDLE` + `$BLUESKY_APP_PASSWORD` → 换 `accessJwt`
- Anon: HN Algolia / Reddit(UA) / arXiv / OpenAlex / OpenReview / OSV / deps.dev / Lobste.rs(UA) / Sourcegraph / Stack Exchange / Jina Reader
