"""伤害计算（对齐 OpenRA DamageWarhead.Versus + SpreadDamage.Falloff）。"""

from __future__ import annotations

from .constants import CELL_WDIST
from .repo import WarheadDef


def damage_versus_multiplier(versus: dict[str, int], armor: str) -> int:
    """返回百分比修饰，默认 100。"""
    if not versus:
        return 100
    if armor in versus:
        return int(versus[armor])
    return 100


def spread_falloff_permille(warhead: WarheadDef, dist_wdist: int) -> int:
    """SpreadDamage Falloff 表：距离越远伤害衰减（千分比，1000=100%）。"""
    if not warhead.falloff:
        return 1000
    spread = warhead.spread or CELL_WDIST
    idx = dist_wdist * len(warhead.falloff) // max(1, spread)
    idx = min(idx, len(warhead.falloff) - 1)
    return warhead.falloff[idx]


def calc_damage(
    warhead: WarheadDef,
    armor: str,
    *,
    firepower_percent: int = 100,
    falloff_permille: int = 1000,
) -> int:
    pct = damage_versus_multiplier(warhead.versus, armor)
    dmg = warhead.damage * pct // 100
    dmg = dmg * firepower_percent // 100
    dmg = dmg * falloff_permille // 1000
    return max(0, dmg)
