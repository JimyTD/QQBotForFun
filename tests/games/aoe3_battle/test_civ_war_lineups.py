"""Civ-war concrete candidate and allocation tests."""

from __future__ import annotations

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.civ_war_lineups import (
    allocate_candidate,
    generate_civ_candidates,
    shortlist_candidates,
)
from plugins.games.aoe3_battle.civ_war_roles import load_curated_civ_units


@pytest.fixture(scope="module")
def repo() -> UnitRepo:
    return UnitRepo.get()


def test_generic_candidates_carry_reviewed_resource_shares(repo: UnitRepo) -> None:
    candidate = next(
        candidate
        for candidate in generate_civ_candidates(repo, "DEEthiopians", age=3)
        if candidate.unit_ids == ("degascenya", "deshotelwarrior")
    )
    assert candidate.title == "火枪马"
    assert candidate.allocation.kind == "resource_shares"
    assert candidate.allocation.values == (0.6, 0.4)


def test_resource_share_allocator_tracks_target_and_budget(repo: UnitRepo) -> None:
    candidate = next(
        candidate
        for candidate in generate_civ_candidates(repo, "British", age=3)
        if candidate.unit_ids == ("musketeer", "hussar")
    )
    lineup = allocate_candidate(candidate, budget=10000, age=3)
    spends = [slot.total_cost for slot in lineup.slots]
    actual_musk_share = spends[0] / sum(spends)
    assert actual_musk_share == pytest.approx(0.6, abs=0.02)
    assert lineup.total_cost <= 10000
    assert 10000 - lineup.total_cost < min(slot.unit_cost for slot in lineup.slots)


def test_chinese_banner_armies_are_fixed_ratio_candidates(repo: UnitRepo) -> None:
    candidates = generate_civ_candidates(repo, "Chinese", age=3)
    national = {candidate.title: candidate for candidate in candidates if candidate.source == "national"}
    assert set(national) == {"旧汉军", "正规军", "明军", "地方军", "帝国军", "禁卫军"}

    old_han = national["旧汉军"]
    lineup = allocate_candidate(old_han, budget=10000, age=3)
    counts = [slot.count for slot in lineup.slots]
    assert counts[0] == counts[1]
    assert counts[0] % 3 == 0

    standard = national["正规军"]
    lineup = allocate_candidate(standard, budget=10000, age=3)
    assert lineup.slots[0].count * 2 == lineup.slots[1].count * 3


def test_national_candidates_sort_before_generic_candidates(repo: UnitRepo) -> None:
    candidates = generate_civ_candidates(repo, "Chinese", age=3)
    assert candidates[0].source == "national"
    assert [candidate.identity_tier for candidate in candidates] == sorted(
        candidate.identity_tier for candidate in candidates
    )


def test_native_candidates_sort_before_consulate_fillers(repo: UnitRepo) -> None:
    candidates = [
        candidate
        for candidate in generate_civ_candidates(repo, "Japanese", age=3)
        if candidate.title == "火枪马"
    ]
    assert candidates[0].unit_ids == ("ypashigaru", "ypnaginatarider")
    first_consulate = next(
        index for index, candidate in enumerate(candidates) if candidate.consulate_count
    )
    assert all(candidate.consulate_count == 0 for candidate in candidates[:first_consulate])


@pytest.mark.parametrize("age", [3, 4, 5])
def test_all_curated_civs_keep_multiple_allocatable_strategies(
    repo: UnitRepo,
    age: int,
) -> None:
    for civ_id in load_curated_civ_units():
        candidates = generate_civ_candidates(repo, civ_id, age=age)
        assert len({candidate.strategy_id for candidate in candidates}) >= 3, civ_id
        assert len({candidate.id for candidate in candidates}) == len(candidates), civ_id
        for candidate in shortlist_candidates(candidates):
            lineup = allocate_candidate(candidate, budget=10000, age=age)
            assert lineup.total_cost <= 10000, (civ_id, candidate.id)
            assert all(slot.count >= 1 for slot in lineup.slots)


@pytest.mark.parametrize("age", [1, 2, 6])
def test_civ_candidates_reject_unsupported_ages(repo: UnitRepo, age: int) -> None:
    with pytest.raises(ValueError, match="ages 3 through 5"):
        generate_civ_candidates(repo, "British", age=age)
