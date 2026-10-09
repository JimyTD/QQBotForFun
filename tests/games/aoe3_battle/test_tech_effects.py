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


def test_apply_cost_absolute_and_assign(repo):
    """Cost 的 Absolute / Assign 都是固定值修正，不是百分比。"""
    crossbow = repo.get_by_id("crossbowman")
    lockbows = {
        "scope": ["crossbowman"],
        "ops": [
            {"stat": "cost", "kind": "set", "value": 0, "resource": "food"},
            {"stat": "cost", "kind": "add", "value": 20, "resource": "wood"},
        ],
    }
    up = _apply_one_tech(crossbow, lockbows, base=crossbow)
    assert up.cost.get("food", 0) == 0
    assert up.cost["wood"] == crossbow.cost.get("wood", 0) + 20


def test_apply_percent_relativity_multiplies(repo):
    """Percent 是比例乘法：0.8 = -20%，不是 +0.8%。"""
    crossbow = repo.get_by_id("crossbowman")
    tech = {
        "scope": ["crossbowman"],
        "ops": [{"stat": "cost", "kind": "percent", "value": 0.8, "resource": "wood"}],
    }
    up = _apply_one_tech(crossbow, tech, base=crossbow)
    assert up.cost["wood"] == round(crossbow.cost["wood"] * 0.8)

    hp = {
        "scope": ["crossbowman"],
        "ops": [{"stat": "hp", "kind": "percent", "value": 1.15}],
    }
    up = _apply_one_tech(crossbow, hp, base=crossbow)
    assert up.hp == round(crossbow.hp * 1.15, 1)


