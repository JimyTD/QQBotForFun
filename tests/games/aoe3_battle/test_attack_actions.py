"""默认阵型的攻击模式：按优先级和距离选整包，蓄力打完进冷却。"""

from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

from plugins.aoe3.attack_actions import (
    AttackAction,
    approach_distance,
    select_attack,
)
from plugins.aoe3.models import Unit
from plugins.aoe3.repository import UnitRepo
from plugins.aoe3.tech_effects import apply_techs as _apply_runtime_techs
from plugins.games.aoe3_battle.battle_contract import EventType
from plugins.games.aoe3_battle.civ_war_techs import resolve_required_techs
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D


def apply_techs(units, techs, base_units=None):
    """Hand-written techs here aim every op at the tech's scope.

    Payloads from ``runtime_tech()`` already carry per-op targets and pass
    through unchanged.
    """
    aimed = []
    for tech in techs:
        targets = [{"type": "ProtoUnit", "value": value} for value in tech["scope"]]
        aimed.append({
            **tech,
            "ops": [
                op if "targets" in op else {**op, "targets": targets}
                for op in tech["ops"]
            ],
        })
    return _apply_runtime_techs(units, aimed, base_units)


def _action(name, **kwargs):
    values = dict(
        priority=1,
        damage=10.0,
        damage_type="Ranged",
        range_min=0.0,
        range_max=12.0,
        rof=3.0,
    )
    values.update(kwargs)
    return AttackAction(name=name, **values)


def test_musketeer_uses_the_gun_outside_two_and_the_bayonet_inside():
    gun = _action(
        "VolleyRangedAttack",
        priority=100,
        damage=23,
        range_min=2,
        range_max=12,
        rof=3,
    )
    bayonet = _action(
        "VolleyHandAttack",
        priority=25,
        damage=13,
        damage_type="Hand",
        range_max=1.75,
        rof=1.5,
    )
    actions = [gun, bayonet]
    assert select_attack(actions, 8).name == "VolleyRangedAttack"
    assert select_attack(actions, 1).name == "VolleyHandAttack"
    assert approach_distance(actions, 20) == 12
    assert approach_distance(actions, 8) == 8
    assert approach_distance(actions, 1.9) == 1.75


def test_case_shot_covers_the_cannon_minimum_without_backing_up():
    cannon = _action(
        "CannonAttack",
        priority=100,
        damage=300,
        damage_type="Siege",
        range_min=11.5,
        range_max=23,
    )
    case = _action(
        "CaseShotAttack",
        priority=90,
        damage=7.5,
        damage_type="Siege",
        range_max=11.5,
        num_projectiles=7,
        aoe_radius=3,
    )
    actions = [cannon, case]
    assert select_attack(actions, 5).name == "CaseShotAttack"
    assert approach_distance(actions, 5) == 5
    assert approach_distance(actions, 30) == 23


def test_point_blank_keeps_the_higher_priority_gun():
    gun = _action("RangedAttack", priority=100, damage=20, range_max=12)
    sword = _action(
        "HandAttack",
        priority=25,
        damage=10,
        damage_type="Hand",
        range_max=1.75,
    )
    assert select_attack([gun, sword], 1).name == "RangedAttack"


def test_charge_is_used_once_then_waits_out_its_cooldown():
    charge = _action(
        "BullseyeChargeAttack",
        priority=100,
        damage=30,
        range_max=16,
        rof=3,
        charge=True,
        recharge=40,
    )
    gun = _action("RangedAttack", priority=90, damage=20, range_max=12, rof=1.5)
    actions = [charge, gun]
    assert select_attack(actions, 10, now=0, charge_ready_at=0).name == "BullseyeChargeAttack"
    assert select_attack(actions, 10, now=1, charge_ready_at=40).name == "RangedAttack"
    assert select_attack(actions, 14, now=1, charge_ready_at=40) is None
    assert approach_distance(actions, 14, now=1, charge_ready_at=40) == 12


