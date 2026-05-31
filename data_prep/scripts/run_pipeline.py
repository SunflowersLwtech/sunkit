#!/usr/bin/env python3
"""Fetch, normalize, dedupe, and shortlist the current source set."""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import math
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_harness.policy import compile_policy_regex, policy_get
from scripts.env_utils import env_value, first_env

REGISTRY_PATH = ROOT / "data_prep" / "source_registry.json"
LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"
ENV_FILE = ROOT / ".env"

HEADERS = {
    "User-Agent": "searchpo-e2e/0.1 (+https://local)",
    "Accept": "application/json, application/atom+xml, application/rss+xml, text/html;q=0.8, */*;q=0.5",
}

DEMO_RE = compile_policy_regex("data_prep.regex.demo")
CODE_RE = compile_policy_regex("data_prep.regex.code")
BUYER_RE = compile_policy_regex("data_prep.regex.buyer")
PAIN_RE = compile_policy_regex("data_prep.regex.pain")
AD_RE = compile_policy_regex("data_prep.regex.ad")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_time(value: str | None) -> str | None:
    if not value:
        return None
    clean = value.strip()
    if not clean:
        return None
    try:
        if clean.endswith("Z"):
            clean = clean[:-1] + "+00:00"
        return datetime.fromisoformat(clean).astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(clean)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except (TypeError, ValueError):
        return None


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def fetch_text(url: str, timeout: float, token: str | None = None, extra_headers: dict[str, str] | None = None) -> str:
    headers = dict(HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_exa_search(url: str, query: str, limit: int, timeout: float) -> str:
    api_key = env_value("EXA_API_KEY", ENV_FILE)
    payload = json.dumps({"query": query, "numResults": limit, "type": "auto"}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            **HEADERS,
            "Content-Type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def source_token(source: dict[str, Any]) -> str:
    auth = str(source.get("auth") or "")
    if auth == "optional_github_token":
        return first_env(["GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN"], ENV_FILE)
    if auth == "optional_huggingface_token":
        return env_value("HUGGINGFACE_TOKEN", ENV_FILE)
    return ""


def missing_required_env(source: dict[str, Any]) -> list[str]:
    required_any = [str(item) for item in source.get("requires_env_any") or []]
    if required_any and not first_env(required_any, ENV_FILE):
        return required_any
    return []


def render_query(value: str) -> str:
    today = datetime.now(timezone.utc).date()
    replacements = {
        "{date_minus_7d}": (today - timedelta(days=7)).isoformat(),
        "{date_minus_14d}": (today - timedelta(days=14)).isoformat(),
        "{date_minus_30d}": (today - timedelta(days=30)).isoformat(),
    }
    rendered = value
    for needle, replacement in replacements.items():
        rendered = rendered.replace(needle, replacement)
    return rendered


def with_query_params(base_url: str, params: dict[str, Any]) -> str:
    parsed = urllib.parse.urlparse(base_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is not None and value != "":
            query[key] = str(value)
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def query_strings(source: dict[str, Any], limit: int) -> list[tuple[str, int]]:
    queries = [render_query(str(item)) for item in source.get("queries") or [] if str(item).strip()]
    try:
        max_queries = max(1, int(env_value("SEARCHPO_MAX_QUERIES_PER_SOURCE", ENV_FILE, "3") or "3"))
    except ValueError:
        max_queries = 3
    selected = queries[:max_queries]
    if not selected:
        return [("", limit)]
    per_query_limit = max(1, math.ceil(limit / len(selected)))
    return [(query, per_query_limit) for query in selected]


def raw_sha(raw: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def raw_item(
    source: str,
    source_item_id: str,
    url: str | None,
    title: str,
    summary: str | None,
    published_at: str | None,
    collected_at: str,
    metrics: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "source": source,
        "source_item_id": str(source_item_id),
        "url": url,
        "title": html.unescape(re.sub(r"\s+", " ", title or "")).strip(),
        "summary": html.unescape(re.sub(r"\s+", " ", summary or "")).strip() or None,
        "published_at": parse_time(published_at),
        "collected_at": collected_at,
        "metrics": metrics,
        "raw_sha256": raw_sha(raw),
        "raw": raw,
    }
    return payload


def parse_json_source(source: dict[str, Any], text: str, collected_at: str, limit: int) -> list[dict[str, Any]]:
    source_id = source["id"]
    data = json.loads(text)
    rows: list[dict[str, Any]] = []

    if source_id == "github_search_ai_repos":
        for repo in data.get("items", [])[:limit]:
            full_name = str(repo.get("full_name") or "")
            rows.append(
                raw_item(
                    source_id,
                    full_name or repo.get("html_url"),
                    repo.get("html_url"),
                    full_name,
                    repo.get("description") or " ".join(str(topic) for topic in repo.get("topics") or [])[:500],
                    repo.get("created_at") or repo.get("pushed_at") or repo.get("updated_at"),
                    collected_at,
                    {
                        "stars": repo.get("stargazers_count"),
                        "forks": repo.get("forks_count"),
                        "open_issues": repo.get("open_issues_count"),
                        "watchers": repo.get("watchers_count"),
                    },
                    repo,
                )
            )
    elif source_id == "exa_web_search":
        for result in data.get("results", [])[:limit]:
            url = result.get("url")
            rows.append(
                raw_item(
                    source_id,
                    result.get("id", url),
                    url,
                    result.get("title") or url or "",
                    result.get("text") or result.get("snippet") or result.get("summary"),
                    result.get("publishedDate") or result.get("published_date"),
                    collected_at,
                    {"score": result.get("score")},
                    result,
                )
            )
    elif source_id == "hacker_news_algolia":
        for hit in data.get("hits", [])[:limit]:
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            rows.append(
                raw_item(
                    source_id,
                    hit.get("objectID", url),
                    url,
                    hit.get("title") or hit.get("story_title") or "",
                    hit.get("story_text") or hit.get("comment_text"),
                    hit.get("created_at"),
                    collected_at,
                    {
                        "points": hit.get("points"),
                        "comments": hit.get("num_comments"),
                    },
                    hit,
                )
            )
    elif source_id == "huggingface_models":
        for model in data[:limit]:
            model_id = str(model.get("id") or model.get("modelId") or "")
            rows.append(
                raw_item(
                    source_id,
                    model_id,
                    f"https://huggingface.co/{model_id}" if model_id else None,
                    model_id,
                    " ".join(str(tag) for tag in model.get("tags") or [])[:500],
                    model.get("lastModified") or model.get("createdAt"),
                    collected_at,
                    {
                        "likes": model.get("likes"),
                        "downloads": model.get("downloads"),
                    },
                    model,
                )
            )
    elif source_id == "devto_ai":
        for article in data[:limit]:
            tags = article.get("tag_list") or []
            rows.append(
                raw_item(
                    source_id,
                    article.get("id", article.get("url")),
                    article.get("url") or article.get("canonical_url"),
                    article.get("title") or "",
                    article.get("description") or " ".join(str(tag) for tag in tags),
                    article.get("published_at") or article.get("created_at"),
                    collected_at,
                    {
                        "positive_reactions": article.get("positive_reactions_count"),
                        "comments": article.get("comments_count"),
                    },
                    article,
                )
            )
    elif source_id == "lobsters_ai":
        for story in data[:limit]:
            url = story.get("url") or story.get("comments_url")
            rows.append(
                raw_item(
                    source_id,
                    story.get("short_id", url),
                    url,
                    story.get("title") or "",
                    story.get("description") or " ".join(str(tag) for tag in story.get("tags") or []),
                    story.get("created_at"),
                    collected_at,
                    {
                        "score": story.get("score"),
                        "comments": story.get("comment_count"),
                    },
                    story,
                )
            )
    elif source_id == "libraries_io_search":
        for package in data[:limit]:
            name = str(package.get("name") or package.get("full_name") or "")
            platform = str(package.get("platform") or "").strip()
            source_item_id = f"{platform}/{name}" if platform and name else name or package.get("repository_url")
            rows.append(
                raw_item(
                    source_id,
                    source_item_id,
                    package.get("repository_url") or package.get("package_manager_url"),
                    source_item_id,
                    package.get("description") or " ".join(str(keyword) for keyword in package.get("keywords") or []),
                    package.get("latest_release_published_at") or package.get("created_at"),
                    collected_at,
                    {
                        "stars": package.get("stars"),
                        "ecosystem_rank": package.get("rank"),
                        "dependent_repos": package.get("dependent_repos_count"),
                        "dependent_projects": package.get("dependents_count"),
                    },
                    package,
                )
            )
    elif source_id == "v2ex_hot":
        for topic in data[:limit]:
            rows.append(
                raw_item(
                    source_id,
                    topic.get("id", topic.get("url")),
                    topic.get("url"),
                    topic.get("title") or "",
                    topic.get("content_rendered") or topic.get("content"),
                    datetime.fromtimestamp(topic["created"], timezone.utc).isoformat() if topic.get("created") else None,
                    collected_at,
                    {"replies": topic.get("replies")},
                    topic,
                )
            )
    else:
        raise ValueError(f"no JSON parser for {source_id}")
    return rows


def child_text(element: ET.Element, names: list[str]) -> str | None:
    for name in names:
        found = element.find(name)
        if found is not None and found.text:
            return found.text
    return None


def parse_feed_source(source: dict[str, Any], text: str, collected_at: str, limit: int) -> list[dict[str, Any]]:
    source_id = source["id"]
    if source_id == "kr36_feed":
        rows = []
        for item in re.findall(r"<item\b.*?</item>", text, flags=re.S | re.I)[:limit]:
            def tag(name: str) -> str:
                match = re.search(rf"<{name}[^>]*>(.*?)</{name}>", item, flags=re.S | re.I)
                if not match:
                    return ""
                value = re.sub(r"^<!\[CDATA\[|\]\]>$", "", match.group(1).strip())
                value = re.sub(r"<[^>]+>", " ", value)
                return html.unescape(re.sub(r"\s+", " ", value)).strip()

            url = tag("link")
            guid = tag("guid") or url or tag("title")
            rows.append(raw_item(source_id, guid, url, tag("title"), tag("description"), tag("pubDate"), collected_at, {}, {"guid": guid}))
        return rows
    safe_text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-fA-F]+);)", "&amp;", text)
    root = ET.fromstring(safe_text)
    rows: list[dict[str, Any]] = []

    if source_id == "arxiv_ai_ml_cl":
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns)[:limit]:
            url = child_text(entry, ["atom:id"])
            title = child_text(entry, ["atom:title"]) or ""
            summary = child_text(entry, ["atom:summary"])
            published = child_text(entry, ["atom:published", "atom:updated"])
            source_item_id = (url or title).rsplit("/", 1)[-1]
            rows.append(raw_item(source_id, source_item_id, url, title, summary, published, collected_at, {}, {"xml": ET.tostring(entry, encoding="unicode")}))
    else:
        items = root.findall(".//item")
        if not items:
            items = root.findall("{http://www.w3.org/2005/Atom}entry")
        for item in items[:limit]:
            link = child_text(item, ["link", "{http://www.w3.org/2005/Atom}link"])
            if item.tag.endswith("entry"):
                link_node = item.find("{http://www.w3.org/2005/Atom}link")
                if link_node is not None:
                    link = link_node.attrib.get("href") or link
            title = child_text(item, ["title", "{http://www.w3.org/2005/Atom}title"]) or ""
            summary = child_text(item, ["description", "summary", "{http://www.w3.org/2005/Atom}summary"])
            published = child_text(item, ["pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published"])
            guid = child_text(item, ["guid", "id", "{http://www.w3.org/2005/Atom}id"]) or link or title
            rows.append(raw_item(source_id, guid, link, title, summary, published, collected_at, {}, {"xml": ET.tostring(item, encoding="unicode")}))
    return rows


