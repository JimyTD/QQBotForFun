"""AoE3 斗蛐蛐 —— 阵容生成器。

负责兵种池筛选、随机抽取、数量计算。

设计文档：docs/games/aoe3-battle.md §二
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Sequence

from src.plugins.aoe3.models import Unit
from src.plugins.aoe3.repository import UnitRepo

logger = logging.getLogger("aoe3_battle.lineup")

# =====================================================================
# 常量
# =====================================================================
BUDGET = 10000               # 默认资源预算（与 game.py BUDGET_DEFAULT 一致）

# 兵种数量权重（§2.2.3）
SLOT_WEIGHTS = [45, 35, 20]  # 1种45%, 2种35%, 3种20%

# LCM 预算浮动范围（§2.2.4）
LCM_BUDGET_TOLERANCE = 0.3   # ±30%

# 抽兵最大重试次数
MAX_DRAW_RETRIES = 20

# 黑名单：按兵种 id 排除（两种模式统一生效）
# 发现数据异常、表现极端、或不适合斗蛐蛐的兵种直接加 id
BLACKLIST: set[str] = {
    # 作弊单位（Cheat unit）— 数据完全离谱
    "mediocre_bombard",          # 普通射石炮，攻击力 5000，cost 16
    "the_tommynator",            # The Tommynator，攻击力 1200，speed 11
    "learicorn",                 # 独角兽，近战 800
    "leonardos_tank",            # Leonardo's Tank，HP=3

    # 火船 — ROF=0，无限 DPS（自爆单位无法模拟）
    "fire_junk",                 # 火船，ROF=0
    "fire_ship_age_of_empires_iii",  # 火船，ROF=0

    # 假炮 — 攻击力 500，cost 100，严重超模
    "quaker_gun",                # 假炮

    # HP 数据异常（wiki 爬虫缺失，详见 docs/aoe3-data-errata.md）
    "elmetto",                   # 钢盔骑兵，HP=1（应为 ~320）
    "mameluke_age_of_empires_iii",   # 马穆鲁克，HP=1（应为 ~230）
    "sennar_horseman",           # 森纳尔骑兵，HP=1（应为 ~320）
}


# =====================================================================
# 阵容数据
# =====================================================================
@dataclass
class UnitSlot:
    """阵容中的一个兵种槽位。"""
    unit: Unit
    count: int

    @property
    def unit_cost(self) -> int:
        """单个单位的资源消耗。"""
        return sum(self.unit.cost.values())

    @property
    def total_cost(self) -> int:
        """该槽位的总资源消耗。"""
        return self.unit_cost * self.count


@dataclass
class Lineup:
    """一方的阵容（支持多兵种）。"""
    slots: list[UnitSlot]

    @property
    def total_cost(self) -> int:
        """总资源消耗。"""
        return sum(s.total_cost for s in self.slots)

    @property
    def total_pop(self) -> int:
        """总人口。"""
        return sum(s.unit.pop * s.count for s in self.slots)

    @property
    def total_count(self) -> int:
        """总个体数。"""
        return sum(s.count for s in self.slots)

    # ---- 向后兼容：单兵种场景的便捷属性 ----
    @property
    def unit(self) -> Unit:
        """第一个（或唯一）兵种。"""
        return self.slots[0].unit

    @property
    def count(self) -> int:
        """第一个（或唯一）兵种的数量。"""
        return self.slots[0].count

    @property
    def pop(self) -> int:
        """总人口（兼容旧接口）。"""
        return self.total_pop

    @property
    def is_multi(self) -> bool:
        """是否为多兵种阵容。"""
        return len(self.slots) > 1


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


def _is_ship(unit: Unit) -> bool:
    """判断是否为船只。"""
    return "Ship" in unit.type


def _is_villager(unit: Unit) -> bool:
    """判断是否为村民类单位。"""
    return "Villager" in unit.type


def get_bet_pool(repo: UnitRepo) -> list[Unit]:
    """押注模式兵种池。

    规则（§2.2.2）：
    - cost > 0 且 has_attack 且 hp > 0
    - 保留雇佣兵、英雄、宠物
    - 排除建筑马车、船只、村民
    - 排除黑名单中的兵种
    """
    pool = []
    blacklisted = 0
    for u in repo.all_units:
        # 必须有费用和攻击力
        if not u.cost or not u.has_attack:
            continue
        # 排除建筑
        if _is_building(u):
            continue
        # 排除船只
        if _is_ship(u):
            continue
        # 排除村民
        if _is_villager(u):
            continue
        # 必须有 HP
        if u.hp <= 0:
            continue
        # 黑名单
        if u.id in BLACKLIST:
            blacklisted += 1
            continue
        pool.append(u)

    logger.info(
        "押注模式兵种池：%d 个兵种（总 %d，黑名单排除 %d）",
        len(pool), len(repo.all_units), blacklisted,
    )
    return pool


def get_duel_pool(repo: UnitRepo) -> list[Unit]:
    """单挑模式兵种池。

    规则（§2.3）：
    - 所有有攻击力的兵种（含英雄、特殊单位、雇佣兵、宠物）
    - 排除建筑、船只、村民
    - 排除黑名单中的兵种
    """
    pool = []
    blacklisted = 0
    for u in repo.all_units:
        if not u.has_attack:
            continue
        if _is_building(u):
            continue
        if _is_ship(u):
            continue
        if _is_villager(u):
            continue
        if u.hp <= 0:
            continue
        # 黑名单
        if u.id in BLACKLIST:
            blacklisted += 1
            continue
        pool.append(u)

    logger.info(
        "单挑模式兵种池：%d 个兵种（总 %d，黑名单排除 %d）",
        len(pool), len(repo.all_units), blacklisted,
    )
    return pool


# =====================================================================
# 资源分配算法
# =====================================================================

def _unit_cost(unit: Unit) -> int:
    """获取单位总资源消耗。"""
    return sum(unit.cost.values())


def approx_lcm_budget(cost_a: int, cost_b: int, base_budget: int) -> int:
    """近似 LCM 算法（§2.2.4）：让双方资源尽量相等。

    返回调整后的预算（双方共用）。
    """
    ca = max(1, round(cost_a))
    cb = max(1, round(cost_b))

    lcm_val = abs(ca * cb) // math.gcd(ca, cb)

    # LCM 太大 → 退化为基础预算
    if lcm_val > base_budget * (1 + LCM_BUDGET_TOLERANCE):
        return base_budget

    # 取最接近 base_budget 的 LCM 倍数
    n = round(base_budget / lcm_val)
    n = max(1, n)
    actual = n * lcm_val

    # clamp 到 ±30% 范围
    lo = int(base_budget * (1 - LCM_BUDGET_TOLERANCE))
    hi = int(base_budget * (1 + LCM_BUDGET_TOLERANCE))
    actual = max(lo, min(hi, actual))

    return actual


def greedy_fill(budget: int, unit_costs: list[int]) -> list[int]:
    """贪心填充三步法（§2.2.3）：多兵种资源分配。

    输入：总预算 budget，兵种 cost 列表
    输出：每个兵种的数量列表
    """
    n = len(unit_costs)
    if n == 0:
        return []

    # Step 1 — 保底：每种兵各 1 个
    counts = [1] * n
    remaining = budget - sum(unit_costs)
    if remaining < 0:
        # 保底就超预算（不应该发生，抽兵约束应拦截）
        logger.warning("贪心填充：保底超预算！budget=%d, costs=%s", budget, unit_costs)
        return counts

    # Step 2 — 均分：剩余预算均分给每个兵种
    per_budget = remaining // n
    for i in range(n):
        extra = per_budget // unit_costs[i]
        counts[i] += extra

    # Step 3 — 贪心零头：最后的零头逐个加最便宜的兵
    remaining = budget - sum(c * cost for c, cost in zip(counts, unit_costs))
    while remaining > 0:
        best = None
        for i in range(n):
            if unit_costs[i] <= remaining:
                if best is None or unit_costs[i] < unit_costs[best]:
                    best = i
        if best is None:
            break
        counts[best] += 1
        remaining -= unit_costs[best]

    return counts


# =====================================================================
# 阵容生成
# =====================================================================

def _draw_units(
    pool: list[Unit],
    slot_count: int,
    budget: int,
    rng: random.Random,
) -> list[Unit] | None:
    """从池中抽取 slot_count 个不同兵种，满足抽兵约束。

    抽兵约束：各出 1 个的总 cost ≤ 预算。
    返回 None 表示重试次数耗尽。
    """
    for _ in range(MAX_DRAW_RETRIES):
        chosen = rng.sample(pool, min(slot_count, len(pool)))
        total_min_cost = sum(_unit_cost(u) for u in chosen)
        if total_min_cost <= budget:
            return chosen
    return None


def _generate_side_lineup(
    pool: list[Unit],
    budget: int,
    rng: random.Random,
) -> Lineup:
    """为一方生成阵容（支持 1~3 兵种）。"""
    # 抽兵种数
    slot_count = rng.choices([1, 2, 3], weights=SLOT_WEIGHTS, k=1)[0]

    # 确保池子够大
    slot_count = min(slot_count, len(pool))

    # 抽兵种（带约束）
    chosen = _draw_units(pool, slot_count, budget, rng)
    if chosen is None:
        # 约束满足不了，降级到 1 个兵种
        logger.warning("抽兵约束多次失败，降级为单兵种。budget=%d", budget)
        chosen = [rng.choice(pool)]

    # 分配数量
    costs = [_unit_cost(u) for u in chosen]

    if len(chosen) == 1:
        # 单兵种：简单除法
        count = max(1, budget // costs[0])
        slots = [UnitSlot(unit=chosen[0], count=count)]
    else:
        # 多兵种：贪心填充
        counts = greedy_fill(budget, costs)
        slots = [UnitSlot(unit=u, count=c) for u, c in zip(chosen, counts)]

    lineup = Lineup(slots=slots)

    logger.info(
        "阵容生成：%d 兵种，总花费 %d/%d (浪费 %d)，总人数 %d",
        len(slots), lineup.total_cost, budget,
        budget - lineup.total_cost, lineup.total_count,
    )
    for s in slots:
        logger.debug("  %s ×%d (cost=%d, 小计=%d)", s.unit.name, s.count, s.unit_cost, s.total_cost)

    return lineup


def generate_bet_lineup(
    repo: UnitRepo,
    *,
    budget: int = BUDGET,
    rng: random.Random | None = None,
) -> MatchLineup:
    """生成押注模式阵容（v2 复合阵容）。

    规则（§2.2.3）：
    - 红蓝双方各独立生成 1~3 个兵种的阵容
    - 单兵种 vs 单兵种时使用 LCM 算法平衡资源
    - 多兵种时使用贪心填充
    """
    if rng is None:
        rng = random.Random()

    pool = get_bet_pool(repo)
    if len(pool) < 2:
        raise ValueError(f"兵种池不足：仅 {len(pool)} 个兵种")

    # 红蓝双方独立生成
    red = _generate_side_lineup(pool, budget, rng)
    blue = _generate_side_lineup(pool, budget, rng)

    # 如果双方都是单兵种，使用 LCM 算法平衡资源
    if not red.is_multi and not blue.is_multi:
        cost_a = red.slots[0].unit_cost
        cost_b = blue.slots[0].unit_cost
        lcm_budget = approx_lcm_budget(cost_a, cost_b, budget)

        red.slots[0] = UnitSlot(
            unit=red.slots[0].unit,
            count=max(1, lcm_budget // cost_a),
        )
        blue.slots[0] = UnitSlot(
            unit=blue.slots[0].unit,
            count=max(1, lcm_budget // cost_b),
        )

        logger.info(
            "LCM 平衡：预算 %d → %d，🔴 %s ×%d (%d) vs 🔵 %s ×%d (%d) 差=%d",
            budget, lcm_budget,
            red.unit.name, red.count, red.total_cost,
            blue.unit.name, blue.count, blue.total_cost,
            abs(red.total_cost - blue.total_cost),
        )

    logger.info(
        "押注阵容最终：🔴 %s (cost=%d, pop=%d) vs 🔵 %s (cost=%d, pop=%d)",
        " + ".join(f"{s.unit.name}×{s.count}" for s in red.slots),
        red.total_cost, red.total_pop,
        " + ".join(f"{s.unit.name}×{s.count}" for s in blue.slots),
        blue.total_cost, blue.total_pop,
    )

    return MatchLineup(red=red, blue=blue, mode="bet")


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

    logger.info(
        "单挑阵容生成：🔴 %s (HP=%d) vs 🔵 %s (HP=%d)",
        red_unit.name, red_unit.hp,
        blue_unit.name, blue_unit.hp,
    )

    return MatchLineup(
        red=Lineup(slots=[UnitSlot(unit=red_unit, count=1)]),
        blue=Lineup(slots=[UnitSlot(unit=blue_unit, count=1)]),
        mode="duel",
    )


# =====================================================================
# 面板文本生成
# =====================================================================

def _atk_summary(u: Unit) -> str:
    """一行压缩攻击信息。"""
    parts = []
    _dtype_label = {"Siege": "攻城伤害", "Hand": "近战伤害"}

    if u.attack_ranged:
        rng_str = f"射程{u.range}"
        if u.range_min:
            rng_str = f"射程{u.range_min}-{u.range}"
        dtype_tag = ""
        if u.damage_type_ranged and u.damage_type_ranged != "Ranged":
            dtype_tag = f",{_dtype_label.get(u.damage_type_ranged, u.damage_type_ranged)}"
        parts.append(f"远程{u.attack_ranged:.0f}({rng_str}, {u.rof_ranged}s{dtype_tag})")
    if u.attack_melee:
        dtype_tag = ""
        if u.damage_type_melee and u.damage_type_melee != "Hand":
            dtype_tag = f",{_dtype_label.get(u.damage_type_melee, u.damage_type_melee)}"
        parts.append(f"近战{u.attack_melee:.0f}({u.rof_melee}s{dtype_tag})")
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
    emoji = "🔴" if side == "red" else "🔵"
    label = "1号" if side == "red" else "2号"

    lines: list[str] = []

    if mode == "duel":
        # 单挑模式：简洁
        lines.append(f"{emoji} {label} · {lineup.unit.name}")
        u = lineup.unit
        lines.append(f"类型：{_type_str_zh(u)}")
        lines.append(f"❤️{u.hp} 🦶{u.speed}")
        lines.append(f"⚔️ {_atk_summary(u)}")
        _append_extras(lines, u)

    elif not lineup.is_multi:
        # 单兵种押注模式：紧凑
        lines.append(f"{emoji} {label} · {lineup.unit.name} ×{lineup.count}")
        u = lineup.unit
        lines.append(f"类型：{_type_str_zh(u)}")
        lines.append(f"💰总资源 {lineup.total_cost}")
        lines.append(f"❤️{u.hp} 🦶{u.speed}")
        lines.append(f"⚔️ {_atk_summary(u)}")
        _append_extras(lines, u)

    else:
        # 多兵种押注模式：每个兵种一段
        lines.append(f"{emoji} {label}（总资源 {lineup.total_cost}，人口 {lineup.total_pop}）")
        for slot in lineup.slots:
            u = slot.unit
            lines.append(f"  {'─' * 20}")
            lines.append(f"  {u.name} ×{slot.count}")
            lines.append(f"  类型：{_type_str_zh(u)}")
            lines.append(f"  ❤️{u.hp} 🦶{u.speed}")
            lines.append(f"  ⚔️ {_atk_summary(u)}")
            _append_extras(lines, u, indent="  ")

    return "\n".join(lines)


def _append_extras(lines: list[str], u: Unit, indent: str = "") -> None:
    """追加抗性 + AOE 信息行。"""
    extras = []
    armor = _armor_str(u)
    if armor:
        extras.append(f"🛡️{armor}")
    aoe_parts = []
    if u.aoe_radius_ranged:
        aoe_parts.append(f"远程AOE{u.aoe_radius_ranged}")
    if u.aoe_radius_melee:
        aoe_parts.append(f"近战AOE{u.aoe_radius_melee}")
    if u.aoe_radius_siege:
        aoe_parts.append(f"攻城AOE{u.aoe_radius_siege}")
    if aoe_parts:
        extras.append("💥" + " ".join(aoe_parts))
    elif u.aoe_radius:
        extras.append(f"💥AOE{u.aoe_radius}")
    if extras:
        lines.append(f"{indent}{' '.join(extras)}")


def format_vs_banner(lineup: MatchLineup) -> str:
    """生成 VS 总览 + 押注提示（第三条消息）。"""
    r = lineup.red
    b = lineup.blue

    if lineup.mode == "duel":
        title = "⚔️ 帝国3斗蛐蛐 · 单挑"
        red_str = f"🔴 {r.unit.name}"
        blue_str = f"🔵 {b.unit.name}"
    elif r.is_multi or b.is_multi:
        title = "⚔️ 帝国3斗蛐蛐"
        red_parts = "+".join(f"{s.count}{s.unit.name}" for s in r.slots)
        blue_parts = "+".join(f"{s.count}{s.unit.name}" for s in b.slots)
        red_str = f"🔴 [{red_parts}]"
        blue_str = f"🔵 [{blue_parts}]"
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


def _unit_emoji(unit) -> str:
    """根据兵种类型返回对应 emoji。"""
    tags = set(unit.type) if unit.type else set()
    # 按优先级匹配
    if tags & {"Ship", "War ship", "Fishing boat", "Recruiting ship"}:
        return "⛵"
    if tags & {"Artillery", "Siege trooper", "Artillery trooper"}:
        return "💣"
    if tags & {"Elephant"}:
        return "🐘"
    if tags & {"Camel"}:
        return "🐫"
    if tags & {"Cavalry", "Heavy cavalry", "Hand cavalry", "Ranged cavalry",
               "Light ranged cavalry", "Gunpowder cavalry", "Lance cavalry",
               "Ranged heavy cavalry"}:
        return "🐴"
    if tags & {"Archer", "Foot archer"}:
        return "🏹"
    if tags & {"Gunpowder trooper", "Gunpowder unit", "Musket infantry",
               "Rifle infantry"}:
        return "🔫"
    if tags & {"Pikeman"}:
        return "🗡️"
    if tags & {"Monk", "Healing unit"}:
        return "✝️"
    if tags & {"Hero"}:
        return "👑"
    if tags & {"Pet"}:
        return "🐾"
    if tags & {"Mercenary", "Outlaw", "MercType1", "MercType2"}:
        return "💰"
    if tags & {"Villager"}:
        return "👷"
    if tags & {"Infantry", "Hand infantry", "Heavy infantry", "Light infantry",
               "Shock infantry", "Hand shock infantry", "Ranged infantry",
               "Ranged shock infantry", "Grenade trooper", "Counter-skirmisher",
               "Hand skirmisher", "Archaic infantry", "Native warrior"}:
        return "⚔️"
    return "■"


def format_formation_panel(lineup: MatchLineup) -> str:
    """生成双方阵型排布面板文本（群聊开战前发送）。"""
    from .simulator import (
        ArmySlot as SimSlot,
        FormationRow,
        Side,
        compute_formation_rows,
    )

    def _format_row(row: FormationRow, num_rows: int) -> str:
        icons = ""
        for unit, count in row.slots:
            icons += _unit_emoji(unit) * count
        tag = "前排" if row.row_index == 0 else (
            "后排" if row.row_index == num_rows - 1 and num_rows > 2
            else ""
        )
        desc = row.label
        tag_str = f" ← {tag}" if tag else ""
        return f"  {row.row_index + 1}排 [{icons}] {desc}{tag_str}"

    def _side_text(
        side_lineup: Lineup,
        side: Side,
        emoji: str,
        label: str,
        reverse: bool = False,
    ) -> str:
        sim_army = [SimSlot(s.unit, s.count) for s in side_lineup.slots]
        rows: list[FormationRow] = compute_formation_rows(sim_army, side)
        num_rows = len(rows)

        lines: list[str] = []
        lines.append(f"{emoji} {label}阵型（{side_lineup.total_count}人，{num_rows}排）")

        display_rows = list(reversed(rows)) if reverse else rows
        for row in display_rows:
            lines.append(_format_row(row, num_rows))

        return "\n".join(lines)

    # 红方倒序（后排在上，前排靠近空地）
    # 蓝方正序（前排靠近空地，后排在下）
    red_text = _side_text(lineup.red, Side.RED, "🔴", "红方", reverse=True)
    blue_text = _side_text(lineup.blue, Side.BLUE, "🔵", "蓝方", reverse=False)

    gap = "      ─── 空地 ───"
    return f"{red_text}\n{gap}\n{blue_text}"