def test_charge_without_a_cooldown_does_not_fire():
    charge = _action(
        "LanceChargeAttack",
        priority=100,
        damage=30,
        damage_type="Siege",
        range_max=3,
        charge=True,
        recharge=0,
    )
    melee = _action(
        "MeleeHandAttack",
        priority=50,
        damage=20,
        damage_type="Hand",
        range_max=2,
    )
    assert select_attack([charge, melee], 2).name == "MeleeHandAttack"


def test_disabled_mode_stays_off_until_action_enable():
    gun = _action("RangedAttack", priority=100, damage=15, range_max=16, enabled=False)
    melee = _action(
        "HandAttack",
        priority=20,
        damage=5,
        damage_type="Hand",
        range_max=1.5,
    )
    assert select_attack([gun, melee], 10) is None
    unit = Unit(
        id="xpspy",
        name="间谍",
        name_en="Spy",
        hp=100,
        speed=4,
        type=["xpspy"],
        attack_actions=[gun, melee],
    )
    enabled = apply_techs(
        [unit],
        [{
            "id": "open",
            "name_zh": "打开射击",
            "scope": ["xpspy"],
            "ops": [{
                "stat": "action_enable",
                "kind": "set",
                "value": 1.0,
                "action": "RangedAttack",
            }],
        }],
    )[0]
    assert enabled.attack_actions[0].enabled
    assert select_attack(enabled.attack_actions, 10).name == "RangedAttack"
    closed = apply_techs(
        [enabled],
        [{
            "id": "close",
            "name_zh": "关闭射击",
            "scope": ["xpspy"],
            "ops": [{
                "stat": "action_enable",
                "kind": "set",
                "value": 0.0,
                "action": "RangedAttack",
            }],
        }],
    )[0]
    assert not closed.attack_actions[0].enabled


def _charge_recharge(unit, name: str) -> float:
    for action in unit.attack_actions:
        if action.name == name and action.charge:
            return action.recharge
    raise AssertionError(name)


def test_koncerz_shortens_the_winged_hussar_charge_cooldown():
    repo = UnitRepo.get()
    unit = repo.get_by_id("dewingedhussar")
    assert unit is not None
    assert _charge_recharge(unit, "LanceChargeAttack") == 60
    techs = resolve_required_techs(
        SimpleNamespace(
            id="check",
            civ_id="DEPolish",
            units=(unit,),
            source="custom",
            required_tech_ids=("DEHCKoncerz",),
        ),
        age=4,
    )
    updated = apply_techs([unit], [techs[0].runtime_tech()])[0]
    assert _charge_recharge(updated, "LanceChargeAttack") == 36
    assert "蓄力冷却-40%" in techs[0].summary


def test_saloon_beverages_shortens_outlaw_charges_only():
    repo = UnitRepo.get()
    cowboy = repo.get_by_id("desalooncowboy")
    general = repo.get_by_id("degeneral")
    assert cowboy is not None and general is not None
    techs = resolve_required_techs(
        SimpleNamespace(
            id="check",
            civ_id="DEAmericans",
            units=(cowboy, general),
            source="custom",
            required_tech_ids=("DESaloonBeverages",),
        ),
        age=4,
    )
    payload = techs[0].runtime_tech()
    updated_cowboy = apply_techs([cowboy], [payload])[0]
    updated_general = apply_techs([general], [payload])[0]
    assert _charge_recharge(cowboy, "BullseyeChargeAttack") == 40
    assert _charge_recharge(updated_cowboy, "BullseyeChargeAttack") == 12
    assert _charge_recharge(general, "ChargeCarbineAttack") == 45
    assert _charge_recharge(updated_general, "ChargeCarbineAttack") == 13.5


