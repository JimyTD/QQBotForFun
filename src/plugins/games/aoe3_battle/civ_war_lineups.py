"""Resolved civ-war candidates and composition-aware quantity allocation."""

from __future__ import annotations

import random
from dataclasses import dataclass

from src.plugins.aoe3.models import Unit
from src.plugins.aoe3.repository import UnitRepo
from src.plugins.aoe3.upgrades import apply_upgrades
from src.plugins.games.aoe3_battle.civ_war_roles import (
    NATIONAL_TACTICS,
    PREFERRED_EXTRA_UNIT_IDS,
    SOURCE_POLICY,
    AllocationRule,
    NationalTactic,
    civ_regular_units,
    is_regular_civ_war_unit,
    load_curated_civ_units,
    resolve_archetypes,
)
from src.plugins.games.aoe3_battle.lineup import (
    BUDGET,
    Lineup,
    UnitSlot,
    _unit_cost,
    get_bet_pool,
    unit_game_age,
)


@dataclass(frozen=True)
class CivWarCandidate:
    """A complete, concrete composition eligible for later matchup selection."""

    id: str
    title: str
    civ_id: str
    units: tuple[Unit, ...]
    allocation: AllocationRule
    source: str
    strategy_id: str
    strategy_description: str = ""
    roles: tuple[str, ...] = ()
    distinctive_count: int = 0

    @property
    def unit_ids(self) -> tuple[str, ...]:
        return tuple(unit.id for unit in self.units)

    @property
    def consulate_count(self) -> int:
        return sum(
            any(tag.startswith("AbstractConsulate") for tag in unit.type)
            for unit in self.units
        )

    @property
    def identity_tier(self) -> int:
        if self.source == "national":
            return 0
        return 1 if self.consulate_count == 0 else 2

    @property
    def is_pure_consulate(self) -> bool:
        return self.consulate_count == len(self.units)

    @property
    def is_mixed_consulate(self) -> bool:
        return 0 < self.consulate_count < len(self.units)


def _load_unique_units() -> dict[str, frozenset[str]]:
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "seeds" / "aoe3" / "civs.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        civ_id: frozenset(data["civs"][civ_id].get("unique_units", ()))
        for civ_id in data["_meta"]["curated_civs"]
    }


_UNIQUE_UNITS = _load_unique_units()


def _resolve_national_tactics(
    civ_id: str,
    age: int,
    available_by_id: dict[str, Unit],
) -> list[CivWarCandidate]:
    candidates: list[CivWarCandidate] = []
    for tactic in NATIONAL_TACTICS:
        if tactic.civ_id != civ_id or age < tactic.min_age:
            continue
        if not all(unit_id in available_by_id for unit_id in tactic.unit_ids):
            continue
        units = tuple(available_by_id[unit_id] for unit_id in tactic.unit_ids)
        candidates.append(_national_candidate(tactic, units))
    return candidates


def _national_candidate(tactic: NationalTactic, units: tuple[Unit, ...]) -> CivWarCandidate:
    return CivWarCandidate(
        id=f"national:{tactic.id}",
        title=tactic.title,
        civ_id=tactic.civ_id,
        units=units,
        allocation=tactic.allocation,
        source="national",
        strategy_id=tactic.id,
        strategy_description=tactic.description,
        distinctive_count=len(units),
    )


def generate_civ_candidates(
    repo: UnitRepo,
    civ_id: str,
    *,
    age: int = 3,
) -> list[CivWarCandidate]:
    """Generate and rank all concrete generic and national candidates for one civ."""
    if age not in {3, 4, 5}:
        raise ValueError("civ war supports ages 3 through 5")

    civ_units = load_curated_civ_units()
    if civ_id not in civ_units:
        raise ValueError(f"not a curated playable civ: {civ_id}")
    units = civ_regular_units(
        civ_id,
        get_bet_pool(repo, age=age),
        civ_units=civ_units,
    )
    national_available_by_id = {unit.id: unit for unit in units}
    for unit_id in PREFERRED_EXTRA_UNIT_IDS.get(civ_id, ()):
        unit = repo.get_by_id(unit_id)
        if (
            unit is not None
            and unit.id not in national_available_by_id
            and unit_game_age(unit) <= age
            and is_regular_civ_war_unit(unit)
        ):
            national_available_by_id[unit.id] = unit
    unique_ids = _UNIQUE_UNITS[civ_id]
    candidates = [
        CivWarCandidate(
            id=f"generic:{resolved.archetype.id}:{':'.join(resolved.unit_ids)}",
            title=resolved.archetype.title,
            civ_id=civ_id,
            units=resolved.units,
            allocation=resolved.archetype.allocation,
            source="generic",
            strategy_id=resolved.archetype.id,
            strategy_description="",
            roles=resolved.archetype.roles,
            distinctive_count=sum(unit.id in unique_ids for unit in resolved.units),
        )
        for resolved in resolve_archetypes(units)
    ]
    candidates.extend(_resolve_national_tactics(civ_id, age, national_available_by_id))
    if not SOURCE_POLICY.allow_pure_consulate:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.source == "national" or not candidate.is_pure_consulate
        ]
    candidates.sort(key=lambda candidate: (
        candidate.identity_tier,
        -candidate.distinctive_count,
        candidate.consulate_count,
        candidate.title,
        candidate.unit_ids,
    ))
    return candidates


