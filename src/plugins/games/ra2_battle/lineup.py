"""红警2斗蛐蛐 —— 阵容生成与对阵面板。"""



from __future__ import annotations



import logging

import math

import random

from dataclasses import dataclass, field



from .display import (
    display_name,
    format_attack_summary,
    format_description_blurb,
    format_unit_role,
)
from .locale import localized_actor_name
from .battle_pool import is_lineup_eligible, lineup_eligible_actors

from .repo import ActorDef, load_actors, load_battle_pool_actors



logger = logging.getLogger("ra2_battle.lineup")



BUDGET_DEFAULT = 5000

BUDGET_MIN = 500

BUDGET_MAX = 50000

# 单方兵种数：1 种 / 2 种 各 50%（不再随机 3 种）

SLOT_WEIGHTS = [50, 50]

LCM_BUDGET_TOLERANCE = 0.3

MAX_DRAW_RETRIES = 30

INITIAL_STAR_OPTIONS = (0, 1, 3)





def roll_initial_stars(rng: random.Random) -> int:

    """本局出战星级：0=无军衔，1=老兵，3=精英；红蓝相同。"""

    return rng.choice(INITIAL_STAR_OPTIONS)





def format_stars_label(stars: int) -> str:

    if stars == 0:

        return "无星（新兵）"

    if stars == 1:

        return "★ 一星"

    if stars == 3:

        return "★★★ 三星"

    return f"星{stars}"





@dataclass

class UnitSlot:

    actor_id: str

    name: str

    count: int

    unit_cost: int



    @property

    def total_cost(self) -> int:

        return self.unit_cost * self.count





@dataclass

class SideLineup:

    slots: list[UnitSlot] = field(default_factory=list)



    @property

    def total_cost(self) -> int:

        return sum(s.total_cost for s in self.slots)



    @property

    def total_count(self) -> int:

        return sum(s.count for s in self.slots)



    @property

    def is_multi(self) -> bool:

        return len(self.slots) > 1



    @property

    def single_actor(self) -> ActorDef | None:

        if len(self.slots) != 1:

            return None

        return load_actors().get(self.slots[0].actor_id)





@dataclass

class MatchLineup:

    red: SideLineup

    blue: SideLineup

    mode: str = "bet"

    budget: int = BUDGET_DEFAULT

    initial_stars: int = 0





def _battle_pool(actors: dict[str, ActorDef]) -> list[ActorDef]:

    return lineup_eligible_actors(actors)





def approx_lcm_budget(cost_a: int, cost_b: int, base_budget: int) -> int:

    """近似 LCM：单兵种对单兵种时让双方总造价接近（对齐帝国斗蛐蛐）。"""

    ca = max(1, round(cost_a))

    cb = max(1, round(cost_b))

    lcm_val = abs(ca * cb) // math.gcd(ca, cb)

    if lcm_val > base_budget * (1 + LCM_BUDGET_TOLERANCE):

        return base_budget

    n = max(1, round(base_budget / lcm_val))

    actual = n * lcm_val

    lo = int(base_budget * (1 - LCM_BUDGET_TOLERANCE))

    hi = int(base_budget * (1 + LCM_BUDGET_TOLERANCE))

    return max(lo, min(hi, actual))





def greedy_fill(budget: int, unit_costs: list[int]) -> list[int]:

    """多兵种：每种保底 1，剩余预算均分 + 零头贪最便宜。"""

    n = len(unit_costs)

    if n == 0:

        return []

    counts = [1] * n

    remaining = budget - sum(unit_costs)

    if remaining < 0:

        logger.warning("贪心填充超预算 budget=%d costs=%s", budget, unit_costs)

        return counts

    per_budget = remaining // n

    for i in range(n):

        counts[i] += per_budget // unit_costs[i]

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





def _pick_slot_count(rng: random.Random) -> int:

    return rng.choices([1, 2], weights=SLOT_WEIGHTS, k=1)[0]





