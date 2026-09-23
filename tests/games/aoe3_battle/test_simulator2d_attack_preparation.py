"""Independent aiming and ROF deadlines with a persistent stationary posture."""

from __future__ import annotations

from dataclasses import replace

import pytest

from plugins.aoe3.models import Unit
from plugins.games.aoe3_battle.battle_contract import EventType
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D
from plugins.games.aoe3_battle.simulator2d.model import AttackMode, Vec2
from plugins.games.aoe3_battle.simulator2d.movement import SteeringResult


def _scene(*, minimum=0.0, melee=0.0, ranged_windup=0.4, melee_windup=0.2):
    gun = Unit(
        id="gun",
        name="gun",
        name_en="gun",
        hp=10000,
        speed=4.0,
        attack_ranged=20.0,
        range=12.0,
        range_min=minimum,
        rof_ranged=1.5,
        attack_melee=melee,
        range_melee=1.75,
        rof_melee=1.0,
        windup_ranged=ranged_windup,
        windup_melee=melee_windup,
    )
    dummy = replace(gun, id="dummy", speed=0.0, attack_ranged=0.0, attack_melee=0.0)
    sim = BattleSimulator2D(gun, 1, dummy, 2, seed=42)
    sim._init_soldiers()
    gunner, first, second = sim._soldiers
    gunner.x, gunner.y = 10.0, 10.0
    first.x, first.y = 14.0, 10.0
    second.x, second.y = 15.0, 12.0
    sim._spatial_hash.rebuild(sim._soldiers)
    return sim, gunner, first, second


def _tick(sim, soldier, tick):
    sim._tick = tick
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._refresh_stopped()
    sim._combat.acquire_target(soldier)
    return sim._combat.process_attacks([soldier])


def _attacks(sim):
    return [e for e in sim._events if e.event_type == EventType.ATTACK]


@pytest.mark.parametrize("windup,hit_ticks", [(0.4, [4, 19, 34]), (2.0, [20, 35, 50])])
def test_first_aim_and_continuous_rof_are_not_added_for_each_shot(windup, hit_ticks):
    sim, soldier, _, _ = _scene(ranged_windup=windup)
    for tick in range(hit_ticks[-1] + 1):
        _tick(sim, soldier, tick)
    assert [e.tick for e in _attacks(sim)] == hit_ticks
    assert soldier.aim_ready_at == pytest.approx(windup)
    assert soldier.attack_ready_at == pytest.approx(hit_ticks[-1] * 0.1 + 1.5)


def test_same_tick_cannot_advance_timers_or_fire_twice():
    sim, soldier, _, _ = _scene(ranged_windup=0.0)
    assert _tick(sim, soldier, 0) == 1
    assert _tick(sim, soldier, 0) == 0
    assert soldier.attack_ready_at == pytest.approx(1.5)


def test_stationary_retarget_preserves_partial_aim_but_does_not_complete_it():
    sim, soldier, first, second = _scene()
    assert _tick(sim, soldier, 0) == 0
    first.alive = False
    assert _tick(sim, soldier, 2) == 0
    assert soldier.target_id == second.id
    assert soldier.aim_ready_at == pytest.approx(0.4)
    assert _tick(sim, soldier, 3) == 0
    assert _tick(sim, soldier, 4) == 1


def test_stationary_retarget_keeps_rof_deadline():
    sim, soldier, first, second = _scene()
    for tick in range(18):
        _tick(sim, soldier, tick)
    first.alive = False
    assert _tick(sim, soldier, 18) == 0
    assert soldier.target_id == second.id
    assert soldier.attack_ready_at == pytest.approx(1.9)
    assert _tick(sim, soldier, 19) == 1


def test_targetless_stationary_wait_keeps_preparation():
    sim, soldier, first, second = _scene()
    _tick(sim, soldier, 0)
    first.alive = second.alive = False
    assert _tick(sim, soldier, 2) == 0
    assert soldier.target_id is None
    assert soldier.aim_ready_at == pytest.approx(0.4)
    assert _tick(sim, soldier, 6) == 0
    second.alive = True
    assert _tick(sim, soldier, 7) == 1


@pytest.mark.parametrize("rof_deadline,fire_tick", [(1.0, 12), (2.0, 20)])
def test_move_then_stop_waits_for_max_of_aim_and_remaining_rof(rof_deadline, fire_tick):
    sim, soldier, _, _ = _scene()
    _tick(sim, soldier, 0)
    soldier.attack_ready_at = rof_deadline
    sim._tick = 2
    sim._combat.interrupt_preparation(soldier)
    soldier.stopped = False
    assert soldier.aim_ready_at is None
    assert soldier.attack_ready_at == rof_deadline
    for tick in range(3, 8):
        sim._tick = tick
        assert sim._combat.process_attacks([soldier]) == 0
    for tick in range(8, fire_tick):
        assert _tick(sim, soldier, tick) == 0
    assert soldier.aim_ready_at == pytest.approx(1.2)
    assert _tick(sim, soldier, fire_tick) == 1


