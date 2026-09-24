"""Adaptive playback timing for battle replays."""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass

from .model import Replay, ReplayEvent

WINDOW_SECONDS = 0.5
SHORT_BATTLE_SECONDS = 40.0
TARGET_TOTAL_SECONDS = 36.0
INTRO_SECONDS = 2.0
OUTRO_SECONDS = 3.0
SPEED_STEP = 0.1
SLOW_SPEED = 0.5
SLOW_WINDOW_PADDING = 1
SLOW_EXTRA_BUDGET_RATIO = 0.2
LAST_DEATH_LEAD = 1


@dataclass(frozen=True)
class PlaybackSegment:
    """One source-time range and its playback speed."""

    source_start: float
    source_end: float
    output_start: float
    output_end: float
    speed: float
    category: str


@dataclass
class _Window:
    source_start: float
    source_end: float
    speed: float
    speed_cap: float
    priority: int
    key: bool
    slow: bool
    category: str


@dataclass(frozen=True)
class PlaybackPlan:
    """A mapping between source time and adaptive output time."""

    source_duration: float
    output_duration: float
    segments: tuple[PlaybackSegment, ...]

    @property
    def max_speed(self) -> float:
        return max((segment.speed for segment in self.segments), default=1.0)

    @property
    def average_speed(self) -> float:
        if self.output_duration <= 0:
            return 1.0
        return self.source_duration / self.output_duration

    def speed_at(self, source_time: float) -> float:
        """Return the playback speed for a source timestamp."""
        source_time = _clamp(source_time, 0.0, self.source_duration)
        for segment in self.segments:
            if segment.source_start <= source_time <= segment.source_end:
                return segment.speed
        return self.segments[-1].speed if self.segments else 1.0

    def source_at(self, output_time: float) -> float:
        """Map one output timestamp back to source time."""
        output_time = _clamp(output_time, 0.0, self.output_duration)
        for segment in self.segments:
            if segment.output_start <= output_time <= segment.output_end:
                span = segment.output_end - segment.output_start
                progress = 1.0 if span <= 0 else (output_time - segment.output_start) / span
                return segment.source_start + (
                    segment.source_end - segment.source_start
                ) * progress
        return self.source_duration

    def output_time_at(self, source_time: float) -> float:
        """Map one source timestamp into the compressed output timeline."""
        source_time = _clamp(source_time, 0.0, self.source_duration)
        for segment in self.segments:
            if segment.source_start <= source_time <= segment.source_end:
                span = segment.source_end - segment.source_start
                progress = 1.0 if span <= 0 else (source_time - segment.source_start) / span
                return segment.output_start + (
                    segment.output_end - segment.output_start
                ) * progress
        return self.output_duration

    def iter_output_samples(self, fps: int):
        """Yield ``(output_time, source_time)`` samples at a fixed output FPS."""
        if self.output_duration <= 0:
            yield 0.0, 0.0
            return
        frame_count = max(1, math.floor(self.output_duration * fps + 1e-9))
        for index in range(frame_count):
            output_time = index / fps
            yield output_time, self.source_at(output_time)
        yield self.output_duration, self.source_duration


def build_playback_plan(
    replay: Replay,
    *,
    target_total_seconds: float = TARGET_TOTAL_SECONDS,
    short_battle_seconds: float = SHORT_BATTLE_SECONDS,
) -> PlaybackPlan:
    """Build an event-density-driven playback plan for one replay."""
    duration = max(0.0, replay.duration)
    windows = _build_windows(replay)
    if duration <= short_battle_seconds:
        for window in windows:
            window.speed = 1.0
            window.speed_cap = 1.0
            window.priority = 0
            window.key = False
            window.slow = False
            window.category = "normal"
        _apply_slow_windows(windows, replay)
        return _plan_from_windows(duration, windows)

    _apply_slow_windows(windows, replay)
    _apply_transition_caps(windows)
    _smooth_speeds(windows)
    _apply_transition_caps(windows)

    target_battle_seconds = max(
        1.0,
        target_total_seconds - INTRO_SECONDS - OUTRO_SECONDS,
    )
    _fit_to_target(windows, target_battle_seconds)
    return _plan_from_windows(duration, windows)


def _single_speed_plan(duration: float, speed: float) -> PlaybackPlan:
    output_duration = duration / speed
    segment = PlaybackSegment(
        source_start=0.0,
        source_end=duration,
        output_start=0.0,
        output_end=output_duration,
        speed=speed,
        category="normal",
    )
    return PlaybackPlan(
        source_duration=duration,
        output_duration=output_duration,
        segments=(segment,),
    )


