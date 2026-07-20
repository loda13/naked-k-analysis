import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

import naked_k_news_llm


class FakeResponse:
    def __init__(self, payload=None, status_code=200, error=None):
        self.payload = payload
        self.status_code = status_code
        self.error = error

    def raise_for_status(self):
        if self.error is not None:
            raise self.error
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class AnthropicNewsConfigTests(unittest.TestCase):
    def test_config_explicit_arguments_override_env_and_dotenv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text(
                "ANTHROPIC_BASE_URL=https://dotenv.example/prefix\n"
                "ANTHROPIC_AUTH_TOKEN=dotenv-token\n"
                "NAKED_K_NEWS_MODEL=dotenv-model\n",
                encoding="utf-8",
            )
            config = naked_k_news_llm.load_news_config(
                env={
                    "ANTHROPIC_BASE_URL": "https://env.example/prefix",
                    "ANTHROPIC_AUTH_TOKEN": "env-token",
                    "NAKED_K_NEWS_MODEL": "env-model",
                },
                enabled=True,
                base_url="https://explicit.example/prefix",
                model="explicit-model",
                dotenv_path=dotenv_path,
            )
        self.assertEqual(config.base_url, "https://explicit.example/prefix")
        self.assertEqual(config.auth_token, "env-token")
        self.assertEqual(config.model, "explicit-model")

    def test_config_uses_priority_within_each_source_and_redacts_token(self):
        config = naked_k_news_llm.load_news_config(
            env={
                "ANTHROPIC_BASE_URL": "https://anthropic.example/api",
                "NAKED_K_NEWS_BASE_URL": "https://news.example/api",
                "NAKED_K_LLM_BASE_URL": "https://llm.example/api",
                "LLM_BASE_URL": "https://fallback.example/api",
                "ANTHROPIC_AUTH_TOKEN": "fake-secret-token",
                "ANTHROPIC_API_KEY": "wrong-token",
                "NAKED_K_NEWS_API_KEY": "wrong-token-2",
                "NAKED_K_LLM_API_KEY": "wrong-token-3",
                "LLM_API_KEY": "wrong-token-4",
                "NAKED_K_NEWS_MODEL": "news-model",
                "ANTHROPIC_MODEL": "anthropic-model",
                "NAKED_K_LLM_MODEL": "llm-model",
                "LLM_MODEL": "fallback-model",
            },
            enabled=True,
            dotenv_path=None,
        )
        redacted = naked_k_news_llm.redact_news_config(config)
        self.assertEqual(config.base_url, "https://anthropic.example/api")
        self.assertEqual(config.auth_token, "fake-secret-token")
        self.assertEqual(config.model, "news-model")
        self.assertEqual(redacted["auth_token"], "***")
        self.assertNotIn("fake-secret-token", json.dumps(redacted))

    def test_validation_requires_fields_without_leaking_credentials(self):
        config = naked_k_news_llm.AnthropicNewsConfig(
            enabled=True, base_url="", auth_token="fake-secret-token", model=""
        )
        with self.assertRaisesRegex(ValueError, "base_url") as discovered:
            naked_k_news_llm.validate_news_config(config, require_model=False)
        self.assertNotIn("fake-secret-token", str(discovered.exception))

        config = dataclasses.replace(config, base_url="https://gateway.example")
        naked_k_news_llm.validate_news_config(config, require_model=False)
        with self.assertRaisesRegex(ValueError, "model"):
            naked_k_news_llm.validate_news_config(config)


class AnthropicEndpointAndHeaderTests(unittest.TestCase):
    def test_endpoint_preserves_gateway_path_prefix(self):
        self.assertEqual(
            naked_k_news_llm.anthropic_messages_url(
                "https://one.iflytek.com/api/llm/console/chat"
            ),
            "https://one.iflytek.com/api/llm/console/chat/v1/messages",
        )
        self.assertEqual(
            naked_k_news_llm.anthropic_models_url(
                "https://one.iflytek.com/api/llm/console/chat/"
            ),
            "https://one.iflytek.com/api/llm/console/chat/v1/models",
        )
        self.assertEqual(
            naked_k_news_llm.anthropic_messages_url("https://gateway.example/prefix/v1"),
            "https://gateway.example/prefix/v1/messages",
        )
        with self.assertRaisesRegex(ValueError, "base_url"):
            naked_k_news_llm.anthropic_messages_url("")

    def test_headers_use_dual_authentication(self):
        config = naked_k_news_llm.AnthropicNewsConfig(auth_token="fake-secret-token")
        headers = naked_k_news_llm.build_anthropic_headers(config)
        self.assertEqual(headers["x-api-key"], "fake-secret-token")
        self.assertEqual(headers["Authorization"], "Bearer fake-secret-token")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(headers["content-type"], "application/json")


