#!/usr/bin/env python3
"""Fetch, normalize, dedupe, and shortlist the current source set."""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "data_prep" / "source_registry.json"
LATEST_RUN_PATH = ROOT / "runtime" / "latest_run.txt"

HEADERS = {
    "User-Agent": "searchpo-e2e/0.1 (+https://local)",
    "Accept": "application/json, application/atom+xml, application/rss+xml, text/html;q=0.8, */*;q=0.5",
}

DEMO_RE = re.compile(r"\b(demo|playground|try it|preview|screenshot|video|example|演示|试用)\b", re.I)
CODE_RE = re.compile(r"\b(github|repo|code|sdk|api|cli|open source|model|paper|arxiv|开源|代码|模型)\b", re.I)
BUYER_RE = re.compile(r"\b(saas|api|pricing|customer|enterprise|workflow|automation|降本|提效|私有化|企业|工作流)\b", re.I)
PAIN_RE = re.compile(r"\b(replace|faster|slow|cost|manual|bug|risk|pain|complaint|坑|慢|贵|手动|替代|风险)\b", re.I)
AD_RE = re.compile(r"\b(best|ultimate|game.?changer|revolutionary|unlock|10x|限时|重磅|首个|唯一)\b", re.I)


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


def fetch_text(url: str, timeout: float, token: str | None = None) -> str:
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


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

    if source_id == "hacker_news_algolia":
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


def source_url(source: dict[str, Any], limit: int) -> str:
    source_id = source["id"]
    if source_id == "hacker_news_algolia":
        return f"{source['primary_endpoint']}?tags=story&query=AI&hitsPerPage={limit}"
    if source_id == "huggingface_models":
        return f"{source['primary_endpoint']}?sort=likes&direction=-1&limit={limit}"
    if source_id == "arxiv_ai_ml_cl":
        return (
            f"{source['primary_endpoint']}?search_query=cat:cs.AI&start=0&max_results={limit}"
            "&sortBy=submittedDate&sortOrder=descending"
        )
    return source.get("probe_url") or source["primary_endpoint"]


def collect_sources(registry: dict[str, Any], raw_dir: Path, limit: int, timeout: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    collected_at = utc_now()
    all_rows: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []

    for source in registry["sources"]:
        source_id = source["id"]
        url = source_url(source, limit)
        started = time.time()
        try:
            text = fetch_text(url, timeout)
            if source_id == "github_trending":
                rows = parse_github_trending(source, text, collected_at, limit)
            elif "json" in str(source.get("fetch_method")):
                rows = parse_json_source(source, text, collected_at, limit)
            else:
                rows = parse_feed_source(source, text, collected_at, limit)
            write_jsonl(raw_dir / f"{source_id}.jsonl", rows)
            all_rows.extend(rows)
            statuses.append({"source": source_id, "ok": True, "count": len(rows), "elapsed_ms": round((time.time() - started) * 1000)})
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
            statuses.append(
                {
                    "source": source_id,
                    "ok": False,
                    "count": 0,
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
    if source == "github_trending" and url:
        return "repo", "repo:" + url.removeprefix("https://github.com/").strip("/")
    if source == "huggingface_models":
        return "model", "model:" + row["source_item_id"]
    if source == "arxiv_ai_ml_cl":
        return "paper", "paper:arxiv:" + row["source_item_id"].replace("abs/", "")
    if source in {"hacker_news_algolia", "v2ex_hot"}:
        return "discussion", "web:" + (domain(url) or source) + ":" + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
    if source == "kr36_feed":
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
    for key in ("stars_today", "stars", "points", "comments", "likes", "downloads", "replies"):
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
    if not row.get("url"):
        flags.append("missing_url")
    title = row.get("title") or ""
    if len(title) < 8 or title.lower() in {"ai", "agent", "llm", "rag"}:
        flags.append("generic_title")
    if signals.get("freshness_hours") and signals["freshness_hours"] > 720:
        flags.append("old_item")
    if not signals["has_demo_keyword"] and not signals["has_code_signal"]:
        flags.append("no_demo_signal")
    if signals["ad_language_density"] and signals["ad_language_density"] > 0.08:
        flags.append("marketing_biased")
    if row["source"] in {"v2ex_hot", "hacker_news_algolia"}:
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
    score = 0.0
    score += 2.5 if signals.get("has_code_signal") else 0.0
    score += 1.5 if signals.get("has_demo_keyword") else 0.0
    score += 1.2 if signals.get("has_buyer_keyword") else 0.0
    score += 1.0 if signals.get("has_pain_keyword") else 0.0
    score += min(2.0, float(signals.get("metric_strength") or 0) / 2)
    score += min(1.0, max(0, int(signals.get("source_count") or 1) - 1) * 0.5)
    freshness = signals.get("freshness_hours")
    if freshness is None:
        score += 0.4
    elif freshness <= 72:
        score += 1.0
    elif freshness <= 720:
        score += 0.5
    score -= 0.8 if "marketing_biased" in candidate["risk_flags"] else 0.0
    score -= 0.7 if "generic_title" in candidate["risk_flags"] else 0.0
    score -= 0.4 if "community_only" in candidate["risk_flags"] else 0.0
    return round(max(0.0, score), 3)


def filter_candidates(candidates: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for candidate in candidates:
        score = candidate_score(candidate)
        item = {**candidate, "candidate_score": score}
        hard_flags = {"missing_url", "generic_title"}
        if hard_flags.intersection(candidate["risk_flags"]) or score < 1.0:
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
