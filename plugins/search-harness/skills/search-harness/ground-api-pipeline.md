# API Docs 抓取 Pipeline(综合 Wave 1+2 + 5 路径对照实测 + 行业 cross-ref)

**版本**:1.0(2026-05-06)
**对应 strategy**:[`ground-api-strategy.md`](./ground-api-strategy.md)(高层定位 + 行业横向对照)
**实证基础**:`reference/batch/{firecrawl-openalex,agent-diy-openalex,wave2-vendor-probe,five-path-openalex-auth}/`(.gitignore 排除,本地保留)
**用户 query 形态**:vendor X 的某个 API 信息(认证 / 端点 / schema / 错误码 / 限流等)
**承袭决议**:`domain-knowledge.md` §5.1 #25(5 路径矩阵)、§5.1 #24(openapi-to-skills demote)、§1.3(ground-api 用例)
**行业一致性**:已 cross-ref [llmstxt.org](https://llmstxt.org) 标准、Mintlify 实施、Cursor/Context7/Aider 消费侧实践(详见 [strategy.md §2](./ground-api-strategy.md))

---

## 1. 一图看懂(决策树)

```
收到 query: "vendor X 的 docs 找 Y"
   │
   ▼
┌─────────────────────────────────────────────────┐
│  Step 0: 推断 docs root URL(2-3 候选)         │
│  - https://docs.<vendor>.com                    │
│  - https://developers.<vendor>.com              │
│  - https://platform.<vendor>.com/docs           │
│  - 看 vendor 主站 footer 链接                    │
└─────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────┐
│  Step 1: 4 个 probe curl(并发,1s 内拿决策)      │
│  curl -sI <root>/llms.txt                       │
│  curl -sI <root>/llms-full.txt                  │
│  curl -sI <root>/sitemap.xml                    │
│  curl -sSL <root>/robots.txt | grep Sitemap:    │
└─────────────────────────────────────────────────┘
   │
   ├─[llms-full.txt size 1KB-5MB]──→ Path 1 直接 curl
   ├─[llms-full.txt size > 5MB]────→ Path 1+2 切片
   ├─[只有 llms.txt]──────────────→ Path 2 + 推断/索引 → r.jina.ai
   ├─[只有 sitemap.xml]──────────→ Path 3 sitemap + r.jina.ai
   ├─[robots.txt 指别处的 sitemap]→ Path 3 用真路径
   ├─[全 miss + 静态站]───────────→ Path 4 root html 抽链 + r.jina.ai
   └─[client-only SPA / 反爬]──────→ Path 5 Firecrawl(<10% 用例)
```

## 2. 可执行 bash(整套)

```bash
#!/usr/bin/env bash
# search-agent ground-api pipeline (composable)
# 用法: ./pipeline.sh <docs_root_url> [<query_keyword>]
set -euo pipefail

ROOT="${1:?need docs root URL}"
QUERY="${2:-}"

# ─── Step 1: 并发 probe(<1s)───────────────────────────
probe() {
  curl -sI -m 5 -o /dev/null -w "%{http_code}\t%{size_header}\t%{content_type}\n" "$1"
}

LLMS=$(probe "$ROOT/llms.txt" || echo "0\t0\t")
LLMSFULL=$(probe "$ROOT/llms-full.txt" || echo "0\t0\t")
SITEMAP=$(probe "$ROOT/sitemap.xml" || echo "0\t0\t")
ROBOTS_SITEMAP=$(curl -sSL -m 5 "$ROOT/robots.txt" 2>/dev/null | grep -i '^Sitemap:' | awk '{print $2}' | tr -d '\r')

# 解析 size + code
LLMSFULL_CODE=$(echo "$LLMSFULL" | cut -f1)
LLMSFULL_SIZE=$(curl -sI -m 5 "$ROOT/llms-full.txt" | awk '/^[Cc]ontent-[Ll]ength/{print $2}' | tr -d '\r')
LLMSFULL_CT=$(echo "$LLMSFULL"  | cut -f3)

# ─── Step 2: 分支 ────────────────────────────────────
if [ "$LLMSFULL_CODE" = "200" ] && [ -n "$LLMSFULL_SIZE" ] && [ "$LLMSFULL_SIZE" -gt 500 ] && [ "$LLMSFULL_SIZE" -lt 5000000 ]; then
  echo "→ Path 1: 中型 llms-full.txt (${LLMSFULL_SIZE}B)" >&2
  curl -sSL "$ROOT/llms-full.txt"
  exit 0
fi

if [ "$LLMSFULL_CODE" = "200" ] && [ -n "$LLMSFULL_SIZE" ] && [ "$LLMSFULL_SIZE" -ge 5000000 ]; then
  echo "→ Path 1+2: 巨型 llms-full.txt (${LLMSFULL_SIZE}B),需 query 切片" >&2
  # 巨型时,先拿 llms.txt 索引 + 用 query 关键字过滤段落
  LLMSFULLBODY=$(curl -sSL "$ROOT/llms-full.txt")
  if [ -n "$QUERY" ]; then
    # 按 # 标题分段,留含 query 的段
    echo "$LLMSFULLBODY" | awk -v q="$QUERY" '
      /^# / {section=""; in_section=0}
      {section=section $0 "\n"}
      tolower($0) ~ tolower(q) {in_section=1}
      /^# / && prev_in {print prev_section}
      {prev_section=section; prev_in=in_section}
      END {if (in_section) print section}'
  else
    echo "$LLMSFULLBODY"
  fi
  exit 0
fi

LLMS_CODE=$(echo "$LLMS" | cut -f1)
if [ "$LLMS_CODE" = "200" ]; then
  echo "→ Path 2: llms.txt 索引(可能 query 在简介里就答了)" >&2
  curl -sSL "$ROOT/llms.txt"
  # 若 query 给定,从 llms.txt 也可能挖到具体 URL,继续 jina
  if [ -n "$QUERY" ]; then
    URL=$(curl -sSL "$ROOT/llms.txt" | grep -oE "https?://[^ )\"]*$QUERY[^ )\"]*" | head -1)
    [ -n "$URL" ] && curl -sSL "https://r.jina.ai/$URL"
  fi
  exit 0
fi

# Sitemap path: 优先 robots.txt 指引,fallback 到 <root>/sitemap.xml
SITEMAP_URL="${ROBOTS_SITEMAP:-$ROOT/sitemap.xml}"
if curl -sI -m 5 "$SITEMAP_URL" | head -1 | grep -q '200'; then
  echo "→ Path 3: sitemap.xml ($SITEMAP_URL)" >&2
  if [ -n "$QUERY" ]; then
    URLS=$(curl -sSL "$SITEMAP_URL" | grep -oE '<loc>[^<]*</loc>' | sed 's/<loc>//;s/<\/loc>//' | grep -i "$QUERY")
    for u in $URLS; do
      curl -sSL "https://r.jina.ai/$u"
      echo
      sleep 2  # Jina anon rate limit
    done
  else
    # 无 query: 拿 URL list 让上层决定
    curl -sSL "$SITEMAP_URL" | grep -oE '<loc>[^<]*</loc>' | sed 's/<loc>//;s/<\/loc>//'
  fi
  exit 0
fi

# Path 4: root HTML 抽链
echo "→ Path 4: root HTML <a href> 一层递归" >&2
ROOT_HTML=$(curl -sSL "$ROOT/")
LINKS=$(echo "$ROOT_HTML" | grep -oE 'href="[^"]+"' | sed 's/href="//;s/"$//' \
        | grep -E "^(/|$ROOT)" | sort -u)
if [ -n "$QUERY" ]; then
  TARGET=$(echo "$LINKS" | grep -i "$QUERY" | head -1)
  if [ -z "$TARGET" ]; then
    # 二层递归
    for sublink in $LINKS; do
      [ "${sublink:0:1}" = "/" ] && sublink="$ROOT$sublink"
      SUBHTML=$(curl -sSL -m 10 "$sublink" 2>/dev/null || true)
      TARGET=$(echo "$SUBHTML" | grep -oE 'href="[^"]+"' | sed 's/href="//;s/"$//' | grep -i "$QUERY" | head -1)
      [ -n "$TARGET" ] && break
    done
  fi
  [ "${TARGET:0:1}" = "/" ] && TARGET="$ROOT$TARGET"
  if [ -n "$TARGET" ]; then
    curl -sSL "https://r.jina.ai/$TARGET"
    exit 0
  fi
fi

# Path 5: 兜底 Firecrawl
echo "→ Path 5: Firecrawl /scrape (烧 1 credit)" >&2
[ -z "${FIRECRAWL_API_KEY:-}" ] && { echo "ERROR: FIRECRAWL_API_KEY 未设" >&2; exit 1; }
TARGET="${TARGET:-$ROOT}"
curl -sS -X POST https://api.firecrawl.dev/v2/scrape \
  -H "Authorization: Bearer $FIRECRAWL_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"url\":\"$TARGET\",\"formats\":[\"markdown\"]}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"]["markdown"])'
```

## 3. 严格验证规则(必加,Wave 2 假阳性 25% 教训)

```python
# 不能只看 HTTP 200,必须验:
def is_real_llms_file(http_code, content_type, body_first_512):
    if http_code not in (200, 206):
        return False
    # 1. 太短 = 占位符 / "Page Not Found"
    if len(body_first_512) < 100:
        return False
    # 2. HTML SPA shell 假阳
    s = body_first_512.lower().lstrip()
    if s.startswith('<!doctype html') or s.startswith('<html'):
        return False
    # 3. "Page Not Found" 文案
    if b'page not found' in body_first_512.lower():
        return False
    # 4. Content-Type 应是 text/* 而非 text/html
    if 'text/html' in content_type.lower():
        return False
    return True

def is_real_openapi_json(http_code, content_type, body_first_512):
    if http_code not in (200, 206):
        return False
    if 'application/json' not in content_type.lower():
        return False  # 关键:Mintlify SPA 给 text/html 即假阳
    s = body_first_512.lstrip()
    if not (s.startswith(b'{') or s.startswith(b'[')):
        return False
    return True
```

## 4. query 形态 → path 选择(基于 5 路径对照实测)

| query 形态 | 例子 | 推荐路径 | 实测耗时 | 实测成本 |
|---|---|---|---|---|
| **简单 1-shot 概念问** | "vendor X 怎么 auth"、"rate limit 多少"、"免费配额" | **Path 2 浅答**(llms.txt 全文)| 0.14s | 0 |
| **完整单页详情** | "vendor X auth 完整 pricing 表"、"specific endpoint schema" | **Path 1**(llms-full 抽节) | 0.61s | 0 |
| **全站索引(后续多 query 复用)** | "我要做 vendor X 的 SDK / skill" | **Path 1**(全 llms-full 入缓存)| 1-3s download | 0 |
| **vendor 不 ship llms.\***(~13%)| Groq 这种 | **Path 3** sitemap → jina | 1-2s/页 | 0 |
| **sitemap 也 miss**(~6%)| 极少数 vendor | **Path 4** root html 抽链 | 1.5s/页 | 0 |
| **client-only SPA + 反爬**(<10%)| 罕见 | **Path 5** Firecrawl | 1.5s/页 | 1 credit/页 |

## 5. 巨型 llms-full.txt 处理策略(>5MB)

Anthropic 58MB / Cloudflare 49MB 这类不能直接灌 LLM context。两种切法:

### A. 按 query 关键字切段(运行时)
```bash
# 抽出含 query 的所有 # 段
curl -sSL <root>/llms-full.txt | awk -v q="rate limit" '
  /^# / {if (matched) print section; section=""; matched=0}
  {section = section $0 "\n"}
  tolower($0) ~ tolower(q) {matched=1}
  END {if (matched) print section}
'
```

### B. 按 page 持久缓存(为多 query 复用)
```bash
# 一次下载 + 切成 per-page 文件,后续 query 直接 grep 文件名
curl -sSL <root>/llms-full.txt > /tmp/<vendor>-full.txt
mkdir -p /tmp/<vendor>-pages
csplit -f /tmp/<vendor>-pages/page -b "%04d.md" /tmp/<vendor>-full.txt '/^# /' '{*}'
# 也可按 Source: URL 切(若是流派 A)
```

**Anthropic 58MB 实战**:64 page 的 LLM context 装不下 58MB。但**自切片缓存**后,每 query 只读相关 ~5KB 段。**查 1 次的 vendor 别下 58MB**,查 ≥3 次的值得下载缓存。

## 6. 关键 trap 列表(实测踩过)

| Trap | 症状 | 解决 |
|---|---|---|
| Vercel `/docs/llms-full.txt` 200 但 body 是 "Page Not Found" | size 298B 假阳 | 严格验:size > 500B + 非 "Page Not Found" 文案 |
| Mintlify `/api-reference/openapi.json` 200 但是 SPA shell HTML | catch-all 路由 | 严格验:Content-Type = `application/json` |
| Groq sitemap 在 `/sitemap.xml` 不在 `/docs/sitemap.xml` | probe 路径死板 | 必先读 `robots.txt` 找 `Sitemap:` 行 |
| Jina anon 6 worker 立即 429 | 单 IP free 配额 | 串行 + exponential backoff,实测 2 worker 稳 |
| `xh` 处理 1MB+ JSON response 时 invalid escape | 工具 bug | 用 raw `curl`,不用 httpie/xh |
| Mintlify `og:title` 等 metadata 被 `r.jina.ai` 漂白 | 期望保留 metadata 时拿不到 | 要 metadata 时切到 Firecrawl `/v2/scrape`(它返回完整 metadata 字段) |

## 7. 命中率(16 vendor panel,Wave 2)

```
路径                                     命中率   实用区间
Path 1 llms-full.txt(<5MB 实用)         44%
Path 1+2 llms-full.txt(任意大小)        56%
Path 2 llms.txt 索引                     87%   ← 最稳入口
Path 3 sitemap.xml(via robots.txt)      88%
Path 1-3 累计                            94%   ← 这之后才需 Firecrawl
Path 4 root html(静态站100%覆盖)        ≈100%(若是静态可访问)
Path 5 Firecrawl(client-only SPA + 反爬) ≤10% niche
```

**累计**:Path 1-3 在 16 vendor panel 上覆盖 94%,加 Path 4 兜底覆盖 100% 静态可访问站,Path 5 仅在 client-only SPA + 反爬 + 上述 4 路径全失败的极端 case 才烧 credits。

## 8. 落到 search-agent 项目的具体动作

1. **`.claude/skills/ground-api/SKILL.md`** 写成本 PIPELINE.md 的 imperative 版,以 §5.1 #25 H 为骨架
2. **`adapters/groundapi/`** 不写,因为 100% 是 skill imperative 能 cover 的(curl + grep + jina + 偶尔 Firecrawl,符合 §2.11 档 1 边界)
3. **缓存层(可选)** 高频 vendor(Anthropic / OpenAI / Cohere)的 llms-full.txt 跑 cron 周更,落到 `cache/llms-full/<vendor>.txt`,query 时 grep 缓存优先
4. **失败计数器** 跑路径 1-4 失败时记一笔,周复盘是否 vendor 升级了 docs(可能从静态变 client-only SPA)

## 9. 复测频次(承袭 §5.1 #14/#15/#20 元教训)

| 频次 | 内容 |
|------|------|
| 季度 | 16 vendor panel 重 probe,看 ship 率 + 假阳变化 |
| 半年 | 重跑 5 路径 OpenAlex case,看 jina/Firecrawl 价格 + 限流 |
| 触发性 | 用户 ground 失败超 3 次 → 立即重新 probe 该 vendor |

---

**总结一句话**:**`curl -sSL <root>/llms.txt` 是 87% 用例的入口,5MB 以下的 `llms-full.txt` 是 44% 用例的全集 ground truth,Firecrawl 只在 ≤10% 极端 case 烧 credits 用**。