def shortlist_candidates(
    candidates: list[CivWarCandidate],
    *,
    local_per_strategy: int = 4,
    consulate_per_strategy: int = 2,
) -> list[CivWarCandidate]:
    """Bound matchup search while preserving native and legal consulate variety."""
    grouped: dict[tuple[str, str], list[CivWarCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault((candidate.source, candidate.strategy_id), []).append(candidate)

    selected: list[CivWarCandidate] = []
    for group in grouped.values():
        if group[0].source == "national":
            selected.extend(group)
            continue
        local = [candidate for candidate in group if candidate.consulate_count == 0]
        consulate = [candidate for candidate in group if candidate.consulate_count > 0]
        selected.extend(local[:local_per_strategy])
        selected.extend(consulate[:consulate_per_strategy])
    selected.sort(key=lambda candidate: (
        candidate.identity_tier,
        -candidate.distinctive_count,
        candidate.consulate_count,
        candidate.title,
        candidate.unit_ids,
    ))
    return selected


def choose_source_pool(
    candidates: list[CivWarCandidate],
    *,
    rng: random.Random,
) -> list[CivWarCandidate]:
    """Choose local or mixed-consulate candidates before matchup ranking."""
    local = [candidate for candidate in candidates if candidate.consulate_count == 0]
    mixed = [candidate for candidate in candidates if candidate.is_mixed_consulate]
    if not local:
        return mixed
    if not mixed:
        return local
    source = rng.choices(
        ("local", "mixed"),
        weights=(SOURCE_POLICY.local_weight, SOURCE_POLICY.mixed_consulate_weight),
        k=1,
    )[0]
    return local if source == "local" else mixed


def choose_strategy_pool(
    candidates: list[CivWarCandidate],
    *,
    rng: random.Random,
) -> list[CivWarCandidate]:
    """Choose one strategy before choosing a concrete unit implementation.

    All national tactics share one top-level strategy bucket so a civilization
    with many authored national tactics does not crowd out generic tactics.
    """
    grouped: dict[tuple[str, str], list[CivWarCandidate]] = {}
    for candidate in candidates:
        key = (
            ("national", "national")
            if candidate.source == "national"
            else ("generic", candidate.strategy_id)
        )
        grouped.setdefault(key, []).append(candidate)
    if not grouped:
        return []
    chosen_key = rng.choice(list(grouped))
    return grouped[chosen_key]


def choose_candidate(
    candidates: list[CivWarCandidate],
    *,
    rng: random.Random,
) -> CivWarCandidate:
    """Choose preferred/ordinary, then ordinary source, strategy and implementation."""
    preferred = [candidate for candidate in candidates if candidate.source == "national"]
    ordinary = [candidate for candidate in candidates if candidate.source != "national"]
    if preferred and ordinary:
        tier = rng.choices(
            ("preferred", "ordinary"),
            weights=(
                SOURCE_POLICY.preferred_strategy_weight,
                SOURCE_POLICY.ordinary_strategy_weight,
            ),
            k=1,
        )[0]
        if tier == "preferred":
            strategy_pool = choose_strategy_pool(preferred, rng=rng)
            return rng.choice(strategy_pool)
    elif preferred:
        strategy_pool = choose_strategy_pool(preferred, rng=rng)
        return rng.choice(strategy_pool)
    elif not ordinary:
        raise ValueError("no civ-war candidates available")

    source_pool = choose_source_pool(ordinary, rng=rng)
    strategy_pool = choose_strategy_pool(source_pool, rng=rng)
    if not strategy_pool:
        raise ValueError("no civ-war candidates available")
    return rng.choice(strategy_pool)


def _allocate_resource_shares(
    units: tuple[Unit, ...],
    budget: int,
    shares: tuple[float, ...],
) -> list[int]:
    costs = [_unit_cost(unit) for unit in units]
    if sum(costs) > budget:
        raise ValueError("budget cannot buy one unit for every composition slot")

    counts = [1] * len(units)
    spent = sum(costs)
    while True:
        affordable = [index for index, cost in enumerate(costs) if spent + cost <= budget]
        if not affordable:
            return counts

        def allocation_error(index: int) -> tuple[float, int]:
            next_spends = [count * cost for count, cost in zip(counts, costs, strict=True)]
            next_spends[index] += costs[index]
            next_total = sum(next_spends)
            error = sum(
                (slot_spend / next_total - share) ** 2
                for slot_spend, share in zip(next_spends, shares, strict=True)
            )
            return error, costs[index]

        selected = min(affordable, key=allocation_error)
        counts[selected] += 1
        spent += costs[selected]


def _allocate_fixed_ratio(
    units: tuple[Unit, ...],
    budget: int,
    ratios: tuple[float, ...],
) -> list[int]:
    integer_ratios = [int(value) for value in ratios]
    package_cost = sum(
        _unit_cost(unit) * ratio
        for unit, ratio in zip(units, integer_ratios, strict=True)
    )
    packages = budget // package_cost
    if packages < 1:
        raise ValueError("budget cannot buy one fixed-ratio composition package")
    return [ratio * packages for ratio in integer_ratios]


def allocate_candidate(
    candidate: CivWarCandidate,
    *,
    budget: int = BUDGET,
    age: int = 3,
) -> Lineup:
    """Apply age upgrades and allocate quantities using the candidate's own policy."""
    upgraded = tuple(
        apply_upgrades(unit, age, civ_id=candidate.civ_id)
        for unit in candidate.units
    )
    if candidate.allocation.kind == "resource_shares":
        counts = _allocate_resource_shares(upgraded, budget, candidate.allocation.values)
    elif candidate.allocation.kind == "fixed_ratio":
        counts = _allocate_fixed_ratio(upgraded, budget, candidate.allocation.values)
    else:  # Defensive guard for candidates built outside the seed loader.
        raise ValueError(f"unsupported allocation kind: {candidate.allocation.kind}")
    return Lineup([
        UnitSlot(unit, count)
        for unit, count in zip(upgraded, counts, strict=True)
    ])
