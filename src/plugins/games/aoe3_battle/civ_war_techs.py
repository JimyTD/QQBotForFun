"""Match civ-war technology-pool rows to concrete candidate lineups."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.plugins.aoe3.models import Unit
from src.plugins.aoe3.tech_effects import op_targets_unit, ops_for_unit
from src.plugins.aoe3.upgrades import age_upgrade_line
from src.plugins.games.aoe3_battle.tech_summary import (
    format_grouped_tech_summary,
    format_tech_summary,
)

POOL_PATH = (
    Path(__file__).resolve().parents[4]
    / "seeds"
    / "aoe3"
    / "civ_war_tech_pool.json"
)
PRIORITY_PATH = (
    Path(__file__).resolve().parents[4]
    / "seeds"
    / "aoe3"
    / "civ_war_priority_techs.json"
)
GENERIC_PATH = (
    Path(__file__).resolve().parents[4]
    / "seeds"
    / "aoe3"
    / "civ_war_generic_techs.json"
)

class _CandidateLike(Protocol):
    civ_id: str
    units: tuple[Unit, ...]
    source: str
    required_tech_ids: tuple[str, ...]


@dataclass(frozen=True)
class MatchedTech:
    """A pool technology with the candidate's concrete matched unit ids."""

    id: str
    name_zh: str
    civ_ids: tuple[str, ...]
    min_age: int | None
    source_flags: tuple[str, ...]
    matched_unit_ids: tuple[str, ...]
    matched_unit_names: tuple[str, ...]
    combat_ops: tuple[dict[str, Any], ...]
    cost_ops: tuple[dict[str, Any], ...]
    priority: tuple[int, ...]
    # The lineup units this tech hits, for per-unit summaries.
    matched_units: tuple[Unit, ...] = field(default=(), compare=False, repr=False)

    @property
    def match_count(self) -> int:
        return len(self.matched_unit_ids)

    @property
    def summary(self) -> str:
        """A short player-facing summary: each unit with the effects that hit it."""
        name = self.name_zh or self.id
        if not self.matched_units:
            return format_tech_summary(
                name,
                combat_ops=self.combat_ops,
                cost_ops=self.cost_ops,
                recipients=self.matched_unit_names,
            )
        return format_grouped_tech_summary(
            name,
            (
                (
                    unit.name,
                    _ops_that_land(ops_for_unit(self.combat_ops, unit), unit),
                    _ops_that_land(ops_for_unit(self.cost_ops, unit), unit),
                )
                for unit in self.matched_units
            ),
        )

    def runtime_tech(self) -> dict[str, Any]:
        """Translate pool ops into the runtime ``scope`` + ``ops`` contract.

        Every op keeps its own ``targets``. The runtime applies an op only to
        the units those targets name; ``scope`` is just the matched list.
        """
        ops: list[dict[str, Any]] = []
        for op in [*self.combat_ops, *self.cost_ops]:
            translated = _runtime_op(op)
            if translated is not None:
                ops.append(translated)
        return {
            "id": self.id,
            "name_zh": self.name_zh,
            "scope": list(self.matched_unit_ids),
            "ops": ops,
        }


_REVOLUTION_ID_PREFIXES = ("DEHCREV", "DEREV")


def is_revolution_tech(tech_id: str, source_flags: Iterable[str] = ()) -> bool:
    """Revolution cards stay out of civ-war and lineup selection."""
    if tech_id.startswith(_REVOLUTION_ID_PREFIXES):
        return True
    return "RevoltTech" in set(source_flags)


def _target_matches(target: str, unit: Unit) -> bool:
    return op_targets_unit(
        {"targets": [{"type": "ProtoUnit", "value": target}]},
        unit,
    )


# Effects that change one attack mode. They only land when that mode is in the
# unit's attack list after the tech's own tactic switch, as in settlement.
_ATTACK_SUBTYPES = {
    "Damage",
    "DamageBonus",
    "DamageArea",
    "MaximumRange",
    "MinimumRange",
    "RateOfFire",
}


