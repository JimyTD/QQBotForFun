"""Structured tracing and invariant checks for the 2D engine."""

from __future__ import annotations

import json
import logging
import math
from collections import deque
from pathlib import Path
from typing import Any

from .config import Simulation2DConfig
from .model import Soldier2D, TickSummary

logger = logging.getLogger("aoe3_battle.simulator2d.trace")


class FlightRecorder:
    """Keep a bounded structured history and flush it on suspicious events."""

    def __init__(
        self,
        *,
        session_id: str,
        seed: int | None,
        config: Simulation2DConfig,
        enabled: bool,
    ) -> None:
        self.session_id = session_id
        self.seed = seed
        self.config = config
        self.enabled = enabled
        self._frames: deque[dict[str, Any]] = deque(
            maxlen=config.trace_buffer_ticks
        )
        self._flush_count = 0
        self._trace_dir = Path(config.trace_dir)

    def record_tick(
        self,
        tick: int,
        *,
        summary: TickSummary,
        decisions: list[dict[str, Any]],
        collision_details: list[dict[str, Any]],
    ) -> None:
        if not self.enabled:
            return
        self._frames.append(
            {
                "tick": tick,
                "summary": {
                    "alive_red": summary.alive_red,
                    "alive_blue": summary.alive_blue,
                    "movers": summary.movers,
                    "attackers": summary.attackers,
                    "blocked": summary.blocked,
                    "wall_contacts": summary.wall_contacts,
                    "collision_pairs": summary.collision_pairs,
                    "max_overlap": round(summary.max_overlap, 4),
                    "avg_speed": round(summary.avg_speed, 4),
                    "solver_fallbacks": summary.solver_fallbacks,
                    "extra": summary.extra,
                },
                "decisions": decisions,
                "collisions": collision_details,
            }
        )

    def flush(self, *, reason: str, context: dict[str, Any]) -> Path | None:
        if not self.enabled:
            return None
        try:
            self._trace_dir.mkdir(parents=True, exist_ok=True)
            timestamp = context.get("timestamp", "latest")
            path = self._trace_dir / (
                f"{timestamp}_{self.session_id}_{reason}_{self._flush_count}.json"
            )
            payload = {
                "session_id": self.session_id,
                "seed": self.seed,
                "reason": reason,
                "context": context,
                "frames": list(self._frames),
            }
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._flush_count += 1
            logger.error("2D trace flushed: %s reason=%s", path, reason)
            return path
        except OSError:
            logger.exception("failed to flush 2D trace reason=%s", reason)
            return None


def nearest_pair_overlap(
    soldiers: list[Soldier2D],
    *,
    radius: float,
) -> tuple[float, tuple[int, int] | None]:
    """Brute-force fallback used by invariant checks."""
    max_overlap = 0.0
    pair: tuple[int, int] | None = None
    alive = [soldier for soldier in soldiers if soldier.alive]
    diameter = radius * 2.0
    for index, first in enumerate(alive):
        for second in alive[index + 1 :]:
            distance = math.hypot(first.x - second.x, first.y - second.y)
            overlap = diameter - distance
            if overlap > max_overlap:
                max_overlap = overlap
                pair = (first.id, second.id)
    return max_overlap, pair
