from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from data_prep.scripts.run_pipeline import collect_sources, entity_for, parse_json_source, source_urls


COLLECTED_AT = "2026-05-31T00:00:00+00:00"


class DataPrepPipelineTests(unittest.TestCase):
    def test_expanded_json_source_parsers_emit_raw_rows(self) -> None:
        github_rows = parse_json_source(
            {"id": "github_search_ai_repos"},
            json.dumps(
                {
                    "items": [
                        {
                            "full_name": "acme/agent-demo",
                            "html_url": "https://github.com/acme/agent-demo",
                            "description": "Open source coding agent demo",
                            "stargazers_count": 123,
                            "forks_count": 4,
                            "created_at": "2026-05-30T00:00:00Z",
                            "topics": ["ai", "agents"],
                        }
                    ]
                }
            ),
            COLLECTED_AT,
            5,
        )
        self.assertEqual(github_rows[0]["source"], "github_search_ai_repos")
        self.assertEqual(entity_for(github_rows[0]), ("repo", "repo:acme/agent-demo"))

        devto_rows = parse_json_source(
            {"id": "devto_ai"},
            json.dumps(
                [
                    {
                        "id": 1,
                        "title": "Build an AI agent",
                        "url": "https://dev.to/acme/build-agent",
                        "description": "A practical coding agent walkthrough",
                        "published_at": "2026-05-30T00:00:00Z",
                        "positive_reactions_count": 9,
                        "comments_count": 2,
                        "tag_list": ["ai"],
                    }
                ]
            ),
            COLLECTED_AT,
            5,
        )
        self.assertEqual(devto_rows[0]["metrics"]["positive_reactions"], 9)

        lobsters_rows = parse_json_source(
            {"id": "lobsters_ai"},
            json.dumps(
                [
                    {
                        "short_id": "abc",
                        "title": "Agent tooling discussion",
                        "url": "https://example.com/agent",
                        "created_at": "2026-05-30T00:00:00Z",
                        "score": 7,
                        "comment_count": 3,
                        "tags": ["ai"],
                    }
                ]
            ),
            COLLECTED_AT,
            5,
        )
        self.assertEqual(lobsters_rows[0]["metrics"]["score"], 7)

        exa_rows = parse_json_source(
            {"id": "exa_web_search"},
            json.dumps(
                {
                    "results": [
                        {
                            "id": "exa-1",
                            "title": "Agent docs",
                            "url": "https://docs.example.com/agent",
                            "text": "Official docs and independent launch context for an AI agent tool.",
                            "publishedDate": "2026-05-30T00:00:00Z",
                            "score": 0.82,
                        }
                    ]
                }
            ),
            COLLECTED_AT,
            5,
        )
        self.assertEqual(exa_rows[0]["source"], "exa_web_search")
        self.assertEqual(entity_for(exa_rows[0])[0], "article")

        libraries_rows = parse_json_source(
            {"id": "libraries_io_search"},
            json.dumps(
                [
                    {
                        "name": "agent-demo",
                        "platform": "NPM",
                        "repository_url": "https://github.com/acme/agent-demo",
                        "description": "Agent package",
                        "stars": 42,
                        "dependent_repos_count": 5,
                        "latest_release_published_at": "2026-05-30T00:00:00Z",
                    }
                ]
            ),
            COLLECTED_AT,
            5,
        )
        self.assertEqual(libraries_rows[0]["source_item_id"], "NPM/agent-demo")
        self.assertEqual(entity_for(libraries_rows[0]), ("repo", "repo:acme/agent-demo"))

    def test_libraries_query_uses_env_key_without_source_registry_secret(self) -> None:
        old_value = os.environ.get("LIBRARIES_IO_API_KEY")
        os.environ["LIBRARIES_IO_API_KEY"] = "test-key"
        try:
            urls = source_urls(
                {
                    "id": "libraries_io_search",
                    "primary_endpoint": "https://libraries.io/api/search",
                    "queries": ["ai agent", "mcp"],
                },
                4,
            )
        finally:
            if old_value is None:
                os.environ.pop("LIBRARIES_IO_API_KEY", None)
            else:
                os.environ["LIBRARIES_IO_API_KEY"] = old_value
        self.assertEqual(len(urls), 2)
        self.assertIn("api_key=test-key", urls[0][0])
        self.assertIn("q=ai+agent", urls[0][0])

    def test_exa_query_uses_post_endpoint_without_query_secret(self) -> None:
        urls = source_urls(
            {
                "id": "exa_web_search",
                "primary_endpoint": "https://api.exa.ai/search",
                "queries": ["AI agent docs"],
            },
            3,
        )
        self.assertEqual(urls, [("https://api.exa.ai/search", "AI agent docs", 3)])

    def test_collect_sources_skips_missing_optional_env_sources(self) -> None:
        registry = {
            "sources": [
                {
                    "id": "missing_optional",
                    "priority": "P1",
                    "primary_endpoint": "https://example.invalid/feed",
                    "requires_env_any": ["SEARCHPO_TEST_MISSING_KEY"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            rows, statuses = collect_sources(registry, Path(tmp), limit=1, timeout=0.1)
        self.assertEqual(rows, [])
        self.assertTrue(statuses[0]["skipped"])
        self.assertEqual(statuses[0]["missing_required_env"], ["SEARCHPO_TEST_MISSING_KEY"])


if __name__ == "__main__":
    unittest.main()
