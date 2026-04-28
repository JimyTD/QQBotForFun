"""Core · llm

OpenAI 兼容 LLM 统一网关。

核心概念：
- Provider：一个后端（zhipu / siliconflow / openrouter...）
- Scene：业务使用场景（turtle_soup_host 等），映射到某个 provider + model + 参数

详见 docs/08-llm-integration.md 和 docs/adr/0003-llm-gateway.md。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from nonebot import logger
from openai import AsyncOpenAI, BadRequestError

from core.errors import (
    LLMConfigError,
    LLMError,
    LLMJSONParseError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from src.settings import get_settings


# =====================================================================
# 数据类型
# =====================================================================
@dataclass
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0

    def json(self) -> Any:
        """解析内容为 JSON；失败抛 LLMJSONParseError。"""
        try:
            return json.loads(_strip_code_fence(self.content))
        except json.JSONDecodeError as e:
            raise LLMJSONParseError(f"not valid json: {self.content[:200]}") from e


# =====================================================================
# 配置加载
# =====================================================================
@dataclass
class _ProviderConf:
    name: str
    base_url: str
    api_key: str
    timeout_seconds: float = 60.0


@dataclass
class _SceneConf:
    name: str
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 1024
    json_mode_default: bool = False
    timeout_seconds: float | None = None


@dataclass
class _Defaults:
    retries: int = 3
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 10.0


class _Config:
    providers: dict[str, _ProviderConf]
    scenes: dict[str, _SceneConf]
    defaults: _Defaults

    def __init__(self) -> None:
        self.providers = {}
        self.scenes = {}
        self.defaults = _Defaults()


_config: _Config | None = None
_clients: dict[str, AsyncOpenAI] = {}


_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _interp_env(value: str) -> str:
    """把 `${VAR}` 替换为实际值。
    优先从 pydantic Settings 读取（会自动加载 .env），其次 os.environ。
    """
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001
        settings = None

    def repl(m: re.Match[str]) -> str:
        var = m.group(1)
        # 先看 Settings（字段名小写）
        if settings is not None:
            v = getattr(settings, var.lower(), None)
            if v:
                return str(v)
        return os.environ.get(var, "")

    return _ENV_VAR_RE.sub(repl, value)


def _load_config() -> _Config:
    settings = get_settings()
    path = Path(settings.llm_config_path)
    if not path.exists():
        raise LLMConfigError(f"LLM config not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    conf = _Config()

    # providers
    for name, block in (data.get("providers") or {}).items():
        conf.providers[name] = _ProviderConf(
            name=name,
            base_url=_interp_env(block["base_url"]),
            api_key=_interp_env(block.get("api_key", "")),
            timeout_seconds=float(block.get("timeout_seconds", 60)),
        )

    # defaults
    d = data.get("defaults") or {}
    conf.defaults = _Defaults(
        retries=int(d.get("retries", 3)),
        backoff_base_seconds=float(d.get("backoff_base_seconds", 1.0)),
        backoff_max_seconds=float(d.get("backoff_max_seconds", 10.0)),
    )

    # scenes
    for name, block in (data.get("scenes") or {}).items():
        provider = block["provider"]
        if provider not in conf.providers:
            raise LLMConfigError(
                f"scene '{name}' references unknown provider '{provider}'"
            )
        conf.scenes[name] = _SceneConf(
            name=name,
            provider=provider,
            model=block["model"],
            temperature=float(block.get("temperature", 0.7)),
            max_tokens=int(block.get("max_tokens", 1024)),
            json_mode_default=bool(block.get("json_mode_default", False)),
            timeout_seconds=(
                float(block["timeout_seconds"]) if "timeout_seconds" in block else None
            ),
        )

    if "default" not in conf.scenes:
        raise LLMConfigError("scene 'default' is required")

    return conf


def init() -> None:
    """启动时调用：加载并校验 LLM 配置。"""
    global _config
    _config = _load_config()
    # 预创建 client
    for name, p in _config.providers.items():
        if not p.api_key:
            logger.warning(f"[llm] provider '{name}' has no api_key; will fail on call")
            continue
        _clients[name] = AsyncOpenAI(
            base_url=p.base_url,
            api_key=p.api_key,
            timeout=p.timeout_seconds,
        )
    logger.info(
        f"[llm] init ok. providers={list(_config.providers)} scenes={list(_config.scenes)}"
    )


def _get_config() -> _Config:
    if _config is None:
        init()
    assert _config is not None
    return _config


def _get_client(provider: str) -> AsyncOpenAI:
    if provider not in _clients:
        p = _get_config().providers.get(provider)
        if p is None:
            raise LLMConfigError(f"unknown provider: {provider}")
        if not p.api_key:
            raise LLMConfigError(f"provider '{provider}' missing api_key")
        _clients[provider] = AsyncOpenAI(
            base_url=p.base_url, api_key=p.api_key, timeout=p.timeout_seconds
        )
    return _clients[provider]


# =====================================================================
# 调用入口
# =====================================================================
async def chat(
    messages: list[LLMMessage],
    *,
    scene: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    json_mode: bool | None = None,
    timeout: float | None = None,
) -> LLMResponse:
    """调用 LLM 获取一次完整回复。"""
    conf = _get_config()
    sc = conf.scenes.get(scene) or conf.scenes["default"]

    eff_json = sc.json_mode_default if json_mode is None else json_mode
    eff_temp = sc.temperature if temperature is None else temperature
    eff_max = sc.max_tokens if max_tokens is None else max_tokens
    eff_to = timeout or sc.timeout_seconds or conf.providers[sc.provider].timeout_seconds

    request_messages = [m.to_dict() for m in messages]
    if eff_json:
        # 对不支持 response_format 的模型，在 system 里追加约束
        _ensure_json_hint(request_messages)

    client = _get_client(sc.provider)

    attempts = conf.defaults.retries
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        start = time.monotonic()
        try:
            kwargs: dict[str, Any] = {
                "model": sc.model,
                "messages": request_messages,
                "temperature": eff_temp,
                "max_tokens": eff_max,
                "timeout": eff_to,
            }
            if eff_json:
                kwargs["response_format"] = {"type": "json_object"}
            completion = await client.chat.completions.create(**kwargs)
        except BadRequestError as e:
            # 4xx 不重试；但若 json_mode 不被支持，退化一次
            if eff_json and "response_format" in str(e):
                logger.warning(
                    f"[llm] scene={scene} model={sc.model} does not support response_format; falling back"
                )
                eff_json = False
                continue
            latency = int((time.monotonic() - start) * 1000)
            logger.error(f"[llm] bad_request scene={scene} latency={latency}ms: {e}")
            raise LLMError(f"bad request: {e}") from e
        except asyncio.TimeoutError as e:
            last_err = LLMTimeoutError(str(e))
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "429" in msg or "rate limit" in msg.lower():
                last_err = LLMRateLimitError(msg)
            else:
                last_err = LLMError(msg)
        else:
            latency = int((time.monotonic() - start) * 1000)
            choice = completion.choices[0]
            content = (choice.message.content or "").strip()
            usage = {
                "prompt_tokens": getattr(completion.usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(completion.usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(completion.usage, "total_tokens", 0) or 0,
            }
            logger.info(
                f"[llm] scene={scene} provider={sc.provider} model={sc.model} "
                f"tokens={usage['prompt_tokens']}/{usage['completion_tokens']} "
                f"latency={latency}ms attempt={attempt}"
            )
            resp = LLMResponse(content=content, model=sc.model, usage=usage, latency_ms=latency)
            if eff_json:
                # 尝试解析，失败重试一次（只尝试一次额外重试，避免死循环）
                try:
                    json.loads(_strip_code_fence(content))
                except json.JSONDecodeError:
                    if attempt == attempts:
                        raise LLMJSONParseError(f"json parse failed: {content[:200]}") from None
                    logger.warning(f"[llm] json parse failed on attempt {attempt}, retrying")
                    last_err = LLMJSONParseError("retry")
                    await _backoff(attempt, conf.defaults)
                    continue
            return resp

        # 到这里说明本次失败
        if attempt < attempts:
            await _backoff(attempt, conf.defaults)

    assert last_err is not None
    logger.error(f"[llm] scene={scene} exhausted retries: {last_err}")
    raise last_err


async def chat_stream(
    messages: list[LLMMessage],
    *,
    scene: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    conf = _get_config()
    sc = conf.scenes.get(scene) or conf.scenes["default"]
    client = _get_client(sc.provider)

    try:
        stream = await client.chat.completions.create(
            model=sc.model,
            messages=[m.to_dict() for m in messages],
            temperature=sc.temperature if temperature is None else temperature,
            max_tokens=sc.max_tokens if max_tokens is None else max_tokens,
            stream=True,
        )
    except Exception as e:  # noqa: BLE001
        raise LLMError(str(e)) from e

    async for chunk in stream:
        try:
            delta = chunk.choices[0].delta.content or ""
        except Exception:  # noqa: BLE001
            continue
        if delta:
            yield delta


async def embedding(text: str | list[str], *, scene: str = "default") -> list[list[float]]:
    """（占位）未来使用。"""
    raise NotImplementedError("embedding is not enabled in v1")


# =====================================================================
# 内部工具
# =====================================================================
async def _backoff(attempt: int, d: _Defaults) -> None:
    delay = min(d.backoff_base_seconds * (2 ** (attempt - 1)), d.backoff_max_seconds)
    await asyncio.sleep(delay)


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_code_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = _CODE_FENCE_RE.sub("", s).strip()
    return s


def _ensure_json_hint(messages: list[dict[str, str]]) -> None:
    hint = "You MUST respond with valid JSON only. Do not include markdown code fences."
    if messages and messages[0]["role"] == "system":
        if "json" not in messages[0]["content"].lower():
            messages[0]["content"] += "\n\n" + hint
    else:
        messages.insert(0, {"role": "system", "content": hint})


# 初始化钩子（可由 bot.py 显式调用，也容许首次 chat 时懒加载）
def is_initialized() -> bool:
    return _config is not None
