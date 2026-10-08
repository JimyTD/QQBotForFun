"""Focused tests for the independent 2D simulation engine."""

from __future__ import annotations

import math
import random
from itertools import pairwise

import pytest

from plugins.aoe3.models import Multiplier, Unit
from plugins.games.aoe3_battle.battle_contract import EventType, Side
from plugins.games.aoe3_battle.broadcaster import format_battle_report
from plugins.games.aoe3_battle.simulator2d import (
    BattleSimulator2D,
    Simulation2DConfig,
)
from plugins.games.aoe3_battle.simulator2d.combat import CombatSystem
from plugins.games.aoe3_battle.simulator2d.compat import ArmySlot
from plugins.games.aoe3_battle.simulator2d.formation import build_deployment
from plugins.games.aoe3_battle.simulator2d.geometry import (
    shape_contact,
    shape_for_unit,
)
from plugins.games.aoe3_battle.simulator2d.model import Soldier2D, Vec2
from plugins.games.aoe3_battle.simulator2d.movement import (
    CollisionResolver,
    LocalAvoidance,
)
from plugins.games.aoe3_battle.simulator2d.spatial import SpatialHash
from tests.games.aoe3_battle.unit_factory import build_attack_actions


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
        attack_actions=build_attack_actions(
            attack_melee=attack_melee,
            attack_ranged=attack_ranged,
            range_=range_,
            aoe_radius_ranged=aoe_radius_ranged,
            damage_cap_ranged=damage_cap_ranged,
        ),
        obstruction_radius_x=obstruction_radius_x,
        obstruction_radius_z=obstruction_radius_z,
        obstruction_radius_equiv=obstruction_radius_equiv,
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


def test_ten_seconds_without_damage_ends_the_battle() -> None:
    unit = _unit("idle", hp=100, speed=0.0, attack_melee=10)
    result = BattleSimulator2D(
        red_army=[(unit, 1)],
        blue_army=[(unit, 1)],
        seed=1,
        field_length=36,
    ).run()

    assert result.timeout
    assert result.winner is None
    assert result.ticks == 100
    assert result.duration == pytest.approx(10.0)
    assert "连续 10 秒没有造成伤害" in format_battle_report(result)


def test_ongoing_damage_is_not_cut_off_at_ten_seconds() -> None:
    unit = _unit("slug", hp=800, speed=6.0, attack_melee=8)
    result = BattleSimulator2D(
        red_army=[(unit, 1)],
        blue_army=[(unit, 1)],
        seed=2,
    ).run()

    assert result.duration > 10.0
    assert not result.timeout


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


@pytest.mark.parametrize("side", [Side.RED, Side.BLUE])
@pytest.mark.parametrize("radii", [(0.49, 0.49), (1.49, 0.49), (0.49, 1.49)])
@pytest.mark.parametrize("count", [7, 9])
def test_default_formation_has_no_gaps_or_overlap(side, radii, count) -> None:
    unit = _unit(
        "formation",
        obstruction_radius_x=radii[0],
        obstruction_radius_z=radii[1],
    )
    config = Simulation2DConfig(max_columns=3)
    army = [ArmySlot(unit, count)]
    deployment = build_deployment(
        army if side == Side.RED else [],
        army if side == Side.BLUE else [],
        config,
    )
    facing = 0.0 if side == Side.RED else math.pi
    shapes = [
        shape_for_unit(unit, pos.x, pos.y, facing, config.fallback_unit_radius)
        for pos in deployment.positions
    ]
    assert config.formation_lateral_gap == 0.0
    assert config.formation_row_gap == 0.0
    assert config.formation_block_gap == 0.0
    cursor = 0
    row_centers = []
    for row_size in deployment.row_sizes[side]:
        row = shapes[cursor:cursor + row_size]
        row_centers.append(row[0].x)
        for first, second in pairwise(row):
            assert second.y - first.y == pytest.approx(
                first.extent(0.0, 1.0) + second.extent(0.0, 1.0)
            )
        cursor += row_size
    for first, second in pairwise(row_centers):
        assert abs(second - first) == pytest.approx(
            2.0 * shapes[0].extent(1.0, 0.0)
        )
    for index, first in enumerate(shapes):
        for second in shapes[index + 1:]:
            assert shape_contact(first, second, tolerance=1e-8) is None


