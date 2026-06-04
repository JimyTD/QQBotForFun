"""经济天气 · 播报文案生成。

将检测结果合并，调用 LLM 生成自然语言播报。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from nonebot import logger

from .detector import AnomalyAlert, MacroAlert, TopMover
from .prompts import FINANCE_REPORT_SYSTEM, FINANCE_REPORT_USER

CST = timezone(timedelta(hours=8))


def _date_label(bar_date: str, overnight: bool = False) -> str:
    """将 bar 日期转为人话标签，始终返回非空字符串。"""
    today = date.today()
    try:
        d = date.fromisoformat(bar_date)
    except (ValueError, TypeError):
        return "今日"
    diff = (today - d).days
    if diff <= 0:
        return "今日"
    if diff == 1:
        return "昨日"
    return f"{d.month:02d}月{d.day:02d}日"

_DISCLAIMER = "\n\n⚠️ 仅供闲聊参考，不构成投资建议"

# ── 生活影响解读模板 ──────────────────────────────────────

_MACRO_IMPACT: dict[str, dict[str, str]] = {
    "cpi_monthly": {
        "up": "物价在涨，日常开销（买菜、吃饭）可能变贵",
        "down": "物价在跌，东西便宜了但可能说明消费不太行",
        "flip_up": "物价从跌转涨，钱包要注意了",
        "flip_down": "物价从涨转跌，消费降温了",
        "big_up": "物价涨得猛，超市账单可能明显变多",
    },
    "ppi_yearly": {
        "up": "工厂出厂价在涨，过段时间可能传导到零售价",
        "down": "工厂出厂价在跌，制造业压力比较大",
        "flip_up": "出厂价从跌转涨，原材料涨价的信号",
        "flip_down": "出厂价从涨转跌，工业品需求在降",
    },
    "lpr": {
        "up": "贷款利率涨了，房贷月供会变多",
        "down": "贷款利率降了，房贷月供能省点",
    },
}

_CAT_IMPACT: dict[str, str] = {
    "sh_index": "基金和养老账户可能受影响",
    "sz_index": "中小盘和科技基金关注下",
    "cy_index": "科技成长股波动明显",
    "us_spy": "全球资金情绪有波动",
    "us_aapl": "科技股风向标在动",
    "gold": "避险情绪有变化，跟国际局势可能相关",
    "hk_hsi": "港股和南下资金有动静",
    "oil_wti": "油价波动可能影响出行和物流成本",
    "fx_usd": "人民币汇率变了，海淘和留学费用关注下",
    "fx_eur": "欧元汇率波动，欧洲旅游购物成本有变化",
    "fx_jpy": "日元汇率变了，赴日旅游成本关注下",
}


def _interpret_macro(m: MacroAlert) -> str:
    """根据宏观数据的变动方向生成人话解读。"""
    templates = _MACRO_IMPACT.get(m.indicator_id, {})
    try:
        val = float(m.value)
        prev = float(m.prev_value)
    except (ValueError, TypeError):
        return ""

    if (prev < 0 and val > 0) or (prev <= 0 and val > 0.3):
        return templates.get("flip_up", "")
    if (prev > 0 and val < 0) or (prev >= 0 and val < -0.3):
        return templates.get("flip_down", "")
    if abs(val) >= 3:
        return templates.get("big_up" if val > 0 else "down", "")
    if val > prev:
        return templates.get("up", "")
    if val < prev:
        return templates.get("down", "")
    return ""


def _interpret_cat(cat_id: str) -> str:
    return _CAT_IMPACT.get(cat_id, "")


# ── 结构化数据（喂 LLM）──────────────────────────────────

def _build_structured_data(
    anomalies: list[AnomalyAlert],
    macros: list[MacroAlert],
    top_mover: TopMover | None,
) -> str:
    parts: list[str] = []

    if anomalies:
        parts.append("【行情异动】")
        for a in anomalies:
            direction = "涨" if a.pct_chg > 0 else "跌"
            label = _date_label(a.bar_date, a.overnight)
            impact = _interpret_cat(a.cat_id)
            parts.append(
                f"- {a.cat_name}（{label}）: {direction}了{abs(a.pct_chg)}%"
                f"（平时日均波动约{a.avg_vol}%，超出正常范围）"
            )
            if impact:
                parts.append(f"  生活影响：{impact}")

    if top_mover and not anomalies:
        direction = "涨" if top_mover.pct_chg > 0 else "跌"
        label = _date_label(top_mover.bar_date, top_mover.overnight)
        impact = _interpret_cat(top_mover.cat_id)
        parts.append("【行情关注】")
        parts.append(
            f"- {top_mover.cat_name}（{label}）: {direction}了{abs(top_mover.pct_chg)}%，各品类里动得最大"
        )
        if impact:
            parts.append(f"  生活影响：{impact}")

    if macros:
        parts.append("【宏观数据更新】")
        for m in macros:
            interp = _interpret_macro(m)
            parts.append(
                f"- {m.name}（{m.plain_name}）: 最新 {m.value}%，前值 {m.prev_value}%"
            )
            if interp:
                parts.append(f"  通俗解读：{interp}")

    return "\n".join(parts)


# ── 报告生成 ──────────────────────────────────────────────

async def generate_report(
    anomalies: list[AnomalyAlert],
    macros: list[MacroAlert],
    top_mover: TopMover | None = None,
) -> str | None:
    """生成播报文案。无内容返回 None。"""
    meaningful_macros = [m for m in macros if m.changed]
    has_content = bool(anomalies) or bool(meaningful_macros) or bool(top_mover)
    if not has_content:
        return None
    macros = meaningful_macros

    structured = _build_structured_data(anomalies, macros, top_mover)

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
        text = _fallback_report(anomalies, macros, top_mover)

    today = datetime.now(CST).strftime("%m月%d日")
    return f"── 经济天气 ({today}) ──\n\n{text}{_DISCLAIMER}"


def _fallback_report(
    anomalies: list[AnomalyAlert],
    macros: list[MacroAlert],
    top_mover: TopMover | None,
) -> str:
    """LLM 不可用时的纯规则兜底文案。"""
    lines: list[str] = []

    for a in anomalies:
        d = "涨" if a.pct_chg > 0 else "跌"
        label = _date_label(a.bar_date, a.overnight)
        line = f"{a.cat_name}（{label}）{d}了{abs(a.pct_chg)}%，平时波动约{a.avg_vol}%，不太正常。"
        impact = _interpret_cat(a.cat_id)
        if impact:
            line += f"{impact}。"
        lines.append(line)

    if top_mover and not anomalies:
        d = "涨" if top_mover.pct_chg > 0 else "跌"
        label = _date_label(top_mover.bar_date, top_mover.overnight)
        line = f"{label}动得最大的是{top_mover.cat_name}，{d}了{abs(top_mover.pct_chg)}%，还在正常范围。"
        impact = _interpret_cat(top_mover.cat_id)
        if impact:
            line += f"{impact}。"
        lines.append(line)

    for m in macros:
        interp = _interpret_macro(m)
        line = f"{m.plain_name}（{m.name}）: {m.prev_value} → {m.value}。"
        if interp:
            line += interp + "。"
        lines.append(line)

    return "\n".join(lines)
