"""经验与军衔（对齐 OpenRA GainsExperience / GivesExperience + ^GainsExperience 倍率）。"""

from __future__ import annotations

from dataclasses import dataclass

from .repo import ActorDef, GainsExperienceDef, VeterancyRules, load_veterancy_rules


@dataclass
class UnitVeterancy:
    """单位当前经验与等级（level 0=无军衔，1=veteran，2=elite）。"""

    experience: int = 0
    level: int = 0

    @property
    def is_veteran(self) -> bool:
        return self.level >= 1

    @property
    def is_elite(self) -> bool:
        return self.level >= 2


def xp_threshold_base(actor: ActorDef, ge: GainsExperienceDef) -> int:
    """对齐 GainsExperienceInfo：ExperienceModifier<0 时用 Cost，否则用 Modifier。"""
    if ge.experience_modifier < 0:
        return max(1, actor.cost)
    return max(1, ge.experience_modifier)


def xp_thresholds(actor: ActorDef, ge: GainsExperienceDef) -> list[int]:
    """各级所需累计经验（升序）。"""
    base = xp_threshold_base(actor, ge)
    keys = sorted(pct for pct, _cond in ge.conditions)
    return [pct * base // 100 for pct in keys]


def max_veterancy_level(ge: GainsExperienceDef) -> int:
    return len(ge.conditions)


def gives_experience_value(actor: ActorDef) -> int:
    """GivesExperience：默认授予 Victim Cost。"""
    return max(0, actor.cost)


def _normalize_product_stars(stars: int) -> int:
    """产品星级 0/1/3；兼容旧第三元 1=无星、2=一星、3=三星。"""
    if stars in (0, 1, 3):
        return stars
    legacy = {1: 0, 2: 1, 3: 3}
    return legacy.get(stars, 0)


def apply_initial_stars(
    vet: UnitVeterancy,
    stars: int,
    actor: ActorDef,
    ge: GainsExperienceDef,
) -> None:
    """出战星级：0=无军衔，1=老兵，3=精英（OpenRA level 0/1/2）。"""
    thresholds = xp_thresholds(actor, ge)
    product = _normalize_product_stars(stars)
    if product == 0:
        vet.experience = 0
        vet.level = 0
        return
    if product == 1 and thresholds:
        vet.experience = thresholds[0]
        vet.level = 1
        return
    if product == 3:
        if len(thresholds) >= 2:
            vet.experience = thresholds[1]
            vet.level = 2
        elif thresholds:
            vet.experience = thresholds[0]
            vet.level = 1


def grant_experience(
    vet: UnitVeterancy,
    amount: int,
    actor: ActorDef,
    ge: GainsExperienceDef,
) -> int:
    """增加经验并升级；返回新达到的等级（0 表示未升级）。"""
    if amount <= 0 or max_veterancy_level(ge) == 0:
        return 0
    thresholds = xp_thresholds(actor, ge)
    cap = thresholds[-1] if thresholds else 0
    old_level = vet.level
    vet.experience = min(cap, vet.experience + amount)
    new_level = 0
    for req in thresholds:
        if vet.experience >= req:
            new_level += 1
    vet.level = min(new_level, max_veterancy_level(ge))
    return vet.level - old_level


@dataclass(frozen=True)
class VeterancyMultipliers:
    firepower: int = 100
    damage_received: int = 100
    speed: int = 100
    reload_delay: int = 100


def combat_multipliers(level: int, rules: VeterancyRules | None = None) -> VeterancyMultipliers:
    rules = rules or load_veterancy_rules()
    if level >= 2:
        return VeterancyMultipliers(
            firepower=rules.firepower_elite,
            damage_received=rules.damage_received_elite,
            speed=rules.speed_elite,
            reload_delay=rules.reload_delay_elite,
        )
    if level >= 1:
        return VeterancyMultipliers(
            firepower=rules.firepower_veteran,
            damage_received=rules.damage_received_veteran,
            speed=rules.speed_veteran,
            reload_delay=rules.reload_delay_veteran,
        )
    return VeterancyMultipliers()


def scaled_reload_delay(base: int, mult: VeterancyMultipliers) -> int:
    return max(1, base * mult.reload_delay // 100)


def scaled_speed(base: int, mult: VeterancyMultipliers) -> int:
    return max(1, base * mult.speed // 100)
