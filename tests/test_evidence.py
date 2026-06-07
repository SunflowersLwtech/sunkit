import json
import os
import unittest
from unittest.mock import patch

from agent_harness.evidence import build_evidence_bundle, build_github_repo_context, x_status_id


class QwenBlogEvidenceTests(unittest.TestCase):
    def test_qwen_blog_uses_article_api_for_primary_text(self) -> None:
        candidate = {
            "candidate_id": "topic-qwen",
            "canonical_url": "https://qwen.ai/blog?id=qwen3.7-plus",
            "title": "Qwen3.7-Plus",
        }

        def fake_fetch(url, headers, timeout):
            self.assertEqual(
                url,
                "https://qwen.ai/api/v2/article/?language=en-US&path=qwen3.7-plus&type=qwen_ai",
            )
            self.assertEqual(headers["Accept"], "application/json")
            return {
                "url": url,
                "status": 200,
                "content_type": "application/json",
                "sha256": "qwen",
                "text": json.dumps(
                    {
                        "success": True,
                        "request_id": "req-1",
                        "data": {
                            "id": "article-1",
                            "type": "qwen_ai",
                            "title": "Qwen3.7-Plus: Multimodal Agent Intelligence",
                            "content": (
                                "<html><head><title>Qwen3.7-Plus</title></head>"
                                "<body>Qwen3.7-Plus is a multimodal agent model with vision-language capabilities, "
                                "coding support, tool use, GUI operation, and productivity workflows for agent loops.</body></html>"
                            ),
                            "extra": {"description": "Qwen3.7-Plus release article"},
                        },
                    }
                ),
            }

        bundle = build_evidence_bundle(candidate, fetcher=fake_fetch)

        self.assertEqual(bundle["source_kind"], "qwen_blog_api")
        self.assertEqual(bundle["canonical_detail_method"], "qwen_article_api")
        self.assertGreater(bundle["sources"][0]["text_chars"], 100)
        self.assertIn("Multimodal Agent Intelligence", bundle["sources"][0]["title"])


class XStatusEvidenceTests(unittest.TestCase):
    def test_x_status_id_extracts_status_url(self) -> None:
        self.assertEqual(x_status_id("https://x.com/dair_ai/status/2059691141302542445?s=46"), "2059691141302542445")
        self.assertEqual(x_status_id("https://twitter.com/dair_ai/status/2059691141302542445"), "2059691141302542445")
        self.assertIsNone(x_status_id("https://x.com/dair_ai"))

    def test_x_status_api_builds_primary_source_facts(self) -> None:
        candidate = {
            "candidate_id": "topic_a6578c46c84b",
            "canonical_url": "https://x.com/dair_ai/status/2059691141302542445?s=46",
            "title": "Harness Complexity Paradox arXiv 2605.26731 DAIR.AI X post",
        }
        payload = {
            "data": {
                "id": "2059691141302542445",
                "created_at": "2026-05-27T17:40:09.000Z",
                "text": "Short text",
                "note_tweet": {
                    "text": "Stronger models do not always need lighter harnesses.",
                    "entities": {
                        "urls": [
                            {
                                "url": "https://t.co/3D1FUdQ3Y8",
                                "expanded_url": "https://arxiv.org/abs/2605.26731",
                            }
                        ]
                    },
                },
            },
            "includes": {
                "users": [{"username": "dair_ai", "name": "DAIR.AI"}],
                "media": [{"url": "https://pbs.twimg.com/media/HJV-LUuawAAc3gJ.jpg"}],
            },
        }

        def fake_fetch(url, headers, timeout):
            self.assertIn("api.twitter.com/2/tweets/2059691141302542445", url)
            self.assertEqual(headers["Authorization"], "Bearer test-token")
            return {
                "url": url,
                "status": 200,
                "content_type": "application/json",
                "sha256": "abc",
                "text": json.dumps(payload),
            }

        with patch.dict(os.environ, {"X_BEARER_TOKEN": "test-token"}, clear=False):
            bundle = build_evidence_bundle(candidate, fetcher=fake_fetch)

        self.assertEqual(bundle["source_kind"], "x_status_api")
        self.assertEqual(bundle["canonical_detail_method"], "x_api_v2_status_lookup")
        self.assertIn("https://arxiv.org/abs/2605.26731", bundle["expanded_urls"])
        self.assertIn("https://pbs.twimg.com/media/HJV-LUuawAAc3gJ.jpg", bundle["expanded_urls"])
        self.assertEqual(bundle["sources"][0]["type"], "x_status_api")
        source_facts = bundle["evidence_summary"]["source_facts"]
        self.assertIn("title: Harness Complexity Paradox arXiv 2605.26731 DAIR.AI X post", source_facts)
        self.assertIn("description: Stronger models do not always need lighter harnesses.", source_facts)

    def test_github_repo_context_fetches_code_aware_facts(self) -> None:
        def fake_fetch(url, headers, timeout):
            if url == "https://api.github.com/repos/mem0ai/mem0":
                return {
                    "url": url,
                    "status": 200,
                    "content_type": "application/json",
                    "sha256": "repo",
                    "text": json.dumps(
                        {
                            "description": "Universal memory layer for AI Agents",
                            "language": "Python",
                            "license": {"spdx_id": "Apache-2.0"},
                            "default_branch": "main",
                        }
                    ),
                }
            if url == "https://api.github.com/repos/mem0ai/mem0/readme":
                return {"url": url, "status": 200, "content_type": "text/plain", "sha256": "readme", "text": "Mem0 README"}
            if url == "https://api.github.com/repos/mem0ai/mem0/contents?ref=main":
                return {
                    "url": url,
                    "status": 200,
                    "content_type": "application/json",
                    "sha256": "root",
                    "text": json.dumps([{"name": "mem0"}, {"name": "server"}, {"name": "mem0-ts"}]),
                }
            if url.startswith("https://raw.githubusercontent.com/mem0ai/mem0/main/"):
                raise RuntimeError("raw unavailable in test")
            if url.endswith("/contents/mem0/__init__.py?ref=main"):
                return {
                    "url": url,
                    "status": 200,
                    "content_type": "text/plain",
                    "sha256": "init",
                    "text": "from mem0.client.main import MemoryClient, AsyncMemoryClient\nfrom mem0.memory.main import Memory, AsyncMemory\n",
                }
            if url.endswith("/contents/mem0/memory/main.py?ref=main"):
                return {
                    "url": url,
                    "status": 200,
                    "content_type": "text/plain",
                    "sha256": "main",
                    "text": ("# import preamble\n" * 300) + "class Memory:\n def add(self): pass\n def search(self): pass\n user_id = agent_id = run_id = None\n self.vector_store = self.embedder = self.llm = None\n",
                }
            raise RuntimeError("not found")

        context = build_github_repo_context("https://github.com/mem0ai/mem0", fetcher=fake_fetch)

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["repo"], "mem0ai/mem0")
        self.assertIn("mem0/__init__.py exports API surface", " ".join(context["facts"]))
        self.assertIn("mem0/memory/main.py contains add/search flows", " ".join(context["facts"]))
        self.assertIn("repo root includes: mem0, mem0-ts, server", " ".join(context["facts"]))


if __name__ == "__main__":
    unittest.main()
