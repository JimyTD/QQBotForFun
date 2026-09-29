"""Civ-war technology pool generation checks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "crawler"))

from aoe3_civ_war_tech_pool import ROOT as DATA_ROOT  # noqa: E402
from aoe3_civ_war_tech_pool import build_pool  # noqa: E402

RAW_DIR = DATA_ROOT / "data" / "aoe3" / "raw"

pytestmark = pytest.mark.skipif(
    not (RAW_DIR / "techtreey.xml").is_file(),
    reason="data/aoe3/raw/techtreey.xml not present",
)


@pytest.fixture(scope="module")
def pool() -> dict:
    return build_pool()


@pytest.fixture(scope="module")
def by_id(pool: dict) -> dict[str, dict]:
    return {tech["id"]: tech for tech in pool["techs"]}


def test_effect_subtypes_are_audited(pool: dict) -> None:
    census = {
        (row["effect_type"], row["subtype"]): row["count"]
        for row in pool["_meta"]["effect_census"]
    }
    assert census[("Data", "Damage")] > 0
    assert census[("Data2", "WorkRateSpecific")] > 0
    assert ("Data", "Damage") in census


def test_runtime_pool_contains_only_supported_ops(pool: dict) -> None:
    for tech in pool["techs"]:
        assert "ignored_ops" not in tech
        assert "unknown_ops" not in tech
        assert tech["combat_ops"] or tech["cost_ops"]


def test_nation_tech_targets_keep_combat_effects(by_id: dict[str, dict]) -> None:
    assert {"AbstractInfantry"} <= set(
        op.get("unittype")
        for op in by_id["HCXPOnikare"]["combat_ops"]
    )
    assert all(
        op.get("action")
        in {"MeleeHandAttack", "TrampleHandAttack", "DefendHandAttack"}
        for op in by_id["HCXPOnikare"]["combat_ops"]
    )
    assert by_id["HCXPOnikare"]["civ_ids"] == ["XPSioux"]


def test_cost_tech_keeps_combat_and_cost_effects(by_id: dict[str, dict]) -> None:
    tech = by_id["YPHCOldHanArmyReforms"]
    assert tech["combat_ops"]
    assert tech["cost_ops"]
    assert {
        op.get("resource") for op in tech["cost_ops"]
    } == {"Food", "Wood", "Gold"}
    assert {
        target["value"]
        for op in tech["combat_ops"]
        for target in op["targets"]
    } == {"ypChuKoNu", "ypQiangPikeman", "ypSteppeRider", "ypKeshik"}
    assert tech["civ_ids"] == ["Chinese"]


def test_shipment_side_effect_is_ignored(by_id: dict[str, dict]) -> None:
    tech = by_id["HCXPGreatTempleHuitzilopochtli"]
    assert any(
        op.get("subtype") == "DamageArea"
        for op in tech["combat_ops"]
    )
    assert any(
        op.get("subtype") == "MaximumVelocity"
        for op in tech["combat_ops"]
    )
    assert tech.get("combat_ops")
    assert not any(
        op.get("subtype") == "FreeHomeCityUnit"
        for op in tech["combat_ops"]
    )


def test_census_covers_every_effect_subtype(pool: dict) -> None:
    census_keys = {
        (row["effect_type"], row["subtype"])
        for row in pool["_meta"]["effect_census"]
    }
    assert ("Data", "Damage") in census_keys
    assert ("Data2", "FreeHomeCityUnitResource") in census_keys
    assert ("TextOutput", "<none>") in census_keys


def test_generic_pools_are_explicit_and_civ_scoped() -> None:
    generic_path = DATA_ROOT / "seeds" / "aoe3" / "civ_war_generic_techs.json"
    payload = json.loads(generic_path.read_text(encoding="utf-8"))
    assert payload["civs"]
    assert all(isinstance(ids, list) for ids in payload["civs"].values())
