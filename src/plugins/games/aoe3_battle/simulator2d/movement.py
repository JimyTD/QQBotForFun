"""Local collision avoidance and overlap resolution for the 2D engine."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from .config import Simulation2DConfig
from .geometry import (
    CollisionShape,
    PoseMotion,
    clamp_position,
    repose,
    shape_contact,
    shape_for_unit,
    steering_motion,
    translation_collision_time,
    unit_bounding_radius,
)
from .model import Soldier2D, Vec2
from .perf import perf_enabled, perf_inc, perf_max
from .spatial import SpatialHash

logger = logging.getLogger("aoe3_battle.simulator2d.movement")


def _pose_collision_time(
    motion: PoseMotion,
    duration: float,
    velocity: Vec2,
    other: CollisionShape,
    other_velocity: Vec2,
    horizon: float,
    stop_time: float | None,
    tolerance: float,
) -> float | None:
    """Predict the chosen command, then conservatively hold its ending heading."""
    relative = PoseMotion(
        motion.start,
        motion.dx - other_velocity.x * duration,
        motion.dy - other_velocity.y * duration,
        motion.turn,
        motion.turn_fraction,
    )
    if other_velocity.length_sq() > 1e-12 and not relative.clear([other], tolerance=tolerance):
        return 0.0
    own = motion.at(1)
    other = repose(
        other, x=other.x + other_velocity.x * duration, y=other.y + other_velocity.y * duration
    )
    moving = max(0.0, (horizon if stop_time is None else min(horizon, stop_time)) - duration)
    ttc = translation_collision_time(
        own, other, velocity.x - other_velocity.x, velocity.y - other_velocity.y, moving
    )
    if ttc is not None:
        return duration + ttc
    remaining = horizon - duration - moving
    if remaining <= 1e-9:
        return None
    own = repose(own, x=own.x + velocity.x * moving, y=own.y + velocity.y * moving)
    other = repose(
        other, x=other.x + other_velocity.x * moving, y=other.y + other_velocity.y * moving
    )
    ttc = translation_collision_time(own, other, -other_velocity.x, -other_velocity.y, remaining)
    return duration + moving + ttc if ttc is not None else None


@dataclass(frozen=True)
class SteeringResult:
    velocity: Vec2
    reason: str
    blocked_by: tuple[int, ...] = ()
    blocked_ticks: int = 0
    time_to_collision: float | None = None
    candidate_angle: float = 0.0
    wall_contact: bool = False
    facing: float | None = None
    turn_fraction: float = 1.0


def _time_to_collision(
    soldier: Soldier2D,
    velocity: Vec2,
    neighbor: Soldier2D,
    *,
    fallback_radius: float,
    horizon: float,
    stop_time: float | None = None,
    heading: float | None = None,
    turn_rate: float = math.tau,
    tolerance: float = 0.0,
) -> float | None:
    neighbor_velocity = Vec2(0.0, 0.0) if neighbor.stopped else neighbor.velocity
    relative_velocity = velocity - neighbor_velocity
    own_shape = shape_for_unit(soldier.unit, soldier.x, soldier.y, soldier.facing, fallback_radius)
    other_shape = shape_for_unit(
        neighbor.unit, neighbor.x, neighbor.y, neighbor.facing, fallback_radius
    )
    moving_horizon = horizon if stop_time is None else min(horizon, max(0.0, stop_time))
    if not own_shape.is_circular:
        angle = (
            heading
            if heading is not None
            else (
                math.atan2(velocity.y, velocity.x)
                if velocity.length_sq() > 1e-12
                else soldier.facing
            )
        )
        motion = steering_motion(
            own_shape,
            relative_velocity.x * moving_horizon,
            relative_velocity.y * moving_horizon,
            angle,
            moving_horizon,
            turn_rate,
        )
        collision = None
        if abs(motion.turn) < 1e-9:
            collision = translation_collision_time(
                own_shape, other_shape, relative_velocity.x, relative_velocity.y, moving_horizon
            )
        elif not motion.clear([other_shape], tolerance=tolerance):
            low, high = 0.0, 1.0
            for _ in range(6):
                mid = (low + high) * 0.5
                if motion.clear([other_shape], end=mid, tolerance=tolerance):
                    low = mid
                else:
                    high = mid
            collision = low * moving_horizon
        own_shape = repose(own_shape, angle=motion.at(1).angle)
    else:
        collision = translation_collision_time(
            own_shape, other_shape, relative_velocity.x, relative_velocity.y, moving_horizon
        )
    if collision is not None or moving_horizon >= horizon:
        return collision

    # Arrival does not erase other moving bodies: predict the stationary
    # remainder too, rather than discarding all collisions after arrival.
    own_shape = repose(
        own_shape,
        x=own_shape.x + velocity.x * moving_horizon,
        y=own_shape.y + velocity.y * moving_horizon,
    )
    other_shape = repose(
        other_shape,
        x=other_shape.x + neighbor_velocity.x * moving_horizon,
        y=other_shape.y + neighbor_velocity.y * moving_horizon,
    )
    collision = translation_collision_time(
        own_shape, other_shape, -neighbor_velocity.x, -neighbor_velocity.y, horizon - moving_horizon
    )
    return moving_horizon + collision if collision is not None else None


def _circle_entry_time(
    relative_position: Vec2,
    relative_velocity: Vec2,
    minimum_distance: float,
    horizon: float,
) -> float | None:
    if relative_position.length_sq() <= minimum_distance * minimum_distance:
        # An outward or tangential step may escape existing overlap.
        returning_to_contact = (
            relative_position.dot(relative_velocity) > 1e-9
            or relative_velocity.length_sq() <= 1e-12
        )
        return 0.0 if returning_to_contact else None

    c = relative_position.dot(relative_position) - minimum_distance * minimum_distance
    a = relative_velocity.dot(relative_velocity)
    if a <= 1e-12:
        return None
    b = -relative_position.dot(relative_velocity)
    if b >= 0.0:
        return None

    discriminant = b * b - a * c
    if discriminant < 0.0:
        return None
    root = math.sqrt(discriminant)
    collision_time = (-b - root) / a
    if 0.0 <= collision_time <= horizon:
        return collision_time
    return None


def _arrival_time(
    position: Vec2,
    velocity: Vec2,
    arrival_zone: tuple[Vec2, float] | None,
) -> float | None:
    if arrival_zone is None:
        return None
    center, radius = arrival_zone
    offset = center - position
    if offset.length_sq() <= radius * radius:
        return 0.0
    return _circle_entry_time(offset, velocity, radius, math.inf)


_ORCA_EPSILON = 1e-5


@dataclass(frozen=True)
class _HalfPlane:
    """A velocity constraint. The allowed side is to the left of ``direction``."""

    point: Vec2
    direction: Vec2


def _det(first: Vec2, second: Vec2) -> float:
    return first.x * second.y - first.y * second.x


def _unit_or_x(vector: Vec2) -> Vec2:
    length = vector.length()
    if length <= _ORCA_EPSILON:
        return Vec2(1.0, 0.0)
    return vector / length


def _orca_half_plane(
    position: Vec2,
    velocity: Vec2,
    radius: float,
    other_position: Vec2,
    other_velocity: Vec2,
    other_radius: float,
    inv_time: float,
    responsibility: float,
) -> _HalfPlane | None:
    """One ORCA line. ``responsibility`` is 0.5 when the neighbor also avoids."""
    relative_position = other_position - position
    relative_velocity = velocity - other_velocity
    dist_sq = relative_position.length_sq()
    combined_radius = radius + other_radius
    combined_radius_sq = combined_radius * combined_radius
    if combined_radius <= _ORCA_EPSILON and dist_sq > combined_radius_sq:
        return None

    if dist_sq > combined_radius_sq:
        w = relative_velocity - relative_position * inv_time
        w_length_sq = w.length_sq()
        dot_product = w.dot(relative_position)
        if dot_product < 0.0 and dot_product * dot_product > combined_radius_sq * w_length_sq:
            unit_w = _unit_or_x(w)
            direction = Vec2(unit_w.y, -unit_w.x)
            u = unit_w * (combined_radius * inv_time - math.sqrt(w_length_sq))
        else:
            leg = math.sqrt(max(0.0, dist_sq - combined_radius_sq))
            if _det(relative_position, w) > 0.0:
                direction = (
                    Vec2(
                        relative_position.x * leg - relative_position.y * combined_radius,
                        relative_position.x * combined_radius + relative_position.y * leg,
                    )
                    / dist_sq
                )
            else:
                direction = (
                    Vec2(
                        relative_position.x * leg + relative_position.y * combined_radius,
                        -relative_position.x * combined_radius + relative_position.y * leg,
                    )
                    / -dist_sq
                )
            u = direction * relative_velocity.dot(direction) - relative_velocity
    else:
        w = relative_velocity - relative_position * inv_time
        unit_w = _unit_or_x(w)
        direction = Vec2(unit_w.y, -unit_w.x)
        u = unit_w * (combined_radius * inv_time - w.length())
    if direction.length_sq() <= _ORCA_EPSILON:
        return None
    return _HalfPlane(velocity + u * responsibility, direction)


def _linear_program1(
    lines: list[_HalfPlane],
    line_no: int,
    radius: float,
    opt_velocity: Vec2,
    direction_opt: bool,
) -> Vec2 | None:
    """Project the optimum onto one half-plane, inside the max-speed disc."""
    line = lines[line_no]
    dot_product = line.point.dot(line.direction)
    discriminant = dot_product * dot_product + radius * radius - line.point.length_sq()
    if discriminant < 0.0:
        return None
    sqrt_discriminant = math.sqrt(discriminant)
    t_left = -dot_product - sqrt_discriminant
    t_right = -dot_product + sqrt_discriminant
    for index in range(line_no):
        earlier = lines[index]
        denominator = _det(line.direction, earlier.direction)
        numerator = _det(earlier.direction, line.point - earlier.point)
        if abs(denominator) <= _ORCA_EPSILON:
            if numerator < 0.0:
                return None
            continue
        t_value = numerator / denominator
        if denominator >= 0.0:
            t_right = min(t_right, t_value)
        else:
            t_left = max(t_left, t_value)
        if t_left > t_right:
            return None
    if direction_opt:
        if opt_velocity.dot(line.direction) > 0.0:
            t_value = t_right
        else:
            t_value = t_left
    else:
        t_value = line.direction.dot(opt_velocity - line.point)
        if t_value < t_left:
            t_value = t_left
        elif t_value > t_right:
            t_value = t_right
    return line.point + line.direction * t_value


def _linear_program2(
    lines: list[_HalfPlane],
    radius: float,
    opt_velocity: Vec2,
    direction_opt: bool,
) -> tuple[Vec2, int]:
    """Closest allowed velocity. The index is the first line that made it fail."""
    if direction_opt:
        result = opt_velocity * radius
    elif opt_velocity.length_sq() > radius * radius:
        result = opt_velocity.normalized() * radius
    else:
        result = opt_velocity
    for index, line in enumerate(lines):
        if _det(line.direction, line.point - result) > 0.0:
            projected = _linear_program1(lines, index, radius, opt_velocity, direction_opt)
            if projected is None:
                return result, index
            result = projected
    return result, len(lines)


def _field_half_planes(
    shape: CollisionShape,
    speed: float,
    horizon: float,
    field_width: float,
    field_height: float,
) -> list[_HalfPlane]:
    """Hard velocity limits using the shape's support, not its bounding circle."""
    if horizon <= 1e-6:
        return []
    planes: list[_HalfPlane] = []
    left = (shape.extent(-1.0, 0.0) - shape.x) / horizon
    right = (field_width - shape.extent(1.0, 0.0) - shape.x) / horizon
    bottom = (shape.extent(0.0, -1.0) - shape.y) / horizon
    top = (field_height - shape.extent(0.0, 1.0) - shape.y) / horizon
    if left > -speed:
        planes.append(_HalfPlane(Vec2(left, 0.0), Vec2(0.0, -1.0)))
    if right < speed:
        planes.append(_HalfPlane(Vec2(right, 0.0), Vec2(0.0, 1.0)))
    if bottom > -speed:
        planes.append(_HalfPlane(Vec2(0.0, bottom), Vec2(1.0, 0.0)))
    if top < speed:
        planes.append(_HalfPlane(Vec2(0.0, top), Vec2(-1.0, 0.0)))
    return planes


