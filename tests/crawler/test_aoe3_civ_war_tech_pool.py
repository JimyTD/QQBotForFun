"""Civ-war technology pool generation checks."""

from __future__ import annotations

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


def test_unknown_effects_are_not_silently_ignored(pool: dict) -> None:
    unknown_rows = [
        tech
        for tech in pool["techs"]
        if tech["review_status"] == "needs-review"
    ]
    assert unknown_rows
    assert all(tech["unknown_ops"] for tech in unknown_rows)
    assert any(
        tech["id"] == "DEHCMaraboutNetwork"
        for tech in unknown_rows
    )


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
    assert any(
        op.get("effect_type") == "Data"
        and op.get("subtype") == "FreeHomeCityUnit"
        for op in tech["ignored_ops"]
    )
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


def test_classified_unknown_subtype_is_never_ignored(pool: dict) -> None:
    unknown_subtypes = set(pool["_meta"]["unknown_subtypes"])
    assert unknown_subtypes
    for tech in pool["techs"]:
        for op in tech["ignored_ops"]:
            assert op.get("subtype") not in unknown_subtypes
