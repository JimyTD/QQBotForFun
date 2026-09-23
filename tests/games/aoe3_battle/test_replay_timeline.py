"""Adaptive replay timing tests."""

from __future__ import annotations

from src.plugins.games.aoe3_battle.replay.model import (
    Replay,
    ReplayEvent,
    ReplayFrame,
)
from src.plugins.games.aoe3_battle.replay.timeline import build_playback_plan


def _frame(time: float) -> ReplayFrame:
    return ReplayFrame(
        tick=round(time * 10),
        time=time,
        units=[],
        sides={},
        summary={},
        field={"width": 36.0, "height": 36.0},
        status="running",
        winner=None,
    )


def _event(time: float, event_type: str) -> ReplayEvent:
    return ReplayEvent(
        tick=round(time * 10),
        time=time,
        event_type=event_type,
        data={},
    )


def _replay(duration: float, events: list[ReplayEvent]) -> Replay:
    step = 0.5
    frames = [_frame(time) for time in _range(0.0, duration, step)]
    if frames[-1].time < duration:
        frames.append(_frame(duration))
    return Replay(
        session_id="timeline",
        mode="bet",
        match_label="test",
        red_label="red",
        blue_label="blue",
        red_count=20,
        blue_count=20,
        frames=frames,
        events=events,
    )


def _range(start: float, end: float, step: float):
    value = start
    while value < end:
        yield value
        value += step


def test_short_battle_stays_at_normal_speed() -> None:
    replay = _replay(20.0, [_event(2.0, "ATTACK"), _event(18.0, "DEATH")])

    plan = build_playback_plan(replay)

    assert plan.output_duration == 20.0
    assert plan.max_speed == 1.0
    assert {segment.category for segment in plan.segments} == {"normal"}


def test_long_idle_battle_is_compressed() -> None:
    replay = _replay(
        120.0,
        [_event(0.5, "ATTACK"), _event(119.0, "DEATH")],
    )

    plan = build_playback_plan(replay)

    assert plan.output_duration <= 36.0
    assert plan.max_speed >= 5.0
    assert plan.average_speed > 3.0


def test_key_moments_stay_near_normal_speed() -> None:
    replay = _replay(
        100.0,
        [
            _event(10.0, "ATTACK"),
            _event(40.0, "DEATH"),
            _event(70.0, "ATTACK"),
            _event(99.0, "DEATH"),
        ],
    )

    plan = build_playback_plan(replay)

    assert plan.speed_at(10.0) == 1.0
    assert plan.speed_at(40.0) == 1.0
    assert plan.speed_at(99.0) == 1.0


def test_output_and_source_time_round_trip() -> None:
    replay = _replay(80.0, [_event(10.0, "ATTACK"), _event(79.0, "DEATH")])
    plan = build_playback_plan(replay)

    for source_time in (0.0, 5.0, 20.0, 40.0, 60.0, 80.0):
        output_time = plan.output_time_at(source_time)
        assert abs(plan.source_at(output_time) - source_time) < 1e-6


def test_output_samples_cover_compressed_timeline() -> None:
    replay = _replay(80.0, [_event(10.0, "ATTACK"), _event(79.0, "DEATH")])
    plan = build_playback_plan(replay)

    samples = list(plan.iter_output_samples(10))

    assert len(samples) == int(plan.output_duration * 10) or len(samples) == int(
        plan.output_duration * 10
    ) + 1
    assert samples[0] == (0.0, 0.0)
    assert samples[-1][1] <= plan.source_duration
