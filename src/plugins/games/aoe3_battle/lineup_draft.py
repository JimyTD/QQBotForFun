"""Player army drafts for the civ-war lineup mode.

The selectable technology list is whatever the civ-war pool currently
classifies as unit-specific or generic. Swapping that pool does not change
the draft steps.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from types import SimpleNamespace

from src.plugins.aoe3.repository import UnitRepo
from src.plugins.aoe3.tech_effects import apply_techs
from src.plugins.aoe3.upgrades import apply_upgrades
from src.plugins.games.aoe3_battle.civ_war_civs import (
    CIV_PROFILES,
    CivProfile,
    pick_random_civs,
    resolve_civ,
)
from src.plugins.games.aoe3_battle.civ_war_lineups import (
    _allocate_fixed_ratio,
    _allocate_resource_shares,
    choose_candidate,
    generate_civ_candidates,
)
from src.plugins.games.aoe3_battle.civ_war_roles import (
    NATIONAL_TACTICS,
    PREFERRED_EXTRA_UNIT_IDS,
    NationalTactic,
    civ_regular_units,
    is_regular_civ_war_unit,
)
from src.plugins.games.aoe3_battle.civ_war_techs import (
    MatchedTech,
    match_candidate_techs,
    resolve_required_techs,
)
from src.plugins.games.aoe3_battle.lineup import (
    Lineup,
    UnitSlot,
    _unit_cost,
    get_bet_pool,
    unit_game_age,
)


@dataclass(frozen=True)
class CompiledArmy:
    """One side, with counts already allocated under a frozen budget."""

    label: str
    civ_id: str
    civ_name: str
    strategy: str
    tech_ids: tuple[str, ...]
    tech_names: tuple[str, ...]
    slots: tuple[tuple[str, str, int], ...]

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "civ_id": self.civ_id,
            "civ_name": self.civ_name,
            "strategy": self.strategy,
            "tech_ids": list(self.tech_ids),
            "tech_names": list(self.tech_names),
            "slots": [
                {"unit_id": unit_id, "unit_name": name, "count": count}
                for unit_id, name, count in self.slots
            ],
        }


def draft_units(repo: UnitRepo, civ_id: str, age: int) -> list:
    """Regular units this civilization can field at ``age``, ordered by name."""
    if age not in {3, 4, 5}:
        raise ValueError("配兵只开放 3 至 5 时代")
    by_id = {
        unit.id: unit
        for unit in civ_regular_units(civ_id, get_bet_pool(repo, age=age))
    }
    for unit_id in PREFERRED_EXTRA_UNIT_IDS.get(civ_id, ()):
        unit = repo.get_by_id(unit_id)
        if (
            unit is not None
            and unit.id not in by_id
            and unit_game_age(unit) <= age
            and is_regular_civ_war_unit(unit)
        ):
            by_id[unit.id] = unit
    return sorted(by_id.values(), key=lambda unit: unit.name)


def tactics_for(
    civ_id: str,
    age: int,
    units_by_id: dict,
) -> list[NationalTactic]:
    """National tactics whose units are all fieldable at this age."""
    return [
        tactic
        for tactic in NATIONAL_TACTICS
        if tactic.civ_id == civ_id
        and tactic.min_age <= age
        and all(unit_id in units_by_id for unit_id in tactic.unit_ids)
    ]


def targets_fielded_unit(tech: MatchedTech, units: tuple) -> bool:
    """True when a combat effect names one of these units, not only a class."""
    fielded = {unit.id.lower() for unit in units}
    for op in tech.combat_ops:
        for target in op.get("targets") or ():
            if (
                target.get("type") == "ProtoUnit"
                and str(target.get("value") or "").lower() in fielded
            ):
                return True
    return False


def list_selectable_techs(civ_id: str, units: tuple, age: int) -> list[MatchedTech]:
    """Unit-specific techs first, then class-wide techs that hit these units.

    The list is whatever the civ-war pool matches for this civilization, age,
    and these soldiers. The hand-authored priority shortlist does not decide
    membership or the 专属 / 通用 label.
    """
    if not units:
        return []
    candidate = SimpleNamespace(
        civ_id=civ_id,
        units=tuple(units),
        source="generic",
        required_tech_ids=(),
        id="lineup-draft",
    )
    specific: list[MatchedTech] = []
    generic: list[MatchedTech] = []
    for tech in match_candidate_techs(candidate, age=age):
        if not tech.combat_ops:
            continue
        if targets_fielded_unit(tech, units):
            specific.append(tech)
        else:
            generic.append(tech)
    return specific + generic


def combat_runtime(tech: MatchedTech) -> dict:
    """Combat-only runtime payload. Tech selection does not change unit cost."""
    payload = tech.runtime_tech()
    payload["ops"] = [
        op for op in payload["ops"] if op.get("stat") != "cost"
    ]
    return payload


def parse_weights(text: str, slot_count: int) -> tuple[int, ...] | str:
    """Parse ``slot_count`` positive integers, or return an error string."""
    parts = text.split()
    if len(parts) != slot_count or not all(part.isdigit() and int(part) > 0 for part in parts):
        example = " ".join(str(8 + index * 2) for index in range(slot_count))
        return f"请按顺序输入 {slot_count} 个正整数，例如 {example}"
    return tuple(int(part) for part in parts)


def compile_custom(
    repo: UnitRepo,
    *,
    civ: CivProfile,
    unit_ids: tuple[str, ...],
    weights: tuple[int, ...],
    tech_ids: tuple[str, ...],
    age: int,
    budget: int,
    label: str,
) -> CompiledArmy:
    units = draft_units(repo, civ.id, age)
    by_id = {unit.id: unit for unit in units}
    chosen = []
    for unit_id in unit_ids:
        unit = by_id.get(unit_id)
        if unit is None:
            raise ValueError(f"兵种不在 {civ.name} 的可出列表里")
        chosen.append(unit)
    if len(chosen) != len(set(unit_ids)):
        raise ValueError("不能重复选择同一个兵")
    if not 1 <= len(chosen) <= 3:
        raise ValueError("自己配需要 1 到 3 个兵")
    if len(chosen) == 1:
        weights = (1,)
    if len(weights) != len(chosen):
        raise ValueError("权重个数要和兵种数一致")
    techs = _techs_by_id(civ.id, tuple(chosen), age, tech_ids)
    return _compile(
        civ=civ,
        units=tuple(chosen),
        techs=techs,
        allocation_kind="resource_shares",
        allocation_values=_shares(weights),
        strategy="自选",
        age=age,
        budget=budget,
        label=label,
    )


def compile_tactic(
    repo: UnitRepo,
    *,
    civ: CivProfile,
    tactic: NationalTactic,
    age: int,
    budget: int,
    label: str,
) -> CompiledArmy:
    by_id = {unit.id: unit for unit in draft_units(repo, civ.id, age)}
    units = tuple(by_id[unit_id] for unit_id in tactic.unit_ids)
    techs = tuple(
        resolve_required_techs(
            SimpleNamespace(
                civ_id=civ.id,
                units=units,
                source="national",
                required_tech_ids=tactic.required_tech_ids,
                id=tactic.id,
            ),
            age=age,
        )
    ) if tactic.required_tech_ids else ()
    return _compile(
        civ=civ,
        units=units,
        techs=techs,
        allocation_kind=tactic.allocation.kind,
        allocation_values=tactic.allocation.values,
        strategy=tactic.title,
        age=age,
        budget=budget,
        label=label,
    )


def compile_ai_army(
    repo: UnitRepo,
    *,
    age: int,
    budget: int,
    rng: random.Random,
) -> CompiledArmy:
    """One automatic civ-war army, rolled once and then kept."""
    civ = rng.choice(list(CIV_PROFILES))
    candidates = generate_civ_candidates(repo, civ.id, age=age)
    if not candidates:
        civ_a, civ_b = pick_random_civs(rng=rng)
        civ = civ_a if civ_a.id != civ.id else civ_b
        candidates = generate_civ_candidates(repo, civ.id, age=age)
    if not candidates:
        raise ValueError(f"{civ.name} 没有可用的国战编制")
    chosen = choose_candidate(candidates, rng=rng)
    techs = tuple(
        resolve_required_techs(chosen, age=age)
        if chosen.required_tech_ids
        else ()
    )
    if not techs and chosen.source != "national":
        slot_count = max(0, len(chosen.units) - 1)
        techs = tuple(
            tech
            for tech in match_candidate_techs(chosen, age=age)
            if tech.combat_ops
        )[:slot_count]
    return _compile(
        civ=civ,
        units=chosen.units,
        techs=techs,
        allocation_kind=chosen.allocation.kind,
        allocation_values=chosen.allocation.values,
        strategy=chosen.title,
        age=age,
        budget=budget,
        label=f"AI·{civ.name}",
    )


def materialize_army(repo: UnitRepo, payload: dict, age: int) -> Lineup:
    """Rebuild a compiled army. Counts stay at the values stored at lock time."""
    raw_units = []
    for slot in payload["slots"]:
        unit = repo.get_by_id(slot["unit_id"])
        if unit is None:
            raise ValueError(f"找不到兵种 {slot['unit_id']}")
        raw_units.append(unit)
    civ = resolve_civ(payload["civ_id"]) or resolve_civ(payload["civ_name"])
    if civ is None:
        raise ValueError(f"找不到文明 {payload['civ_id']}")
    techs = _techs_by_id(
        civ.id,
        tuple(raw_units),
        age,
        tuple(payload.get("tech_ids") or ()),
    )
    upgraded = _apply_combat(tuple(raw_units), techs, age, civ.id)
    return Lineup([
        UnitSlot(unit, int(slot["count"]))
        for unit, slot in zip(upgraded, payload["slots"], strict=True)
    ])


def _techs_by_id(
    civ_id: str,
    units: tuple,
    age: int,
    tech_ids: tuple[str, ...],
) -> tuple[MatchedTech, ...]:
    if not tech_ids:
        return ()
    return tuple(
        resolve_required_techs(
            SimpleNamespace(
                civ_id=civ_id,
                units=units,
                source="custom",
                required_tech_ids=tech_ids,
                id="lineup-draft",
            ),
            age=age,
        )
    )


def _shares(weights: tuple[int, ...]) -> tuple[float, ...]:
    total = sum(weights)
    return tuple(weight / total for weight in weights)


def _apply_combat(units: tuple, techs: tuple[MatchedTech, ...], age: int, civ_id: str):
    bases = tuple(units)
    upgraded = tuple(apply_upgrades(unit, age, civ_id=civ_id) for unit in bases)
    if not techs:
        return upgraded
    applied = []
    for unit, base in zip(upgraded, bases, strict=True):
        payloads = [
            combat_runtime(tech)
            for tech in techs
            if unit.id in tech.matched_unit_ids
        ]
        payloads = [payload for payload in payloads if payload["ops"]]
        if payloads:
            applied.append(apply_techs([unit], payloads, base_units=[base])[0])
        else:
            applied.append(unit)
    return tuple(applied)


def _compile(
    *,
    civ: CivProfile,
    units: tuple,
    techs: tuple[MatchedTech, ...],
    allocation_kind: str,
    allocation_values: tuple[float, ...],
    strategy: str,
    age: int,
    budget: int,
    label: str,
) -> CompiledArmy:
    upgraded = _apply_combat(units, techs, age, civ.id)
    if sum(_unit_cost(unit) for unit in upgraded) > budget:
        raise ValueError("这笔军费买不起每个兵各 1 个")
    if allocation_kind == "resource_shares":
        counts = _allocate_resource_shares(upgraded, budget, allocation_values)
    elif allocation_kind == "fixed_ratio":
        counts = _allocate_fixed_ratio(upgraded, budget, allocation_values)
    else:
        raise ValueError(f"不支持的分配方式 {allocation_kind}")
    return CompiledArmy(
        label=label,
        civ_id=civ.id,
        civ_name=civ.name,
        strategy=strategy,
        tech_ids=tuple(tech.id for tech in techs),
        tech_names=tuple(tech.name_zh or tech.id for tech in techs),
        slots=tuple(
            (unit.id, unit.name, count)
            for unit, count in zip(upgraded, counts, strict=True)
        ),
    )
