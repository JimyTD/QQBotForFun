"""Focused tests for the independent 2D simulation engine."""

from __future__ import annotations

import random

import pytest

from plugins.aoe3.models import Multiplier, Unit
from plugins.games.aoe3_battle.battle_contract import EventType, Side
from plugins.games.aoe3_battle.broadcaster import format_battle_report
from plugins.games.aoe3_battle.simulator2d import (
    BattleSimulator2D,
    Simulation2DConfig,
)
from plugins.games.aoe3_battle.simulator2d.combat import CombatSystem
from plugins.games.aoe3_battle.simulator2d.config import CollisionMode
from plugins.games.aoe3_battle.simulator2d.model import Soldier2D, Vec2
from plugins.games.aoe3_battle.simulator2d.movement import (
    CollisionResolver,
    LocalAvoidance,
)
from plugins.games.aoe3_battle.simulator2d.spatial import SpatialHash


def _unit(
    unit_id: str,
    *,
    hp: int = 100,
    speed: float = 5.0,
    attack_melee: float = 10.0,
    attack_ranged: float = 0.0,
    range_: float = 0.0,
    aoe_radius_ranged: int = 0,
    damage_cap_ranged: float = 0.0,
    obstruction_radius_x: float = 0.0,
    obstruction_radius_z: float = 0.0,
    obstruction_radius_equiv: float = 0.0,
) -> Unit:
    return Unit(
        id=unit_id,
        name=unit_id,
        name_en=unit_id,
        hp=hp,
        speed=speed,
        attack_melee=attack_melee,
        attack_ranged=attack_ranged,
        range=range_,
        rof_melee=1.0,
        rof_ranged=1.0,
        aoe_radius_ranged=aoe_radius_ranged,
        damage_cap_ranged=damage_cap_ranged,
        obstruction_radius_x=obstruction_radius_x,
        obstruction_radius_z=obstruction_radius_z,
        obstruction_radius_equiv=obstruction_radius_equiv,
        multipliers_ranged=[
            Multiplier(vs="Infantry", value=1.0),
        ],
    )


def test_two_soldier_duel_runs_to_a_winner() -> None:
    unit = _unit("duelist", hp=80, attack_melee=20)
    result = BattleSimulator2D(
        red_army=[(unit, 1)],
        blue_army=[(unit, 1)],
        seed=7,
    ).run()

    assert result.winner in (Side.RED, Side.BLUE, None)
    assert result.red_count == 1
    assert result.blue_count == 1
    assert any(event.event_type == EventType.ATTACK for event in result.events)
    assert any(event.event_type == EventType.BATTLE_END for event in result.events)


def test_initial_formation_has_no_overlap() -> None:
    melee = _unit("melee", attack_melee=10)
    ranged = _unit("ranged", attack_ranged=10, range_=12)
    simulator = BattleSimulator2D(
        red_army=[(melee, 12), (ranged, 12)],
        blue_army=[(melee, 12), (ranged, 12)],
        seed=1,
    )
    simulator._init_soldiers()
    soldiers = simulator._alive()

    for index, first in enumerate(soldiers):
        for second in soldiers[index + 1 :]:
            minimum = first.radius(simulator.config.fallback_unit_radius) + second.radius(
                simulator.config.fallback_unit_radius
            )
            assert first.distance_to(second) >= minimum * 0.99


def test_initial_formation_stays_inside_dynamic_field() -> None:
    melee = _unit("melee", attack_melee=10)
    simulator = BattleSimulator2D(
        red_army=[(melee, 60)],
        blue_army=[(melee, 40)],
        seed=2,
    )
    simulator._init_soldiers()
    soldiers = simulator._alive()
    assert all(
        soldier.radius(simulator.config.fallback_unit_radius)
        <= soldier.x
        <= simulator._field_width
        - soldier.radius(simulator.config.fallback_unit_radius)
        for soldier in soldiers
    )
    assert all(
        soldier.radius(simulator.config.fallback_unit_radius)
        <= soldier.y
        <= simulator._field_height
        - soldier.radius(simulator.config.fallback_unit_radius)
        for soldier in soldiers
    )


def test_larger_units_use_their_real_obstruction_radius() -> None:
    infantry = _unit(
        "infantry",
        obstruction_radius_equiv=0.49,
    )
    elephant = _unit(
        "elephant",
        hp=400,
        obstruction_radius_x=0.49,
        obstruction_radius_z=0.99,
        obstruction_radius_equiv=0.6964,
    )
    simulator = BattleSimulator2D(
        red_army=[(elephant, 1)],
        blue_army=[(infantry, 1)],
        seed=11,
    )
    simulator._init_soldiers()
    first, second = simulator._alive()

    assert first.radius(simulator.config.fallback_unit_radius) == pytest.approx(0.6964)
    assert second.radius(simulator.config.fallback_unit_radius) == pytest.approx(0.49)
    assert first.distance_to(second) >= first.radius(
        simulator.config.fallback_unit_radius
    ) + second.radius(simulator.config.fallback_unit_radius)


def test_spatial_hash_circle_query() -> None:
    unit = _unit("unit")
    hash_ = SpatialHash(cell_size=2.0)
    first = Soldier2D(1, Side.RED, unit, 10.0, 10.0, 0.0, 0.0)
    second = Soldier2D(2, Side.BLUE, unit, 10.0, 10.0, 1.0, 0.0)
    third = Soldier2D(3, Side.BLUE, unit, 10.0, 10.0, 5.0, 5.0)
    hash_.rebuild([first, second, third])

    found = hash_.query_circle(Vec2(0.0, 0.0), 1.5)

    assert {soldier.id for soldier in found} == {1, 2}