def _ops_that_land(ops: list[dict[str, Any]], unit: Unit) -> list[dict[str, Any]]:
    """Drop attack effects this unit has no attack for, so the summary matches settlement."""
    actions = list(unit.attack_actions)
    by_tactic = unit.attack_actions_by_tactic or {}
    for op in ops:
        tactic = str(op.get("tactic") or "")
        if op.get("subtype") == "InitialTactic" and tactic in by_tactic:
            actions = list(by_tactic[tactic])
    names = {action.name for action in actions}
    has_hand = any(action.handlogic for action in actions)
    result = []
    for op in ops:
        subtype = op.get("subtype")
        if subtype == "DamageForAllHandLogicActions" and not has_hand:
            continue
        if (
            subtype in _ATTACK_SUBTYPES
            and op.get("action")
            and not op.get("allactions")
            and str(op["action"]) not in names
        ):
            continue
        result.append(op)
    return result


# (game subtype, game relativity) -> (runtime stat, runtime kind).
# An effect whose relativity is not listed here shows up in
# ``unapplied_effect_key`` instead of being dropped silently.
_RUNTIME_KINDS: dict[tuple[str, str], tuple[str, str]] = {
    ("Hitpoints", "BasePercent"): ("hp", "mult"),
    ("Hitpoints", "Absolute"): ("hp", "add"),
    ("Hitpoints", "Assign"): ("hp", "set"),
    ("Hitpoints", "Percent"): ("hp", "percent"),
    ("HitPoints", "BasePercent"): ("hp", "mult"),
    ("HitPoints", "Absolute"): ("hp", "add"),
    ("HitPoints", "Assign"): ("hp", "set"),
    ("HitPoints", "Percent"): ("hp", "percent"),
    ("Damage", "BasePercent"): ("damage", "mult"),
    ("Damage", "Absolute"): ("damage", "add"),
    ("Damage", "Assign"): ("damage", "set"),
    ("Damage", "Percent"): ("damage", "percent"),
    ("DamageForAllHandLogicActions", "BasePercent"): ("hand_damage", "mult"),
    ("DamageForAllHandLogicActions", "Absolute"): ("hand_damage", "add"),
    ("DamageForAllHandLogicActions", "Assign"): ("hand_damage", "set"),
    ("RateOfFire", "Assign"): ("rof", "set"),
    ("RateOfFire", "Absolute"): ("rof", "add"),
    ("RateOfFire", "BasePercent"): ("rof", "mult"),
    ("MaximumVelocity", "Absolute"): ("speed", "add"),
    ("MaximumVelocity", "Assign"): ("speed", "set"),
    ("MaximumVelocity", "BasePercent"): ("speed", "mult"),
    ("Cost", "BasePercent"): ("cost", "mult"),
    ("Cost", "Absolute"): ("cost", "add"),
    ("Cost", "Assign"): ("cost", "set"),
    ("Cost", "Override"): ("cost", "set"),
    ("Cost", "Percent"): ("cost", "percent"),
    ("RechargeTime", "Assign"): ("recharge", "set"),
    ("RechargeTime", "Absolute"): ("recharge", "add"),
    ("RechargeTime", "BasePercent"): ("recharge", "mult"),
}

# These subtypes are still read as a plain addition whatever the relativity
# says. What Assign / BasePercent should mean for them is an open question in
# docs/wip/aoe3-tech-effects.md; this keeps the existing reading until then.
_ADD_ANY_RELATIVITY = {
    "DamageBonus": "mult",
    "DamageArea": "aoe",
    "MaximumRange": "range",
    "MinimumRange": "range",
    "ArmorSpecific": "armor",
    "Armor": "armor",
}

# Subtypes whose effect is a switch, not an amount: any relativity works.
_SWITCH_KINDS = {
    "ActionEnable": ("action_enable", "set"),
    "InitialTactic": ("initial_tactic", "set"),
}

# Armor effects name the damage type they resist.
_ARMOR_KINDS = {
    "Hand": "melee",
    "Melee": "melee",
    "Ranged": "ranged",
    "Siege": "siege",
}


