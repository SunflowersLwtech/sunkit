# Endpoint Probe

Probe time: 2026-05-28 around 12:07 Asia/Kuala_Lumpur.

These probes verify only basic reachability from this machine. They do not prove long-term API stability or field completeness.

| Source | Probe | Result | Notes |
| --- | --- | --- | --- |
| GitHub Trending | `GET https://github.com/trending?since=daily&spoken_language_code=` | `200 OK` | HTML reachable with browser-like user agent. |
| GitHub Search API | `GET https://api.github.com/search/repositories?q=topic:ai+created:>2026-05-21&sort=stars&order=desc&per_page=1` | `200 OK` | Unauthenticated search limit observed as `10`; use sparingly or add token. |
| Hacker News Algolia | `GET https://hn.algolia.com/api/v1/search_by_date?tags=story&query=AI&hitsPerPage=1` | `200 OK` | JSON API reachable. |
| Product Hunt Feed | `GET https://www.producthunt.com/feed` | `200 OK` | Atom feed reachable; Cloudflare cookie set but response returned. |
| Hugging Face Models API | `GET https://huggingface.co/api/models?sort=likes&direction=-1&limit=1` | `200 OK` | Public API reachable; rate header showed remaining quota in fixed window. |
| arXiv API | `GET https://export.arxiv.org/api/query?search_query=cat:cs.AI&start=0&max_results=1&sortBy=submittedDate&sortOrder=descending` | `200 OK` | HTTP version redirects to HTTPS; use HTTPS directly. |
| V2EX Hot API | `GET https://www.v2ex.com/api/topics/hot.json` | `200 OK` | JSON API reachable; rate-limit headers present. |
| 36Kr RSS | `GET https://36kr.com/feed` | `200 OK` | RSS feed reachable. |

## Immediate Source Decisions

- Use Product Hunt feed in MVP, not GraphQL, because feed is no-auth and reachable.
- Use arXiv HTTPS endpoint directly to avoid redirect handling noise.
- Use GitHub Search API only as fallback or query expansion unless a token is configured.
- Treat V2EX and 36Kr as P1 sources: useful for Chinese relevance but not required for the first 30-candidate P0 pool.
