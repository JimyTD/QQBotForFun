"""Tests for the 2D AOE resolver's shape, falloff, and cap spending."""

from __future__ import annotations

import random

import pytest

from plugins.aoe3.models import Unit
from plugins.games.aoe3_battle.battle_contract import EventType, Side
from plugins.games.aoe3_battle.simulator2d.aoe import distance_factor, resolve_aoe
from plugins.games.aoe3_battle.simulator2d.combat import CombatSystem, SlotStats
from plugins.games.aoe3_battle.simulator2d.config import Simulation2DConfig
from plugins.games.aoe3_battle.simulator2d.model import Soldier2D
from plugins.games.aoe3_battle.simulator2d.spatial import SpatialHash


def _unit(unit_id: str) -> Unit:
    return Unit(
        id=unit_id,
        name=unit_id,
        name_en=unit_id,
        hp=1000,
        attack_ranged=100.0,
        range=20.0,
        rof_ranged=1.0,
    )


def _soldier(
    soldier_id: int,
    side: Side,
    x: float,
    y: float,
) -> Soldier2D:
    return Soldier2D(
        id=soldier_id,
        side=side,
        unit=_unit(f"unit-{soldier_id}"),
        hp=1000.0,
        max_hp=1000.0,
        x=x,
        y=y,
    )


def test_distance_factor_has_inner_and_outer_regions() -> None:
    assert distance_factor(0.0, 3.0, 0.5, 0.2) == pytest.approx(1.0)
    assert distance_factor(0.25, 3.0, 0.5, 0.2) == pytest.approx(0.6)
    assert distance_factor(0.5, 3.0, 0.5, 0.2) == pytest.approx(0.2)
    assert distance_factor(2.5, 3.0, 0.5, 0.2) == pytest.approx(0.2)


def test_cap_is_spent_nearest_first() -> None:
    attacker = _soldier(1, Side.RED, 0.0, 0.0)
    main = _soldier(2, Side.BLUE, 10.0, 0.0)
    near = _soldier(3, Side.BLUE, 10.5, 0.0)
    middle = _soldier(4, Side.BLUE, 11.0, 0.0)
    far = _soldier(5, Side.BLUE, 12.0, 0.0)
    soldiers = [attacker, main, near, middle, far]
    spatial = SpatialHash(cell_size=2.0)
    spatial.rebuild(soldiers)

    hits = resolve_aoe(
        attacker=attacker,
        main_target=main,
        radius=3.0,
        base_damage=100.0,
        damage_cap=150.0,
        spatial_hash=spatial,
    )

    assert [hit.target.id for hit in hits] == [3, 4]
    assert hits[0].damage == pytest.approx(100.0)
    assert hits[1].damage == pytest.approx(50.0)


def test_cap_does_not_apply_to_main_target() -> None:
    attacker = _soldier(1, Side.RED, 0.0, 0.0)
    main = _soldier(2, Side.BLUE, 10.0, 0.0)
    far = _soldier(3, Side.BLUE, 20.0, 0.0)
    spatial = SpatialHash(cell_size=2.0)
    spatial.rebuild([attacker, main, far])

    hits = resolve_aoe(
        attacker=attacker,
        main_target=main,
        radius=3.0,
        base_damage=100.0,
        damage_cap=150.0,
        spatial_hash=spatial,
    )

    assert hits == []


def test_directional_mode_excludes_targets_behind_impact() -> None:
    attacker = _soldier(1, Side.RED, 0.0, 0.0)
    main = _soldier(2, Side.BLUE, 10.0, 0.0)
    front = _soldier(3, Side.BLUE, 11.0, 0.0)
    behind = _soldier(4, Side.BLUE, 9.0, 0.0)
    spatial = SpatialHash(cell_size=2.0)
    spatial.rebuild([attacker, main, front, behind])

    hits = resolve_aoe(
        attacker=attacker,
        main_target=main,
        radius=3.0,
        base_damage=100.0,
        damage_cap=500.0,
        area_sort_mode="Directional",
        spatial_hash=spatial,
    )

    assert [hit.target.id for hit in hits] == [3]


def test_radius_uses_2d_plane_distance() -> None:
    attacker = _soldier(1, Side.RED, 0.0, 0.0)
    main = _soldier(2, Side.BLUE, 10.0, 0.0)
    diagonal_inside = _soldier(3, Side.BLUE, 11.0, 1.0)
    outside = _soldier(4, Side.BLUE, 14.0, 0.0)
    spatial = SpatialHash(cell_size=2.0)
    spatial.rebuild([attacker, main, diagonal_inside, outside])

    hits = resolve_aoe(
        attacker=attacker,
        main_target=main,
        radius=2.0,
        base_damage=100.0,
        damage_cap=500.0,
        spatial_hash=spatial,
    )

    assert [hit.target.id for hit in hits] == [3]


def test_combat_system_applies_multiplier_after_cap_allocation() -> None:
    attacker_unit = _unit("artillery")
    target_unit = _unit("infantry")
    target_unit.type = ["Infantry"]
    attacker = _soldier(1, Side.RED, 0.0, 0.0)
    attacker.unit = attacker_unit
    main = _soldier(2, Side.BLUE, 10.0, 0.0)
    main.unit = target_unit
    nearby = _soldier(3, Side.BLUE, 10.5, 0.0)
    nearby.unit = target_unit
    spatial = SpatialHash(cell_size=2.0)
    spatial.rebuild([attacker, main, nearby])

    events: list[tuple[EventType, dict]] = []
    config = Simulation2DConfig()
    system = CombatSystem(
        config=config,
        rng=random.Random(1),
        spatial_hash=spatial,
        soldier_map={soldier.id: soldier for soldier in (attacker, main, nearby)},
        emit=lambda event_type, data: events.append((event_type, data)),
        tick_getter=lambda: 0,
        damage_callback=lambda *_, **__: None,
        field_width=30.0,
        field_height=30.0,
    )

    stats = SlotStats(
        slot="ranged",
        base_damage=100.0,
        num_projectiles=1,
        multipliers=[type("M", (), {"vs": "Infantry", "value": 2.0})()],
        damage_type="Siege",
        aoe_radius=3,
        damage_cap_proto=50.0,
        area_sort_mode="Radial",
        outer_damage_area_distance=0.0,
        outer_damage_area_factor=0.0,
    )
    system.process_aoe(attacker, main, "ranged", slot_stats=stats)

    splash = [
        data
        for event_type, data in events
        if event_type == EventType.AOE_SPLASH
    ]
    assert len(splash) == 1
    assert splash[0]["splash_target_id"] == nearby.id
    assert splash[0]["splash_damage"] == pytest.approx(100.0)
