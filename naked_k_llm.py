from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests


PostCallable = Callable[..., Any]


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = False
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    max_tokens: int = 1000
    timeout_seconds: float = 60.0
    extra_headers: dict[str, str] = field(default_factory=dict)


def _first_env(env: dict[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = env.get(name)
        if value:
            return value
    return default


def _load_dotenv_values(dotenv_path: str | Path | None) -> dict[str, str]:
    if dotenv_path is None:
        return {}
    path = Path(dotenv_path)
    if not path.exists() or not path.is_file():
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
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_llm_config(
    env: dict[str, str] | None = None,
    enabled: bool = False,
    base_url: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    dotenv_path: str | Path | None = ".env",
) -> LLMConfig:
    dotenv_values = _load_dotenv_values(dotenv_path)
    if env is None:
        source = {**dotenv_values, **os.environ}
    else:
        source = {**dotenv_values, **env}
    headers_text = _first_env(source, "NAKED_K_LLM_EXTRA_HEADERS", "LLM_EXTRA_HEADERS", default="{}")
    try:
        extra_headers = json.loads(headers_text)
    except json.JSONDecodeError:
        extra_headers = {}
    if not isinstance(extra_headers, dict):
        extra_headers = {}

    return LLMConfig(
        enabled=enabled,
        provider=provider or _first_env(source, "NAKED_K_LLM_PROVIDER", "LLM_PROVIDER", default="openai_compatible"),
        base_url=base_url or _first_env(source, "NAKED_K_LLM_BASE_URL", "LLM_BASE_URL"),
        api_key=_first_env(source, "NAKED_K_LLM_API_KEY", "LLM_API_KEY"),
        model=model or _first_env(source, "NAKED_K_LLM_MODEL", "LLM_MODEL"),
        temperature=float(_first_env(source, "NAKED_K_LLM_TEMPERATURE", "LLM_TEMPERATURE", default="0.2")),
        max_tokens=int(_first_env(source, "NAKED_K_LLM_MAX_TOKENS", "LLM_MAX_TOKENS", default="1000")),
        timeout_seconds=float(_first_env(source, "NAKED_K_LLM_TIMEOUT", "LLM_TIMEOUT", default="60")),
        extra_headers={str(key): str(value) for key, value in extra_headers.items()},
    )


def validate_llm_config(config: LLMConfig) -> None:
    if config.provider != "openai_compatible":
        raise ValueError("Only openai_compatible LLM provider is currently supported")
    missing = []
    if not config.base_url:
        missing.append("base_url")
    if not config.api_key:
        missing.append("api_key")
    if not config.model:
        missing.append("model")
    if missing:
        raise ValueError(f"Missing LLM config fields: {', '.join(missing)}")


def redact_llm_config(config: LLMConfig) -> dict[str, Any]:
    return {
        "enabled": config.enabled,
        "provider": config.provider,
        "base_url": config.base_url,
        "api_key": "***" if config.api_key else "",
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "timeout_seconds": config.timeout_seconds,
        "extra_headers": {key: "***" for key in config.extra_headers},
    }


def openai_chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def build_llm_messages(ai_payload: dict[str, Any]) -> list[dict[str, str]]:
    system_prompt = (
        "你是专业交易员复盘助手，只能基于确定性裸K引擎输出做解释、复盘、质疑和日志草稿。"
        "不得改写 action、entry_trigger、stop_loss、target_price、risk_plan；"
        "不得发明价格、指标或交易信号；不得使用 MACD/RSI 金叉等散户指标话术。"
        "请用中文输出紧凑 JSON，字段包括 market_reading、plan_review、risk_challenge、journal_note、boundary_check。"
    )
    user_prompt = json.dumps(ai_payload, ensure_ascii=False, sort_keys=True)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _strip_markdown_json_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if not lines:
        return text
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_content(content: str) -> dict[str, Any] | None:
    """Parse JSON from LLM response with multiple fallback strategies.

    Handles:
    1. Direct JSON
    2. JSON wrapped in markdown code fences
    3. JSON embedded in text (extract between first { and last })
    4. Malformed JSON with common issues (trailing commas, missing quotes)
    """
    text = content.strip()

    # Try 1: Direct parse
    parsed = _parse_json_object(text)
    if parsed is not None:
        return parsed

    # Try 2: Strip markdown code fences
    parsed = _parse_json_object(_strip_markdown_json_fence(text))
    if parsed is not None:
        return parsed

    # Try 3: Extract JSON from mixed content
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        parsed = _parse_json_object(candidate)
        if parsed is not None:
            return parsed

        # Try 4: Fix common JSON issues (trailing commas before } or ])
        import re
        fixed = re.sub(r',(\s*[}\]])', r'\1', candidate)
        parsed = _parse_json_object(fixed)
        if parsed is not None:
            return parsed

    return None


def _sanitize_error(error: Exception, config: LLMConfig) -> str:
    text = str(error)
    if config.api_key:
        text = text.replace(config.api_key, "***")
    return text[:300]


def generate_llm_commentary(
    ai_payload: dict[str, Any],
    config: LLMConfig,
    post: PostCallable | None = None,
) -> dict[str, Any]:
    validate_llm_config(config)
    request_post = post or requests.post
    messages = build_llm_messages(ai_payload)
    body = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        **config.extra_headers,
    }
    response = request_post(
        openai_chat_completions_url(config.base_url),
        headers=headers,
        json=body,
        timeout=config.timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") or []
    content = str((((choices[0] if choices else {}).get("message") or {}).get("content")) or "")

    parsed = _parse_content(content)
    if parsed is None and content:
        # Log parsing failure for debugging
        import sys
        print(f"[LLM JSON PARSE FAIL] Unable to parse LLM response:", file=sys.stderr)
        print(f"  Content length: {len(content)}", file=sys.stderr)
        print(f"  First 300 chars: {content[:300]}", file=sys.stderr)

    return {
        "status": "ok",
        "provider": config.provider,
        "model": config.model,
        "content": content,
        "parsed": parsed,
        "usage": payload.get("usage"),
        "endpoint": openai_chat_completions_url(config.base_url),
    }


def safe_generate_llm_commentary(
    ai_payload: dict[str, Any],
    config: LLMConfig,
    post: PostCallable | None = None,
) -> dict[str, Any]:
    try:
        return generate_llm_commentary(ai_payload, config=config, post=post)
    except Exception as exc:
        return {
            "status": "error",
            "provider": config.provider,
            "model": config.model,
            "error_type": exc.__class__.__name__,
            "error": _sanitize_error(exc, config),
        }
