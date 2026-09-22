"""Civ-war tactical role resolution and generic-archetype enumeration."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import product
from pathlib import Path

from src.plugins.aoe3.models import Unit

ROLE_MUSK = "musk"
ROLE_SKIRM = "skirm"
ROLE_SHOCK = "shock"
ROLE_DRAGOON = "dragoon"
ROLE_ANTI_CAV_HEAVY = "anti_cavalry_heavy"
ROLE_ANTI_INFANTRY_ARTILLERY = "anti_infantry_artillery"

ALL_ROLES: frozenset[str] = frozenset({
    ROLE_MUSK,
    ROLE_SKIRM,
    ROLE_SHOCK,
    ROLE_DRAGOON,
    ROLE_ANTI_CAV_HEAVY,
    ROLE_ANTI_INFANTRY_ARTILLERY,
})

# Regular-army exclusions above the normal battle pool.
CIV_WAR_EXCLUDED_IDS: frozenset[str] = frozenset({"xpspy", "despyottoman"})
DEDICATED_DEMOLITION_IDS: frozenset[str] = frozenset({
    "destealthpetard",
    "xppetard",
    "xppetardnitro",
    "xpram",
})
_INFANTRY_TAGS: frozenset[str] = frozenset({
    "AbstractInfantry",
    "AbstractHeavyInfantry",
    "AbstractLightInfantry",
})


@dataclass(frozen=True)
class AllocationRule:
    """How a resolved composition divides the battle budget."""

    kind: str
    values: tuple[float, ...]


@dataclass(frozen=True)
class Archetype:
    """A generic tactical archetype; slot order is also display order."""

    id: str
    title: str
    roles: tuple[str, ...]
    allocation: AllocationRule


@dataclass(frozen=True)
class NationalTactic:
    """A civ-owned composition with explicit units and allocation."""

    civ_id: str
    id: str
    title: str
    description: str
    min_age: int
    unit_ids: tuple[str, ...]
    allocation: AllocationRule


@dataclass(frozen=True)
class SourcePolicy:
    """Top-level strategy and ordinary-source probabilities."""

    preferred_strategy_weight: float
    ordinary_strategy_weight: float
    local_weight: float
    mixed_consulate_weight: float
    allow_pure_consulate: bool


@dataclass(frozen=True)
class ResolvedArchetype:
    """已落实到具体兵种的通用骨架候选。"""

    archetype: Archetype
    units: tuple[Unit, ...]

    @property
    def unit_ids(self) -> tuple[str, ...]:
        return tuple(unit.id for unit in self.units)


_ROOT = Path(__file__).resolve().parents[4]
_CIVS_PATH = _ROOT / "seeds" / "aoe3" / "civs.json"
_ARCHETYPES_PATH = _ROOT / "seeds" / "aoe3" / "civ_war_archetypes.json"
_PREFERRED_TACTICS_PATH = _ROOT / "seeds" / "aoe3" / "civ_war_preferred_tactics.json"


def _parse_allocation(raw: dict, *, slot_count: int) -> AllocationRule:
    kind = str(raw["kind"])
    values = tuple(float(value) for value in raw["values"])
    if kind not in {"resource_shares", "fixed_ratio"}:
        raise ValueError(f"unsupported civ-war allocation kind: {kind}")
    if len(values) != slot_count or any(value <= 0 for value in values):
        raise ValueError(f"invalid {kind} values for {slot_count} slots: {values}")
    if kind == "resource_shares" and abs(sum(values) - 1.0) > 1e-9:
        raise ValueError(f"resource shares must sum to 1: {values}")
    if kind == "fixed_ratio" and any(not value.is_integer() for value in values):
        raise ValueError(f"fixed ratios must be integers: {values}")
    return AllocationRule(kind, values)


def _load_archetype_config() -> tuple[
    tuple[Archetype, ...],
    tuple[NationalTactic, ...],
    SourcePolicy,
    dict[str, frozenset[str]],
]:
    data = json.loads(_ARCHETYPES_PATH.read_text(encoding="utf-8"))
    archetypes: list[Archetype] = []
    for raw in data["generic_archetypes"]:
        roles = tuple(raw["roles"])
        if any(role not in ALL_ROLES for role in roles):
            raise ValueError(f"unknown role in archetype {raw['id']}: {roles}")
        archetypes.append(Archetype(
            id=raw["id"],
            title=raw["title"],
            roles=roles,
            allocation=_parse_allocation(raw["allocation"], slot_count=len(roles)),
        ))

    tactics: list[NationalTactic] = []
    for civ_id, entries in data.get("civ_tactics", {}).items():
        for raw in entries:
            unit_ids = tuple(raw["unit_ids"])
            tactics.append(NationalTactic(
                civ_id=civ_id,
                id=raw["id"],
                title=raw["title"],
                description=str(raw.get("reason", "")).strip(),
                min_age=int(raw["min_age"]),
                unit_ids=unit_ids,
                allocation=_parse_allocation(raw["allocation"], slot_count=len(unit_ids)),
            ))
    preferred_data = json.loads(_PREFERRED_TACTICS_PATH.read_text(encoding="utf-8"))
    for civ_id, entries in preferred_data.get("civs", {}).items():
        for raw in entries:
            if raw.get("status", "approved") != "approved":
                continue
            unit_ids = tuple(raw["unit_ids"])
            tactics.append(NationalTactic(
                civ_id=civ_id,
                id=raw["id"],
                title=raw["title"],
                description=str(raw.get("reason", "")).strip(),
                min_age=int(raw.get("min_age", 3)),
                unit_ids=unit_ids,
                allocation=_parse_allocation(raw["allocation"], slot_count=len(unit_ids)),
            ))
    raw_policy = data["source_policy"]
    policy = SourcePolicy(
        preferred_strategy_weight=float(raw_policy["preferred_strategy_weight"]),
        ordinary_strategy_weight=float(raw_policy["ordinary_strategy_weight"]),
        local_weight=float(raw_policy["local_weight"]),
        mixed_consulate_weight=float(raw_policy["mixed_consulate_weight"]),
        allow_pure_consulate=bool(raw_policy["allow_pure_consulate"]),
    )
    if policy.preferred_strategy_weight < 0 or policy.ordinary_strategy_weight <= 0:
        raise ValueError(f"invalid civ-war strategy weights: {policy}")
    if abs(
        policy.preferred_strategy_weight + policy.ordinary_strategy_weight - 1.0
    ) > 1e-9:
        raise ValueError(f"civ-war strategy weights must sum to 1: {policy}")
    if policy.local_weight <= 0 or policy.mixed_consulate_weight < 0:
        raise ValueError(f"invalid civ-war source weights: {policy}")
    if abs(policy.local_weight + policy.mixed_consulate_weight - 1.0) > 1e-9:
        raise ValueError(f"civ-war source weights must sum to 1: {policy}")
    extra_unit_ids = {
        civ_id: frozenset(unit_ids)
        for civ_id, unit_ids in preferred_data.get("_meta", {}).get(
            "extra_unit_ids", {}
        ).items()
    }
    return tuple(archetypes), tuple(tactics), policy, extra_unit_ids


(
    GENERIC_ARCHETYPES,
    NATIONAL_TACTICS,
    SOURCE_POLICY,
    PREFERRED_EXTRA_UNIT_IDS,
) = _load_archetype_config()


def _has_multiplier(unit: Unit, *, attack: str, targets: frozenset[str]) -> bool:
    multipliers = unit.multipliers_melee if attack == "melee" else unit.multipliers_ranged
    return any(mult.vs in targets and mult.value > 1.0 for mult in multipliers)


def _tooltip_marks_anti_infantry(unit: Unit) -> bool:
    """Use the authored English unit tooltip only for artillery sub-role disambiguation."""
    return "against infantry" in unit.description_en.lower()


def _is_skirmisher(unit: Unit, tags: frozenset[str]) -> bool:
    if not tags & {"AbstractSkirmisher", "AbstractFootArcher"}:
        return False
    if _has_multiplier(
        unit,
        attack="ranged",
        targets=frozenset({"AbstractHeavyInfantry"}),
    ):
        return True
    description = unit.description_en.lower()
    return "against infantry" in description or "counters heavy infantry" in description


def unit_roles(unit: Unit) -> frozenset[str]:
    """Return tactical roles using AoE3 logical counter-class tag combinations."""
    tags = frozenset(unit.type)
    roles: set[str] = set()

    if "AbstractMusketeer" in tags:
        roles.add(ROLE_MUSK)
    if _is_skirmisher(unit, tags):
        roles.add(ROLE_SKIRM)
    if "AbstractHandCavalry" in tags or {
        "AbstractHandInfantry",
        "AbstractLightInfantry",
    } <= tags:
        roles.add(ROLE_SHOCK)
    if tags & {"AbstractRangedCavalry", "AbstractRangedShockInfantry"}:
        roles.add(ROLE_DRAGOON)
    if (
        {"AbstractHandInfantry", "AbstractHeavyInfantry"} <= tags
        and _has_multiplier(unit, attack="melee", targets=frozenset({"AbstractCavalry"}))
    ):
        roles.add(ROLE_ANTI_CAV_HEAVY)
    is_anti_artillery = _has_multiplier(
        unit,
        attack="ranged",
        targets=frozenset({"AbstractArtillery"}),
    )
    if "AbstractArtillery" in tags and (
        _has_multiplier(unit, attack="ranged", targets=_INFANTRY_TAGS)
        or (_tooltip_marks_anti_infantry(unit) and not is_anti_artillery)
    ):
        roles.add(ROLE_ANTI_INFANTRY_ARTILLERY)

    return frozenset(roles)


def is_regular_civ_war_unit(unit: Unit) -> bool:
    """Filter non-regular units after normal battle-pool safety filtering."""
    tags = set(unit.type)
    is_covert_agent = {"MercType2", "AbstractCanSeeStealth"} <= tags
    return not (
        unit.id in CIV_WAR_EXCLUDED_IDS
        or unit.id in DEDICATED_DEMOLITION_IDS
        or unit.id.endswith("mansabdar")
        or is_covert_agent
        or bool(tags & {
            "Hero",
            "AbstractPet",
            "AbstractFindScout",
        })
    )


def resolve_archetypes(
    units: Iterable[Unit],
    archetypes: Iterable[Archetype] = GENERIC_ARCHETYPES,
) -> list[ResolvedArchetype]:
    """Enumerate fully resolved generic archetypes without choosing randomly."""
    unit_list = list(units)
    roles_by_id = {unit.id: unit_roles(unit) for unit in unit_list}
    resolved: list[ResolvedArchetype] = []

    for archetype in archetypes:
        choices = [
            [unit for unit in unit_list if role in roles_by_id[unit.id]]
            for role in archetype.roles
        ]
        if any(not choice for choice in choices):
            continue
        for selected in product(*choices):
            if len({unit.id for unit in selected}) != len(selected):
                continue
            resolved.append(ResolvedArchetype(archetype, selected))

    return resolved


def load_curated_civ_units() -> dict[str, tuple[str, ...]]:
    """Load unit ids for the curated playable civs, never infer from `is_main`."""
    data = json.loads(_CIVS_PATH.read_text(encoding="utf-8"))
    civs = data["civs"]
    return {
        civ_id: tuple(civs[civ_id]["units"])
        for civ_id in data["_meta"]["curated_civs"]
    }


def civ_regular_units(
    civ_id: str,
    pool: Iterable[Unit],
    *,
    civ_units: dict[str, tuple[str, ...]] | None = None,
) -> list[Unit]:
    """Return one civ's regular army from an already age-filtered normal pool."""
    if civ_units is None:
        civ_units = load_curated_civ_units()
    allowed_ids = set(civ_units[civ_id])
    return [
        unit for unit in pool
        if unit.id in allowed_ids and is_regular_civ_war_unit(unit)
    ]
