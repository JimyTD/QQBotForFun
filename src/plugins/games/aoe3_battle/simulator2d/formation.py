"""Initial 2D formation placement."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ....aoe3.models import Unit
from .compat import ArmySlot, Side
from .config import Simulation2DConfig
from .geometry import directional_extent
from .model import Vec2


@dataclass(frozen=True)
class Deployment:
    """Concrete battlefield placement for both armies."""

    positions: list[Vec2]
    field_width: float
    field_height: float
    columns: dict[Side, int]
    rows: dict[Side, int]
    row_sizes: dict[Side, tuple[int, ...]]


@dataclass(frozen=True)
class _Block:
    """One unit type packed into centered rows."""

    units: tuple[Unit, ...]
    columns: int
    rows: int
    row_sizes: tuple[int, ...]
    lateral_pitch: float
    longitudinal_pitch: float
    lateral_extent: float
    longitudinal_extent: float

    @property
    def width(self) -> float:
        return self.columns * self.lateral_pitch

    @property
    def depth(self) -> float:
        return self.rows * self.longitudinal_pitch


def _ordered_slots(army: list[ArmySlot]) -> list[ArmySlot]:
    return sorted(
        army,
        key=lambda item: (item.unit.range, -item.unit.speed, item.unit.id),
    )


def _blocks(army: list[ArmySlot], config: Simulation2DConfig) -> list[_Block]:
    """Group units by type while preserving the existing front-to-back order."""
    grouped: list[list[Unit]] = []
    for slot in _ordered_slots(army):
        for _ in range(slot.count):
            if not grouped or grouped[-1][0].id != slot.unit.id:
                grouped.append([])
            grouped[-1].append(slot.unit)
    return [_layout_block(tuple(units), config) for units in grouped]


def _layout_block(units: tuple[Unit, ...], config: Simulation2DConfig) -> _Block:
    if not units:
        return _Block((), 0, 0, (), 0.0, 0.0, 0.0, 0.0)

    unit = units[0]
    lateral_extent = directional_extent(unit, 0.0, 0.0, 1.0, config.fallback_unit_radius)
    longitudinal_extent = directional_extent(
        unit,
        0.0,
        1.0,
        0.0,
        config.fallback_unit_radius,
    )
    lateral_pitch = 2.0 * lateral_extent + config.formation_lateral_gap
    longitudinal_pitch = 2.0 * longitudinal_extent + config.formation_row_gap

    # A square-ish block avoids both a long single row and an unnecessarily
    # deep column, while still letting larger footprints fill fewer units per row.
    ideal_columns = math.ceil(
        math.sqrt(len(units) * longitudinal_pitch / lateral_pitch)
    )
    columns = max(config.min_columns, ideal_columns)
    columns = min(len(units), config.max_columns, columns)
    rows = (len(units) + columns - 1) // columns
    row_sizes = tuple(
        min(columns, len(units) - row * columns)
        for row in range(rows)
    )
    return _Block(
        units=units,
        columns=columns,
        rows=rows,
        row_sizes=row_sizes,
        lateral_pitch=lateral_pitch,
        longitudinal_pitch=longitudinal_pitch,
        lateral_extent=lateral_extent,
        longitudinal_extent=longitudinal_extent,
    )


def _side_depth(blocks: list[_Block], config: Simulation2DConfig) -> float:
    if not blocks:
        return 0.0
    # Each block spans from its front edge to its back edge. Consecutive
    # blocks are separated by the same physical gap, not their center pitch.
    return sum(block.depth for block in blocks) + config.formation_block_gap * len(
        blocks
    )


def _max_block_width(blocks: list[_Block]) -> float:
    if not blocks:
        return 0.0
    return max(
        (block.columns - 1) * block.lateral_pitch + block.lateral_extent * 2.0
        for block in blocks
    )


def build_deployment(
    red_army: list[ArmySlot],
    blue_army: list[ArmySlot],
    config: Simulation2DConfig,
) -> Deployment:
    """Place both armies facing each other on a shared battlefield."""
    red_blocks = _blocks(red_army, config)
    blue_blocks = _blocks(blue_army, config)
    red_depth = _side_depth(red_blocks, config)
    blue_depth = _side_depth(blue_blocks, config)

    max_block_width = max(
        _max_block_width(red_blocks),
        _max_block_width(blue_blocks),
    )
    field_height = max(
        config.field_length,
        max_block_width + config.formation_side_margin * 2.0,
    )
    field_width = (
        config.formation_depth_margin * 2.0
        + red_depth
        + config.field_length
        + blue_depth
    )
    mid_y = field_height / 2.0
    red_front_edge = config.formation_depth_margin + red_depth
    blue_front_edge = red_front_edge + config.field_length

    red_positions, red_rows = _place_side(
        red_blocks,
        front_edge=red_front_edge,
        mid_y=mid_y,
        outward=-1.0,
        config=config,
    )
    blue_positions, blue_rows = _place_side(
        blue_blocks,
        front_edge=blue_front_edge,
        mid_y=mid_y,
        outward=1.0,
        config=config,
    )
    return Deployment(
        positions=[*red_positions, *blue_positions],
        field_width=field_width,
        field_height=field_height,
        columns={
            Side.RED: max((block.columns for block in red_blocks), default=0),
            Side.BLUE: max((block.columns for block in blue_blocks), default=0),
        },
        rows=red_rows | blue_rows,
        row_sizes={
            Side.RED: tuple(
                size for block in red_blocks for size in block.row_sizes
            ),
            Side.BLUE: tuple(
                size for block in blue_blocks for size in block.row_sizes
            ),
        },
    )


def _place_side(
    blocks: list[_Block],
    *,
    front_edge: float,
    mid_y: float,
    outward: float,
    config: Simulation2DConfig,
) -> tuple[list[Vec2], dict[Side, int]]:
    positions: list[Vec2] = []
    row_count = 0
    edge = front_edge
    side = Side.RED if outward < 0 else Side.BLUE
    for block in blocks:
        first_center = edge + outward * block.longitudinal_extent
        for row_index, visible_columns in enumerate(block.row_sizes):
            x = first_center + outward * row_index * block.longitudinal_pitch
            row_width = (visible_columns - 1) * block.lateral_pitch
            for column in range(visible_columns):
                y = mid_y - row_width / 2.0 + column * block.lateral_pitch
                positions.append(Vec2(x, y))
        edge += outward * (block.depth + config.formation_block_gap)
        row_count += block.rows
    return positions, {side: row_count}
