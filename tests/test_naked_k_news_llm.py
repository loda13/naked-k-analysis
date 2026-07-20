import dataclasses
import copy
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

    def test_environment_aliases_outrank_dotenv_higher_priority_aliases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv_path = Path(tmpdir) / ".env"
            dotenv_path.write_text(
                "ANTHROPIC_BASE_URL=https://dotenv.example/high-priority\n"
                "ANTHROPIC_AUTH_TOKEN=dotenv-token\n"
                "NAKED_K_NEWS_MODEL=dotenv-model\n",
                encoding="utf-8",
            )
            config = naked_k_news_llm.load_news_config(
                env={
                    "NAKED_K_NEWS_BASE_URL": "https://env.example/news",
                    "NAKED_K_NEWS_API_KEY": "env-token",
                    "ANTHROPIC_MODEL": "env-model",
                },
                dotenv_path=dotenv_path,
            )
        self.assertEqual(config.base_url, "https://env.example/news")
        self.assertEqual(config.auth_token, "env-token")
        self.assertEqual(config.model, "env-model")

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

    def test_discovery_handles_only_exact_chat_markers_and_capability_dict_keys(self):
        config = naked_k_news_llm.AnthropicNewsConfig(
            base_url="https://gateway.example", auth_token="fake-token"
        )
        for row in (
            {"id": "llm", "type": "llm"},
            {"id": "messages", "model_type": "messages"},
            {"id": "text-generation", "task": "text-generation"},
            {"id": "capability-dict", "capabilities": {"chat": True}},
            {"id": "endpoint", "supported_endpoints": ["messages"]},
        ):
            with self.subTest(row=row):
                resolved = naked_k_news_llm.resolve_news_model(
                    config, get=lambda url, **kwargs: FakeResponse({"data": [row]})
                )
                self.assertEqual(resolved.model, row["id"])

    def test_discovery_keeps_contextual_metadata_ambiguous(self):
        config = naked_k_news_llm.AnthropicNewsConfig(
            base_url="https://gateway.example", auth_token="fake-token"
        )
        with self.assertRaises(naked_k_news_llm.NewsModelSelectionRequired) as raised:
            naked_k_news_llm.resolve_news_model(
                config,
                get=lambda url, **kwargs: FakeResponse(
                    {"data": [{"id": "contextual", "type": "contextual"}]}
                ),
            )
        self.assertEqual(raised.exception.model_ids, ("contextual",))

    def test_discovery_excludes_exact_non_chat_markers_and_vetoes_conflicting_duplicates(self):
        config = naked_k_news_llm.AnthropicNewsConfig(
            base_url="https://gateway.example", auth_token="fake-token"
        )
        for marker in ("rerank", "audio", "moderation"):
            with self.subTest(marker=marker):
                with self.assertRaises(naked_k_news_llm.NewsModelDiscoveryError):
                    naked_k_news_llm.resolve_news_model(
                        config,
                        get=lambda url, **kwargs: FakeResponse(
                            {"data": [{"id": marker, "type": marker}]}
                        ),
                    )
        resolved = naked_k_news_llm.resolve_news_model(
            config,
            get=lambda url, **kwargs: FakeResponse({"data": [
                {"id": "conflicting", "type": "chat"},
                {"id": "conflicting", "task": "embedding"},
                {"id": "selected", "capabilities": {"text": True}},
            ]}),
        )
        self.assertEqual(resolved.model, "selected")

    def test_discovery_normalizes_null_and_non_list_catalogs_to_discovery_errors(self):
        config = naked_k_news_llm.AnthropicNewsConfig(
            base_url="https://gateway.example", auth_token="fake-token"
        )
        for catalog in (None, "not-a-list", {"unexpected": []}):
            with self.subTest(catalog=catalog):
                with self.assertRaises(naked_k_news_llm.NewsModelDiscoveryError):
                    naked_k_news_llm.resolve_news_model(
                        config,
                        get=lambda url, **kwargs: FakeResponse({"data": catalog}),
                    )


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


