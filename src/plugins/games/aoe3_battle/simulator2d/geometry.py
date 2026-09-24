"""Collision geometry helpers for the 2D battle simulator."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import pairwise

from ....aoe3.models import Unit

_EPSILON = 1e-9
_CONTACT_SAMPLES = 64


@lru_cache(maxsize=4096)
def _ellipse_matrix(rx: float, ry: float, angle: float) -> tuple[float, float, float]:
    c, s = math.cos(angle), math.sin(angle)
    return (
        rx * rx * c * c + ry * ry * s * s,
        (rx * rx - ry * ry) * c * s,
        rx * rx * s * s + ry * ry * c * c,
    )


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

    def support(self, nx: float, ny: float) -> tuple[float, float]:
        """Boundary point relative to the center with this outward normal."""
        c, s = math.cos(self.angle), math.sin(self.angle)
        lx, ly = c * nx + s * ny, -s * nx + c * ny
        length = math.hypot(self.radius_x * lx, self.radius_z * ly)
        if length <= _EPSILON:
            return 0.0, 0.0
        x, y = self.radius_x**2 * lx / length, self.radius_z**2 * ly / length
        return c * x - s * y, s * x + c * y


def clamp_position(shape: CollisionShape, width: float, height: float) -> tuple[float, float]:
    rx, ry = shape.extent(1, 0), shape.extent(0, 1)
    return min(max(shape.x, rx), width - rx), min(max(shape.y, ry), height - ry)


def inside_field(
    shape: CollisionShape, width: float, height: float, tolerance: float = 0.0
) -> bool:
    rx, ry = shape.extent(1, 0), shape.extent(0, 1)
    return (
        rx - tolerance <= shape.x <= width - rx + tolerance
        and ry - tolerance <= shape.y <= height - ry + tolerance
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
    return swept_contact(first, second, 0.0, 0.0, tolerance=tolerance)


@lru_cache(maxsize=8192)
def swept_contact(
    first: CollisionShape,
    second: CollisionShape,
    move_x: float,
    move_y: float,
    *,
    tolerance: float = 0.0,
    padding: float = 0.0,
) -> ShapeContact | None:
    """Contact with the complete translated ellipse, not sampled endpoints.

    The swept volume is convex. Projecting its center segment and the two
    ellipse support functions uses the same separation test as static contact.
    Circular pairs use the exact capsule-distance fast path.
    """
    delta_x = second.x - first.x
    delta_y = second.y - first.y
    length_sq = move_x * move_x + move_y * move_y
    fraction = (
        max(0.0, min(1.0, (delta_x * move_x + delta_y * move_y) / length_sq))
        if length_sq > _EPSILON**2
        else 0.0
    )
    near_x, near_y = delta_x - fraction * move_x, delta_y - fraction * move_y
    center_distance = math.hypot(near_x, near_y)
    if center_distance >= first.bounding_radius + second.bounding_radius + padding:
        return None

    if first.is_circular and second.is_circular:
        minimum_distance = first.radius_x + second.radius_x + padding
        depth = minimum_distance - center_distance
        if depth <= tolerance:
            return None
        if center_distance <= _EPSILON:
            return ShapeContact(depth=depth, normal_x=1.0, normal_y=0.0)
        return ShapeContact(
            depth=depth,
            normal_x=near_x / center_distance,
            normal_y=near_y / center_distance,
        )

    initial_angle = math.atan2(delta_y, delta_x)
    sample_count = _CONTACT_SAMPLES
    best_angle = initial_angle
    qxx, qxy, qyy = _ellipse_matrix(first.radius_x, first.radius_z, first.angle)
    rxx, rxy, ryy = _ellipse_matrix(second.radius_x, second.radius_z, second.angle)

    def separation_at(angle: float) -> float:
        nx, ny = math.cos(angle), math.sin(angle)
        start = delta_x * nx + delta_y * ny
        end = start - move_x * nx - move_y * ny
        distance = 0.0 if start * end <= 0 else min(abs(start), abs(end))
        xx, xy, yy = nx * nx, 2 * nx * ny, ny * ny
        return (
            distance
            - math.sqrt(max(0.0, qxx * xx + qxy * xy + qyy * yy))
            - math.sqrt(max(0.0, rxx * xx + rxy * xy + ryy * yy))
            - padding
        )

    best_separation = separation_at(best_angle)
    if best_separation >= -tolerance - _EPSILON:
        return None
    # Cheap separating axes cover most non-contact pairs, particularly long
    # units alongside a wall. Only overlapping/near-tangent pairs need search.
    for angle in (
        first.angle,
        first.angle + math.pi / 2,
        second.angle,
        second.angle + math.pi / 2,
        math.atan2(move_y, move_x) + math.pi / 2,
    ):
        separation = separation_at(angle)
        if separation >= -tolerance - _EPSILON:
            return None
        if separation > best_separation:
            best_angle, best_separation = angle, separation
    step = math.tau / sample_count
    # Any separating axis disproves overlap. For intersecting shapes the
    # largest (least negative) separation gives the minimum translation.
    for offset in range(1, sample_count // 2 + 1):
        angle = initial_angle + offset * step
        separation = separation_at(angle)
        if separation >= -tolerance - _EPSILON:
            return None
        if separation > best_separation:
            best_separation = separation
            best_angle = angle
        angle = initial_angle - offset * step
        separation = separation_at(angle)
        if separation >= -tolerance - _EPSILON:
            return None
        if separation > best_separation:
            best_separation = separation
            best_angle = angle

    # Include the nonsmooth projection breakpoint of the swept center segment.
    if length_sq > _EPSILON**2:
        angle = math.atan2(move_y, move_x) + math.pi / 2
        separation = separation_at(angle)
        if separation > best_separation:
            best_angle, best_separation = angle, separation
    lower = best_angle - step
    upper = best_angle + step
    for _ in range(24):
        left = lower + (upper - lower) * 0.382
        right = lower + (upper - lower) * 0.618
        left_separation = separation_at(left)
        right_separation = separation_at(right)
        if left_separation >= right_separation:
            upper = right
        else:
            lower = left
    refined_angle = (lower + upper) / 2.0
    refined_separation = separation_at(refined_angle)
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


def translation_clear(
    first: CollisionShape,
    second: CollisionShape,
    dx: float,
    dy: float,
    *,
    tolerance: float = 0.0,
    padding: float = 0.0,
) -> bool:
    if first.is_circular and second.is_circular:
        px, py = second.x - first.x, second.y - first.y
        initial_distance = math.hypot(px, py)
        radius = first.radius_x + second.radius_x + padding
        length_sq = dx * dx + dy * dy
        dot = px * dx + py * dy
        t = max(0.0, min(1.0, dot / length_sq)) if length_sq > 1e-18 else 0.0
        nearest = math.hypot(px - t * dx, py - t * dy)
        if radius - nearest <= tolerance:
            return True
        return (
            initial_distance < radius
            and dot <= 0.0
            and math.hypot(px - dx, py - dy) > initial_distance + _EPSILON
        )
    contact = swept_contact(first, second, dx, dy, tolerance=tolerance, padding=padding)
    if contact is None:
        return True
    initial = swept_contact(first, second, 0, 0, padding=padding)
    if initial is None or contact.depth > initial.depth + _EPSILON:
        return False
    # Existing overlap may escape but cannot be deepened or crossed through.
    final = swept_contact(
        replace(first, x=first.x + dx, y=first.y + dy), second, 0, 0, padding=padding
    )
    return final is None or final.depth < initial.depth - _EPSILON


def rotation_clear(
    shape: CollisionShape,
    angle: float,
    obstacles: Iterable[CollisionShape],
    *,
    field: tuple[float, float] | None = None,
    tolerance: float = 0.0,
    padding: float = 0.0,
) -> bool:
    """Bound rotation intervals conservatively, subdividing only near contact."""
    delta = (angle - shape.angle + math.pi) % math.tau - math.pi
    if shape.is_circular or abs(delta) <= _EPSILON:
        return True
    nearby = [
        other
        for other in obstacles
        if math.hypot(shape.x - other.x, shape.y - other.y)
        < shape.bounding_radius + other.bounding_radius + padding
    ]

    def clear_interval(start: float, end: float, depth: int) -> bool:
        mid = replace(shape, angle=(start + end) * 0.5)
        # The ellipse support function changes by at most |a-b| per radian.
        bound = abs(shape.radius_x - shape.radius_z) * abs(end - start) * 0.5
        if field is not None:
            if not inside_field(mid, *field, tolerance):
                return False
            field_clear = inside_field(mid, *field, tolerance - bound)
        else:
            field_clear = True
        uncertain = not field_clear
        for other in nearby:
            if swept_contact(mid, other, 0, 0, tolerance=tolerance, padding=padding) is not None:
                return False
            if (
                swept_contact(mid, other, 0, 0, tolerance=tolerance, padding=padding + bound)
                is not None
            ):
                uncertain = True
        if not uncertain:
            return True
        if depth >= 12:
            return False
        middle = (start + end) * 0.5
        return clear_interval(start, middle, depth + 1) and clear_interval(middle, end, depth + 1)

    return clear_interval(shape.angle, shape.angle + delta, 0)


def motion_clear(
    shape: CollisionShape,
    end_x: float,
    end_y: float,
    angle: float,
    obstacles: Iterable[CollisionShape],
    *,
    field: tuple[float, float] | None = None,
    tolerance: float = 0.0,
    padding: float = 0.0,
) -> bool:
    """Validate simultaneous linear translation and shortest-arc rotation."""
    delta = (angle - shape.angle + math.pi) % math.tau - math.pi
    if shape.is_circular or abs(delta) <= _EPSILON:
        if field is not None:
            if not inside_field(shape, *field, tolerance) or not inside_field(
                replace(shape, x=end_x, y=end_y), *field, tolerance
            ):
                return False
        return all(
            translation_clear(
                shape, other, end_x - shape.x, end_y - shape.y, tolerance=tolerance, padding=padding
            )
            for other in obstacles
        )
    dx, dy = end_x - shape.x, end_y - shape.y
    length_sq = dx * dx + dy * dy
    nearby = []
    for other in obstacles:
        px, py = other.x - shape.x, other.y - shape.y
        fraction = max(0.0, min(1.0, (px * dx + py * dy) / length_sq)) if length_sq > 1e-18 else 0.0
        bound = shape.bounding_radius + other.bounding_radius + padding
        if (px - fraction * dx) ** 2 + (py - fraction * dy) ** 2 < bound * bound:
            nearby.append(other)
    obstacles = tuple(nearby)
    if field is not None:
        r = shape.bounding_radius - tolerance
        if all(
            r <= x <= field[0] - r and r <= y <= field[1] - r
            for x, y in ((shape.x, shape.y), (end_x, end_y))
        ):
            field = None
    if not obstacles and field is None:
        return True
    end = replace(shape, x=end_x, y=end_y, angle=shape.angle + delta)

    def clear_interval(start: CollisionShape, finish: CollisionShape, depth: int) -> bool:
        mid = replace(
            start,
            x=(start.x + finish.x) * 0.5,
            y=(start.y + finish.y) * 0.5,
            angle=(start.angle + finish.angle) * 0.5,
        )
        angular_bound = abs(shape.radius_x - shape.radius_z) * abs(finish.angle - start.angle) * 0.5
        if field is not None and not all(
            inside_field(p, *field, tolerance) for p in (start, mid, finish)
        ):
            return False
        uncertain = field is not None and not all(
            inside_field(replace(p, angle=mid.angle), *field, tolerance - angular_bound)
            for p in (start, finish)
        )
        for other in obstacles:
            if swept_contact(mid, other, 0, 0, tolerance=tolerance, padding=padding) is not None:
                return False
            # The fixed-mid-angle swept ellipse plus this angular bound
            # contains every intermediate pose; endpoints alone are not enough.
            if (
                swept_contact(
                    replace(start, angle=mid.angle),
                    other,
                    finish.x - start.x,
                    finish.y - start.y,
                    tolerance=tolerance,
                    padding=padding + angular_bound,
                )
                is not None
            ):
                uncertain = True
        if not uncertain:
            return True
        if depth >= 12:
            return False
        return clear_interval(start, mid, depth + 1) and clear_interval(mid, finish, depth + 1)

    return clear_interval(shape, end, 0)


def angle_delta(start: float, end: float) -> float:
    return (end - start + math.pi) % math.tau - math.pi


@dataclass(frozen=True)
class PoseMotion:
    """One movement command shared by prediction, path validation and execution."""

    start: CollisionShape
    dx: float
    dy: float
    turn: float
    turn_fraction: float = 1.0

    def at(self, fraction: float) -> CollisionShape:
        progress = min(1.0, fraction / max(self.turn_fraction, _EPSILON))
        return replace(
            self.start,
            x=self.start.x + self.dx * fraction,
            y=self.start.y + self.dy * fraction,
            angle=self.start.angle + self.turn * progress,
        )

    def clear(
        self,
        obstacles: Iterable[CollisionShape],
        *,
        field=None,
        tolerance=0.0,
        padding=0.0,
        start=0.0,
        end=1.0,
    ) -> bool:
        obstacles = tuple(obstacles)
        cuts = [start, end]
        if start < self.turn_fraction < end:
            cuts.insert(1, self.turn_fraction)
        for left, right in pairwise(cuts):
            a, b = self.at(left), self.at(right)
            if not motion_clear(
                a, b.x, b.y, b.angle, obstacles, field=field, tolerance=tolerance, padding=padding
            ):
                return False
        return True


def steering_motion(
    shape: CollisionShape, dx: float, dy: float, heading: float, duration: float, turn_rate: float
) -> PoseMotion:
    delta = angle_delta(shape.angle, heading)
    if shape.is_circular:
        return PoseMotion(shape, dx, dy, delta)
    limit = max(0.0, turn_rate * duration)
    turn = max(-limit, min(limit, delta))
    fraction = min(1.0, abs(delta) / limit) if limit > _EPSILON else 1.0
    return PoseMotion(shape, dx, dy, turn, fraction)


def translation_collision_time(
    first: CollisionShape,
    second: CollisionShape,
    vx: float,
    vy: float,
    horizon: float,
) -> float | None:
    """First contact for relative translation with fixed orientations."""
    if first.is_circular and second.is_circular:
        px, py = second.x - first.x, second.y - first.y
        radius = first.radius_x + second.radius_x
        a, b = vx * vx + vy * vy, px * vx + py * vy
        if px * px + py * py <= radius * radius:
            return 0.0 if b > 1e-9 or a <= 1e-12 else None
        if a <= 1e-12 or b <= 0:
            return None
        disc = b * b - a * (px * px + py * py - radius * radius)
        if disc < 0:
            return None
        hit = max(0.0, (b - math.sqrt(disc)) / a)
        return hit if hit <= horizon else None
    if translation_clear(first, second, vx * horizon, vy * horizon):
        return None
    # After the common swept test confirms collision, projected time windows
    # provide a conservative entry time for steering scores. Execution still
    # uses the full swept test; no point samples or circles decide feasibility.
    entry, exit_ = 0.0, horizon
    for angle in (first.angle + i * math.pi / 32 for i in range(32)):
        nx, ny = math.cos(angle), math.sin(angle)
        p = (second.x - first.x) * nx + (second.y - first.y) * ny
        v = vx * nx + vy * ny
        r = first.extent(nx, ny) + second.extent(nx, ny)
        if abs(v) <= 1e-12:
            if abs(p) > r:
                return None
            continue
        a, b = (p - r) / v, (p + r) / v
        entry, exit_ = max(entry, min(a, b)), min(exit_, max(a, b))
        if entry > exit_:
            return None
    return entry
