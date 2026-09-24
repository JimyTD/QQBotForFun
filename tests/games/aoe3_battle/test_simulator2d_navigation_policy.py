"""Common movement policy and honest outcomes from bounded local search."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from plugins.aoe3.models import Unit
from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D
from plugins.games.aoe3_battle.simulator2d.model import Side, Soldier2D, Vec2
from plugins.games.aoe3_battle.simulator2d.navigation import RouteSearch, RouteStatus, search_detour


def _ranged_snapshot(mirror=False):
    repo = UnitRepo.get()
    sim = BattleSimulator2D(
        repo.get_by_id("skirmisher"), 7, repo.get_by_id("desoldado"), 1, seed=42
    )
    sim._init_soldiers()
    sim._soldiers.clear()
    sim._soldier_map.clear()
    sim._field_width, sim._field_height = 48.0, 36.0
    rows = [
        (31, 20.057, 15.590, -0.26083067),
        (32, 19.986, 16.966, 0.54785673),
        (33, 19.895, 18.595, -0.08026972),
        (34, 19.972, 20.441, 0.79340254),
        (44, 19.677, 14.689, -0.46158047),
        (45, 19.162, 16.032, -1.91143148),
        (46, 19.395, 17.754, -0.37208533),
        (81, 39.810, 16.993, 3.04192247),
    ]
    for uid, x, y, angle in rows:
        unit = repo.get_by_id("desoldado" if uid == 81 else "skirmisher")
        s = sim._create_soldier(uid, Side.BLUE if uid == 81 else Side.RED, unit, Vec2(x, y))
        s.facing = angle
        s.stopped = uid != 46
        sim._soldiers.append(s)
        sim._soldier_map[uid] = s
    if mirror:
        for s in sim._soldiers:
            s.x = 48 - s.x
            s.facing = math.pi - s.facing
    mover = sim._soldier_map[46]
    mover.move_target_id = 81
    mover.blocked_target_id = 81
    mover.no_progress_ticks = sim.config.blocked_window_ticks
    sim._spatial_hash.rebuild(sim._soldiers)
    return sim, mover, sim._soldier_map[81]


@pytest.mark.parametrize("mirror", [False, True])
def test_round_skirmisher_can_back_out_of_the_recorded_deadlock(mirror):
    sim, mover, target = _ranged_snapshot(mirror)
    start = mover.pos
    for tick in range(100):
        sim._tick = tick
        summary = sim._process_movement()
        assert summary.max_overlap <= sim.config.separation_slop
        if mover.distance_to(target) <= mover.effective_ranged_range:
            break
    assert (mover.pos - start).length() > 0.3
    assert mover.distance_to(target) <= mover.effective_ranged_range


@pytest.mark.parametrize("radii", [(0.5, 0.5), (0.5, 0.7)])
def test_every_shape_has_a_reverse_escape_action(radii):
    unit = Unit(
        id="mover",
        name="mover",
        name_en="mover",
        hp=100,
        speed=4,
        attack_melee=10,
        obstruction_radius_x=radii[0],
        obstruction_radius_z=radii[1],
    )
    sim = BattleSimulator2D(unit, 1, unit, 1)
    sim._init_soldiers()
    mover, target = sim._soldiers
    mover.x, mover.y, mover.facing = 10, 10, 0
    target.x, target.y, target.stopped = 20, 10, True
    obstacles = [
        Soldier2D(10 + i, Side.RED, unit, 100, 100, x, y, stopped=True)
        for i, (x, y) in enumerate([(11, 10), (10, 10 + 2 * radii[1]), (10, 10 - 2 * radii[1])])
    ]
    sim._soldiers.extend(obstacles)
    sim._spatial_hash.rebuild(sim._soldiers)
    command = sim._movement.choose_velocity(
        mover,
        Vec2(4, 0),
        field_width=30,
        field_height=30,
        blocked_ticks=sim.config.blocked_window_ticks,
    )
    assert command.velocity.x < 0
    assert command.facing is not None
    mover.velocity_x, mover.velocity_y = command.velocity.x, command.velocity.y
    sim._integrate_movement(sim._soldiers, [mover], {mover.id: command})
    assert mover.x < 10


@pytest.mark.parametrize("radii", [(0.5, 0.5), (0.5, 0.7)])
def test_shared_recovery_does_not_force_a_step_when_fully_enclosed(radii):
    unit = Unit(
        id="enclosed",
        name="enclosed",
        name_en="enclosed",
        hp=100,
        speed=4,
        attack_melee=10,
        obstruction_radius_x=radii[0],
        obstruction_radius_z=radii[1],
    )
    sim = BattleSimulator2D(unit, 1, unit, 1)
    sim._init_soldiers()
    mover, target = sim._soldiers
    mover.x, mover.y, mover.facing = 10, 10, 0
    target.x, target.y, target.stopped = 20, 10, True
    sim._soldiers.extend(
        Soldier2D(10 + i, Side.RED, unit, 100, 100, 10 + x, 10 + y, stopped=True)
        for i, (x, y) in enumerate(
            [(2 * radii[0], 0), (-2 * radii[0], 0), (0, 2 * radii[1]), (0, -2 * radii[1])]
        )
    )
    sim._spatial_hash.rebuild(sim._soldiers)
    command = sim._movement.choose_velocity(
        mover, Vec2(4, 0), field_width=30, field_height=30, blocked_ticks=30
    )
    assert command.velocity.length() < 1e-9


def _wall():
    unit = Unit(id="wall", name="wall", name_en="wall", hp=100, speed=4, attack_melee=10)
    sim = BattleSimulator2D(unit, 1, unit, 1, seed=42)
    sim._init_soldiers()
    sim._field_width = sim._field_height = 30
    mover, target = sim._soldiers
    mover.x, mover.y, mover.facing = 4, 10, 0
    target.x, target.y, target.stopped = 16, 10, True
    sim._soldiers.extend(
        Soldier2D(10 + i, Side.RED, unit, 100, 100, 8, y, stopped=True)
        for i, y in enumerate([8, 9, 10, 11, 12])
    )
    sim._spatial_hash.rebuild(sim._soldiers)
    return sim, mover, target


def test_search_distinguishes_clear_route_and_budget_exhaustion():
    sim, mover, target = _wall()
    exhausted = search_detour(
        mover, target, sim._spatial_hash, sim.config, 30, 30, expansion_budget=0
    )
    assert exhausted.status == RouteStatus.BUDGET_EXHAUSTED
    assert exhausted.plan is None
    found = search_detour(mover, target, sim._spatial_hash, sim.config, 30, 30)
    assert found.status == RouteStatus.FOUND
    assert found.plan is not None
    for s in sim._soldiers[2:]:
        s.alive = False
    sim._spatial_hash.rebuild(sim._soldiers)
    direct = search_detour(mover, target, sim._spatial_hash, sim.config, 30, 30, expansion_budget=0)
    assert direct.status == RouteStatus.DIRECT


def test_search_budget_failure_keeps_the_target_and_schedules_a_bounded_retry(monkeypatch):
    sim, mover, target = _wall()
    mover.move_target_id = target.id
    mover.blocked_target_id = target.id
    mover.no_progress_ticks = 6
    budgets = []

    def exhausted(*args, **kwargs):
        budgets.append(kwargs["expansion_budget"])
        return RouteSearch(RouteStatus.BUDGET_EXHAUSTED, expanded=kwargs["expansion_budget"])

    monkeypatch.setattr("plugins.games.aoe3_battle.simulator2d.engine.search_detour", exhausted)
    sim._desired_velocity(mover)
    assert mover.move_target_id == target.id
    assert mover.navigation_status == "budget_exhausted"
    assert mover.detour_retry_tick >= 12
    sim._tick = mover.detour_retry_tick
    sim._desired_velocity(mover)
    assert budgets == [
        sim.config.navigation_max_expansions,
        sim.config.navigation_max_expansions * 2,
    ]


def test_route_cost_limit_is_not_reported_as_a_proven_obstruction():
    sim, mover, target = _wall()
    config = replace(sim.config, navigation_max_stretch=0.01)
    result = search_detour(mover, target, sim._spatial_hash, config, 30, 30)
    assert result.status == RouteStatus.COST_LIMIT


def test_exhausted_local_graph_is_not_confused_with_budget_exhaustion():
    sim, mover, target = _wall()
    result = search_detour(
        mover, target, sim._spatial_hash, replace(sim.config, navigation_max_obstacles=0), 30, 30
    )
    assert result.status == RouteStatus.LOCAL_NO_ROUTE
    assert result.expanded > 0


def test_failed_alternative_targets_do_not_reset_the_recovery_window(monkeypatch):
    sim, mover, target = _wall()
    other = sim._create_soldier(100, Side.BLUE, target.unit, Vec2(16, 12))
    sim._soldiers.append(other)
    sim._soldier_map[other.id] = other
    sim._spatial_hash.rebuild(sim._soldiers)
    mover.move_target_id = target.id
    mover.blocked_target_id = target.id
    mover.no_progress_ticks = 6
    monkeypatch.setattr(
        "plugins.games.aoe3_battle.simulator2d.engine.search_detour",
        lambda *args, **kwargs: RouteSearch(RouteStatus.LOCAL_NO_ROUTE, expanded=10),
    )
    monkeypatch.setattr(
        "plugins.games.aoe3_battle.simulator2d.engine.route_clear", lambda *args, **kwargs: False
    )
    sim._desired_velocity(mover)
    assert mover.move_target_id == target.id
    assert mover.no_progress_ticks >= 6


def test_ranged_route_can_end_at_a_local_firing_position():
    sim, mover, target = _ranged_snapshot()
    result = search_detour(
        mover,
        target,
        sim._spatial_hash,
        sim.config,
        48,
        36,
        arrival_distance=mover.effective_ranged_range,
    )
    assert result.status == RouteStatus.FOUND
    assert (result.plan.points[-1] - target.pos).length() <= mover.effective_ranged_range
    assert result.plan.cost < 6