def test_spy_pistol_stays_off_until_a_tech_enables_it():
    """伤害包上的 active=0 关掉这条蓄力，战术文件没写关也不算出生就开。"""
    repo = UnitRepo.get()
    unit = repo.get_by_id("xpspy")
    assert unit is not None
    pistol = next(action for action in unit.attack_actions if action.name == "ChargePistolAttack")
    assert pistol.charge and not pistol.enabled
    assert pistol.recharge == 45
    assert select_attack(unit.attack_actions, 8, target_types=("Unit",)) is None
    opened = apply_techs(
        [unit],
        [{
            "id": "agents",
            "name_zh": "特工",
            "scope": ["xpspy"],
            "ops": [{
                "stat": "action_enable",
                "kind": "set",
                "value": 1.0,
                "action": "ChargePistolAttack",
            }],
        }],
    )[0]
    chosen = select_attack(opened.attack_actions, 8, target_types=("Unit",))
    assert chosen is not None and chosen.name == "ChargePistolAttack"


def test_reservistas_card_unlocks_the_insurgente_musket():
    """科技池里的 ActionEnable 要真正把默认关着的模式打开。"""
    repo = UnitRepo.get()
    unit = repo.get_by_id("deinsurgente")
    assert unit is not None
    assert select_attack(unit.attack_actions, 8, target_types=("Unit",)) is None
    techs = resolve_required_techs(
        SimpleNamespace(
            id="check",
            civ_id="DEMexicans",
            units=(unit,),
            source="custom",
            required_tech_ids=("DEHCReservistas",),
        ),
        age=4,
    )
    payload = techs[0].runtime_tech()
    assert any(
        op["stat"] == "action_enable"
        and op["action"] == "VolleyRangedAttack"
        and op["value"] == 1
        for op in payload["ops"]
    )
    assert any(
        op["stat"] == "initial_tactic" and op.get("tactic") == "Volley"
        for op in payload["ops"]
    )
    updated = apply_techs([unit], [payload])[0]
    chosen = select_attack(updated.attack_actions, 8, target_types=("Unit",))
    assert chosen is not None
    assert chosen.name == "VolleyRangedAttack"
    assert "开启攻击：远程攻击" in techs[0].summary


def test_damage_upgrade_reaches_every_mode():
    gun = _action("VolleyRangedAttack", damage=20)
    bayonet = _action("VolleyHandAttack", damage=10, damage_type="Hand", range_max=1.75)
    unit = Unit(
        id="musketeer",
        name="火枪手",
        name_en="Musketeer",
        hp=100,
        speed=4,
        type=["musketeer"],
        attack_actions=[gun, bayonet],
    )
    upgraded = apply_techs(
        [unit],
        [{
            "id": "vet",
            "name_zh": "老兵",
            "scope": ["musketeer"],
            "ops": [{"stat": "damage", "kind": "mult", "value": 1.2}],
        }],
    )[0]
    assert upgraded.attack_actions[0].damage == 24
    assert upgraded.attack_actions[1].damage == 12


def test_named_range_upgrade_does_not_stretch_the_other_mode():
    gun = _action("VolleyRangedAttack", range_max=12)
    bayonet = _action("VolleyHandAttack", damage_type="Hand", range_max=1.75)
    unit = Unit(
        id="musketeer",
        name="火枪手",
        name_en="Musketeer",
        hp=100,
        speed=4,
        type=["musketeer"],
        attack_actions=[gun, bayonet],
    )
    upgraded = apply_techs(
        [unit],
        [{
            "id": "range",
            "name_zh": "射程",
            "scope": ["musketeer"],
            "ops": [{
                "stat": "range",
                "kind": "add",
                "value": 2,
                "subtype": "MaximumRange",
                "action": "VolleyRangedAttack",
            }],
        }],
    )[0]
    assert upgraded.attack_actions[0].range_max == 14
    assert upgraded.attack_actions[1].range_max == 1.75


