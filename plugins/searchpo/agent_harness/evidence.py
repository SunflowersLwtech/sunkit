from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional

from agent_harness.core import utc_now, write_json
from agent_harness.policy import policy_get


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
FetchFn = Callable[[str, Optional[dict[str, str]], float], dict[str, Any]]


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.meta_description = ""
        self.text_parts: list[str] = []
        self._title = False
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        if tag_lower == "title":
            self._title = True
        if tag_lower in {"script", "style", "noscript", "svg"}:
            self._skip = True
        if tag_lower == "meta" and attrs_dict.get("name", "").lower() in {"description", "og:description"}:
            self.meta_description = attrs_dict.get("content", "").strip()
        if tag_lower == "meta" and attrs_dict.get("property", "").lower() in {"og:description", "twitter:description"}:
            self.meta_description = attrs_dict.get("content", "").strip()

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower == "title":
            self._title = False
        if tag_lower in {"script", "style", "noscript", "svg"}:
            self._skip = False

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._title:
            self.title_parts.append(text)
        elif not self._skip:
            self.text_parts.append(text)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _env_value(key: str) -> str:
    value = os.environ.get(key, "")
    if value:
        return value
    if not ENV_PATH.exists():
        return ""
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        env_key, env_value = line.split("=", 1)
        if env_key.strip() == key:
            return env_value.strip().strip('"').strip("'")
    return ""