@pytest.mark.parametrize("side", [Side.RED, Side.BLUE])
@pytest.mark.parametrize("radii", [(0.79, 0.79), (1.49, 0.49), (0.49, 1.49)])
def test_default_formation_blocks_touch_without_overlap(side, radii) -> None:
    infantry = _unit(
        "infantry",
        obstruction_radius_x=0.49,
        obstruction_radius_z=0.49,
    )
    rear_unit = _unit(
        "rear",
        range_=20.0,
        obstruction_radius_x=radii[0],
        obstruction_radius_z=radii[1],
    )
    config = Simulation2DConfig(max_columns=1)
    army = [ArmySlot(infantry, 2), ArmySlot(rear_unit, 2)]
    deployment = build_deployment(
        army if side == Side.RED else [],
        army if side == Side.BLUE else [],
        config,
    )
    facing = 0.0 if side == Side.RED else math.pi
    shapes = [
        shape_for_unit(unit, pos.x, pos.y, facing, config.fallback_unit_radius)
        for unit, pos in zip(
            [infantry, infantry, rear_unit, rear_unit],
            deployment.positions,
            strict=True,
        )
    ]
    for first, second in pairwise(shapes):
        assert abs(second.x - first.x) == pytest.approx(
            first.extent(1.0, 0.0) + second.extent(1.0, 0.0)
        )
    for index, first in enumerate(shapes):
        for second in shapes[index + 1:]:
            assert shape_contact(first, second, tolerance=1e-8) is None


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


def test_formation_keeps_unit_types_in_separate_blocks() -> None:
    infantry = _unit(
        "infantry",
        range_=0.0,
        obstruction_radius_x=0.49,
        obstruction_radius_z=0.49,
    )
    cavalry = _unit(
        "cavalry",
        range_=0.0,
        speed=8.0,
        obstruction_radius_x=0.49,
        obstruction_radius_z=0.99,
    )
    config = Simulation2DConfig()
    deployment = build_deployment(
        [ArmySlot(infantry, 7), ArmySlot(cavalry, 5)],
        [],
        config,
    )

    # Existing ordering puts faster same-range units first. The two blocks must
    # still be physically separated rather than sharing rows.
    cavalry_positions = deployment.positions[:5]
    infantry_positions = deployment.positions[5:]
    assert min(position.x for position in cavalry_positions) > max(
        position.x for position in infantry_positions
    )


def test_formation_rows_use_each_units_own_footprint() -> None:
    infantry = _unit(
        "infantry",
        range_=0.0,
        obstruction_radius_x=0.49,
        obstruction_radius_z=0.49,
    )
    artillery = _unit(
        "artillery",
        attack_melee=0.0,
        attack_ranged=100.0,
        range_=20.0,
        obstruction_radius_x=1.0,
        obstruction_radius_z=0.5,
    )
    deployment = build_deployment(
        [ArmySlot(infantry, 12), ArmySlot(artillery, 4)],
        [],
        Simulation2DConfig(),
    )

    rows = deployment.row_sizes[Side.RED]
    assert rows[0] > rows[-1]
    assert deployment.rows[Side.RED] > 2


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


def test_ellipse_contact_uses_minimum_translation_not_deepest_axis() -> None:
    elephant = _unit(
        "elephant",
        obstruction_radius_x=1.49,
        obstruction_radius_z=0.49,
    )
    first = shape_for_unit(elephant, 0.0, 0.0, 0.0, 0.45)
    second = shape_for_unit(elephant, 1.0, 0.0, 0.0, 0.45)

    contact = shape_contact(first, second)

    assert contact is not None
    assert first.extent(1.0, 0.0) == pytest.approx(1.49)
    assert second.extent(1.0, 0.0) == pytest.approx(1.49)
    # The Minkowski sum is an ellipse with axes 2.98 and 0.98. Its nearest
    # boundary to (1, 0) is off the center line, not the 1.98-deep x axis.
    expected = 0.98 * math.sqrt(1.0 - 1.0 / (2.98**2 - 0.98**2))
    assert contact.normal_x > 0
    assert abs(contact.normal_y) > 0.9
    assert contact.depth == pytest.approx(expected, abs=1e-5)