def unapplied_effect_key(op: dict[str, Any]) -> tuple[str, str, str] | None:
    """``(subtype, relativity, newtype)`` when settlement cannot apply this op.

    Every such effect must be listed in ``UNAPPLIED_EFFECTS``; a test fails on
    any effect that is neither applied nor listed.
    """
    if _runtime_op(op) is not None:
        return None
    newtype = (
        str(op.get("newtype") or "")
        if op.get("subtype") in {"Armor", "ArmorSpecific"}
        else ""
    )
    return (
        str(op.get("subtype") or ""),
        str(op.get("relativity") or ""),
        newtype,
    )


# Effects the settlement does not apply yet, by (subtype, relativity, newtype).
# Listed explicitly so nothing is dropped silently. Each one is a decision
# for the Owner, see docs/wip/aoe3-tech-effects.md.
UNAPPLIED_EFFECTS: frozenset[tuple[str, str, str]] = frozenset({
    ("ActionAdd", "Absolute", ""),
    ("ActionAddAttachingUnit", "Absolute", ""),
    ("AddContainedBonusType", "Assign", ""),
    ("AddContainedType", "Assign", ""),
    ("Armor", "Absolute", ""),
    ("Armor", "BasePercent", ""),
    ("Armor", "Percent", ""),
    ("ArmorType", "Absolute", ""),
    ("AttackPriority", "Absolute", ""),
    ("AutoAttackType", "Absolute", ""),
    ("ContainedHitpointBonus", "Assign", ""),
    ("ConversionDelay", "Absolute", ""),
    ("ConversionResistance", "Percent", ""),
    ("DamageCap", "BasePercent", ""),
    ("DamageForAllRangedLogicActions", "Absolute", ""),
    ("DamageForAllRangedLogicActions", "BasePercent", ""),
    ("DamageMultiplier", "Assign", ""),
    ("DodgeChance", "Assign", ""),
    ("EnableDodge", "Assign", ""),
    ("GarrisonBonusDamage", "Assign", ""),
    ("HitPercent", "Absolute", ""),
    ("HitPercent", "Assign", ""),
    ("HitPercent", "BasePercent", ""),
    ("HitPercent", "Percent", ""),
    ("HitPercentType", "Absolute", ""),
    ("ProtoActionAdd", "Assign", ""),
    ("RangeForAllRangedLogicActions", "Absolute", ""),
    ("SelfDamageMultiplier", "Assign", ""),
    ("SetActionFlag", "Absolute", ""),
    ("SetProjectile", "Absolute", ""),
    ("SetTacticDataOverride", "Assign", ""),
    ("SetUnitType", "Assign", ""),
    ("Snare", "Assign", ""),
    ("SpeedModifier", "Absolute", ""),
    ("SpeedModifier", "Assign", ""),
    ("SpeedModifier", "BasePercent", ""),
    ("TacticArmor", "Absolute", ""),
    ("TacticEnable", "Absolute", ""),
    ("TacticEnable", "Assign", ""),
    ("UnitRegenAbsolute", "Assign", ""),
    ("UnitRegenIgnoreOnStealth", "Absolute", ""),
    ("UnitRegenRate", "Absolute", ""),
    ("UnitRegenRate", "Assign", ""),
    ("UnitRegenRate", "Percent", ""),
    ("UnitRegenRateLimit", "Absolute", ""),
    ("VeterancyBonus", "Assign", ""),
    ("VeterancyEnable", "Absolute", ""),
})


def _runtime_op(op: dict[str, Any]) -> dict[str, Any] | None:
    subtype = str(op.get("subtype") or "")
    amount = op.get("amount")
    relation = str(op.get("relativity") or "")
    if amount is None:
        return None
    if subtype in _SWITCH_KINDS:
        stat, kind = _SWITCH_KINDS[subtype]
    elif subtype in _ADD_ANY_RELATIVITY:
        stat, kind = _ADD_ANY_RELATIVITY[subtype], "add"
    else:
        mapped = _RUNTIME_KINDS.get((subtype, relation))
        if mapped is None:
            return None
        stat, kind = mapped
    armor_kind = ""
    if stat == "armor":
        armor_kind = _ARMOR_KINDS.get(str(op.get("newtype") or ""), "")
        if not armor_kind:
            return None
    result: dict[str, Any] = {
        "stat": stat,
        "kind": kind,
        "value": amount,
        "subtype": subtype,
        "targets": list(op.get("targets") or ()),
    }
    for key in ("action", "allactions", "unittype", "resource", "newtype", "tactic"):
        if op.get(key):
            result[key] = (
                str(op[key]).lower()
                if key == "resource"
                else op[key]
            )
    if armor_kind:
        result["armor_kind"] = armor_kind
    if subtype == "DamageBonus":
        result["vs"] = op.get("unittype", "")
    return result