def _draw_units(

    pool: list[ActorDef],

    slot_count: int,

    budget: int,

    rng: random.Random,

) -> list[ActorDef] | None:

    for _ in range(MAX_DRAW_RETRIES):

        chosen = rng.sample(pool, min(slot_count, len(pool)))

        if sum(a.cost for a in chosen) <= budget:

            return chosen

    return None





def _generate_side_lineup(

    pool: list[ActorDef],

    budget: int,

    rng: random.Random,

) -> SideLineup:

    slot_count = min(_pick_slot_count(rng), len(pool))

    chosen = _draw_units(pool, slot_count, budget, rng)

    if chosen is None:

        logger.warning("抽兵约束失败，降级单兵种 budget=%d", budget)

        chosen = [rng.choice(pool)]



    costs = [a.cost for a in chosen]

    if len(chosen) == 1:

        count = max(1, budget // costs[0])

        a0 = chosen[0]
        slots = [UnitSlot(a0.id, display_name(a0), count, costs[0])]

    else:

        counts = greedy_fill(budget, costs)

        slots = [
            UnitSlot(a.id, display_name(a), c, a.cost)
            for a, c in zip(chosen, counts)
        ]



    lineup = SideLineup(slots=slots)

    logger.info(

        "单方阵容：%d 兵种 花费 %d/%d 共 %d 单位",

        len(slots),

        lineup.total_cost,

        budget,

        lineup.total_count,

    )

    return lineup





def _apply_lcm_single_vs_single(

    red: SideLineup,

    blue: SideLineup,

    budget: int,

) -> tuple[SideLineup, SideLineup, int]:

    cost_a = red.slots[0].unit_cost

    cost_b = blue.slots[0].unit_cost

    lcm_budget = approx_lcm_budget(cost_a, cost_b, budget)

    red.slots[0] = UnitSlot(

        red.slots[0].actor_id,

        red.slots[0].name,

        max(1, lcm_budget // cost_a),

        cost_a,

    )

    blue.slots[0] = UnitSlot(

        blue.slots[0].actor_id,

        blue.slots[0].name,

        max(1, lcm_budget // cost_b),

        cost_b,

    )

    logger.info(

        "LCM 平衡：预算 %d → %d，🔴 %s×%d($%d) vs 🔵 %s×%d($%d) 差=$%d",

        budget,

        lcm_budget,

        red.slots[0].name,

        red.slots[0].count,

        red.total_cost,

        blue.slots[0].name,

        blue.slots[0].count,

        blue.total_cost,

        abs(red.total_cost - blue.total_cost),

    )

    return red, blue, lcm_budget





def generate_bet_lineup(

    *,

    budget: int = BUDGET_DEFAULT,

    rng: random.Random | None = None,

    seed: int | None = None,

) -> MatchLineup:

    rng = rng or random.Random(seed)

    actors = load_actors()

    pool = _battle_pool(actors)

    if len(pool) < 2:

        raise RuntimeError("斗蛐蛐池单位不足，请先运行 openra_ra2_export.py")



    initial_stars = roll_initial_stars(rng)
    red = _generate_side_lineup(pool, budget, rng)
    blue = _generate_side_lineup(pool, budget, rng)
    effective_budget = budget
    if not red.is_multi and not blue.is_multi:
        red, blue, effective_budget = _apply_lcm_single_vs_single(red, blue, budget)
    return MatchLineup(
        red=red,
        blue=blue,
        mode="bet",
        budget=effective_budget,
        initial_stars=initial_stars,
    )





def generate_duel_lineup(

    rng: random.Random | None = None,

    seed: int | None = None,

) -> MatchLineup:

    rng = rng or random.Random(seed)

    pool = _battle_pool(load_battle_pool_actors())

    a, b = rng.sample(pool, 2)

    initial_stars = roll_initial_stars(rng)

    return MatchLineup(

        red=SideLineup([UnitSlot(a.id, display_name(a), 1, a.cost)]),

        blue=SideLineup([UnitSlot(b.id, display_name(b), 1, b.cost)]),

        mode="duel",

        budget=0,

        initial_stars=initial_stars,

    )





def _format_one_unit(actor: ActorDef, count: int, indent: str = "") -> list[str]:

    lines: list[str] = []

    lines.append(f"{indent}❤️{actor.hp} 🦶{actor.speed} 💰{actor.cost}")

    lines.append(f"{indent}⚔️ {format_attack_summary(actor)}")

    lines.append(f"{indent}📋 {format_unit_role(actor)}")

    blurb = format_description_blurb(actor)

    if blurb:

        lines.append(f"{indent}💬 {blurb}")

    return lines





def format_side_panel(

    side: SideLineup,

    color: str,

    mode: str,

    *,

    initial_stars: int = 0,

) -> str:

    """单方详情（结构对齐帝国斗蛐蛐，内容为红警 OpenRA 数据）。"""

    emoji = "🔴" if color == "red" else "🔵"

    label = "1号" if color == "red" else "2号"

    star_tag = format_stars_label(initial_stars)

    actors = load_actors()

    lines: list[str] = []



    if mode == "duel" and len(side.slots) == 1:

        s = side.slots[0]

        actor = actors.get(s.actor_id)

        show = localized_actor_name(s.actor_id, s.name) if actor else s.name
        lines.append(f"{emoji} {label} · {show} · {star_tag}")

        if actor:

            lines.extend(_format_one_unit(actor, 1))

        return "\n".join(lines)



    if len(side.slots) == 1:

        s = side.slots[0]

        actor = actors.get(s.actor_id)

        show = localized_actor_name(s.actor_id, s.name) if actor else s.name
        lines.append(f"{emoji} {label} · {show} ×{s.count} · {star_tag}")

        if actor:

            lines.append(f"💰总造价 ${side.total_cost}")

            lines.extend(_format_one_unit(actor, s.count))

        return "\n".join(lines)



    lines.append(

        f"{emoji} {label}（总造价 ${side.total_cost}，共 {side.total_count} 单位）· {star_tag}"

    )

    for s in side.slots:

        actor = actors.get(s.actor_id)

        lines.append(f"  {'─' * 18}")

        show = localized_actor_name(s.actor_id, s.name)
        lines.append(f"  {show} ×{s.count}  (${s.unit_cost}×{s.count})")

        if actor:

            lines.extend(_format_one_unit(actor, s.count, indent="  "))

    return "\n".join(lines)





def format_vs_banner(match: MatchLineup) -> str:

    """VS 总览 + 押注提示（话术对齐帝国斗蛐蛐）。"""

    r, b = match.red, match.blue

    star_line = f"⭐ 本局出战：{format_stars_label(match.initial_stars)}（红蓝相同）"



    if match.mode == "duel":

        title = "⚔️ 红警2斗蛐蛐 · 单挑"

        rs = f"🔴 {r.slots[0].name}" if r.slots else "🔴 ?"

        bs = f"🔵 {b.slots[0].name}" if b.slots else "🔵 ?"

    else:

        title = "⚔️ 红警2斗蛐蛐"

        if r.is_multi or b.is_multi:

            rp = "+".join(f"{s.count}{s.name}" for s in r.slots)

            bp = "+".join(f"{s.count}{s.name}" for s in b.slots)

            rs, bs = f"🔴 [{rp}]", f"🔵 [{bp}]"

        elif r.slots and b.slots:

            rs = f"🔴 {r.slots[0].name} ×{r.slots[0].count}"

            bs = f"🔵 {b.slots[0].name} ×{b.slots[0].count}"

        else:

            rs, bs = "🔴 ?", "🔵 ?"



    lines = [

        title,

        star_line,

        f"{rs}  VS  {bs}",

    ]

    if match.mode == "bet":

        lines.append(f"💰本局造价预算 ${match.budget}")

    lines.extend([

        "━━━━━━━━━━━━━━━━━━━━━━━━",

        "@我 1 / 押注1 押红方 | @我 2 / 押注2 押蓝方",

        "入场券 5 金币 · @我 开战 直接开打",

        "（二维空旷战场 · 数据来自 OpenRA/ra2）",

    ])

    return "\n".join(lines)

