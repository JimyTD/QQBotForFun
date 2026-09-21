"""AoE3 斗蛐蛐指定兵种参数解析（无 NoneBot 依赖）。"""

from __future__ import annotations

import re

_CUSTOM_UNIT_COUNT_MAX = 1000
_AGE_TOKEN_RE = re.compile(
    r"^(?:(\d)\s*时代|时代\s*(\d)|age\s*(\d))$",
    re.IGNORECASE,
)


def extract_age(parts: list[str]) -> tuple[int | None, list[str]]:
    """从分词里抽出时代参数，返回 (age, 去掉时代词后的分词)。"""
    age: int | None = None
    rest: list[str] = []
    for part in parts:
        match = _AGE_TOKEN_RE.match(part)
        if match:
            value = int(next(group for group in match.groups() if group))
            if 2 <= value <= 5:
                age = value
                continue
        rest.append(part)
    return age, rest


def parse_custom_battle_args(
    parts: list[str],
) -> tuple[list[str], list[int] | None, int | None, str | None]:
    """解析自选参数，返回 (兵种, 固定数量, 预算, 错误)。

    固定数量仅在两个兵种都紧邻整数时启用：
      ``兵种A 100 兵种B 50``

    兼容旧格式：
      ``兵种A 兵种B 10000``
      ``兵种A 10000``
    后者仍是预算，不是数量。
    """
    if not parts:
        return [], None, None, "⚠️ 请至少指定一个兵种名"

    # 旧格式：单个兵种 + 数字，数字始终是预算。
    if (
        len(parts) == 2
        and not parts[0].isdigit()
        and parts[1].isdigit()
    ):
        return [parts[0]], None, int(parts[1]), None

    # 旧格式：两个兵种 + 末尾单个数字，数字仍是预算。
    if (
        len(parts) == 3
        and not parts[0].isdigit()
        and not parts[1].isdigit()
        and parts[2].isdigit()
    ):
        return [parts[0], parts[1]], None, int(parts[2]), None

    # 固定数量格式必须严格为 兵种A 数量 兵种B 数量。
    has_any_digit = any(part.isdigit() for part in parts)
    if has_any_digit:
        if len(parts) % 2 != 0:
            return (
                [],
                None,
                None,
                "⚠️ 固定数量格式需为：兵种A 数量 兵种B 数量",
            )

        unit_names: list[str] = []
        unit_counts: list[int] = []
        for idx in range(0, len(parts), 2):
            name = parts[idx]
            count_str = parts[idx + 1]
            if name.isdigit() or not count_str.isdigit():
                return (
                    [],
                    None,
                    None,
                    "⚠️ 固定数量格式需为：兵种A 数量 兵种B 数量",
                )
            count = int(count_str)
            if not 1 <= count <= _CUSTOM_UNIT_COUNT_MAX:
                return (
                    [],
                    None,
                    None,
                    f"⚠️ 数量必须是 1~{_CUSTOM_UNIT_COUNT_MAX} 的整数",
                )
            unit_names.append(name)
            unit_counts.append(count)

        if len(unit_names) > 2:
            return [], None, None, "⚠️ 最多选 2 个兵种"
        if len(set(unit_names)) != len(unit_names):
            return [], None, None, "⚠️ 固定数量模式需指定两个不同兵种"
        if len(unit_names) != 2:
            return (
                [],
                None,
                None,
                "⚠️ 固定数量格式需为：兵种A 数量 兵种B 数量",
            )
        return unit_names, unit_counts, None, None

    unit_names = list(parts)
    if len(unit_names) > 2:
        return [], None, None, "⚠️ 最多选 2 个兵种"
    return unit_names, None, None, None