def _matched_units(
    row: dict[str, Any],
    units: list[Unit],
) -> tuple[Unit, ...]:
    """Units that receive at least one of the tech's effects.

    This decides whether the tech can be picked. Which effects a unit gets is
    decided per effect at settlement. ``unittype`` on an op is the counter,
    projectile, or attachment, not the recipient.
    """
    ops = [*row.get("combat_ops", ()), *row.get("cost_ops", ())]
    return tuple(
        unit
        for unit in units
        if any(op_targets_unit(op, unit) for op in ops)
    )


def _matched_unit_ids(
    row: dict[str, Any],
    units: list[Unit],
) -> tuple[str, ...]:
    return tuple(unit.id for unit in _matched_units(row, units))


def _is_civ_allowed(row: dict[str, Any], civ_id: str) -> bool:
    owners = set(row.get("civ_ids", ()))
    if not owners:
        return False
    return civ_id in owners


def _within_age(row: dict[str, Any], age: int) -> bool:
    min_age = row.get("min_age")
    return min_age is None or int(min_age) <= age


def _priority(row: dict[str, Any], matched_count: int) -> tuple[int, ...]:
    # Lower values win. Unknown rows are excluded before this function runs;
    # the tuple stays stable for deterministic fallback ordering.
    source_flags = set(row.get("source_flags", ()))
    source_rank = 0 if "UniqueTech" in source_flags or "HomeCity" in source_flags else 1
    return (
        0,
        source_rank,
        -matched_count,
        row.get("id", ""),
    )