def test_allocate_lineup_counts_single(repo):
    """allocate_lineup_counts 按当前 cost 分配数量 (单兵种)。

    单价要用 ``UnitSlot.unit_cost`` (= 资源 + 人口折算的房子成本,
    见 lineup._unit_cost, a0295d8 起生效), 而不是 ``sum(cost.values())``。
    """
    import dataclasses

    from src.plugins.games.aoe3_battle.lineup import (
        Lineup,
        UnitSlot,
        allocate_lineup_counts,
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
    assert any("骑兵胸甲" in line for line in lines)
    assert any("🔴" in line for line in lines)


def test_runtime_tech_summary_uses_new_wording():
    tech = {
        "name_zh": "预备军",
        "scope": ["deinsurgente"],
        "ops": [
            {
                "stat": "action_enable",
                "kind": "set",
                "value": 1.0,
                "action": "VolleyRangedAttack",
            },
            {"stat": "initial_tactic", "kind": "set", "value": 1.0, "tactic": "Volley"},
        ],
    }
    text = format_tech_summary(
        tech["name_zh"],
        combat_ops=(
            {
                "subtype": "ActionEnable",
                "amount": 1.0,
                "relativity": "Assign",
                "action": "VolleyRangedAttack",
            },
            {"subtype": "InitialTactic", "amount": 1.0, "relativity": "Assign"},
        ),
    )
    assert text == "预备军：开启攻击：远程攻击，切换攻击方式"
    assert "解锁攻击" not in text
    assert "换成阵型" not in text


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
    assert pair == "【诸葛弩、轻骑兵】骑兵战斗力：生命+15%，全部攻击：伤害+15%"


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
    assert "对步兵伤害倍率+1" in summary
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


def test_action_scoped_range_ops_are_not_deduped(repo):
    """同一科技给多个动作各写一条时，每条都要落到自己的动作。"""
    longbow = repo.get_by_id("longbowman")
    tech = {
        "scope": ["longbowman"],
        "ops": [
            {
                "stat": "range",
                "kind": "add",
                "value": 4,
                "subtype": "MaximumRange",
                "action": "VolleyRangedAttack",
            },
            {
                "stat": "range",
                "kind": "add",
                "value": 4,
                "subtype": "MaximumRange",
                "action": "RangedBuildingAttack",
            },
            {
                "stat": "range",
                "kind": "add",
                "value": 3,
                "subtype": "MaximumRange",
                "action": "BuildingAttack",
            },
        ],
    }
    upgraded = _apply_one_tech(longbow, tech, base=longbow)
    by_name = {action.name: action for action in upgraded.attack_actions}
    assert by_name["VolleyRangedAttack"].range_max == 26
    assert by_name["RangedBuildingAttack"].range_max == 26
    assert by_name["BuildingAttack"].range_max == 9


def test_minimum_and_maximum_range_on_same_action_both_apply(repo):
    """DEHCFodioTactics 的 VolleyLongRangedAttack 同时改 min 与 max。"""
    tech = {
        "scope": ["defulawarrior"],
        "ops": [
            {
                "stat": "range",
                "kind": "add",
                "value": 3,
                "subtype": "MaximumRange",
                "action": "VolleyLongRangedAttack",
            },
            {
                "stat": "range",
                "kind": "add",
                "value": 3,
                "subtype": "MinimumRange",
                "action": "VolleyLongRangedAttack",
            },
        ],
    }
    unit = repo.get_by_id("defulawarrior")
    before = next(
        action for action in unit.attack_actions
        if action.name == "VolleyLongRangedAttack"
    )
    upgraded = _apply_one_tech(unit, tech, base=unit)
    after = next(
        action for action in upgraded.attack_actions
        if action.name == "VolleyLongRangedAttack"
    )
    assert after.range_max == before.range_max + 3
    assert after.range_min == before.range_min + 3


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
    assert summary == (
        "飞炮：移速+1.1，全部攻击："
        "攻击间隔-10%、攻击间隔-0.5秒、攻击间隔改为 2.75 秒"
    )


def test_tech_summary_names_the_attack_modes_it_changes():
    summary = format_tech_summary(
        "火龙经",
        combat_ops=(
            {
                "subtype": "RateOfFire",
                "amount": 0.9,
                "relativity": "BasePercent",
                "action": "CannonAttack",
            },
            {
                "subtype": "RateOfFire",
                "amount": 0.9,
                "relativity": "BasePercent",
                "action": "FlameAttack",
            },
        ),
    )
    assert summary == "火龙经：火炮攻击：攻击间隔-10%，火焰攻击：攻击间隔-10%"

    grouped = format_tech_summary(
        "卡纳里援助",
        combat_ops=(
            {
                "subtype": "RateOfFire",
                "amount": 0.8,
                "relativity": "BasePercent",
                "action": "CoverHandAttack",
            },
            {
                "subtype": "RateOfFire",
                "amount": 0.8,
                "relativity": "BasePercent",
                "action": "DefendHandAttack",
            },
            {
                "subtype": "RateOfFire",
                "amount": 0.8,
                "relativity": "BasePercent",
                "action": "MeleeHandAttack",
            },
        ),
    )
    assert grouped == "卡纳里援助：近战攻击：攻击间隔-20%"


def test_tech_summary_names_charge_and_action_targets():
    summary = format_tech_summary(
        "破甲剑",
        combat_ops=(
            {"subtype": "Damage", "amount": 1.1, "relativity": "BasePercent"},
            {
                "subtype": "DamageArea",
                "amount": 1.0,
                "relativity": "Absolute",
                "action": "LanceChargeAttack",
            },
            {"subtype": "RechargeTime", "amount": 0.6, "relativity": "BasePercent"},
            {
                "subtype": "MaximumRange",
                "amount": 2.0,
                "relativity": "Absolute",
                "action": "LanceChargeAttack",
            },
        ),
    )
    assert summary == (
        "破甲剑：全部攻击：伤害+10%，"
        "冲锋攻击：溅射范围+1、射程+2，蓄力冷却-40%"
    )

    opened = format_tech_summary(
        "预备军",
        combat_ops=(
            {
                "subtype": "ActionEnable",
                "amount": 1.0,
                "action": "VolleyRangedAttack",
            },
            {"subtype": "InitialTactic", "amount": 1.0},
        ),
    )
    assert opened == "预备军：开启攻击：远程攻击，切换攻击方式"


def test_tech_summary_uses_relativity_and_translated_types():
    summary = format_tech_summary(
        "锁弓",
        combat_ops=(
            {"subtype": "Damage", "amount": 1.3, "relativity": "BasePercent"},
            {
                "subtype": "ActionEnable",
                "amount": 1.0,
                "action": "LockRangedAttack",
            },
            {
                "subtype": "ActionEnable",
                "amount": 0.0,
                "action": "VolleyRangedAttack",
            },
            {
                "subtype": "MaximumRange",
                "amount": -2.0,
                "relativity": "Absolute",
                "action": "LockRangedAttack",
            },
        ),
        cost_ops=(
            {
                "subtype": "Cost",
                "amount": 0.0,
                "relativity": "Override",
                "resource": "Food",
            },
            {
                "subtype": "Cost",
                "amount": 20.0,
                "relativity": "Absolute",
                "resource": "Wood",
            },
        ),
    )
    assert summary == (
        "锁弓：全部攻击：伤害+30%，开启攻击：锁弓远程，"
        "关闭攻击：远程攻击，食物造价改为 0，木材造价+20，"
        "锁弓远程：射程-2"
    )

    bonus = format_tech_summary(
        "反骑兵战术",
        combat_ops=(
            {
                "subtype": "DamageBonus",
                "amount": 1.0,
                "relativity": "Absolute",
                "action": "BowAttack",
                "unittype": "AbstractHeavyCavalry",
            },
        ),
    )
    assert bonus.endswith("远程攻击：对重装骑兵伤害倍率+1")


def test_tech_summary_hides_internal_abilities_and_caps_length():
    summary = format_tech_summary(
        "十字军骑士",
        combat_ops=(
            {"subtype": "ActionEnable", "amount": 1.0, "action": "Stealth"},
            {"subtype": "ActionEnable", "amount": 1.0, "action": "Discover"},
            {
                "subtype": "ActionEnable",
                "amount": 0.0,
                "action": "IncreaseHPWithFortifications",
            },
            *(
                {
                    "subtype": "RateOfFire",
                    "amount": 0.9,
                    "relativity": "BasePercent",
                    "action": action,
                }
                for action in (
                    "CannonAttack",
                    "FlameAttack",
                    "BuildingAttack",
                    "MeleeHandAttack",
                    "VolleyRangedAttack",
                        "ChargeAttack",
                        "BowAttack",
                        "BombardAttack",
                        "CaseShotAttack",
                        "BarrageAttack",
                    )
                ),
        ),
    )
    assert "IncreaseHPWithFortifications" not in summary
    assert "开启能力：潜行" in summary
    assert "等 " in summary
    assert len(summary) < 120


def test_tech_summary_caps_recipient_list():
    summary = format_tech_summary(
        "西方改革",
        combat_ops=({"subtype": "Damage", "amount": 1.08, "relativity": "BasePercent"},),
        recipients=("中国连弩兵", "中国长矛兵", "火绳枪兵", "怯薛", "草原骑兵"),
    )
    assert summary == "【中国连弩兵、中国长矛兵、火绳枪兵 等 5 个兵种】西方改革：全部攻击：伤害+8%"


def test_tech_summary_falls_back_to_name_for_unknown_ops():
    assert format_tech_summary(
        "未知科技",
        combat_ops=({"subtype": "SomethingNew", "amount": 1.0},),
    ) == "未知科技"
