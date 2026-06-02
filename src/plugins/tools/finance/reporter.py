"""经济天气 · 播报文案生成。

将检测结果合并，调用 LLM 生成自然语言播报。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from nonebot import logger

from .detector import AnomalyAlert, MacroAlert
from .prompts import FINANCE_REPORT_SYSTEM, FINANCE_REPORT_USER

CST = timezone(timedelta(hours=8))

_DISCLAIMER = "\n\n⚠️ 仅供闲聊参考，不构成投资建议"


def _build_structured_data(
    anomalies: list[AnomalyAlert],
    macros: list[MacroAlert],
) -> str:
    """将检测结果拼成给 LLM 看的结构化文本。"""
    parts: list[str] = []

    if anomalies:
        parts.append("【今日异动】")
        for a in anomalies:
            direction = "涨" if a.pct_chg > 0 else "跌"
            parts.append(
                f"- {a.cat_name}: {direction}了{abs(a.pct_chg)}%"
                f"（平时日均波动约{a.avg_vol}%，今天超出正常范围）"
            )

    if macros:
        parts.append("【宏观数据更新】")
        for m in macros:
            parts.append(
                f"- {m.name}（{m.plain_name}）: 最新 {m.value}，前值 {m.prev_value}"
            )

    return "\n".join(parts)


async def generate_report(
    anomalies: list[AnomalyAlert],
    macros: list[MacroAlert],
) -> str | None:
    """生成播报文案。无内容返回 None。"""
    if not anomalies and not macros:
        return None

    structured = _build_structured_data(anomalies, macros)

    try:
        from core import llm

        resp = await llm.chat(
            messages=[
                llm.LLMMessage(role="system", content=FINANCE_REPORT_SYSTEM),
                llm.LLMMessage(
                    role="user",
                    content=FINANCE_REPORT_USER.format(structured_data=structured),
                ),
            ],
            scene="finance_report",
            temperature=0.7,
            max_tokens=512,
        )
        text = resp.content.strip()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[finance] LLM failed, falling back to raw: {e}")
        text = _fallback_report(anomalies, macros)

    today = datetime.now(CST).strftime("%m月%d日")
    return f"── 经济天气 ({today}) ──\n\n{text}{_DISCLAIMER}"


def _fallback_report(
    anomalies: list[AnomalyAlert],
    macros: list[MacroAlert],
) -> str:
    """LLM 不可用时的纯规则兜底文案。"""
    lines: list[str] = []
    for a in anomalies:
        d = "涨" if a.pct_chg > 0 else "跌"
        lines.append(f"{a.cat_name}{d}了{abs(a.pct_chg)}%，平时波动约{a.avg_vol}%，今天不太正常。")
    for m in macros:
        lines.append(f"{m.plain_name}（{m.name}）更新：{m.value}（前值{m.prev_value}）")
    return "\n".join(lines)