def _load_priority(path: Path = PRIORITY_PATH) -> dict[str, tuple[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        row["id"]: (str(row.get("tier", "support")), str(row.get("note", "")))
        for row in payload["techs"]
    }


def _priority_rank(
    tech_id: str,
    priority: dict[str, tuple[str, str]],
) -> int:
    tier, _note = priority.get(tech_id, ("generic", ""))
    return 0 if tier == "core" else 1 if tier == "support" else 2


def _load_pool(path: Path = POOL_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["techs"]


def _load_generic_pool(path: Path = GENERIC_PATH) -> dict[str, set[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        civ_id: set(tech_ids)
        for civ_id, tech_ids in payload["civs"].items()
    }


def match_candidate_techs(
    candidate: _CandidateLike,
    *,
    age: int,
    pool: list[dict[str, Any]] | None = None,
    priority: dict[str, tuple[str, str]] | None = None,
    generic_pool: dict[str, set[str]] | None = None,
    path: Path = POOL_PATH,
) -> list[MatchedTech]:
    """Return deterministic pool matches that hit the candidate's units.

    An age-upgrade line is not a composition choice, at any tier. This uses
    the upgrade tables. The generator's ``is_age_upgrade`` flag only marks
    Shadow and SetAge rows, so it does not cover Veteran, Guard, or Imperial.
    """
    rows = pool if pool is not None else _load_pool(path)
    priority = priority if priority is not None else _load_priority()
    generic_pool = generic_pool if generic_pool is not None else _load_generic_pool()
    allowed_generic = generic_pool.get(candidate.civ_id, set())
    blocked_ids: set[str] = set()
    blocked_names: set[str] = set()
    for unit in candidate.units:
        tech_ids, names = age_upgrade_line(unit, candidate.civ_id)
        blocked_ids.update(tech_ids)
        blocked_names.update(names)
    matched: list[MatchedTech] = []
    for row in rows:
        if row["id"] in blocked_ids or row.get("name_zh") in blocked_names:
            continue
        if is_revolution_tech(row["id"], row.get("source_flags") or ()):
            continue
        if not _is_civ_allowed(row, candidate.civ_id):
            continue
        if not _within_age(row, age):
            continue
        if row["id"] not in priority and row["id"] not in allowed_generic:
            continue
        matched_units = _matched_units(row, list(candidate.units))
        if not matched_units:
            continue
        if not row.get("combat_ops") and not row.get("cost_ops"):
            continue
        matched.append(
            MatchedTech(
                id=row["id"],
                name_zh=row.get("name_zh", ""),
                civ_ids=tuple(row.get("civ_ids", ())),
                min_age=row.get("min_age"),
                source_flags=tuple(row.get("source_flags", ())),
                matched_unit_ids=tuple(unit.id for unit in matched_units),
                matched_unit_names=tuple(unit.name for unit in matched_units),
                combat_ops=tuple(row.get("combat_ops", ())),
                cost_ops=tuple(row.get("cost_ops", ())),
                priority=(
                    _priority_rank(row["id"], priority),
                    -len(matched_units),
                    *_priority(row, len(matched_units))[1:],
                ),
                matched_units=matched_units,
            )
        )
    matched.sort(key=lambda tech: tech.priority)
    return matched


def resolve_required_techs(
    candidate: _CandidateLike,
    *,
    age: int,
    pool: list[dict[str, Any]] | None = None,
    path: Path = POOL_PATH,
) -> list[MatchedTech]:
    """Resolve explicit bindings for a national/preferred composition."""
    if not candidate.required_tech_ids:
        return []
    rows = pool if pool is not None else _load_pool(path)
    rows_by_id = {row["id"]: row for row in rows}
    units = list(candidate.units)
    resolved: list[MatchedTech] = []
    for tech_id in candidate.required_tech_ids:
        row = rows_by_id.get(tech_id)
        if row is None:
            raise ValueError(f"required tech not found in pool: {tech_id}")
        if is_revolution_tech(row["id"], row.get("source_flags") or ()):
            raise ValueError(f"required tech {tech_id} is a revolution card")
        if not _is_civ_allowed(row, candidate.civ_id):
            raise ValueError(
                f"required tech {tech_id} is not available to {candidate.civ_id}"
            )
        if not _within_age(row, age):
            raise ValueError(f"required tech {tech_id} is not available at age {age}")
        matched_units = _matched_units(row, units)
        if not matched_units:
            raise ValueError(
                f"required tech {tech_id} does not hit any unit in "
                f"{candidate.id if hasattr(candidate, 'id') else candidate}"
            )
        resolved.append(
            MatchedTech(
                id=row["id"],
                name_zh=row.get("name_zh", ""),
                civ_ids=tuple(row.get("civ_ids", ())),
                min_age=row.get("min_age"),
                source_flags=tuple(row.get("source_flags", ())),
                matched_unit_ids=tuple(unit.id for unit in matched_units),
                matched_unit_names=tuple(unit.name for unit in matched_units),
                combat_ops=tuple(row.get("combat_ops", ())),
                cost_ops=tuple(row.get("cost_ops", ())),
                priority=(0, -len(matched_units), row["id"]),
                matched_units=matched_units,
            )
        )
    return resolved


def select_candidate_techs(
    candidate: _CandidateLike,
    *,
    age: int,
    pool: list[dict[str, Any]] | None = None,
    priority: dict[str, tuple[str, str]] | None = None,
    generic_pool: dict[str, set[str]] | None = None,
    path: Path = POOL_PATH,
) -> list[MatchedTech]:
    """Select the fixed-priority compensation set for an auto candidate."""
    if candidate.source == "generic":
        budget = max(0, len(candidate.units) - 1)
    elif candidate.source == "national":
        budget = 1
    else:
        return []
    if budget == 0:
        return []
    return match_candidate_techs(
        candidate,
        age=age,
        pool=pool,
        priority=priority,
        generic_pool=generic_pool,
        path=path,
    )[:budget]
