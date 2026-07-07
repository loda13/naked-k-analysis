import json
import tempfile
import unittest
from pathlib import Path

import naked_k_llm


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class NakedKLLMTests(unittest.TestCase):
    def test_loads_openai_compatible_config_from_env_without_leaking_key(self):
        env = {
            "LLM_BASE_URL": "https://ark.cn-beijing.volces.com/api/coding/v3",
            "LLM_API_KEY": "test-secret-key",
            "LLM_MODEL": "glm-5.2",
        }

        config = naked_k_llm.load_llm_config(env=env, enabled=True)
        redacted = naked_k_llm.redact_llm_config(config)

        self.assertTrue(config.enabled)
        self.assertEqual(config.base_url, "https://ark.cn-beijing.volces.com/api/coding/v3")
        self.assertEqual(config.model, "glm-5.2")
        self.assertEqual(redacted["api_key"], "***")
        self.assertNotIn("test-secret-key", json.dumps(redacted))

    def test_loads_config_from_local_dotenv_without_overriding_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        'LLM_BASE_URL="https://ark.cn-beijing.volces.com/api/coding/v3"',
                        "LLM_API_KEY=dotenv-secret-key",
                        "LLM_MODEL=glm-5.2",
                    ]
                ),
                encoding="utf-8",
            )

            config = naked_k_llm.load_llm_config(
                env={"LLM_MODEL": "env-model"},
                enabled=True,
                dotenv_path=dotenv_path,
            )

        self.assertEqual(config.base_url, "https://ark.cn-beijing.volces.com/api/coding/v3")
        self.assertEqual(config.api_key, "dotenv-secret-key")
        self.assertEqual(config.model, "env-model")

    def test_builds_openai_compatible_request_with_signal_boundary_prompt(self):
        payload = {
            "engine_plan": {
                "action": "小仓试错",
                "entry_trigger": 105.0,
                "stop_loss": 99.0,
                "target_price": 117.0,
            },
            "signal_boundary": {"forbidden": ["change_action", "invent_entry"]},
        }

        messages = naked_k_llm.build_llm_messages(payload)

        joined = "\n".join(message["content"] for message in messages)
        self.assertIn("不得改写", joined)
        self.assertIn("action", joined)
        self.assertIn("entry_trigger", joined)
        self.assertIn("小仓试错", joined)

    def test_parses_markdown_fenced_json_response(self):
        result = naked_k_llm.generate_llm_commentary(
            {"engine_plan": {"action": "观望"}},
            config=naked_k_llm.LLMConfig(
                enabled=True,
                base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
                api_key="test-secret-key",
                model="glm-5.2",
            ),
            post=lambda url, headers, json, timeout: FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '```json\n{"journal_note":"等待回踩确认"}\n```'
                            }
                        }
                    ]
                }
            ),
        )

        self.assertEqual(result["parsed"], {"journal_note": "等待回踩确认"})

    def test_calls_openai_compatible_chat_completions(self):
        calls = []

        def fake_post(url, headers, json, timeout):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": '{"market_reading":"结构转换","risk_challenge":"等待确认"}'
                            }
                        }
                    ],
                    "usage": {"total_tokens": 123},
                }
            )

        config = naked_k_llm.LLMConfig(
            enabled=True,
            base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
            api_key="test-secret-key",
            model="glm-5.2",
        )

        result = naked_k_llm.generate_llm_commentary(
            {"engine_plan": {"action": "观望"}, "signal_boundary": {"forbidden": ["change_action"]}},
            config=config,
            post=fake_post,
        )

        self.assertEqual(calls[0]["url"], "https://ark.cn-beijing.volces.com/api/coding/v3/chat/completions")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer test-secret-key")
        self.assertEqual(calls[0]["json"]["model"], "glm-5.2")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["parsed"]["risk_challenge"], "等待确认")
        self.assertNotIn("test-secret-key", json.dumps(result, ensure_ascii=False))

    def test_safe_generation_reports_error_without_secret(self):
        def fake_post(url, headers, json, timeout):
            raise RuntimeError("network failed with test-secret-key")

        config = naked_k_llm.LLMConfig(
            enabled=True,
            base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
            api_key="test-secret-key",
            model="glm-5.2",
        )

        result = naked_k_llm.safe_generate_llm_commentary(
            {"engine_plan": {"action": "观望"}},
            config=config,
            post=fake_post,
        )

        self.assertEqual(result["status"], "error")
        self.assertNotIn("test-secret-key", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
