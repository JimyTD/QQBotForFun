"""武器用途（ValidTargets）与 OpenRA WeaponInfo.IsValidTarget 对齐测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.games.ra2_battle.repo import load_actors, load_weapons
from plugins.games.ra2_battle.targeting import weapon_valid_against

_DATA = Path(__file__).resolve().parents[3] / "data" / "ra2" / "actors.json"


@pytest.fixture(scope="module")
def require_export():
    if not _DATA.is_file():
        pytest.skip("缺少 data/ra2，先运行 openra_ra2_export.py")


@pytest.fixture(scope="module")
def actors(require_export):
    return load_actors()


@pytest.fixture(scope="module")
def weapons(require_export):
    return load_weapons()


# (weapon_id, victim_id, expected) — 依据 vendor/openra-ra2/mods/ra2/weapons/*.yaml 继承链
_WEAPON_VS_VICTIM = [
    # 天启：主炮对地，导弹对空（^AAMissile）
    ("120mmx", "htnk", True),
    ("MammothTusk", "htnk", False),
    # 防空履带：机枪对地，高射炮对空
    ("FlakGuyGun", "htnk", True),
    ("FlakGuyAAGun", "htnk", False),
    ("FlakGuyGun", "flakt", True),
    ("FlakGuyAAGun", "flakt", False),
    # 潜艇鱼雷：水面/水下
    ("SubTorpedo", "dest", True),
    ("SubTorpedo", "htnk", False),
    ("120mm", "dest", True),
]


@pytest.mark.parametrize("weapon_id,victim_id,expected", _WEAPON_VS_VICTIM)
def test_weapon_valid_targets(
    weapons, actors, weapon_id: str, victim_id: str, expected: bool
):
    assert weapon_id in weapons, f"缺少武器 {weapon_id}"
    assert victim_id in actors, f"缺少单位 {victim_id}"
    got = weapon_valid_against(weapons[weapon_id], actors[victim_id])
    assert got is expected, (
        f"{weapon_id} vs {victim_id}: 期望 {expected}, "
        f"武器 valid={weapons[weapon_id].valid_targets or 'Ground,Water(default)'}, "
        f"目标 types={actors[victim_id].target_types}"
    )


def test_mammoth_tusk_exported_air_only(weapons):
    assert weapons["MammothTusk"].valid_targets == ("Air",)


def test_apoc_armaments_pairing(actors):
    arms = {a.weapon for a in actors["apoc"].armaments}
    assert "120mmx" in arms
    assert "MammothTusk" in arms
