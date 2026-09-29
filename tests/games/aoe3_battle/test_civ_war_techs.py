"""Civ-war technology matching and compensation selection."""

from __future__ import annotations

from dataclasses import dataclass

from plugins.aoe3.models import Unit
from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.civ_war_lineups import (
    CivWarCandidate,
    allocate_candidate,
    generate_civ_candidates,
)
from plugins.games.aoe3_battle.civ_war_matchup import estimate_matchup
from plugins.games.aoe3_battle.civ_war_roles import AllocationRule
from plugins.games.aoe3_battle.civ_war_techs import (
    MatchedTech,
    match_candidate_techs,
    resolve_required_techs,
    select_candidate_techs,
)
from plugins.games.aoe3_battle.lineup import MatchLineup, format_vs_banner


@dataclass(frozen=True)
class _Candidate:
    civ_id: str
    units: tuple[Unit, ...]
    source: str = "generic"
    required_tech_ids: tuple[str, ...] = ()


def _unit(repo: UnitRepo, unit_id: str) -> Unit:
    unit = repo.get_by_id(unit_id)
    assert unit is not None
    return unit


def test_match_candidate_techs_filters_by_civ_and_unit() -> None:
    repo = UnitRepo.get()
    candidate = _Candidate(
        civ_id="XPSioux",
        units=(
            _unit(repo, "xpwarbow"),
            _unit(repo, "xpdogsoldier"),
        ),
    )
    matched = match_candidate_techs(candidate, age=3)
    dog = next(tech for tech in matched if tech.id == "HCXPOnikare")

    assert dog.civ_ids == ("XPSioux",)
    assert dog.matched_unit_ids == ("xpwarbow", "xpdogsoldier")


def test_priority_tech_beats_generic_multi_match() -> None:
    repo = UnitRepo.get()
    candidate = _Candidate(
        civ_id="XPSioux",
        units=(
            _unit(repo, "xpwarbow"),
            _unit(repo, "xpdogsoldier"),
        ),
    )
    selected = select_candidate_techs(candidate, age=3)

    assert selected
    assert selected[0].id == "HCXPOnikare"
    assert selected[0].priority[0] == 0
    assert all(tech.id != "DEHCAkicita" for tech in selected)


def test_two_unit_auto_candidate_gets_one_tech() -> None:
    repo = UnitRepo.get()
    candidate = _Candidate(
        civ_id="Chinese",
        units=(
            _unit(repo, "ypchukonu"),
            _unit(repo, "ypstepperider"),
        ),
    )
    selected = select_candidate_techs(candidate, age=3)
    assert len(selected) <= 1


def test_unknown_effect_rows_are_not_selected() -> None:
    repo = UnitRepo.get()
    candidate = _Candidate(
        civ_id="DEHausa",
        units=(
            _unit(repo, "defulawarrior"),
            _unit(repo, "delifidi"),
        ),
    )
    selected = select_candidate_techs(candidate, age=3)
    assert all(tech.combat_ops or tech.cost_ops for tech in selected)


def test_national_candidate_does_not_get_auto_compensation() -> None:
    repo = UnitRepo.get()
    candidate = _Candidate(
        civ_id="Chinese",
        units=(
            _unit(repo, "ypchukonu"),
            _unit(repo, "ypqiangpikeman"),
        ),
        source="national",
    )
    assert select_candidate_techs(candidate, age=3) == []


def test_real_candidate_keeps_technology_identity() -> None:
    repo = UnitRepo.get()
    candidate = CivWarCandidate(
        id="test",
        title="test",
        civ_id="Chinese",
        units=(
            _unit(repo, "ypchukonu"),
            _unit(repo, "ypstepperider"),
        ),
        allocation=AllocationRule("resource_shares", (0.5, 0.5)),
        source="generic",
        strategy_id="test",
    )
    matched = match_candidate_techs(candidate, age=3)
    assert matched
    assert all(isinstance(tech, MatchedTech) for tech in matched)


def test_required_tech_binding_resolves() -> None:
    repo = UnitRepo.get()
    candidate = _Candidate(
        civ_id="XPSioux",
        units=(_unit(repo, "xpdogsoldier"),),
        source="national",
        required_tech_ids=("HCXPOnikare",),
    )
    resolved = resolve_required_techs(candidate, age=3)
    assert [tech.id for tech in resolved] == ["HCXPOnikare"]
    assert resolved[0].matched_unit_ids == ("xpdogsoldier",)


def test_runtime_tech_translation_applies_bonus() -> None:
    repo = UnitRepo.get()
    candidate = _Candidate(
        civ_id="XPSioux",
        units=(_unit(repo, "xpdogsoldier"),),
        source="national",
        required_tech_ids=("HCXPOnikare",),
    )
    tech = resolve_required_techs(candidate, age=3)[0].runtime_tech()
    assert tech["scope"] == ["xpdogsoldier"]
    assert any(op["stat"] == "mult" for op in tech["ops"])


def test_cost_tech_changes_allocated_counts() -> None:
    repo = UnitRepo.get()
    candidate = next(
        item
        for item in generate_civ_candidates(repo, "Chinese", age=3)
        if item.id == "national:old_han_army"
    )
    lineup = allocate_candidate(candidate, age=3)
    assert lineup.slots[0].unit.cost == {"food": 106}
    assert lineup.slots[1].unit.cost == {"wood": 75}


def test_matchup_estimate_carries_selected_techs() -> None:
    repo = UnitRepo.get()
    red = next(
        item
        for item in generate_civ_candidates(repo, "XPSioux", age=3)
        if item.id == "national:dog_soldier_host"
    )
    blue = next(
        item
        for item in generate_civ_candidates(repo, "Chinese", age=3)
        if item.id == "national:old_han_army"
    )
    estimate = estimate_matchup(red, blue, age=3)
    assert [tech.id for tech in estimate.red_techs] == [
        "HCXPOnikare",
        "HCXPSiouxNakotaSupport",
    ]
    assert [tech.id for tech in estimate.blue_techs] == [
        "YPHCOldHanArmyReforms",
        "YPHCHanAntiCavalryBonus",
    ]


def test_civ_war_banner_lists_tech_names() -> None:
    repo = UnitRepo.get()
    red = next(
        item
        for item in generate_civ_candidates(repo, "XPSioux", age=3)
        if item.id == "national:dog_soldier_host"
    )
    blue = next(
        item
        for item in generate_civ_candidates(repo, "Chinese", age=3)
        if item.id == "national:old_han_army"
    )
    estimate = estimate_matchup(red, blue, age=3)
    match = MatchLineup(
        red=estimate.red_lineup,
        blue=estimate.blue_lineup,
        mode="civ_war",
        age=3,
        red_civ_name="拉科塔",
        blue_civ_name="中国",
        red_strategy=red.title,
        blue_strategy=blue.title,
        red_tech_names=tuple(tech.name_zh or tech.id for tech in estimate.red_techs),
        blue_tech_names=tuple(tech.name_zh or tech.id for tech in estimate.blue_techs),
    )
    banner = format_vs_banner(match)
    assert "国战科技" in banner
