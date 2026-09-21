"""Static civ-war matchup estimation and selection tests."""

from __future__ import annotations

import random

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.civ_war_lineups import generate_civ_candidates
from plugins.games.aoe3_battle.civ_war_matchup import (
    estimate_matchup,
    generate_civ_war_lineup,
    rank_matchups,
    select_civ_matchup,
)
from plugins.games.aoe3_battle.lineup import format_vs_banner


@pytest.fixture(scope="module")
def repo() -> UnitRepo:
    return UnitRepo.get()


def test_identical_candidate_estimate_is_symmetric(repo: UnitRepo) -> None:
    candidate = next(
        candidate
        for candidate in generate_civ_candidates(repo, "British", age=3)
        if candidate.unit_ids == ("musketeer", "hussar")
    )
    estimate = estimate_matchup(candidate, candidate, age=3)
    assert estimate.advantage_log == pytest.approx(0.0, abs=1e-12)
    assert estimate.balance_gap == pytest.approx(0.0, abs=1e-12)


def test_ranked_matchups_are_bounded_and_sorted(repo: UnitRepo) -> None:
    red = generate_civ_candidates(repo, "Japanese", age=3)
    blue = generate_civ_candidates(repo, "Indians", age=3)
    ranked = rank_matchups(red, blue, age=3)
    assert len(ranked) <= 48 * 48
    assert [item.selection_score for item in ranked] == sorted(
        item.selection_score for item in ranked
    )


def test_select_matchup_is_reproducible_and_does_not_run_simulator(repo: UnitRepo) -> None:
    first = select_civ_matchup(
        repo,
        "DEEthiopians",
        "XPAztec",
        age=3,
        rng=random.Random(42),
    )
    second = select_civ_matchup(
        repo,
        "DEEthiopians",
        "XPAztec",
        age=3,
        rng=random.Random(42),
    )
    assert first.red_candidate.id == second.red_candidate.id
    assert first.blue_candidate.id == second.blue_candidate.id
    assert first.red_lineup.total_cost <= 10000
    assert first.blue_lineup.total_cost <= 10000


def test_select_matchup_rejects_same_civ(repo: UnitRepo) -> None:
    with pytest.raises(ValueError, match="distinct civilizations"):
        select_civ_matchup(repo, "British", "British")


def test_generate_public_civ_war_lineup_has_identity(repo: UnitRepo) -> None:
    match, estimate = generate_civ_war_lineup(
        repo,
        "British",
        "Japanese",
        age=3,
        rng=random.Random(7),
    )
    assert match.mode == "civ_war"
    assert match.red_civ_name == "英国"
    assert match.blue_civ_name == "日本"
    assert match.red_strategy == estimate.red_candidate.title
    assert match.blue_strategy == estimate.blue_candidate.title
    banner = format_vs_banner(match)
    assert "国战" in banner
    assert "英国" in banner and "日本" in banner
    assert match.red_strategy in banner and match.blue_strategy in banner
