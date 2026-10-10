"""时代升级：科技 id 列表 + 统一结算。

对应 docs/games/aoe3-battle.md §3.10：同一科技只生效一次，不同科技按统一算符全部叠加，
没有取大。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.aoe3.upgrades import age_tech_ids, apply_upgrades

_DATA_PATH = (
    Path(__file__).resolve().parents[3] / "seeds" / "aoe3" / "unit_upgrades.json"
)


def _action(unit, name):
    return next(a for a in unit.attack_actions if a.name == name)


def _max_ranged_damage(unit):
    return max(
        (a.damage for a in unit.attack_actions if a.damage_type != "Hand" and a.hits_soldiers),
        default=0.0,
    )


def _melee_action(unit):
    return next(a for a in unit.attack_actions if a.damage_type == "Hand")


@pytest.fixture(scope="module")
def data():
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def repo():
    return UnitRepo.get()


def _hp_ratio(repo, uid, age, civ_id=None):
    unit = repo.get_by_id(uid)
    return round(apply_upgrades(unit, age, civ_id=civ_id).hp / unit.hp, 4)


@pytest.mark.parametrize("uid", ["musketeer", "skirmisher", "pikeman", "hussar",
                                 "crossbowman", "longbowman"])
def test_standard_curve(repo, uid):
    """标准步骑（含散兵）= 100/120/150/200。"""
    assert [_hp_ratio(repo, uid, age) for age in (2, 3, 4, 5)] == [1.0, 1.2, 1.5, 2.0]


def test_artillery_curve(repo):
    """炮兵 = 100/100/125/175（无精锐/近卫）。"""
    assert [_hp_ratio(repo, "falconet", age) for age in (2, 3, 4, 5)] == [1.0, 1.0, 1.25, 1.75]


def test_seed_records_tech_ids_not_multipliers(data):
    entry = data["units"]["musketeer"]["5"]
    assert entry["techs"] == ["VeteranMusketeers", "GuardMusketeers", "ImperialMusketeers"]
    assert "hp_mult" not in entry
    assert data["category"]["AbstractNativeWarrior"]["5"]


def test_imperial_musketeer_hp_oracle(repo):
    """外部 oracle（aoe3homecity）：帝王火枪 HP = 300。"""
    assert apply_upgrades(repo.get_by_id("musketeer"), 5).hp == 300


def test_native_unit_line_and_legendary_natives_both_apply(repo):
    """阿坎安科比亚：精英 +25%、风云 +35%、传奇土著 +50% 全部叠加 = ×2.1（不取大）。"""
    assert [_hp_ratio(repo, "denatakanmusketeer", age) for age in (3, 4, 5)] == [1.25, 1.6, 2.1]


def test_merc_guard_tier_and_contractor_both_apply(repo):
    """马穆鲁克：护卫 +30%（4 时代）+ 佣兵承包商 +50%（5 时代）= ×1.8。"""
    assert [_hp_ratio(repo, "mercmameluke", age) for age in (4, 5)] == [1.3, 1.8]


def test_home_city_card_shadow_is_not_an_age_upgrade(repo):
    """瑞士长矛兵的 +20% 来自荷兰主城卡影子档，不随时代生效；5 时代只有佣兵承包商。"""
    assert [_hp_ratio(repo, "mercswisspikeman", age) for age in (3, 4, 5)] == [1.0, 1.0, 1.5]


def test_percent_relativity_age_upgrade_applies(repo):
    """老练燧发枪手写的是 Percent 1.2（按当前值乘），旧版只认 BasePercent 而漏掉。"""
    assert _hp_ratio(repo, "minuteman", 3) == 1.2


def test_council_line_preferred_over_revolution_only_tier(repo):
    """大元帅：议会线（+250/+500/+1500），不选只有革命能开放的 +1300 档。"""
    hetman = repo.get_by_id("dehetman")
    assert [apply_upgrades(hetman, age).hp for age in (3, 4, 5)] == [750, 1250, 2750]


def test_revolution_only_tier_is_never_an_age_upgrade(data):
    """迫击炮战船：哥伦比亚海军（革命卡）才开放的帝国档不进时代升级，4 时代只有舰载榴弹炮。"""
    monitor = data["units"]["monitor"]
    assert monitor["4"]["techs"] == ["ShipHowitzers"]
    assert "DEImperialMonitors" not in monitor["5"]["techs"]


def test_research_shadows_never_enter_age_upgrades(data):
    """研究科技的影子档要先研究主科技，不是时代升级（靠生成器“正百分比生命/伤害”门槛挡住）。"""
    research_shadows = {
        "RiflingShadow", "CaracoleShadow", "IncendiaryGrenadesShadow", "BayonetShadow",
        "HeatedShotShadow", "DEAzapShadowInfantryBreastplate", "PaperCartridgeShadow",
    }
    used = {
        tech
        for tiers in data["units"].values()
        for entry in tiers.values()
        for tech in entry["techs"]
    }
    assert used.isdisjoint(research_shadows)


def test_age_upgrade_is_settled_once_per_tech(repo):
    musk = repo.get_by_id("musketeer")
    ids = age_tech_ids(musk, 5)
    assert len(ids) == len(set(ids))
    assert apply_upgrades(musk, 5, tech_ids=ids) == apply_upgrades(musk, 5)


def test_apply_upgrades_returns_copy(repo):
    musk = repo.get_by_id("musketeer")
    base_hp = musk.hp
    up = apply_upgrades(musk, 5)
    assert up is not musk
    assert up.hp == base_hp * 2
    assert musk.hp == base_hp
    for action in up.attack_actions:
        assert action.damage == round(_action(musk, action.name).damage * 2, 2)


def test_damage_upgrade_scales_aoe_cap_with_attack(repo):
    falconet = repo.get_by_id("falconet")
    upgraded = apply_upgrades(falconet, 5)
    base = _action(falconet, "CannonAttack")
    after = _action(upgraded, "CannonAttack")
    ratio = after.damage / base.damage
    assert after.damage_cap == pytest.approx(base.damage_cap * ratio, abs=0.02)


def test_apply_upgrades_renames_unit(repo):
    musk = repo.get_by_id("musketeer")
    assert [apply_upgrades(musk, age).name for age in (3, 4, 5)] == [
        "老练火枪兵", "护卫火枪兵", "帝国火枪兵",
    ]


def test_apply_age2_noop(repo):
    musk = repo.get_by_id("musketeer")
    assert apply_upgrades(musk, 2) is musk


# ---------------- 文明专属时代升级（国战） ----------------

def test_civ_upgrade_keeps_veteran_tier_unchanged(repo):
    musk = repo.get_by_id("musketeer")
    assert apply_upgrades(musk, 3, civ_id="British") == apply_upgrades(musk, 3)


def test_british_redcoat_uses_guard_dependency_plus_rg_bonus(repo):
    musk = repo.get_by_id("musketeer")
    generic = apply_upgrades(musk, 4)
    redcoat = apply_upgrades(musk, 4, civ_id="British")
    assert generic.hp == round(musk.hp * 1.5, 1)
    assert _max_ranged_damage(generic) == round(_max_ranged_damage(musk) * 1.5, 2)
    assert redcoat.hp == round(musk.hp * 1.55, 1)
    assert _max_ranged_damage(redcoat) == round(_max_ranged_damage(musk) * 1.65, 2)
    assert redcoat.name == "红衫军火枪兵"


def test_self_contained_ottoman_rg_is_not_double_counted(repo):
    humbaraci = repo.get_by_id("dehumbaraci")
    upgraded = apply_upgrades(humbaraci, 4, civ_id="Ottomans")
    assert upgraded.hp == round(humbaraci.hp * 1.6, 1)
    assert _max_ranged_damage(upgraded) == round(_max_ranged_damage(humbaraci) * 1.6, 2)
    assert upgraded.cost["gold"] == humbaraci.cost["gold"] - 5


def test_shared_artillery_gets_its_own_civilization_variant(repo):
    culverin = repo.get_by_id("culverin")
    italian = apply_upgrades(culverin, 4, civ_id="DEItalians")
    maltese = apply_upgrades(culverin, 4, civ_id="DEMaltese")
    assert italian.hp == round(culverin.hp * 1.35, 1)
    assert _max_ranged_damage(italian) == round(_max_ranged_damage(culverin) * 1.25, 2)
    assert italian.armor_ranged == pytest.approx(culverin.armor_ranged + 0.05)
    assert maltese.hp == round(culverin.hp * 1.25, 1)
    assert _max_ranged_damage(maltese) == round(_max_ranged_damage(culverin) * 1.35, 2)


def test_portuguese_ordinance_pikeman_applies_cost_discount(repo):
    pikeman = repo.get_by_id("pikeman")
    assert apply_upgrades(pikeman, 4, civ_id="Portuguese").cost == {"food": 30, "wood": 30}


def test_polish_scytheman_applies_rof_delta(repo):
    pikeman = repo.get_by_id("pikeman")
    upgraded = apply_upgrades(pikeman, 4, civ_id="DEPolish")
    assert _melee_action(upgraded).rof == pytest.approx(_melee_action(pikeman).rof - 0.25)


def test_outlaw_via_category(repo):
    assert [_hp_ratio(repo, "deallegiancebarbarymarksman", age) for age in (3, 4, 5)] == [
        1.2, 1.5, 2.0,
    ]


# ---------------- 射程 / 速度 / 倍率 ----------------

def test_range_by_action_name(repo):
    """奥斯曼枪手射程随升级线 +1/+2/+4，打到三种远程攻击，近战不变。"""
    abus = repo.get_by_id("abusgun")
    up = apply_upgrades(abus, 5)
    gun = _action(abus, "VolleyRangedAttack")
    assert _action(up, "VolleyRangedAttack").range_max == round(gun.range_max + 4.0, 2)
    assert _action(up, "VolleyHandAttack").range_max == _action(abus, "VolleyHandAttack").range_max
    defend = next(a for a in up.attack_actions_by_tactic["Defend"] if a.name == "DefendRangedAttack")
    base_defend = next(
        a for a in abus.attack_actions_by_tactic["Defend"] if a.name == "DefendRangedAttack"
    )
    assert defend.range_max == round(base_defend.range_max + 4.0, 2)


def test_slinger_elite_range_follows_raw_data(repo):
    """精锐投石索兵原始数据是射程 +8（旧版当成 +147 脏数据丢弃）。"""
    slinger = repo.get_by_id("deslinger")
    up = apply_upgrades(slinger, 3)
    before = _action(slinger, "VolleyRangedAttack").range_max
    assert _action(up, "VolleyRangedAttack").range_max == before + 8


def test_speed_integral(repo):
    cannon = repo.get_by_id("deleathercannon")
    assert apply_upgrades(cannon, 5).speed == round(cannon.speed + 1.0, 3)


def test_mult_add_on_existing_bonus(repo):
    slinger = repo.get_by_id("deslinger")
    volley = _action(apply_upgrades(slinger, 4), "VolleyRangedAttack")
    assert next(m.value for m in volley.multipliers if m.vs == "AbstractArtillery") == 2.5
