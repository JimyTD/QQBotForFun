"""Long-ellipse-only flank routing regressions."""

from __future__ import annotations

from plugins.aoe3.repository import UnitRepo
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D, Simulation2DConfig
from plugins.games.aoe3_battle.simulator2d.model import Side, Vec2
from plugins.games.aoe3_battle.simulator2d.movement import LocalAvoidance


def _wall_scene(
    repo,
    mover_id: str,
    *,
    block_count: int = 8,
    field_height: float = 24.0,
    blocker_side: Side = Side.BLUE,
):
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
    sim._soldier_map.update({mover.id: mover, target.id: target})
    for index in range(block_count):
        y = 12.0 + (index - (block_count - 1) / 2.0) * 1.25
        blocker = sim._create_soldier(10 + index, blocker_side, base, Vec2(14.0, y))
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
    # Friendly blockers: the mover must get past them to its target. With
    # enemy blockers a melee mover simply stops and fights the wall.
    sim, mover, _target = _wall_scene(repo, "ypmahout", blocker_side=Side.RED)

    for tick in range(240):
        sim._tick = tick
        sim._process_movement()
        if mover.x > 16.0:
            break

    assert mover.x > 16.0
    assert mover.detour_remaining or mover.detour_waypoint_x is not None or mover.x > 14.0


def test_long_ellipse_flank_fails_when_side_space_is_too_small() -> None:
    repo = UnitRepo.get()
    sim, mover, target = _wall_scene(repo, "ypmahout", block_count=16, field_height=24.0)

    # The outer edge leaves the field, so the plan is refused with the long
    # backoff instead of squeezing a trimmed route through the wall.
    assert sim._long_ellipse_flank(mover, target) is False
    assert mover.long_ellipse_flank_cooldown_until == sim.config.long_ellipse_flank_cooldown_ticks
    mover.long_ellipse_flank_cooldown_until = 0

    for tick in range(240):
        sim._tick = tick
        sim._process_movement()

    assert mover.x < 14.0


def test_circle_units_do_not_enter_long_ellipse_flank() -> None:
    repo = UnitRepo.get()
    sim, mover, target = _wall_scene(repo, "musketeer")

    used = sim._long_ellipse_flank(mover, target)

    assert used is False
    assert not mover.detour_remaining
    assert mover.detour_waypoint_x is None


def _ellipse_corner(repo, *, blocked_ticks: int):
    """A turning ellipse whose forward sweep is blocked by a stopped neighbor."""
    unit = repo.get_by_id("depetelephant")
    sim = BattleSimulator2D(unit, 1, unit, 1, seed=7)
    sim._init_soldiers()
    sim._soldiers.clear()
    sim._soldier_map.clear()
    sim._field_width = sim._field_height = 40.0
    mover = sim._create_soldier(1, Side.RED, unit, Vec2(20.0, 20.0))
    mover.facing = 0.0
    blocker = sim._create_soldier(2, Side.RED, unit, Vec2(20.0, 22.3))
    blocker.facing = 0.0
    blocker.stopped = True
    sim._soldiers.extend((mover, blocker))
    sim._spatial_hash.rebuild(sim._soldiers)
    avoidance = LocalAvoidance(sim.config, sim._spatial_hash)
    # Last tick it moved toward the blocker; this tick it wants to keep going.
    mover.velocity_x, mover.velocity_y = 0.0, 4.0
    return avoidance.choose_velocity(
        mover,
        Vec2(0.0, 5.0),
        field_width=40.0,
        field_height=40.0,
        blocked_ticks=blocked_ticks,
    ), sim


def test_blocked_ellipse_sweep_does_not_back_off_on_the_first_tick() -> None:
    repo = UnitRepo.get()
    command, _sim = _ellipse_corner(repo, blocked_ticks=0)

    # Backing off here and re-advancing next tick is the reported jitter.
    assert command.velocity.y >= -1e-9


def test_blocked_ellipse_sweep_may_back_off_after_the_blocked_window() -> None:
    repo = UnitRepo.get()
    sim_config = Simulation2DConfig()
    command, _sim = _ellipse_corner(repo, blocked_ticks=sim_config.blocked_window_ticks)

    assert command.velocity.length() > 0.0


def test_elephants_do_not_shuttle_against_a_melee_swarm() -> None:
    repo = UnitRepo.get()
    previous: dict[int, tuple[Vec2, Vec2 | None]] = {}
    reversals = 0
    elephants = set()

    def watch(frame) -> None:
        nonlocal reversals
        for unit in frame["units"]:
            if unit["side"] != "blue":
                continue
            elephants.add(unit["id"])
            pos = Vec2(unit["x"], unit["y"])
            if unit["id"] in previous:
                last_pos, last_step = previous[unit["id"]]
                step = pos - last_pos
                if last_step is not None and step.dot(last_step) < -1e-4:
                    reversals += 1
                previous[unit["id"]] = (pos, step if step.length() > 1e-4 else last_step)
            else:
                previous[unit["id"]] = (pos, None)

    BattleSimulator2D(
        repo.get_by_id("wardog"),
        50,
        repo.get_by_id("depetelephant"),
        8,
        seed=42,
        frame_callback=watch,
    ).run()

    # The old reverse-first fallback made blocked elephants shuttle every
    # tick: about 56 reversals per elephant in this scene, against about 16
    # now. Genuine back-offs after a blocked window remain legal.
    assert elephants
    assert reversals <= len(elephants) * 30
