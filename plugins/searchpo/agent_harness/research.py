from __future__ import annotations

import json
import ipaddress
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse, urlunparse

from agent_harness.core import utc_now, write_json
from agent_harness.evidence import build_github_repo_context, cross_check_evidence, extract_text, sha256_text
from agent_harness.policy import policy_format, policy_get
from agent_harness.service_artifacts import (
    build_fact_bank_artifact,
    build_topic_brief_artifact,
    write_source_map,
)
from scripts.env_utils import load_env_file


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


class AnySearchError(RuntimeError):
    pass


class AnySearchUnavailableError(AnySearchError):
    pass


@dataclass(frozen=True)
class ResearchCommandResult:
    command: list[str]
    stdout: str
    stderr: str = ""
    returncode: int = 0


@dataclass(frozen=True)
class UrlSelection:
    selected_urls: list[str]
    dropped_urls: list[dict[str, Any]]
    candidate_urls: list[dict[str, Any]]


class ResearchRunner(Protocol):
    def run(self, args: list[str], timeout: float) -> ResearchCommandResult:
        ...


def _policy_int(path: str, default: int) -> int:
    try:
        return int(policy_get(path, default))
    except (TypeError, ValueError):
        return default


def _policy_bool(path: str, default: bool) -> bool:
    value = policy_get(path, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _policy_list(path: str, default: list[Any]) -> list[Any]:
    value = policy_get(path, default)
    return value if isinstance(value, list) else list(default)


def _skill_dir() -> Path:
    configured = str(policy_get("research.anysearch_skill_dir", "vendor/anysearch-skill"))
    path = Path(configured).expanduser()
    return path if path.is_absolute() else ROOT / path


class AnySearchCliRunner:
    def __init__(self, skill_dir: Path | None = None) -> None:
        self.skill_dir = skill_dir or _skill_dir()

    def _command_bases(self) -> list[list[str]]:
        script_dir = self.skill_dir / "scripts"
        return [
            ["python3", str(script_dir / "anysearch_cli.py")],
            ["python", str(script_dir / "anysearch_cli.py")],
            ["node", str(script_dir / "anysearch_cli.js")],
            ["bash", str(script_dir / "anysearch_cli.sh")],
        ]

    def run(self, args: list[str], timeout: float) -> ResearchCommandResult:
        if not self.skill_dir.exists():
            raise AnySearchUnavailableError(f"AnySearch skill directory is missing: {self.skill_dir}")
        failures: list[str] = []
        for base in self._command_bases():
            executable = base[0]
            script = Path(base[1])
            if not script.exists() or shutil.which(executable) is None:
                continue
            command = [*base, *args]
            try:
                env = {**load_env_file(ENV_FILE), **os.environ}
                proc = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                failures.append(f"{executable}: {exc}")
                continue
            if proc.returncode == 0:
                return ResearchCommandResult(command=command, stdout=proc.stdout, stderr=proc.stderr, returncode=0)
            failures.append(f"{executable}: rc={proc.returncode} stderr={proc.stderr[-500:]}")
        raise AnySearchUnavailableError("AnySearch CLI failed for all runtimes: " + " | ".join(failures))


def _raw_limit() -> int:
    return _policy_int("research.raw_output_max_chars", 100_000)


def _write_raw(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text[: _raw_limit()] + ("\n" if text and not text.endswith("\n") else ""), encoding="utf-8")


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = re.sub(r"/+$", "", parsed.path or "/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _is_blocked_supplemental_host(host: str) -> bool:
    if not host:
        return True
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return address.is_loopback or address.is_link_local or address.is_private or address.is_reserved or address.is_multicast


def _primary_adjacent_hosts(primary_host: str) -> set[str]:
    hosts = {primary_host} if primary_host else set()
    if primary_host == "github.com":
        hosts.update({"raw.githubusercontent.com", "gist.githubusercontent.com"})
    return hosts


def _matches_ignored_url_pattern(url: str) -> bool:
    for pattern in policy_get("research.ignored_url_patterns", []):
        try:
            if re.search(str(pattern), url, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def _walk_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"url", "link", "href", "canonical_url"} and isinstance(item, str):
                urls.append(item)
            urls.extend(_walk_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_walk_urls(item))
    elif isinstance(value, str):
        urls.extend(re.findall(r"https?://[^\s\]\)\"'<>]+", value))
    return urls


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    try:
        urls.extend(_walk_urls(json.loads(text)))
    except json.JSONDecodeError:
        urls.extend(_walk_urls(text))
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        cleaned = raw.rstrip(".,;:!?)\u3002\uff0c")
        url = _normalize_url(cleaned)
        if url and url not in seen:
            normalized.append(url)
            seen.add(url)
    return normalized


def _topic_terms(candidate: dict[str, Any]) -> list[str]:
    stopwords = {
        "about",
        "after",
        "analysis",
        "and",
        "api",
        "article",
        "articles",
        "blog",
        "blogs",
        "com",
        "docs",
        "for",
        "from",
        "github",
        "http",
        "https",
        "id",
        "into",
        "official",
        "org",
        "review",
        "search",
        "source",
        "strategy",
        "that",
        "the",
        "this",
        "tool",
        "with",
        "www",
        "分析",
        "对比",
        "搜索",
        "策略",
    }
    text = " ".join(
        str(value or "")
        for value in [
            _topic_label(candidate),
            candidate.get("summary"),
            candidate.get("entity_key"),
            candidate.get("canonical_url"),
        ]
    )
    terms: list[str] = []
    for raw in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", text.lower()):
        clean = raw.strip()
        if len(clean) < 3 or clean in stopwords:
            continue
        if clean not in terms:
            terms.append(clean)
    return terms[:12]


def _is_operator_topic_without_url(candidate: dict[str, Any]) -> bool:
    canonical_url = str(candidate.get("canonical_url") or "").strip()
    return (
        str(candidate.get("input_mode") or "") == str(policy_get("subject_inputs.operator_topic.input_mode", "operator_topic"))
        or str(candidate.get("selection_source") or "") == str(policy_get("subject_inputs.operator_topic.selection_source", "operator_topic"))
    ) and not canonical_url.startswith(("http://", "https://"))


def _looks_competitive(candidate: dict[str, Any]) -> bool:
    haystack = f"{candidate.get('title') or ''} {candidate.get('summary') or ''}".lower()
    signals = [
        " vs ",
        "versus",
        "compare",
        "comparison",
        "competitive",
        "market",
        "landscape",
        "alternative",
        "alternatives",
        "竞品",
        "对比",
        "横评",
        "市场",
        "格局",
    ]
    return any(signal in haystack for signal in signals)


def _subject_kind(candidate: dict[str, Any]) -> str:
    canonical_url = _normalize_url(str(candidate.get("canonical_url") or ""))
    title_summary = f"{_topic_label(candidate)} {candidate.get('summary') or ''}".lower()
    parsed = urlparse(canonical_url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    if _is_operator_topic_without_url(candidate):
        return "operator_topic"
    if host == "github.com" and len([part for part in parsed.path.split("/") if part]) >= 2:
        return "github_repo"
    if host in {"arxiv.org", "openreview.net", "doi.org"} or any(
        token in title_summary for token in ["paper", "arxiv", "benchmark", "论文", "基准"]
    ):
        return "paper"
    if any(token in title_summary for token in ["cve-", "osv-", "vulnerability", "security advisory", "漏洞", "安全公告"]):
        return "security_package"
    if any(token in host or token in path or token in title_summary for token in ["docs", "doc", "api", "sdk", "llms.txt"]):
        return "api_docs"
    if canonical_url:
        return "generic_link"
    return "operator_topic"


def _strategy_profile(subject_kind: str) -> dict[str, Any]:
    profiles = policy_get("research.strategy_profiles", {})
    if isinstance(profiles, dict):
        profile = profiles.get(subject_kind) or profiles.get("generic_link") or {}
        if isinstance(profile, dict):
            return dict(profile)
    return {}


def _render_queries(candidate: dict[str, Any], templates: list[Any], max_queries: int) -> list[str]:
    title = str(candidate.get("title") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    canonical_url = str(candidate.get("canonical_url") or "").strip()
    host = _host(canonical_url) if canonical_url.startswith(("http://", "https://")) else ""
    parsed_title = urlparse(title)
    if parsed_title.scheme in {"http", "https"} and parsed_title.netloc:
        title = _topic_label(candidate)
    values = {
        "title": title,
        "summary": summary,
        "url": canonical_url if canonical_url.startswith(("http://", "https://")) else "",
        "host": host,
    }
    queries: list[str] = []
    for template in templates:
        rendered = policy_format(str(template), **values).strip()
        if rendered and rendered not in queries:
            queries.append(rendered)
    return queries[:max_queries]


def build_widesearch_strategy(candidate: dict[str, Any]) -> dict[str, Any]:
    subject_kind = _subject_kind(candidate)
    profile = _strategy_profile(subject_kind)
    is_competitive = _looks_competitive(candidate)
    canonical_url = _normalize_url(str(candidate.get("canonical_url") or ""))
    if profile.get("query_templates"):
        templates = list(profile["query_templates"])
    elif canonical_url:
        templates = _policy_list("research.link_query_templates", [])
    else:
        templates = _policy_list("research.topic_query_templates", [])
    if not templates:
        templates = _policy_list(
            "research.search_query_templates",
            [
                "{title} official documentation",
                "{title} review limitations",
                "{title} source analysis",
            ],
        )
    max_queries = _policy_int(
        "research.max_competitive_search_queries" if is_competitive else "research.max_search_queries",
        8 if is_competitive else 5,
    )
    queries = _render_queries(candidate, templates, max_queries)
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "selected_candidate_id": candidate.get("candidate_id"),
        "strategy_id": profile.get("strategy_id") or subject_kind,
        "subject_kind": subject_kind,
        "depth": "competitive" if is_competitive else "standard",
        "topic_label": _topic_label(candidate),
        "canonical_url": canonical_url,
        "source_buckets": profile.get("source_buckets") or _policy_list("research.default_source_buckets", []),
        "provider_hints": profile.get("provider_hints") or [],
        "ground_api_ladder": _policy_list("research.ground_api_ladder", []),
        "query_templates": [str(item) for item in templates],
        "search_queries": queries,
        "scoring": policy_get("research.source_scoring", {}),
    }


def _search_queries(candidate: dict[str, Any]) -> list[str]:
    return [str(item) for item in build_widesearch_strategy(candidate).get("search_queries") or []]


def _source_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        clean = re.sub(r"^[#*\-\s]+", "", line).strip()
        if 8 <= len(clean) <= 140:
            return clean
    return fallback


def _snippet(text: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _label_from_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    host = parsed.netloc.lower().removeprefix("www.")
    if host == "github.com" and len(parts) >= 2:
        return f"{parts[0]}/{parts[1].removesuffix('.git')}"
    query_id = (parse_qs(parsed.query).get("id") or [""])[0].strip()
    if query_id and re.fullmatch(r"[A-Za-z0-9._-]{3,120}", query_id):
        return query_id.replace("_", " ").strip()
    if parts:
        return parts[-1].replace("-", " ").replace("_", " ").strip() or host
    return host


def _topic_label(candidate: dict[str, Any]) -> str:
    title = str(candidate.get("title") or "").strip()
    canonical_url = str(candidate.get("canonical_url") or "").strip()
    parsed = urlparse(title)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        host = parsed.netloc.lower().removeprefix("www.")
        canonical_label = _label_from_url(canonical_url)
        if canonical_label and _normalize_url(title) != _normalize_url(canonical_url):
            return canonical_label
        return _label_from_url(title) or host
    return title or "Searchpo topic"


def _supplemental_artifact(index: int, url: str, extracted_markdown: str) -> dict[str, Any]:
    extracted = extract_text(extracted_markdown, "text/markdown")
    text = extracted["text"] or extracted_markdown
    title = extracted["title"] or _source_title(text, _host(url))
    return {
        "id": f"research_supplement_{index}",
        "type": "anysearch_extract",
        "url": url,
        "host": _host(url),
        "status": "extracted",
        "content_type": "text/markdown",
        "sha256": sha256_text(extracted_markdown),
        "title": title,
        "description": extracted["description"],
        "text_chars": len(text),
        "excerpt": text[:2500],
    }


def _url_relevance_score(url: str, candidate: dict[str, Any], strategy: dict[str, Any]) -> int:
    host = _hostname(url)
    text = f"{urlparse(url).path} {urlparse(url).query} {host}".lower()
    terms = _topic_terms(candidate)
    score = sum(1 for term in terms if term.lower() in text)
    subject_kind = str(strategy.get("subject_kind") or "")
    if subject_kind == "github_repo" and any(host.endswith(item) for item in ("github.com", "github.io", "readthedocs.io")):
        score += 1
    if subject_kind == "paper" and any(host.endswith(item) for item in ("arxiv.org", "openreview.net", "paperswithcode.com")):
        score += 1
    if subject_kind == "security_package" and any(host.endswith(item) for item in ("nvd.nist.gov", "osv.dev", "github.com")):
        score += 1
    if subject_kind == "api_docs" and any(token in text for token in ("docs", "api", "sdk", "llms")):
        score += 1
    return score


def _drop_record(url: str, reason: str, *, host: str = "", score: int | None = None, query: str = "") -> dict[str, Any]:
    record: dict[str, Any] = {"url": url, "reason": reason}
    if host:
        record["host"] = host
    if score is not None:
        record["relevance_score"] = score
    if query:
        record["query"] = query
    return record


def _select_urls(search_outputs: list[tuple[str, str]], candidate: dict[str, Any], strategy: dict[str, Any]) -> UrlSelection:
    canonical_url = _normalize_url(str(candidate.get("canonical_url") or ""))
    primary_host = _hostname(canonical_url) if canonical_url else ""
    primary_adjacent_hosts = _primary_adjacent_hosts(primary_host)
    seen_urls = {canonical_url} if canonical_url else set()
    seen_hosts: set[str] = set()
    require_independent_hosts = _policy_bool("research.require_independent_hosts", True)
    exclude_primary_host = _policy_bool("research.exclude_primary_host", True)
    selected: list[str] = []
    dropped: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    max_extracts = _policy_int("research.max_extracts", 4)
    min_relevance = _policy_int("research.min_url_relevance_score", 1)
    ignored_hosts = {str(item).lower() for item in policy_get("research.ignored_hosts", [])}
    for query, output in search_outputs:
        for url in extract_urls(output):
            normalized = _normalize_url(url)
            host = _hostname(normalized)
            netloc_host = _host(normalized)
            score = _url_relevance_score(normalized, candidate, strategy) if normalized else 0
            candidates.append({"url": normalized or url, "host": host or netloc_host, "query": query, "relevance_score": score})
            if not normalized:
                dropped.append(_drop_record(url, "invalid_url", query=query))
                continue
            if normalized in seen_urls:
                dropped.append(_drop_record(normalized, "duplicate_url", host=host, score=score, query=query))
                continue
            if host in ignored_hosts or netloc_host in ignored_hosts:
                dropped.append(_drop_record(normalized, "ignored_host", host=host, score=score, query=query))
                continue
            if _matches_ignored_url_pattern(normalized):
                dropped.append(_drop_record(normalized, "ignored_url_pattern", host=host, score=score, query=query))
                continue
            if _is_blocked_supplemental_host(host):
                dropped.append(_drop_record(normalized, "blocked_local_or_private_host", host=host, score=score, query=query))
                continue
            if exclude_primary_host and primary_host and host in primary_adjacent_hosts:
                dropped.append(_drop_record(normalized, "primary_or_adjacent_host", host=host, score=score, query=query))
                continue
            if require_independent_hosts and host in seen_hosts:
                dropped.append(_drop_record(normalized, "duplicate_host", host=host, score=score, query=query))
                continue
            if score < min_relevance:
                dropped.append(_drop_record(normalized, "low_url_relevance", host=host, score=score, query=query))
                continue
            selected.append(normalized)
            seen_urls.add(normalized)
            seen_hosts.add(host)
            if len(selected) >= max_extracts:
                return UrlSelection(selected, dropped, candidates)
    return UrlSelection(selected, dropped, candidates)


def _extract_quality_issue(artifact: dict[str, Any], candidate: dict[str, Any]) -> str:
    text = str(artifact.get("excerpt") or "")
    compact = re.sub(r"\s+", " ", text).strip().lower()
    if not compact:
        return "empty_extract"
    low_quality_patterns = [
        "page not found",
        "404 not found",
        "access denied",
        "enable javascript",
        "please enable cookies",
        "captcha",
    ]
    if any(pattern in compact[:1200] for pattern in low_quality_patterns):
        return "low_quality_extract"
    min_score = _policy_int("research.min_extract_relevance_score", 1)
    terms = _topic_terms(candidate)
    score = sum(1 for term in terms if term.lower() in compact)
    if terms and score < min_score:
        return "low_extract_relevance"
    return ""


def _fact_bank(candidate: dict[str, Any], bundle: dict[str, Any], supplemental: list[dict[str, Any]]) -> dict[str, Any]:
    return build_fact_bank_artifact(candidate, bundle, supplemental)


def _research_brief(candidate: dict[str, Any], fact_bank: dict[str, Any], supplemental: list[dict[str, Any]]) -> dict[str, Any]:
    topic_candidate = {**candidate, "title": _topic_label(candidate)}
    return build_topic_brief_artifact(topic_candidate, fact_bank, supplemental)


def _merge_research(
    candidate: dict[str, Any],
    bundle: dict[str, Any],
    supplemental: list[dict[str, Any]],
    fact_bank: dict[str, Any],
    research_brief: dict[str, Any],
    research_supplemental: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    research_supplemental = research_supplemental if research_supplemental is not None else supplemental
    sources = [*(bundle.get("sources") or []), *supplemental]
    combined_text = "\n".join(str(source.get("excerpt") or source.get("json") or "") for source in sources)
    evidence_summary = dict(bundle.get("evidence_summary") or {})
    existing_facts = [str(item) for item in evidence_summary.get("source_facts") or []]
    fact_bank_facts = [str(item) for item in fact_bank.get("source_backed_facts") or []]
    merged_facts: list[str] = []
    for fact in [*existing_facts, *fact_bank_facts]:
        if fact and fact not in merged_facts:
            merged_facts.append(fact)
    existing_angles = [str(item) for item in evidence_summary.get("constructive_angles") or []]
    extra_angles = [
        str(research_brief.get("angle") or ""),
        *[str(item) for item in research_brief.get("visual_opportunities") or []],
    ]
    merged_angles: list[str] = []
    for angle in [*existing_angles, *extra_angles]:
        if angle and angle not in merged_angles:
            merged_angles.append(angle)
    enriched = dict(bundle)
    enriched["sources"] = sources
    enriched["source_count"] = len(sources)
    enriched["combined_text_sha256"] = sha256_text(combined_text)
    enriched["evidence_summary"] = {
        **evidence_summary,
        "source_facts": merged_facts[:16],
        "constructive_angles": merged_angles[:12],
        "combined_excerpt": combined_text[:5000],
        "topic_brief": research_brief,
        "research_brief": research_brief,
        "fact_bank_risk_notes": fact_bank.get("risk_notes") or [],
    }
    enriched["research"] = {
        "status": "pending_cross_check",
        "fact_bank_status": fact_bank.get("status") or "missing",
        "supplemental_source_count": len(research_supplemental),
        "independent_source_hosts": sorted({str(source.get("host") or "") for source in research_supplemental if source.get("host")}),
    }
    return enriched


def _enriched_cross_check(candidate: dict[str, Any], bundle: dict[str, Any], fact_bank: dict[str, Any]) -> dict[str, Any]:
    review = cross_check_evidence(candidate, bundle)
    research = bundle.get("research") or {}
    supplemental_count = int(research.get("supplemental_source_count") or 0)
    hosts = [str(item) for item in research.get("independent_source_hosts") or [] if str(item)]
    min_sources = _policy_int("research.min_supplemental_sources", 2)
    errors = list(review.get("errors") or [])
    fact_bank_status = "pass" if fact_bank.get("source_backed_facts") else "fail"
    research_sufficient = supplemental_count >= min_sources and len(hosts) >= min_sources and fact_bank_status == "pass"
    if not research_sufficient:
        errors.append(
            f"research enrichment insufficient: supplemental_source_count={supplemental_count}, "
            f"independent_source_hosts={len(hosts)}, fact_bank_status={fact_bank_status}"
        )
    checks = dict(review.get("checks") or {})
    checks.update(
        {
            "research_sufficient": research_sufficient,
            "supplemental_source_count": supplemental_count,
            "independent_source_hosts": hosts,
            "fact_bank_status": fact_bank_status,
        }
    )
    review["checks"] = checks
    review["research_sufficient"] = research_sufficient
    review["supplemental_source_count"] = supplemental_count
    review["independent_source_hosts"] = hosts
    review["fact_bank_status"] = fact_bank_status
    review["errors"] = errors
    review["status"] = "pass" if not errors else "fail"
    review["source_facts"] = (bundle.get("evidence_summary") or {}).get("source_facts") or []
    review["constructive_angles"] = (bundle.get("evidence_summary") or {}).get("constructive_angles") or []
    research = dict(bundle.get("research") or {})
    research["status"] = "pass" if review["status"] == "pass" else "fail"
    research["fact_bank_status"] = fact_bank_status
    research["research_sufficient"] = research_sufficient
    bundle["research"] = research
    return review


def run_research_enrichment(
    run_dir: Path,
    candidate: dict[str, Any],
    evidence_bundle: dict[str, Any],
    *,
    runner: ResearchRunner | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    runner = runner or AnySearchCliRunner()
    timeout = float(policy_get("research.timeout_seconds", 30))
    max_results = _policy_int("research.max_results_per_query", 5)
    min_extract_chars = _policy_int("research.min_extract_chars", 180)
    research_dir = run_dir / "research"
    raw_dir = research_dir / "anysearch_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    strategy = build_widesearch_strategy(candidate)
    write_json(run_dir / "widesearch_strategy.json", strategy)
    search_queries = [str(query) for query in strategy.get("search_queries") or []]
    search_outputs: list[tuple[str, str]] = []
    commands: list[dict[str, Any]] = []
    try:
        for idx, query in enumerate(search_queries, start=1):
            args = ["search", query, "--max_results", str(max_results)]
            result = runner.run(args, timeout)
            _write_raw(raw_dir / f"search_{idx:02d}.txt", result.stdout)
            search_outputs.append((query, result.stdout))
            commands.append({"kind": "search", "query": query, "command": result.command, "stderr": result.stderr[-1000:]})
    except AnySearchError:
        raise
    except Exception as exc:
        raise AnySearchUnavailableError(str(exc)) from exc

    url_selection = _select_urls(search_outputs, candidate, strategy)
    selected_urls = url_selection.selected_urls
    supplemental: list[dict[str, Any]] = []
    anysearch_supplemental: list[dict[str, Any]] = []
    repo_context: dict[str, Any] | None = None
    extract_errors: list[str] = []
    dropped_urls = list(url_selection.dropped_urls)
    for idx, url in enumerate(selected_urls, start=1):
        try:
            result = runner.run(["extract", url], timeout)
        except Exception as exc:
            extract_errors.append(f"{url}: {exc}")
            continue
        _write_raw(raw_dir / f"extract_{idx:02d}.txt", result.stdout)
        artifact = _supplemental_artifact(idx, url, result.stdout)
        commands.append({"kind": "extract", "url": url, "command": result.command, "stderr": result.stderr[-1000:]})
        if int(artifact.get("text_chars") or 0) < min_extract_chars:
            dropped_urls.append(
                _drop_record(
                    url,
                    "extract_too_short",
                    host=str(artifact.get("host") or ""),
                    score=_url_relevance_score(url, candidate, strategy),
                )
            )
            continue
        quality_issue = _extract_quality_issue(artifact, candidate)
        if quality_issue:
            dropped_urls.append(
                _drop_record(
                    url,
                    quality_issue,
                    host=str(artifact.get("host") or ""),
                    score=_url_relevance_score(url, candidate, strategy),
                )
            )
            continue
        supplemental.append(artifact)
        anysearch_supplemental.append(artifact)
        if not repo_context and str(artifact.get("host") or "").lower() == "github.com":
            repo_context = build_github_repo_context(url, timeout=timeout)
            if repo_context:
                for source in repo_context.get("sources") or []:
                    if isinstance(source, dict):
                        supplemental.append(source)

    bundle_with_repo_context = dict(evidence_bundle)
    if repo_context:
        bundle_with_repo_context["repo_context"] = repo_context

    preliminary_bundle = _merge_research(
        candidate,
        bundle_with_repo_context,
        supplemental,
        {"source_backed_facts": []},
        {"angle": "", "visual_opportunities": []},
        research_supplemental=anysearch_supplemental,
    )
    fact_bank = _fact_bank(candidate, preliminary_bundle, supplemental)
    research_brief = _research_brief(candidate, fact_bank, supplemental)
    enriched_bundle = _merge_research(
        candidate,
        bundle_with_repo_context,
        supplemental,
        fact_bank,
        research_brief,
        research_supplemental=anysearch_supplemental,
    )
    review = _enriched_cross_check(candidate, enriched_bundle, fact_bank)

    research_record = {
        "schema_version": 1,
        "created_at": utc_now(),
        "selected_candidate_id": candidate.get("candidate_id"),
        "anysearch_skill_dir": str(_skill_dir()),
        "widesearch_strategy": strategy,
        "search_queries": search_queries,
        "candidate_urls": url_selection.candidate_urls,
        "selected_urls": selected_urls,
        "dropped_urls": dropped_urls,
        "extract_errors": extract_errors,
        "supplemental_source_count": len(anysearch_supplemental),
        "independent_source_hosts": sorted({str(source.get("host") or "") for source in anysearch_supplemental if source.get("host")}),
        "supporting_source_count": len(supplemental) - len(anysearch_supplemental),
        "commands": commands,
        "repo_context": {
            "status": (repo_context or {}).get("status"),
            "repo": (repo_context or {}).get("repo"),
            "fact_count": len((repo_context or {}).get("facts") or []),
            "source_count": len((repo_context or {}).get("sources") or []),
            "errors": (repo_context or {}).get("errors") or [],
        } if repo_context else None,
        "status": "pass" if review.get("status") == "pass" else "fail",
    }
    strategy["candidate_url_count"] = len(url_selection.candidate_urls)
    strategy["selected_urls"] = selected_urls
    strategy["dropped_url_count"] = len(dropped_urls)
    write_json(run_dir / "widesearch_strategy.json", strategy)
    write_json(run_dir / "anysearch_research.json", research_record)
    write_json(run_dir / "fact_bank.json", fact_bank)
    write_json(run_dir / "topic_brief.json", research_brief)
    write_json(run_dir / "research_brief.json", research_brief)
    if repo_context:
        write_json(run_dir / "repo_context.json", repo_context)
    write_source_map(run_dir, enriched_bundle)
    write_json(run_dir / "evidence_bundle.json", enriched_bundle)
    write_json(run_dir / "cross_check_review.json", review)
    for source in supplemental:
        _write_raw(run_dir / "evidence" / f"{source['id']}.txt", str(source.get("excerpt") or ""))
    if review.get("status") != "pass":
        raise RuntimeError("research cross-check failed: " + "; ".join(str(item) for item in review.get("errors") or []))
    return enriched_bundle, review, fact_bank, research_brief
