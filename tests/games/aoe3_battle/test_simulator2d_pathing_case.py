"""Physical paths, not just opposite sign flags, are the routing contract."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from plugins.aoe3.models import Unit
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D, Simulation2DConfig
from plugins.games.aoe3_battle.simulator2d.model import Side, Soldier2D, Vec2
from plugins.games.aoe3_battle.simulator2d.movement import _time_to_collision


def _scene(*, count=2, center=10.0, mirror=False, substeps=2, radius=0.45):
    unit = Unit(
        id="mover",
        name="mover",
        name_en="mover",
        hp=100,
        speed=4.0,
        attack_melee=10.0,
        rof_melee=1.0,
        obstruction_radius_equiv=radius,
    )
    sim = BattleSimulator2D(
        red_army=[(unit, count)],
        blue_army=[(unit, 1)],
        seed=7,
        config=Simulation2DConfig(movement_substeps=substeps),
    )
    sim._init_soldiers()
    sim._field_width = 24.0
    sim._field_height = 20.0
    movers = sim._soldiers[:count]
    target = sim._soldiers[count]
    target.x, target.y, target.stopped = 16.0, center, True
    for i, mover in enumerate(movers):
        mover.x, mover.y = 2.0, center + (i - (count - 1) / 2) * (2 * radius + 0.3)
    wall = [
        Soldier2D(100 + i, Side.RED, unit, 100, 100, 8.0, center + i - 2, stopped=True)
        for i in range(5)
    ]
    sim._soldiers.extend(wall)
    sim._soldier_map.update({s.id: s for s in wall})
    if mirror:
        for s in sim._soldiers:
            s.x = 24.0 - s.x
            s.facing = math.pi
    sim._spatial_hash.rebuild(sim._soldiers)
    return sim, movers, target, wall


@pytest.mark.parametrize("velocity,expected", [(Vec2(4, 0), 0.525), (Vec2(-4, 0), None)])
def test_collision_prediction_distinguishes_approach_from_separation(velocity, expected):
    _sim, movers, _, wall = _scene(count=1)
    mover, blocker = movers[0], wall[2]
    blocker.x = mover.x + 3
    result = _time_to_collision(mover, velocity, blocker, fallback_radius=0.45, horizon=1)
    assert result == pytest.approx(expected) if expected is not None else result is None


def test_opposite_choices_have_opposite_world_waypoints():
    results = []
    for unit_id in (1, 2):
        sim, movers, target, _ = _scene(count=1)
        mover = movers[0]
        mover.id = unit_id + 10
        sim._set_detour_waypoint(mover, target)
        assert mover.detour_waypoint_y is not None
        results.append(mover.detour_waypoint_y - mover.y)
    assert results[0] < 0 < results[1]


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("substeps", [1, 2, 4])
def test_units_physically_split_and_cross_wall_without_penetration(mirror, substeps):
    sim, movers, _, wall = _scene(mirror=mirror, substeps=substeps)
    extremes = [[s.y, s.y] for s in movers]
    crossed = set()
    initial_wall = [(s.x, s.y) for s in wall]
    for _ in range(200):
        previous = [s.pos for s in movers]
        sim._tick += 1
        sim._process_movement()
        for i, mover in enumerate(movers):
            extremes[i][0] = min(extremes[i][0], mover.y)
            extremes[i][1] = max(extremes[i][1], mover.y)
            assert (mover.pos - previous[i]).length() <= 0.401
            assert all(mover.distance_to(b) >= 0.895 for b in wall)
            if mover.x < 15.0 if mirror else mover.x > 9.0:
                crossed.add(i)
        if len(crossed) == len(movers):
            break
    assert len(crossed) == 2, [(s.x, s.y, s.no_progress_ticks) for s in movers]
    assert extremes[0][0] < 7.2
    assert extremes[1][1] > 12.8
    assert [(s.x, s.y) for s in wall] == initial_wall


def test_border_rejects_unreachable_side():
    sim, movers, target, _ = _scene(count=1, center=2.5)
    sim._set_detour_waypoint(movers[0], target)
    assert movers[0].detour_waypoint_y > 4.5
    assert all(p.y >= 0.45 for p in movers[0].detour_remaining)


def test_nearer_edge_wins_over_id_parity():
    sim, movers, target, _ = _scene(count=1)
    movers[0].y = 11.5
    target.y = 11.5
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._set_detour_waypoint(movers[0], target)
    assert movers[0].detour_sign == 1


def test_dead_target_clears_route():
    sim, movers, target, _ = _scene(count=1)
    sim._set_detour_waypoint(movers[0], target)
    target.alive = False
    desired, _ = sim._desired_velocity(movers[0])
    assert not movers[0].detour_remaining
    assert movers[0].detour_waypoint_x is None
    assert desired.length() == 0


def test_detour_cannot_disable_collision_guard():
    sim, movers, target, wall = _scene(count=1)
    mover = movers[0]
    mover.x = 7.0
    mover.move_target_id = target.id
    mover.detour_waypoint_x, mover.detour_waypoint_y = 10.0, 10.0
    mover.velocity_x = 4.0
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._integrate_movement(sim._soldiers, [mover])
    assert mover.x < 8.0
    assert all(mover.distance_to(b) >= 0.895 for b in wall)


def test_integrated_simulation_makes_units_reach_contact():
    sim, _, _, _ = _scene()
    unit = sim.red_army[0].unit
    result = BattleSimulator2D(unit, 20, unit, 20, seed=42, max_ticks=180).run()
    assert any(
        e.data.get("mode") == "melee" for e in result.events if e.event_type.value == "ATTACK"
    )


def test_high_speed_step_does_not_tunnel_through_distant_wall():
    sim, movers, _, wall = _scene(count=1, substeps=1)
    mover = movers[0]
    mover.velocity_x = 100.0
    sim._integrate_movement(sim._soldiers, [mover])
    assert mover.x < wall[0].x


def test_large_mover_uses_its_own_clearance():
    sim, movers, target, wall = _scene(count=1, radius=0.8)
    for blocker in wall:
        blocker.unit = replace(blocker.unit, obstruction_radius_equiv=0.45)
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._set_detour_waypoint(movers[0], target)
    for _ in range(150):
        sim._tick += 1
        sim._process_movement()
        assert all(movers[0].distance_to(blocker) >= 1.245 for blocker in wall)
        if movers[0].x > 9.5:
            break
    assert movers[0].x > 9.5


def test_route_rotates_with_the_scene():
    sim, movers, target, _ = _scene(count=1)
    sim._set_detour_waypoint(movers[0], target)
    original = Vec2(movers[0].detour_waypoint_x, movers[0].detour_waypoint_y)
    rotated, movers, target, _ = _scene(count=1)
    rotated._field_width = rotated._field_height = 30.0
    for soldier in rotated._soldiers:
        soldier.x, soldier.y = 24.0 - soldier.y, soldier.x + 2.0
    rotated._spatial_hash.rebuild(rotated._soldiers)
    rotated._set_detour_waypoint(movers[0], target)
    assert movers[0].detour_waypoint_x == pytest.approx(24.0 - original.y)
    assert movers[0].detour_waypoint_y == pytest.approx(original.x + 2.0)


def test_alternating_steps_do_not_reset_the_progress_watchdog():
    sim, movers, target, wall = _scene(count=1)
    for blocker in wall:
        blocker.alive = False
    sim._spatial_hash.rebuild(sim._soldiers)
    mover = movers[0]
    mover.move_target_id = target.id
    for tick in range(24):
        sim._tick = tick
        mover.velocity_x = 2.0 if tick % 2 == 0 else -2.0
        sim._integrate_movement(sim._soldiers, [mover])
    assert mover.no_progress_ticks >= 20
    assert mover.oscillating


def test_fast_cavalry_brakes_into_attack_range_instead_of_strafing():
    from plugins.aoe3.repository import UnitRepo

    repo = UnitRepo.get()
    sim = BattleSimulator2D(
        repo.get_by_id("delifidi"), 1, repo.get_by_id("dejunglebowman"), 1, seed=42
    )
    sim._init_soldiers()
    mover, target = sim._soldiers
    mover.x, mover.y = 17.353, 8.250
    target.x, target.y, target.stopped = 15.479, 7.546, True
    sim._spatial_hash.rebuild(sim._soldiers)
    path = 0.0
    for tick in range(20):
        sim._tick = tick
        previous = mover.pos
        sim._process_movement()
        path += (mover.pos - previous).length()
        if mover.distance_to(target) <= mover.effective_melee_range:
            break
    assert mover.distance_to(target) <= mover.effective_melee_range
    assert path < 1.0
    assert mover.distance_to(target) >= mover.radius(0.45) + target.radius(0.45)


def test_route_is_cancelled_when_deaths_open_the_direct_path():
    sim, movers, target, wall = _scene(count=1)
    mover = movers[0]
    sim._set_detour_waypoint(mover, target)
    assert mover.detour_waypoint_x is not None
    for blocker in wall:
        blocker.alive = False
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._shorten_detour(mover, target)
    assert mover.detour_waypoint_x is None
    assert mover.detour_shortcuts == 1


def test_route_shortcut_never_cuts_through_a_live_wall():
    sim, movers, target, _ = _scene(count=1)
    mover = movers[0]
    sim._set_detour_waypoint(mover, target)
    sim._shorten_detour(mover, target)
    assert mover.detour_waypoint_x is not None


def test_committed_route_does_not_strafe_when_already_inside_attack_range():
    sim, movers, target, wall = _scene(count=1)
    mover = movers[0]
    mover.x, mover.y = target.x - 1.4, target.y
    for blocker in wall:
        blocker.alive = False
    mover.detour_waypoint_x, mover.detour_waypoint_y = 18.0, 14.0
    mover.detour_target_id = target.id
    sim._spatial_hash.rebuild(sim._soldiers)
    sim._refresh_stopped()
    assert mover.stopped
    assert mover.detour_waypoint_x is None