def test_ranged_aoe_splashes_multiple_enemies() -> None:
    artillery = _unit(
        "artillery",
        hp=200,
        speed=1.0,
        attack_melee=0.0,
        attack_ranged=20.0,
        range_=20.0,
        aoe_radius_ranged=2,
        damage_cap_ranged=40.0,
    )
    target = _unit("target", hp=100, attack_melee=1.0)
    result = BattleSimulator2D(
        red_army=[(artillery, 1)],
        blue_army=[(target, 3)],
        seed=3,
    ).run()

    splash_events = [
        event
        for event in result.events
        if event.event_type == EventType.AOE_SPLASH
    ]
    assert splash_events


def test_result_is_compatible_with_existing_report() -> None:
    unit = _unit("compat", hp=40, attack_melee=20)
    result = BattleSimulator2D(
        red_army=[(unit, 2)],
        blue_army=[(unit, 2)],
        seed=5,
    ).run()

    report = format_battle_report(result)

    assert "战斗结果" in report
    assert "战斗时长" in report


def test_config_controls_formation_columns() -> None:
    config = Simulation2DConfig(max_columns=6, min_columns=2)

    assert config.columns_for(1) == 1
    assert config.columns_for(4) == 4
    assert config.columns_for(100) == 6


def test_blocked_melee_slides_sideways_instead_of_waiting() -> None:
    config = Simulation2DConfig()
    unit = _unit("blocked", speed=5.0, attack_melee=10.0)
    mover = Soldier2D(1, Side.BLUE, unit, 100.0, 1.0, 5.0, 0.0)
    blocker = Soldier2D(2, Side.RED, unit, 100.0, 1.0, 5.5, 0.0)
    blocker.stopped = True
    spatial = SpatialHash(config.spatial_cell_size)
    spatial.rebuild([mover, blocker])
    avoidance = LocalAvoidance(config, spatial)

    result = avoidance.choose_velocity(
        mover,
        Vec2(1.0, 0.0),
        field_width=30.0,
        field_height=30.0,
        blocked_ticks=config.blocked_window_ticks,
    )

    assert result.velocity.x < 1.0
    assert abs(result.velocity.y) > 0.1
    assert result.reason in ("free", "separate", "avoid", "detour", "fallback")


def test_nearest_enemy_query_scales_to_large_distance() -> None:
    config = Simulation2DConfig(spatial_cell_size=2.0)
    unit = _unit("scout")
    searcher = Soldier2D(1, Side.RED, unit, 100.0, 100.0, 0.0, 0.0)
    far = Soldier2D(2, Side.BLUE, unit, 100.0, 100.0, 80.0, 0.0)
    nearer = Soldier2D(3, Side.BLUE, unit, 100.0, 100.0, 40.0, 0.0)
    spatial = SpatialHash(config.spatial_cell_size)
    spatial.rebuild([searcher, far, nearer])
    combat = CombatSystem(
        config=config,
        rng=random.Random(1),
        spatial_hash=spatial,
        soldier_map={1: searcher, 2: far, 3: nearer},
        emit=lambda *_args, **_kwargs: None,
        tick_getter=lambda: 0,
        damage_callback=lambda *_args, **_kwargs: None,
        field_width=100.0,
        field_height=100.0,
    )

    assert combat.nearest_enemy(searcher) is nearer


def test_blocked_unit_keeps_lateral_flow_with_friendly_wall() -> None:
    config = Simulation2DConfig()
    unit = _unit("wall", speed=5.0, attack_melee=10.0)
    mover = Soldier2D(1, Side.RED, unit, 100.0, 1.0, 5.0, 0.0)
    wall = [
        Soldier2D(index, Side.RED, unit, 100.0, 1.0, 5.0 + index * 1.1, 0.0)
        for index in range(2, 8)
    ]
    for blocker in wall:
        blocker.stopped = True
    spatial = SpatialHash(config.spatial_cell_size)
    spatial.rebuild([mover, *wall])
    avoidance = LocalAvoidance(config, spatial)

    result = avoidance.choose_velocity(
        mover,
        Vec2(1.0, 0.0),
        field_width=40.0,
        field_height=40.0,
        blocked_ticks=config.blocked_window_ticks,
    )

    assert abs(result.velocity.y) > 0.05
    assert result.velocity.length() > 0.1


def test_rigid_collision_correction_is_bounded() -> None:
    config = Simulation2DConfig(collision_mode=CollisionMode.RIGID)
    unit = _unit("rigid")
    first = Soldier2D(1, Side.RED, unit, 100.0, 10.0, 10.0, 10.0)
    second = Soldier2D(2, Side.BLUE, unit, 100.0, 10.0, 10.1, 10.0)
    spatial = SpatialHash(config.spatial_cell_size)
    spatial.rebuild([first, second])
    resolver = CollisionResolver(config, spatial)

    resolution = resolver.resolve(
        [first, second],
        field_width=30.0,
        field_height=30.0,
    )

    assert abs(first.x - 10.0) <= config.max_position_correction_per_tick + 1e-6
    assert abs(second.x - 10.1) <= config.max_position_correction_per_tick + 1e-6
    assert resolution.corrections >= 1
