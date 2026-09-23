"""Focused movement tests for 2D pathing / bypass behavior."""

from __future__ import annotations

from plugins.aoe3.models import Unit
from plugins.games.aoe3_battle.simulator2d import (
    BattleSimulator2D,
    Simulation2DConfig,
)
from plugins.games.aoe3_battle.simulator2d.engine import (
    BattleSimulator2D as _Engine,
)
from plugins.games.aoe3_battle.simulator2d.model import Side, Soldier2D, Vec2
from plugins.games.aoe3_battle.simulator2d.movement import LocalAvoidance
from plugins.games.aoe3_battle.simulator2d.spatial import SpatialHash


def _unit(unit_id: str) -> Unit:
    return Unit(
        id=unit_id,
        name=unit_id,
        name_en=unit_id,
        hp=100000,
        speed=4.0,
        attack_melee=10.0,
        rof_melee=1.0,
    )


def test_unit_can_bypass_stopped_friendly_wall() -> None:
    config = Simulation2DConfig()
    unit = _unit("mover")
    mover = Soldier2D(1, Side.RED, unit, 100000, 100000, 1.0, 0.0)
    wall = [
        Soldier2D(index, Side.RED, unit, 100000, 100000, 4.0, y)
        for index, y in enumerate([-2.0, -1.0, 0.0, 1.0, 2.0], start=2)
    ]
    for blocker in wall:
        blocker.stopped = True
    spatial = SpatialHash(config.spatial_cell_size)
    spatial.rebuild([mover, *wall])
    avoidance = LocalAvoidance(config, spatial)

    result = avoidance.choose_velocity(
        mover,
        Vec2(1.0, 0.0),
        field_width=30.0,
        field_height=30.0,
        blocked_ticks=config.blocked_window_ticks,
    )

    assert abs(result.velocity.y) > 0.5, (
        "A unit facing a full friendly wall must select a lateral path, "
        f"got {result.velocity}"
    )


def test_integrated_simulation_makes_units_reach_contact() -> None:
    unit = _unit("mover")
    result = BattleSimulator2D(
        red_unit=unit,
        red_count=20,
        blue_unit=unit,
        blue_count=20,
        seed=42,
        config=Simulation2DConfig(),
    ).run()

    assert any(
        event.data.get("mode") == "melee"
        for event in result.events
        if event.event_type.value == "ATTACK"
    )


def test_mover_physically_crosses_blocking_wall() -> None:
    config = Simulation2DConfig()
    unit = _unit("mover")
    simulator = _Engine(
        red_army=[(unit, 1)],
        blue_army=[(unit, 1)],
        seed=1,
        config=config,
    )
    simulator._init_soldiers()
    mover = simulator._soldiers[0]
    target = simulator._soldiers[1]
    target.x = 12.0
    target.y = 0.0
    mover.x = 1.0
    mover.y = 0.0
    wall = []
    for index, y in enumerate([-2.0, -1.0, 0.0, 1.0, 2.0], start=10):
        blocker = Soldier2D(index, Side.RED, unit, 100000, 100000, 6.0, y)
        blocker.stopped = True
        wall.append(blocker)
    simulator._soldiers.extend(wall)
    simulator._spatial_hash.rebuild(simulator._soldiers)

    crossed = False
    path = []
    lateral_before_forward = 0.0
    for _ in range(300):
        simulator._tick += 1
        desired, _ = simulator._desired_velocity(mover)
        result = simulator._movement.choose_velocity(
            mover,
            desired,
            field_width=30.0,
            field_height=30.0,
            blocked_ticks=mover.no_progress_ticks,
        )
        mover.velocity_x = result.velocity.x
        mover.velocity_y = result.velocity.y
        simulator._integrate_movement(
            simulator._alive(),
            [mover],
        )
        simulator._spatial_hash.rebuild(simulator._soldiers)
        path.append((mover.x, mover.y))
        if mover.x < 6.0:
            lateral_before_forward = max(lateral_before_forward, abs(mover.y))
        if mover.x > 6.9 and abs(mover.y) > 2.4:
            crossed = True
            break

    assert crossed, (
        f"mover did not travel around the wall: "
        f"pos=({mover.x:.2f},{mover.y:.2f}), "
        f"vel=({mover.velocity_x:.2f},{mover.velocity_y:.2f})"
    )
    assert lateral_before_forward < 4.5, (
        "unit ran too far sideways before passing the wall: "
        f"lateral={lateral_before_forward:.2f}, path={path[:20]}"
    )


def test_two_soldiers_split_to_opposite_wall_edges() -> None:
    config = Simulation2DConfig()
    unit = _unit("mover")
    simulator = _Engine(
        red_army=[(unit, 2)],
        blue_army=[(unit, 1)],
        seed=7,
        config=config,
    )
    simulator._init_soldiers()
    movers = simulator._soldiers[:2]
    target = simulator._soldiers[2]
    target.x = 12.0
    target.y = 0.0
    for index, mover in enumerate(movers):
        mover.x = 1.0
        mover.y = -0.45 + index * 0.9
    wall = [
        Soldier2D(index, Side.RED, unit, 100000, 100000, 6.0, y)
        for index, y in enumerate([-2.0, -1.0, 0.0, 1.0, 2.0], start=10)
    ]
    for blocker in wall:
        blocker.stopped = True
    simulator._soldiers.extend(wall)
    simulator._spatial_hash.rebuild(simulator._soldiers)
    # Let the engine accumulate blockage naturally before creating detours.
    for _ in range(80):
        simulator._tick += 1
        simulator._process_movement()
        simulator._refresh_stopped()
    simulator._set_detour_waypoint(movers[0], target)
    simulator._set_detour_waypoint(movers[1], target)
    side_signs = [mover.detour_sign for mover in movers]
    assert side_signs[0] != side_signs[1], (
        f"detour edge selection did not split: {side_signs}"
    )

    max_positive = [0.0, 0.0]
    max_negative = [0.0, 0.0]
    for _ in range(180):
        simulator._tick += 1
        simulator._process_movement()
        simulator._refresh_stopped()
        for index, mover in enumerate(movers):
            max_positive[index] = max(max_positive[index], mover.y)
            max_negative[index] = min(max_negative[index], mover.y)
        if all(mover.x > 6.5 for mover in movers):
            break

    assert max_positive[0] > 0.8 or max_positive[1] > 0.8, (
        f"neither unit produced a lateral detour: {max_positive}"
    )
    assert max_negative[0] < -0.8 or max_negative[1] < -0.8, (
        "neither unit produced the opposite lateral detour: "
        f"positive={max_positive}, negative={max_negative}"
    )
