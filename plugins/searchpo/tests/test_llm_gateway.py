from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import scripts.deepseek_polish as polish_module
from scripts.content_scorer import score_content
from scripts.llm_gateway import gateway_config, parse_json_text, strip_code_fences
from tests.test_deepseek_polish import polish_payload

GATEWAY_URL = "https://gateway.example.test/v1/chat/completions"
NO_ENV_FILE = Path("/nonexistent/searchpo-test.env")


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.headers: dict[str, str] = {}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def chat_reply(content: str) -> dict[str, object]:
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}], "usage": {"total_tokens": 12}}


def http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(GATEWAY_URL, code, "error", {}, io.BytesIO(body.encode("utf-8")))


def request_json(request: object) -> dict[str, object]:
    return json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]


class FenceStrippingTests(unittest.TestCase):
    def test_fenced_json_is_parsed(self) -> None:
        self.assertEqual(parse_json_text('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_json_text('```\n{"a": 2}\n```'), {"a": 2})

    def test_prose_and_reasoning_around_the_fence_are_ignored(self) -> None:
        text = '<think>score it {carefully}</think>Here is the result:\n```json\n{"overall": 8.5}\n```\nDone.'
        self.assertEqual(parse_json_text(text), {"overall": 8.5})

    def test_unterminated_fence_still_parses(self) -> None:
        self.assertEqual(parse_json_text('```json\n{"a": 3}'), {"a": 3})

    def test_unfenced_json_whose_strings_contain_fences_is_not_mangled(self) -> None:
        payload = {"component_code": "```tsx\nreturn <div/>;\n```", "title": "x"}
        self.assertEqual(parse_json_text(json.dumps(payload)), payload)

    def test_strip_code_fences_leaves_plain_text_alone(self) -> None:
        self.assertEqual(strip_code_fences('  {"a": 1}  '), '{"a": 1}')

    def test_garbage_raises(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            parse_json_text("no json here")


class GatewayConfigTests(unittest.TestCase):
    def test_unset_url_keeps_native_providers(self) -> None:
        with patch.dict(os.environ, {"SEARCHPO_LLM_URL": "", "SEARCHPO_LLM_API_KEY": "k", "SEARCHPO_LLM_MODEL": "m"}):
            self.assertIsNone(gateway_config(NO_ENV_FILE))

    def test_url_requires_key_and_model(self) -> None:
        with patch.dict(os.environ, {"SEARCHPO_LLM_URL": GATEWAY_URL, "SEARCHPO_LLM_API_KEY": "", "SEARCHPO_LLM_MODEL": "m"}):
            with self.assertRaises(SystemExit):
                gateway_config(NO_ENV_FILE)
        with patch.dict(os.environ, {"SEARCHPO_LLM_URL": GATEWAY_URL, "SEARCHPO_LLM_API_KEY": "k", "SEARCHPO_LLM_MODEL": ""}):
            with self.assertRaises(SystemExit):
                gateway_config(NO_ENV_FILE)

    def test_scorer_model_overrides_only_for_scorer(self) -> None:
        env = {
            "SEARCHPO_LLM_URL": GATEWAY_URL,
            "SEARCHPO_LLM_API_KEY": "gateway-test-key",
            "SEARCHPO_LLM_MODEL": "qwen/qwen3.8-flash",
            "SEARCHPO_LLM_SCORER_MODEL": "openai/gpt-5.4-mini",
        }
        with patch.dict(os.environ, env):
            self.assertEqual(gateway_config(NO_ENV_FILE)["model"], "qwen/qwen3.8-flash")
            self.assertEqual(gateway_config(NO_ENV_FILE, role="scorer")["model"], "openai/gpt-5.4-mini")
            self.assertEqual(gateway_config(NO_ENV_FILE)["url"], GATEWAY_URL)


class PolishThroughGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_url = polish_module.CHAT_GATEWAY_URL

    def tearDown(self) -> None:
        polish_module.CHAT_GATEWAY_URL = self._old_url

    def _polish(self) -> dict[str, object]:
        return polish_module.deepseek_chat(
            "gateway-test-key",
            "qwen/qwen3.8-flash",
            {"candidate_id": "scrapling", "title": "D4Vinci/Scrapling", "canonical_url": "https://github.com/D4Vinci/Scrapling"},
            {"topic_brief": {}, "fact_bank": {"source_backed_facts": []}},
            {"evidence_summary": {"source_facts": []}},
            {"status": "pass", "research_sufficient": True},
            timeout=1,
            video_seconds=30,
        )

    def test_gateway_request_shape_and_fenced_reply(self) -> None:
        polish_module.CHAT_GATEWAY_URL = GATEWAY_URL
        fenced = "```json\n" + json.dumps(polish_payload(), ensure_ascii=False) + "\n```"
        requests: list[object] = []

        def fake_urlopen(request: object, timeout: float = 0) -> FakeResponse:
            requests.append(request)
            return FakeResponse(chat_reply(fenced))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            polished = self._polish()

        self.assertEqual(polished["polished_title"], "Scrapling 先看问题")
        first = requests[0]
        self.assertEqual(first.full_url, GATEWAY_URL)  # type: ignore[attr-defined]
        self.assertEqual(first.get_method(), "POST")  # type: ignore[attr-defined]
        self.assertEqual(first.get_header("Authorization"), "Bearer gateway-test-key")  # type: ignore[attr-defined]
        self.assertEqual(first.get_header("Content-type"), "application/json")  # type: ignore[attr-defined]
        body = request_json(first)
        self.assertEqual(body["model"], "qwen/qwen3.8-flash")
        self.assertEqual([message["role"] for message in body["messages"]], ["system", "user"])  # type: ignore[index]
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertNotIn("thinking", body)

    def test_without_gateway_polish_still_calls_deepseek(self) -> None:
        polish_module.CHAT_GATEWAY_URL = ""
        urls: list[str] = []

        def fake_urlopen(request: object, timeout: float = 0) -> FakeResponse:
            urls.append(request.full_url)  # type: ignore[attr-defined]
            return FakeResponse(chat_reply(json.dumps(polish_payload(), ensure_ascii=False)))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self._polish()

        self.assertTrue(urls)
        self.assertTrue(all(url == "https://api.deepseek.com/chat/completions" for url in urls))

    def test_rejected_parameters_are_relaxed_once(self) -> None:
        polish_module.CHAT_GATEWAY_URL = GATEWAY_URL
        bodies: list[dict[str, object]] = []
        errors = [
            http_error(400, '{"error": {"message": "Unsupported value: \'temperature\' does not support 0.4 with this model."}}'),
            http_error(400, '{"error": {"message": "Unsupported parameter: \'max_tokens\' is not supported with this model. Use \'max_completion_tokens\' instead."}}'),
        ]

        def fake_urlopen(request: object, timeout: float = 0) -> FakeResponse:
            bodies.append(request_json(request))
            if errors:
                raise errors.pop(0)
            return FakeResponse(chat_reply(json.dumps(polish_payload(), ensure_ascii=False)))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self._polish()

        self.assertIn("temperature", bodies[0])
        self.assertNotIn("temperature", bodies[1])
        self.assertIn("max_tokens", bodies[1])
        self.assertNotIn("max_tokens", bodies[2])
        self.assertEqual(bodies[2]["max_completion_tokens"], bodies[0]["max_tokens"])

    def test_gateway_errors_do_not_echo_the_key(self) -> None:
        polish_module.CHAT_GATEWAY_URL = GATEWAY_URL
        with patch("urllib.request.urlopen", side_effect=http_error(401, "invalid key gateway-test-key")):
            with self.assertRaises(RuntimeError) as caught:
                polish_module.request_deepseek("gateway-test-key", "m", {"model": "m", "messages": []}, 1)
        self.assertNotIn("gateway-test-key", str(caught.exception))
        self.assertIn("HTTP 401", str(caught.exception))


class ScorerThroughGatewayTests(unittest.TestCase):
    def test_scorer_sends_openai_format_and_parses_fenced_scores(self) -> None:
        scores = {"scores": {"hook_strength": 8}, "overall": 8.4, "suggestions": [], "verdict": "pass"}
        requests: list[object] = []

        def fake_urlopen(request: object, timeout: float = 0) -> FakeResponse:
            requests.append(request)
            return FakeResponse(chat_reply("```json\n" + json.dumps(scores) + "\n```"))

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = score_content(
                "gateway-test-key",
                "openai/gpt-5.4-mini",
                {"polished_title": "t", "voiceover_text": "v"},
                {"title": "Demo"},
                {"evidence_summary": {}},
                {"status": "pass"},
                5,
                NO_ENV_FILE,
                gateway_url=GATEWAY_URL,
            )

        self.assertEqual(result, scores)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].full_url, GATEWAY_URL)  # type: ignore[attr-defined]
        body = request_json(requests[0])
        self.assertEqual(body["model"], "openai/gpt-5.4-mini")
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIn("scoring_dimensions", body["messages"][1]["content"])  # type: ignore[index]
        self.assertNotIn("contents", body)


if __name__ == "__main__":
    unittest.main()