def _linear_program3(
    lines: list[_HalfPlane],
    radius: float,
    num_obst_lines: int,
    begin_line: int,
    result: Vec2,
) -> Vec2:
    """Least-violating velocity when the half-planes have no common point."""
    distance = 0.0
    for index in range(begin_line, len(lines)):
        line = lines[index]
        if _det(line.direction, line.point - result) <= distance:
            continue
        projected_lines = list(lines[:num_obst_lines])
        for earlier in lines[num_obst_lines:index]:
            determinant = _det(line.direction, earlier.direction)
            if abs(determinant) <= _ORCA_EPSILON:
                if line.direction.dot(earlier.direction) > 0.0:
                    continue
                point = (line.point + earlier.point) * 0.5
            else:
                point = line.point + line.direction * (
                    _det(earlier.direction, line.point - earlier.point) / determinant
                )
            direction = (earlier.direction - line.direction).normalized()
            if direction.length_sq() <= _ORCA_EPSILON:
                continue
            projected_lines.append(_HalfPlane(point, direction))
        temp = result
        solved, failed_at = _linear_program2(
            projected_lines,
            radius,
            Vec2(-line.direction.y, line.direction.x),
            True,
        )
        if failed_at < len(projected_lines):
            result = temp
        else:
            result = solved
        distance = _det(line.direction, line.point - result)
    return result


