"""斗蛐蛐阵容池、黑名单与全兵种/星级/规模 smoke 覆盖。"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from plugins.games.ra2_battle.battle_pool import (
    LINEUP_BLACKLIST,
    is_lineup_eligible,
    lineup_eligible_ids,
)
from plugins.games.ra2_battle.lineup import generate_bet_lineup, generate_duel_lineup
from plugins.games.ra2_battle.repo import load_actors
from plugins.games.ra2_battle.simulator import BattleSimulator, EventType

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"

# 固定对手：便宜步兵，便于各兵种单独跑通
_CANNON_FODDER = ("e1", 3, 0)

# 特殊机制代表性对阵（名称, 红方, 蓝方, 最低 tick 事件类型可选）
_SPECIAL_MATCHUPS: list[tuple[str, list, list, set[EventType] | None]] = [
    ("心控_尤里", [("yuri", 1, 1)], [("htnk", 1, 0)], {EventType.MIND_CONTROL}),
    ("心控_心灵突击队", [("ptroop", 1, 1)], [("e1", 4, 0)], {EventType.MIND_CONTROL}),
    ("航母_黄蜂", [("carrier", 1, 0)], [("e1", 6, 0)], {EventType.SPAWN_CHILD, EventType.ATTACK}),
    ("辐射_辐射兵", [("deso", 2, 1)], [("e1", 8, 0)], {EventType.ATTACK}),
    ("磁能_坦克", [("ttnk", 1, 1)], [("mtnk", 2, 0)], {EventType.ATTACK}),
    ("天启_导弹仅对空", [("apoc", 1, 3)], [("htnk", 3, 0)], {EventType.ATTACK}),
    ("防空履带", [("htk", 2, 0)], [("e1", 8, 0)], {EventType.ATTACK}),
    ("神盾_防空舰", [("aegis", 1, 1)], [("e1", 6, 0)], {EventType.ATTACK}),
    ("潜艇", [("sub", 1, 1)], [("dest", 1, 0)], {EventType.ATTACK}),
    ("超时空兵团", [("ccomand", 1, 1)], [("e1", 5, 0)], {EventType.ATTACK}),
    ("超时空军团", [("cleg", 1, 1)], [("e1", 5, 0)], {EventType.ATTACK}),
    ("警犬", [("dog", 3, 0)], [("e1", 5, 0)], {EventType.ATTACK, EventType.DEATH}),
    ("自爆卡车", [("dtruck", 1, 0)], [("htnk", 1, 0)], {EventType.ATTACK, EventType.DEATH}),
    ("恐怖分子", [("terror", 4, 0)], [("e1", 4, 0)], {EventType.ATTACK}),
    ("谭雅", [("tany", 1, 3)], [("e1", 6, 0)], {EventType.ATTACK}),
    ("幻影坦克", [("mgtk", 1, 1)], [("htnk", 2, 0)], {EventType.ATTACK}),
    ("光棱坦克", [("sref", 1, 1)], [("htnk", 2, 0)], {EventType.ATTACK}),
    ("战斗要塞IFV", [("fv", 1, 1)], [("e1", 6, 0)], {EventType.ATTACK}),
]


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


@pytest.fixture(scope="module")
def actors(require_export):
    return load_actors()


@pytest.fixture(scope="module")
def eligible_ids(actors):
    return lineup_eligible_ids(actors)


def _run(red, blue, *, seed: int = 0, max_ticks: int = 5000) -> BattleSimulator:
    return BattleSimulator(
        red,
        blue,
        seed=seed,
        max_ticks=max_ticks,
        width=14,
        height=8,
    ).run()


def test_blacklist_documented_and_enforced(actors, eligible_ids):
    for bid, reason in LINEUP_BLACKLIST.items():
        assert bid in actors, f"黑名单 id {bid} 不在 actors.json"
        assert not is_lineup_eligible(actors[bid]), reason
    assert "engineer" in LINEUP_BLACKLIST
    assert "cmin" in LINEUP_BLACKLIST
    assert "harv" not in LINEUP_BLACKLIST
    assert "hornet" not in LINEUP_BLACKLIST
    assert actors["hornet"].spawn_only
    assert not is_lineup_eligible(actors["hornet"])


def test_harv_in_pool_cmin_blacklisted(actors, eligible_ids):
    assert "harv" in eligible_ids
    assert "cmin" not in eligible_ids
    assert not is_lineup_eligible(actors["cmin"])


def test_chrono_units_in_pool(actors, eligible_ids):
    assert "ccomand" in eligible_ids
    assert "cleg" in eligible_ids


def test_random_lineup_never_draws_blacklist(require_export):
    for seed in range(30):
        m = generate_bet_lineup(budget=5000, seed=seed)
        for side in (m.red, m.blue):
            for slot in side.slots:
                assert slot.actor_id not in LINEUP_BLACKLIST
                assert slot.actor_id not in ("hornet", "asw")


@pytest.mark.parametrize("stars", [0, 1, 3])
def test_star_ratings_htnk_vs_e1(require_export, stars: int):
    r = _run([("htnk", 1, stars)], [_CANNON_FODDER], seed=stars * 11)
    assert r.ticks > 0
    assert r.winner is not None or r.duration > 0
    if stars >= 1:
        lvl = [
            e.payload.get("attacker_level", 0)
            for e in r.events
            if e.type == EventType.ATTACK and e.payload.get("attacker") == "htnk"
        ]
        if lvl:
            assert max(lvl) >= 1


@pytest.mark.parametrize(
    "red, blue, note",
    [
        (("e1", 1, 1), ("e2", 20, 1), "少打多"),
        (("e1", 25, 1), ("e2", 3, 1), "多打少"),
        (("htnk", 1, 3), ("htnk", 1, 1), "三星打一星"),
        (("htnk", 5, 1), ("mtnk", 2, 1), "多坦克少坦克"),
    ],
)
def test_quantity_and_star_mix(require_export, red, blue, note: str):
    r = _run([red], [blue], seed=hash(note) % 10000)
    assert r.ticks > 0


@pytest.mark.parametrize(
    "title, red, blue, expect_types",
    _SPECIAL_MATCHUPS,
    ids=[m[0] for m in _SPECIAL_MATCHUPS],
)
def test_special_matchup(
    require_export,
    title: str,
    red: list,
    blue: list,
    expect_types: set[EventType] | None,
):
    r = _run(red, blue, seed=abs(hash(title)) % 10000, max_ticks=8000)
    assert r.ticks > 0, f"{title} 未推进"
    if expect_types:
        got = {e.type for e in r.events}
        assert expect_types & got, f"{title} 缺少事件 {expect_types - got}"


_ELIGIBLE_FOR_PARAM = (
    lineup_eligible_ids() if _DATA.is_file() else ["__skip__"]
)


@pytest.mark.parametrize("actor_id", _ELIGIBLE_FOR_PARAM)
def test_each_eligible_unit_completes(require_export, actor_id: str):
    """阵容池内每个兵种至少能跑完一局（胜/负/平均可）。"""
    r = _run([(actor_id, 1, 0)], [_CANNON_FODDER], seed=hash(actor_id) % 100000, max_ticks=6000)
    assert r.ticks > 0
    types = {e.type for e in r.events}
    assert EventType.BATTLE_START in types
    assert EventType.BATTLE_END in types