def test_charge_shot_in_the_simulator_then_falls_back_to_the_gun():
    charge = _action(
        "BullseyeChargeAttack",
        priority=100,
        damage=30,
        range_max=16,
        rof=3,
        windup=0,
        charge=True,
        recharge=40,
    )
    gun = _action(
        "RangedAttack",
        priority=90,
        damage=20,
        range_max=12,
        rof=1.5,
        windup=0,
    )
    shooter = Unit(
        id="cowboy",
        name="牛仔",
        name_en="Cowboy",
        hp=10000,
        speed=4,
        attack_actions=[charge, gun],
    )
    dummy = Unit(
        id="dummy",
        name="靶子",
        name_en="Dummy",
        hp=10000,
        speed=0,
    )
    sim = BattleSimulator2D(shooter, 1, dummy, 1, seed=1)
    sim._init_soldiers()
    attacker, target = sim._soldiers
    attacker.x, attacker.y = 10.0, 10.0
    target.x, target.y = 16.0, 10.0
    attacker.stopped = True
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._tick = 0
    sim._combat.acquire_target(attacker)
    assert sim._combat.process_attacks([attacker]) == 1
    assert attacker.charge_ready_at == 40
    assert attacker.prepared_action_name == "BullseyeChargeAttack"
    sim._tick = 30
    sim._combat.acquire_target(attacker)
    assert sim._combat.process_attacks([attacker]) == 1
    assert attacker.prepared_action_name == "RangedAttack"
    damages = [
        event.data["damage"]
        for event in sim._events
        if event.event_type == EventType.ATTACK and not event.data.get("is_splash")
    ]
    assert damages == [30.0, 20.0]


def test_crate_rate_does_not_count_as_a_soldier_attack():
    parser_path = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "crawler"
        / "aoe3_gamedata_parser.py"
    )
    spec = importlib.util.spec_from_file_location("aoe3_gamedata_parser", parser_path)
    parser = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(parser)
    crate = ET.fromstring(
        "<action><name>HandAttackCrate</name><type>Attack</type>"
        "<attackaction>1</attackaction>"
        '<rate type="AbstractInfiniteCrate">1</rate></action>'
    )
    hand = ET.fromstring(
        "<action><name>HandAttack</name><type>Attack</type>"
        "<attackaction>1</attackaction>"
        '<rate type="Unit">1</rate></action>'
    )
    assert parser._hits_soldiers(crate) is False
    assert parser._hits_soldiers(hand) is True


def test_crate_smash_is_not_used_against_soldiers():
    """砸箱子的近战目标是箱子，贴脸仍用打人的那一刀。"""
    repo = UnitRepo.get()
    expected = {
        "defulawarrior": "MeleeHandAttack",
        "deminer": "HandAttack",
        "natklamathrifleman": "VolleyHandAttack",
        "derevhaidamaka": "MeleeHandAttack",
    }
    for unit_id, melee_name in expected.items():
        unit = repo.get_by_id(unit_id)
        assert unit is not None
        assert any(action.name == "HandAttackCrate" for action in unit.attack_actions)
        chosen = select_attack(
            unit.attack_actions,
            0.5,
            charge_ready_at=1,
            target_types=("Unit",),
        )
        assert chosen is not None and chosen.name == melee_name


def test_building_attack_is_not_used_against_a_soldier():
    bayonet = _action(
        "MeleeHandAttack",
        priority=25,
        damage=13,
        damage_type="Hand",
        range_max=1.75,
        rates=("Unit",),
        handlogic=True,
    )
    siege = _action(
        "BuildingAttack",
        priority=50,
        damage=20,
        damage_type="Siege",
        range_max=1.75,
        rates=("LogicalTypeShipsAndBuildings",),
        hits_soldiers=False,
        handlogic=True,
    )
    chosen = select_attack(
        [siege, bayonet],
        1.0,
        target_types=("Unit", "AbstractInfantry"),
    )
    assert chosen is not None and chosen.name == "MeleeHandAttack"


def test_farther_lower_priority_shot_stops_the_approach():
    short = _action("RangedAttack", priority=100, damage=140, range_max=20)
    far = _action("LongRangeAttack", priority=90, damage=80, range_max=40)
    actions = [short, far]
    assert approach_distance(actions, 30) == 30
    assert select_attack(actions, 30).name == "LongRangeAttack"
    assert select_attack(actions, 10).name == "RangedAttack"
