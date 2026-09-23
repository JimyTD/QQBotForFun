"""RTS combat eligibility must not depend on arbitrary crowd-balancing gates."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from plugins.aoe3.models import Unit
from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.battle_contract import EventType
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D
from plugins.games.aoe3_battle.simulator2d.model import AttackMode


def _unit(name="unit", **changes):
    return replace(
        Unit(
            id=name,
            name=name,
            name_en=name,
            hp=10000,
            speed=4.0,
            attack_melee=10.0,
            range_melee=1.75,
            rof_melee=1.2,
        ),
        **changes,
    )


@pytest.mark.parametrize("count", [1, 3, 5])
def test_entire_shotel_front_row_attacks_in_range_without_overlap(count):
    repo = UnitRepo.get()
    shotel = replace(repo.get_by_id("deshotelwarrior"), hp=10000)
    dragoon = replace(repo.get_by_id("dragoon"), hp=10000)
    sim = BattleSimulator2D(shotel, count, dragoon, count, seed=42)
    sim._init_soldiers()
    front = sim._soldiers[:count]
    enemies = sim._soldiers[count:]
    for index, (soldier, enemy) in enumerate(zip(front, enemies, strict=True)):
        soldier.x, soldier.y = 10.0, 10.0 + index * 1.6
        enemy.x, enemy.y, enemy.stopped = 11.72, soldier.y, True
    sim._spatial_hash.rebuild(sim._soldiers)
    for tick in range(16):
        sim._tick = tick
        sim._refresh_stopped()
        assert all(s.stopped for s in front)
        summary = sim._process_movement()
        assert summary.max_overlap <= 0.002
        for soldier in sim._alive():
            sim._combat.acquire_target(soldier)
        sim._combat.process_attacks(sim._alive())
    first_hits = {}
    for event in sim._events:
        if event.event_type == EventType.ATTACK and event.data["attacker_id"] <= count:
            first_hits.setdefault(event.data["attacker_id"], event.tick)
    assert set(first_hits) == {s.id for s in front}
    assert max(first_hits.values()) <= math.ceil(shotel.windup_melee / sim.config.tick_interval)
    assert all(s.total_damage_dealt > 0 for s in front)


def test_attack_permission_does_not_allow_hits_beyond_range():
    sim = BattleSimulator2D(_unit(), 1, _unit(), 1)
    sim._init_soldiers()
    attacker, target = sim._soldiers
    attacker.x, attacker.y = 10, 10
    target.x, target.y = 11.80, 10
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._refresh_stopped()
    assert not attacker.stopped
    assert sim._combat.determine_attack_mode(attacker, target) is None


@pytest.mark.parametrize(
    "minimum,distance,expected",
    [
        (0.0, 1.0, AttackMode.RANGED),
        (5.0, 1.0, None),
        (5.0, 4.9, None),
        (5.0, 5.0, AttackMode.RANGED),
    ],
)
def test_ranged_only_units_obey_actual_minimum_range(minimum, distance, expected):
    gun = _unit("gun", attack_melee=0, attack_ranged=20, range=15, range_min=minimum)
    sim = BattleSimulator2D(gun, 1, _unit(), 1)
    sim._init_soldiers()
    attacker, target = sim._soldiers
    attacker.x = 10
    target.x = 10 + distance
    target.y = attacker.y
    assert sim._combat.determine_attack_mode(attacker, target) == expected
    if expected is not None:
        assert sim._combat.calc_damage(attacker, target, expected) == pytest.approx(20)


def test_melee_slot_is_retained_inside_ranged_minimum():
    gun = _unit("gun", attack_ranged=20, range=15, range_min=5)
    sim = BattleSimulator2D(gun, 1, _unit(), 1)
    sim._init_soldiers()
    attacker, target = sim._soldiers
    attacker.x, target.x = 10, 11.5
    target.y = attacker.y
    assert sim._combat.determine_attack_mode(attacker, target) == AttackMode.MELEE


def _splash(cap, projectiles=1):
    gun = _unit(
        "gun",
        attack_melee=0,
        attack_ranged=20,
        range=15,
        aoe_radius_ranged=3,
        damage_cap_ranged=cap,
        num_projectiles_ranged=projectiles,
    )
    sim = BattleSimulator2D(gun, 1, _unit(), 10, seed=42)
    sim._init_soldiers()
    attacker, main, *others = sim._soldiers
    attacker.x, attacker.y = 5, 10
    main.x, main.y = 10, 10
    for index, unit in enumerate(others):
        unit.x = 10 + 1.8 * math.cos(index * math.tau / len(others))
        unit.y = 10 + 1.8 * math.sin(index * math.tau / len(others))
    others[-1].x, others[-1].y = 20, 10
    sim._spatial_hash.rebuild(sim._soldiers)
    count = sim._combat.process_aoe(attacker, main, AttackMode.RANGED)
    return sim, main, others, count


def test_aoe_hits_geometry_not_a_random_radius_sized_quota():
    _sim, main, others, count = _splash(160)
    assert count == 8  # Radius 3 is a distance, not a three-person hit quota.
    assert main.hp == 10000
    assert all(unit.hp == 9980 for unit in others[:-1])
    assert others[-1].hp == 10000


def test_real_cap_is_preserved_without_inventing_a_minimum_one_damage():
    _sim, _main, others, count = _splash(4)
    assert count == 8
    assert sum(10000 - unit.hp for unit in others) == pytest.approx(4)


@pytest.mark.parametrize("projectiles", [1, 3])
def test_missing_cap_uses_user_approved_twice_combined_base_attack(projectiles):
    _sim, _main, others, count = _splash(0, projectiles)
    assert count == 8
    assert sum(10000 - unit.hp for unit in others) == pytest.approx(20 * projectiles * 2)


def test_cooldown_keeps_running_while_moving_and_is_not_reset_by_stopping():
    sim = BattleSimulator2D(_unit(windup_melee=0.2), 1, _unit(), 1)
    sim._init_soldiers()
    attacker, target = sim._soldiers
    attacker.attack_ready_at = 1.0
    sim._tick = 1
    sim._combat.process_attacks(sim._alive())
    assert attacker.attack_ready_at - sim._combat.now == pytest.approx(0.9)
    attacker.x, target.x, target.y = 10, 11.5, attacker.y
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._refresh_stopped()
    sim._combat.acquire_target(attacker)
    assert attacker.attack_ready_at - sim._combat.now == pytest.approx(0.9)
    assert attacker.aim_ready_at == pytest.approx(0.3)


def test_minimum_range_is_an_intentional_hold_not_a_pathing_deadlock():
    gun = _unit("gun", attack_melee=0, attack_ranged=20, range=15, range_min=5)
    sim = BattleSimulator2D(gun, 1, _unit(), 1)
    sim._init_soldiers()
    attacker, target = sim._soldiers
    attacker.x, target.x, target.y = 10, 13, attacker.y
    target.stopped = True
    sim._spatial_hash.rebuild(sim._soldiers)
    position = attacker.pos
    for tick in range(50):
        sim._tick = tick
        sim._process_movement()
        assert sim._combat.process_attacks([attacker]) == 0
        assert attacker.pos == position
        assert attacker.last_steer_reason == "minimum_range"
        assert attacker.no_progress_ticks == 0


def test_full_armor_is_not_overridden_by_an_invented_damage_floor():
    gun = _unit("gun", attack_ranged=0.5, range=15)
    sim = BattleSimulator2D(gun, 1, _unit(armor_ranged=1.0), 1)
    sim._init_soldiers()
    assert sim._combat.calc_damage(*sim._soldiers, AttackMode.RANGED) == 0.0