NEWS_CONFIG = naked_k_news_llm.AnthropicNewsConfig(
    enabled=True,
    base_url="https://gateway.example",
    auth_token="fake-secret-token",
    model="news-chat",
)
NEWS_ITEMS = [{
    "id": "news-01",
    "title": "Company wins a material contract",
    "publisher": "Wire A",
    "published_at": "2026-07-20T08:00:00+08:00",
    "url": "https://example.com/news-01",
    "summary": "The contract expands the order backlog.",
    "source_provider": "google_news_rss",
    "freshness": "fresh",
}]


def valid_round1(**overrides):
    payload = {
        "status": "ok",
        "direction": "strong_bullish",
        "score": 2,
        "confidence": 86,
        "materiality": "high",
        "horizon": "short_term",
        "summary": "消息面偏积极",
        "positive_factors": ["新增订单"],
        "negative_factors": ["交付仍有不确定性"],
        "evidence_ids": ["news-01"],
        "uncertainties": ["合同执行进度未知"],
        "data_quality": "sufficient",
    }
    payload.update(overrides)
    return payload


def valid_round2(*, technical_action="观望", model_action="买入", **overrides):
    payload = {
        "status": "ok",
        "technical_view": {"action": technical_action, "summary": "技术面保持原判断"},
        "news_view": {"direction": "strong_bullish", "summary": "消息面偏积极"},
        "conflict_analysis": "消息催化可能改变原有等待结论",
        "model_action": model_action,
        "confidence": 78,
        "decision_reasons": ["消息具有较高重要性"],
        "risk_flags": ["消息仍待后续验证"],
        "evidence_ids": ["news-01"],
        "execution_note": "等待确定性裸K执行层生成价格计划",
    }
    payload.update(overrides)
    return payload