class LocalAvoidance:
    """Choose a collision-free velocity close to the desired velocity."""

    def __init__(
        self,
        config: Simulation2DConfig,
        spatial_hash: SpatialHash,
    ) -> None:
        self.config = config
        self.spatial_hash = spatial_hash

    def choose_velocity(
        self,
        soldier: Soldier2D,
        desired: Vec2,
        *,
        field_width: float,
        field_height: float,
        blocked_ticks: int,
        arrival_zone: tuple[Vec2, float] | None = None,
        participants: set[int] | None = None,
    ) -> SteeringResult:
        desired = desired.clamped_length(soldier.effective_speed)
        if desired.length_sq() <= 1e-12:
            if perf_enabled():
                perf_inc("steer.desired_zero")
            return SteeringResult(Vec2(0.0, 0.0), "desired_zero")

        other_speed = (
            self.config.max_known_speed
            if self.config.max_known_speed > 0.0
            else soldier.effective_speed
        )
        horizon = self.config.avoidance_horizon
        neighbors = self.spatial_hash.query_circle(
            soldier.pos,
            (soldier.effective_speed + other_speed) * horizon,
            predicate=lambda other: other.id != soldier.id and other.alive,
        )
        neighbors.sort(key=lambda other: (other.distance_sq_to(soldier), other.id))
        cap = self.config.orca_max_neighbors
        if perf_enabled():
            perf_inc("steer.calls")
            perf_inc("steer.neighbor_sum", min(len(neighbors), cap))
            perf_max("steer.neighbor_max", len(neighbors))
            if len(neighbors) > cap:
                perf_inc("steer.over_cap")
        neighbors = neighbors[:cap]

        lines: list[_HalfPlane] = []
        blocked_by: int | None = None
        worst_violation = 0.0
        inv_step = 1.0 / self.config.tick_interval
        own_shape = shape_for_unit(
            soldier.unit,
            soldier.x,
            soldier.y,
            soldier.facing,
            self.config.fallback_unit_radius,
        )
        own_radius = own_shape.bounding_radius
        preferred_motion = steering_motion(
            own_shape,
            desired.x * self.config.tick_interval,
            desired.y * self.config.tick_interval,
            math.atan2(desired.y, desired.x),
            self.config.tick_interval,
            self.config.movement_turn_rate,
        )
        stop_time = _arrival_time(soldier.pos, desired, arrival_zone)
        elliptical_shapes: list[CollisionShape] = []
        for other in neighbors:
            other_shape = shape_for_unit(
                other.unit,
                other.x,
                other.y,
                other.facing,
                self.config.fallback_unit_radius,
            )
            discs = own_shape.is_circular and other_shape.is_circular
            if not discs:
                elliptical_shapes.append(other_shape)
                if preferred_motion.clear((other_shape,), tolerance=self.config.separation_slop):
                    continue
            other_radius = other_shape.bounding_radius
            other_velocity = Vec2(0.0, 0.0) if other.stopped else other.velocity
            if discs:
                overlapping = soldier.distance_sq_to(other) <= (own_radius + other_radius) ** 2
            else:
                overlapping = shape_contact(own_shape, other_shape) is not None
            if participants is None:
                reciprocal = other.alive and not other.stopped and other.effective_speed > 1e-8
            else:
                reciprocal = other.id in participants
            inv_time = inv_step if overlapping else 1.0 / horizon
            if not overlapping and not reciprocal and stop_time is not None and stop_time > 1e-6:
                inv_time = 1.0 / min(horizon, stop_time)
            plane = _orca_half_plane(
                soldier.pos,
                soldier.velocity,
                own_radius,
                other.pos,
                other_velocity,
                other_radius,
                inv_time,
                0.5 if reciprocal else 1.0,
            )
            if plane is None:
                continue
            violation = _det(plane.direction, plane.point - desired)
            if violation > worst_violation:
                worst_violation = violation
                blocked_by = other.id
            lines.append(plane)

        bounds = _field_half_planes(
            own_shape,
            soldier.effective_speed,
            horizon,
            field_width,
            field_height,
        )
        lines = bounds + lines
        num_obst = len(bounds)
        max_speed = soldier.effective_speed
        velocity, failed_at = _linear_program2(lines, max_speed, desired, False)
        fallback = failed_at < len(lines)
        if fallback:
            velocity = _linear_program3(lines, max_speed, num_obst, failed_at, velocity)
        if (
            desired.length_sq() > 1e-12
            and velocity.length() < max_speed * 0.2
            and blocked_ticks >= self.config.blocked_window_ticks
        ):
            base = desired.normalized()
            options = [velocity] if velocity.length() >= max_speed * 0.2 else []
            for angle in (math.pi / 2, -math.pi / 2, math.pi):
                solved, failed = _linear_program2(
                    lines, max_speed, base.rotated(angle) * max_speed, False
                )
                if failed < len(lines):
                    solved = _linear_program3(lines, max_speed, num_obst, failed, solved)
                    fallback = True
                if solved.length() >= max_speed * 0.2:
                    options.append(solved)
            if options:
                velocity = max(options, key=lambda item: (item.dot(base), item.length_sq()))
        if elliptical_shapes:

            def sweep_clear(candidate: Vec2) -> bool:
                if candidate.length_sq() <= 1e-12:
                    return True
                solved = steering_motion(
                    own_shape,
                    candidate.x * self.config.tick_interval,
                    candidate.y * self.config.tick_interval,
                    math.atan2(candidate.y, candidate.x),
                    self.config.tick_interval,
                    self.config.movement_turn_rate,
                )
                return solved.clear(elliptical_shapes, tolerance=self.config.separation_slop)

            if not sweep_clear(velocity):
                velocity = Vec2(0.0, 0.0)
                for angle in (math.pi, 2.5, -2.5, math.pi / 2, -math.pi / 2):
                    direction = desired.rotated(angle).normalized()
                    for scale in (1.0, 0.65, 0.35):
                        candidate = direction * (max_speed * scale)
                        if sweep_clear(candidate):
                            velocity = candidate
                            break
                    if velocity.length_sq() > 1e-12:
                        break

        if perf_enabled():
            perf_inc("steer.tested", len(lines))
            if not fallback and (velocity - desired).length_sq() <= 1e-8:
                perf_inc("steer.early_free")

        if fallback:
            reason = "fallback"
        elif (velocity - desired).length_sq() <= 1e-8:
            reason = "free"
        else:
            reason = "avoid"
        if velocity.length_sq() <= 1e-12:
            return SteeringResult(
                Vec2(0.0, 0.0),
                reason,
                blocked_by=(blocked_by,) if blocked_by is not None else (),
                facing=soldier.facing,
            )
        heading = math.atan2(velocity.y, velocity.x)
        motion = steering_motion(
            shape_for_unit(
                soldier.unit,
                soldier.x,
                soldier.y,
                soldier.facing,
                self.config.fallback_unit_radius,
            ),
            velocity.x * self.config.tick_interval,
            velocity.y * self.config.tick_interval,
            heading,
            self.config.tick_interval,
            self.config.movement_turn_rate,
        )
        return SteeringResult(
            velocity,
            reason,
            blocked_by=(blocked_by,) if blocked_by is not None else (),
            facing=motion.at(1).angle,
            turn_fraction=motion.turn_fraction,
        )


