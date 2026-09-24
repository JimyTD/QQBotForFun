"""The planner, steering and integrator agree about the same ellipse motion."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from plugins.aoe3.models import Unit
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D, Simulation2DConfig
from plugins.games.aoe3_battle.simulator2d.geometry import (
    CollisionShape,
    inside_field,
    motion_clear,
    rotation_clear,
    shape_contact,
    shape_for_unit,
    swept_contact,
)
from plugins.games.aoe3_battle.simulator2d.model import Side, Soldier2D, Vec2
from plugins.games.aoe3_battle.simulator2d.movement import _time_to_collision
from plugins.games.aoe3_battle.simulator2d.navigation import plan_detour, route_clear


def _unit(x=2.0, y=0.3):
    return Unit(
        id="elongated",
        name="elongated",
        name_en="elongated",
        hp=10000,
        speed=4,
        attack_melee=10,
        range_melee=1.5,
        obstruction_radius_x=x,
        obstruction_radius_z=y,
    )


def _corridor(*, transverse=False, substeps=2):
    unit = _unit(0.3, 2.0) if transverse else _unit()
    sim = BattleSimulator2D(
        unit,
        1,
        _unit(0.3, 0.3),
        1,
        seed=42,
        config=Simulation2DConfig(movement_substeps=substeps, max_known_unit_radius=4),
    )
    sim._init_soldiers()
    sim._field_width = 30
    sim._field_height = 20
    mover, target = sim._soldiers
    mover.x, mover.y, mover.facing = 4, 10, 0
    target.x, target.y, target.stopped = 28, 10, True
    walls = [
        Soldier2D(i + 10, Side.RED, _unit(4, 0.45), 10000, 10000, 12, y, stopped=True)
        for i, y in enumerate((9.0, 11.0))
    ]
    sim._soldiers.extend(walls)
    sim._soldier_map.update({s.id: s for s in walls})
    sim._spatial_hash.rebuild(sim._soldiers)
    return sim, mover, target, walls


@pytest.mark.parametrize("substeps", [1, 2, 4])
def test_longitudinal_narrow_gap_passes_planner_steering_and_execution(substeps):
    sim, mover, target, walls = _corridor(substeps=substeps)
    end = Vec2(20, 10)
    assert route_clear(mover, end, sim._spatial_hash, sim.config, target_id=target.id)
    assert plan_detour(mover, target, sim._spatial_hash, sim.config, 30, 20) is None
    for tick in range(40):
        sim._tick = tick
        before = mover.pos
        summary = sim._process_movement()
        assert mover.x == pytest.approx(before.x + 0.4, abs=1e-6)
        assert mover.y == pytest.approx(10)
        assert mover.facing == pytest.approx(0)
        assert summary.max_overlap <= sim.config.separation_slop
        for wall in walls:
            assert (
                shape_contact(
                    shape_for_unit(mover.unit, mover.x, mover.y, mover.facing, 0.45),
                    shape_for_unit(wall.unit, wall.x, wall.y, wall.facing, 0.45),
                )
                is None
            )
    assert mover.x == pytest.approx(end.x)


def test_transverse_narrow_gap_is_rejected_by_both_path_and_step():
    sim, mover, target, _walls = _corridor(transverse=True)
    assert not route_clear(mover, Vec2(20, 10), sim._spatial_hash, sim.config, target_id=target.id)
    mover.x = 12
    mover.y = 6
    mover.facing = math.pi / 2
    sim._spatial_hash.rebuild(sim._soldiers)
    # Sweeping the wide side through the first wall is not a legal shortcut.
    shape = shape_for_unit(mover.unit, mover.x, mover.y, 0, 0.45)
    walls = [shape_for_unit(s.unit, s.x, s.y, s.facing, 0.45) for s in sim._soldiers[2:]]
    assert not motion_clear(shape, 12, 10, 0, walls)


def test_long_axis_collision_is_detected_before_equal_area_circles_touch():
    _sim, mover, target, _ = _corridor()
    mover.x, target.x, target.y = 10, 13, 10
    mover.facing = 0
    assert mover.distance_to(target) > mover.radius(0.45) + target.radius(0.45)
    ttc = _time_to_collision(mover, Vec2(4, 0), target, fallback_radius=0.45, horizon=1)
    assert ttc is not None
    assert ttc == pytest.approx((3 - 2 - 0.3) / 4, abs=0.001)


def test_swept_ellipse_detects_crossing_when_both_endpoints_are_clear():
    first = CollisionShape(0, 0, 2, 0.3, 0)
    second = CollisionShape(5, 0, 0.4, 0.4, 0)
    assert shape_contact(first, second) is None
    assert shape_contact(replace(first, x=10), second) is None
    assert swept_contact(first, second, 10, 0) is not None
    assert not motion_clear(first, 10, 0, 0, [second])


def test_safe_rotation_endpoints_do_not_allow_sweeping_through_a_neighbor():
    shape = CollisionShape(10, 10, 2, 0.3, 0)
    neighbor = CollisionShape(11.2, 11.2, 0.35, 0.35, 0)
    assert shape_contact(shape, neighbor) is None
    assert shape_contact(replace(shape, angle=math.pi / 2), neighbor) is None
    assert not rotation_clear(shape, math.pi / 2, [neighbor])
    assert not motion_clear(shape, 10, 10.4, math.pi / 2, [neighbor])
    sim, mover, target, walls = _corridor()
    for wall in walls:
        wall.alive = False
    mover.x, mover.y = 10, 10
    target.x, target.y = neighbor.x, neighbor.y
    target.unit = _unit(0.35, 0.35)
    sim._spatial_hash.rebuild(sim._soldiers)
    mover.velocity_x, mover.velocity_y = 0, 4
    sim._integrate_movement(sim._alive(), [mover])
    assert abs(mover.facing - math.pi / 2) > 0.01
    assert (
        shape_contact(
            shape_for_unit(mover.unit, mover.x, mover.y, mover.facing, 0.45),
            neighbor,
            tolerance=sim.config.separation_slop,
        )
        is None
    )


def test_field_boundary_uses_ellipse_extent_not_bounding_circle():
    shape = CollisionShape(4, 0.35, 2, 0.3, 0)
    assert inside_field(shape, 30, 20)
    assert motion_clear(shape, 12, 0.35, 0, [], field=(30, 20))
    assert not motion_clear(shape, 4, 0.35, math.pi / 2, [], field=(30, 20))
    sim, mover, target, walls = _corridor()
    for wall in walls:
        wall.alive = False
    mover.y = target.y = 0.35
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._process_movement()
    assert mover.x == pytest.approx(4.4)
    assert mover.y == pytest.approx(0.35)


def test_deployment_uses_actual_axis_extents_for_long_units():
    sim = BattleSimulator2D(_unit(2.0, 0.3), 20, _unit(0.4, 1.6), 10, seed=1)
    sim._init_soldiers()
    shapes = [shape_for_unit(s.unit, s.x, s.y, s.facing, 0.45) for s in sim._soldiers]
    assert all(inside_field(s, sim._field_width, sim._field_height) for s in shapes)
    for index, first in enumerate(shapes):
        assert all(shape_contact(first, second) is None for second in shapes[index + 1 :])


def test_planned_ellipse_detour_is_executable_when_obstacles_do_not_change():
    sim = BattleSimulator2D(_unit(1.0, 0.3), 1, _unit(0.3, 0.3), 1, seed=7)
    sim._init_soldiers()
    sim._field_width, sim._field_height = 30, 20
    mover, target = sim._soldiers
    mover.x, mover.y, mover.facing = 6, 10, 0
    target.x, target.y, target.stopped = 20, 10, True
    blocker = Soldier2D(100, Side.RED, _unit(0.6, 0.6), 10000, 10000, 11, 10, stopped=True)
    sim._soldiers.append(blocker)
    sim._soldier_map[blocker.id] = blocker
    sim._spatial_hash.rebuild(sim._soldiers)
    plan = plan_detour(mover, target, sim._spatial_hash, sim.config, 30, 20)
    assert plan is not None
    for point in plan.points:
        while (point - mover.pos).length() > 1e-7:
            delta = (point - mover.pos).clamped_length(mover.unit.speed * sim.config.tick_interval)
            expected = mover.pos + delta
            mover.velocity_x = delta.x / sim.config.tick_interval
            mover.velocity_y = delta.y / sim.config.tick_interval
            sim._integrate_movement(sim._alive(), [mover])
            assert mover.x == pytest.approx(expected.x, abs=1e-6)
            assert mover.y == pytest.approx(expected.y, abs=1e-6)
    assert mover.x > blocker.x


def test_ellipse_prediction_keeps_moving_obstacles_after_arrival():
    _sim, mover, target, _ = _corridor()
    mover.x, mover.y, mover.facing = 10, 10, 0
    target.x, target.y, target.stopped = 11, 12, False
    target.velocity_y = -2
    ttc = _time_to_collision(
        mover, Vec2(4, 0), target, fallback_radius=0.45, horizon=1, stop_time=0.25
    )
    assert ttc is not None
    assert ttc > 0.25
    assert ttc == pytest.approx(0.7, abs=0.01)
