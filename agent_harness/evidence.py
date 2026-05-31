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
    url = http_source_url(candidate)
    sources: list[dict[str, Any]] = []
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
        source_facts.append("primary source text loaded")
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
        "source_kind": "github_repo" if repo else "web_url",
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
    errors: list[str] = []
    warnings: list[str] = []
    if not sources:
        errors.append("evidence_bundle has no fetched sources")
    if int(primary.get("text_chars") or 0) < min_chars:
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
        "status": "pass" if not errors else "fail",
        "canonical_url": bundle.get("canonical_url"),
        "source_kind": bundle.get("source_kind"),
        "checks": checks,
        "source_facts": (bundle.get("evidence_summary") or {}).get("source_facts") or [],
        "constructive_angles": (bundle.get("evidence_summary") or {}).get("constructive_angles") or [],
        "warnings": warnings,
        "errors": errors,
    }


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
    if review.get("status") != "pass":
        raise RuntimeError("cross-check failed: " + "; ".join(str(item) for item in review.get("errors") or []))
    return bundle, review
