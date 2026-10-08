"""已选科技效果的运行时应用测试。"""
from __future__ import annotations

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.aoe3.tech_effects import (
    _apply_one_tech,
    apply_techs,
    format_tech_lines,
)
from src.plugins.games.aoe3_battle.tech_summary import format_tech_summary


@pytest.fixture(scope="module")
def repo() -> UnitRepo:
    return UnitRepo.get()


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
    assert up.hp == round(hussar.hp + hussar.hp * 0.1, 1)
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
    for action in up.attack_actions:
        base_action = next(a for a in skirm.attack_actions if a.name == action.name)
        assert action.damage == round(base_action.damage + base_action.damage * 0.15, 2)


def test_apply_hp_additive_on_tier(repo):
    """tier 已乘 1.5 后，横向科技 +15% 应加算于 base 而非乘在 tier 上。"""
    import dataclasses
    musk_base = repo.get_by_id("musketeer")
    musk_tier = dataclasses.replace(
        musk_base,
        hp=round(musk_base.hp * 1.5, 1),
    )
    tech = {"scope": ["AbstractInfantry"], "ops": [
        {"stat": "hp", "kind": "mult", "value": 1.15}
    ]}
    up = _apply_one_tech(musk_tier, tech, base=musk_base)
    # 正确：base × 1.5 + base × 0.15 = base × 1.65
    expected = round(musk_base.hp * 1.5 + musk_base.hp * 0.15, 1)
    assert up.hp == expected
    # 错误（旧连乘）：base × 1.5 × 1.15 = base × 1.725
    wrong = round(musk_base.hp * 1.5 * 1.15, 1)
    assert up.hp != wrong or expected == wrong  # 若恰好数值相同也不误报


def test_apply_speed_debuff(repo):
    """细红线 → 火枪 +20% 血 −10% 速。"""
    musk = repo.get_by_id("musketeer")
    thin_red = {"scope": ["musketeer"], "ops": [
        {"stat": "hp", "kind": "mult", "value": 1.2},
        {"stat": "speed", "kind": "mult", "value": 0.9},
    ]}
    up = _apply_one_tech(musk, thin_red, base=musk)
    assert up.hp == round(musk.hp + musk.hp * 0.2, 1)
    assert up.speed == round(musk.speed * 0.9, 3)


def test_apply_scope_miss(repo):
    """scope 不命中 → 原样返回。"""
    musk = repo.get_by_id("musketeer")
    arty_tech = {"scope": ["AbstractArtillery"], "ops": [
        {"stat": "hp", "kind": "mult", "value": 1.1}
    ]}
    up = _apply_one_tech(musk, arty_tech, base=musk)
    assert up is musk


