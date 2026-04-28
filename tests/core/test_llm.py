"""LLM 网关：仅测试纯工具函数（JSON 解析、配置等），不打真实 API。"""

from __future__ import annotations

import pytest

from core import llm
from core.errors import LLMJSONParseError


def test_strip_code_fence_plain() -> None:
    assert llm._strip_code_fence('{"a":1}') == '{"a":1}'


def test_strip_code_fence_with_json_block() -> None:
    raw = "```json\n{\"a\":1}\n```"
    assert llm._strip_code_fence(raw).strip() == '{"a":1}'


def test_strip_code_fence_with_plain_block() -> None:
    raw = "```\n{\"a\":1}\n```"
    assert llm._strip_code_fence(raw).strip() == '{"a":1}'


def test_llmresponse_json_ok() -> None:
    r = llm.LLMResponse(content='{"x": 1, "y": [1,2]}', model="test")
    assert r.json() == {"x": 1, "y": [1, 2]}


def test_llmresponse_json_fail() -> None:
    r = llm.LLMResponse(content="not a json", model="test")
    with pytest.raises(LLMJSONParseError):
        r.json()


def test_llmresponse_json_with_fence() -> None:
    r = llm.LLMResponse(content='```json\n{"ok": true}\n```', model="test")
    assert r.json() == {"ok": True}


def test_ensure_json_hint_empty() -> None:
    msgs: list[dict[str, str]] = []
    llm._ensure_json_hint(msgs)
    assert msgs[0]["role"] == "system"
    assert "json" in msgs[0]["content"].lower()


def test_ensure_json_hint_existing_system() -> None:
    msgs = [{"role": "system", "content": "hello"}]
    llm._ensure_json_hint(msgs)
    assert len(msgs) == 1
    assert "json" in msgs[0]["content"].lower()
