"""经济天气报告生成的兜底行为。"""

from __future__ import annotations

from typing import Any

import pytest

from core import llm
from plugins.tools.finance.detector import MacroAlert, TopMover
from plugins.tools.finance.reporter import _fallback_report, generate_report


def _top_mover() -> TopMover:
    return TopMover(
        cat_id="sz_index",
        cat_name="A股·深成指",
        pct_chg=-0.64,
        bar_date="2026-09-23",
        overnight=False,
    )


def _response(content: str, *, truncated: bool = False) -> llm.LLMResponse:
    return llm.LLMResponse(
        content=content,
        model="test-model",
        truncated=truncated,
    )


def test_fallback_separates_events_without_blank_edges() -> None:
    macro = MacroAlert(
        indicator_id="lpr", name="LPR", plain_name="贷款利率",
        date_str="2026-09-30", value="3.0", prev_value="3.1",
    )
    text = _fallback_report([], [macro], _top_mover())
    sections = text.split("\n\n")
    assert len(sections) == 2
    assert "A股·深成指" in sections[0]
    assert sections[1].startswith("贷款利率（LPR）")
    assert not text.startswith("\n") and not text.endswith("\n")
    assert _fallback_report([], [], None) == ""


@pytest.mark.asyncio
async def test_empty_llm_output_falls_back_to_raw_report(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _chat(*args: Any, **kwargs: Any) -> llm.LLMResponse:
        return _response("")

    monkeypatch.setattr(llm, "chat", _chat)

    report = await generate_report([], [], _top_mover())

    assert report is not None
    assert "A股·深成指" in report
    assert "跌了0.64%" in report


@pytest.mark.asyncio
async def test_truncated_llm_output_falls_back_to_raw_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _chat(*args: Any, **kwargs: Any) -> llm.LLMResponse:
        return _response("今日经济天气：", truncated=True)

    monkeypatch.setattr(llm, "chat", _chat)

    report = await generate_report([], [], _top_mover())

    assert report is not None
    assert "今日经济天气：" not in report
    assert "A股·深成指" in report


@pytest.mark.asyncio
async def test_normal_llm_output_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _chat(*args: Any, **kwargs: Any) -> llm.LLMResponse:
        return _response("今日经济天气：市场整体小幅波动。")

    monkeypatch.setattr(llm, "chat", _chat)

    report = await generate_report([], [], _top_mover())

    assert report is not None
    assert "今日经济天气：市场整体小幅波动。" in report
    assert "A股·深成指" not in report
