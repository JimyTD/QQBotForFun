"""AoE3 斗蛐蛐 —— 阵容生成器。

负责兵种池筛选、随机抽取、数量计算。

设计文档：docs/games/aoe3-battle.md §二
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Sequence

from src.plugins.aoe3.models import Unit
from src.plugins.aoe3.repository import UnitRepo

logger = logging.getLogger("aoe3_battle.lineup")

# =====================================================================
# 常量
# =====================================================================
BUDGET = 1000                # 资源预算


# =====================================================================
# 阵容数据
# =====================================================================
@dataclass
class Lineup:
    """一方的阵容。"""
    unit: Unit
    count: int
    total_cost: int            # 实际总资源
    pop: int                   # 总人口

    @property
    def unit_cost(self) -> int:
        """单个单位的资源消耗。"""
        return sum(self.unit.cost.values())


@dataclass
class MatchLineup:
    """一局对阵的双方阵容。"""
    red: Lineup
    blue: Lineup
    mode: str                  # "bet" | "duel"


# =====================================================================
# 兵种池筛选
# =====================================================================
def _is_building(unit: Unit) -> bool:
    """判断是否为建筑（排除建筑马车等）。"""
    type_lower = {t.lower() for t in unit.type}
    building_keywords = {"building", "wagon", "rickshaw"}
    return bool(type_lower & building_keywords)


def _is_hero(unit: Unit) -> bool:
    """判断是否为英雄。"""
    return "Hero" in unit.type


def _is_pet(unit: Unit) -> bool:
    """判断是否为宠物。"""
    type_lower = {t.lower() for t in unit.type}
    return "pet" in type_lower or "guardian" in type_lower


def get_bet_pool(repo: UnitRepo) -> list[Unit]:
    """押注模式兵种池。

    规则（§2.2.2）：
    - is_trainable=True 且 cost > 0
    - 保留战舰、雇佣兵
    - 排除建筑马车、英雄、宠物
    """
    pool = []
    for u in repo.all_units:
        # 必须有费用和攻击力
        if not u.cost or not u.has_attack:
            continue
        # 排除英雄
        if _is_hero(u):
            continue
        # 排除宠物
        if _is_pet(u):
            continue
        # 排除建筑
        if _is_building(u):
            continue
        # 必须有 HP
        if u.hp <= 0:
            continue
        pool.append(u)

    logger.info("押注模式兵种池：%d 个兵种（总 %d）", len(pool), len(repo.all_units))
    return pool


def get_duel_pool(repo: UnitRepo) -> list[Unit]:
    """单挑模式兵种池。

    规则（§2.3）：
    - 所有有攻击力的兵种（含英雄、特殊单位、雇佣兵、村民、宠物）
    - 排除建筑
    """
    pool = []
    for u in repo.all_units:
        if not u.has_attack:
            continue
        if _is_building(u):
            continue
        if u.hp <= 0:
            continue
        pool.append(u)

    logger.info("单挑模式兵种池：%d 个兵种（总 %d）", len(pool), len(repo.all_units))
    return pool


# =====================================================================
# 阵容生成
# =====================================================================
def _calc_count(unit: Unit, budget: int) -> int:
    """计算兵种数量 = round(预算 / 单位资源)，最少 1。"""
    unit_cost = sum(unit.cost.values())
    if unit_cost <= 0:
        return 1
    count = round(budget / unit_cost)
    return max(1, count)


def generate_bet_lineup(
    repo: UnitRepo,
    *,
    budget: int = BUDGET,
    rng: random.Random | None = None,
) -> MatchLineup:
    """生成押注模式阵容。

    规则（§2.2.1）：
    - 红蓝各随机抽 1 个兵种
    - 数量按资源预算算
    - 不强制重抽，随机到什么就用什么
    """
    if rng is None:
        rng = random.Random()

    pool = get_bet_pool(repo)
    if len(pool) < 2:
        raise ValueError(f"兵种池不足：仅 {len(pool)} 个兵种")

    # 随机抽两个不同兵种
    red_unit, blue_unit = rng.sample(pool, 2)

    red_count = _calc_count(red_unit, budget)
    blue_count = _calc_count(blue_unit, budget)

    red_cost = sum(red_unit.cost.values()) * red_count
    blue_cost = sum(blue_unit.cost.values()) * blue_count

    logger.info(
        "押注阵容生成：🔴 %s ×%d (cost=%d) vs 🔵 %s ×%d (cost=%d) 差异=%d",
        red_unit.name, red_count, red_cost,
        blue_unit.name, blue_count, blue_cost,
        abs(red_cost - blue_cost),
    )

    return MatchLineup(
        red=Lineup(
            unit=red_unit,
            count=red_count,
            total_cost=red_cost,
            pop=red_unit.pop * red_count,
        ),
        blue=Lineup(
            unit=blue_unit,
            count=blue_count,
            total_cost=blue_cost,
            pop=blue_unit.pop * blue_count,
        ),
        mode="bet",
    )


def generate_duel_lineup(
    repo: UnitRepo,
    *,
    rng: random.Random | None = None,
) -> MatchLineup:
    """生成单挑模式阵容。

    规则（§2.3）：
    - 两边各 1 个兵种，各 1 个单位
    - 不考虑资源平衡
    """
    if rng is None:
        rng = random.Random()

    pool = get_duel_pool(repo)
    if len(pool) < 2:
        raise ValueError(f"兵种池不足：仅 {len(pool)} 个兵种")

    red_unit, blue_unit = rng.sample(pool, 2)

    red_cost = sum(red_unit.cost.values()) if red_unit.cost else 0
    blue_cost = sum(blue_unit.cost.values()) if blue_unit.cost else 0

    logger.info(
        "单挑阵容生成：🔴 %s (HP=%d) vs 🔵 %s (HP=%d)",
        red_unit.name, red_unit.hp,
        blue_unit.name, blue_unit.hp,
    )

    return MatchLineup(
        red=Lineup(
            unit=red_unit,
            count=1,
            total_cost=red_cost,
            pop=red_unit.pop,
        ),
        blue=Lineup(
            unit=blue_unit,
            count=1,
            total_cost=blue_cost,
            pop=blue_unit.pop,
        ),
        mode="duel",
    )


# =====================================================================
# 面板文本生成
# =====================================================================

def _atk_summary(u: Unit) -> str:
    """一行压缩攻击信息。"""
    parts = []
    if u.attack_ranged:
        rng_str = f"射程{u.range}"
        if u.range_min:
            rng_str = f"射程{u.range_min}-{u.range}"
        parts.append(f"远程{u.attack_ranged:.0f}({rng_str}, {u.rof_ranged}s)")
    if u.attack_melee:
        parts.append(f"近战{u.attack_melee:.0f}({u.rof_melee}s)")
    if u.attack_siege and not u.attack_ranged:
        parts.append(f"攻城{u.attack_siege:.0f}")
    return " | ".join(parts) if parts else "无攻击"


def _armor_str(u: Unit) -> str:
    """抗性摘要。"""
    parts = []
    if u.armor_ranged:
        parts.append(f"远防{u.armor_ranged:.0%}")
    if u.armor_melee:
        parts.append(f"近防{u.armor_melee:.0%}")
    return " ".join(parts)


def _type_str_zh(u: Unit) -> str:
    """兵种类型中文翻译（精简版，去掉冗余标签）。"""
    from src.plugins.aoe3.i18n import t

    # 过滤掉不太有用的标签
    skip = {"Affected by villager upgrades", "MercType1", "MercType2",
            "Cheat unit", "stealth"}
    types_zh = []
    for tp in u.type:
        if tp in skip:
            continue
        zh = t("type", tp)
        if zh not in types_zh:
            types_zh.append(zh)
    return " / ".join(types_zh) if types_zh else "未知"


def format_side_panel(
    lineup: Lineup, side: str, mode: str
) -> str:
    """生成单方的详情面板文本（配合 icon 图片发送）。

    side: "red" | "blue"
    """
    u = lineup.unit
    emoji = "🔴" if side == "red" else "🔵"
    label = "1号" if side == "red" else "2号"

    if mode == "duel":
        header = f"{emoji} {label} · {u.name}"
    else:
        header = f"{emoji} {label} · {u.name} ×{lineup.count}"

    lines = [header]
    lines.append(f"类型：{_type_str_zh(u)}")

    # 核心属性一行
    stat_parts = [f"❤️{u.hp}", f"🦶{u.speed}"]
    if mode != "duel":
        lines.append(f"💰总资源 {lineup.total_cost}")
    lines.append(" ".join(stat_parts))

    # 攻击
    lines.append(f"⚔️ {_atk_summary(u)}")

    # 抗性 + AOE
    extras = []
    armor = _armor_str(u)
    if armor:
        extras.append(f"🛡️{armor}")
    if u.aoe_radius:
        extras.append(f"💥AOE半径{u.aoe_radius}")
    if extras:
        lines.append(" ".join(extras))

    return "\n".join(lines)


def format_vs_banner(lineup: MatchLineup) -> str:
    """生成 VS 总览 + 押注提示（第三条消息）。"""
    r = lineup.red
    b = lineup.blue

    if lineup.mode == "duel":
        title = "⚔️ 帝国3斗蛐蛐 · 单挑"
        red_str = f"🔴 {r.unit.name}"
        blue_str = f"🔵 {b.unit.name}"
    else:
        title = "⚔️ 帝国3斗蛐蛐"
        red_str = f"🔴 {r.unit.name} ×{r.count}"
        blue_str = f"🔵 {b.unit.name} ×{b.count}"

    lines = [
        title,
        f"{red_str}  VS  {blue_str}",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "@ 1 押红方 | @ 2 押蓝方",
        "入场券 5 金币 · @ 开战 直接开打",
    ]
    return "\n".join(lines)


def format_matchup_panel(lineup: MatchLineup) -> str:
    """兼容旧接口：生成完整对阵面板纯文本（CLI 等场景使用）。"""
    parts = []
    parts.append(format_side_panel(lineup.red, "red", lineup.mode))
    parts.append("")
    parts.append(format_side_panel(lineup.blue, "blue", lineup.mode))
    parts.append("")
    parts.append(format_vs_banner(lineup))
    return "\n".join(parts)
