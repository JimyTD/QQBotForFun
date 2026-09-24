"""Whole-pose motion, including the previously frozen elephant #26 snapshot."""

from __future__ import annotations

import math

import pytest

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D, Simulation2DConfig
from plugins.games.aoe3_battle.simulator2d.geometry import (
    CollisionShape,
    PoseMotion,
    angle_delta,
    motion_clear,
    rotation_clear,
    shape_contact,
    steering_motion,
)
from plugins.games.aoe3_battle.simulator2d.model import Side, Vec2
from plugins.games.aoe3_battle.simulator2d.movement import SteeringResult, _pose_collision_time


def test_simultaneous_motion_can_clear_an_obstacle_that_prevents_a_pivot():
    shape = CollisionShape(10, 10, 2, 0.3, 0)
    neighbor = CollisionShape(11.2, 11.2, 0.35, 0.35, 0)
    assert not rotation_clear(shape, math.pi / 2, [neighbor])
    assert motion_clear(shape, 10, 8, math.pi / 2, [neighbor])
    motion = PoseMotion(shape, 0, -2, math.pi / 2)
    assert motion.clear([neighbor])
    for i in range(101):
        assert shape_contact(motion.at(i / 100), neighbor) is None


def test_clear_endpoints_do_not_allow_mid_turn_collision():
    shape = CollisionShape(10, 10, 2, 0.3, 0)
    neighbor = CollisionShape(11.2, 11.2, 0.35, 0.35, 0)
    motion = PoseMotion(shape, 0, 0.4, math.pi / 2)
    assert shape_contact(motion.start, neighbor) is None
    assert shape_contact(motion.at(1), neighbor) is None
    assert not motion.clear([neighbor])


def test_turn_rate_uses_time_not_tick_count():
    shape = CollisionShape(10, 10, 0.39, 0.89, 0)
    motion = steering_motion(shape, 0, 2, math.pi / 2, 0.1, math.pi)
    assert motion.turn == pytest.approx(math.pi * 0.1)
    assert motion.at(1).angle == pytest.approx(math.pi * 0.1)
    remaining = steering_motion(motion.at(1), 0, 2, math.pi / 2, 0.4, math.pi)
    assert remaining.at(1).angle == pytest.approx(math.pi / 2)


def _blocked_snapshot(substeps=2, mirror=False):
    repo = UnitRepo.get()
    sim = BattleSimulator2D(
        repo.get_by_id("pikeman"),
        6,
        repo.get_by_id("ypmahout"),
        6,
        seed=42,
        config=Simulation2DConfig(movement_substeps=substeps),
    )
    sim._init_soldiers()
    sim._soldiers.clear()
    sim._soldier_map.clear()
    rows = [
        (11, "pikeman", 22.429, 14.302, 0.549700569),
        (13, "pikeman", 21.952, 16.599, -0.417526648),
        (17, "pikeman", 24.517, 10.685, 0.455935987),
        (18, "pikeman", 25.667, 10.602, 1.105990475),
        (20, "pikeman", 23.116, 11.745, 0.090063754),
        (21, "pikeman", 22.329, 13.304, 0.010613705),
        (25, "ypmahout", 23.931, 13.460, -3.057457447),
        (26, "ypmahout", 24.552, 14.322, -2.754338420),
        (27, "ypmahout", 23.667, 16.823, -3.011263335),
        (28, "ypmahout", 24.079, 18.164, -2.453118997),
        (30, "ypmahout", 24.839, 12.381, -2.661669825),
        (31, "ypmahout", 24.977, 15.863, 2.734059058),
    ]
    for uid, name, x, y, facing in rows:
        unit = sim._create_soldier(
            uid, Side.RED if name == "pikeman" else Side.BLUE, repo.get_by_id(name), Vec2(x, y)
        )
        unit.facing = facing
        unit.stopped = uid != 26
        sim._soldiers.append(unit)
        sim._soldier_map[uid] = unit
    if mirror:
        for unit in sim._soldiers:
            unit.x = sim._field_width - unit.x
            unit.facing = math.pi - unit.facing
    mover = sim._soldier_map[26]
    mover.move_target_id = 11
    mover.no_progress_ticks = sim.config.blocked_window_ticks
    sim._spatial_hash.rebuild(sim._soldiers)
    return sim, mover


@pytest.mark.parametrize("substeps", [1, 2, 4])
@pytest.mark.parametrize("mirror", [False, True])
def test_frozen_snapshot_can_maneuver_without_turning_through_neighbors(substeps, mirror):
    sim, mover = _blocked_snapshot(substeps, mirror)
    start = mover.pos
    for tick in range(15):
        sim._tick = tick
        previous, angle = mover.pos, mover.facing
        summary = sim._process_movement()
        assert (
            mover.pos - previous
        ).length() <= mover.effective_speed * sim.config.tick_interval + 0.003
        assert (
            abs(angle_delta(angle, mover.facing))
            <= sim.config.movement_turn_rate * sim.config.tick_interval + 1e-6
        )
        assert summary.max_overlap <= sim.config.separation_slop
        if (mover.pos - start).length() >= 0.3:
            break
    assert (mover.pos - start).length() >= 0.3


@pytest.mark.parametrize("substeps", [1, 2, 4])
def test_motor_executes_selected_translation_and_heading_without_reinterpreting(substeps):
    sim, mover = _blocked_snapshot(substeps)
    for other in sim._soldiers:
        other.alive = other.id == mover.id
    sim._spatial_hash.rebuild(sim._soldiers)
    mover.x, mover.y, mover.facing = 10, 10, 0
    sim._spatial_hash.rebuild(sim._soldiers)
    mover.velocity_x, mover.velocity_y = 0, 2
    command = SteeringResult(Vec2(0, 2), "maneuver", facing=0.4, turn_fraction=0.5)
    sim._integrate_movement([mover], [mover], {mover.id: command})
    assert mover.x == pytest.approx(10)
    assert mover.y == pytest.approx(10.2)
    assert mover.facing == pytest.approx(0.4)


def test_fully_enclosed_unit_does_not_get_a_forced_escape():
    shape = CollisionShape(10, 10, 0.5, 0.5, 0)
    obstacles = [
        CollisionShape(10 + dx, 10 + dy, 0.5, 0.5, 0)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
    ]
    for angle in (i * math.pi / 8 for i in range(16)):
        motion = PoseMotion(shape, 0.3 * math.cos(angle), 0.3 * math.sin(angle), 0)
        assert not motion.clear(obstacles)


def test_prediction_still_accounts_for_a_moving_body_after_our_stop():
    shape = CollisionShape(0, 0, 0.45, 0.45, 0)
    other = CollisionShape(1, 2, 0.45, 0.45, 0)
    motion = PoseMotion(shape, 0.4, 0, 0)
    ttc = _pose_collision_time(motion, 0.1, Vec2(4, 0), other, Vec2(0, -2), 1, 0.25, 0.002)
    assert ttc == pytest.approx(0.55)
