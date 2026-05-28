"""王中王主题池与阵容生成测试。"""

from __future__ import annotations

import random

import pytest

from plugins.games.aoe3_battle.lineup import generate_rival_lineup, get_bet_pool
from plugins.games.aoe3_battle.rival_themes import (
    RIVAL_THEMES,
    filter_theme_pool,
    pick_random_themes,
    resolve_theme,
)
from plugins.aoe3.repository import UnitRepo


@pytest.fixture(scope="module")
def repo():
    return UnitRepo.get()


@pytest.fixture(scope="module")
def bet_pool(repo):
    return get_bet_pool(repo)


@pytest.mark.parametrize(
    ("token", "expected_id"),
    [
        ("散兵", "skirmisher"),
        ("火枪王", "musketeer"),
        ("近战重步", "melee_heavy"),
        ("炮兵", "artillery"),
        ("mercenary", "mercenary"),
    ],
)
def test_resolve_theme(token, expected_id):
    t = resolve_theme(token)
    assert t is not None
    assert t.id == expected_id


def test_theme_pool_sizes(repo, bet_pool):
    """与文档 §2.5 封板规模大致一致（允许数据更新小幅漂移）。"""
    expected_min = {
        "skirmisher": 90,
        "musketeer": 55,
        "melee_heavy": 60,
        "archer": 40,
        "grenadier": 10,
        "hand_cavalry": 85,
        "ranged_cavalry": 65,
        "artillery": 30,
        "outlaw": 45,
        "mercenary": 55,
    }
    for theme in RIVAL_THEMES:
        pool = filter_theme_pool(bet_pool, theme)
        assert len(pool) >= expected_min[theme.id], theme.id


def test_archer_excludes_ranged_cavalry(bet_pool):
    theme = resolve_theme("弓手王")
    assert theme is not None
    pool = filter_theme_pool(bet_pool, theme)
    for u in pool:
        assert "AbstractRangedCavalry" not in u.type


def test_pick_random_themes_unique():
    rng = random.Random(0)
    opts = pick_random_themes(count=3, rng=rng)
    assert len(opts) == 3
    assert len({t.id for t in opts}) == 3


def test_generate_rival_lineup(repo):
    rng = random.Random(42)
    result = generate_rival_lineup(repo, "skirmisher", budget=10000, rng=rng)
    assert not isinstance(result, str)
    assert result.mode == "rival"
    assert result.rival_theme == "散兵王"
    assert len(result.red.slots) == 1
    assert len(result.blue.slots) == 1
    assert result.red.count >= 1
    assert result.blue.count >= 1
