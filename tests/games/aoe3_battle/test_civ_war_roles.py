"""国战生态位判定与通用骨架枚举测试。"""

from __future__ import annotations

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.civ_war_roles import (
    ROLE_ANTI_CAV_HEAVY,
    ROLE_ANTI_INFANTRY_ARTILLERY,
    ROLE_DRAGOON,
    ROLE_MUSK,
    ROLE_SHOCK,
    ROLE_SKIRM,
    civ_regular_units,
    is_regular_civ_war_unit,
    load_curated_civ_units,
    resolve_archetypes,
    unit_roles,
)
from plugins.games.aoe3_battle.lineup import get_bet_pool


@pytest.fixture(scope="module")
def repo() -> UnitRepo:
    return UnitRepo.get()


@pytest.mark.parametrize(
    ("unit_id", "role"),
    [
        ("degascenya", ROLE_MUSK),
        ("deshotelwarrior", ROLE_SHOCK),
        ("xpcoyoteman", ROLE_SHOCK),
        ("xpwarbow", ROLE_SKIRM),
        ("xpeagleknight", ROLE_DRAGOON),
        ("xpriflerider", ROLE_DRAGOON),
        ("rodelero", ROLE_ANTI_CAV_HEAVY),
        ("ypchangdao", ROLE_ANTI_CAV_HEAVY),
        ("falconet", ROLE_ANTI_INFANTRY_ARTILLERY),
    ],
)
def test_unit_roles_cover_confirmed_ecosystems(repo: UnitRepo, unit_id: str, role: str) -> None:
    unit = repo.get_by_id(unit_id)
    assert unit is not None
    assert role in unit_roles(unit)


def test_culverin_is_not_anti_infantry_artillery(repo: UnitRepo) -> None:
    culverin = repo.get_by_id("culverin")
    assert culverin is not None
    assert ROLE_ANTI_INFANTRY_ARTILLERY not in unit_roles(culverin)


def test_mortar_is_not_anti_infantry_artillery(repo: UnitRepo) -> None:
    mortar = repo.get_by_id("mortar")
    assert mortar is not None
    assert ROLE_ANTI_INFANTRY_ARTILLERY not in unit_roles(mortar)


def test_organ_gun_is_anti_infantry_artillery_from_tooltip(repo: UnitRepo) -> None:
    organ_gun = repo.get_by_id("organgun")
    assert organ_gun is not None
    assert ROLE_ANTI_INFANTRY_ARTILLERY in unit_roles(organ_gun)


def test_skirm_tag_does_not_override_actual_anti_artillery_role(repo: UnitRepo) -> None:
    arrow_knight = repo.get_by_id("xparrowknight")
    assert arrow_knight is not None
    assert "AbstractSkirmisher" in arrow_knight.type
    assert ROLE_SKIRM not in unit_roles(arrow_knight)


def test_skirm_tooltip_keeps_units_without_explicit_multiplier(repo: UnitRepo) -> None:
    fire_thrower = repo.get_by_id("dehoopthrower")
    assert fire_thrower is not None
    assert ROLE_SKIRM in unit_roles(fire_thrower)


def test_scouts_do_not_enter_regular_civ_war_pool(repo: UnitRepo) -> None:
    scout = repo.get_by_id("deeaglescout")
    assert scout is not None
    assert not is_regular_civ_war_unit(scout)


def test_siege_trooper_tag_does_not_exclude_regular_army(repo: UnitRepo) -> None:
    steppe_rider = repo.get_by_id("ypstepperider")
    assert steppe_rider is not None
    assert "AbstractSiegeTrooper" in steppe_rider.type
    assert is_regular_civ_war_unit(steppe_rider)


def test_dedicated_demolition_unit_is_excluded(repo: UnitRepo) -> None:
    petard = repo.get_by_id("xppetard")
    assert petard is not None
    assert not is_regular_civ_war_unit(petard)


def test_covert_agent_is_excluded_without_excluding_maigadi(repo: UnitRepo) -> None:
    shinobi = repo.get_by_id("ypshinobihorse")
    maigadi = repo.get_by_id("demaigadi")
    assert shinobi is not None and maigadi is not None
    assert not is_regular_civ_war_unit(shinobi)
    assert is_regular_civ_war_unit(maigadi)


def test_ethiopian_musk_shock_resolves_from_tags(repo: UnitRepo) -> None:
    civ_units = load_curated_civ_units()
    ethiopian_units = civ_regular_units(
        "DEEthiopians",
        get_bet_pool(repo, age=3),
        civ_units=civ_units,
    )
    candidates = resolve_archetypes(ethiopian_units)
    assert ("degascenya", "deshotelwarrior") in {
        candidate.unit_ids
        for candidate in candidates
        if candidate.archetype.id == "musk_shock"
    }


def test_roles_do_not_use_pikeman_as_an_automatic_shortcut(repo: UnitRepo) -> None:
    azap = repo.get_by_id("deazap")
    assert azap is not None
    # Azap is correctly admitted through close-combat heavy anti-cavalry properties,
    # not merely because it carries AbstractPikeman.
    assert ROLE_ANTI_CAV_HEAVY in unit_roles(azap)