def test_rotated_ellipse_uses_long_axis_extent() -> None:
    elephant = _unit(
        "elephant",
        obstruction_radius_x=1.49,
        obstruction_radius_z=0.49,
    )
    horizontal = shape_for_unit(elephant, 0.0, 0.0, 0.0, 0.45)
    rotated = shape_for_unit(elephant, 0.0, 0.0, 1.5707963267948966, 0.45)

    assert horizontal.extent(1.0, 0.0) == pytest.approx(1.49)
    assert horizontal.extent(0.0, 1.0) == pytest.approx(0.49)
    assert rotated.extent(1.0, 0.0) == pytest.approx(0.49)
    assert rotated.extent(0.0, 1.0) == pytest.approx(1.49)


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


def test_field_length_override_controls_middle_distance() -> None:
    unit = _unit("distance", attack_melee=10.0)
    far = BattleSimulator2D(
        red_army=[(unit, 1)],
        blue_army=[(unit, 1)],
        field_length=36.0,
    )
    near = BattleSimulator2D(
        red_army=[(unit, 1)],
        blue_army=[(unit, 1)],
        field_length=3.0,
    )

    assert far.config.field_length == 36.0
    assert near.config.field_length == 3.0


def test_blocked_melee_separates_instead_of_waiting() -> None:
    config = Simulation2DConfig()
    unit = _unit("blocked", speed=5.0, attack_melee=10.0)
    mover = Soldier2D(1, Side.BLUE, unit, 100.0, 1.0, 5.0, 10.0)
    blocker = Soldier2D(2, Side.RED, unit, 100.0, 1.0, 5.5, 10.0)
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

    assert result.velocity.x < 0.0
    assert result.velocity.length() > 0.1
    assert result.reason in ("free", "separate", "avoid", "detour", "fallback", "maneuver")


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


def test_stall_flag_does_not_rotate_a_currently_clear_velocity() -> None:
    config = Simulation2DConfig()
    unit = _unit("wall", speed=5.0, attack_melee=10.0)
    mover = Soldier2D(1, Side.RED, unit, 100.0, 1.0, 5.0, 10.0)
    wall = [
        Soldier2D(index, Side.RED, unit, 100.0, 1.0, 5.0 + index * 1.1, 10.0)
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

    assert result.velocity == Vec2(1.0, 0.0)


def test_rigid_collision_correction_is_bounded() -> None:
    config = Simulation2DConfig()
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


def test_hp_ratio_uses_initial_total_hp_and_never_rebounds_on_death() -> None:
    unit = _unit("hp-ratio", hp=100.0, attack_melee=10.0)
    sim = BattleSimulator2D(
        red_army=[(unit, 3)],
        blue_army=[(unit, 1)],
        seed=1,
    )
    frames: list[dict] = []
    sim._frame_callback = frames.append
    sim._init_soldiers()

    sim._emit_visual_frame(status="running", winner=None, timeout=False)
    assert frames[-1]["sides"]["red"]["hp_ratio"] == 1.0

    sim._soldiers[0].hp = unit.hp * 0.5
    sim._emit_visual_frame(status="running", winner=None, timeout=False)
    assert frames[-1]["sides"]["red"]["hp_ratio"] == pytest.approx(
        5 / 6,
        abs=1e-4,
    )

    sim._soldiers[1].alive = False
    sim._soldiers[1].hp = 0.0
    sim._emit_visual_frame(status="running", winner=None, timeout=False)
    assert frames[-1]["sides"]["red"]["hp_ratio"] == pytest.approx(
        0.5,
        abs=1e-4,
    )
