"""Temporary 2D battle timing. Inactive unless ``activate()`` is called.

Nested buckets (``nav.*``, ``execute``, ``spatial.rebuild``) sit inside the
``phase.*`` totals. Add phase totals to each other; do not add nested buckets
on top of them.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

logger = logging.getLogger("aoe3_battle.simulator2d.perf")

_CURRENT: PerfStats | None = None

_PHASES = (
    "phase.tick",
    "phase.refresh",
    "phase.desired",
    "phase.steer",
    "phase.steer_apply",
    "phase.integrate",
    "phase.resolve",
    "phase.combat",
    "phase.artillery",
    "phase.bookkeeping",
)
_NESTED = (
    "nav.search",
    "nav.route_clear",
    "execute",
    "spatial.rebuild",
)


class PerfStats:
    """Cumulative counters plus a baseline for the current log window."""

    def __init__(self) -> None:
        self.time: dict[str, float] = defaultdict(float)
        self.count: dict[str, int] = defaultdict(int)
        self.max: dict[str, int] = defaultdict(int)
        self.lifetime_max: dict[str, int] = defaultdict(int)
        self._base_time: dict[str, float] = {}
        self._base_count: dict[str, int] = {}
        self._wall_mark = time.perf_counter()
        self.wall_origin = self._wall_mark

    def add_time(self, name: str, seconds: float) -> None:
        self.time[name] += seconds

    def inc(self, name: str, n: int = 1) -> None:
        if n:
            self.count[name] += n

    def observe_max(self, name: str, value: int) -> None:
        if value > self.max[name]:
            self.max[name] = value
        if value > self.lifetime_max[name]:
            self.lifetime_max[name] = value

    def take_window(self) -> tuple[float, dict[str, float], dict[str, int], dict[str, int]]:
        now = time.perf_counter()
        wall = now - self._wall_mark
        self._wall_mark = now
        times = {key: self.time[key] - self._base_time.get(key, 0.0) for key in self.time}
        counts = {key: self.count[key] - self._base_count.get(key, 0) for key in self.count}
        peaks = dict(self.max)
        self.max.clear()
        self._base_time = dict(self.time)
        self._base_count = dict(self.count)
        return wall, times, counts, peaks


class PerfSpan:
    """Record elapsed time when profiling is active."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._started = 0.0

    def __enter__(self) -> PerfSpan:
        if _CURRENT is not None:
            self._started = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        stats = _CURRENT
        if stats is not None:
            stats.add_time(self.name, time.perf_counter() - self._started)


def activate() -> PerfStats:
    """Start a fresh profiling session for this process."""
    global _CURRENT
    _CURRENT = PerfStats()
    return _CURRENT


def deactivate() -> None:
    global _CURRENT
    _CURRENT = None


def mark_start() -> None:
    """Ignore setup time before the first simulated tick."""
    stats = _CURRENT
    if stats is None:
        return
    now = time.perf_counter()
    stats.wall_origin = now
    stats._wall_mark = now


def perf_enabled() -> bool:
    return _CURRENT is not None


def perf_inc(name: str, n: int = 1) -> None:
    stats = _CURRENT
    if stats is not None and n:
        stats.count[name] += n


def perf_max(name: str, value: int) -> None:
    stats = _CURRENT
    if stats is not None:
        stats.observe_max(name, value)


def perf_add_time(name: str, seconds: float) -> None:
    stats = _CURRENT
    if stats is not None:
        stats.add_time(name, seconds)


def log_window(session: str, tick: int, ticks: int) -> None:
    stats = _CURRENT
    if stats is None or ticks <= 0:
        return
    wall, times, counts, peaks = stats.take_window()
    _emit(session, tick, ticks, wall, times, counts, peaks, cumulative=False)


def log_cumulative(session: str, tick: int) -> None:
    stats = _CURRENT
    if stats is None:
        return
    wall = time.perf_counter() - stats.wall_origin
    _emit(
        session,
        tick,
        tick + 1,
        wall,
        dict(stats.time),
        dict(stats.count),
        dict(stats.lifetime_max),
        cumulative=True,
    )


