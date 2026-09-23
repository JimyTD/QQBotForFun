"""Typed, renderer-facing replay data."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReplayFrame:
    """One public simulator frame captured during a battle."""

    tick: int
    time: float
    units: list[dict[str, Any]]
    sides: dict[str, dict[str, Any]]
    summary: dict[str, Any]
    field: dict[str, float]
    status: str
    winner: str | None


@dataclass
class ReplayEvent:
    """One event retained for subtitles and key moments."""

    tick: int
    time: float
    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    x: float | None = None
    y: float | None = None


@dataclass
class Replay:
    """Structured replay independent from the simulator runtime."""

    session_id: str
    mode: str
    match_label: str
    red_label: str
    blue_label: str
    red_count: int
    blue_count: int
    frames: list[ReplayFrame]
    events: list[ReplayEvent]
    result: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        if not self.frames:
            return 0.0
        return max(0.0, self.frames[-1].time)

    @property
    def winner(self) -> str | None:
        if "winner" in self.result:
            return self.result["winner"]
        return self.frames[-1].winner if self.frames else None
