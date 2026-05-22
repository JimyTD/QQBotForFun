"""索敌优先级与 OpenRA AutoTarget ValidTargets 顺序对齐。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.games.ra2_battle.repo import load_actors
from plugins.games.ra2_battle.targeting import (
    auto_target_sort_key,
    auto_target_type_rank,
    merged_valid_targets_ordered,
)

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


@pytest.fixture(scope="module")
def actors(require_export):
    return load_actors()


def test_merged_valid_targets_ordered_from_yaml(actors):
    apoc = actors["apoc"]
    order = merged_valid_targets_ordered(apoc)
    assert len(order) >= 1
    assert order == tuple(dict.fromkeys(order))


def test_auto_target_type_rank_uses_first_matching_category(actors):
    apoc = actors["apoc"]
    htnk = actors["htnk"]
    rank = auto_target_type_rank(apoc, htnk)
    order = merged_valid_targets_ordered(apoc)
    cats = set(htnk.target_types) | {"Ground", "Vehicle"}
    assert order[rank] in cats


def test_sort_key_in_range_before_distance(actors):
    apoc = actors["apoc"]
    near = actors["e1"]
    key_in = auto_target_sort_key(
        apoc, near, in_weapon_range=True, distance=9999, target_hp=100
    )
    key_out = auto_target_sort_key(
        apoc, near, in_weapon_range=False, distance=1, target_hp=100
    )
    assert key_in < key_out
