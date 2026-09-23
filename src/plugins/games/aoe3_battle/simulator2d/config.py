"""Configuration for the independent 2D battle engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .constants import (
    DEFAULT_ROF_MELEE,
    DEFAULT_ROF_RANGED,
    FIELD_LENGTH,
    MAX_TICKS,
    MELEE_RANGE,
    POP_HOUSE_COST,
    TICK_INTERVAL,
)


class CollisionMode(StrEnum):
    """User-visible physical semantics for the 2D development viewer."""

    RIGID = "rigid"
    SOFT = "soft"


@dataclass(frozen=True)
class Simulation2DConfig:
    """All tunable values for the 2D movement and combat model.

    The defaults are intentionally conservative and tuned for the 2D spatial
    model.
    """

    tick_interval: float = TICK_INTERVAL
    collision_mode: CollisionMode = CollisionMode.RIGID
    max_ticks: int = MAX_TICKS
    field_length: float = FIELD_LENGTH
    melee_range: float = MELEE_RANGE
    default_rof_ranged: float = DEFAULT_ROF_RANGED
    default_rof_melee: float = DEFAULT_ROF_MELEE
    pop_house_cost: int = POP_HOUSE_COST
    close_range_penalty: float = 0.5

    unit_radius: float = 0.45
    formation_spacing: float = 1.25
    row_spacing: float = 2.0
    max_columns: int = 40
    min_columns: int = 1
    formation_side_margin: float = 3.0
    formation_depth_margin: float = 3.0
    max_formation_columns_for_duel: int = 1

    spatial_cell_size: float = 4.0
    avoidance_radius: float = 3.2
    avoidance_horizon: float = 0.85
    avoidance_margin: float = 0.12
    max_neighbors: int = 8
    movement_substeps: int = 2
    separation_iterations: int = 4
    separation_slop: float = 0.002
    max_overlap_for_log: float = 0.08
    max_position_correction_per_tick: float = 0.18

    target_refresh_ticks: int = 6
    target_distance_epsilon: float = 0.05
    blocked_window_ticks: int = 6
    blocked_progress_epsilon: float = 0.015
    detour_commit_ticks: int = 30
    detour_angle_degrees: float = 48.0

    candidate_angles_degrees: tuple[float, ...] = (
        0.0,
        10.0,
        -10.0,
        20.0,
        -20.0,
        35.0,
        -35.0,
        50.0,
        -50.0,
        70.0,
        -70.0,
        90.0,
        -90.0,
    )
    candidate_speed_scales: tuple[float, ...] = (1.0, 0.65, 0.35)

    stop_check_slack: float = 0.02
    nearest_search_min_radius: float = 2.0
    nearest_search_max_radius: float = 256.0

    trace_summary_every_ticks: int = 10
    trace_agent_sample_every_ticks: int = 10
    trace_buffer_ticks: int = 80
    trace_dir: str = "logs/aoe3_battle/traces_2d"

    def columns_for(self, total: int) -> int:
        """Return a compact formation width for ``total`` soldiers."""
        if total <= 0:
            return self.min_columns
        if total == 1:
            return self.max_formation_columns_for_duel

        raw = int(total**0.5 * 1.5) + 1
        return max(self.min_columns, min(self.max_columns, raw))