def parse_github_trending(source: dict[str, Any], text: str, collected_at: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    articles = re.findall(r"<article\b.*?</article>", text, flags=re.S | re.I)
    for article in articles[:limit]:
        match = re.search(r'<h2[^>]*>\s*<a[^>]+href="/([^"]+)"[^>]*>(.*?)</a>', article, flags=re.S | re.I)
        if not match:
            continue
        repo = re.sub(r"\s+", "", html.unescape(re.sub("<.*?>", "", match.group(1) or ""))).strip()
        repo = match.group(1).strip("/")
        title = repo
        desc_match = re.search(r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>(.*?)</p>', article, flags=re.S | re.I)
        summary = html.unescape(re.sub("<.*?>", "", desc_match.group(1))).strip() if desc_match else None
        stars_match = re.search(r'aria-label="star"[^>]*>.*?</svg>\s*([^<]+)', article, flags=re.S | re.I)
        stars_today_match = re.search(r"([\d,]+)\s+stars?\s+today", article, flags=re.I)
        metrics = {
            "stars": stars_match.group(1).strip().replace(",", "") if stars_match else None,
            "stars_today": stars_today_match.group(1).replace(",", "") if stars_today_match else None,
        }
        rows.append(
            raw_item(
                source["id"],
                repo,
                f"https://github.com/{repo}",
                title,
                summary,
                None,
                collected_at,
                metrics,
                {"repo": repo, "article_excerpt": re.sub(r"\s+", " ", article)[:2000]},
            )
        )
    return rows


def source_urls(source: dict[str, Any], limit: int) -> list[tuple[str, str, int]]:
    source_id = source["id"]
    primary_endpoint = str(source["primary_endpoint"])
    if source_id == "github_search_ai_repos":
        return [
            (
                with_query_params(primary_endpoint, {"q": query, "sort": "updated", "order": "desc", "per_page": per_query_limit}),
                query,
                per_query_limit,
            )
            for query, per_query_limit in query_strings(source, limit)
        ]
    if source_id == "hacker_news_algolia":
        return [
            (
                with_query_params(primary_endpoint, {"tags": "story", "query": query or "AI", "hitsPerPage": per_query_limit}),
                query or "AI",
                per_query_limit,
            )
            for query, per_query_limit in query_strings(source, limit)
        ]
    if source_id == "huggingface_models":
        urls = []
        for query, per_query_limit in query_strings(source, limit):
            params = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
            params["limit"] = per_query_limit
            urls.append((with_query_params(primary_endpoint, params), query, per_query_limit))
        return urls
    if source_id == "arxiv_ai_ml_cl":
        return [
            (
                with_query_params(
                    primary_endpoint,
                    {
                        "search_query": query or "cat:cs.AI",
                        "start": 0,
                        "max_results": per_query_limit,
                        "sortBy": "submittedDate",
                        "sortOrder": "descending",
                    },
                ),
                query or "cat:cs.AI",
                per_query_limit,
            )
            for query, per_query_limit in query_strings(source, limit)
        ]
    if source_id == "devto_ai":
        return [
            (
                with_query_params(primary_endpoint, {"tag": query or "ai", "top": 7, "per_page": per_query_limit}),
                query or "ai",
                per_query_limit,
            )
            for query, per_query_limit in query_strings(source, limit)
        ]
    if source_id == "exa_web_search":
        return [
            (primary_endpoint, query, per_query_limit)
            for query, per_query_limit in query_strings(source, limit)
        ]
    if source_id == "libraries_io_search":
        api_key = env_value("LIBRARIES_IO_API_KEY", ENV_FILE)
        return [
            (
                with_query_params(primary_endpoint, {"q": query, "per_page": per_query_limit, "api_key": api_key}),
                query,
                per_query_limit,
            )
            for query, per_query_limit in query_strings(source, limit)
        ]
    return [(source.get("probe_url") or primary_endpoint, "native", limit)]


def collect_sources(registry: dict[str, Any], raw_dir: Path, limit: int, timeout: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    collected_at = utc_now()
    all_rows: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []

    for source in registry["sources"]:
        source_id = source["id"]
        started = time.time()
        missing_env = missing_required_env(source)
        if missing_env:
            statuses.append(
                {
                    "source": source_id,
                    "ok": True,
                    "skipped": True,
                    "count": 0,
                    "elapsed_ms": 0,
                    "missing_required_env": missing_env,
                }
            )
            continue
        source_rows: list[dict[str, Any]] = []
        errors: list[str] = []
        requests = source_urls(source, limit)
        token = source_token(source)
        request_timeout = float(source.get("timeout_seconds") or timeout)
        try:
            for url, query, request_limit in requests:
                try:
                    if source_id == "exa_web_search":
                        text = fetch_exa_search(url, query, request_limit, request_timeout)
                    else:
                        text = fetch_text(url, request_timeout, token=token)
                    if source_id == "github_trending":
                        rows = parse_github_trending(source, text, collected_at, request_limit)
                    elif "json" in str(source.get("fetch_method")):
                        rows = parse_json_source(source, text, collected_at, request_limit)
                    else:
                        rows = parse_feed_source(source, text, collected_at, request_limit)
                    source_rows.extend(rows)
                except (
                    urllib.error.URLError,
                    urllib.error.HTTPError,
                    ET.ParseError,
                    json.JSONDecodeError,
                    ValueError,
                    TimeoutError,
                    socket.timeout,
                    ssl.SSLError,
                ) as exc:
                    errors.append(f"{query}: {exc}")
                    if source.get("abort_on_first_error"):
                        break
            if source_rows:
                write_jsonl(raw_dir / f"{source_id}.jsonl", source_rows)
            all_rows.extend(source_rows)
            statuses.append(
                {
                    "source": source_id,
                    "ok": bool(source_rows),
                    "count": len(source_rows),
                    "requests": len(requests),
                    "failed_requests": len(errors),
                    "elapsed_ms": round((time.time() - started) * 1000),
                    **({"errors": errors[:3]} if errors else {}),
                }
            )
        except Exception as exc:
            statuses.append(
                {
                    "source": source_id,
                    "ok": False,
                    "count": 0,
                    "requests": len(requests),
                    "elapsed_ms": round((time.time() - started) * 1000),
                    "error": str(exc),
                }
            )
    return all_rows, statuses


def domain(url: str | None) -> str:
    if not url:
        return ""
    return urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")


def entity_for(row: dict[str, Any]) -> tuple[str, str]:
    source = row["source"]
    url = row.get("url")
    title = row.get("title") or ""
    if source in {"github_trending", "github_search_ai_repos"} and url:
        return "repo", "repo:" + url.removeprefix("https://github.com/").strip("/")
    if source == "huggingface_models":
        return "model", "model:" + row["source_item_id"]
    if source == "arxiv_ai_ml_cl":
        return "paper", "paper:arxiv:" + row["source_item_id"].replace("abs/", "")
    if source == "libraries_io_search":
        if url and domain(url) == "github.com":
            return "repo", "repo:" + url.removeprefix("https://github.com/").strip("/")
        return "product", "package:" + row["source_item_id"]
    if source == "exa_web_search":
        if url and domain(url) == "github.com":
            return "repo", "repo:" + url.removeprefix("https://github.com/").strip("/")
        return "article", "web:" + (domain(url) or source) + ":" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
    if source in {"hacker_news_algolia", "v2ex_hot", "lobsters_ai"}:
        return "discussion", "web:" + (domain(url) or source) + ":" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
    if source in {"kr36_feed", "devto_ai", "openai_news_rss"}:
        return "article", "web:" + (domain(url) or source) + ":" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
    return "product", "product:" + (domain(url) or hashlib.sha1(title.encode("utf-8")).hexdigest()[:12])


def freshness_hours(published_at: str | None, collected_at: str) -> float | None:
    if not published_at:
        return None
    try:
        published = datetime.fromisoformat(published_at)
        collected = datetime.fromisoformat(collected_at)
        return round(max(0.0, (collected - published).total_seconds() / 3600), 2)
    except ValueError:
        return None


def metric_strength(metrics: dict[str, Any]) -> float | None:
    values: list[float] = []
    for key in (
        "stars_today",
        "stars",
        "forks",
        "points",
        "comments",
        "likes",
        "downloads",
        "replies",
        "positive_reactions",
        "score",
        "dependent_repos",
        "dependent_projects",
    ):
        value = metrics.get(key)
        try:
            if value is not None:
                values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return round(min(10.0, sum(max(0.0, value) for value in values) ** 0.5 / 10), 2)


def risk_flags(row: dict[str, Any], signals: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    thresholds = policy_get("data_prep.risk_thresholds", {})
    generic_titles = set(policy_get("data_prep.generic_titles", ["ai", "agent", "llm", "rag"]))
    if not row.get("url"):
        flags.append("missing_url")
    title = row.get("title") or ""
    if len(title) < int(thresholds.get("generic_title_min_chars", 8)) or title.lower() in generic_titles:
        flags.append("generic_title")
    if signals.get("freshness_hours") and signals["freshness_hours"] > float(thresholds.get("old_item_hours", 720)):
        flags.append("old_item")
    if not signals["has_demo_keyword"] and not signals["has_code_signal"]:
        flags.append("no_demo_signal")
    if signals["ad_language_density"] and signals["ad_language_density"] > float(thresholds.get("ad_language_density", 0.08)):
        flags.append("marketing_biased")
    if row["source"] in {"v2ex_hot", "hacker_news_algolia", "lobsters_ai"}:
        flags.append("community_only")
    return flags


def normalize(rows: list[dict[str, Any]], registry: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reliability = {source["id"]: float(source.get("source_reliability", 0.7)) for source in registry["sources"]}
    deduped: dict[str, dict[str, Any]] = {}
    clusters: dict[str, list[str]] = {}

    for row in rows:
        entity_type, entity_key = entity_for(row)
        text = " ".join(str(row.get(field) or "") for field in ("title", "summary"))
        words = max(1, len(re.findall(r"\w+", text)))
        signals = {
            "freshness_hours": freshness_hours(row.get("published_at"), row["collected_at"]),
            "has_demo_keyword": bool(DEMO_RE.search(text)),
            "has_code_signal": bool(CODE_RE.search(text)) or entity_type in {"repo", "model", "paper"},
            "has_buyer_keyword": bool(BUYER_RE.search(text)),
            "has_pain_keyword": bool(PAIN_RE.search(text)),
            "ad_language_density": round(len(AD_RE.findall(text)) / words, 4),
            "source_count": 1,
            "metric_strength": metric_strength(row.get("metrics") or {}),
        }
        flags = risk_flags(row, signals)
        candidate_id = hashlib.sha1(entity_key.encode("utf-8")).hexdigest()[:16]
        candidate = {
            "candidate_id": candidate_id,
            "entity_type": entity_type,
            "entity_key": entity_key,
            "canonical_url": row.get("url"),
            "title": row.get("title") or entity_key,
            "summary": row.get("summary"),
            "published_at": row.get("published_at"),
            "collected_at": row["collected_at"],
            "source_ids": [row["source"]],
            "evidence": [
                {
                    "source": row["source"],
                    "url": row.get("url") or "https://local.invalid/missing-url",
                    "reliability": reliability.get(row["source"], 0.7),
                    "claim_role": "primary",
                }
            ],
            "metrics": row.get("metrics") or {},
            "signals": signals,
            "risk_flags": flags,
        }
        dedupe_key = entity_key if entity_key else row.get("url") or candidate_id
        if dedupe_key in deduped:
            existing = deduped[dedupe_key]
            existing["source_ids"] = sorted(set(existing["source_ids"] + [row["source"]]))
            existing["evidence"].extend(candidate["evidence"])
            existing["signals"]["source_count"] = len(existing["source_ids"])
            existing["risk_flags"] = sorted(set(existing["risk_flags"] + ["possible_duplicate"] + flags))
            clusters.setdefault(existing["candidate_id"], []).append(candidate_id)
        else:
            deduped[dedupe_key] = candidate
            clusters[candidate_id] = [candidate_id]

    return list(deduped.values()), [{"candidate_id": key, "members": value} for key, value in clusters.items()]


def candidate_score(candidate: dict[str, Any]) -> float:
    signals = candidate["signals"]
    weights = policy_get("data_prep.score", {})
    score = 0.0
    score += float(weights.get("has_code_signal", 2.5)) if signals.get("has_code_signal") else 0.0
    score += float(weights.get("has_demo_keyword", 1.5)) if signals.get("has_demo_keyword") else 0.0
    score += float(weights.get("has_buyer_keyword", 1.2)) if signals.get("has_buyer_keyword") else 0.0
    score += float(weights.get("has_pain_keyword", 1.0)) if signals.get("has_pain_keyword") else 0.0
    score += min(float(weights.get("metric_strength_cap", 2.0)), float(signals.get("metric_strength") or 0) / float(weights.get("metric_strength_divisor", 2.0)))
    score += min(float(weights.get("extra_source_cap", 1.0)), max(0, int(signals.get("source_count") or 1) - 1) * float(weights.get("extra_source_weight", 0.5)))
    freshness = signals.get("freshness_hours")
    if freshness is None:
        score += float(weights.get("unknown_freshness", 0.4))
    elif freshness <= float(weights.get("fresh_hours", 72)):
        score += float(weights.get("fresh_bonus", 1.0))
    elif freshness <= float(weights.get("recent_hours", 720)):
        score += float(weights.get("recent_bonus", 0.5))
    penalties = weights.get("penalties", {})
    for flag, penalty in penalties.items():
        score -= float(penalty) if flag in candidate["risk_flags"] else 0.0
    return round(max(0.0, score), 3)


def filter_candidates(candidates: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for candidate in candidates:
        score = candidate_score(candidate)
        item = {**candidate, "candidate_score": score}
        hard_flags = set(policy_get("data_prep.score.hard_reject_flags", ["missing_url", "generic_title"]))
        min_keep_score = float(policy_get("data_prep.score.min_keep_score", 1.0))
        if hard_flags.intersection(candidate["risk_flags"]) or score < min_keep_score:
            rejected.append({"candidate_id": candidate["candidate_id"], "title": candidate["title"], "score": score, "risk_flags": candidate["risk_flags"]})
        else:
            kept.append(item)
    kept.sort(key=lambda item: item["candidate_score"], reverse=True)
    report = {
        "created_at": utc_now(),
        "input_count": len(candidates),
        "kept_count": len(kept),
        "rejected_count": len(rejected),
        "rejected": rejected,
    }
    return kept[:limit], report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-per-source", type=int, default=20)
    parser.add_argument("--shortlist-size", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args()

    registry = read_json(REGISTRY_PATH)
    run_dir = ROOT / "runtime" / "artifacts" / datetime.now().strftime("%Y-%m-%d") / args.run_id
    raw_dir = run_dir / "raw"
    rows, statuses = collect_sources(registry, raw_dir, args.limit_per_source, args.timeout)
    candidates, clusters = normalize(rows, registry)
    shortlist, report = filter_candidates(candidates, args.shortlist_size)

    write_jsonl(run_dir / "normalized_candidates.jsonl", candidates)
    write_json(run_dir / "dedupe_clusters.json", {"created_at": utc_now(), "clusters": clusters})
    write_json(run_dir / "candidate_filter_report.json", report)
    write_json(run_dir / "candidate_shortlist.json", {"created_at": utc_now(), "run_dir": str(run_dir), "items": shortlist})
    write_json(run_dir / "source_fetch_report.json", {"created_at": utc_now(), "sources": statuses, "raw_count": len(rows)})

    LATEST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_RUN_PATH.write_text(str(run_dir) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), "raw_count": len(rows), "candidate_count": len(candidates), "shortlist_count": len(shortlist), "sources": statuses}, ensure_ascii=False, indent=2))
    return 0 if rows and shortlist else 1


if __name__ == "__main__":
    raise SystemExit(main())
