"""Validation for approved civilization preferred tactics."""

from __future__ import annotations

import json
from pathlib import Path

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.civ_war_roles import NATIONAL_TACTICS, load_curated_civ_units
from plugins.games.aoe3_battle.lineup import unit_game_age

_TACTICS_PATH = (
    Path(__file__).resolve().parents[3]
    / "seeds"
    / "aoe3"
    / "civ_war_preferred_tactics.json"
)


def test_preferred_tactics_cover_every_curated_civ() -> None:
    data = json.loads(_TACTICS_PATH.read_text(encoding="utf-8"))
    curated = set(load_curated_civ_units())
    covered = {
        civ_id
        for civ_id, tactics in data["civs"].items()
        if tactics or any(tactic.civ_id == civ_id for tactic in NATIONAL_TACTICS)
    }
    assert set(data["civs"]) == curated
    assert covered == curated


def test_preferred_tactic_units_and_allocations_are_valid() -> None:
    data = json.loads(_TACTICS_PATH.read_text(encoding="utf-8"))
    repo = UnitRepo.get()
    ids: set[tuple[str, str]] = set()
    for civ_id, tactics in data["civs"].items():
        for tactic in tactics:
            key = (civ_id, tactic["id"])
            assert key not in ids
            ids.add(key)
            unit_ids = tactic["unit_ids"]
            values = tactic["allocation"]["values"]
            assert 1 <= len(unit_ids) <= 3
            assert len(unit_ids) == len(values)
            assert len(set(unit_ids)) == len(unit_ids)
            units = [repo.get_by_id(unit_id) for unit_id in unit_ids]
            assert all(unit is not None for unit in units)
            assert all(unit.cost for unit in units if unit is not None)
            assert tactic.get("min_age", 3) >= max(
                unit_game_age(unit) for unit in units if unit is not None
            )
            assert tactic["allocation"]["kind"] == "resource_shares"
            assert abs(sum(values) - 1.0) < 1e-9


def test_preferred_tactics_contain_valid_single_unit_strategy() -> None:
    data = json.loads(_TACTICS_PATH.read_text(encoding="utf-8"))
    single = next(
        tactic
        for tactics in data["civs"].values()
        for tactic in tactics
        if len(tactic["unit_ids"]) == 1
    )
    assert single["allocation"] == {"kind": "resource_shares", "values": [1.0]}
