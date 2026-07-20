"""Anthropic-compatible configuration and transport for news analysis."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import requests


GetCallable = Callable[..., Any]
PostCallable = Callable[..., Any]

_CHAT_MARKERS = {"chat", "text", "llm", "messages", "text_generation"}
_NON_CHAT_MARKERS = {"embedding", "rerank", "image", "audio", "moderation"}


@dataclass(frozen=True)
class AnthropicNewsConfig:
    enabled: bool = False
    provider: str = "anthropic_compatible"
    base_url: str = ""
    auth_token: str = ""
    model: str = ""
    temperature: float = 0.1
    max_tokens: int = 1400
    timeout_seconds: float = 60.0


class NewsModelDiscoveryError(RuntimeError):
    """The gateway could not provide a usable model catalog."""


class NewsModelSelectionRequired(NewsModelDiscoveryError):
    """The caller must select a model from the discovered catalog."""

    def __init__(self, model_ids: tuple[str, ...]):
        self.model_ids = tuple(sorted(set(model_ids)))
        super().__init__("Model selection required: " + ", ".join(self.model_ids))


class NewsResponseError(RuntimeError):
    """The Anthropic Messages response was unavailable or invalid."""


def first_news_env(env: dict[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = env.get(name)
        if value:
            return value
    return default


def load_news_dotenv_values(dotenv_path: str | Path | None) -> dict[str, str]:
    """Load a small, dependency-free subset of dotenv syntax."""
    if dotenv_path is None:
        return {}
    path = Path(dotenv_path)
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if not key:
            continue
        if len(value) >= 2 and value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_news_config(
    env: dict[str, str] | None = None,
    *,
    enabled: bool = False,
    base_url: str | None = None,
    model: str | None = None,
    dotenv_path: str | Path | None = ".env",
) -> AnthropicNewsConfig:
    dotenv_values = load_news_dotenv_values(dotenv_path)
    environment_values = os.environ if env is None else env
    return AnthropicNewsConfig(
        enabled=enabled,
        base_url=(base_url if base_url is not None else _news_setting(
            environment_values,
            dotenv_values,
            "ANTHROPIC_BASE_URL",
            "NAKED_K_NEWS_BASE_URL",
            "NAKED_K_LLM_BASE_URL",
            "LLM_BASE_URL",
        )),
        auth_token=_news_setting(
            environment_values,
            dotenv_values,
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_API_KEY",
            "NAKED_K_NEWS_API_KEY",
            "NAKED_K_LLM_API_KEY",
            "LLM_API_KEY",
        ),
        model=(model if model is not None else _news_setting(
            environment_values,
            dotenv_values,
            "NAKED_K_NEWS_MODEL",
            "ANTHROPIC_MODEL",
            "NAKED_K_LLM_MODEL",
            "LLM_MODEL",
        )),
        temperature=float(_news_setting(
            environment_values, dotenv_values, "NAKED_K_NEWS_TEMPERATURE", default="0.1"
        )),
        max_tokens=int(_news_setting(
            environment_values, dotenv_values, "NAKED_K_NEWS_MAX_TOKENS", default="1400"
        )),
        timeout_seconds=float(_news_setting(
            environment_values, dotenv_values, "NAKED_K_NEWS_TIMEOUT", default="60"
        )),
    )


def _news_setting(
    environment_values: dict[str, str],
    dotenv_values: dict[str, str],
    *names: str,
    default: str = "",
) -> str:
    return first_news_env(
        environment_values, *names,
        default=first_news_env(dotenv_values, *names, default=default),
    )


def validate_news_config(config: AnthropicNewsConfig, *, require_model: bool = True) -> None:
    missing = [name for name, value in (
        ("base_url", config.base_url),
        ("auth_token", config.auth_token),
        ("model", config.model if require_model else "resolved"),
    ) if not value]
    if missing:
        raise ValueError("Missing news config fields: " + ", ".join(missing))


def redact_news_config(config: AnthropicNewsConfig) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "provider": config.provider,
        "base_url": config.base_url,
        "auth_token": "***" if config.auth_token else "",
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "timeout_seconds": config.timeout_seconds,
    }


def _anthropic_endpoint(base_url: str, resource: str) -> str:
    if not base_url.strip():
        raise ValueError("Missing news config fields: base_url")
    normalized = base_url.rstrip("/")
    if normalized.endswith(f"/v1/{resource}"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/{resource}"
    return f"{normalized}/v1/{resource}"


def anthropic_messages_url(base_url: str) -> str:
    return _anthropic_endpoint(base_url, "messages")


def anthropic_models_url(base_url: str) -> str:
    return _anthropic_endpoint(base_url, "models")


def build_anthropic_headers(config: AnthropicNewsConfig) -> dict[str, str]:
    return {
        "x-api-key": config.auth_token,
        "Authorization": f"Bearer {config.auth_token}",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def _sanitize_error(error: Exception | str, config: AnthropicNewsConfig, *, limit: int = 300) -> str:
    text = str(error)
    if config.auth_token:
        text = text.replace(config.auth_token, "***")
    return text[:limit]


def _response_json(response: Any, config: AnthropicNewsConfig, error_type: type[RuntimeError]) -> Any:
    try:
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise error_type(_sanitize_error(exc, config)) from None


def _model_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("data", payload.get("models", []))
    else:
        rows = []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"]]


def _normalize_marker(value: str) -> str:
    return "_".join(value.strip().lower().replace("-", "_").split())


def _metadata_markers(value: Any, *, endpoint: bool = False) -> set[str]:
    if isinstance(value, str):
        normalized = _normalize_marker(value)
        if endpoint:
            return {_normalize_marker(part) for part in normalized.split("/") if part}
        return {normalized} if normalized else set()
    if isinstance(value, list):
        return set().union(*(_metadata_markers(item, endpoint=endpoint) for item in value)) if value else set()
    if isinstance(value, dict):
        return {
            _normalize_marker(str(key))
            for key, item in value.items()
            if item and _normalize_marker(str(key))
        }
    return set()


def _model_kind(row: dict[str, Any]) -> str:
    words: set[str] = set()
    for key in ("type", "model_type", "task", "capabilities"):
        words.update(_metadata_markers(row.get(key)))
    words.update(_metadata_markers(row.get("supported_endpoints"), endpoint=True))
    if words & _NON_CHAT_MARKERS:
        return "excluded"
    if words & _CHAT_MARKERS:
        return "eligible"
    return "ambiguous"


def resolve_news_model(config: AnthropicNewsConfig, get: GetCallable | None = None) -> AnthropicNewsConfig:
    if config.model:
        return config
    validate_news_config(config, require_model=False)
    request_get = get or requests.get
    try:
        response = request_get(
            anthropic_models_url(config.base_url),
            headers=build_anthropic_headers(config),
            timeout=config.timeout_seconds,
        )
    except Exception as exc:
        raise NewsModelDiscoveryError(_sanitize_error(exc, config)) from None
    payload = _response_json(response, config, NewsModelDiscoveryError)
    rows = _model_rows(payload)
    ids = tuple(sorted({row["id"] for row in rows}))
    if not ids:
        raise NewsModelDiscoveryError("No models returned by gateway")
    kinds_by_id: dict[str, set[str]] = {}
    for row in rows:
        kinds_by_id.setdefault(row["id"], set()).add(_model_kind(row))
    excluded = {model_id for model_id, kinds in kinds_by_id.items() if "excluded" in kinds}
    eligible = {
        model_id for model_id, kinds in kinds_by_id.items()
        if model_id not in excluded and "eligible" in kinds
    }
    ambiguous = {
        model_id for model_id, kinds in kinds_by_id.items()
        if model_id not in excluded and "eligible" not in kinds and "ambiguous" in kinds
    }
    if len(eligible) == 1 and not ambiguous:
        return replace(config, model=next(iter(eligible)))
    if eligible or ambiguous:
        raise NewsModelSelectionRequired(tuple(eligible | ambiguous))
    raise NewsModelDiscoveryError("No chat-capable models returned by gateway")


def parse_news_json_content(content: str) -> dict[str, Any] | None:
    text = content.strip()
    for candidate in (text, _strip_news_json_fence(text), _embedded_news_json(text)):
        try:
            parsed = json.loads(candidate)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _strip_news_json_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _embedded_news_json(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start >= 0 and end > start else ""


def request_anthropic_json(
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
    config: AnthropicNewsConfig,
    post: PostCallable | None = None,
) -> dict[str, Any]:
    """Return parsed, usage, stop_reason, provider, model, and endpoint metadata."""
    validate_news_config(config)
    endpoint = anthropic_messages_url(config.base_url)
    body = {
        "model": config.model,
        "system": system_prompt,
        "messages": [{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)}],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
    request_post = post or requests.post
    try:
        response = request_post(
            endpoint,
            headers=build_anthropic_headers(config),
            json=body,
            timeout=config.timeout_seconds,
        )
    except Exception as exc:
        raise NewsResponseError(_sanitize_error(exc, config)) from None
    payload = _response_json(response, config, NewsResponseError)
    blocks = payload.get("content") if isinstance(payload, dict) else None
    content = "\n".join(
        str(block.get("text", "")) for block in (blocks or [])
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    parsed = parse_news_json_content(content)
    if not content or parsed is None:
        raise NewsResponseError("Anthropic response did not contain a JSON object")
    return {
        "status": "ok",
        "provider": config.provider,
        "model": config.model,
        "content": content,
        "parsed": parsed,
        "usage": payload.get("usage"),
        "stop_reason": payload.get("stop_reason"),
        "endpoint": endpoint,
    }
