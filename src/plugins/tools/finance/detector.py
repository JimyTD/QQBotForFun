"""经济天气 · 异动检测 + 宏观数据检测。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from nonebot import logger

from .config import CATEGORIES, LOOKBACK_DAYS, N_SIGMA, CategoryDef
from .data_provider import DailyBar, MacroDataPoint, fetch_all_categories, fetch_all_macros


@dataclass
class AnomalyAlert:
    """品类异动。"""

    cat_id: str
    cat_name: str
    pct_chg: float      # 涨跌幅
    avg_vol: float       # 近期日均绝对波动
    threshold: float     # 触发阈值
    bar_date: str = ""   # 数据实际日期 YYYY-MM-DD
    overnight: bool = False  # 隔夜市场（昨天的date是正常最新）


@dataclass
class TopMover:
    """最大波动（未达异动阈值时使用）。"""

    cat_id: str
    cat_name: str
    pct_chg: float
    bar_date: str = ""   # 数据实际日期 YYYY-MM-DD
    overnight: bool = False


@dataclass
class MacroAlert:
    """宏观数据新发布。"""

    indicator_id: str
    name: str
    plain_name: str
    date_str: str
    value: str
    prev_value: str
    changed: bool = True  # value != prev_value


def _cat_def(cat_id: str) -> CategoryDef | None:
    for c in CATEGORIES:
        if c.id == cat_id:
            return c
    return None


def _cat_name(cat_id: str) -> str:
    c = _cat_def(cat_id)
    return c.name if c else cat_id


def detect_anomalies(data: dict[str, list[DailyBar]]) -> list[AnomalyAlert]:
    """对所有品类做异动检测，返回今天触发的异动列表。"""
    alerts: list[AnomalyAlert] = []

    for cat_id, bars in data.items():
        if len(bars) < LOOKBACK_DAYS + 1:
            continue

        recent = bars[-(LOOKBACK_DAYS + 1) :]
        lookback = [abs(b.pct_chg) for b in recent[:-1]]
        today = recent[-1]

        mean_vol = float(np.mean(lookback))
        std_vol = float(np.std(lookback, ddof=1))

        if std_vol == 0:
            continue

        threshold = mean_vol + N_SIGMA * std_vol
        if abs(today.pct_chg) > threshold:
            cat = _cat_def(cat_id)
            alerts.append(AnomalyAlert(
                cat_id=cat_id,
                cat_name=cat.name if cat else cat_id,
                pct_chg=round(today.pct_chg, 2),
                avg_vol=round(mean_vol, 2),
                threshold=round(threshold, 2),
                bar_date=today.date,
                overnight=cat.overnight if cat else False,
            ))
            logger.info(
                f"[finance] anomaly: {cat_id} {today.pct_chg:+.2f}% "
                f"(threshold={threshold:.2f}%, avg={mean_vol:.2f}%)"
            )

    return alerts


def find_top_mover(data: dict[str, list[DailyBar]]) -> TopMover | None:
    """找到今日绝对涨跌幅最大的品类。|pct_chg| < 0.3% 时返回 None。"""
    best: TopMover | None = None
    for cat_id, bars in data.items():
        if not bars:
            continue
        today = bars[-1]
        if best is None or abs(today.pct_chg) > abs(best.pct_chg):
            cat = _cat_def(cat_id)
            best = TopMover(
                cat_id=cat_id,
                cat_name=cat.name if cat else cat_id,
                pct_chg=round(today.pct_chg, 2),
                bar_date=today.date,
                overnight=cat.overnight if cat else False,
            )
    if best is not None and abs(best.pct_chg) < 0.3:
        return None
    return best


async def detect_macro_updates() -> list[MacroAlert]:
    """检测宏观数据是否有新发布，返回需要播报的列表。"""
    import asyncio

    from .storage import get_macro_seen, set_macro_seen

    macros = await asyncio.to_thread(fetch_all_macros)
    alerts: list[MacroAlert] = []

    for point in macros:
        seen_date, _ = await get_macro_seen(point.indicator_id)

        if point.date_str != seen_date:
            value_changed = point.value.strip() != point.prev_value.strip()
            alerts.append(MacroAlert(
                indicator_id=point.indicator_id,
                name=point.name,
                plain_name=point.plain_name,
                date_str=point.date_str,
                value=point.value,
                prev_value=point.prev_value,
                changed=value_changed,
            ))
            await set_macro_seen(point.indicator_id, point.date_str, point.value)
            logger.info(
                f"[finance] macro {'update' if value_changed else 'unchanged'}: "
                f"{point.name} {point.prev_value} -> {point.value} ({point.date_str})"
            )

    return alerts


async def run_detection() -> tuple[list[AnomalyAlert], list[MacroAlert], TopMover | None]:
    """完整检测流程：拉数据 + 异动 + 宏观 + 最大波动。"""
    import asyncio

    from .data_provider import clear_cache

    clear_cache()

    # AKShare 调用是同步阻塞的（含 time.sleep 限速），用 to_thread 避免阻塞事件循环
    data = await asyncio.to_thread(fetch_all_categories)
    logger.info(f"[finance] fetched {len(data)} categories")

    anomalies = detect_anomalies(data)
    macros = await detect_macro_updates()
    top_mover = find_top_mover(data) if not anomalies else None

    return anomalies, macros, top_mover
