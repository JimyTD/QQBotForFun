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
    pct_chg: float      # 今日涨跌幅
    avg_vol: float       # 近期日均绝对波动
    threshold: float     # 触发阈值


@dataclass
class MacroAlert:
    """宏观数据新发布。"""

    indicator_id: str
    name: str
    plain_name: str
    date_str: str
    value: str
    prev_value: str


def _cat_name(cat_id: str) -> str:
    for c in CATEGORIES:
        if c.id == cat_id:
            return c.name
    return cat_id


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
            alerts.append(AnomalyAlert(
                cat_id=cat_id,
                cat_name=_cat_name(cat_id),
                pct_chg=round(today.pct_chg, 2),
                avg_vol=round(mean_vol, 2),
                threshold=round(threshold, 2),
            ))
            logger.info(
                f"[finance] anomaly: {cat_id} {today.pct_chg:+.2f}% "
                f"(threshold={threshold:.2f}%, avg={mean_vol:.2f}%)"
            )

    return alerts


async def detect_macro_updates() -> list[MacroAlert]:
    """检测宏观数据是否有新发布，返回需要播报的列表。"""
    from .storage import get_macro_seen, set_macro_seen

    macros = fetch_all_macros()
    alerts: list[MacroAlert] = []

    for point in macros:
        seen_date, _ = await get_macro_seen(point.indicator_id)

        if point.date_str != seen_date:
            alerts.append(MacroAlert(
                indicator_id=point.indicator_id,
                name=point.name,
                plain_name=point.plain_name,
                date_str=point.date_str,
                value=point.value,
                prev_value=point.prev_value,
            ))
            await set_macro_seen(point.indicator_id, point.date_str, point.value)
            logger.info(
                f"[finance] macro update: {point.name} "
                f"{point.prev_value} -> {point.value} ({point.date_str})"
            )

    return alerts


async def run_detection() -> tuple[list[AnomalyAlert], list[MacroAlert]]:
    """完整检测流程：拉数据 + 异动 + 宏观。"""
    from .data_provider import clear_cache

    clear_cache()

    data = fetch_all_categories()
    logger.info(f"[finance] fetched {len(data)} categories")

    anomalies = detect_anomalies(data)
    macros = await detect_macro_updates()

    return anomalies, macros
