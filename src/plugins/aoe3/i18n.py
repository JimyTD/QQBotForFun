"""AoE3 中英文翻译层 —— 加载 seeds/aoe3/i18n_zh.json，提供翻译函数。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # project root
_I18N_FILE = _ROOT / "seeds" / "aoe3" / "i18n_zh.json"

# 翻译表：{ category: { en: zh } }
_TABLE: dict[str, dict[str, str]] = {}

# 反向表：{ category: { zh_lower: en } }  —— 用于搜索时中文→英文
_REVERSE: dict[str, dict[str, str]] = {}


def _load() -> None:
    """懒加载翻译表。"""
    if _TABLE:
        return
    data: dict[str, Any] = json.loads(_I18N_FILE.read_text(encoding="utf-8"))
    for cat, mapping in data.items():
        if cat.startswith("_"):
            continue
        if isinstance(mapping, dict):
            _TABLE[cat] = mapping
            _REVERSE[cat] = {v.lower(): k for k, v in mapping.items()}


def t(category: str, key: str) -> str:
    """翻译：返回中文，找不到则原样返回英文。

    >>> t("type", "Heavy infantry")
    '重步兵'
    >>> t("type", "UnknownType")
    'UnknownType'
    """
    _load()
    table = _TABLE.get(category, {})
    return table.get(key, key)


def t_list(category: str, keys: list[str]) -> list[str]:
    """批量翻译列表。"""
    return [t(category, k) for k in keys]


def t_age(age_raw: str) -> str:
    """翻译时代字段，处理脏数据（粘连、带星号等）。

    >>> t_age("Commerce AgeFortress Age")
    '殖民时代 / 堡垒时代'
    >>> t_age("Fortress Age*")
    '堡垒时代'
    """
    _load()
    age_table = _TABLE.get("age", {})
    if not age_raw:
        return ""

    # 去星号
    cleaned = age_raw.rstrip("*").strip()

    # 直接命中
    if cleaned in age_table:
        return age_table[cleaned]

    # 处理粘连情况：尝试拆分（如 "Commerce AgeFortress Age"）
    parts: list[str] = []
    remaining = cleaned
    # 按已知时代名从长到短贪心匹配
    known_ages = sorted(age_table.keys(), key=len, reverse=True)
    while remaining:
        matched = False
        for age_en in known_ages:
            if remaining.startswith(age_en):
                parts.append(age_table[age_en])
                remaining = remaining[len(age_en):]
                matched = True
                break
        if not matched:
            # 无法匹配的残余部分原样保留
            parts.append(remaining)
            break

    return " / ".join(parts) if parts else age_raw


def t_mult_vs(vs: str) -> str:
    """翻译倍率目标。"""
    return t("multiplier_vs", vs)


def reverse_lookup(category: str, zh_text: str) -> str | None:
    """中文反查英文，用于搜索。找不到返回 None。

    >>> reverse_lookup("type", "重步兵")
    'Heavy infantry'
    """
    _load()
    rev = _REVERSE.get(category, {})
    return rev.get(zh_text.lower())
