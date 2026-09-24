"""阶梯链：配置解析、错误分类、冷却与降档行为。

全部离线 —— 不触网、不打真实 API。
设计文档：docs/08-llm-integration.md
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import patch

import pytest

from core import llm
from core.errors import LLMConfigError, LLMError, LLMJSONParseError


# ---------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------
class _FakeAPIError(Exception):
    """带 status_code 的假异常 —— _classify_exception 只看这个属性。"""

    def __init__(self, status: int, message: str = "boom") -> None:
        super().__init__(message)
        self.status_code = status


class _FakeCompletions:
    """按脚本文案依次返回结果：int = 抛该 HTTP 状态；str = 返回该内容。"""

    def __init__(self, script: list[Any], calls: list[str]) -> None:
        self._script = script
        self._calls = calls

    async def create(self, **kwargs: Any) -> Any:
        self._calls.append(kwargs["model"])
        step = self._script.pop(0) if self._script else "ok"
        if isinstance(step, int):
            raise _FakeAPIError(step)
        return _FakeCompletion(step)


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})()


class _FakeClient:
    def __init__(self, script: list[Any], calls: list[str]) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(script, calls)})()


def _make_config(slots: list[tuple[str, str]], *, retries: int = 1) -> llm._Config:
    conf = llm._Config()
    for name in {p for p, _ in slots}:
        conf.providers[name] = llm._ProviderConf(name=name, base_url="http://fake", api_key="k")
    conf.scenes["default"] = llm._SceneConf(
        name="default",
        chain=[llm._ChainSlot(provider=p, model=m) for p, m in slots],
    )
    conf.defaults = llm._Defaults(
        retries=retries, backoff_base_seconds=0.0, backoff_max_seconds=0.0
    )
    return conf


@pytest.fixture(autouse=True)
def _clean_state() -> Any:
    """每个用例都从干净的健康态 + 一份可用默认配置开始。

    健康态必须清（否则冷却会跨用例串味）；
    默认配置必须给 —— `_slot_available` 会检查 provider 的 api_key。
    """
    llm._HEALTH.clear()
    llm._online_models = None
    with patch.object(llm, "_config", _make_config([("tokenhub", "m1"), ("zhipu", "m2")])):
        yield
    llm._HEALTH.clear()
    llm._online_models = None


def _patch_llm(conf: llm._Config, clients: dict[str, Any]) -> Any:
    return (
        patch.object(llm, "_config", conf),
        patch.object(llm, "_get_client", side_effect=lambda p: clients[p]),
    )


async def _chat(scene: str = "default", **kw: Any) -> llm.LLMResponse:
    return await llm.chat([llm.LLMMessage(role="user", content="hi")], scene=scene, **kw)


# ---------------------------------------------------------------------
# _parse_chain
# ---------------------------------------------------------------------
def _providers(*names: str) -> dict[str, llm._ProviderConf]:
    return {
        n: llm._ProviderConf(name=n, base_url="http://fake", api_key="k") for n in names
    }


def test_parse_chain_backward_compatible_single_model() -> None:
    slots = llm._parse_chain(
        "s", {"provider": "zhipu", "model": "glm-4-flash-250414"}, _providers("zhipu")
    )
    assert len(slots) == 1
    assert slots[0].provider == "zhipu"
    assert slots[0].model == "glm-4-flash-250414"


def test_parse_chain_inherits_scene_provider() -> None:
    slots = llm._parse_chain(
        "s", {"provider": "zhipu", "chain": ["a", "b"]}, _providers("zhipu")
    )
    assert [(s.provider, s.model) for s in slots] == [("zhipu", "a"), ("zhipu", "b")]


def test_parse_chain_explicit_provider_override() -> None:
    slots = llm._parse_chain(
        "s",
        {"provider": "zhipu", "chain": ["a", "tokenhub:glm-5.1"]},
        _providers("zhipu", "tokenhub"),
    )
    assert [(s.provider, s.model) for s in slots] == [
        ("zhipu", "a"),
        ("tokenhub", "glm-5.1"),
    ]


def test_parse_chain_model_name_may_contain_slash() -> None:
    """模型名可能带斜杠（deepseek/deepseek-flash），按第一个冒号切分即可。"""
    slots = llm._parse_chain(
        "s", {"chain": ["tokenhub:deepseek/deepseek-flash"]}, _providers("tokenhub")
    )
    assert slots[0].provider == "tokenhub"
    assert slots[0].model == "deepseek/deepseek-flash"


def test_parse_chain_rejects_unknown_provider() -> None:
    with pytest.raises(LLMConfigError, match="unknown provider"):
        llm._parse_chain("s", {"chain": ["nope:x"]}, _providers("zhipu"))


def test_parse_chain_requires_chain_or_model() -> None:
    with pytest.raises(LLMConfigError, match="必须声明"):
        llm._parse_chain("s", {}, _providers("zhipu"))


def test_parse_chain_rejects_bare_item_without_default_provider() -> None:
    with pytest.raises(LLMConfigError, match="未带 provider"):
        llm._parse_chain("s", {"chain": ["glm-5.1"]}, _providers("tokenhub"))


def test_parse_chain_rejects_empty_chain() -> None:
    with pytest.raises(LLMConfigError, match="为空"):
        llm._parse_chain("s", {"chain": ["  "], "provider": "zhipu"}, _providers("zhipu"))


def test_scene_head_accessors_point_at_chain_head() -> None:
    sc = llm._SceneConf(
        name="s",
        chain=[llm._ChainSlot("tokenhub", "m1"), llm._ChainSlot("zhipu", "m2")],
    )
    assert sc.provider == "tokenhub"
    assert sc.model == "m1"


# ---------------------------------------------------------------------
# 错误分类
# ---------------------------------------------------------------------
def test_classify_tokenhub_401006_is_transient_not_auth() -> None:
    """401006 码里带 401，必须特判成瞬态，否则会被当鉴权失败白白降档。"""
    exc = _FakeAPIError(401, "Error code: 401006 - endpoint is inactive")
    assert llm._classify_exception(exc) == llm.KIND_TRANSIENT


def test_classify_402_is_quota() -> None:
    assert llm._classify_exception(_FakeAPIError(402)) == llm.KIND_QUOTA


def test_classify_429_is_rate_limited() -> None:
    assert llm._classify_exception(_FakeAPIError(429)) == llm.KIND_RATE_LIMITED


def test_classify_401_is_auth() -> None:
    assert llm._classify_exception(_FakeAPIError(401)) == llm.KIND_AUTH


def test_classify_404_is_unavailable() -> None:
    assert llm._classify_exception(_FakeAPIError(404)) == llm.KIND_UNAVAILABLE


def test_classify_503_is_transient() -> None:
    assert llm._classify_exception(_FakeAPIError(503)) == llm.KIND_TRANSIENT


def test_classify_timeout_is_transient() -> None:
    assert llm._classify_exception(TimeoutError()) == llm.KIND_TRANSIENT


def test_classify_api_timeout_error_is_transient() -> None:
    """回归：openai SDK 的 `APITimeoutError` 不是 `asyncio.TimeoutError`。

    2026-09-18 生产事故（06:21:55 那次「锁刃龙」）：超时落到兜底 `KIND_FATAL`，
    于是 ① 被当成不可重试 → 直接降档；② `qwen3.5-plus` 被冷却 **600 秒**，
    一次超时废掉最优档十分钟。必须按类名识别。
    """

    class APITimeoutError(Exception):  # 模拟 SDK 的包装类（真实类名一致）
        pass

    exc = APITimeoutError("Request timed out.")
    assert llm._is_timeout_error(exc)
    assert llm._classify_exception(exc) == llm.KIND_TRANSIENT


def test_classify_httpx_timeout_family_is_transient() -> None:
    assert llm._is_timeout_error(llm.httpx.ReadTimeout("read timeout"))
    assert llm._is_timeout_error(llm.httpx.ConnectTimeout("connect timeout"))
    assert llm._classify_exception(llm.httpx.ReadTimeout("read timeout")) == llm.KIND_TRANSIENT


def test_classify_400_with_timeout_word_stays_fatal() -> None:
    """别误伤：参数错误里带 "timeout" 字样仍是 fatal，不能当成超时。"""
    exc = _FakeAPIError(400, "invalid timeout parameter")
    assert not llm._is_timeout_error(exc)
    assert llm._classify_exception(exc) == llm.KIND_FATAL


def test_classify_falls_back_to_status_in_message() -> None:
    """没有 status_code 属性时，从消息里抠出 HTTP 状态码。"""
    assert llm._classify_exception(Exception("Error code: 402 - no quota")) == llm.KIND_QUOTA


# ---------------------------------------------------------------------
# 冷却
# ---------------------------------------------------------------------
def test_quota_cool_grows_exponentially_and_caps() -> None:
    base, cap = llm._QUOTA_BASE_COOL, llm._QUOTA_COOL_CAP
    assert llm._cool_seconds_for(llm.KIND_QUOTA, 1) == base
    assert llm._cool_seconds_for(llm.KIND_QUOTA, 2) == base * 2
    assert llm._cool_seconds_for(llm.KIND_QUOTA, 3) == base * 4
    # 额度不刷新 → 冷却递增但必须封顶，留一条自愈路径
    assert llm._cool_seconds_for(llm.KIND_QUOTA, 99) == cap


def test_mark_failed_then_slot_unavailable_until_cooldown() -> None:
    slot = llm._ChainSlot("tokenhub", "m1")
    assert llm._slot_available(slot)

    llm._mark_slot_failed(slot, llm.KIND_QUOTA, "402")
    assert not llm._slot_available(slot)
    assert llm._HEALTH[slot.key].exhaust_count == 1

    # 手动把冷却拨到过去 → 恢复可用
    llm._HEALTH[slot.key].cool_until = time.time() - 1
    assert llm._slot_available(slot)


def test_mark_ok_resets_exhaust_count() -> None:
    slot = llm._ChainSlot("tokenhub", "m1")
    llm._mark_slot_failed(slot, llm.KIND_QUOTA, "402")
    llm._mark_slot_failed(slot, llm.KIND_QUOTA, "402")
    assert llm._HEALTH[slot.key].exhaust_count == 2

    llm._mark_slot_ok(slot)
    assert llm._HEALTH[slot.key].exhaust_count == 0
    assert llm._slot_available(slot)


def test_offline_model_is_unavailable() -> None:
    """被 /v1/models 标记下线的档直接判不可用。"""
    llm._online_models = {"alive"}
    assert not llm._slot_available(llm._ChainSlot("tokenhub", "dead"))
    assert llm._slot_available(llm._ChainSlot("tokenhub", "alive"))
    # 非 tokenhub 的 provider 不受该清单影响
    assert llm._slot_available(llm._ChainSlot("zhipu", "dead"))


def test_refresh_online_models_keeps_pre_offline_but_drops_discontinued() -> None:
    """`pre-offline` 必须保留 —— 它仍可调用，且正是最该优先烧的档。

    回归用例：早期实现只认 `status == "online"`，会把 qwen3.5-* / glm-5.1 /
    glm-5 / glm-5-turbo / kimi-k2.5 这批「已公告下线」的档全部误剔，
    恰好剔掉链头的目标（2026-09-18 实测这 7 个都是 pre-offline）。
    """
    conf = llm._Config()
    conf.providers["tokenhub"] = llm._ProviderConf(
        name="tokenhub", base_url="http://fake", api_key="k"
    )
    conf.scenes["default"] = llm._SceneConf(
        name="default", chain=[llm._ChainSlot("tokenhub", "a")]
    )

    class _Resp:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, Any]:
            return {
                "data": [
                    {"id": "still-online", "status": "online"},
                    {"id": "imminent", "status": "pre-offline"},
                    {"id": "dead", "status": "discontinued"},
                    {"id": "no-status-field"},
                ]
            }

    with (
        patch.object(llm, "_config", conf),
        patch.object(llm.httpx, "get", return_value=_Resp()),
    ):
        online = llm.refresh_online_models()

    # 未知 status 也保留 —— 黑名单策略：宁可留着，也不误剔能调的档
    assert online == {"still-online", "imminent", "no-status-field"}
    assert "imminent" in llm._pre_offline_models
    assert llm._slot_available(llm._ChainSlot("tokenhub", "imminent"))
    assert not llm._slot_available(llm._ChainSlot("tokenhub", "dead"))


def test_slot_without_api_key_is_unavailable() -> None:
    """provider 没配 api_key 的档不该被尝试。"""
    conf = llm._Config()
    conf.providers["nokey"] = llm._ProviderConf(name="nokey", base_url="http://x", api_key="")
    conf.scenes["default"] = llm._SceneConf(
        name="default", chain=[llm._ChainSlot("nokey", "m")]
    )
    with patch.object(llm, "_config", conf):
        assert not llm._slot_available(llm._ChainSlot("nokey", "m"))


# ---------------------------------------------------------------------
# chat() 降档
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_chat_degrades_to_next_slot_on_quota_exhausted() -> None:
    conf = _make_config([("tokenhub", "m1"), ("zhipu", "m2")])
    calls: list[str] = []
    clients = {"tokenhub": _FakeClient([402], calls), "zhipu": _FakeClient(["ok"], calls)}

    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client:
        resp = await _chat()

    assert calls == ["m1", "m2"]
    assert resp.model == "m2"
    assert resp.provider == "zhipu"
    assert resp.chain_index == 1
    assert resp.degraded is True


@pytest.mark.asyncio
async def test_chat_head_slot_still_wins_when_healthy() -> None:
    conf = _make_config([("tokenhub", "m1"), ("zhipu", "m2")])
    calls: list[str] = []
    clients = {"tokenhub": _FakeClient(["ok"], calls), "zhipu": _FakeClient(["ok2"], calls)}

    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client:
        resp = await _chat()

    assert calls == ["m1"]
    assert resp.chain_index == 0
    assert resp.degraded is False


@pytest.mark.asyncio
async def test_chat_skips_slot_in_cooldown_without_calling_it() -> None:
    """冷却中的档不该再被真实调用一次。"""
    conf = _make_config([("tokenhub", "m1"), ("zhipu", "m2")])
    llm._mark_slot_failed(llm._ChainSlot("tokenhub", "m1"), llm.KIND_QUOTA, "402")

    calls: list[str] = []
    clients = {"tokenhub": _FakeClient(["ok"], calls), "zhipu": _FakeClient(["ok2"], calls)}
    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client:
        resp = await _chat()

    assert calls == ["m2"]
    assert resp.chain_index == 1


@pytest.mark.asyncio
async def test_chat_skips_provider_without_api_key_instead_of_raising() -> None:
    """链头 provider 没配 key → 跳过它降档，而不是整次调用失败。

    回归用例：`_get_client` 抛的是 `LLMConfigError`，它**不是** `LLMError` 的子类，
    不拦掉就会穿透 chat() 的降档循环 —— 表现为「链里有一档没配好，整条链都用不了」。
    """
    conf = llm._Config()
    conf.providers["nokey"] = llm._ProviderConf(name="nokey", base_url="http://x", api_key="")
    conf.providers["zhipu"] = llm._ProviderConf(name="zhipu", base_url="http://x", api_key="k")
    conf.scenes["default"] = llm._SceneConf(
        name="default",
        chain=[llm._ChainSlot("nokey", "m1"), llm._ChainSlot("zhipu", "m2")],
    )
    conf.defaults = llm._Defaults(
        retries=1, backoff_base_seconds=0.0, backoff_max_seconds=0.0
    )

    calls: list[str] = []
    clients = {"zhipu": _FakeClient(["ok"], calls)}
    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client:
        resp = await _chat()

    assert calls == ["m2"]
    assert resp.provider == "zhipu"
    assert resp.chain_index == 1


@pytest.mark.asyncio
async def test_chat_raises_when_all_slots_fail() -> None:
    conf = _make_config([("tokenhub", "m1"), ("zhipu", "m2")])
    calls: list[str] = []
    clients = {"tokenhub": _FakeClient([402], calls), "zhipu": _FakeClient([402], calls)}

    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client, pytest.raises(LLMError):
        await _chat()

    assert calls == ["m1", "m2"]


@pytest.mark.asyncio
async def test_chat_raises_when_every_slot_cooling() -> None:
    conf = _make_config([("tokenhub", "m1"), ("zhipu", "m2")])
    for p, m in (("tokenhub", "m1"), ("zhipu", "m2")):
        llm._mark_slot_failed(llm._ChainSlot(p, m), llm.KIND_QUOTA, "402")

    calls: list[str] = []
    clients = {"tokenhub": _FakeClient(["ok"], calls), "zhipu": _FakeClient(["ok"], calls)}
    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client, pytest.raises(LLMError, match="没有可用的链档"):
        await _chat()

    assert calls == []


@pytest.mark.asyncio
async def test_chat_retries_rate_limited_within_same_slot() -> None:
    """限流是就地重试，不该跳档。"""
    conf = _make_config([("tokenhub", "m1"), ("zhipu", "m2")], retries=3)
    calls: list[str] = []
    clients = {"tokenhub": _FakeClient([429, "ok"], calls), "zhipu": _FakeClient(["ok2"], calls)}

    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client:
        resp = await _chat()

    assert calls == ["m1", "m1"]
    assert resp.chain_index == 0


@pytest.mark.asyncio
async def test_chat_degrades_on_non_json_output() -> None:
    """JSON 不合规不是档位故障 —— 不打冷却，但要降档重试。"""
    conf = _make_config([("tokenhub", "m1"), ("zhipu", "m2")])
    calls: list[str] = []
    clients = {
        "tokenhub": _FakeClient(["not json"], calls),
        "zhipu": _FakeClient(['{"ok": true}'], calls),
    }

    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client:
        resp = await _chat(json_mode=True)

    assert calls == ["m1", "m2"]
    assert resp.chain_index == 1
    assert resp.json() == {"ok": True}
    # 拿到回复的档不算故障
    assert llm._HEALTH[llm._ChainSlot("tokenhub", "m1").key].exhaust_count == 0


@pytest.mark.asyncio
async def test_chat_success_clears_previous_cooldown() -> None:
    conf = _make_config([("tokenhub", "m1")])
    llm._mark_slot_failed(llm._ChainSlot("tokenhub", "m1"), llm.KIND_QUOTA, "402")
    llm._HEALTH["tokenhub:m1"].cool_until = time.time() - 1

    calls: list[str] = []
    clients = {"tokenhub": _FakeClient(["ok"], calls)}
    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client:
        await _chat()

    assert llm._HEALTH["tokenhub:m1"].cool_until == 0.0
    assert llm._HEALTH["tokenhub:m1"].last_error is None


def test_parse_chain_accepts_inline_list() -> None:
    slots = llm._parse_chain(
        "s", {"chain": ["zhipu:a", "zhipu:b"]}, _providers("zhipu")
    )
    assert [s.model for s in slots] == ["a", "b"]


# ---------------------------------------------------------------------
# 场景级 retries / 总预算 / 截断标记（2026-09-18 群聊等待过久事故的护栏）
# ---------------------------------------------------------------------
class _ScriptedCompletions:
    """比 `_FakeCompletions` 更自由的替身：可注入延迟与 finish_reason。"""

    def __init__(
        self,
        *,
        calls: list[str],
        delay: float = 0.0,
        error: Exception | None = None,
        content: str = "ok",
        finish_reason: str | None = None,
        max_tokens: int = 2048,
    ) -> None:
        self._calls = calls
        self._delay = delay
        self._error = error
        self._content = content
        self._finish_reason = finish_reason
        self._max_tokens = max_tokens

    async def create(self, **kwargs: Any) -> Any:
        self._calls.append(kwargs["model"])
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        choice = type(
            "C",
            (),
            {
                "message": type("M", (), {"content": self._content})(),
                "finish_reason": self._finish_reason,
            },
        )()
        usage = type(
            "U",
            (),
            {
                "prompt_tokens": 10,
                "completion_tokens": self._max_tokens,
                "total_tokens": 10 + self._max_tokens,
            },
        )()
        return type("R", (), {"choices": [choice], "usage": usage})()


def _client_with(completions: Any) -> Any:
    return type("C", (), {"chat": type("Ch", (), {"completions": completions})()})()


@pytest.mark.asyncio
async def test_scene_retries_overrides_global_defaults() -> None:
    """场景级 retries=1 覆盖全局 3：群聊场景不再重复烧用户的时间。"""
    conf = _make_config([("tokenhub", "m1")], retries=3)
    conf.scenes["default"].retries = 1

    calls: list[str] = []
    clients = {"tokenhub": _FakeClient([429, "ok"], calls)}
    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client, pytest.raises(LLMError):
        await _chat()

    assert calls == ["m1"]


@pytest.mark.asyncio
async def test_chat_gives_up_once_total_budget_is_spent() -> None:
    """总预算耗尽后不再尝试后续档。

    只压单次超时挡不住累积：链上 12 档 × 15s 仍是 3 分钟。
    """
    conf = _make_config([("tokenhub", "m1"), ("zhipu", "m2")])
    scene = conf.scenes["default"]
    scene.timeout_seconds = 0.05
    scene.total_timeout_seconds = 0.1

    calls: list[str] = []
    slow = _ScriptedCompletions(
        calls=calls, delay=0.25, error=TimeoutError("Request timed out.")
    )
    clients = {"tokenhub": _client_with(slow), "zhipu": _client_with(slow)}

    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client, pytest.raises(LLMError):
        await _chat()

    # 第一档超时耗时已超预算 → 第二档不该再被打一次
    assert calls == ["m1"]


@pytest.mark.asyncio
async def test_chat_flags_truncated_output() -> None:
    """`finish_reason == length` 必须被标记 —— 别再静默给用户半句话。"""
    conf = _make_config([("tokenhub", "m1")])
    calls: list[str] = []
    truncated = _ScriptedCompletions(
        calls=calls, content="半句话", finish_reason="length"
    )
    clients = {"tokenhub": _client_with(truncated)}

    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client:
        resp = await _chat()

    assert resp.truncated is True


@pytest.mark.asyncio
async def test_chat_marks_normal_output_not_truncated() -> None:
    conf = _make_config([("tokenhub", "m1")])
    calls: list[str] = []
    normal = _ScriptedCompletions(calls=calls, content="完整回答", finish_reason="stop")
    clients = {"tokenhub": _client_with(normal)}

    p_conf, p_client = _patch_llm(conf, clients)
    with p_conf, p_client:
        resp = await _chat()

    assert resp.truncated is False


# ---------------------------------------------------------------------
# 真实配置文件（config/llm.yaml）
# ---------------------------------------------------------------------
def test_project_llm_yaml_loads_and_every_scene_ends_with_zhipu() -> None:
    """配置写错会直接阻止 bot 启动，所以这里把真实配置读一遍。

    断言的只是**结构约定**，不锁死具体模型名 —— 链序会随评测结果调整。
    """
    conf = llm._load_config()

    assert "default" in conf.scenes
    assert "zhipu" in conf.providers
    assert "tokenhub" in conf.providers

    for name, sc in conf.scenes.items():
        assert sc.chain, f"scene '{name}' 的链为空"
        # 尾档必须是智谱：TokenHub 那边额度用完/下线后总要有东西接住
        assert sc.chain[-1].provider == "zhipu", f"scene '{name}' 的尾档不是智谱兜底"
        assert all(s.model for s in sc.chain), f"scene '{name}' 有空模型名"


# ---------------------------------------------------------------------
# 诊断
# ---------------------------------------------------------------------
def test_health_snapshot_is_read_only_and_lists_slots() -> None:
    conf = _make_config([("tokenhub", "m1"), ("zhipu", "m2")])
    with patch.object(llm, "_config", conf):
        snap = llm.health_snapshot()
    assert [s["slot"] for s in snap] == ["tokenhub:m1", "zhipu:m2"]
    assert all(s["status"] == "ok" for s in snap)


# ---------------------------------------------------------------------
# JSON 提取：容忍模型在 JSON 前后夹带解释文字
# ---------------------------------------------------------------------
# 背景（2026-09-20 生产日志）：TokenHub 的档常先来一段「好的，我来分析……」，
# 而旧实现只处理「整段被 ``` 包裹」，于是 json.loads 失败 →
# 档内重试 3 次 → 跨档降级。实测 judge 有 29% 的调用要重试 3 次才成功，
# 最长一次拖到 92 秒。下面这些用例锁住「夹带文字也能解析出来」。
def test_extract_json_block_plain() -> None:
    assert llm._extract_json_block('{"a": 1}') == '{"a": 1}'


def test_extract_json_block_with_leading_prose() -> None:
    text = '好的，我来分析一下这个问题。\n{"type": "yes", "hint": ""}'
    assert llm._extract_json_block(text) == '{"type": "yes", "hint": ""}'


def test_extract_json_block_with_trailing_prose() -> None:
    text = '{"type": "no"}\n以上就是我的判定，希望有帮助。'
    assert llm._extract_json_block(text) == '{"type": "no"}'


def test_extract_json_block_with_fence_and_prose() -> None:
    text = '分析：\n```json\n{"a": {"b": 1}}\n```\n完毕。'
    assert llm._extract_json_block(text) == '{"a": {"b": 1}}'


def test_extract_json_block_ignores_braces_inside_string() -> None:
    """字符串里的花括号不能骗过配对扫描 —— 用正则做这件事会翻车。"""
    text = '前言 {"hint": "他说{这样}就好了", "type": "key"} 后记'
    assert llm._extract_json_block(text) == '{"hint": "他说{这样}就好了", "type": "key"}'


def test_extract_json_block_handles_escaped_quote() -> None:
    raw = r'{"hint": "他说\"你好\"", "n": 1}'
    assert llm._extract_json_block(f"前言 {raw} 后记") == raw


def test_extract_json_block_nested_objects() -> None:
    assert llm._extract_json_block('x {"a": {"b": {"c": 1}}} y') == '{"a": {"b": {"c": 1}}}'


def test_extract_json_block_returns_none_without_json() -> None:
    assert llm._extract_json_block("抱歉，我无法回答这个问题。") is None


def test_extract_json_block_returns_none_on_unterminated_object() -> None:
    """括号没配平 → 不返回片段，交给调用方按「解析失败」处理。"""
    assert llm._extract_json_block('{"a": 1') is None


def test_llmresponse_json_tolerates_surrounding_prose() -> None:
    """回归：夹带文字的回复以前会被判 JSON 失败，触发重试与降档。"""
    r = llm.LLMResponse(
        content='好的，判定如下：\n{"type": "irrelevant", "hint": ""}\n以上。',
        model="test",
    )
    assert r.json() == {"type": "irrelevant", "hint": ""}


def test_is_valid_json_uses_same_tolerance_as_parser() -> None:
    """预校验与解析必须同一套标准，否则会出现「校验通过、解析却失败」。"""
    assert llm._is_valid_json('前言 {"ok": true} 后记')
    assert not llm._is_valid_json("没有任何 JSON")


def test_llmresponse_json_still_raises_on_garbage() -> None:
    r = llm.LLMResponse(content="完全不是 JSON", model="test")
    with pytest.raises(LLMJSONParseError):
        r.json()
