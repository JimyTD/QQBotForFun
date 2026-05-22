"""阵容随机：槽位数、LCM、出战星级。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.games.ra2_battle.lineup import (
    INITIAL_STAR_OPTIONS,
    approx_lcm_budget,
    generate_bet_lineup,
    roll_initial_stars,
)

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


def test_slot_count_only_one_or_two(require_export):
    for seed in range(50):
        m = generate_bet_lineup(budget=5000, seed=seed)
        assert 1 <= len(m.red.slots) <= 2
        assert 1 <= len(m.blue.slots) <= 2


def test_initial_stars_in_options(require_export):
    for seed in range(30):
        m = generate_bet_lineup(budget=5000, seed=seed)
        assert m.initial_stars in INITIAL_STAR_OPTIONS


def test_roll_initial_stars_distribution():
    import random

    rng = random.Random(42)
    seen = {roll_initial_stars(rng) for _ in range(300)}
    assert seen == set(INITIAL_STAR_OPTIONS)


def test_lcm_single_vs_single_closer_spend(require_export):
    m = generate_bet_lineup(budget=5000, seed=7)
    if m.red.is_multi or m.blue.is_multi:
        pytest.skip("本 seed 非单兵种，换测 approx_lcm_budget")
    diff = abs(m.red.total_cost - m.blue.total_cost)
    assert diff <= 5000 * 0.35


def test_approx_lcm_budget_within_tolerance():
    base = 5000
    actual = approx_lcm_budget(900, 1500, base)
    assert int(base * 0.7) <= actual <= int(base * 1.3)
