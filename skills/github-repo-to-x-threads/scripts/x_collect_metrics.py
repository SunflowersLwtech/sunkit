#!/usr/bin/env python3
"""Collect X API metrics for tweets recorded in x_publish_log.json."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from x_publish_thread import load_env, read_json, refresh_access_token, write_json  # noqa: E402


API_BASE = "https://api.x.com"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def tweet_ids_from_log(repo_run_dir: Path) -> list[str]:
    log_path = repo_run_dir / "x_publish_log.json"
    if not log_path.exists():
        return []
    log = read_json(log_path)
    ids = [str(post.get("tweet_id")) for post in log.get("posts", []) if post.get("tweet_id")]
    return list(dict.fromkeys(ids))


def api_get(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def collect(ids: list[str], token: str, include_private: bool) -> tuple[dict[str, Any], str]:
    fields = ["created_at", "public_metrics", "text"]
    if include_private:
        fields.extend(["organic_metrics", "non_public_metrics"])
    query = urllib.parse.urlencode({"ids": ",".join(ids), "tweet.fields": ",".join(fields)})
    url = f"{API_BASE}/2/tweets?{query}"
    mode = "private_plus_public" if include_private else "public_only"
    return api_get(url, token), mode


def aggregate(snapshot: dict[str, Any]) -> dict[str, float]:
    totals = {
        "impressions": 0.0,
        "likes": 0.0,
        "reposts": 0.0,
        "replies": 0.0,
        "bookmarks": 0.0,
        "profile_clicks": 0.0,
        "url_link_clicks": 0.0,
    }
    for tweet in snapshot.get("data", []):
        public = tweet.get("public_metrics") or {}
        organic = tweet.get("organic_metrics") or {}
        non_public = tweet.get("non_public_metrics") or {}
        totals["impressions"] += float(
            organic.get("impression_count")
            or non_public.get("impression_count")
            or public.get("impression_count")
            or public.get("view_count")
            or 0
        )
        totals["likes"] += float(public.get("like_count", 0) or 0)
        totals["reposts"] += float(public.get("retweet_count", 0) or 0) + float(public.get("quote_count", 0) or 0)
        totals["replies"] += float(public.get("reply_count", 0) or 0)
        totals["bookmarks"] += float(public.get("bookmark_count", 0) or 0)
        totals["profile_clicks"] += float(
            organic.get("user_profile_clicks") or non_public.get("user_profile_clicks") or 0
        )
        totals["url_link_clicks"] += float(organic.get("url_link_clicks") or non_public.get("url_link_clicks") or 0)
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_run_dir", help="Run source directory containing x_publish_log.json")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--ids", nargs="*", help="Override tweet ids")
    parser.add_argument("--public-only", action="store_true")
    args = parser.parse_args()

    repo_run_dir = Path(args.repo_run_dir).expanduser().resolve()
    ids = args.ids or tweet_ids_from_log(repo_run_dir)
    if not ids:
        raise SystemExit("No tweet ids found. Provide --ids or publish first.")

    env, env_path = load_env([repo_run_dir / ".env", Path.cwd() / ".env", Path(args.env_file)])
    token = env.get("X_OAUTH2_ACCESS_TOKEN") or env.get("X_USER_ACCESS_TOKEN", "")
    if not token:
        token = refresh_access_token(env, env_path)
    if not token:
        raise SystemExit("Missing X OAuth2 user token")

    try:
        payload, mode = collect(ids, token, not args.public_only)
    except RuntimeError as exc:
        if "401" in str(exc):
            token = refresh_access_token(env, env_path)
            if not token:
                raise
            payload, mode = collect(ids, token, not args.public_only)
        else:
            raise
    result = {
        "schema_version": 1,
        "created_at": utc_now(),
        "repo_run_dir": str(repo_run_dir),
        "tweet_ids": ids,
        "collection_mode": mode,
        "raw": payload,
        "aggregate_metrics": aggregate(payload),
    }
    write_json(repo_run_dir / "x_metrics_snapshot.json", result)
    print(f"Collected {len(payload.get('data', []))} tweet(s), mode={mode}")
    print(f"Wrote: {repo_run_dir / 'x_metrics_snapshot.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
