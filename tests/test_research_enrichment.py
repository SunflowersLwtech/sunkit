from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_harness.evidence import build_evidence_bundle
from agent_harness.research import (
    AnySearchUnavailableError,
    ResearchCommandResult,
    build_widesearch_strategy,
    run_research_enrichment,
)


PRIMARY_TEXT = (
    "Demo Tool helps developers inspect logs with source-grounded traces. "
    "It documents a CLI workflow, compares runs, explains regression checks, "
    "and gives enough implementation context to support a bounded short-video analysis."
)


def primary_fetch(url: str, headers: dict[str, str] | None, timeout: float) -> dict[str, object]:
    if url == "https://example.com/demo-tool":
        return {
            "url": url,
            "status": 200,
            "content_type": "text/html",
            "sha256": "primary",
            "text": f"<html><title>Demo Tool</title><body>{PRIMARY_TEXT}</body></html>",
        }
    raise AssertionError(url)


def github_fetch(url: str, headers: dict[str, str] | None, timeout: float) -> dict[str, object]:
    if url == "https://github.com/acme/demo":
        return {
            "url": url,
            "status": 200,
            "content_type": "text/html",
            "sha256": "gh-page",
            "text": f"<html><title>acme demo</title><body>{PRIMARY_TEXT}</body></html>",
        }
    if url == "https://api.github.com/repos/acme/demo":
        return {
            "url": url,
            "status": 200,
            "content_type": "application/json",
            "sha256": "gh-api",
            "text": json.dumps(
                {
                    "description": "Trace inspection tool",
                    "stargazers_count": 42,
                    "language": "Python",
                    "license": {"spdx_id": "MIT"},
                }
            ),
        }
    if url == "https://api.github.com/repos/acme/demo/readme":
        return {
            "url": url,
            "status": 200,
            "content_type": "text/plain",
            "sha256": "gh-readme",
            "text": "Demo provides a CLI for inspecting logs, comparing runs, and identifying regressions before adoption.",
        }
    raise AssertionError(url)


class FakeAnySearchRunner:
    def __init__(self, search_output: str, extracts: dict[str, str], fail: bool = False) -> None:
        self.search_output = search_output
        self.extracts = extracts
        self.fail = fail
        self.calls: list[list[str]] = []

    def run(self, args: list[str], timeout: float) -> ResearchCommandResult:
        self.calls.append(args)
        if self.fail:
            raise AnySearchUnavailableError("quota exhausted")
        if args[0] == "search":
            return ResearchCommandResult(command=["fake", *args], stdout=self.search_output)
        if args[0] == "extract":
            url = args[1]
            if url not in self.extracts:
                raise AnySearchUnavailableError(f"missing extract fixture: {url}")
            return ResearchCommandResult(command=["fake", *args], stdout=self.extracts[url])
        raise AssertionError(args)


def extract_text_for(host: str) -> str:
    return (
        f"# Demo Tool analysis from {host}\n\n"
        "Demo Tool is described as a developer workflow aid for log inspection, run comparison, "
        "and regression review. The source discusses practical evaluation steps, caveats around "
        "hands-on verification, and why teams should inspect implementation details before adoption."
    )


