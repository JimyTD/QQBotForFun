"""Initial 2D formation placement."""

from __future__ import annotations

from dataclasses import dataclass

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


def _ordered_units(army: list[ArmySlot]) -> list:
    units = []
    for slot in sorted(
        army,
        key=lambda item: (item.unit.range, -item.unit.speed, item.unit.id),
    ):
        units.extend([slot.unit] * slot.count)
    return units


def _formation_shape(
    total: int,
    config: Simulation2DConfig,
) -> tuple[int, int]:
    if total <= 0:
        return 0, 0
    columns = config.columns_for(total)
    rows = (total + columns - 1) // columns
    return columns, rows


def build_deployment(
    red_army: list[ArmySlot],
    blue_army: list[ArmySlot],
    config: Simulation2DConfig,
) -> Deployment:
    """Place both armies facing each other on a shared battlefield."""
    red_units = _ordered_units(red_army)
    blue_units = _ordered_units(blue_army)

    red_columns, red_rows = _formation_shape(len(red_units), config)
    blue_columns, blue_rows = _formation_shape(len(blue_units), config)
    max_columns = max(red_columns, blue_columns, 1)
    max_lateral_diameter = max(
        (
            directional_extent(unit, 0.0, 0.0, 1.0, config.fallback_unit_radius) * 2.0
            for unit in red_units + blue_units
        ),
        default=0.0,
    )
    lateral_spacing = max(
        config.formation_spacing,
        max_lateral_diameter + config.separation_slop * 2.0,
    )
    lateral_span = (max_columns - 1) * lateral_spacing
    field_height = max(
        config.field_length,
        lateral_span + config.formation_side_margin * 2,
    )
    row_spacing = max(
        config.row_spacing,
        max(
            (
                directional_extent(unit, 0.0, 1.0, 0.0, config.fallback_unit_radius) * 2.0
                for unit in red_units + blue_units
            ),
            default=0.0,
        )
        + config.separation_slop * 2.0,
    )
    red_depth_span = (red_rows - 1) * row_spacing
    blue_depth_span = (blue_rows - 1) * row_spacing
    field_width = (
        config.formation_depth_margin * 2 + config.field_length + red_depth_span + blue_depth_span
    )
    mid_y = field_height / 2.0
    red_front_x = config.formation_depth_margin + red_depth_span
    blue_front_x = red_front_x + config.field_length

    positions: list[Vec2] = []
    positions.extend(
        _place_side(
            red_units,
            columns=red_columns,
            front_x=red_front_x,
            mid_y=mid_y,
            direction=-1.0,
            spacing=lateral_spacing,
            row_spacing=row_spacing,
            config=config,
        )
    )
    positions.extend(
        _place_side(
            blue_units,
            columns=blue_columns,
            front_x=blue_front_x,
            mid_y=mid_y,
            direction=1.0,
            spacing=lateral_spacing,
            row_spacing=row_spacing,
            config=config,
        )
    )

    return Deployment(
        positions=positions,
        field_width=field_width,
        field_height=field_height,
        columns={Side.RED: red_columns, Side.BLUE: blue_columns},
        rows={Side.RED: red_rows, Side.BLUE: blue_rows},
    )


def _place_side(
    units: list,
    *,
    columns: int,
    front_x: float,
    mid_y: float,
    direction: float,
    spacing: float,
    row_spacing: float,
    config: Simulation2DConfig,
) -> list[Vec2]:
    positions: list[Vec2] = []
    if not units:
        return positions

    for index, _unit in enumerate(units):
        row = index // columns
        column = index % columns
        visible_columns = min(columns, len(units) - row * columns)
        row_width = (visible_columns - 1) * spacing
        y = mid_y - row_width / 2.0 + column * spacing
        x = front_x + direction * row * row_spacing
        positions.append(Vec2(x, y))
    return positions
