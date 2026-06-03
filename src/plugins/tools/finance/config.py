"""经济天气 · 配置。"""

from __future__ import annotations

from dataclasses import dataclass, field


N_SIGMA: float = 1.5
LOOKBACK_DAYS: int = 30
CRON_SCHEDULE: str = "30 16 * * 1-5"


@dataclass(frozen=True)
class CategoryDef:
    """品类定义。"""

    id: str
    name: str
    source: str  # akshare 接口路径提示
    fetch_kind: str  # "index_sina" | "gold_sge" | "forex_safe" | "us_stock_sina" | "hk_index_sina" | "futures_foreign"

    # 新浪 A 股指数 / 美股需要的 symbol
    symbol: str = ""
    # 外管局汇率需要的列名
    column: str = ""


CATEGORIES: list[CategoryDef] = [
    # A 股指数 (新浪源)
    CategoryDef("sh_index", "A股·沪指", "stock_zh_index_daily", "index_sina", symbol="sh000001"),
    CategoryDef("sz_index", "A股·深成指", "stock_zh_index_daily", "index_sina", symbol="sz399001"),
    CategoryDef("cy_index", "A股·创业板", "stock_zh_index_daily", "index_sina", symbol="sz399006"),
    # 美股 (新浪源)
    CategoryDef("us_spy", "美股·标普500", "stock_us_daily", "us_stock_sina", symbol="SPY"),
    CategoryDef("us_aapl", "美股·苹果", "stock_us_daily", "us_stock_sina", symbol="AAPL"),
    # 黄金
    CategoryDef("gold", "黄金", "spot_golden_benchmark_sge", "gold_sge"),
    # 港股 (新浪源)
    CategoryDef("hk_hsi", "港股·恒生指数", "stock_hk_index_daily_sina", "hk_index_sina", symbol="HSI"),
    # 原油期货 (新浪源, WTI原油)
    CategoryDef("oil_wti", "原油·WTI", "futures_foreign_hist", "futures_foreign", symbol="CL"),
    # 汇率 (外管局央行中间价)
    CategoryDef("fx_usd", "汇率·美元", "currency_boc_safe", "forex_safe", column="美元"),
    CategoryDef("fx_eur", "汇率·欧元", "currency_boc_safe", "forex_safe", column="欧元"),
    CategoryDef("fx_jpy", "汇率·日元", "currency_boc_safe", "forex_safe", column="日元"),
]


@dataclass(frozen=True)
class MacroIndicator:
    """宏观指标定义。"""

    id: str
    name: str
    plain_name: str  # 大白话名
    func_name: str   # akshare 函数名
    value_col: str   # 数值列名
    date_col: str     # 日期列名
    prev_col: str = ""  # 前值列名（数据自带时直接用，空则取倒数第二行）


MACRO_INDICATORS: list[MacroIndicator] = [
    MacroIndicator("cpi_monthly", "CPI月率", "物价涨跌", "macro_china_cpi_monthly", "今值", "日期", "前值"),
    MacroIndicator("ppi_yearly", "PPI年率", "出厂价涨跌", "macro_china_ppi_yearly", "今值", "日期", "前值"),
    MacroIndicator("lpr", "LPR利率", "房贷利率", "macro_china_lpr", "LPR1Y", "TRADE_DATE"),
]
