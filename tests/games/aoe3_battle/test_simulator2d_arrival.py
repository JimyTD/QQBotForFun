"""Full-speed approach with a finite stopping trajectory, not an early brake."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D, Simulation2DConfig
from plugins.games.aoe3_battle.simulator2d.model import Side, Soldier2D, Vec2
from plugins.games.aoe3_battle.simulator2d.movement import _arrival_time, _time_to_collision


def _scene(distance, *, mirror=False, dt=0.1, speed=6.25):
    repo = UnitRepo.get()
    shotel = replace(repo.get_by_id("deshotelwarrior"), speed=speed, hp=10000)
    dragoon = replace(repo.get_by_id("dragoon"), hp=10000)
    sim = BattleSimulator2D(
        shotel, 1, dragoon, 1, seed=42, config=Simulation2DConfig(tick_interval=dt)
    )
    sim._init_soldiers()
    mover, target = sim._soldiers
    mover.x, mover.y = 10.0, 12.0
    target.x, target.y, target.stopped = 10.0 + distance, 12.0, True
    if mirror:
        mover.x, target.x = 40.0 - mover.x, 40.0 - target.x
        mover.facing = target.facing = math.pi
    sim._spatial_hash.rebuild(sim._soldiers)
    return sim, mover, target


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("distance", [7.52, 5.79, 4.91, 3.0, 2.21, 1.85])
def test_shotel_runs_at_nominal_speed_until_the_final_step(distance, mirror):
    sim, mover, target = _scene(distance, mirror=mirror)
    before = mover.pos
    expected = min(
        mover.unit.speed,
        (distance - mover.effective_melee_range + sim.config.stop_check_slack)
        / sim.config.tick_interval,
    )
    summary = sim._process_movement()
    assert mover.velocity.length() == pytest.approx(expected, abs=1e-6)
    assert mover.y == pytest.approx(before.y)
    assert (mover.pos - before).length() == pytest.approx(expected * sim.config.tick_interval)
    assert mover.distance_to(target) >= mover.radius(0.45) + target.radius(0.45)
    assert summary.max_overlap <= 0.002
    assert mover.aim_ready_at is None


@pytest.mark.parametrize("dt", [0.05, 0.1, 0.2])
@pytest.mark.parametrize("speed", [4.0, 6.25, 7.25])
def test_clear_contact_time_matches_distance_over_speed(dt, speed):
    sim, mover, target = _scene(8.0, dt=dt, speed=speed)
    allowed_ticks = math.ceil(
        (8.0 - mover.effective_melee_range + sim.config.stop_check_slack) / (speed * dt)
    )
    for tick in range(allowed_ticks):
        sim._tick = tick
        before_distance = mover.distance_to(target)
        sim._process_movement()
        if before_distance - mover.effective_melee_range >= speed * dt:
            assert mover.velocity.length() == pytest.approx(speed, abs=1e-6)
        assert mover.y == pytest.approx(12.0)
        assert mover.distance_to(target) >= mover.radius(0.45) + target.radius(0.45)
        if mover.distance_to(target) <= mover.effective_melee_range:
            break
    assert mover.distance_to(target) <= mover.effective_melee_range
    sim._refresh_stopped()
    assert mover.stopped


def test_stopping_before_a_body_removes_only_the_future_overshoot():
    _sim, mover, target = _scene(3.0)
    velocity = Vec2(4.0, 0.0)
    stop_time = _arrival_time(mover.pos, velocity, (target.pos, 1.73))
    assert stop_time == pytest.approx((3.0 - 1.73) / 4)
    assert _time_to_collision(mover, velocity, target, fallback_radius=0.45, horizon=1) is not None
    assert (
        _time_to_collision(
            mover, velocity, target, fallback_radius=0.45, horizon=1, stop_time=stop_time
        )
        is None
    )


def test_an_unsafe_arrival_point_does_not_disable_target_collision():
    _sim, mover, target = _scene(3.0)
    velocity = Vec2(4.0, 0.0)
    stop_time = _arrival_time(mover.pos, velocity, (target.pos, 0.2))
    assert _time_to_collision(
        mover, velocity, target, fallback_radius=0.45, horizon=1, stop_time=stop_time
    ) == pytest.approx((3.0 - 1.38) / 4)


def test_moving_neighbor_can_still_collide_after_we_stop():
    _sim, mover, target = _scene(3.0)
    mover.unit = replace(
        mover.unit,
        obstruction_radius_x=0.45,
        obstruction_radius_z=0.45,
        obstruction_radius_equiv=0.45,
    )
    target.unit = mover.unit
    mover.x, mover.y = 0.0, 0.0
    target.x, target.y, target.stopped = 1.0, 2.0, False
    target.velocity_x, target.velocity_y = 0.0, -2.0
    assert _time_to_collision(
        mover, Vec2(4, 0), target, fallback_radius=0.45, horizon=1, stop_time=0.25
    ) == pytest.approx(0.55)


def test_real_intervening_body_is_not_ignored_for_attack_approach():
    sim, mover, target = _scene(5.0)
    blocker = Soldier2D(100, Side.RED, mover.unit, 10000, 10000, 11.3, 12, stopped=True)
    sim._soldiers.append(blocker)
    sim._soldier_map[blocker.id] = blocker
    sim._spatial_hash.rebuild(sim._soldiers)
    for tick in range(10):
        sim._tick = tick
        summary = sim._process_movement()
        assert mover.distance_to(blocker) >= mover.radius(0.45) + blocker.radius(0.45) - 0.003
        assert mover.distance_to(target) >= mover.radius(0.45) + target.radius(0.45) - 0.003
        assert summary.max_overlap <= 0.003


def test_diagonal_approach_uses_the_same_full_speed_arrival():
    sim, mover, target = _scene(4.91)
    target.x = mover.x + 4.91 / math.sqrt(2)
    target.y = mover.y + 4.91 / math.sqrt(2)
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._process_movement()
    assert mover.velocity.length() == pytest.approx(6.25)
    assert mover.velocity_x == pytest.approx(mover.velocity_y)
