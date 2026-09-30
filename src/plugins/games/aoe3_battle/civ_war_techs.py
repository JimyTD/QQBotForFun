"""Match civ-war technology-pool rows to concrete candidate lineups."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from src.plugins.aoe3.models import Unit
from src.plugins.aoe3.upgrades import age_upgrade_line
from src.plugins.games.aoe3_battle.tech_summary import format_tech_summary

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

    @property
    def match_count(self) -> int:
        return len(self.matched_unit_ids)

    @property
    def summary(self) -> str:
        """A short player-facing summary of the applied and ignored effects."""
        return format_tech_summary(
            self.name_zh or self.id,
            combat_ops=self.combat_ops,
            cost_ops=self.cost_ops,
            recipients=self.matched_unit_names,
        )

    def runtime_tech(self) -> dict[str, Any]:
        """Translate pool ops into the runtime ``scope`` + ``ops`` contract."""
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


def _target_matches(target: str, unit: Unit) -> bool:
    return target.lower() == unit.id.lower() or target in unit.type


def _runtime_op(op: dict[str, Any]) -> dict[str, Any] | None:
    subtype = op.get("subtype")
    amount = op.get("amount")
    relation = op.get("relativity")
    if amount is None:
        return None
    match subtype:
        case "Hitpoints" | "HitPoints":
            stat, kind = "hp", "add" if relation == "Absolute" else "mult"
        case "Damage":
            stat, kind = "damage", "mult"
        case "DamageBonus":
            stat, kind = "mult", "add"
        case "DamageArea":
            stat, kind = "aoe", "add"
        case "MaximumRange" | "MinimumRange":
            stat, kind = "range", "add"
        case "RateOfFire":
            stat, kind = "rof", "set" if relation == "Assign" else "add"
        case "MaximumVelocity":
            stat = "speed"
            kind = {
                "Absolute": "add",
                "Assign": "set",
                "BasePercent": "mult",
            }.get(relation, "add")
        case "ArmorSpecific" | "Armor":
            stat, kind = "armor", "add"
        case "Cost":
            stat, kind = "cost", "mult" if relation == "BasePercent" else "add"
        case _:
            return None
    result: dict[str, Any] = {
        "stat": stat,
        "kind": kind,
        "value": amount,
        "subtype": subtype,
    }
    for key in ("action", "allactions", "unittype", "resource", "newtype"):
        if op.get(key):
            result[key] = (
                str(op[key]).lower()
                if key == "resource"
                else op[key]
            )
    if subtype in {"ArmorSpecific", "Armor"}:
        result["armor_kind"] = {
            "Hand": "melee",
            "Melee": "melee",
            "Ranged": "ranged",
        }.get(op.get("newtype"), "")
    if subtype == "DamageBonus":
        result["vs"] = op.get("unittype", "")
    return result


def _row_targets(row: dict[str, Any]) -> list[str]:
    """Units that receive the tech.

    ``unittype`` on an op is the counter, projectile, or attachment, not the
    recipient. A longbow tech that bonuses damage against heavy infantry must
    not be treated as a heavy-infantry tech.
    """
    values: set[str] = set()
    for op in [*row.get("combat_ops", ()), *row.get("cost_ops", ())]:
        for target in op.get("targets", ()):
            if target.get("type") == "ProtoUnit" and target.get("value"):
                values.add(str(target["value"]))
    return sorted(values)


def _matched_units(
    row: dict[str, Any],
    units: list[Unit],
) -> tuple[Unit, ...]:
    targets = _row_targets(row)
    if not targets:
        return ()
    return tuple(
        unit
        for unit in units
        if any(_target_matches(target, unit) for target in targets)
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