def test_blocked_movement_intent_interrupts_aim_even_without_displacement(monkeypatch):
    sim, soldier, first, second = _scene()
    _tick(sim, soldier, 0)
    soldier.attack_ready_at = 2.0
    first.x = second.x = 30.0
    sim._tick = 1
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._refresh_stopped()
    initial = soldier.pos
    monkeypatch.setattr(
        sim._movement,
        "choose_velocity",
        lambda *args, **kwargs: SteeringResult(Vec2(0, 0), "sliding"),
    )
    sim._process_movement()
    assert soldier.pos == initial
    assert soldier.aim_ready_at is None
    assert soldier.prepared_mode is None
    assert soldier.attack_ready_at == pytest.approx(2.0)


def test_passive_collision_correction_does_not_interrupt_aim(monkeypatch):
    sim, soldier, _, _ = _scene()
    _tick(sim, soldier, 0)
    resolve = sim._collisions.resolve

    def pushed(*args, **kwargs):
        result = resolve(*args, **kwargs)
        soldier.x += 0.05
        return result

    monkeypatch.setattr(sim._collisions, "resolve", pushed)
    sim._tick = 2
    sim._process_movement()
    assert soldier.x == pytest.approx(10.05)
    assert soldier.aim_ready_at == pytest.approx(0.4)
    assert _tick(sim, soldier, 4) == 1


@pytest.mark.parametrize("rof_deadline,fire_tick", [(0.0, 4), (1.5, 15)])
def test_illegal_action_switch_restarts_aim_without_resetting_rof(rof_deadline, fire_tick):
    sim, soldier, target, _ = _scene(minimum=3.0, melee=10.0, ranged_windup=0.6)
    _tick(sim, soldier, 0)
    soldier.attack_ready_at = rof_deadline
    target.x = 11.5
    assert _tick(sim, soldier, 2) == 0
    assert soldier.prepared_mode == AttackMode.MELEE
    assert soldier.aim_ready_at == pytest.approx(0.4)
    assert soldier.attack_ready_at == pytest.approx(rof_deadline)
    assert _tick(sim, soldier, fire_tick - 1) == 0
    assert _tick(sim, soldier, fire_tick) == 1
    assert _attacks(sim)[-1].data["mode"] == "melee"


def test_legal_prepared_action_survives_melee_boundary_jitter():
    sim, soldier, target, _ = _scene(melee=10.0)
    _tick(sim, soldier, 0)
    for tick, distance in enumerate([1.74, 1.76, 1.74, 1.74], 1):
        target.x = soldier.x + distance
        _tick(sim, soldier, tick)
        assert soldier.prepared_mode == AttackMode.RANGED
        assert soldier.aim_ready_at == pytest.approx(0.4)
    assert [e.tick for e in _attacks(sim)] == [4]
    # A completed shot allows a new action choice for the next cycle.
    assert _tick(sim, soldier, 5) == 0
    assert soldier.prepared_mode == AttackMode.MELEE
    assert soldier.aim_ready_at == pytest.approx(0.7)
    assert soldier.attack_ready_at == pytest.approx(1.9)


def test_final_legality_check_prevents_a_shot_outside_range():
    sim, soldier, first, second = _scene()
    _tick(sim, soldier, 0)
    first.x = second.x = 30.0
    sim._tick = 4
    assert sim._combat.process_attacks([soldier]) == 0
    assert soldier.attack_ready_at == 0.0
    assert not _attacks(sim)


def test_frame_exposes_independent_remaining_times_without_mutating_deadlines():
    sim, soldier, _, _ = _scene()
    frames = []
    sim._frame_callback = frames.append
    soldier.attack_ready_at = 2.0
    _tick(sim, soldier, 0)
    sim._emit_visual_frame(status="running", winner=None, timeout=False)
    unit = frames[-1]["units"][0]
    assert unit["attack_cd"] == 2.0
    assert unit["aim_cd"] == 0.4
    assert unit["prepared_mode"] == "ranged"
    _tick(sim, soldier, 5)
    sim._emit_visual_frame(status="running", winner=None, timeout=False)
    unit = frames[-1]["units"][0]
    assert unit["attack_cd"] == 1.5
    assert unit["aim_cd"] == 0.0
    assert soldier.attack_ready_at == 2.0


def test_visual_frame_carries_real_attack_and_death_events():
    sim, soldier, target, _ = _scene(ranged_windup=0.0)
    frames = []
    sim._frame_callback = frames.append

    _tick(sim, soldier, 0)
    sim._emit_visual_frame(status="running", winner=None, timeout=False)

    attack = next(event for event in frames[-1]["visual_events"] if event["type"] == "attack")
    assert attack["attacker_id"] == soldier.id
    assert attack["target_id"] == target.id
    assert attack["x"] == target.x
    assert attack["y"] == target.y

    target.hp = 0.1
    sim._tick = 1
    sim._apply_damage(soldier, target, 1.0, AttackMode.RANGED)
    sim._emit_visual_frame(status="running", winner=None, timeout=False)

    death = next(event for event in frames[-1]["visual_events"] if event["type"] == "death")
    assert death["unit_id"] == target.id
    assert death["x"] == target.x
    assert death["y"] == target.y