def anthropic_payload(model_payload):
    return FakeResponse({
        "content": [{"type": "text", "text": json.dumps(model_payload, ensure_ascii=False)}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "stop_reason": "end_turn",
    })


class RoundOneNewsAssessmentTests(unittest.TestCase):
    def test_round_one_request_is_technically_blind_and_normalizes_news(self):
        calls = []
        item = dict(NEWS_ITEMS[0], ignored="must not be sent")

        def fake_post(url, headers, json, timeout):
            calls.append(copy.deepcopy(json))
            return anthropic_payload(valid_round1())

        result = naked_k_news_llm.assess_news_round1(
            name="测试公司",
            ticker="TEST",
            as_of="2026-07-20T12:00:00+08:00",
            items=[item],
            config=NEWS_CONFIG,
            post=fake_post,
        )

        user_text = calls[0]["messages"][0]["content"]
        user_payload = json.loads(user_text)
        self.assertEqual(user_payload["company"], {"name": "测试公司", "ticker": "TEST"})
        self.assertEqual(user_payload["as_of"], "2026-07-20T12:00:00+08:00")
        self.assertEqual(user_payload["news"], NEWS_ITEMS)
        for forbidden in [
            "entry_trigger", "stop_loss", "target_price", "position_size",
            "technical_conclusion", "买入",
        ]:
            self.assertNotIn(forbidden, user_text)
        self.assertIn("untrusted", calls[0]["system"].lower())
        self.assertEqual(result, valid_round1())

    def test_round_one_returns_only_whitelisted_model_fields(self):
        model_payload = valid_round1(transport_usage={"tokens": 99}, surprise="discard me")
        result = naked_k_news_llm.assess_news_round1(
            name="测试公司", ticker="TEST", as_of="2026-07-20", items=NEWS_ITEMS,
            config=NEWS_CONFIG,
            post=lambda *args, **kwargs: anthropic_payload(model_payload),
        )
        self.assertEqual(result, valid_round1())
        self.assertIsNot(result, model_payload)

    def test_round_one_rejects_invalid_enums_ranges_and_evidence(self):
        mutations = {
            "score low": {"score": -3},
            "score high": {"score": 3},
            "score bool": {"score": True},
            "confidence low": {"confidence": -1},
            "confidence high": {"confidence": 101},
            "confidence bool": {"confidence": False},
            "direction": {"direction": "up"},
            "materiality": {"materiality": "urgent"},
            "horizon": {"horizon": "forever"},
            "data quality": {"data_quality": "unknown"},
            "unknown evidence": {"evidence_ids": ["news-99"]},
            "sufficient empty evidence": {"evidence_ids": []},
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label), self.assertRaises(naked_k_news_llm.NewsValidationError):
                naked_k_news_llm.assess_news_round1(
                    name="测试公司", ticker="TEST", as_of="2026-07-20", items=NEWS_ITEMS,
                    config=NEWS_CONFIG,
                    post=lambda *args, mutation=mutation, **kwargs: anthropic_payload(
                        valid_round1(**mutation)
                    ),
                )

    def test_round_one_rejects_every_missing_field_and_wrong_field_type(self):
        scalar_types = {
            "status": [], "direction": [], "score": "2", "confidence": 86.0,
            "materiality": [], "horizon": [], "summary": [], "data_quality": [],
        }
        list_fields = ("positive_factors", "negative_factors", "evidence_ids", "uncertainties")
        for field in valid_round1():
            invalid = valid_round1()
            invalid.pop(field)
            with self.subTest(case="missing", field=field), self.assertRaises(
                naked_k_news_llm.NewsValidationError
            ):
                naked_k_news_llm.assess_news_round1(
                    name="测试公司", ticker="TEST", as_of="2026-07-20", items=NEWS_ITEMS,
                    config=NEWS_CONFIG,
                    post=lambda *args, invalid=invalid, **kwargs: anthropic_payload(invalid),
                )
        for field, wrong_value in {**scalar_types, **{name: "not-list" for name in list_fields}}.items():
            with self.subTest(case="wrong type", field=field), self.assertRaises(
                naked_k_news_llm.NewsValidationError
            ):
                invalid = valid_round1(**{field: wrong_value})
                naked_k_news_llm.assess_news_round1(
                    name="测试公司", ticker="TEST", as_of="2026-07-20", items=NEWS_ITEMS,
                    config=NEWS_CONFIG,
                    post=lambda *args, invalid=invalid, **kwargs: anthropic_payload(invalid),
                )
        for field in list_fields:
            with self.subTest(case="non-string list item", field=field), self.assertRaises(
                naked_k_news_llm.NewsValidationError
            ):
                invalid = valid_round1(**{field: [1]})
                naked_k_news_llm.assess_news_round1(
                    name="测试公司", ticker="TEST", as_of="2026-07-20", items=NEWS_ITEMS,
                    config=NEWS_CONFIG,
                    post=lambda *args, invalid=invalid, **kwargs: anthropic_payload(invalid),
                )


class RoundTwoDeliberationTests(unittest.TestCase):
    def _call(self, output, *, technical_action="观望", items=None, round1=None, risk_context=None, calls=None):
        technical_snapshot = {
            "action": technical_action,
            "summary": "裸K技术结论",
            "risk_plan": {"max_loss": 1000},
        }
        captured = [] if calls is None else calls

        def fake_post(url, headers, json, timeout):
            captured.append(copy.deepcopy(json))
            return anthropic_payload(output)

        result = naked_k_news_llm.deliberate_round2(
            technical_snapshot=technical_snapshot,
            items=NEWS_ITEMS if items is None else items,
            round1=valid_round1() if round1 is None else round1,
            risk_context=risk_context or {
                "technical_risk_plan": {"max_loss": 1000},
                "risk_limits": {"risk_per_trade_pct": 1.0},
                "portfolio_limits": {"max_open_positions": 5},
            },
            config=NEWS_CONFIG,
            post=fake_post,
        )
        return result, captured

    def test_round_two_receives_all_deep_copied_sections_and_allows_free_action_changes(self):
        risk_context = {
            "technical_risk_plan": {"max_loss": 1000},
            "risk_limits": {"risk_per_trade_pct": 1.0},
            "portfolio_limits": {"max_open_positions": 5},
        }
        for technical_action, model_action in (("观望", "买入"), ("买入", "回避")):
            with self.subTest(technical_action=technical_action, model_action=model_action):
                result, calls = self._call(
                    valid_round2(technical_action=technical_action, model_action=model_action),
                    technical_action=technical_action,
                    risk_context=risk_context,
                )
                payload = json.loads(calls[0]["messages"][0]["content"])
                self.assertEqual(payload["technical_snapshot"]["action"], technical_action)
                self.assertEqual(payload["raw_news"], NEWS_ITEMS)
                self.assertEqual(payload["round1_news_assessment"], valid_round1())
                self.assertEqual(payload["risk_context"], risk_context)
                self.assertEqual(
                    set(payload["risk_context"]),
                    {"technical_risk_plan", "risk_limits", "portfolio_limits"},
                )
                self.assertNotIn("weight", calls[0]["system"].lower())
                self.assertNotIn("加总", calls[0]["system"])
                self.assertEqual(result["model_action"], model_action)

    def test_round_two_returns_whitelisted_fields_and_allows_price_words_in_prose(self):
        output = valid_round2(
            conflict_analysis="价格风险需由确定性执行层处理",
            extra={"not_a_price": "discard"},
        )
        result, _ = self._call(output)
        self.assertEqual(result, valid_round2(conflict_analysis="价格风险需由确定性执行层处理"))
        self.assertNotIn("extra", result)
        self.assertIsNot(result, output)

    def test_round_two_rejects_required_field_and_type_mutations(self):
        required = valid_round2()
        for field in required:
            invalid = copy.deepcopy(required)
            invalid.pop(field)
            with self.subTest(case="missing top level", field=field), self.assertRaises(
                naked_k_news_llm.NewsValidationError
            ):
                self._call(invalid)

        wrong_types = {
            "status": [], "technical_view": [], "news_view": [],
            "conflict_analysis": [], "model_action": [], "confidence": 78.0,
            "decision_reasons": "not-list", "risk_flags": "not-list",
            "evidence_ids": "not-list", "execution_note": [],
        }
        for field, wrong_value in wrong_types.items():
            with self.subTest(case="wrong top-level type", field=field), self.assertRaises(
                naked_k_news_llm.NewsValidationError
            ):
                self._call(valid_round2(**{field: wrong_value}))
        for field in ("decision_reasons", "risk_flags", "evidence_ids"):
            with self.subTest(case="non-string list item", field=field), self.assertRaises(
                naked_k_news_llm.NewsValidationError
            ):
                self._call(valid_round2(**{field: [1]}))
        for view, fields in (("technical_view", ("action", "summary")), ("news_view", ("direction", "summary"))):
            for field in fields:
                invalid = valid_round2()
                invalid[view] = dict(invalid[view])
                invalid[view].pop(field)
                with self.subTest(case="missing nested", view=view, field=field), self.assertRaises(
                    naked_k_news_llm.NewsValidationError
                ):
                    self._call(invalid)
                invalid = valid_round2()
                invalid[view] = dict(invalid[view], **{field: []})
                with self.subTest(case="wrong nested type", view=view, field=field), self.assertRaises(
                    naked_k_news_llm.NewsValidationError
                ):
                    self._call(invalid)

    def test_round_two_rejects_tampering_invalid_actions_evidence_and_confidence(self):
        mutations = {
            "status not ok": {"status": "error"},
            "technical action tamper": {"technical_view": {"action": "买入", "summary": "changed"}},
            "news direction tamper": {"news_view": {"direction": "bearish", "summary": "changed"}},
            "invalid action": {"model_action": "追涨"},
            "invalid evidence": {"evidence_ids": ["news-99"]},
            "confidence bool": {"confidence": True},
            "confidence low": {"confidence": -1},
            "confidence high": {"confidence": 101},
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label), self.assertRaises(naked_k_news_llm.NewsValidationError):
                self._call(valid_round2(**mutation))

    def test_round_two_rejects_forbidden_price_keys_recursively(self):
        for forbidden in naked_k_news_llm.FORBIDDEN_MODEL_PRICE_KEYS:
            with self.subTest(forbidden=forbidden), self.assertRaises(
                naked_k_news_llm.NewsValidationError
            ):
                output = valid_round2()
                output["unrecognized"] = {"nested": {forbidden: 100}}
                self._call(output)


class TwoPassOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.collection = {
            "status": "ok",
            "as_of": "2026-07-20T12:00:00+08:00",
            "items": copy.deepcopy(NEWS_ITEMS),
        }
        self.technical = {"action": "观望", "risk_plan": {"max_loss": 1000}}
        self.risk_context = {
            "technical_risk_plan": {"max_loss": 1000},
            "risk_limits": {"risk_per_trade_pct": 1.0},
            "portfolio_limits": {"max_open_positions": 5},
        }

    def _run(self, post, collection=None):
        return naked_k_news_llm.run_two_pass_deliberation(
            name="测试公司", ticker="TEST",
            collection=self.collection if collection is None else collection,
            technical_snapshot=self.technical,
            risk_context=self.risk_context,
            config=NEWS_CONFIG,
            post=post,
        )

    def test_no_items_skips_transport_and_falls_back(self):
        result = self._run(
            lambda *args, **kwargs: self.fail("POST must not be called"),
            collection={"status": "insufficient", "as_of": "2026-07-20", "items": []},
        )
        self.assertEqual(result["status"], "technical_fallback")
        self.assertEqual(result["news_analysis"]["status"], "insufficient")
        self.assertEqual(result["news_analysis"]["round1"], {})
        self.assertEqual(result["deliberation"], {})
        self.assertTrue(result["fallback_reason"])

    def test_insufficient_round_one_is_retained_and_skips_round_two(self):
        calls = []
        insufficient = valid_round1(data_quality="insufficient", evidence_ids=[])

        def fake_post(*args, **kwargs):
            calls.append(kwargs["json"])
            return anthropic_payload(insufficient)

        result = self._run(fake_post)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "technical_fallback")
        self.assertEqual(result["news_analysis"]["status"], "insufficient")
        self.assertEqual(result["news_analysis"]["round1"], insufficient)
        self.assertIn("insufficient", result["fallback_reason"].lower())
        self.assertEqual(result["deliberation"], {})

    def test_round_one_failure_is_safe_and_falls_back_after_one_post(self):
        calls = []

        def broken_post(url, headers, json, timeout):
            calls.append(json)
            raise RuntimeError("fake-secret-token " + json["system"])

        result = self._run(broken_post)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "technical_fallback")
        self.assertEqual(result["news_analysis"]["status"], "error")
        self.assertEqual(result["deliberation"], {})
        self.assertIn("NewsResponseError", serialized)
        self.assertNotIn("fake-secret-token", serialized)
        self.assertNotIn(calls[0]["system"], serialized)

    def test_round_two_failure_retains_round_one_and_falls_back_after_two_posts(self):
        calls = []

        def fake_post(url, headers, json, timeout):
            calls.append(json)
            if len(calls) == 1:
                return anthropic_payload(valid_round1())
            return anthropic_payload(valid_round2(model_action="not-allowed"))

        result = self._run(fake_post)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["status"], "technical_fallback")
        self.assertEqual(result["news_analysis"]["status"], "ok")
        self.assertEqual(result["news_analysis"]["round1"], valid_round1())
        self.assertEqual(result["deliberation"], {})
        self.assertIn("NewsValidationError", result["fallback_reason"])

    def test_both_valid_returns_validated_deliberation(self):
        responses = [valid_round1(), valid_round2()]

        def fake_post(*args, **kwargs):
            return anthropic_payload(responses.pop(0))

        result = self._run(fake_post)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["news_analysis"]["status"], "ok")
        self.assertEqual(result["news_analysis"]["collection"], self.collection)
        self.assertEqual(result["news_analysis"]["provider"], NEWS_CONFIG.provider)
        self.assertEqual(result["news_analysis"]["model"], NEWS_CONFIG.model)
        self.assertEqual(result["news_analysis"]["round1"], valid_round1())
        self.assertEqual(result["deliberation"], valid_round2())
        self.assertEqual(result["fallback_reason"], "")


if __name__ == "__main__":
    unittest.main()
