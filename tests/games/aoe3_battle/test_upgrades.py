"""单位改良（科技加成）数据与运行时校验。

对应 docs/games/aoe3-battle.md §3.10 的「正确性保证」：
  - 标准/炮兵/类别曲线断言
  - 外部 oracle：帝王火枪 HP = 基础 ×2 = 300
  - 上界（抓重复计）
  - 运行时 apply_upgrades 出副本、不改原对象
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.aoe3.upgrades import apply_upgrades, get_multipliers

_DATA_PATH = (
    Path(__file__).resolve().parents[3] / "seeds" / "aoe3" / "unit_upgrades.json"
)


@pytest.fixture(scope="module")
def data():
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def repo():
    return UnitRepo.get()


@pytest.mark.parametrize("uid", ["musketeer", "skirmisher", "pikeman", "hussar",
                                 "crossbowman", "longbowman"])
def test_standard_curve(data, uid):
    """标准步骑（含散兵）= 100/120/150/200。"""
    e = data["units"][uid]
    assert e["3"]["hp_mult"] == 1.2
    assert e["4"]["hp_mult"] == 1.5
    assert e["5"]["hp_mult"] == 2.0
    assert e["5"]["damage_mult"] == 2.0


def test_artillery_curve(data):
    """炮兵 = 100/100/125/175（无精锐/近卫）。"""
    fal = data["units"]["falconet"]
    assert "3" not in fal
    assert fal["4"]["hp_mult"] == 1.25
    assert fal["5"]["hp_mult"] == 1.75


def test_category_curves(data):
    cat = data["category"]
    assert cat["AbstractOutlaw"]["5"]["hp_mult"] == 2.0
    assert cat["Mercenary"]["5"]["hp_mult"] == 1.5
    assert cat["AbstractNativeWarrior"]["5"]["hp_mult"] == 1.5


def test_imperial_musketeer_hp_oracle(repo, data):
    """外部 oracle（aoe3homecity）：帝王火枪 HP = 300。"""
    musk = repo.get_by_id("musketeer")
    assert round(musk.hp * data["units"]["musketeer"]["5"]["hp_mult"]) == 300


def test_no_double_counting(data):
    """逐兵 age5 mult 上界，抓重复计（RG 可略高，但不应 > 2.3）。"""
    for uid, e in data["units"].items():
        m5 = e.get("5", {}).get("hp_mult", 1.0)
        assert m5 <= 2.3, f"{uid} age5 hp_mult={m5} 疑似重复计"


def test_no_negative_increment(data):
    """血/攻改良只取正向；不应出现 <1 的 mult（削弱/置换已被过滤）。"""
    for uid, e in data["units"].items():
        for age, entry in e.items():
            for k in ("hp_mult", "damage_mult"):
                if k in entry:
                    assert entry[k] >= 1.0, f"{uid} age{age} {k}={entry[k]} 出现削弱"


def test_apply_upgrades_returns_copy(repo):
    """apply_upgrades 出副本，不污染原对象。"""
    musk = repo.get_by_id("musketeer")
    base_hp = musk.hp
    up = apply_upgrades(musk, 5)
    assert up is not musk
    assert up.hp == base_hp * 2
    assert musk.hp == base_hp  # 原对象不变
    assert up.attack_ranged == round(musk.attack_ranged * 2, 2)


def test_apply_upgrades_renames_unit(repo):
    """时代升级后兵种改名（SetName）。"""
    musk = repo.get_by_id("musketeer")
    assert musk.name == "火枪兵"
    up3 = apply_upgrades(musk, 3)
    assert up3.name == "老练火枪兵"
    up4 = apply_upgrades(musk, 4)
    assert up4.name == "护卫火枪兵"
    up5 = apply_upgrades(musk, 5)
    assert up5.name == "帝国火枪兵"


def test_apply_age2_noop(repo):
    """2 时代标准兵无军改，原样返回。"""
    musk = repo.get_by_id("musketeer")
    assert apply_upgrades(musk, 2) is musk


def test_outlaw_via_category(repo):
    """亡命徒走类别科技（无逐兵链）。"""
    # 找一个带 AbstractOutlaw 标签的单位
    outlaw = next(
        (u for u in repo.all_units if "AbstractOutlaw" in u.type and u.hp > 0),
        None,
    )
    assert outlaw is not None
    hp_mult, dmg_mult, source = get_multipliers(outlaw, 5)
    assert source == "AbstractOutlaw"
    assert hp_mult == 2.0


# ---------------- 逐兵 / 类别 max 去重 ----------------

def test_merc_category_not_suppressed_by_small_unit_tech(repo):
    """瑞士长枪有荷兰专属 +10% 逐兵小档，5 时代仍应吃到佣兵类别 +50%（max 去重）。"""
    swiss = repo.get_by_id("mercswisspikeman")
    if swiss is None:
        pytest.skip("无 mercswisspikeman")
    hp_mult, _, source = get_multipliers(swiss, 5)
    assert hp_mult == 1.5 and source == "Mercenary"
    # 低时代保留它自己更大的逐兵档
    hp3, _, src3 = get_multipliers(swiss, 3)
    assert hp3 == 1.1 and src3 == "unit"


# ---------------- 整包扩展：range / aoe / rof / 速度 / 护甲 / 倍率 ----------------

def test_range_integral_package(data):
    """阿布枪兵射程随 tier 链整包累加：+1/+2/+4（Veteran/Guard/Imperial）。"""
    e = data["units"]["abusgun"]
    assert e["3"]["range_add"]["ranged"] == 1.0
    assert e["4"]["range_add"]["ranged"] == 2.0
    assert e["5"]["range_add"]["ranged"] == 4.0


def test_apply_range_and_only_representative_action(repo):
    """apply 后阿布枪兵 5 时代射程 = 基础+4；近战不受远程动作影响。"""
    abus = repo.get_by_id("abusgun")
    up = apply_upgrades(abus, 5)
    assert up.range == round(abus.range + 4.0, 2)


def test_dirty_value_capped(data, repo):
    """脏数据护栏：DEEliteSlingersShadow 给 Volley +147 射程被丢弃，
    投石手 3 时代射程不变（只保留 Champion/Legendary 的 +1）。"""
    e = data["units"]["deslinger"]
    # age3 不应出现 +147 的射程
    assert e.get("3", {}).get("range_add", {}).get("ranged", 0) < 10
    sl = repo.get_by_id("deslinger")
    up3 = apply_upgrades(sl, 3)
    assert up3.range == sl.range  # 3 时代射程不变


def test_speed_integral(repo, data):
    """皮革炮速度随 tier 链整包提升（+0.5/+1.0）。"""
    e = data["units"]["deleathercannon"]
    assert e["4"]["speed_add"] == 0.5
    assert e["5"]["speed_add"] == 1.0
    cannon = repo.get_by_id("deleathercannon")
    up = apply_upgrades(cannon, 5)
    assert up.speed == round(cannon.speed + 1.0, 3)


def test_mult_add_only_existing_positive(repo):
    """倍率加成只作用于已存在的正倍率；不新建、不碰惩罚倍率。"""
    sl = repo.get_by_id("deslinger")
    up = apply_upgrades(sl, 4)
    art = next(m.value for m in up.multipliers_ranged if m.vs == "AbstractArtillery")
    assert art == 2.5  # 基础 2.0 + 0.5
    # 惩罚倍率（<1）保持不变
    for m in up.multipliers_ranged:
        if m.vs in ("AbstractCavalry", "AbstractLightInfantry"):
            assert m.value < 1.0


def test_no_upgrade_induced_outliers(repo):
    """升级不应把任何攻击单位的数据推成离谱值（隔离基础脏数据，仅看增量）。"""
    for u in repo.all_units:
        if not (u.attack_ranged or u.attack_melee):
            continue
        base_mr = {m.vs: m.value for m in u.multipliers_ranged}
        for age in (3, 4, 5):
            up = apply_upgrades(u, age)
            assert (up.range - u.range) <= 8.5, f"{u.id} age{age} 射程暴涨"
            assert up.speed <= max(12, u.speed * 1.8 + 0.01), f"{u.id} age{age} 速度暴涨"
            assert up.armor_ranged <= 0.95 or up.armor_ranged == u.armor_ranged
            for m in up.multipliers_ranged:
                if abs(m.value - base_mr.get(m.vs, m.value)) > 1e-6:
                    assert m.value <= 7, f"{u.id} age{age} 倍率 {m} 被升级推爆"
