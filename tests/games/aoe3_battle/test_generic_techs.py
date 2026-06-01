"""通用科技（roguelike 横向加成）测试。

覆盖：
  - 数据加载 + 基本完整性
  - 选择逻辑：age 门槛、相关性过滤、每方 K/2
  - 应用逻辑：hp/damage mult、速度双刃、射程加成、scope 不命中不生效
  - 战报展示
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.aoe3.generic_techs import (
    _apply_one_tech,
    _load,
    apply_generic_techs,
    format_tech_lines,
    select_techs,
)


@pytest.fixture(scope="module")
def repo() -> UnitRepo:
    return UnitRepo.get()


# ------------------------------------------------------------------
# 数据加载
# ------------------------------------------------------------------

def test_load_nonempty():
    techs = _load()
    assert len(techs) >= 20, f"通用科技池太小：{len(techs)}"


def test_all_techs_have_required_fields():
    for t in _load():
        assert "id" in t and "name_zh" in t and "scope" in t and "ops" in t
        assert t["age"] in (2, 3, 4, 5), f"{t['id']} age={t['age']}"
        assert len(t["scope"]) > 0
        assert len(t["ops"]) > 0


# ------------------------------------------------------------------
# 选择逻辑
# ------------------------------------------------------------------

def test_select_age_gate(repo):
    """age2 时不应选到 age3+ 的科技。"""
    musk = repo.get_by_id("musketeer")
    rng = random.Random(42)
    red, blue = select_techs([musk], [musk], age=2, k=4, rng=rng)
    all_techs = red + blue
    for t in all_techs:
        assert t["age"] <= 2, f"age2 局选到了 {t['id']}(age{t['age']})"


def test_select_relevance(repo):
    """纯炮兵双方 → 不应选到骑兵/步兵科技。"""
    falconet = repo.get_by_id("falconet")
    rng = random.Random(123)
    red, blue = select_techs([falconet], [falconet], age=5, k=4, rng=rng)
    arty_tags = set(falconet.type) | {falconet.id}
    for t in red + blue:
        assert any(s in arty_tags for s in t["scope"]), \
            f"炮兵局选到不相关科技 {t['id']} scope={t['scope']}"


def test_select_k_per_side(repo):
    """k=4 → 每方 ≤2 条。"""
    musk = repo.get_by_id("musketeer")
    rng = random.Random(99)
    red, blue = select_techs([musk], [musk], age=5, k=4, rng=rng)
    assert len(red) <= 2
    assert len(blue) <= 2


def test_select_k2_duel(repo):
    """k=2 → 每方 ≤1 条。"""
    musk = repo.get_by_id("musketeer")
    rng = random.Random(77)
    red, blue = select_techs([musk], [musk], age=5, k=2, rng=rng)
    assert len(red) <= 1
    assert len(blue) <= 1


# ------------------------------------------------------------------
# 应用逻辑
# ------------------------------------------------------------------

def test_apply_hp_mult(repo):
    """骑兵胸甲 → 重骑兵 +10% 血（加算于 base）。"""
    hussar = repo.get_by_id("hussar")
    cuirass = {"scope": ["AbstractHeavyCavalry"], "ops": [
        {"stat": "hp", "kind": "mult", "value": 1.1}
    ]}
    if "AbstractHeavyCavalry" not in hussar.type:
        pytest.skip("hussar 不是重骑")
    up = _apply_one_tech(hussar, cuirass, base=hussar)
    # 加算：hp + base_hp × (1.1 - 1) = hp + base_hp × 0.1
    assert up.hp == round(hussar.hp + hussar.hp * 0.1)
    assert up is not hussar


def test_apply_damage_mult(repo):
    """纸包弹 → 火药步兵 +15% 攻（加算于 base）。"""
    skirm = repo.get_by_id("skirmisher")
    paper = {"scope": ["AbstractGunpowderTrooper"], "ops": [
        {"stat": "damage", "kind": "mult", "value": 1.15, "action": None, "allactions": True}
    ]}
    if "AbstractGunpowderTrooper" not in skirm.type:
        pytest.skip("skirmisher 不是火药步兵")
    up = _apply_one_tech(skirm, paper, base=skirm)
    assert up.attack_ranged == round(skirm.attack_ranged + skirm.attack_ranged * 0.15, 2)


def test_apply_hp_additive_on_tier(repo):
    """tier 已乘 1.5 后，通用科技 +15% 应加算于 base 而非乘在 tier 上。"""
    import dataclasses
    musk_base = repo.get_by_id("musketeer")
    musk_tier = dataclasses.replace(musk_base, hp=round(musk_base.hp * 1.5))
    tech = {"scope": ["AbstractInfantry"], "ops": [
        {"stat": "hp", "kind": "mult", "value": 1.15}
    ]}
    up = _apply_one_tech(musk_tier, tech, base=musk_base)
    # 正确：base × 1.5 + base × 0.15 = base × 1.65
    expected = round(musk_base.hp * 1.5 + musk_base.hp * 0.15)
    assert up.hp == expected
    # 错误（旧连乘）：base × 1.5 × 1.15 = base × 1.725
    wrong = round(musk_base.hp * 1.5 * 1.15)
    assert up.hp != wrong or expected == wrong  # 若恰好数值相同也不误报


def test_apply_speed_debuff(repo):
    """细红线 → 火枪 +20% 血 −10% 速。"""
    musk = repo.get_by_id("musketeer")
    thin_red = {"scope": ["musketeer"], "ops": [
        {"stat": "hp", "kind": "mult", "value": 1.2},
        {"stat": "speed", "kind": "mult", "value": 0.9},
    ]}
    up = _apply_one_tech(musk, thin_red, base=musk)
    assert up.hp == round(musk.hp + musk.hp * 0.2)
    assert up.speed == round(musk.speed * 0.9, 3)


def test_apply_scope_miss(repo):
    """scope 不命中 → 原样返回。"""
    musk = repo.get_by_id("musketeer")
    arty_tech = {"scope": ["AbstractArtillery"], "ops": [
        {"stat": "hp", "kind": "mult", "value": 1.1}
    ]}
    up = _apply_one_tech(musk, arty_tech, base=musk)
    assert up is musk


def test_apply_generic_techs_list(repo):
    """apply_generic_techs 对列表逐个叠加（加算于 base）。"""
    musk = repo.get_by_id("musketeer")
    techs = [
        {"scope": ["AbstractInfantry"], "ops": [
            {"stat": "hp", "kind": "mult", "value": 1.15}
        ]},
        {"scope": ["AbstractGunpowderTrooper"], "ops": [
            {"stat": "damage", "kind": "mult", "value": 1.15, "action": None, "allactions": True}
        ]},
    ]
    result = apply_generic_techs([musk], techs, base_units=[musk])
    assert len(result) == 1
    up = result[0]
    # 加算：hp + base_hp × 0.15
    assert up.hp == round(musk.hp + musk.hp * 0.15)
    assert up.attack_ranged == round(musk.attack_ranged + musk.attack_ranged * 0.15, 2)


# ------------------------------------------------------------------
# Cost 修改 + 数量分配
# ------------------------------------------------------------------

def test_apply_cost_effect(repo):
    """cost mult 应加算在 base cost 上。"""
    musk = repo.get_by_id("musketeer")
    base_gold = musk.cost.get("gold", 0)
    assert base_gold > 0
    tech = {"scope": ["AbstractGunpowderTrooper"], "ops": [
        {"stat": "cost", "kind": "mult", "value": 0.75, "resource": "gold"},
    ]}
    up = _apply_one_tech(musk, tech, base=musk)
    expected = max(0, round(base_gold + base_gold * (0.75 - 1.0)))
    assert up.cost["gold"] == expected


def test_allocate_lineup_counts_single(repo):
    """allocate_lineup_counts 按当前 cost 分配数量（单兵种）。"""
    import dataclasses
    from src.plugins.games.aoe3_battle.lineup import (
        Lineup, UnitSlot, allocate_lineup_counts,
    )
    musk = repo.get_by_id("musketeer")
    budget = 1000
    old_cost = sum(musk.cost.values())

    lineup = Lineup(slots=[UnitSlot(musk, 1)])
    allocate_lineup_counts(lineup, budget)
    assert lineup.slots[0].count == max(1, budget // old_cost)

    half_cost = {k: max(1, v // 2) for k, v in musk.cost.items()}
    cheap_musk = dataclasses.replace(musk, cost=half_cost)
    lineup2 = Lineup(slots=[UnitSlot(cheap_musk, 1)])
    allocate_lineup_counts(lineup2, budget)
    assert lineup2.slots[0].count > lineup.slots[0].count


# ------------------------------------------------------------------
# 战报展示
# ------------------------------------------------------------------

def test_format_tech_lines_empty():
    assert format_tech_lines([], []) == []


def test_format_tech_lines_content():
    t = {"name_zh": "骑兵胸甲", "scope": ["AbstractHeavyCavalry"], "ops": [
        {"stat": "hp", "kind": "mult", "value": 1.1}
    ]}
    lines = format_tech_lines([t], [])
    assert any("骑兵胸甲" in l for l in lines)
    assert any("🔴" in l for l in lines)