class AnthropicModelDiscoveryTests(unittest.TestCase):
    def test_configured_model_bypasses_discovery(self):
        config = naked_k_news_llm.AnthropicNewsConfig(
            base_url="https://gateway.example/prefix", auth_token="fake-token", model="selected"
        )
        resolved = naked_k_news_llm.resolve_news_model(
            config, get=lambda url, **kwargs: self.fail("GET must not be called")
        )
        self.assertIs(resolved, config)

    def test_discovery_selects_only_explicitly_eligible_model(self):
        calls = []

        def fake_get(url, headers, timeout):
            calls.append({"url": url, "headers": headers, "timeout": timeout})
            return FakeResponse({"data": [{"id": "news-chat", "capabilities": ["chat"]}]})

        config = naked_k_news_llm.AnthropicNewsConfig(
            base_url="https://gateway.example/prefix", auth_token="fake-token"
        )
        resolved = naked_k_news_llm.resolve_news_model(config, get=fake_get)
        self.assertEqual(resolved.model, "news-chat")
        self.assertEqual(calls[0]["url"], "https://gateway.example/prefix/v1/models")
        self.assertEqual(calls[0]["headers"], naked_k_news_llm.build_anthropic_headers(config))

    def test_discovery_excludes_explicit_non_chat_models_and_deduplicates_ids(self):
        config = naked_k_news_llm.AnthropicNewsConfig(
            base_url="https://gateway.example", auth_token="fake-token"
        )
        response = FakeResponse(
            {"data": [
                {"id": "embed", "type": "embedding"},
                {"id": "image", "task": "image"},
                {"id": "chat", "model_type": "text"},
                {"id": "chat", "model_type": "text"},
            ]}
        )
        self.assertEqual(
            naked_k_news_llm.resolve_news_model(config, get=lambda url, **kwargs: response).model,
            "chat",
        )

    def test_discovery_requires_explicit_choice_for_ambiguous_or_multiple_models(self):
        config = naked_k_news_llm.AnthropicNewsConfig(
            base_url="https://gateway.example", auth_token="fake-token"
        )
        for payload, expected_ids in (
            ({"data": [{"id": "unlabeled-model"}]}, ("unlabeled-model",)),
            ({"data": [{"id": "z", "type": "chat"}, {"id": "a", "task": "text"}]}, ("a", "z")),
        ):
            with self.assertRaises(naked_k_news_llm.NewsModelSelectionRequired) as raised:
                naked_k_news_llm.resolve_news_model(
                    config, get=lambda url, **kwargs: FakeResponse(payload)
                )
            self.assertEqual(raised.exception.model_ids, expected_ids)
            self.assertNotIn("fake-token", str(raised.exception))

    def test_discovery_rejects_empty_list_and_sanitizes_http_json_failures(self):
        config = naked_k_news_llm.AnthropicNewsConfig(
            base_url="https://gateway.example", auth_token="fake-token"
        )
        with self.assertRaises(naked_k_news_llm.NewsModelDiscoveryError):
            naked_k_news_llm.resolve_news_model(
                config, get=lambda url, **kwargs: FakeResponse({"data": []})
            )
        for response in (FakeResponse(error=RuntimeError("bad fake-token")), FakeResponse(ValueError("bad fake-token"))):
            with self.assertRaises(naked_k_news_llm.NewsModelDiscoveryError) as raised:
                naked_k_news_llm.resolve_news_model(config, get=lambda url, **kwargs: response)
            self.assertNotIn("fake-token", str(raised.exception))


class AnthropicMessagesTransportTests(unittest.TestCase):
    def test_messages_transport_parses_fenced_json_and_hides_authentication(self):
        calls = []
        config = naked_k_news_llm.AnthropicNewsConfig(
            enabled=True,
            base_url="https://one.iflytek.com/api/llm/console/chat",
            auth_token="fake-secret-token",
            model="news-chat",
        )

        def fake_post(url, headers, json, timeout):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse({
                "content": [{"type": "text", "text": "```json\\n{\"status\":\"ok\"}\\n```"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "stop_reason": "end_turn",
            })

        result = naked_k_news_llm.request_anthropic_json(
            system_prompt="Return JSON only.", user_payload={"topic": "news"}, config=config, post=fake_post
        )
        self.assertEqual(calls[0]["url"], "https://one.iflytek.com/api/llm/console/chat/v1/messages")
        self.assertEqual(calls[0]["json"]["system"], "Return JSON only.")
        self.assertEqual(calls[0]["json"]["messages"], [{"role": "user", "content": '{"topic": "news"}'}])
        self.assertEqual(calls[0]["json"]["model"], "news-chat")
        self.assertEqual(calls[0]["json"]["temperature"], 0.1)
        self.assertEqual(calls[0]["json"]["max_tokens"], 1400)
        self.assertEqual(result["parsed"], {"status": "ok"})
        self.assertEqual(result["usage"], {"input_tokens": 10, "output_tokens": 5})
        self.assertEqual(result["stop_reason"], "end_turn")
        self.assertNotIn("fake-secret-token", json.dumps(result))
        self.assertNotIn("Authorization", json.dumps(result))
        self.assertNotIn("x-api-key", json.dumps(result))

    def test_messages_transport_sanitizes_and_clips_errors(self):
        config = naked_k_news_llm.AnthropicNewsConfig(
            base_url="https://gateway.example", auth_token="fake-secret-token", model="news-chat"
        )
        with self.assertRaises(naked_k_news_llm.NewsResponseError) as raised:
            naked_k_news_llm.request_anthropic_json(
                system_prompt="sys", user_payload={}, config=config,
                post=lambda url, **kwargs: (_ for _ in ()).throw(RuntimeError("fake-secret-token" + "x" * 400)),
            )
        self.assertNotIn("fake-secret-token", str(raised.exception))
        self.assertLessEqual(len(str(raised.exception)), 300)

    def test_messages_transport_rejects_empty_or_non_object_text(self):
        config = naked_k_news_llm.AnthropicNewsConfig(
            base_url="https://gateway.example", auth_token="fake-token", model="news-chat"
        )
        for content in ([], [{"type": "text", "text": "[]"}]):
            with self.assertRaises(naked_k_news_llm.NewsResponseError):
                naked_k_news_llm.request_anthropic_json(
                    system_prompt="sys", user_payload={}, config=config,
                    post=lambda url, **kwargs: FakeResponse({"content": content}),
                )


if __name__ == "__main__":
    unittest.main()
