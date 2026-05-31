from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse, urlunparse

from agent_harness.core import utc_now, write_json
from agent_harness.evidence import cross_check_evidence, extract_text, sha256_text
from agent_harness.policy import policy_format, policy_get
from agent_harness.service_artifacts import (
    build_fact_bank_artifact,
    build_topic_brief_artifact,
    write_source_map,
)


ROOT = Path(__file__).resolve().parents[1]


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
                proc = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=os.environ.copy(),
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


def _search_queries(candidate: dict[str, Any]) -> list[str]:
    title = str(candidate.get("title") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    canonical_url = str(candidate.get("canonical_url") or "").strip()
    host = _host(canonical_url) if canonical_url.startswith(("http://", "https://")) else ""
    templates = policy_get(
        "research.search_query_templates",
        [
            "{title} official documentation",
            "{title} review limitations",
            "{title} source analysis",
        ],
    )
    values = {"title": title, "summary": summary, "url": canonical_url, "host": host}
    queries: list[str] = []
    for template in templates:
        rendered = policy_format(str(template), **values).strip()
        if rendered and rendered not in queries:
            queries.append(rendered)
    max_queries = _policy_int("research.max_search_queries", 3)
    return queries[:max_queries]


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


def _topic_label(candidate: dict[str, Any]) -> str:
    title = str(candidate.get("title") or "").strip()
    parsed = urlparse(title)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        host = parsed.netloc.lower().removeprefix("www.")
        if host == "github.com" and len(parts) >= 2:
            return f"{parts[0]}/{parts[1].removesuffix('.git')}"
        if parts:
            return parts[-1].replace("-", " ").replace("_", " ").strip() or host
        return host
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


def _select_urls(search_outputs: list[str], candidate: dict[str, Any]) -> list[str]:
    canonical_url = _normalize_url(str(candidate.get("canonical_url") or ""))
    primary_host = _host(canonical_url) if canonical_url else ""
    seen_urls = {canonical_url} if canonical_url else set()
    seen_hosts: set[str] = set()
    require_independent_hosts = _policy_bool("research.require_independent_hosts", True)
    exclude_primary_host = _policy_bool("research.exclude_primary_host", True)
    selected: list[str] = []
    max_extracts = _policy_int("research.max_extracts", 4)
    ignored_hosts = {str(item).lower() for item in policy_get("research.ignored_hosts", [])}
    for output in search_outputs:
        for url in extract_urls(output):
            normalized = _normalize_url(url)
            host = _host(normalized)
            if not normalized or normalized in seen_urls:
                continue
            if host in ignored_hosts:
                continue
            if exclude_primary_host and primary_host and host == primary_host:
                continue
            if require_independent_hosts and host in seen_hosts:
                continue
            selected.append(normalized)
            seen_urls.add(normalized)
            seen_hosts.add(host)
            if len(selected) >= max_extracts:
                return selected
    return selected


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
) -> dict[str, Any]:
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
        "status": "pass",
        "fact_bank_status": "pass",
        "supplemental_source_count": len(supplemental),
        "independent_source_hosts": sorted({str(source.get("host") or "") for source in supplemental if source.get("host")}),
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

    search_outputs: list[str] = []
    commands: list[dict[str, Any]] = []
    try:
        for idx, query in enumerate(_search_queries(candidate), start=1):
            args = ["search", query, "--max_results", str(max_results)]
            result = runner.run(args, timeout)
            _write_raw(raw_dir / f"search_{idx:02d}.txt", result.stdout)
            search_outputs.append(result.stdout)
            commands.append({"kind": "search", "query": query, "command": result.command, "stderr": result.stderr[-1000:]})
    except AnySearchError:
        raise
    except Exception as exc:
        raise AnySearchUnavailableError(str(exc)) from exc

    selected_urls = _select_urls(search_outputs, candidate)
    supplemental: list[dict[str, Any]] = []
    extract_errors: list[str] = []
    for idx, url in enumerate(selected_urls, start=1):
        try:
            result = runner.run(["extract", url], timeout)
        except Exception as exc:
            extract_errors.append(f"{url}: {exc}")
            continue
        _write_raw(raw_dir / f"extract_{idx:02d}.txt", result.stdout)
        artifact = _supplemental_artifact(idx, url, result.stdout)
        commands.append({"kind": "extract", "url": url, "command": result.command, "stderr": result.stderr[-1000:]})
        if int(artifact.get("text_chars") or 0) >= min_extract_chars:
            supplemental.append(artifact)

    preliminary_bundle = _merge_research(
        candidate,
        evidence_bundle,
        supplemental,
        {"source_backed_facts": []},
        {"angle": "", "visual_opportunities": []},
    )
    fact_bank = _fact_bank(candidate, preliminary_bundle, supplemental)
    research_brief = _research_brief(candidate, fact_bank, supplemental)
    enriched_bundle = _merge_research(candidate, evidence_bundle, supplemental, fact_bank, research_brief)
    review = _enriched_cross_check(candidate, enriched_bundle, fact_bank)

    research_record = {
        "schema_version": 1,
        "created_at": utc_now(),
        "selected_candidate_id": candidate.get("candidate_id"),
        "anysearch_skill_dir": str(_skill_dir()),
        "search_queries": _search_queries(candidate),
        "selected_urls": selected_urls,
        "extract_errors": extract_errors,
        "supplemental_source_count": len(supplemental),
        "independent_source_hosts": sorted({str(source.get("host") or "") for source in supplemental if source.get("host")}),
        "commands": commands,
        "status": "pass" if review.get("status") == "pass" else "fail",
    }
    write_json(run_dir / "anysearch_research.json", research_record)
    write_json(run_dir / "fact_bank.json", fact_bank)
    write_json(run_dir / "topic_brief.json", research_brief)
    write_json(run_dir / "research_brief.json", research_brief)
    write_source_map(run_dir, enriched_bundle)
    write_json(run_dir / "evidence_bundle.json", enriched_bundle)
    write_json(run_dir / "cross_check_review.json", review)
    for source in supplemental:
        _write_raw(run_dir / "evidence" / f"{source['id']}.txt", str(source.get("excerpt") or ""))
    if review.get("status") != "pass":
        raise RuntimeError("research cross-check failed: " + "; ".join(str(item) for item in review.get("errors") or []))
    return enriched_bundle, review, fact_bank, research_brief