class ResearchEnrichmentTests(unittest.TestCase):
    def test_successful_enrichment_writes_fact_bank_and_brief(self) -> None:
        candidate = {"candidate_id": "cand-1", "title": "Demo Tool", "canonical_url": "https://example.com/demo-tool"}
        bundle = build_evidence_bundle(candidate, fetcher=primary_fetch)
        runner = FakeAnySearchRunner(
            "Results:\nhttps://docs.example.org/demo-tool\nhttps://blog.example.net/demo-tool-review\n",
            {
                "https://docs.example.org/demo-tool": extract_text_for("docs.example.org"),
                "https://blog.example.net/demo-tool-review": extract_text_for("blog.example.net"),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            enriched, review, fact_bank, research_brief = run_research_enrichment(run_dir, candidate, bundle, runner=runner)
            self.assertEqual(review["status"], "pass")
            self.assertTrue(review["research_sufficient"])
            self.assertEqual(review["supplemental_source_count"], 2)
            self.assertEqual(len(review["independent_source_hosts"]), 2)
            self.assertEqual(enriched["source_count"], 3)
            self.assertTrue((run_dir / "anysearch_research.json").is_file())
            self.assertTrue((run_dir / "widesearch_strategy.json").is_file())
            self.assertTrue((run_dir / "fact_bank.json").is_file())
            self.assertTrue((run_dir / "topic_brief.json").is_file())
            self.assertTrue((run_dir / "research_brief.json").is_file())
            self.assertTrue((run_dir / "source_map.json").is_file())
            self.assertTrue(fact_bank["facts"])
            self.assertTrue(fact_bank["source_backed_facts"])
            self.assertEqual(research_brief["topic"], "Demo Tool")
            research = json.loads((run_dir / "anysearch_research.json").read_text())
            self.assertEqual(research["widesearch_strategy"]["subject_kind"], "generic_link")
            self.assertIn("candidate_urls", research)

    def test_anysearch_unavailable_fails_gate(self) -> None:
        candidate = {"candidate_id": "cand-1", "title": "Demo Tool", "canonical_url": "https://example.com/demo-tool"}
        bundle = build_evidence_bundle(candidate, fetcher=primary_fetch)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AnySearchUnavailableError):
                run_research_enrichment(Path(tmp), candidate, bundle, runner=FakeAnySearchRunner("", {}, fail=True))

    def test_insufficient_supplemental_sources_fail(self) -> None:
        candidate = {"candidate_id": "cand-1", "title": "Demo Tool", "canonical_url": "https://example.com/demo-tool"}
        bundle = build_evidence_bundle(candidate, fetcher=primary_fetch)
        runner = FakeAnySearchRunner(
            "https://docs.example.org/demo-tool\n",
            {"https://docs.example.org/demo-tool": extract_text_for("docs.example.org")},
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                run_research_enrichment(Path(tmp), candidate, bundle, runner=runner)
            review = json.loads((Path(tmp) / "cross_check_review.json").read_text())
            self.assertFalse(review["research_sufficient"])

    def test_duplicate_hosts_do_not_count_as_independent_sources(self) -> None:
        candidate = {"candidate_id": "cand-1", "title": "Demo Tool", "canonical_url": "https://example.com/demo-tool"}
        bundle = build_evidence_bundle(candidate, fetcher=primary_fetch)
        runner = FakeAnySearchRunner(
            "https://docs.example.org/demo-tool\nhttps://docs.example.org/demo-tool-review\n",
            {
                "https://docs.example.org/demo-tool": extract_text_for("docs.example.org"),
                "https://docs.example.org/demo-tool-review": extract_text_for("docs.example.org"),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                run_research_enrichment(Path(tmp), candidate, bundle, runner=runner)
            research = json.loads((Path(tmp) / "anysearch_research.json").read_text())
            self.assertEqual(research["supplemental_source_count"], 1)
            self.assertTrue(any(item["reason"] == "duplicate_host" for item in research["dropped_urls"]))

    def test_github_repo_keeps_api_and_readme_plus_supplements(self) -> None:
        candidate = {"candidate_id": "cand-1", "title": "acme demo", "canonical_url": "https://github.com/acme/demo"}
        bundle = build_evidence_bundle(candidate, fetcher=github_fetch)
        runner = FakeAnySearchRunner(
            "https://docs.example.org/acme-demo\nhttps://blog.example.net/acme-demo-review\n",
            {
                "https://docs.example.org/acme-demo": extract_text_for("docs.example.org"),
                "https://blog.example.net/acme-demo-review": extract_text_for("blog.example.net"),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            enriched, review, _, _ = run_research_enrichment(Path(tmp), candidate, bundle, runner=runner)
            source_ids = {source["id"] for source in enriched["sources"]}
            self.assertIn("github_repo_api", source_ids)
            self.assertIn("github_readme", source_ids)
            self.assertEqual(enriched["source_count"], 5)
            self.assertEqual(review["status"], "pass")

    def test_github_url_title_uses_repo_label_and_skips_primary_adjacent_urls(self) -> None:
        candidate = {
            "candidate_id": "cand-1",
            "title": "https://github.com/acme/demo",
            "canonical_url": "https://github.com/acme/demo",
        }
        bundle = build_evidence_bundle(candidate, fetcher=github_fetch)
        runner = FakeAnySearchRunner(
            "\n".join(
                [
                    "https://github.com/acme/demo",
                    "https://raw.githubusercontent.com/acme/demo/main/README.md",
                    "http://localhost:8080/api/debug",
                    "http://www.w3.org/2000/svg",
                    "https://docs.example.org/acme-demo",
                    "https://blog.example.net/acme-demo-review",
                ]
            ),
            {
                "https://docs.example.org/acme-demo": extract_text_for("docs.example.org"),
                "https://blog.example.net/acme-demo-review": extract_text_for("blog.example.net"),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _, review, _, _ = run_research_enrichment(run_dir, candidate, bundle, runner=runner)
            search_queries = [args[1] for args in runner.calls if args[0] == "search"]
            self.assertTrue(search_queries)
            self.assertIn("acme/demo", search_queries[0])
            self.assertNotIn("https://github.com/acme/demo", search_queries[0])
            research = json.loads((run_dir / "anysearch_research.json").read_text())
            self.assertEqual(
                research["selected_urls"],
                ["https://docs.example.org/acme-demo", "https://blog.example.net/acme-demo-review"],
            )
            self.assertEqual(research["widesearch_strategy"]["subject_kind"], "github_repo")
            self.assertTrue(any(item["reason"] == "primary_or_adjacent_host" for item in research["dropped_urls"]))
            self.assertTrue(review["research_sufficient"])

    def test_operator_topic_without_url_uses_topic_seed_then_widesearch(self) -> None:
        candidate = {
            "candidate_id": "topic-1",
            "input_mode": "operator_topic",
            "selection_source": "operator_topic",
            "title": "Demo Tool adoption strategy",
            "summary": "Explain whether teams should use Demo Tool and what to verify.",
            "canonical_url": "manual-topic://topic-1",
        }
        bundle = build_evidence_bundle(candidate)
        runner = FakeAnySearchRunner(
            "https://docs.example.org/demo-tool\nhttps://blog.example.net/demo-tool-review\n",
            {
                "https://docs.example.org/demo-tool": extract_text_for("docs.example.org"),
                "https://blog.example.net/demo-tool-review": extract_text_for("blog.example.net"),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            enriched, review, _, _ = run_research_enrichment(run_dir, candidate, bundle, runner=runner)
            search_queries = [args[1] for args in runner.calls if args[0] == "search"]
            self.assertTrue(search_queries)
            self.assertIn("Demo Tool adoption strategy", search_queries[0])
            self.assertEqual(enriched["source_kind"], "operator_topic_seed")
            self.assertEqual(enriched["source_count"], 3)
            self.assertEqual(review["status"], "pass")
            self.assertTrue(review["research_sufficient"])

    def test_widesearch_strategy_uses_competitive_depth_for_comparison_topics(self) -> None:
        candidate = {
            "candidate_id": "topic-1",
            "input_mode": "operator_topic",
            "selection_source": "operator_topic",
            "title": "browse.sh vs Browser Use competitive analysis",
            "summary": "Compare browser automation agents and risks.",
            "canonical_url": "manual-topic://topic-1",
        }
        strategy = build_widesearch_strategy(candidate)
        self.assertEqual(strategy["subject_kind"], "operator_topic")
        self.assertEqual(strategy["depth"], "competitive")
        self.assertIn("canonical_or_official", strategy["source_buckets"])
        self.assertGreaterEqual(len(strategy["search_queries"]), 5)


if __name__ == "__main__":
    unittest.main()
