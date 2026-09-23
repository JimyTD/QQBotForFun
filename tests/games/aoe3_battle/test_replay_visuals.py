"""Replay visual effect tests."""

from __future__ import annotations

from src.plugins.games.aoe3_battle.replay.model import (
    Replay,
    ReplayEvent,
    ReplayFrame,
)
from src.plugins.games.aoe3_battle.replay.renderer import ReplayRenderer


def _frame(time: float) -> ReplayFrame:
    return ReplayFrame(
        tick=round(time * 10),
        time=time,
        units=[
            {
                "id": 1,
                "side": "red",
                "unit_id": "a",
                "name": "A",
                "x": 10.0,
                "y": 10.0,
                "hp": 50.0,
                "max_hp": 100.0,
                "radius": 0.45,
                "stopped": True,
                "target_id": 2,
            },
            {
                "id": 2,
                "side": "blue",
                "unit_id": "b",
                "name": "B",
                "x": 20.0,
                "y": 10.0,
                "hp": 40.0,
                "max_hp": 100.0,
                "radius": 0.45,
                "stopped": True,
                "target_id": 1,
            },
        ],
        sides={
            "red": {
                "alive": 1,
                "initial_count": 1,
                "hp_ratio": 0.5,
                "composition": [{"name": "A", "count": 1}],
            },
            "blue": {
                "alive": 1,
                "initial_count": 1,
                "hp_ratio": 0.4,
                "composition": [{"name": "B", "count": 1}],
            },
        },
        summary={},
        field={"width": 36.0, "height": 36.0},
        status="running",
        winner=None,
    )


def _event(
    time: float,
    event_type: str,
    *,
    x: float | None = None,
    y: float | None = None,
    data: dict | None = None,
) -> ReplayEvent:
    return ReplayEvent(
        tick=round(time * 10),
        time=time,
        event_type=event_type,
        data=data or {},
        x=x,
        y=y,
    )


def _replay(events: list[ReplayEvent]) -> Replay:
    return Replay(
        session_id="visuals",
        mode="bet",
        match_label="visuals",
        red_label="red",
        blue_label="blue",
        red_count=1,
        blue_count=1,
        frames=[_frame(time) for time in (0.0, 0.1, 0.2, 0.3, 1.0)],
        events=events,
    )


def test_projectile_effect_expires_quickly() -> None:
    replay = _replay(
        [
            _event(
                0.1,
                "ATTACK",
                data={"attacker_id": 1, "target_id": 2, "mode": "ranged"},
            )
        ]
    )
    renderer = ReplayRenderer()
    active = renderer._render_frame(replay, replay.frames[2])
    expired = renderer._render_frame(replay, replay.frames[4])

    assert active.tobytes() != expired.tobytes()


def test_aoe_and_death_effects_are_short_lived() -> None:
    replay = _replay(
        [
            _event(
                0.1,
                "AOE_SPLASH",
                x=10.0,
                y=10.0,
                data={"radius": 2.0},
            ),
            _event(
                0.1,
                "DEATH",
                x=20.0,
                y=10.0,
                data={},
            ),
        ]
    )
    renderer = ReplayRenderer()
    active = renderer._render_frame(replay, replay.frames[2])
    expired = renderer._render_frame(replay, replay.frames[4])

    assert active.tobytes() != expired.tobytes()


def test_hud_contains_composition_and_speed() -> None:
    replay = _replay([])
    renderer = ReplayRenderer()
    frame = replay.frames[1]

    image = renderer._render_frame(replay, frame)

    assert image.size == (960, 540)