def _build_windows(replay: Replay) -> list[_Window]:
    duration = max(0.0, replay.duration)
    count = max(1, math.ceil(duration / WINDOW_SECONDS))
    windows: list[_Window] = []
    for index in range(count):
        start = index * WINDOW_SECONDS
        end = min(duration, start + WINDOW_SECONDS)
        windows.append(
            _Window(
                source_start=start,
                source_end=end,
                speed=1.0,
                speed_cap=1.0,
                priority=0,
                key=False,
                slow=False,
                category="normal",
            )
        )

    events = [
        event
        for event in replay.events
        if event.event_type in {"ATTACK", "AOE_SPLASH", "DEATH"}
    ]
    attack_counts = [0] * count
    death_counts = [0] * count
    event_times: list[float] = []
    for event in events:
        index = _window_index(event.time, count)
        event_times.append(event.time)
        if event.event_type == "DEATH":
            death_counts[index] += 1
        else:
            attack_counts[index] += 1
    event_times.sort()

    key_indices = _key_indices(replay, events, death_counts, count)
    total_units = max(1, replay.red_count + replay.blue_count)
    high_attack_threshold = max(3, math.ceil(total_units * 0.04))
    medium_attack_threshold = max(1, math.ceil(total_units * 0.015))

    for index, window in enumerate(windows):
        midpoint = (window.source_start + window.source_end) / 2
        nearest_event = _nearest_event_distance(midpoint, event_times)
        attack_count = attack_counts[index]
        death_count = death_counts[index]

        if index in key_indices:
            window.speed = 1.0
            window.speed_cap = 1.0
            window.priority = 99
            window.key = True
            window.category = "key"
            continue

        if attack_count >= high_attack_threshold:
            window.speed = 1.5
            window.speed_cap = 1.75
            window.priority = 3
            window.category = "intense"
        elif attack_count >= medium_attack_threshold or death_count:
            window.speed = 2.0
            window.speed_cap = 2.5
            window.priority = 2
            window.category = "combat"
        elif attack_count:
            window.speed = 2.5
            window.speed_cap = 4.0
            window.priority = 1
            window.category = "sparse"
        elif nearest_event is None or nearest_event > 3.0:
            window.speed = 8.0
            window.speed_cap = 8.0
            window.priority = 0
            window.category = "idle"
        elif nearest_event > 1.0:
            window.speed = 5.0
            window.speed_cap = 8.0
            window.priority = 0
            window.category = "approach"
        else:
            window.speed = 3.0
            window.speed_cap = 5.0
            window.priority = 1
            window.category = "approach"
    return windows


def _key_indices(
    replay: Replay,
    events: list[ReplayEvent],
    death_counts: list[int],
    count: int,
) -> set[int]:
    key_indices: set[int] = set()
    first_attack = next((event for event in events if event.event_type != "DEATH"), None)
    first_death = next((event for event in events if event.event_type == "DEATH"), None)
    last_death = next(
        (event for event in reversed(events) if event.event_type == "DEATH"),
        None,
    )
    for event in (first_attack, first_death, last_death):
        if event is not None:
            _mark_near(key_indices, _window_index(event.time, count), count)

    total_units = max(1, replay.red_count + replay.blue_count)
    major_death_threshold = max(2, math.ceil(total_units * 0.08))
    for index, deaths in enumerate(death_counts):
        if deaths >= major_death_threshold:
            _mark_near(key_indices, index, count)

    for index in range(max(0, count - 2), count):
        key_indices.add(index)
    return key_indices


def _apply_slow_windows(windows: list[_Window], replay: Replay) -> None:
    """Mark mass-death and final-kill windows for 0.5x playback."""
    if not windows:
        return
    deaths: dict[int, int] = {}
    death_times: list[float] = []
    for event in replay.events:
        if event.event_type != "DEATH":
            continue
        index = _window_index(event.time, len(windows))
        deaths[index] = deaths.get(index, 0) + 1
        death_times.append(event.time)
    if not death_times:
        return

    total_units = max(1, replay.red_count + replay.blue_count)
    mass_death_threshold = max(4, math.ceil(total_units * 0.08))
    slow_indices: set[int] = set()
    for index, count in deaths.items():
        if count >= mass_death_threshold:
            for offset in range(
                -SLOW_WINDOW_PADDING,
                SLOW_WINDOW_PADDING + 1,
            ):
                candidate = index + offset
                if 0 <= candidate < len(windows):
                    slow_indices.add(candidate)

    last_window = _window_index(max(death_times), len(windows))
    final_slow_indices = set(
        range(max(0, last_window - LAST_DEATH_LEAD), last_window + 1)
    )
    for offset in range(-LAST_DEATH_LEAD, 1):
        candidate = last_window + offset
        if 0 <= candidate < len(windows):
            slow_indices.add(candidate)

    if replay.duration <= SHORT_BATTLE_SECONDS:
        for index in slow_indices:
            window = windows[index]
            window.speed = SLOW_SPEED
            window.speed_cap = SLOW_SPEED
            window.priority = 100
            window.key = True
            window.slow = True
            window.category = "slow"
        return

    # Keep slow-motion bounded relative to the rest of the battle.
    # Budget slow motion by its expected output time (source / 0.5),
    # while allowing at least the final-kill window pair.
    max_slow_extra = max(
        WINDOW_SECONDS / SLOW_SPEED,
        replay.duration * SLOW_EXTRA_BUDGET_RATIO,
    )
    # Last-kill windows get first claim, then mass-death windows fill the
    # remaining budget. The hard cap applies to all slow motion.
    final_slow_indices = {last_window}
    slow_output = 0.0
    retained_slow: set[int] = set()
    # Final-kill windows are always retained first; mass-death windows then
    # fill whatever remains of the slow-motion budget.
    for index in sorted(final_slow_indices):
        retained_slow.add(index)
        slow_output += (
            windows[index].source_end - windows[index].source_start
        ) / SLOW_SPEED
    for index in sorted(slow_indices - final_slow_indices):
        source_span = (
            windows[index].source_end - windows[index].source_start
        )
        extra_span = source_span * (1 / SLOW_SPEED - 1)
        if slow_output + extra_span > max_slow_extra:
            continue
        retained_slow.add(index)
        slow_output += extra_span
    slow_indices = retained_slow
    for index in slow_indices:
        window = windows[index]
        window.speed = SLOW_SPEED
        window.speed_cap = SLOW_SPEED
        window.priority = 100
        window.key = True
        window.slow = True
        window.category = "slow"

    # Keep one transition window on each side from jumping directly to idle speed.
    for index in slow_indices:
        for neighbor in (index - 1, index + 1):
            if (
                0 <= neighbor < len(windows)
                and not windows[neighbor].slow
                and windows[neighbor].speed > 3.0
            ):
                windows[neighbor].speed = 3.0
                windows[neighbor].speed_cap = min(3.0, windows[neighbor].speed_cap)