def _http_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": "searchpo-evidence-fetch/1.0",
        "Accept": "text/html,application/json,text/plain,application/vnd.github.raw+json;q=0.9,*/*;q=0.1",
    }
    token = _env_value("GITHUB_TOKEN") or _env_value("GH_TOKEN") or _env_value("GITHUB_PERSONAL_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra:
        headers.update(extra)
    return headers


def fetch_url(url: str, headers: dict[str, str] | None = None, timeout: float = 25.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_http_headers(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or response.getcode())
            content_type = response.headers.get("content-type", "")
            payload = response.read(int(policy_get("evidence_fetch.max_bytes", 900_000)))
    except urllib.error.HTTPError as exc:
        detail = exc.read(600).decode("utf-8", "replace")
        raise RuntimeError(f"evidence fetch HTTP {exc.code} for {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"evidence fetch failed for {url}: {exc}") from exc
    if status < 200 or status >= 300:
        raise RuntimeError(f"evidence fetch non-2xx status {status} for {url}")
    text = payload.decode("utf-8", "replace")
    return {"url": url, "status": status, "content_type": content_type, "sha256": sha256_bytes(payload), "text": text}


def extract_text(payload: str, content_type: str = "") -> dict[str, str]:
    if "html" not in content_type.lower() and "<html" not in payload[:500].lower():
        text = re.sub(r"\s+", " ", payload).strip()
        return {"title": "", "description": "", "text": text}
    parser = TextExtractor()
    parser.feed(payload)
    text = re.sub(r"\s+", " ", " ".join(parser.text_parts)).strip()
    return {
        "title": re.sub(r"\s+", " ", " ".join(parser.title_parts)).strip(),
        "description": parser.meta_description,
        "text": text,
    }


def http_source_url(candidate: dict[str, Any]) -> str:
    url = str(candidate.get("canonical_url") or "").strip()
    if not re.match(r"^https?://", url):
        raise RuntimeError("selected subject must have an http(s) URL before evidence fetch; pass SEARCHPO_TOPIC_URL or SEARCHPO_LINK")
    return url


def _qwen_blog_article_path(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower().removeprefix("www.") != "qwen.ai" or parsed.path.rstrip("/") != "/blog":
        return ""
    path = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", path):
        return ""
    return path


def _qwen_blog_api_url(path: str) -> str:
    return "https://qwen.ai/api/v2/article/?" + urllib.parse.urlencode(
        {"language": "en-US", "path": path, "type": "qwen_ai"}
    )


def _qwen_blog_source_artifact(source_id: str, fetched: dict[str, Any], canonical_url: str) -> dict[str, Any]:
    raw_text = str(fetched.get("text") or "")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Qwen article API returned invalid JSON") from exc
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    content = str(data.get("content") or "")
    extracted = extract_text(content, "text/html")
    text = extracted["text"]
    title = str(data.get("title") or extracted["title"] or "").strip()
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    description = str(extra.get("description") or extracted["description"] or "").strip()
    if not text and description:
        text = description
    if not title:
        raise RuntimeError("Qwen article API response missing article title")
    if not text:
        raise RuntimeError("Qwen article API response missing article content")
    return {
        "id": source_id,
        "type": "qwen_blog_api",
        "url": canonical_url,
        "api_url": fetched.get("url"),
        "status": fetched.get("status"),
        "content_type": fetched.get("content_type"),
        "sha256": fetched.get("sha256"),
        "title": title,
        "description": description,
        "text_chars": len(text),
        "excerpt": text[:2500],
        "json": {
            "success": payload.get("success"),
            "request_id": payload.get("request_id"),
            "id": data.get("id"),
            "type": data.get("type"),
            "title": title,
            "extra": extra,
            "content_sha256": sha256_text(content),
        },
        "captured_at": utc_now(),
    }


def _fetch_qwen_blog_source(url: str, fetcher: FetchFn, timeout: float) -> dict[str, Any] | None:
    path = _qwen_blog_article_path(url)
    if not path:
        return None
    fetched = fetcher(_qwen_blog_api_url(path), {"Accept": "application/json"}, timeout)
    return _qwen_blog_source_artifact("primary_url", fetched, url)


def x_status_id(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part == "status" and index + 1 < len(parts):
            status_id = parts[index + 1]
            if re.fullmatch(r"\d{6,30}", status_id):
                return status_id
    return None


def _x_api_url(status_id: str) -> str:
    params = urllib.parse.urlencode(
        {
            "tweet.fields": "author_id,created_at,public_metrics,entities,attachments,conversation_id,possibly_sensitive,lang,note_tweet",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "username,name,verified,description,public_metrics",
            "media.fields": "url,width,height,type",
        }
    )
    return f"https://api.twitter.com/2/tweets/{status_id}?{params}"


def _x_bearer_token() -> str:
    return _env_value("X_BEARER_TOKEN") or _env_value("TWITTER_BEARER_TOKEN")


def _x_expanded_urls(tweet: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    entity_sets = [
        ((tweet.get("entities") or {}).get("urls") or []),
        (((tweet.get("note_tweet") or {}).get("entities") or {}).get("urls") or []),
    ]
    for items in entity_sets:
        for item in items:
            expanded = str(item.get("expanded_url") or item.get("url") or "").strip()
            if expanded:
                urls.append(expanded)
    seen: set[str] = set()
    unique: list[str] = []
    for item in urls:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _x_media_urls(payload: dict[str, Any]) -> list[str]:
    media = ((payload.get("includes") or {}).get("media") or [])
    return [str(item.get("url") or "").strip() for item in media if str(item.get("url") or "").strip()]


def _x_author(payload: dict[str, Any]) -> dict[str, Any]:
    users = ((payload.get("includes") or {}).get("users") or [])
    return users[0] if users and isinstance(users[0], dict) else {}


def _x_source_artifact(source_id: str, fetched: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    raw_text = str(fetched.get("text") or "")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("X status API returned invalid JSON") from exc
    tweet = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if not tweet:
        raise RuntimeError("X status API response missing data")
    author = _x_author(payload)
    username = str(author.get("username") or "").strip()
    display_name = str(author.get("name") or "").strip()
    note_text = str(((tweet.get("note_tweet") or {}).get("text") or tweet.get("text") or "")).strip()
    expanded_urls = _x_expanded_urls(tweet)
    media_urls = _x_media_urls(payload)
    lines = [
        f"X status by @{username} ({display_name})" if username or display_name else "X status",
        f"Created at: {tweet.get('created_at')}" if tweet.get("created_at") else "",
        note_text,
        "Expanded URLs: " + ", ".join(expanded_urls) if expanded_urls else "",
        "Media URLs: " + ", ".join(media_urls) if media_urls else "",
    ]
    excerpt = "\n".join(line for line in lines if line).strip()
    title = str(candidate.get("title") or "").strip() or (f"X status by @{username}" if username else "X status")
    return {
        "id": source_id,
        "type": "x_status_api",
        "url": str(candidate.get("canonical_url") or fetched.get("url") or ""),
        "status": fetched.get("status"),
        "content_type": fetched.get("content_type"),
        "sha256": fetched.get("sha256"),
        "title": title,
        "description": note_text[:420],
        "text_chars": len(excerpt),
        "excerpt": excerpt[:2500],
        "json": payload,
        "captured_at": utc_now(),
    }


def _fetch_x_status_source(url: str, candidate: dict[str, Any], fetcher: FetchFn, timeout: float) -> tuple[dict[str, Any], list[str]] | None:
    status_id = x_status_id(url)
    if not status_id:
        return None
    token = _x_bearer_token()
    if not token:
        raise RuntimeError("X status URL requires X_BEARER_TOKEN or TWITTER_BEARER_TOKEN for primary evidence fetch")
    fetched = fetcher(_x_api_url(status_id), {"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout)
    source = _x_source_artifact("primary_url", fetched, candidate)
    expanded_urls = _x_expanded_urls(source["json"].get("data") or {})
    expanded_urls.extend(_x_media_urls(source["json"]))
    return source, expanded_urls


def _is_operator_topic_seed(candidate: dict[str, Any]) -> bool:
    manual_scheme = str(policy_get("subject_inputs.operator_topic.manual_url_scheme", "manual-topic://"))
    url = str(candidate.get("canonical_url") or "")
    return (
        str(candidate.get("input_mode") or "") == str(policy_get("subject_inputs.operator_topic.input_mode", "operator_topic"))
        or str(candidate.get("selection_source") or "") == str(policy_get("subject_inputs.operator_topic.selection_source", "operator_topic"))
        or url.startswith(manual_scheme)
    )


def _operator_topic_seed_bundle(candidate: dict[str, Any]) -> dict[str, Any]:
    title = str(candidate.get("title") or "operator topic").strip()
    summary = str(candidate.get("summary") or "").strip()
    url = str(candidate.get("canonical_url") or "").strip()
    seed_text = "\n".join(
        item
        for item in [
            f"Operator topic: {title}",
            f"Operator context: {summary}" if summary else "",
            "This is a user-supplied research seed, not external evidence. Use widesearch supplemental sources before making public claims.",
        ]
        if item
    )
    source = {
        "id": "operator_topic_seed",
        "type": "operator_topic_seed",
        "url": url,
        "status": "seed",
        "evidence_role": "research_seed",
        "requires_widesearch": True,
        "external_evidence": False,
        "content_type": "text/plain",
        "sha256": sha256_text(seed_text),
        "title": title,
        "description": summary,
        "text_chars": len(seed_text),
        "excerpt": seed_text,
    }
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "selected_candidate_id": candidate.get("candidate_id"),
        "canonical_url": url,
        "source_kind": "operator_topic_seed",
        "evidence_role": "research_seed",
        "requires_widesearch": True,
        "external_evidence": False,
        "sources": [source],
        "source_count": 1,
        "combined_text_sha256": sha256_text(seed_text),
        "evidence_summary": {
            "source_facts": ["operator supplied topic seed; external claims require widesearch corroboration"],
            "constructive_angles": [
                "Turn the topic into answerable research questions.",
                "Separate what the user asked from what external sources actually support.",
                "Cross-check at least two independent extracted sources before copy generation.",
            ],
            "candidate_terms": _terms(candidate),
            "combined_excerpt": seed_text[:3200],
        },
    }


def github_repo(url: str) -> tuple[str, str] | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    return parts[0], parts[1].removesuffix(".git")


def _source_artifact(source_id: str, source_type: str, fetched: dict[str, Any]) -> dict[str, Any]:
    extracted = extract_text(str(fetched.get("text") or ""), str(fetched.get("content_type") or ""))
    text = extracted["text"]
    return {
        "id": source_id,
        "type": source_type,
        "url": fetched.get("url"),
        "status": fetched.get("status"),
        "content_type": fetched.get("content_type"),
        "sha256": fetched.get("sha256"),
        "title": extracted["title"],
        "description": extracted["description"],
        "text_chars": len(text),
        "excerpt": text[:2500],
    }


def _json_source_artifact(source_id: str, source_type: str, fetched: dict[str, Any]) -> dict[str, Any]:
    raw_text = str(fetched.get("text") or "")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"evidence source {source_id} did not return valid JSON") from exc
    return {
        "id": source_id,
        "type": source_type,
        "url": fetched.get("url"),
        "status": fetched.get("status"),
        "content_type": fetched.get("content_type"),
        "sha256": fetched.get("sha256"),
        "json": data,
        "text_chars": len(raw_text),
    }


def _repo_facts(repo_json: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    if repo_json.get("description"):
        facts.append(f"description: {repo_json['description']}")
    if repo_json.get("stargazers_count") is not None:
        facts.append(f"stars: {repo_json['stargazers_count']}")
    if repo_json.get("language"):
        facts.append(f"language: {repo_json['language']}")
    license_data = repo_json.get("license") or {}
    if license_data.get("spdx_id"):
        facts.append(f"license: {license_data['spdx_id']}")
    topics = repo_json.get("topics") or []
    if topics:
        facts.append("topics: " + ", ".join(str(topic) for topic in topics[:8]))
    return facts


def _repo_context_fact_from_source(path: str, text: str) -> list[str]:
    facts: list[str] = []
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return facts
    if path.endswith("__init__.py"):
        exported = sorted(set(re.findall(r"\b(MemoryClient|AsyncMemoryClient|Memory|AsyncMemory)\b", text)))
        if exported:
            facts.append(f"{path} exports API surface: {', '.join(exported)}")
    if path.endswith("memory/main.py"):
        if re.search(r"class\s+Memory\b", text):
            facts.append(f"{path} defines the core Memory engine")
        if "vector_store" in text and "embedder" in text and "llm" in text:
            facts.append(f"{path} wires embedder, vector store, LLM, history, and optional reranking components")
        if re.search(r"def\s+add\b", text) and re.search(r"def\s+search\b", text):
            facts.append(f"{path} contains add/search flows for writing and retrieving memories")
        if all(token in text for token in ["user_id", "agent_id", "run_id"]):
            facts.append(f"{path} scopes memory operations by user_id, agent_id, or run_id")
    if path.endswith("utils/factory.py"):
        providers = [
            item
            for item in ["qdrant", "chroma", "pgvector", "milvus", "pinecone", "redis", "elasticsearch", "supabase", "weaviate", "faiss"]
            if re.search(rf"['\"]{re.escape(item)}['\"]", text, re.I)
        ]
        if providers:
            facts.append(f"{path} exposes vector-store/provider factory options: {', '.join(providers[:10])}")
    if path.endswith("server/main.py"):
        routes = sorted(set(re.findall(r"@app\.(?:get|post|put|delete)\(\s*['\"]([^'\"]+)['\"]", text)))
        if routes:
            facts.append(f"{path} exposes REST routes including {', '.join(routes[:8])}")
    if path.endswith("open-source/overview.mdx") and ("library" in compact.lower() or "self-host" in compact.lower()):
        facts.append(f"{path} documents open-source deployment modes and control boundaries")
    return facts


def build_github_repo_context(
    url: str,
    *,
    fetcher: FetchFn = fetch_url,
    timeout: float = 25.0,
    source_id_prefix: str = "github_repo_context",
) -> dict[str, Any] | None:
    repo = github_repo(url)
    if not repo:
        return None
    owner, name = repo
    sources: list[dict[str, Any]] = []
    facts: list[str] = []
    errors: list[str] = []

    def fetch_source(source_id: str, source_type: str, source_url: str, headers: dict[str, str] | None, *, json_source: bool = False) -> dict[str, Any] | None:
        try:
            fetched = fetcher(source_url, headers, timeout)
            return _json_source_artifact(source_id, source_type, fetched) if json_source else _source_artifact(source_id, source_type, fetched)
        except Exception as exc:
            errors.append(f"{source_id}: {exc}")
            return None

    repo_source = fetch_source(
        f"{source_id_prefix}_api",
        "github_repo_api",
        f"https://api.github.com/repos/{owner}/{name}",
        {"Accept": "application/vnd.github+json"},
        json_source=True,
    )
    default_branch = "main"
    if repo_source:
        sources.append(repo_source)
        repo_json = repo_source.get("json") or {}
        default_branch = str(repo_json.get("default_branch") or default_branch)
        facts.extend(_repo_facts(repo_json))

    readme_source = fetch_source(
        f"{source_id_prefix}_readme",
        "github_readme",
        f"https://api.github.com/repos/{owner}/{name}/readme",
        {"Accept": "application/vnd.github.raw"},
    )
    if readme_source:
        sources.append(readme_source)
        excerpt = str(readme_source.get("excerpt") or "")
        title = readme_source.get("title") or f"{owner}/{name} README"
        facts.append(f"README: {title or excerpt[:140]}")

    contents_source = fetch_source(
        f"{source_id_prefix}_root_contents",
        "github_root_contents",
        f"https://api.github.com/repos/{owner}/{name}/contents?ref={default_branch}",
        {"Accept": "application/vnd.github+json"},
        json_source=True,
    )
    if contents_source:
        sources.append(contents_source)
        items = contents_source.get("json") or []
        if isinstance(items, list):
            names = [str(item.get("name")) for item in items if isinstance(item, dict) and item.get("name")]
            if names:
                preferred = [
                    "mem0",
                    "mem0-ts",
                    "server",
                    "openmemory",
                    "evaluation",
                    "examples",
                    "docs",
                    "cookbooks",
                    "tests",
                    "cli",
                ]
                ordered = [name for name in preferred if name in names]
                ordered.extend(name for name in names if name not in ordered)
                facts.append(f"repo root includes: {', '.join(ordered[:12])}")

    candidate_paths = [
        f"{name}/__init__.py",
        f"{name}/memory/main.py",
        f"{name}/utils/factory.py",
        "server/main.py",
        "docs/open-source/overview.mdx",
    ]
    def fetch_raw_file_source(source_id: str, path: str) -> tuple[dict[str, Any], str] | None:
        raw_url = f"https://raw.githubusercontent.com/{owner}/{name}/{default_branch}/{urllib.parse.quote(path, safe='/')}"
        try:
            fetched = fetcher(raw_url, {"Accept": "text/plain,*/*;q=0.1"}, timeout)
            return _source_artifact(source_id, "github_source_file", fetched), str(fetched.get("text") or "")
        except Exception as raw_exc:
            try:
                api_url = f"https://api.github.com/repos/{owner}/{name}/contents/{path}?ref={default_branch}"
                fetched = fetcher(api_url, {"Accept": "application/vnd.github.raw"}, timeout)
                return _source_artifact(source_id, "github_source_file", fetched), str(fetched.get("text") or "")
            except Exception as api_exc:
                errors.append(f"{source_id}: raw fetch failed: {raw_exc}; contents API failed: {api_exc}")
                return None

    for path in candidate_paths:
        fetched_source = fetch_raw_file_source(
            f"{source_id_prefix}_{re.sub(r'[^a-zA-Z0-9]+', '_', path).strip('_')}",
            path,
        )
        if not fetched_source:
            continue
        source, raw_text = fetched_source
        if not source:
            continue
        sources.append(source)
        facts.extend(_repo_context_fact_from_source(path, raw_text))

    seen: set[str] = set()
    unique_facts = []
    for fact in facts:
        clean = re.sub(r"\s+", " ", str(fact)).strip()
        if clean and clean not in seen:
            seen.add(clean)
            unique_facts.append(clean)

    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "repo": f"{owner}/{name}",
        "url": f"https://github.com/{owner}/{name}",
        "default_branch": default_branch,
        "sources": sources,
        "facts": unique_facts[:20],
        "visual_brief": [
            "Use repo/code-aware visuals: file tree, SDK/API call path, memory write/read pipeline, and deployment/adoption boundaries.",
            "Show concrete source paths instead of generic source hosts.",
            "For memory projects, separate write path, retrieval path, scope boundary, and storage/provider choices.",
        ],
        "errors": errors[:12],
        "status": "pass" if len(unique_facts) >= 4 else "partial",
    }


def _terms(candidate: dict[str, Any]) -> list[str]:
    values = [candidate.get("title"), candidate.get("entity_key"), candidate.get("canonical_url")]
    terms: list[str] = []
    for value in values:
        for part in re.split(r"[\s/_:.-]+", str(value or "")):
            clean = part.strip()
            if len(clean) >= 4 and clean.lower() not in {"https", "http", "github", "repo", "topic"}:
                terms.append(clean)
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            unique.append(term)
    return unique[:8]


def build_evidence_bundle(candidate: dict[str, Any], fetcher: FetchFn = fetch_url, timeout: float = 25.0) -> dict[str, Any]:
    if _is_operator_topic_seed(candidate) and not re.match(r"^https?://", str(candidate.get("canonical_url") or "")):
        return _operator_topic_seed_bundle(candidate)
    url = http_source_url(candidate)
    sources: list[dict[str, Any]] = []
    source_kind = "web_url"
    canonical_detail_method = "http_fetch"
    expanded_urls: list[str] = []
    qwen_blog_source = _fetch_qwen_blog_source(url, fetcher, timeout)
    if qwen_blog_source:
        sources.append(qwen_blog_source)
        source_kind = "qwen_blog_api"
        canonical_detail_method = "qwen_article_api"
    elif x_status_source := _fetch_x_status_source(url, candidate, fetcher, timeout):
        primary_source, expanded_urls = x_status_source
        sources.append(primary_source)
        source_kind = "x_status_api"
        canonical_detail_method = "x_api_v2_status_lookup"
    else:
        primary = fetcher(url, None, timeout)
        sources.append(_source_artifact("primary_url", "primary_page", primary))
    repo = github_repo(url)
    repo_facts: list[str] = []
    if repo:
        owner, name = repo
        repo_api = fetcher(f"https://api.github.com/repos/{owner}/{name}", {"Accept": "application/vnd.github+json"}, timeout)
        repo_source = _json_source_artifact("github_repo_api", "github_repo_api", repo_api)
        sources.append(repo_source)
        repo_facts = _repo_facts(repo_source["json"])
        readme = fetcher(
            f"https://api.github.com/repos/{owner}/{name}/readme",
            {"Accept": "application/vnd.github.raw"},
            timeout,
        )
        sources.append(_source_artifact("github_readme", "github_readme", readme))
    combined_text = "\n".join(str(source.get("excerpt") or source.get("json") or "") for source in sources)
    source_facts = repo_facts or [
        item
        for item in [
            f"title: {sources[0].get('title')}" if sources[0].get("title") else "",
            f"description: {sources[0].get('description')}" if sources[0].get("description") else "",
        ]
        if item
    ]
    if not source_facts:
        raise RuntimeError("primary source has no extractable source facts")
    constructive_angles = [
        "Explain the concrete user problem this source appears to address.",
        "Explain what is directly evidenced by the source, and what still needs hands-on verification.",
        "Give a practical adoption or evaluation path instead of a hype claim.",
    ]
    bundle = {
        "schema_version": 1,
        "created_at": utc_now(),
        "selected_candidate_id": candidate.get("candidate_id"),
        "canonical_url": url,
        "source_kind": "github_repo" if repo else source_kind,
        "canonical_detail_method": "github_api_and_readme" if repo else canonical_detail_method,
        "expanded_urls": expanded_urls,
        "sources": sources,
        "source_count": len(sources),
        "combined_text_sha256": sha256_text(combined_text),
        "evidence_summary": {
            "source_facts": source_facts,
            "constructive_angles": constructive_angles,
            "candidate_terms": _terms(candidate),
            "combined_excerpt": combined_text[:3200],
        },
    }
    return bundle


def cross_check_evidence(candidate: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    sources = bundle.get("sources") or []
    combined = "\n".join(str(source.get("excerpt") or source.get("json") or "") for source in sources)
    min_chars = int(policy_get("evidence_fetch.min_primary_chars", 180))
    primary = next((source for source in sources if source.get("id") == "primary_url"), {})
    if bundle.get("source_kind") == "operator_topic_seed":
        primary = next((source for source in sources if source.get("id") == "operator_topic_seed"), {})
    errors: list[str] = []
    warnings: list[str] = []
    if not sources:
        errors.append("evidence_bundle has no fetched sources")
    if bundle.get("source_kind") == "operator_topic_seed":
        warnings.append("operator topic seed is not external evidence; research enrichment must supply independent sources")
    elif int(primary.get("text_chars") or 0) < min_chars:
        errors.append(f"primary source text too short for cross-check: {primary.get('text_chars') or 0} chars")
    if bundle.get("source_kind") == "github_repo":
        source_ids = {str(source.get("id")) for source in sources}
        for required in ("github_repo_api", "github_readme"):
            if required not in source_ids:
                errors.append(f"GitHub source missing required evidence: {required}")
    terms = _terms(candidate)
    if terms and not any(term.lower() in combined.lower() for term in terms):
        warnings.append(f"selected candidate terms not directly found in fetched text: {terms}")
    checks = {
        "primary_source_loaded": bool(primary),
        "primary_text_chars": int(primary.get("text_chars") or 0),
        "source_count": len(sources),
        "github_repo_requires_api_and_readme": bundle.get("source_kind") != "github_repo" or not errors,
        "candidate_terms_found_or_warned": not any("candidate terms" in warning for warning in warnings),
    }
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "selected_candidate_id": candidate.get("candidate_id"),
        "status": "pending_research" if bundle.get("source_kind") == "operator_topic_seed" and not errors else ("pass" if not errors else "fail"),
        "canonical_url": bundle.get("canonical_url"),
        "source_kind": bundle.get("source_kind"),
        "checks": checks,
        "source_facts": (bundle.get("evidence_summary") or {}).get("source_facts") or [],
        "constructive_angles": (bundle.get("evidence_summary") or {}).get("constructive_angles") or [],
        "warnings": warnings,
        "errors": errors,
    }


def strong_research_review_errors(review: dict[str, Any] | None) -> list[str]:
    review = review or {}
    min_supplemental = int(policy_get("research.min_supplemental_sources", 2))
    min_independent_hosts = int(policy_get("research.min_independent_hosts", min_supplemental))
    hosts = [str(host) for host in review.get("independent_source_hosts") or [] if str(host).strip()]
    errors: list[str] = []
    if review.get("status") != "pass":
        errors.append(f"cross_check_review.status is {review.get('status') or 'missing'}")
    if review.get("research_sufficient") is not True:
        errors.append("cross_check_review.research_sufficient is not true")
    if review.get("fact_bank_status") != "pass":
        errors.append(f"cross_check_review.fact_bank_status is {review.get('fact_bank_status') or 'missing'}")
    if int(review.get("supplemental_source_count") or 0) < min_supplemental:
        errors.append(
            f"cross_check_review.supplemental_source_count below policy minimum: "
            f"{review.get('supplemental_source_count') or 0} < {min_supplemental}"
        )
    if len(set(hosts)) < min_independent_hosts:
        errors.append(f"cross_check_review.independent_source_hosts below policy minimum: {len(set(hosts))} < {min_independent_hosts}")
    return errors


def write_evidence_artifacts(run_dir: Path, candidate: dict[str, Any], fetcher: FetchFn = fetch_url, timeout: float = 25.0) -> tuple[dict[str, Any], dict[str, Any]]:
    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_evidence_bundle(candidate, fetcher=fetcher, timeout=timeout)
    review = cross_check_evidence(candidate, bundle)
    write_json(run_dir / "evidence_bundle.json", bundle)
    write_json(run_dir / "cross_check_review.json", review)
    for source in bundle.get("sources") or []:
        source_id = str(source.get("id") or "source")
        if source.get("excerpt"):
            (evidence_dir / f"{source_id}.txt").write_text(str(source["excerpt"]) + "\n", encoding="utf-8")
        if source.get("json") is not None:
            write_json(evidence_dir / f"{source_id}.json", source["json"])
    if review.get("status") != "pass" and bundle.get("source_kind") != "operator_topic_seed":
        raise RuntimeError("cross-check failed: " + "; ".join(str(item) for item in review.get("errors") or []))
    return bundle, review