@dataclass
class CollisionResolution:
    max_overlap: float
    corrections: int
    residual_pairs: int
    initial_max_overlap: float
    details: list[dict[str, Any]]


class CollisionResolver:
    """Positional overlap correction after velocity integration."""

    def __init__(
        self,
        config: Simulation2DConfig,
        spatial_hash: SpatialHash,
    ) -> None:
        self.config = config
        self.spatial_hash = spatial_hash

    def resolve(
        self,
        soldiers: list[Soldier2D],
        *,
        field_width: float,
        field_height: float,
    ) -> CollisionResolution:
        alive = [soldier for soldier in soldiers if soldier.alive]
        initial_max_overlap = 0.0
        total_pairs = 0
        details: list[dict[str, Any]] = []

        iterations = self.config.separation_iterations
        iterations_run = 0
        overlap_pairs = 0
        correction_budget: dict[int, float] = {}
        for iteration in range(iterations):
            iterations_run += 1
            self.spatial_hash.rebuild(alive)
            moved = False
            iteration_max = 0.0
            iteration_pairs = 0
            pairs = self._overlap_pairs(alive)
            overlap_pairs += len(pairs)
            pairs.sort(key=lambda item: item[0], reverse=True)
            if iteration == 0:
                initial_max_overlap = pairs[0][0] if pairs else 0.0
                for overlap, first, second, distance in pairs[:32]:
                    if overlap < self.config.max_overlap_for_log:
                        break
                    details.append(
                        {
                            "a": first.id,
                            "b": second.id,
                            "distance": round(distance, 4),
                            "overlap": round(overlap, 4),
                            "iteration": iteration,
                        }
                    )

            pair_limit = len(pairs)
            for overlap, first, second, _distance in pairs[:pair_limit]:
                if overlap <= self.config.separation_slop:
                    continue
                contact = shape_contact(
                    shape_for_unit(
                        first.unit,
                        first.x,
                        first.y,
                        first.facing,
                        self.config.fallback_unit_radius,
                    ),
                    shape_for_unit(
                        second.unit,
                        second.x,
                        second.y,
                        second.facing,
                        self.config.fallback_unit_radius,
                    ),
                )
                if contact is None:
                    continue
                nx = contact.normal_x
                ny = contact.normal_y
                overlap = contact.depth
                moved = True
                iteration_pairs += 1
                iteration_max = max(iteration_max, overlap)
                allowed = min(
                    self.config.max_position_correction_per_tick,
                    correction_budget.get(first.id, self.config.max_position_correction_per_tick),
                    correction_budget.get(second.id, self.config.max_position_correction_per_tick),
                )
                if allowed <= self.config.separation_slop:
                    continue
                applied = self._separate_pair(
                    first,
                    second,
                    nx,
                    ny,
                    overlap,
                    field_width=field_width,
                    field_height=field_height,
                    max_correction=allowed,
                )
                correction_budget[first.id] = (
                    correction_budget.get(
                        first.id,
                        self.config.max_position_correction_per_tick,
                    )
                    - applied
                )
                correction_budget[second.id] = (
                    correction_budget.get(
                        second.id,
                        self.config.max_position_correction_per_tick,
                    )
                    - applied
                )

            total_pairs += iteration_pairs
            if not moved or iteration_max <= self.config.separation_slop:
                break

        self.spatial_hash.rebuild(alive)
        residual_max, residual_pairs, residual_details = self._measure_residual(
            alive,
            field_width=field_width,
            field_height=field_height,
        )
        if residual_details:
            details.extend(residual_details)
        if perf_enabled():
            perf_inc("resolve.calls")
            perf_inc("resolve.iterations", iterations_run)
            perf_inc("resolve.overlap_pairs", overlap_pairs)
            perf_inc("resolve.corrections", total_pairs)
            perf_max("resolve.residual_pairs", residual_pairs)
        return CollisionResolution(
            max_overlap=residual_max,
            corrections=total_pairs,
            residual_pairs=residual_pairs,
            initial_max_overlap=initial_max_overlap,
            details=details[:32],
        )

    def _overlap_pairs(
        self,
        alive: list[Soldier2D],
    ) -> list[tuple[float, Soldier2D, Soldier2D, float]]:
        pairs: list[tuple[float, Soldier2D, Soldier2D, float]] = []
        for soldier in sorted(alive, key=lambda item: item.id):
            nearby = self.spatial_hash.query_circle(
                soldier.pos,
                self._pair_search_radius(soldier),
                predicate=lambda other, soldier_id=soldier.id: other.id > soldier_id,
            )
            for other in nearby:
                distance = soldier.distance_to(other)
                contact = shape_contact(
                    shape_for_unit(
                        soldier.unit,
                        soldier.x,
                        soldier.y,
                        soldier.facing,
                        self.config.fallback_unit_radius,
                    ),
                    shape_for_unit(
                        other.unit,
                        other.x,
                        other.y,
                        other.facing,
                        self.config.fallback_unit_radius,
                    ),
                )
                if contact is not None and contact.depth > self.config.separation_slop:
                    pairs.append((contact.depth, soldier, other, distance))
        return pairs

    def _measure_residual(
        self,
        alive: list[Soldier2D],
        *,
        field_width: float,
        field_height: float,
    ) -> tuple[float, int, list[dict[str, Any]]]:
        del field_width, field_height
        max_overlap = 0.0
        pair_count = 0
        details: list[dict[str, Any]] = []
        for soldier in sorted(alive, key=lambda item: item.id):
            nearby = self.spatial_hash.query_circle(
                soldier.pos,
                self._pair_search_radius(soldier),
                predicate=lambda other, soldier_id=soldier.id: other.id > soldier_id,
            )
            for other in nearby:
                distance = soldier.distance_to(other)
                contact = shape_contact(
                    shape_for_unit(
                        soldier.unit,
                        soldier.x,
                        soldier.y,
                        soldier.facing,
                        self.config.fallback_unit_radius,
                    ),
                    shape_for_unit(
                        other.unit,
                        other.x,
                        other.y,
                        other.facing,
                        self.config.fallback_unit_radius,
                    ),
                )
                if contact is None or contact.depth <= self.config.separation_slop:
                    continue
                overlap = contact.depth
                pair_count += 1
                max_overlap = max(max_overlap, overlap)
                if len(details) < 16:
                    details.append(
                        {
                            "a": soldier.id,
                            "b": other.id,
                            "distance": round(distance, 4),
                            "overlap": round(overlap, 4),
                            "residual": True,
                        }
                    )
        return max_overlap, pair_count, details

    def _pair_search_radius(self, soldier: Soldier2D) -> float:
        """Return a conservative collision-pair query radius for ``soldier``.

        The largest obstruction in the loaded unit data is currently under 10
        world units, so the previous global-radius search can no longer be
        expressed as twice one fixed radius.  A bounded scan over the loaded
        unit archetypes keeps this query conservative without making the hot
        path depend on the number of live soldiers.
        """
        unit = soldier.unit
        own_radius = unit_bounding_radius(unit, self.config.fallback_unit_radius)
        max_known_radius = self.config.max_known_unit_radius or own_radius
        return (own_radius + max_known_radius) * 1.05

    def _separate_pair(
        self,
        first: Soldier2D,
        second: Soldier2D,
        nx: float,
        ny: float,
        overlap: float,
        *,
        field_width: float,
        field_height: float,
        max_correction: float,
    ) -> float:
        if first.stopped and second.stopped:
            first_share, second_share = 0.5, 0.5
        elif first.stopped:
            first_share, second_share = 0.0, 1.0
        elif second.stopped:
            first_share, second_share = 1.0, 0.0
        else:
            first_share, second_share = 0.5, 0.5

        correction = min(
            overlap + self.config.separation_slop,
            max_correction,
        )
        first.x -= nx * correction * first_share
        first.y -= ny * correction * first_share
        second.x += nx * correction * second_share
        second.y += ny * correction * second_share

        for soldier in (first, second):
            shape = shape_for_unit(
                soldier.unit, soldier.x, soldier.y, soldier.facing, self.config.fallback_unit_radius
            )
            soldier.x, soldier.y = clamp_position(shape, field_width, field_height)
        return correction
