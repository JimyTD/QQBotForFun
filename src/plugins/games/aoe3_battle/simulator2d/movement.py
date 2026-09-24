"""Local collision avoidance and overlap resolution for the 2D engine."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import Any

from .config import CollisionMode, Simulation2DConfig
from .geometry import (
    CollisionShape,
    PoseMotion,
    angle_delta,
    clamp_position,
    shape_contact,
    shape_for_unit,
    steering_motion,
    translation_collision_time,
    unit_bounding_radius,
)
from .model import Soldier2D, Vec2
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
    other = replace(
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
    own = replace(own, x=own.x + velocity.x * moving, y=own.y + velocity.y * moving)
    other = replace(
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
        own_shape = replace(own_shape, angle=motion.at(1).angle)
    else:
        collision = translation_collision_time(
            own_shape, other_shape, relative_velocity.x, relative_velocity.y, moving_horizon
        )
    if collision is not None or moving_horizon >= horizon:
        return collision

    # Arrival does not erase other moving bodies: predict the stationary
    # remainder too, rather than discarding all collisions after arrival.
    own_shape = replace(
        own_shape,
        x=own_shape.x + velocity.x * moving_horizon,
        y=own_shape.y + velocity.y * moving_horizon,
    )
    other_shape = replace(
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


def _motion_score(
    preferred: Vec2,
    candidate: Vec2,
    *,
    detour_sign: int,
    previous: Vec2 = Vec2(0.0, 0.0),
) -> float:
    """Shape-independent preference for progress, speed and stable movement."""
    preferred_dir = preferred.normalized()
    candidate_dir = candidate.normalized()
    forward_penalty = 1.0 - max(-1.0, min(1.0, preferred_dir.dot(candidate_dir)))
    speed_penalty = max(0.0, preferred.length() - candidate.length()) * 0.8
    cross = preferred_dir.x * candidate_dir.y - preferred_dir.y * candidate_dir.x
    side_penalty = 0.005 if cross * detour_sign < 0 else 0.0
    turn_penalty = 0.0
    if previous.length() > 0.1 and candidate.length() > 0.1:
        alignment = previous.normalized().dot(candidate_dir)
        turn_penalty = max(0.0, -alignment) * 6.0
    return forward_penalty * 4.0 + speed_penalty + side_penalty + turn_penalty


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
    ) -> SteeringResult:
        desired = desired.clamped_length(soldier.effective_speed)
        if desired.length_sq() <= 1e-12:
            return SteeringResult(Vec2(0.0, 0.0), "desired_zero")

        neighbors = self.spatial_hash.query_circle(
            soldier.pos,
            max(
                self.config.avoidance_radius,
                unit_bounding_radius(soldier.unit, self.config.fallback_unit_radius)
                + self.config.max_known_unit_radius
                + soldier.effective_speed * self.config.tick_interval,
            ),
            predicate=lambda other: other.id != soldier.id,
        )
        neighbors.sort(
            key=lambda item: (
                item.distance_sq_to(soldier)
                - max(
                    0.0,
                    item.velocity.dot(Vec2(item.x - soldier.x, item.y - soldier.y).normalized()),
                ),
                item.id,
            )
        )
        # The nearest bodies are never hidden behind the steering neighbor cap.
        local_radius = (
            unit_bounding_radius(soldier.unit, self.config.fallback_unit_radius)
            + self.config.max_known_unit_radius
            + soldier.effective_speed * self.config.tick_interval
        )
        neighbors = [
            other
            for index, other in enumerate(neighbors)
            if index < self.config.max_neighbors or other.distance_sq_to(soldier) <= local_radius**2
        ]

        shape = shape_for_unit(
            soldier.unit, soldier.x, soldier.y, soldier.facing, self.config.fallback_unit_radius
        )
        return self._choose_pose_velocity(
            soldier,
            shape,
            desired,
            neighbors,
            field_width,
            field_height,
            blocked_ticks,
            arrival_zone,
        )

    def _choose_pose_velocity(
        self,
        soldier: Soldier2D,
        shape: CollisionShape,
        desired: Vec2,
        neighbors: list[Soldier2D],
        field_width: float,
        field_height: float,
        blocked_ticks: int,
        arrival_zone: tuple[Vec2, float] | None,
    ) -> SteeringResult:
        """Choose translation and turning together; do not force a pivot first."""
        dt = self.config.tick_interval
        field = (field_width, field_height)
        obstacles = [
            shape_for_unit(
                other.unit, other.x, other.y, other.facing, self.config.fallback_unit_radius
            )
            for other in neighbors
        ]
        desired_heading = math.atan2(desired.y, desired.x)
        best = None
        best_moving = None
        recovering = blocked_ticks >= self.config.blocked_window_ticks
        angles = (
            *self.config.candidate_angles_degrees,
            *([135.0, -135.0, 180.0] if recovering else []),
        )
        for speed_scale in self.config.candidate_speed_scales:
            for angle in angles if speed_scale else (0.0,):
                candidate = desired.rotated(math.radians(angle)) * speed_scale
                heading = math.atan2(candidate.y, candidate.x) if speed_scale else desired_heading
                facings = (
                    (heading,)
                    if abs(angle_delta(heading, soldier.facing)) < 1e-9
                    else (heading, soldier.facing)
                )
                for facing in facings:
                    motion = steering_motion(
                        shape,
                        candidate.x * dt,
                        candidate.y * dt,
                        facing,
                        dt,
                        self.config.movement_turn_rate,
                    )
                    score = _motion_score(
                        desired,
                        candidate,
                        detour_sign=soldier.detour_sign,
                        previous=soldier.velocity,
                    )
                    score += abs(angle_delta(motion.at(1).angle, desired_heading)) * 0.15
                    moving_candidate = candidate.length_sq() > 1e-6
                    if (
                        best is not None
                        and score >= best[0]
                        and (
                            not recovering
                            or not moving_candidate
                            or (best_moving is not None and score >= best_moving[0])
                        )
                    ):
                        continue
                    if not motion.clear(
                        obstacles, field=field, tolerance=self.config.separation_slop
                    ):
                        continue
                    ttc = None
                    blocked_by = None
                    stop_time = _arrival_time(soldier.pos, candidate, arrival_zone)
                    for other, other_shape in zip(neighbors, obstacles, strict=True):
                        collision = _pose_collision_time(
                            motion,
                            dt,
                            candidate,
                            other_shape,
                            Vec2(0, 0) if other.stopped else other.velocity,
                            self.config.avoidance_horizon,
                            stop_time,
                            self.config.separation_slop,
                        )
                        if collision is not None and (ttc is None or collision < ttc):
                            ttc, blocked_by = collision, other.id
                    # A real collision in this tick is vetoed above. Beyond it,
                    # risk is a cost, not an order to freeze indefinitely.
                    if ttc is not None:
                        score += 4.0 * (1.0 - ttc / self.config.avoidance_horizon)
                    item = (score, candidate, motion, ttc, blocked_by, angle)
                    if best is None or score < best[0]:
                        best = item
                    if candidate.length_sq() > 1e-6 and (
                        best_moving is None or score < best_moving[0]
                    ):
                        best_moving = item
                    if angle == 0 and speed_scale == 1 and ttc is None:
                        return SteeringResult(
                            candidate,
                            "free",
                            facing=motion.at(1).angle,
                            turn_fraction=motion.turn_fraction,
                        )
                if best is not None and best[0] < 0.001:
                    break
            if best is not None and best[0] < 0.001:
                break
        if (
            recovering
            and best is not None
            and best[1].length_sq() < 1e-6
            and best_moving is not None
        ):
            best = best_moving
        if best is None:
            return SteeringResult(Vec2(0, 0), "blocked", facing=soldier.facing)
        _, velocity, motion, ttc, blocker, angle = best
        reason = "free" if angle == 0 and ttc is None else "avoid"
        if abs(angle_delta(motion.at(1).angle, math.atan2(velocity.y, velocity.x))) > 0.1:
            reason = "maneuver"
        return SteeringResult(
            velocity,
            reason,
            blocked_by=(blocker,) if blocker is not None else (),
            time_to_collision=ttc,
            candidate_angle=angle,
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

        iterations = (
            2
            if self.config.collision_mode == CollisionMode.SOFT
            else self.config.separation_iterations
        )
        correction_budget: dict[int, float] = {}
        for iteration in range(iterations):
            self.spatial_hash.rebuild(alive)
            moved = False
            iteration_max = 0.0
            iteration_pairs = 0
            pairs = self._overlap_pairs(alive)
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
                    (
                        min(
                            overlap,
                            min(
                                unit_bounding_radius(
                                    first.unit,
                                    self.config.fallback_unit_radius,
                                ),
                                unit_bounding_radius(
                                    second.unit,
                                    self.config.fallback_unit_radius,
                                ),
                            )
                            * 0.35,
                        )
                        if self.config.collision_mode == CollisionMode.SOFT
                        else overlap
                    ),
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
