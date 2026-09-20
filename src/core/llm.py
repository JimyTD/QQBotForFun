"""Core · llm

OpenAI 兼容 LLM 统一网关。

核心概念：
- Provider：一个后端（zhipu / longcat / openrouter...）
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

import httpx
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
    #: 实际生效的 provider。阶梯链降档后可能与 scene 配置的链头不同。
    provider: str = ""
    #: 命中的档位下标：0 = 链头，>0 说明这次调用发生过降档。
    chain_index: int = 0
    #: `chain_index > 0` 的便捷标记。
    degraded: bool = False
    #: 输出撞上 `max_tokens` 被硬截断（`finish_reason == "length"`）。
    #: 调用方可据此提醒用户，而不是让用户看半句话。
    truncated: bool = False

    def json(self) -> Any:
        """解析内容为 JSON；失败抛 LLMJSONParseError。

        容忍模型在 JSON 前后夹带解释文字 —— 见 `_extract_json_block`。
        TokenHub 的档经常这样（实测 judge 输出 112–256 token，而 JSON 只需 ~50），
        直接 `json.loads` 会失败并触发无谓的重试与降档。
        """
        block = _extract_json_block(self.content)
        if block is None:
            raise LLMJSONParseError(f"not valid json: {self.content[:200]}")
        try:
            return json.loads(block)
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


@dataclass(frozen=True)
class _ChainSlot:
    """阶梯链上的一档：一个 (provider, model) 组合。"""

    provider: str
    model: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass
class _SceneConf:
    name: str
    #: 有序阶梯链。链头是首选档，之后依次降级（额度耗尽 / 限流 / 故障）。
    #: 单档链（旧的 provider+model 写法）在解析时等价成只有一个元素的链。
    chain: list[_ChainSlot]
    temperature: float = 0.7
    max_tokens: int = 1024
    json_mode_default: bool = False
    timeout_seconds: float | None = None
    #: 覆盖全局 `defaults.retries`。None = 用全局值。
    #: 群聊场景设成 1：单次超时最坏等待 = timeout_seconds，
    #: 而不是 timeout_seconds × retries（45×3 会让用户干等两分多钟）。
    retries: int | None = None
    #: 整次调用的**总预算**（含全部降档尝试）。None = 不限。
    #: 链上有 12 档，只压单次超时挡不住累积：12 × 15s 仍是 3 分钟。
    #: 超预算立即停手并抛错，让调用方走降级路径（如返回搜索摘要）。
    total_timeout_seconds: float | None = None

    @property
    def provider(self) -> str:
        """链头 provider（向后兼容旧用法）。"""
        return self.chain[0].provider

    @property
    def model(self) -> str:
        """链头 model（向后兼容旧用法）。"""
        return self.chain[0].model


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


def _parse_chain(
    scene: str, block: dict[str, Any], providers: dict[str, _ProviderConf]
) -> list[_ChainSlot]:
    """解析 scene 的阶梯链。

    ``chain`` 优先；旧的 ``provider`` + ``model`` 写法等价于只有一个元素的链，
    所以老配置不改也能继续跑。链元素有两种写法：

    ```yaml
    scenes:
      turtle_soup_judge:
        provider: tokenhub          # 链元素的默认 provider
        chain:
          - qwen3.5-plus            # 继承 scene.provider
          - tokenhub:glm-5.1        # 显式指定 provider（会覆盖默认）
          - zhipu:glm-4-flash-250414

      turtle_soup_claim:            # 旧写法，等价于单档链
        provider: zhipu
        model: glm-4-flash-250414
    ```

    ``provider:model`` 按**第一个**冒号切分 —— 模型名可能含斜杠
    （如 ``deepseek/deepseek-flash``），但不含冒号。
    """
    default_provider = block.get("provider")

    raw_items: list[str] = []
    if block.get("chain"):
        chain_block = block["chain"]
        if not isinstance(chain_block, list):
            raise LLMConfigError(f"scene '{scene}': 'chain' 必须是列表")
        raw_items = [str(item) for item in chain_block]
    elif block.get("model"):
        if not default_provider:
            raise LLMConfigError(f"scene '{scene}' 写了 'model' 但没有 'provider'")
        raw_items = [f"{default_provider}:{block['model']}"]
    else:
        raise LLMConfigError(
            f"scene '{scene}' 必须声明 'chain'，或 'provider' + 'model'"
        )

    slots: list[_ChainSlot] = []
    for raw in raw_items:
        item = raw.strip()
        if not item:
            continue
        if ":" in item:
            provider, model = item.split(":", 1)
        else:
            if not default_provider:
                raise LLMConfigError(
                    f"scene '{scene}': 链元素 '{item}' 未带 provider，"
                    f"且 scene 未声明默认 provider"
                )
            provider, model = default_provider, item
        provider, model = provider.strip(), model.strip()
        if not model:
            raise LLMConfigError(f"scene '{scene}': 链元素 '{item}' 缺少 model")
        if provider not in providers:
            raise LLMConfigError(
                f"scene '{scene}' references unknown provider '{provider}'"
            )
        slots.append(_ChainSlot(provider=provider, model=model))

    if not slots:
        raise LLMConfigError(f"scene '{scene}' 的 chain 为空")
    return slots


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
        conf.scenes[name] = _SceneConf(
            name=name,
            chain=_parse_chain(name, block, conf.providers),
            temperature=float(block.get("temperature", 0.7)),
            max_tokens=int(block.get("max_tokens", 1024)),
            json_mode_default=bool(block.get("json_mode_default", False)),
            timeout_seconds=(
                float(block["timeout_seconds"]) if "timeout_seconds" in block else None
            ),
            retries=int(block["retries"]) if "retries" in block else None,
            total_timeout_seconds=(
                float(block["total_timeout_seconds"])
                if "total_timeout_seconds" in block
                else None
            ),
        )

    if "default" not in conf.scenes:
        raise LLMConfigError("scene 'default' is required")

    return conf


# =====================================================================
# 阶梯链 · 错误分类 / 冷却 / 模型差异
# =====================================================================
# 设计依据见 docs/plans/2026-09-17-llm-tokenhub-model-ladder.md：
# - TokenHub 免费额度**按模型各自独立、不刷新、用完/下线即失效**
#   → 额度耗尽后冷却时间指数递增、24h 封顶，避免每隔几小时白白打一次已永久耗尽的档。
# - **限流 / 抖动**就地退避重试；**配额耗尽 / 鉴权失败 / 模型下线**立即降下一档。

KIND_RATE_LIMITED = "rate_limited"
KIND_QUOTA = "quota_exhausted"
KIND_AUTH = "auth"
KIND_TRANSIENT = "transient"
KIND_FATAL = "fatal"
KIND_UNAVAILABLE = "unavailable"

#: 可就地重试的两种；其余（配额/鉴权/参数/下线）直接降档，重试也白搭。
_RETRYABLE_KINDS = frozenset({KIND_RATE_LIMITED, KIND_TRANSIENT})

_BASE_COOL_SECONDS: dict[str, float] = {
    KIND_RATE_LIMITED: 35.0,
    KIND_TRANSIENT: 20.0,
    KIND_AUTH: 30 * 60.0,
    KIND_FATAL: 10 * 60.0,
    KIND_UNAVAILABLE: 24 * 3600.0,
}

#: 超时异常的类名。SDK / httpx 各自包装，不能只判断 `asyncio.TimeoutError`。
_TIMEOUT_CLASS_NAMES = frozenset(
    {"APITimeoutError", "TimeoutException", "ReadTimeout", "ConnectTimeout"}
)


def _is_timeout_error(exc: Exception) -> bool:
    """识别超时，作为**可重试的瞬态**处理。

    ⚠️ 只判断 ``asyncio.TimeoutError`` 是不够的：openai SDK 把超时包装成
    ``APITimeoutError``（继承 ``APIConnectionError``，**不是** ``asyncio.TimeoutError``），
    httpx 抛的则是 ``ReadTimeout`` 等。

    漏判的后果（2026-09-18 生产日志实锤）：超时落到函数末尾的兜底 ``KIND_FATAL``，
    于是 ①被当成不可重试 → 直接降档；②该档被冷却 **600 秒**，一次超时废掉最优模型
    十分钟。配合场景级 ``retries`` 控制重试次数，超时应当是"换个档再试"而非"封档"。
    """
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return True
    if any(cls.__name__ in _TIMEOUT_CLASS_NAMES for cls in type(exc).__mro__):
        return True
    # 最后兜底：SDK 的超时文案是固定的 "Request timed out."（实测），不与其他错误歧义。
    return "timed out" in str(exc).lower()


#: 额度耗尽的起步冷却与封顶（指数递增：6h → 12h → 24h）。
#: 封顶而非永久封禁，是为了留一条自愈路径——万一是临时 402 或额度被补发。
_QUOTA_BASE_COOL = 6 * 3600.0
_QUOTA_COOL_CAP = 24 * 3600.0


@dataclass
class _SlotHealth:
    cool_until: float = 0.0
    last_error: str | None = None
    last_error_kind: str | None = None
    last_ok_at: float | None = None
    #: 连续「额度耗尽」次数，用于递增冷却。成功一次即清零。
    exhaust_count: int = 0


#: slot.key -> 健康态。进程内，重启清零（生产单实例，够用）。
_HEALTH: dict[str, _SlotHealth] = {}

#: TokenHub `/v1/models` 里**明确不可用**的 status（黑名单策略）。
#: 用黑名单而非白名单：字段没见过时宁可当成可用，也不要把能调的档误剔掉。
#: ⚠️ `pre-offline` = 「已公告下线但**仍可调用**」，**不在**此列 ——
#: 2026-09-18 实测：qwen3.5-*、glm-5.1、glm-5、glm-5-turbo、kimi-k2.5 全是这个状态，
#: 而它们正是最该优先烧的那批（见规划 §5.5.0）。
_OFFLINE_STATUSES = frozenset({"discontinued", "offline", "retired"})

#: `/v1/models` 返回的**可调用**模型名；None = 未知（不裁剪）。
_online_models: set[str] | None = None

#: 其中处于 `pre-offline`（已公告下线、仍在服务）的模型名。仅用于诊断提示。
_pre_offline_models: set[str] = set()

#: 各模型的请求差异 —— 不迁就就是整档 400，白白降级。
#: 键为 model 名（不含 provider 前缀）；未登记的走默认：
#: 用 scene 的 temperature、不发 thinking 字段。
#:
#: 可用字段：
#:   temperature   覆盖 scene 的 temperature
#:   thinking      "disabled" → 发 {"thinking": {"type": "disabled"}}
#:   no_thinking   True → 完全不发 thinking 字段（默认行为）
#:
#: ⚠️ 2026-09-18 已用 `scripts/probe_tokenhub_models.py` 对 A 类 13 档实测：
#: 全部可调用、全部支持 `response_format`、响应均在 5s 内
#: （单次采样，网络抖动大，仅作量级参考）。
#: 结论是**只有下面这一档需要特殊照顾**，其余走默认即可 —— 不必凭猜测填表。
_MODEL_QUIRKS: dict[str, dict[str, Any]] = {
    # kimi-k2.5：只接受 temperature=1.0。
    # 实测 0.1 / 0.6 一律返回 400（TokenHub 业务码 400001），
    # 不迁就的话这一整档会被判成 fatal 白白降级。
    # 另：该档还拒绝 thinking 字段，但默认行为本来就不发，故无需额外声明。
    "kimi-k2.5": {"temperature": 1.0},
}

# 供将来参考（实测观察，当前无需配置）：
# - minimax-m2.7：发 thinking={"type":"disabled"} 后仍返回 reasoning_content，
#   即该字段**关不掉**。默认不发已是正确做法；若将来把「默认发 disabled」改成默认值，
#   必须给它加 `no_thinking: True`。
# - 其余 11 档默认都会带 reasoning_content（即默认开思考），
#   但实测延迟仍在 1~4s，对 30s 超时的 judge 场景无压力，
#   所以规划里「别把强制思考的档放链头」这条**在 A 类清单上不成立**，无需为延迟调链序。


def _classify_exception(exc: Exception) -> str:
    """把一次调用失败归类。

    优先用 SDK 的 ``status_code``。TokenHub 的业务码要特判：
    ``401006``（endpoint is inactive）其实是**瞬态**，但码里带 "401"，
    走通用字符串匹配会被误判成鉴权失败而白白降档。
    """
    msg = str(exc)
    low = msg.lower()

    if "401006" in msg or "endpoint is inactive" in low:
        return KIND_TRANSIENT
    if _is_timeout_error(exc):
        return KIND_TRANSIENT

    status = getattr(exc, "status_code", None)
    if status is None:
        m = re.search(r"\b(4\d{2}|5\d{2})\b", msg)
        status = int(m.group(1)) if m else None

    if status == 402:
        return KIND_QUOTA
    if status == 429:
        return KIND_RATE_LIMITED
    if status in (401, 403):
        return KIND_AUTH
    if status == 404:
        return KIND_UNAVAILABLE
    if status == 400:
        # 400 多半是 quirks 没配对（不是模型坏），但也可能是模型名无效。
        if "model" in low and ("not found" in low or "not exist" in low or "invalid" in low):
            return KIND_UNAVAILABLE
        return KIND_FATAL
    if status is not None and status >= 500:
        return KIND_TRANSIENT

    if "额度" in msg or "未开通" in msg or "quota" in low or "insufficient" in low:
        return KIND_QUOTA
    if "rate limit" in low or "too many requests" in low:
        return KIND_RATE_LIMITED
    if "not found" in low or "does not exist" in low:
        return KIND_UNAVAILABLE
    return KIND_FATAL


def _cool_seconds_for(kind: str, exhaust_count: int = 1) -> float:
    if kind == KIND_QUOTA:
        n = max(1, exhaust_count)
        return min(_QUOTA_BASE_COOL * (2 ** (n - 1)), _QUOTA_COOL_CAP)
    return _BASE_COOL_SECONDS.get(kind, 10 * 60.0)


def _slot_available(slot: _ChainSlot) -> bool:
    """该档现在能不能试。

    三种情况直接判不可用（让链继续往下走）：
    1. provider 没配 api_key —— ⚠️ 必须在这里拦掉。``_get_client`` 会抛
       `LLMConfigError`，而它**不是** `LLMError` 的子类，会穿透降档逻辑
       打断整次调用，而不是优雅跳到下一档；
    2. 被 ``/v1/models`` 标成已下线；
    3. 正在冷却中。
    """
    conf = _get_config()
    provider = conf.providers.get(slot.provider)
    if provider is None or not provider.api_key:
        return False
    if (
        slot.provider == "tokenhub"
        and _online_models is not None
        and slot.model not in _online_models
    ):
        return False
    h = _HEALTH.get(slot.key)
    return h is None or h.cool_until <= time.time()


def _mark_slot_ok(slot: _ChainSlot) -> None:
    h = _HEALTH.setdefault(slot.key, _SlotHealth())
    h.cool_until = 0.0
    h.last_error = None
    h.last_error_kind = None
    h.last_ok_at = time.time()
    h.exhaust_count = 0


def _mark_slot_failed(slot: _ChainSlot, kind: str, message: str) -> None:
    h = _HEALTH.setdefault(slot.key, _SlotHealth())
    if kind == KIND_QUOTA:
        h.exhaust_count += 1
    cool = _cool_seconds_for(kind, h.exhaust_count)
    h.cool_until = time.time() + cool
    h.last_error = message[:400]
    h.last_error_kind = kind
    logger.warning(
        f"[llm] slot={slot.key} 失败 kind={kind} 冷却={cool:.0f}s: {message[:160]}"
    )


def _extra_body_for(model: str) -> dict[str, Any] | None:
    """按模型差异生成 openai SDK 的 ``extra_body``（非标参数走这里透传）。"""
    q = _MODEL_QUIRKS.get(model)
    if not q or q.get("no_thinking"):
        return None
    thinking = q.get("thinking")
    if thinking:
        return {"thinking": {"type": thinking}}
    return None


def refresh_online_models(*, timeout: float = 3.0) -> set[str] | None:
    """拉 TokenHub ``/v1/models``，得到当前**可调用**的模型名集合。

    启动时把**已下线**（``discontinued``）的档从链上剔除 —— 模型下线后不必改配置。

    ⚠️ 该接口返回的是**平台全量模型清单**（实测 121 个），不代表当前 Key 已开通哪些；
    能否调用仍以实际请求为准（未开通/额度耗尽都会 402）。
    ⚠️ 该接口**不反映额度是否耗尽**。
    失败返回 None（= 不裁剪），绝不抛异常阻断启动。
    """
    global _online_models, _pre_offline_models
    try:
        conf = _get_config()
        provider = conf.providers.get("tokenhub")
        if provider is None or not provider.api_key:
            return None
        resp = httpx.get(
            provider.base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {provider.api_key}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        items = resp.json().get("data") or []
        online: set[str] = set()
        pre_offline: set[str] = set()
        for it in items:
            if not isinstance(it, dict) or not it.get("id"):
                continue
            model = str(it["id"])
            status = str(it.get("status", "online")).lower()
            if status in _OFFLINE_STATUSES:
                continue
            online.add(model)
            if status == "pre-offline":
                pre_offline.add(model)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[llm] 拉取 tokenhub 模型列表失败，本次不裁剪链路: {e}")
        return None

    if not online:
        return None
    _online_models = online
    _pre_offline_models = pre_offline
    logger.info(
        f"[llm] tokenhub 可调用模型 {len(online)} 个"
        + (f"，其中 {len(pre_offline)} 个已公告下线（仍可用，应优先烧）" if pre_offline else "")
        + "；链上已停服的档将被跳过"
    )
    return online


def scene_chains() -> dict[str, list[str]]:
    """诊断用：scene 名 -> 链上各档的 slot key（如 ``["tokenhub:glm-5.1", "zhipu:..."]``）。

    只读配置，不发起任何调用。
    """
    try:
        conf = _get_config()
    except Exception:  # noqa: BLE001
        return {}
    return {name: [s.key for s in sc.chain] for name, sc in conf.scenes.items()}


def providers_snapshot() -> dict[str, dict[str, Any]]:
    """诊断用：各 provider 的 base_url 与是否配了 key（**不回显 key 本身**）。"""
    try:
        conf = _get_config()
    except Exception:  # noqa: BLE001
        return {}
    return {
        name: {"base_url": p.base_url, "configured": bool(p.api_key)}
        for name, p in conf.providers.items()
    }


def health_snapshot() -> list[dict[str, Any]]:
    """诊断用：按当前配置的链逐档给出冷却/下线状态。

    只读内存，**不发起任何真实调用** —— 探活会白白消耗免费额度。
    """
    try:
        conf = _get_config()
    except Exception:  # noqa: BLE001
        return []

    now = time.time()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sc in conf.scenes.values():
        for slot in sc.chain:
            if slot.key in seen:
                continue
            seen.add(slot.key)
            h = _HEALTH.get(slot.key)
            cooling = bool(h and h.cool_until > now)
            offline = (
                slot.provider == "tokenhub"
                and _online_models is not None
                and slot.model not in _online_models
            )
            if offline:
                status = "offline"
            elif cooling and h is not None and h.last_error_kind:
                status = h.last_error_kind
            else:
                status = "ok"
            out.append(
                {
                    "slot": slot.key,
                    "status": status,
                    "cool_remaining_s": round(h.cool_until - now) if cooling and h else 0,
                    "exhaust_count": h.exhaust_count if h else 0,
                    "last_ok_at": h.last_ok_at if h else None,
                    "last_error": h.last_error if h else None,
                    #: 已公告下线但仍在服务 —— 用一点少一点，链上应优先烧
                    "imminent_offline": slot.model in _pre_offline_models,
                }
            )
    return out


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
    # TokenHub 的模型下线后不必改配置：拉一次在线清单，链上已下线的档会被跳过。
    # 失败只告警，不影响启动。
    refresh_online_models()


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
    """调用 LLM 获取一次完整回复。

    按 scene 配置的**阶梯链**依次尝试：

    - 冷却中 / 已被 `/v1/models` 标记下线的档**直接跳过**，不浪费一次调用；
    - 失败分流：限流与抖动在档内退避重试；配额耗尽 / 鉴权失败 / 参数错 / 模型下线
      打冷却后**降下一档**；
    - 返回值的 ``model`` / ``provider`` 是**实际生效**的那一档，``chain_index > 0``
      表示本次发生过降档。

    全链都不可用时抛 `LLMError`（签名与异常族未变，调用点无需改动）。
    """
    conf = _get_config()
    sc = conf.scenes.get(scene) or conf.scenes["default"]

    eff_json = sc.json_mode_default if json_mode is None else json_mode
    eff_temp = sc.temperature if temperature is None else temperature
    eff_max = sc.max_tokens if max_tokens is None else max_tokens

    request_messages = [m.to_dict() for m in messages]
    if eff_json:
        # 对不支持 response_format 的模型，在 system 里追加约束
        _ensure_json_hint(request_messages)

    last_err: Exception | None = None
    skipped: list[str] = []
    # 总预算：跨全部降档尝试计时。链上有 12 档，只压单次超时挡不住累积。
    deadline = (
        time.monotonic() + sc.total_timeout_seconds
        if sc.total_timeout_seconds
        else None
    )

    for slot_index, slot in enumerate(sc.chain):
        if deadline is not None and time.monotonic() >= deadline:
            logger.warning(
                f"[llm] scene={scene} 已达总预算 {sc.total_timeout_seconds:.0f}s，"
                f"停止降档（已试 {slot_index} 档）"
            )
            last_err = LLMTimeoutError(
                f"scene '{scene}' 超出总预算 {sc.total_timeout_seconds:.0f}s"
            )
            break
        if not _slot_available(slot):
            skipped.append(slot.key)
            continue
        try:
            return await _call_slot(
                slot=slot,
                slot_index=slot_index,
                scene=sc,
                scene_name=scene,
                messages=request_messages,
                temperature=eff_temp,
                max_tokens=eff_max,
                json_mode=eff_json,
                timeout=timeout,
                defaults=conf.defaults,
                deadline=deadline,
            )
        except LLMJSONParseError as e:
            # 输出不合法不是 provider 的故障 —— 不打冷却，仅降档再试。
            last_err = e
            logger.warning(f"[llm] scene={scene} slot={slot.key} 输出非 JSON，降档重试")
        except LLMConfigError as e:
            # 兜底：该档配置不全（缺 api_key / provider 未声明）时跳过它继续降档。
            # ⚠️ LLMConfigError **不是** LLMError 的子类，不单独捕获就会穿透出去
            # 打断整次调用 —— 这正是「链上有一档没配好就整条链不可用」的成因。
            last_err = e
            logger.warning(f"[llm] scene={scene} slot={slot.key} 配置不可用，降档: {e}")
        except LLMError as e:
            last_err = e

    if last_err is None:
        last_err = LLMError(
            f"scene '{scene}' 没有可用的链档（全部冷却中或已下线）: {skipped}"
        )
    logger.error(f"[llm] scene={scene} 阶梯链全部失败: {last_err}")
    raise last_err


async def _call_slot(
    *,
    slot: _ChainSlot,
    slot_index: int,
    scene: _SceneConf,
    scene_name: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    timeout: float | None,
    defaults: _Defaults,
    deadline: float | None = None,
) -> LLMResponse:
    """在**单档内**完成调用（含退避重试与 JSON 校验）。

    失败时负责打好该档的冷却，再抛 `LLMError` 交给外层降档。
    """
    conf = _get_config()
    provider_conf = conf.providers[slot.provider]
    client = _get_client(slot.provider)
    eff_to = timeout or scene.timeout_seconds or provider_conf.timeout_seconds
    if deadline is not None:
        # 单次调用不得突破总预算：剩下的余量留给后面的降档档位。
        eff_to = min(eff_to, max(1.0, deadline - time.monotonic()))
    quirks = _MODEL_QUIRKS.get(slot.model, {})
    call_temp = float(quirks.get("temperature", temperature))
    extra_body = _extra_body_for(slot.model)
    # 场景级 retries 优先：交互式场景（群聊）靠它把最坏等待压到 timeout × 1。
    attempts = max(1, scene.retries if scene.retries is not None else defaults.retries)
    last_err: Exception | None = None

    for attempt in range(1, attempts + 1):
        start = time.monotonic()
        try:
            kwargs: dict[str, Any] = {
                "model": slot.model,
                "messages": messages,
                "temperature": call_temp,
                "max_tokens": max_tokens,
                "timeout": eff_to,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if extra_body:
                kwargs["extra_body"] = extra_body
            completion = await client.chat.completions.create(**kwargs)
        except BadRequestError as e:
            # 4xx 不重试；但若 json_mode 不被支持，退化一次（不降档）
            if json_mode and "response_format" in str(e):
                logger.warning(
                    f"[llm] slot={slot.key} 不支持 response_format，退化为纯文本 JSON 约束"
                )
                json_mode = False
                continue
            _mark_slot_failed(slot, KIND_FATAL, str(e))
            logger.error(f"[llm] bad_request slot={slot.key}: {e}")
            raise LLMError(f"bad request: {e}") from e
        except Exception as e:  # noqa: BLE001
            kind = _classify_exception(e)
            if kind in _RETRYABLE_KINDS and attempt < attempts:
                last_err = e
                await _backoff(attempt, defaults)
                continue
            _mark_slot_failed(slot, kind, str(e))
            raise _wrap_error(kind, e) from e

        latency = int((time.monotonic() - start) * 1000)
        choice = completion.choices[0]
        content = (choice.message.content or "").strip()
        # finish_reason 以前从未被读取：输出撞上 max_tokens 时会静默截断，
        # 用户拿到半句话而日志里看不出任何异常。这里补上留痕 + 标记。
        truncated = getattr(choice, "finish_reason", None) == "length"
        if truncated:
            logger.warning(
                f"[llm] scene={scene_name} slot={slot.key} "
                f"输出撞 max_tokens={max_tokens} 被截断"
            )

        if json_mode and not _is_valid_json(content):
            if attempt >= attempts:
                # 调用本身是成功的（拿到了回复），只是内容不合规 —— 别标成档位故障
                _mark_slot_ok(slot)
                raise LLMJSONParseError(f"json parse failed: {content[:200]}")
            logger.warning(f"[llm] slot={slot.key} 输出非 JSON，第 {attempt} 次重试")
            await _backoff(attempt, defaults)
            continue

        usage = {
            "prompt_tokens": getattr(completion.usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(completion.usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(completion.usage, "total_tokens", 0) or 0,
        }
        _mark_slot_ok(slot)
        logger.info(
            f"[llm] scene={scene_name} slot={slot.key} chain_index={slot_index} "
            f"tokens={usage['prompt_tokens']}/{usage['completion_tokens']} "
            f"latency={latency}ms attempt={attempt}"
        )
        return LLMResponse(
            content=content,
            model=slot.model,
            usage=usage,
            latency_ms=latency,
            provider=slot.provider,
            chain_index=slot_index,
            degraded=slot_index > 0,
            truncated=truncated,
        )

    # 走到这里说明档内重试耗尽（只可能是可重试类错误）
    assert last_err is not None
    final_kind = _classify_exception(last_err)
    _mark_slot_failed(slot, final_kind, f"retries exhausted: {last_err}")
    raise _wrap_error(final_kind, last_err) from last_err


async def chat_stream(
    messages: list[LLMMessage],
    *,
    scene: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """流式调用 —— ⚠️ **不走阶梯链降档**，只用链头。

    当前项目无调用者。流式一旦开始 yield 就无法换档，所以这里刻意保持简单；
    将来若要用，需先明确「已 yield 后不可降级」的语义。
    """
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


def _wrap_error(kind: str, exc: Exception) -> LLMError:
    """按错误类型返回语义化异常 —— 都是 `LLMError` 子类，调用点无需改动。"""
    message = str(exc)
    if kind == KIND_RATE_LIMITED:
        return LLMRateLimitError(message)
    if isinstance(exc, asyncio.TimeoutError):
        return LLMTimeoutError(message)
    return LLMError(message)


def _is_valid_json(text: str) -> bool:
    """能否从这段回复里抠出合法 JSON（容忍前后夹带解释文字）。"""
    block = _extract_json_block(text)
    if block is None:
        return False
    try:
        json.loads(block)
    except json.JSONDecodeError:
        return False
    return True


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_code_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = _CODE_FENCE_RE.sub("", s).strip()
    return s


def _extract_json_block(text: str) -> str | None:
    """从可能夹带解释文字的回复里，抠出**第一个完整的 JSON 对象**。

    为什么需要：即使 prompt 写明「严格输出 JSON，无多余文字」，
    TokenHub 的档（实测 qwen3.5-plus 等）仍会先来一段「好的，我来分析……」。
    旧实现只处理「整段被 ``` 包裹」，前后有文字就 `json.loads` 失败 ——
    而失败会触发档内重试 + 跨档降级，把一次 4s 的调用放大成几十秒。
    实测 judge 有 29% 的调用要重试 3 次才成功，根因就在这里。

    用**括号配对扫描**而不是正则：正则处理不了字符串内的花括号与转义，
    例如 ``{"hint": "他说{这样}"}`` 用正则会被括号数骗到。
    """
    s = _strip_code_fence(text)
    start = s.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return None


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