def _mark_near(indices: set[int], center: int, count: int) -> None:
    for index in range(max(0, center - 1), min(count, center + 2)):
        indices.add(index)


def _window_index(source_time: float, count: int) -> int:
    return max(0, min(count - 1, int(source_time / WINDOW_SECONDS)))


def _nearest_event_distance(source_time: float, event_times: list[float]) -> float | None:
    if not event_times:
        return None
    index = bisect_left(event_times, source_time)
    candidates = []
    if index < len(event_times):
        candidates.append(abs(event_times[index] - source_time))
    if index > 0:
        candidates.append(abs(event_times[index - 1] - source_time))
    return min(candidates) if candidates else None


def _apply_transition_caps(windows: list[_Window]) -> None:
    key_indices = [index for index, window in enumerate(windows) if window.key]
    if not key_indices:
        return
    for index, window in enumerate(windows):
        if window.slow:
            window.speed = SLOW_SPEED
            window.speed_cap = SLOW_SPEED
            continue
        if window.key:
            window.speed = 1.0
            window.speed_cap = 1.0
            continue
        distance = min(abs(index - key_index) for key_index in key_indices)
        cap = window.speed_cap
        if distance == 1:
            cap = min(cap, 2.0)
        elif distance == 2:
            cap = min(cap, 3.0)
        window.speed_cap = cap
        window.speed = min(window.speed, cap)


def _smooth_speeds(windows: list[_Window]) -> None:
    for _ in range(2):
        previous = [window.speed for window in windows]
        for index, window in enumerate(windows):
            if window.slow:
                window.speed = SLOW_SPEED
                continue
            if window.key:
                window.speed = 1.0
                continue
            before = previous[max(0, index - 1)]
            after = previous[min(len(previous) - 1, index + 1)]
            window.speed = min(
                window.speed_cap,
                max(1.0, (before + previous[index] * 2 + after) / 4),
            )


def _fit_to_target(windows: list[_Window], target_seconds: float) -> None:
    output_duration = _window_output_duration(windows)
    if output_duration <= target_seconds:
        return
    priorities = sorted({window.priority for window in windows if not window.key})
    for _ in range(256):
        changed = False
        for priority in priorities:
            candidates = [
                window
                for window in windows
                if not window.key
                and not window.slow
                and window.priority == priority
                and window.speed < window.speed_cap - 1e-9
            ]
            if not candidates:
                continue
            for window in candidates:
                window.speed = min(window.speed_cap, window.speed + SPEED_STEP)
            changed = True
            output_duration = _window_output_duration(windows)
            if output_duration <= target_seconds:
                return
        if not changed:
            return


def _window_output_duration(windows: list[_Window]) -> float:
    return sum(
        (window.source_end - window.source_start) / max(0.01, window.speed)
        for window in windows
    )


def _plan_from_windows(duration: float, windows: list[_Window]) -> PlaybackPlan:
    output_cursor = 0.0
    segments: list[PlaybackSegment] = []
    for window in windows:
        output_span = (window.source_end - window.source_start) / max(0.01, window.speed)
        segments.append(
            PlaybackSegment(
                source_start=window.source_start,
                source_end=window.source_end,
                output_start=output_cursor,
                output_end=output_cursor + output_span,
                speed=window.speed,
                category=window.category,
            )
        )
        output_cursor += output_span
    if segments:
        segments[-1] = PlaybackSegment(
            source_start=segments[-1].source_start,
            source_end=duration,
            output_start=segments[-1].output_start,
            output_end=output_cursor,
            speed=segments[-1].speed,
            category=segments[-1].category,
        )
    return PlaybackPlan(
        source_duration=duration,
        output_duration=output_cursor,
        segments=tuple(segments),
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