def _emit(
    session: str,
    tick: int,
    ticks: int,
    wall: float,
    times: dict[str, float],
    counts: dict[str, int],
    peaks: dict[str, int],
    *,
    cumulative: bool,
) -> None:
    samples = counts.get("tick.samples", 0) or ticks
    alive_avg = counts.get("tick.alive_sum", 0) / samples if samples else 0.0
    ms_per_tick = wall / ticks * 1000 if ticks else 0.0
    ms_per_unit = ms_per_tick / alive_avg if alive_avg else 0.0
    label = "合计" if cumulative else "区间"
    logger.info(
        "PERF %s %s tick=%d ticks=%d wall=%.2fs tick_accounted=%.2fs "
        "alive_avg=%.1f ms/tick=%.1f ms/unit=%.2f",
        session,
        label,
        tick,
        ticks,
        wall,
        times.get("phase.tick", 0.0),
        alive_avg,
        ms_per_tick,
        ms_per_unit,
    )
    logger.info("  阶段 %s", _format_times(times, wall, _PHASES[1:]))
    logger.info("  内含 %s", _format_times(times, wall, _NESTED))
    logger.info("  转向 %s", _format_steer(counts, peaks))
    logger.info("  绕路 %s", _format_nav(counts, peaks))
    logger.info("  解算 %s", _format_resolve(counts, peaks))


def _format_times(times: dict[str, float], wall: float, names: tuple[str, ...]) -> str:
    parts: list[str] = []
    for name in names:
        seconds = times.get(name, 0.0)
        if seconds < 0.0005:
            continue
        pct = 100.0 * seconds / wall if wall else 0.0
        parts.append(f"{name}={seconds:.3f}s/{pct:.1f}%")
    return " ".join(parts) if parts else "-"


def _ratio(counts: dict[str, int], num: str, den: str) -> str:
    base = counts.get(den, 0)
    if base <= 0:
        return "-"
    return f"{counts.get(num, 0) / base:.2f}"


def _format_steer(counts: dict[str, int], peaks: dict[str, int]) -> str:
    calls = counts.get("steer.calls", 0)
    neighbor_avg = counts.get("steer.neighbor_sum", 0) / calls if calls else 0.0
    reasons = " ".join(
        f"{key.removeprefix('steer.reason.')}={value}"
        for key, value in sorted(counts.items())
        if key.startswith("steer.reason.") and value
    )
    return (
        f"calls={calls} zero={counts.get('steer.desired_zero', 0)} "
        f"early/calls={_ratio(counts, 'steer.early_free', 'steer.calls')} "
        f"tested/call={_ratio(counts, 'steer.tested', 'steer.calls')} "
        f"rejected={counts.get('steer.clear_rejected', 0)} "
        f"pruned={counts.get('steer.pruned', 0)} "
        f"over_cap={counts.get('steer.over_cap', 0)} "
        f"neighbor_avg={neighbor_avg:.2f} neighbor_max={peaks.get('steer.neighbor_max', 0)} "
        f"no_progress_avg={_ratio(counts, 'tick.no_progress_sum', 'tick.samples')} "
        f"movers_avg={_ratio(counts, 'tick.mover_sum', 'tick.samples')} "
        f"{reasons}".rstrip()
    )


def _format_nav(counts: dict[str, int], peaks: dict[str, int]) -> str:
    calls = counts.get("nav.search_calls", 0)
    statuses = " ".join(
        f"{key.removeprefix('nav.status.')}={value}"
        for key, value in sorted(counts.items())
        if key.startswith("nav.status.") and value
    )
    expanded = counts.get("nav.expanded", 0)
    expanded_avg = expanded / calls if calls else 0.0
    slow = counts.get("nav.slow_bodies", 0)
    slow_avg = slow / calls if calls else 0.0
    return (
        f"search={calls} expanded_avg={expanded_avg:.1f} slow_avg={slow_avg:.1f} "
        f"route_clear={counts.get('nav.route_clear_calls', 0)} "
        f"replans={counts.get('nav.replans', 0)} "
        f"expanded_max={peaks.get('nav.expanded_max', 0)} "
        f"{statuses}".rstrip()
    )


def _format_resolve(counts: dict[str, int], peaks: dict[str, int]) -> str:
    calls = counts.get("resolve.calls", 0)
    iters = counts.get("resolve.iterations", 0)
    iter_avg = iters / calls if calls else 0.0
    return (
        f"calls={calls} iter_avg={iter_avg:.2f} "
        f"overlap_pairs={counts.get('resolve.overlap_pairs', 0)} "
        f"corrections={counts.get('resolve.corrections', 0)} "
        f"residual_max_pairs={peaks.get('resolve.residual_pairs', 0)} "
        f"execute={counts.get('execute.calls', 0)} "
        f"clipped={counts.get('execute.clipped', 0)} "
        f"rebuilds={counts.get('spatial.rebuild_calls', 0)}"
    )
