"""Long-ellipse-only flank routing regressions."""

from __future__ import annotations

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D, Simulation2DConfig
from plugins.games.aoe3_battle.simulator2d.model import Side, Vec2


def _wall_scene(repo, mover_id: str, *, block_count: int = 8, field_height: float = 24.0):
    base = repo.get_by_id("pikeman")
    mover_unit = repo.get_by_id(mover_id)
    sim = BattleSimulator2D(
        mover_unit,
        1,
        base,
        1,
        seed=7,
        config=Simulation2DConfig(movement_substeps=2),
    )
    sim._init_soldiers()
    sim._soldiers.clear()
    sim._soldier_map.clear()
    sim._field_width = 40.0
    sim._field_height = field_height
    mover = sim._create_soldier(1, Side.RED, mover_unit, Vec2(4.0, 12.0))
    target = sim._create_soldier(2, Side.BLUE, base, Vec2(34.0, 12.0))
    target.stopped = True
    sim._soldiers.extend((mover, target))
    for index in range(block_count):
        y = 12.0 + (index - (block_count - 1) / 2.0) * 1.25
        blocker = sim._create_soldier(10 + index, Side.BLUE, base, Vec2(14.0, y))
        blocker.stopped = True
        sim._soldiers.append(blocker)
        sim._soldier_map[blocker.id] = blocker
    mover.move_target_id = target.id
    mover.has_ranged = False
    mover.has_melee = True
    mover.effective_melee_range = 1.5
    mover.effective_ranged_range = 0.0
    mover.effective_ranged_range_min = 0.0
    mover.facing = 0.0
    sim._spatial_hash.rebuild(sim._soldiers)
    return sim, mover, target


def test_long_ellipse_flank_routes_around_a_blocked_front() -> None:
    repo = UnitRepo.get()
    sim, mover, _target = _wall_scene(repo, "ypmahout")

    for tick in range(240):
        sim._tick = tick
        sim._process_movement()
        if mover.x > 16.0:
            break

    assert mover.x > 16.0
    assert mover.detour_remaining or mover.detour_waypoint_x is not None or mover.x > 14.0


def test_long_ellipse_flank_fails_when_side_space_is_too_small() -> None:
    repo = UnitRepo.get()
    sim, mover, _target = _wall_scene(repo, "ypmahout", block_count=16, field_height=24.0)

    for tick in range(240):
        sim._tick = tick
        sim._process_movement()

    assert mover.x < 14.0
    assert mover.long_ellipse_flank_cooldown_until > 0


def test_circle_units_do_not_enter_long_ellipse_flank() -> None:
    repo = UnitRepo.get()
    sim, mover, target = _wall_scene(repo, "musketeer")

    used = sim._long_ellipse_flank(mover, target)

    assert used is False
    assert not mover.detour_remaining
    assert mover.detour_waypoint_x is None