def test_apply_techs_list(repo):
    """apply_techs 对列表逐个叠加（加算于 base）。"""
    musk = repo.get_by_id("musketeer")
    techs = [
        {"scope": ["AbstractInfantry"], "ops": [
            {"stat": "hp", "kind": "mult", "value": 1.15}
        ]},
        {"scope": ["AbstractGunpowderTrooper"], "ops": [
            {"stat": "damage", "kind": "mult", "value": 1.15, "action": None, "allactions": True}
        ]},
    ]
    result = apply_techs([musk], techs, base_units=[musk])
    assert len(result) == 1
    up = result[0]
    # 加算：hp + base_hp × 0.15
    assert up.hp == round(musk.hp + musk.hp * 0.15, 1)
    for action in up.attack_actions:
        base_action = next(a for a in musk.attack_actions if a.name == action.name)
        assert action.damage == round(base_action.damage + base_action.damage * 0.15, 2)


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
    """allocate_lineup_counts 按当前 cost 分配数量 (单兵种)。

    单价要用 ``UnitSlot.unit_cost`` (= 资源 + 人口折算的房子成本,
    见 lineup._unit_cost, a0295d8 起生效), 而不是 ``sum(cost.values())``。
    """
    import dataclasses
    from src.plugins.games.aoe3_battle.lineup import (
        Lineup, UnitSlot, allocate_lineup_counts,
    )
    musk = repo.get_by_id("musketeer")
    budget = 1000
    full_cost = UnitSlot(musk, 1).unit_cost

    lineup = Lineup(slots=[UnitSlot(musk, 1)])
    allocate_lineup_counts(lineup, budget)
    assert lineup.slots[0].count == max(1, budget // full_cost)

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


def test_tech_summary_uses_player_facing_effect_names():
    summary = format_tech_summary(
        "细细的红线",
        combat_ops=(
            {"subtype": "Hitpoints", "amount": 1.2, "relativity": "BasePercent"},
            {"subtype": "MaximumVelocity", "amount": 0.9, "relativity": "BasePercent"},
        ),
    )
    assert summary == "细细的红线：生命+20%，移速-10%"
    labeled = format_tech_summary(
        "细细的红线",
        combat_ops=(
            {"subtype": "Hitpoints", "amount": 1.2, "relativity": "BasePercent"},
        ),
        recipients=("火枪兵", "火枪兵"),
    )
    assert labeled == "【火枪兵】细细的红线：生命+20%"
    pair = format_tech_summary(
        "骑兵战斗力",
        combat_ops=(
            {"subtype": "Hitpoints", "amount": 1.15, "relativity": "BasePercent"},
            {"subtype": "Damage", "amount": 1.15, "relativity": "BasePercent"},
        ),
        recipients=("诸葛弩", "轻骑兵"),
    )
    assert pair == "【诸葛弩、轻骑兵】骑兵战斗力：生命+15%，攻击+15%"


def test_tech_summary_describes_cost_and_counter():
    summary = format_tech_summary(
        "旧朝改革",
        combat_ops=(
            {
                "subtype": "DamageBonus",
                "amount": 1.0,
                "unittype": "AbstractInfantry",
            },
        ),
        cost_ops=(
            {
                "subtype": "Cost",
                "amount": 1.25,
                "relativity": "BasePercent",
                "resource": "food",
            },
        ),
    )
    assert "对步兵伤害+1" in summary
    assert "食物造价+25%" in summary


def test_apply_rof_percent_and_absolute(repo):
    """BasePercent 按基础间隔加算，Absolute 加减秒，下限 0.1 秒。"""
    falconet = repo.get_by_id("falconet")
    cannon_base = next(a for a in falconet.attack_actions if a.name == "CannonAttack")
    assert falconet is not None and cannon_base.rof == 4.0
    faster = {
        "scope": ["falconet"],
        "ops": [{
            "stat": "rof",
            "kind": "mult",
            "value": 0.9,
            "action": "CannonAttack",
        }],
    }
    percent = _apply_one_tech(falconet, faster, base=falconet)
    cannon = next(action for action in percent.attack_actions if action.name == "CannonAttack")
    assert cannon.rof == 3.6

    quicker = {
        "scope": ["falconet"],
        "ops": [{
            "stat": "rof",
            "kind": "add",
            "value": -0.5,
            "action": "CannonAttack",
        }],
    }
    absolute = _apply_one_tech(falconet, quicker, base=falconet)
    cannon = next(action for action in absolute.attack_actions if action.name == "CannonAttack")
    assert cannon.rof == 3.5


def test_named_and_allactions_range_do_not_stack_on_one_action(repo):
    musk = repo.get_by_id("musketeer")
    tech = {
        "scope": ["musketeer"],
        "ops": [
            {
                "stat": "range",
                "kind": "add",
                "value": 2,
                "action": "VolleyRangedAttack",
                "subtype": "MaximumRange",
            },
            {
                "stat": "range",
                "kind": "add",
                "value": 5,
                "allactions": True,
                "subtype": "MaximumRange",
            },
            {
                "stat": "range",
                "kind": "add",
                "value": 1,
                "action": "VolleyHandAttack",
                "subtype": "MaximumRange",
            },
        ],
    }
    upgraded = _apply_one_tech(musk, tech, base=musk)
    by_name = {action.name: action for action in upgraded.attack_actions}
    assert by_name["VolleyRangedAttack"].range_max == 17
    assert by_name["VolleyHandAttack"].range_max == 6.75
    assert by_name["BuildingAttack"].range_max == 11


def test_tech_summary_keeps_velocity_and_rof_relativity():
    summary = format_tech_summary(
        "飞炮",
        combat_ops=(
            {
                "subtype": "MaximumVelocity",
                "amount": 1.1,
                "relativity": "Absolute",
            },
            {
                "subtype": "RateOfFire",
                "amount": 0.9,
                "relativity": "BasePercent",
            },
            {
                "subtype": "RateOfFire",
                "amount": -0.5,
                "relativity": "Absolute",
            },
            {
                "subtype": "RateOfFire",
                "amount": 2.75,
                "relativity": "Assign",
            },
        ),
    )
    assert summary == "飞炮：移速+1.1，射击间隔-10%，射击间隔-0.5秒，射击间隔改为 2.75 秒"


def test_tech_summary_falls_back_to_name_for_unknown_ops():
    assert format_tech_summary(
        "未知科技",
        combat_ops=({"subtype": "SomethingNew", "amount": 1.0},),
    ) == "未知科技"
