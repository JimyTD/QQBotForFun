"""每一条科技效果只打它写明的兵、写明的攻击，不认识的效果不能静默丢掉。

例子都是能在配兵或国战里选到的真实科技，见 docs/wip/aoe3-tech-effects.md。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.aoe3.tech_effects import apply_techs, op_targets_unit
from plugins.games.aoe3_battle import civ_war_techs as cwt
from plugins.games.aoe3_battle.lineup_draft import draft_units


@pytest.fixture(scope="module")
def repo() -> UnitRepo:
    return UnitRepo.get()


def _resolve(repo: UnitRepo, tech_id: str, civ_id: str, unit_ids: tuple[str, ...], age: int = 5):
    units = tuple(repo.get_by_id(unit_id) for unit_id in unit_ids)
    assert all(units)
    candidate = SimpleNamespace(
        id="check",
        civ_id=civ_id,
        units=units,
        source="custom",
        required_tech_ids=(tech_id,),
    )
    tech = cwt.resolve_required_techs(candidate, age=age)[0]
    return tech, {unit.id: unit for unit in units}


def _settle(tech, unit):
    return apply_techs([unit], [tech.runtime_tech()], base_units=[unit])[0]


def _damage(unit, name: str) -> float:
    return next(action.damage for action in unit.attack_actions if action.name == name)


def test_siege_archery_gives_the_ranger_buff_only_to_the_ranger(repo):
    """攻城箭术：生命、攻击 +15% 只写给游骑兵，长弓兵只换建筑攻击。"""
    tech, units = _resolve(repo, "DEHCSiegeArchery", "British", ("longbowman", "deranger"))
    longbow = _settle(tech, units["longbowman"])
    ranger = _settle(tech, units["deranger"])
    assert longbow.hp == units["longbowman"].hp == 95
    assert _damage(longbow, "VolleyRangedAttack") == _damage(units["longbowman"], "VolleyRangedAttack")
    assert ranger.hp == 109.2
    assert tech.summary == (
        "攻城箭术：【长弓兵】开启攻击：远程建筑攻击，关闭攻击：建筑攻击；"
        "【游骑兵】生命+15%，全部攻击：伤害+15%"
    )


def test_old_han_reforms_do_not_add_other_armies_gold_cost(repo):
    """旧朝改革：草原骑兵只涨食物、木材造价，不吃别的军队的金币 +25%。"""
    tech, units = _resolve(repo, "YPHCOldHanArmyReforms", "Chinese", ("ypstepperider",), age=3)
    rider = _settle(tech, units["ypstepperider"])
    assert units["ypstepperider"].cost == {"gold": 85}
    assert rider.cost == {"gold": 85}
    assert rider.hp == 225


def test_artillery_hitpoints_keeps_the_grenadier_value_off_artillery(repo):
    """攻城武器生命值：猛火油柜、轻型迫击炮 +15%，掷弹兵的 +20% 打不到它们。"""
    tech, units = _resolve(
        repo, "YPHCArtilleryHitpointsChinese", "Chinese", ("ypflamethrower", "yphandmortar"), age=3,
    )
    assert _settle(tech, units["ypflamethrower"]).hp == 241.5
    assert _settle(tech, units["yphandmortar"]).hp == 115


def test_dravidian_martial_arts_hits_only_hand_attacks(repo):
    """达罗毗荼武术：所有近战攻击 +15%，拉杰普特人的近战再 +5%；鹰炮没有近战，不变。"""
    tech, units = _resolve(repo, "YPHCMeleeDamageIndians", "Indians", ("falconet", "yprajput"))
    falconet = _settle(tech, units["falconet"])
    rajput = _settle(tech, units["yprajput"])
    assert falconet == units["falconet"]
    base = units["yprajput"]
    assert _damage(rajput, "MeleeHandAttack") == round(_damage(base, "MeleeHandAttack") * 1.2, 2)
    assert _damage(rajput, "BuildingAttack") == _damage(base, "BuildingAttack")
    assert "鹰炮" not in tech.summary


def test_mughal_elephant_armor_adds_siege_armor_by_damage_type(repo):
    """蒙兀儿大象护甲：连枷象只加攻城护甲 +0.1，攻城象只加远程护甲 +0.1。"""
    tech, units = _resolve(
        repo, "DEHCElephantArmors", "Indians", ("ypmercflailiphant", "ypsiegeelephant"),
    )
    flail = units["ypmercflailiphant"]
    siege = units["ypsiegeelephant"]
    flail_after = _settle(tech, flail)
    siege_after = _settle(tech, siege)
    assert (flail_after.armor_melee, flail_after.armor_ranged) == (flail.armor_melee, flail.armor_ranged)
    assert flail_after.armor_siege == round(flail.armor_siege + 0.1, 3)
    assert siege_after.armor_ranged == round(siege.armor_ranged + 0.1, 3)
    assert siege_after.armor_siege == siege.armor_siege
    assert "【连枷象】攻城护甲+0.1" in tech.summary


def test_mongol_scourge_building_damage_stays_on_the_building_attack(repo):
    """蒙古勇者：×1.5 只写给草原骑兵的建筑攻击，近战攻击不变。"""
    tech, units = _resolve(repo, "YPHCMongolianScourge", "Chinese", ("ypstepperider",), age=3)
    base = units["ypstepperider"]
    rider = _settle(tech, base)
    assert _damage(rider, "BuildingAttack") == round(_damage(base, "BuildingAttack") * 1.5, 2)
    assert _damage(rider, "MeleeHandAttack") == _damage(base, "MeleeHandAttack")


def _reachable_pairs(repo: UnitRepo):
    pool = cwt._load_pool()
    priority = cwt._load_priority()
    generic = cwt._load_generic_pool()
    pairs = {}
    for civ_id in sorted(generic):
        for age in (3, 4, 5):
            for unit in draft_units(repo, civ_id, age):
                candidate = SimpleNamespace(
                    civ_id=civ_id, units=(unit,), source="generic", required_tech_ids=(), id="x",
                )
                for tech in cwt.match_candidate_techs(
                    candidate, age=age, pool=pool, priority=priority, generic_pool=generic,
                ):
                    pairs[(tech.id, unit.id)] = (tech, unit)
    return pairs


@pytest.mark.slow
def test_every_reachable_tech_only_settles_effects_that_name_the_unit(repo):
    """全量：去掉打不到这个兵的效果，结算结果不变。"""
    leaks = []
    for (tech_id, unit_id), (tech, unit) in _reachable_pairs(repo).items():
        payload = tech.runtime_tech()
        own = {**payload, "ops": [op for op in payload["ops"] if op_targets_unit(op, unit)]}
        if apply_techs([unit], [payload], base_units=[unit]) != apply_techs(
            [unit], [own], base_units=[unit],
        ):
            leaks.append((tech_id, unit_id))
    assert leaks == []


def test_no_pool_effect_is_dropped_without_being_listed():
    """科技池里每一条效果要么能结算，要么写在 UNAPPLIED_EFFECTS 里。"""
    unlisted = set()
    for row in cwt._load_pool():
        for op in (*row.get("combat_ops", ()), *row.get("cost_ops", ())):
            key = cwt.unapplied_effect_key(op)
            if key is not None and key not in cwt.UNAPPLIED_EFFECTS:
                unlisted.add((row["id"], *key))
    assert unlisted == set()


def test_runtime_ops_keep_their_own_targets():
    op = cwt._runtime_op({
        "subtype": "Hitpoints",
        "amount": 1.15,
        "relativity": "BasePercent",
        "targets": [{"type": "ProtoUnit", "value": "deRanger"}],
    })
    assert op["targets"] == [{"type": "ProtoUnit", "value": "deRanger"}]


def test_unlocks_follow_techstatus_active_and_obtainable_shadows():
    """active 直接给（含主城卡免费升级）；obtainable 只开放研究，不生效；
    影子科技靠前置自动生效时，原始状态必须是可获得。"""
    from plugins.aoe3.tech_links import expand

    assert expand(["IncendiaryGrenades"], age=3) == ["IncendiaryGrenades", "IncendiaryGrenadesShadow"]
    assert expand(["DEHCAkicita"], age=3) == ["DEHCAkicita", "DEHCAkicitaShadow"]
    assert expand(["HCShipWingedHussars"], age=4) == [
        "HCShipWingedHussars", "VeteranWingedHussars", "GuardWingedHussars",
    ]
    # 半兄弟（革命卡）开放研究的影子科技，原始不可获得：古老的士兵战斗力不会带出它。
    assert expand(["DEHCArchaicCombat"], age=4) == ["DEHCArchaicCombat"]
    # 时代前置：罗马战术的影子要帝王时代。
    assert expand(["DEHCRomanTactics"], age=4) == ["DEHCRomanTactics"]
    assert expand(["DEHCRomanTactics"], age=5) == ["DEHCRomanTactics", "DERomanTacticsShadow"]


def test_selection_and_labels_include_unlocked_techs(repo):
    """燃烧弹的效果主要在影子科技里：选兵、专属标记都按“主科技 + 解锁”看。"""
    from plugins.games.aoe3_battle.lineup_draft import list_selectable_techs, targets_fielded_unit

    soldado = repo.get_by_id("desoldado")
    techs = {t.id: t for t in list_selectable_techs("DEMexicans", (soldado,), 3)}
    assert targets_fielded_unit(techs["IncendiaryGrenades"], (soldado,))
    flamer = repo.get_by_id("dehoopthrower")
    assert "Rifling" in {t.id for t in list_selectable_techs("DEMaltese", (flamer,), 3)}


def test_untyped_armor_adds_all_three_armors(repo):
    """华卡纳：数据只写护甲 +0.05 作用步兵、轻步兵，三种伤害类型的护甲都加。"""
    tech, units = _resolve(repo, "deBigWarHutHualcana", "DEInca", ("deslinger",), age=3)
    base = units["deslinger"]
    after = _settle(tech, base)
    # 投石索兵只是步兵，不是轻步兵：只吃一条 +0.05。
    assert after.armor_melee == round(base.armor_melee + 0.05, 3)
    assert after.armor_ranged == round(base.armor_ranged + 0.05, 3)
    assert after.armor_siege == round(base.armor_siege + 0.05, 3)
