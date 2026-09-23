"""Collision geometry helpers for the 2D battle simulator."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ....aoe3.models import Unit

_EPSILON = 1e-9
_CONTACT_SAMPLES = 64


def _unit_axes(unit: Unit, fallback: float) -> tuple[float, float]:
    """Return physical obstruction radii as ``(lateral, longitudinal)``."""
    radius_x = unit.obstruction_radius_x
    radius_z = unit.obstruction_radius_z
    if radius_x > 0 and radius_z > 0:
        return radius_x, radius_z
    radius = unit.collision_radius or fallback
    radius = max(radius, _EPSILON)
    return radius, radius


def unit_radius(unit: Unit, fallback: float) -> float:
    """Return a unit's equivalent circular radius or the configured fallback."""
    return unit.collision_radius or fallback


def unit_bounding_radius(unit: Unit, fallback: float) -> float:
    """Return the radius of a circle that contains the unit's real footprint."""
    return max(_unit_axes(unit, fallback))


def combined_radius(first: Unit, second: Unit, fallback: float) -> float:
    """Return the equivalent-circular non-overlap distance."""
    return unit_radius(first, fallback) + unit_radius(second, fallback)


@dataclass(frozen=True)
class CollisionShape:
    """An oriented ellipse in local ``(x=lateral, z=longitudinal)`` axes."""

    x: float
    y: float
    radius_x: float
    radius_z: float
    angle: float

    @property
    def bounding_radius(self) -> float:
        return max(self.radius_x, self.radius_z)

    @property
    def is_circular(self) -> bool:
        return abs(self.radius_x - self.radius_z) <= 1e-6

    def _local_direction(self, nx: float, ny: float) -> tuple[float, float]:
        c = math.cos(self.angle)
        s = math.sin(self.angle)
        return c * nx + s * ny, -s * nx + c * ny

    def extent(self, nx: float, ny: float) -> float:
        """Return the support distance from the center along ``(nx, ny)``."""
        length = math.hypot(nx, ny)
        if length <= _EPSILON:
            return self.bounding_radius
        nx /= length
        ny /= length
        local_forward, local_side = self._local_direction(nx, ny)
        return math.hypot(
            self.radius_x * local_forward,
            self.radius_z * local_side,
        )


def shape_for_unit(
    unit: Unit,
    x: float,
    y: float,
    angle: float,
    fallback: float,
) -> CollisionShape:
    """Build an oriented collision shape from real unit obstruction data."""
    radius_x, radius_z = _unit_axes(unit, fallback)
    return CollisionShape(
        x=x,
        y=y,
        radius_x=radius_x,
        radius_z=radius_z,
        angle=angle,
    )


def directional_extent(
    unit: Unit,
    angle: float,
    direction_x: float,
    direction_y: float,
    fallback: float,
) -> float:
    """Return the unit's footprint extent along a world direction."""
    return shape_for_unit(unit, 0.0, 0.0, angle, fallback).extent(
        direction_x,
        direction_y,
    )


def combined_directional_extent(
    first: Unit,
    first_angle: float,
    second: Unit,
    second_angle: float,
    direction_x: float,
    direction_y: float,
    fallback: float,
) -> float:
    """Return the directional non-overlap distance for two oriented units."""
    return directional_extent(
        first,
        first_angle,
        direction_x,
        direction_y,
        fallback,
    ) + directional_extent(
        second,
        second_angle,
        -direction_x,
        -direction_y,
        fallback,
    )


@dataclass(frozen=True)
class ShapeContact:
    """Minimum translation contact between two convex footprints."""

    depth: float
    normal_x: float
    normal_y: float


def _shape_separation(
    first: CollisionShape,
    second: CollisionShape,
    angle: float,
) -> float:
    nx = math.cos(angle)
    ny = math.sin(angle)
    center_projection = (
        (second.x - first.x) * nx
        + (second.y - first.y) * ny
    )
    return (
        abs(center_projection)
        - first.extent(nx, ny)
        - second.extent(-nx, -ny)
    )


def shape_contact(
    first: CollisionShape,
    second: CollisionShape,
    *,
    tolerance: float = 0.0,
) -> ShapeContact | None:
    """Return a separating contact for two oriented ellipses.

    Circles use the exact analytic path. Ellipses use a deterministic bounded
    angular search over the support function instead of a third-party
    dependency, which keeps the hot path predictable for this simulator.
    """
    delta_x = second.x - first.x
    delta_y = second.y - first.y
    center_distance = math.hypot(delta_x, delta_y)
    if center_distance > first.bounding_radius + second.bounding_radius + tolerance:
        return None

    if first.is_circular and second.is_circular:
        minimum_distance = first.radius_x + second.radius_x
        depth = minimum_distance - center_distance
        if depth <= tolerance:
            return None
        if center_distance <= _EPSILON:
            return ShapeContact(depth=depth, normal_x=1.0, normal_y=0.0)
        return ShapeContact(
            depth=depth,
            normal_x=delta_x / center_distance,
            normal_y=delta_y / center_distance,
        )

    initial_angle = math.atan2(delta_y, delta_x)
    sample_count = _CONTACT_SAMPLES
    best_angle = initial_angle
    best_separation = _shape_separation(first, second, best_angle)
    step = math.tau / sample_count
    # Any separating axis disproves overlap. For intersecting shapes the
    # largest (least negative) separation gives the minimum translation.
    for offset in range(1, sample_count // 2 + 1):
        angle = initial_angle + offset * step
        separation = _shape_separation(first, second, angle)
        if separation > best_separation:
            best_separation = separation
            best_angle = angle
        angle = initial_angle - offset * step
        separation = _shape_separation(first, second, angle)
        if separation > best_separation:
            best_separation = separation
            best_angle = angle

    lower = best_angle - step
    upper = best_angle + step
    for _ in range(24):
        left = lower + (upper - lower) * 0.382
        right = lower + (upper - lower) * 0.618
        left_separation = _shape_separation(first, second, left)
        right_separation = _shape_separation(first, second, right)
        if left_separation >= right_separation:
            upper = right
        else:
            lower = left
    refined_angle = (lower + upper) / 2.0
    refined_separation = _shape_separation(first, second, refined_angle)
    if refined_separation > best_separation:
        best_angle = refined_angle
        best_separation = refined_separation
    if best_separation >= -tolerance - _EPSILON:
        return None
    nx, ny = math.cos(best_angle), math.sin(best_angle)
    # Projection uses an absolute value; orient the response from first to
    # second so the positional resolver pushes bodies apart, not together.
    if nx * delta_x + ny * delta_y < 0.0:
        nx, ny = -nx, -ny
    return ShapeContact(
        depth=-best_separation,
        normal_x=nx,
        normal_y=ny,
    )
