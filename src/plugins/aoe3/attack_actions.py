"""默认阵型里的攻击模式。

一条模式是一整包。蓄力是其中一种：条满了才进候选，打完按冷却退出。
冷却字段缺省或为 0 的蓄力先不自动打出。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Multiplier


@dataclass(frozen=True)
class AttackAction:
    """一个已经绑定整包数值的攻击模式。"""

    name: str
    priority: int
    damage: float
    damage_type: str
    range_min: float
    range_max: float
    rof: float
    enabled: bool = True
    charge: bool = False
    recharge: float = 0.0
    aoe_radius: float = 0.0
    damage_cap: float = 0.0
    num_projectiles: int = 1
    windup: float = 0.0
    area_sort_mode: str = ""
    outer_damage_area_distance: float = 0.0
    outer_damage_area_factor: float = 0.0
    basedamagecap: bool = False
    multipliers: tuple[Multiplier, ...] = ()
    rates: tuple[str, ...] = ()
    hits_soldiers: bool = True
    handlogic: bool = False
    rangedlogic: bool = False


def attack_action_from_dict(raw: dict) -> AttackAction:
    multipliers = tuple(
        Multiplier(vs=item["vs"], value=float(item["value"]))
        for item in raw.get("multipliers") or []
        if item.get("vs")
    )
    return AttackAction(
        name=str(raw.get("name") or ""),
        priority=int(raw.get("priority") or 0),
        damage=float(raw.get("damage") or 0),
        damage_type=str(raw.get("damage_type") or ""),
        range_min=float(raw.get("range_min") or 0),
        range_max=float(raw.get("range_max") or 0),
        rof=float(raw.get("rof") or 0),
        enabled=bool(raw.get("enabled", True)),
        charge=bool(raw.get("charge", False)),
        recharge=float(raw.get("recharge") or 0),
        aoe_radius=float(raw.get("aoe_radius") or 0),
        damage_cap=float(raw.get("damage_cap") or 0),
        num_projectiles=int(raw.get("num_projectiles") or 1),
        windup=float(raw.get("windup") or 0),
        area_sort_mode=str(raw.get("area_sort_mode") or ""),
        outer_damage_area_distance=float(raw.get("outer_damage_area_distance") or 0),
        outer_damage_area_factor=float(raw.get("outer_damage_area_factor") or 0),
        basedamagecap=bool(raw.get("basedamagecap", False)),
        multipliers=multipliers,
        rates=tuple(str(item) for item in raw.get("rates") or () if item),
        hits_soldiers=bool(raw.get("hits_soldiers", True)),
        handlogic=bool(raw.get("handlogic", False)),
        rangedlogic=bool(raw.get("rangedlogic", False)),
    )


_UNIVERSAL_RATES = frozenset({"unit", "all", "military"})


def targets_guardians_only(action: AttackAction) -> bool:
    """这条攻击是否专门对付宝藏守护者。

    目标类型非空且全部含 ``Guardian`` 时成立。``Guardian`` 和
    ``WaterGuardian`` 都算；同时还能打 ``Unit`` 等普通目标的动作不算。
    没写目标类型时也不屏蔽。
    """
    if not action.rates:
        return False
    return all("guardian" in rate.lower() for rate in action.rates)


def rate_matches(action: AttackAction, target_types: tuple[str, ...] | list[str] | set[str] | None) -> bool:
    """目标类型对得上才打这一下。没写目标类型的攻击打谁都行。"""
    if target_types is None or not action.rates:
        return True
    lowered = {item.lower() for item in target_types}
    for rate in action.rates:
        key = rate.lower()
        if key in _UNIVERSAL_RATES or key in lowered:
            return True
    return False


def priority_shots(
    actions: tuple[AttackAction, ...] | list[AttackAction],
    *,
    limit: int = 2,
) -> list[AttackAction]:
    """当前阵型里按优先级取最多两条。同优先级保持阵型里的先后。

    优先展示打得到普通单位、当前开启且伤害大于 0 的动作。没有这种动作时，
    才回退到建筑、守卫等特殊目标动作。原始列表和战斗逻辑不受影响。
    """
    usable = [
        action
        for action in actions
        if (
            action.enabled
            and action.hits_soldiers
            and action.damage > 0
            and action.range_max > 0
        )
    ]
    fallback = [action for action in actions if not targets_guardians_only(action)]
    ranked = sorted(enumerate(usable or fallback), key=lambda item: (-item[1].priority, item[0]))
    return [action for _, action in ranked[:limit]]


def soldier_attacks(
    actions: tuple[AttackAction, ...] | list[AttackAction],
) -> list[AttackAction]:
    """现在开着、打得中人、伤害大于 0 的模式。"""
    return [
        action
        for action in actions
        if action.enabled and action.hits_soldiers and action.damage > 0
    ]


def soldier_search_range(actions: tuple[AttackAction, ...] | list[AttackAction]) -> float:
    """搜敌半径只用打得中人、并且现在打得出来的最远射程。"""
    reach = 0.0
    for action in actions:
        if not action.hits_soldiers or not action.enabled:
            continue
        if action.damage <= 0 or action.range_max <= 0:
            continue
        if action.charge and action.recharge <= 0:
            continue
        reach = max(reach, action.range_max)
    return reach


def action_is_melee(action: AttackAction) -> bool:
    """手战且射程很短的模式，沿用近战抬手和回放槽。"""
    return action.damage_type == "Hand" and action.range_max < 6


def _usable(action: AttackAction, now: float, charge_ready_at: float) -> bool:
    if not action.enabled or action.damage <= 0 or action.range_max <= 0:
        return False
    if not action.charge:
        return True
    if action.recharge <= 0 or now < charge_ready_at:
        return False
    return True


def select_attack(
    actions: tuple[AttackAction, ...] | list[AttackAction],
    distance: float,
    *,
    now: float = 0.0,
    charge_ready_at: float = 0.0,
    target_types: tuple[str, ...] | list[str] | set[str] | None = None,
) -> AttackAction | None:
    """在已经打开、距离盖得住、目标类型对得上的模式里取优先级最高的一条。"""
    hits = [
        action
        for action in actions
        if _usable(action, now, charge_ready_at)
        and rate_matches(action, target_types)
        and action.range_min - 1e-6 <= distance <= action.range_max + 1e-6
    ]
    if not hits:
        return None
    return max(hits, key=lambda action: (action.priority, action.range_max, action.name))


def opening_attack(
    actions: tuple[AttackAction, ...] | list[AttackAction],
    *,
    now: float = 0.0,
    charge_ready_at: float = 0.0,
    target_types: tuple[str, ...] | list[str] | set[str] | None = None,
) -> AttackAction | None:
    """从远处走近时，停在优先级最高那条的最大射程上。"""
    usable = [
        action
        for action in actions
        if _usable(action, now, charge_ready_at) and rate_matches(action, target_types)
    ]
    if not usable:
        return None
    return max(usable, key=lambda action: (action.priority, action.range_max, action.name))


def approach_distance(
    actions: tuple[AttackAction, ...] | list[AttackAction],
    distance: float,
    *,
    now: float = 0.0,
    charge_ready_at: float = 0.0,
    target_types: tuple[str, ...] | list[str] | set[str] | None = None,
) -> float:
    """已经有模式盖住当前距离时停在原地，不为了打更近的模式继续靠近。

    落在两段射程中间时，向更近的那条模式走进去。再近也没有模式时停住。
    """
    if select_attack(
        actions,
        distance,
        now=now,
        charge_ready_at=charge_ready_at,
        target_types=target_types,
    ):
        return distance
    usable = [
        action
        for action in actions
        if _usable(action, now, charge_ready_at) and rate_matches(action, target_types)
    ]
    if not usable:
        return distance
    opening = max(usable, key=lambda action: (action.priority, action.range_max, action.name))
    if distance > opening.range_max:
        return opening.range_max
    closer = [action for action in usable if action.range_max < distance]
    if not closer:
        return distance
    chosen = max(closer, key=lambda action: (action.priority, action.range_max, action.name))
    return chosen.range_max
