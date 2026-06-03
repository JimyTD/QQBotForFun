"""经济天气 · 数据中间层。

所有 AKShare 调用统一走这里，外部不直接 import akshare。
提供缓存（同一次定时任务内不重复请求）和统一的数据结构。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from nonebot import logger

from .config import CATEGORIES, MACRO_INDICATORS, CategoryDef, MacroIndicator

# 延迟 import akshare，首次调用时加载
_ak = None


def _get_ak():  # noqa: ANN202
    global _ak
    if _ak is None:
        import akshare

        _ak = akshare
    return _ak


@dataclass
class DailyBar:
    date: str  # YYYY-MM-DD
    pct_chg: float  # 日涨跌幅 (%)


@dataclass
class MacroDataPoint:
    indicator_id: str
    name: str
    plain_name: str
    date_str: str
    value: str
    prev_value: str


# ── 内存缓存 ──────────────────────────────────────────────

_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 300  # 5 分钟


def _get_cached(key: str) -> object | None:
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return val
    return None


def _set_cached(key: str, val: object) -> None:
    _cache[key] = (time.time(), val)


def clear_cache() -> None:
    _cache.clear()


# ── 数据拉取 ──────────────────────────────────────────────

def _safe_call(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
    """同步调用 AKShare 接口，失败返回 None。"""
    try:
        time.sleep(0.5)
        return func(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[finance] akshare call {func.__name__} failed: {e}")
        return None


def _price_to_bars(df: pd.DataFrame, date_col: str, price_col: str, tail_n: int = 70) -> list[DailyBar]:
    """价格序列 -> DailyBar 列表。"""
    df = df.copy()
    df["_date"] = pd.to_datetime(df[date_col])
    df["_price"] = pd.to_numeric(df[price_col], errors="coerce")
    df = df.sort_values("_date").dropna(subset=["_price"]).tail(tail_n)
    df["_pct"] = df["_price"].pct_change() * 100
    df = df.dropna(subset=["_pct"])
    return [DailyBar(date=r["_date"].strftime("%Y-%m-%d"), pct_chg=round(r["_pct"], 4)) for _, r in df.iterrows()]


def _fetch_spot_pct(cat: CategoryDef) -> float | None:
    """用实时接口获取当日涨跌幅(%)，失败返回 None。"""
    ak = _get_ak()

    if cat.fetch_kind == "index_sina":
        cache_key = "_spot_zh_index"
        df = _get_cached(cache_key)
        if df is None:
            df = _safe_call(ak.stock_zh_index_spot_sina)
            if df is not None:
                _set_cached(cache_key, df)
        if df is not None:
            row = df[df["代码"] == cat.symbol]
            if len(row) > 0:
                return float(row.iloc[0]["涨跌幅"])

    elif cat.fetch_kind == "hk_index_sina":
        cache_key = "_spot_hk_index"
        df = _get_cached(cache_key)
        if df is None:
            df = _safe_call(ak.stock_hk_index_spot_sina)
            if df is not None:
                _set_cached(cache_key, df)
        if df is not None:
            row = df[df["代码"] == cat.symbol]
            if len(row) > 0:
                return float(row.iloc[0]["涨跌幅"])

    elif cat.fetch_kind == "futures_foreign":
        df = _safe_call(ak.futures_foreign_commodity_realtime, symbol=cat.symbol)
        if df is not None and len(df) > 0:
            return float(df.iloc[0]["涨跌幅"])

    return None


def _supplement_today(bars: list[DailyBar], cat: CategoryDef) -> list[DailyBar]:
    """如果日K最后一根不是今天，用实时接口补上当天数据。"""
    if not bars:
        return bars
    today_str = date.today().strftime("%Y-%m-%d")
    if bars[-1].date >= today_str:
        return bars
    if cat.overnight:
        return bars

    pct = _fetch_spot_pct(cat)
    if pct is not None:
        bars.append(DailyBar(date=today_str, pct_chg=round(pct, 4)))
        logger.debug(f"[finance] supplemented {cat.id} with spot: {today_str} {pct:+.2f}%")
    return bars


def fetch_category(cat: CategoryDef) -> list[DailyBar]:
    """拉取单个品类的历史日线数据。"""
    cache_key = f"cat_{cat.id}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    ak = _get_ak()
    bars: list[DailyBar] = []

    if cat.fetch_kind == "index_sina":
        df = _safe_call(ak.stock_zh_index_daily, symbol=cat.symbol)
        if df is not None and len(df) > 0:
            bars = _price_to_bars(df, "date", "close")

    elif cat.fetch_kind == "gold_sge":
        df = _safe_call(ak.spot_golden_benchmark_sge)
        if df is not None and len(df) > 0:
            bars = _price_to_bars(df, "交易时间", "早盘价")

    elif cat.fetch_kind == "forex_safe":
        cached_fx = _get_cached("_forex_safe_raw")
        if cached_fx is None:
            cached_fx = _safe_call(ak.currency_boc_safe)
            if cached_fx is not None:
                _set_cached("_forex_safe_raw", cached_fx)
        if cached_fx is not None and cat.column in cached_fx.columns:
            bars = _price_to_bars(cached_fx, "日期", cat.column)

    elif cat.fetch_kind == "hk_index_sina":
        df = _safe_call(ak.stock_hk_index_daily_sina, symbol=cat.symbol)
        if df is not None and len(df) > 0:
            bars = _price_to_bars(df, "date", "close")

    elif cat.fetch_kind == "futures_foreign":
        df = _safe_call(ak.futures_foreign_hist, symbol=cat.symbol)
        if df is not None and len(df) > 0:
            bars = _price_to_bars(df, "date", "close")

    elif cat.fetch_kind == "us_stock_sina":
        df = _safe_call(ak.stock_us_daily, symbol=cat.symbol, adjust="")
        if df is not None and len(df) > 0:
            bars = _price_to_bars(df, "date", "close")

    if bars:
        bars = _supplement_today(bars, cat)
        _set_cached(cache_key, bars)
        logger.debug(f"[finance] fetched {cat.id}: {len(bars)} bars, latest={bars[-1].date}")
    else:
        logger.warning(f"[finance] no data for {cat.id}")

    return bars


def fetch_all_categories() -> dict[str, list[DailyBar]]:
    """拉取所有品类数据。"""
    result: dict[str, list[DailyBar]] = {}
    for cat in CATEGORIES:
        bars = fetch_category(cat)
        if bars:
            result[cat.id] = bars
    return result


def fetch_macro(indicator: MacroIndicator) -> MacroDataPoint | None:
    """拉取单个宏观指标的最新数据点。"""
    cache_key = f"macro_{indicator.id}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    ak = _get_ak()
    func = getattr(ak, indicator.func_name, None)
    if func is None:
        logger.warning(f"[finance] akshare has no function {indicator.func_name}")
        return None

    df = _safe_call(func)
    if df is None or len(df) < 2:
        return None

    if indicator.value_col not in df.columns:
        logger.warning(
            f"[finance] {indicator.func_name} missing column '{indicator.value_col}', "
            f"available: {list(df.columns)}"
        )
        return None

    df = df.dropna(subset=[indicator.value_col])
    if len(df) < 2:
        return None

    latest = df.iloc[-1]

    if indicator.prev_col and indicator.prev_col in df.columns:
        prev_value = str(latest[indicator.prev_col])
    else:
        prev_value = str(df.iloc[-2][indicator.value_col])

    point = MacroDataPoint(
        indicator_id=indicator.id,
        name=indicator.name,
        plain_name=indicator.plain_name,
        date_str=str(latest[indicator.date_col]),
        value=str(latest[indicator.value_col]),
        prev_value=prev_value,
    )
    _set_cached(cache_key, point)
    return point


def fetch_all_macros() -> list[MacroDataPoint]:
    """拉取所有宏观指标最新数据。"""
    results = []
    for ind in MACRO_INDICATORS:
        point = fetch_macro(ind)
        if point is not None:
            results.append(point)
    return results
