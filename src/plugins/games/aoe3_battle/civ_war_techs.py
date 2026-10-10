"""Match civ-war technology-pool rows to concrete candidate lineups."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.plugins.aoe3.models import Unit
from src.plugins.aoe3.tech_effects import (
    UNAPPLIED_EFFECTS,
    op_targets_unit,
    ops_for_unit,
    runtime_op,
    unapplied_effect_key,
)
from src.plugins.aoe3.tech_links import expand as expand_unlocks
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
    # Techs this one unlocks (TechStatus active, satisfied shadows), already
    # minus the units' age-upgrade lines. They settle together with this tech.
    unlocked: tuple[dict[str, Any], ...] = field(default=(), compare=False, repr=False)

    @property
    def all_combat_ops(self) -> tuple[dict[str, Any], ...]:
        return (*self.combat_ops, *(op for row in self.unlocked for op in row.get("combat_ops", ())))

    @property
    def all_cost_ops(self) -> tuple[dict[str, Any], ...]:
        return (*self.cost_ops, *(op for row in self.unlocked for op in row.get("cost_ops", ())))

    @property
    def match_count(self) -> int:
        return len(self.matched_unit_ids)

    @property
    def summary(self) -> str:
        """A short player-facing summary: each unit with the effects that hit it."""
        name = self.name_zh or self.id
        combat_ops, cost_ops = self.all_combat_ops, self.all_cost_ops
        if not self.matched_units:
            return format_tech_summary(
                name,
                combat_ops=combat_ops,
                cost_ops=cost_ops,
                recipients=self.matched_unit_names,
            )
        return format_grouped_tech_summary(
            name,
            (
                (
                    unit.name,
                    _ops_that_land(ops_for_unit(combat_ops, unit), unit),
                    _ops_that_land(ops_for_unit(cost_ops, unit), unit),
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
        for op in [*self.all_combat_ops, *self.all_cost_ops]:
            translated = _runtime_op(op)
            if translated is not None:
                ops.append(translated)
        return {
            "id": self.id,
            "name_zh": self.name_zh,
            "scope": list(self.matched_unit_ids),
            "ops": ops,
            "unlocked_ids": [row["id"] for row in self.unlocked],
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


_runtime_op = runtime_op
__all__ = ["UNAPPLIED_EFFECTS", "unapplied_effect_key"]


def _matched_units(
    row: dict[str, Any],
    units: list[Unit],
    unlocked: Iterable[dict[str, Any]] = (),
) -> tuple[Unit, ...]:
    """Units that receive at least one effect of the tech or of what it unlocks.

    This decides whether the tech can be picked. Which effects a unit gets is
    decided per effect at settlement. ``unittype`` on an op is the counter,
    projectile, or attachment, not the recipient.

    An effect only counts when it lands on this unit: an attack effect needs
    the unit to have that attack (same rule as the summary). A tech that names
    a unit but changes nothing on it is not offered (Owner, 2026-10-10).
    """
    ops = [
        op
        for source in (row, *unlocked)
        for op in (*source.get("combat_ops", ()), *source.get("cost_ops", ()))
    ]
    return tuple(
        unit
        for unit in units
        if _ops_that_land(ops_for_unit(ops, unit), unit)
    )


def _matched_unit_ids(
    row: dict[str, Any],
    units: list[Unit],
) -> tuple[str, ...]:
    return tuple(unit.id for unit in _matched_units(row, units))


def _age_line_ids(units: Iterable[Unit], civ_id: str) -> set[str]:
    ids: set[str] = set()
    for unit in units:
        tech_ids, _names = age_upgrade_line(unit, civ_id)
        ids.update(tech_ids)
    return ids


def _unlocked_rows(
    tech_id: str,
    rows_by_id: dict[str, dict[str, Any]],
    *,
    age: int,
    skip: set[str],
) -> tuple[dict[str, Any], ...]:
    """Pool rows this tech unlocks, minus what the age upgrades already apply."""
    unlocked = []
    for child in expand_unlocks([tech_id], age=age)[1:]:
        if child in skip:
            continue
        row = rows_by_id.get(child)
        if row is not None:
            unlocked.append(row)
    return tuple(unlocked)


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
    rows_by_id = {row["id"]: row for row in rows}
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
        unlocked = _unlocked_rows(row["id"], rows_by_id, age=age, skip=blocked_ids)
        matched_units = _matched_units(row, list(candidate.units), unlocked)
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
                unlocked=unlocked,
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
    age_lines = _age_line_ids(units, candidate.civ_id)
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
        unlocked = _unlocked_rows(row["id"], rows_by_id, age=age, skip=age_lines)
        matched_units = _matched_units(row, units, unlocked)
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
                unlocked=unlocked,
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
