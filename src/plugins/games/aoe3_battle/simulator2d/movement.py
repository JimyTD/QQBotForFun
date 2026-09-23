"""Local collision avoidance and overlap resolution for the 2D engine."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from .config import CollisionMode, Simulation2DConfig
from .geometry import (
    combined_radius,
    shape_contact,
    shape_for_unit,
    unit_bounding_radius,
    unit_radius,
)
from .model import Soldier2D, Vec2
from .spatial import SpatialHash

logger = logging.getLogger("aoe3_battle.simulator2d.movement")


@dataclass(frozen=True)
class SteeringResult:
    velocity: Vec2
    reason: str
    blocked_by: tuple[int, ...] = ()
    blocked_ticks: int = 0
    time_to_collision: float | None = None
    candidate_angle: float = 0.0
    wall_contact: bool = False


def _time_to_collision(
    soldier: Soldier2D,
    velocity: Vec2,
    neighbor: Soldier2D,
    *,
    fallback_radius: float,
    horizon: float,
    stop_time: float | None = None,
) -> float | None:
    relative_position = Vec2(neighbor.x - soldier.x, neighbor.y - soldier.y)
    neighbor_velocity = Vec2(0.0, 0.0) if neighbor.stopped else neighbor.velocity
    relative_velocity = velocity - neighbor_velocity
    minimum_distance = combined_radius(
        soldier.unit,
        neighbor.unit,
        fallback_radius,
    )
    moving_horizon = horizon if stop_time is None else min(horizon, max(0.0, stop_time))
    collision = _circle_entry_time(
        relative_position, relative_velocity, minimum_distance, moving_horizon
    )
    if collision is not None or moving_horizon >= horizon:
        return collision

    # Arrival does not erase other moving bodies: predict the stationary
    # remainder too, rather than discarding all collisions after arrival.
    relative_at_stop = relative_position - relative_velocity * moving_horizon
    collision = _circle_entry_time(
        relative_at_stop,
        neighbor_velocity * -1.0,
        minimum_distance,
        horizon - moving_horizon,
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


def _candidate_score(
    soldier: Soldier2D,
    preferred: Vec2,
    candidate: Vec2,
    neighbors: list[Soldier2D],
    *,
    fallback_radius: float,
    horizon: float,
    stop_time: float | None = None,
) -> tuple[float, float | None, int | None]:
    nearest_ttc: float | None = None
    blocking_id: int | None = None
    currently_overlapping = False
    for neighbor in neighbors:
        minimum_distance = combined_radius(
            soldier.unit,
            neighbor.unit,
            fallback_radius,
        )
        if neighbor.distance_sq_to(soldier) < minimum_distance * minimum_distance:
            currently_overlapping = True
        ttc = _time_to_collision(
            soldier,
            candidate,
            neighbor,
            fallback_radius=fallback_radius,
            horizon=horizon,
            stop_time=stop_time,
        )
        if ttc is not None and (nearest_ttc is None or ttc < nearest_ttc):
            nearest_ttc = ttc
            blocking_id = neighbor.id

    if currently_overlapping:
        collision_penalty = 10000.0
    elif nearest_ttc is None:
        collision_penalty = 0.0
    else:
        collision_penalty = 1000.0 * (1.0 - nearest_ttc / max(horizon, 1e-9))

    direction_penalty = preferred.normalized().dot(candidate.normalized())
    if direction_penalty < -1.0:
        direction_penalty = -1.0
    elif direction_penalty > 1.0:
        direction_penalty = 1.0

    score = collision_penalty + (1.0 - direction_penalty) * 8.0
    return score, nearest_ttc, blocking_id


def _sliding_score(
    preferred: Vec2,
    candidate: Vec2,
    nearest_ttc: float | None,
    *,
    horizon: float,
    blocked_ticks: int,
    blocked_window_ticks: int,
    detour_sign: int,
    previous: Vec2 = Vec2(0.0, 0.0),
) -> float:
    """Score candidates with collision as a smooth penalty, not a hard veto.

    A hard veto makes a unit stand still when an entire friendly front row
    blocks it.  A smooth penalty lets it choose the least-colliding tangential
    direction and slide along the formation edge.
    """
    collision_penalty = (
        0.0 if nearest_ttc is None else 35.0 * (1.0 - nearest_ttc / max(horizon, 1e-9))
    )
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
    return collision_penalty + forward_penalty * 4.0 + speed_penalty + side_penalty + turn_penalty


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
        desired = desired.clamped_length(soldier.unit.speed)
        if desired.length_sq() <= 1e-12:
            return SteeringResult(Vec2(0.0, 0.0), "desired_zero")

        neighbors = self.spatial_hash.query_circle(
            soldier.pos,
            self.config.avoidance_radius,
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
        neighbors = neighbors[: self.config.max_neighbors]

        if not neighbors:
            return self._apply_walls(
                soldier,
                desired,
                blocked_by=(),
                field_width=field_width,
                field_height=field_height,
            )

        free_path = True
        separating_from_overlap = False
        desired_stop_time = _arrival_time(soldier.pos, desired, arrival_zone)
        for neighbor in neighbors:
            if (
                neighbor.distance_sq_to(soldier)
                < (
                    combined_radius(
                        soldier.unit,
                        neighbor.unit,
                        self.config.fallback_unit_radius,
                    )
                )
                ** 2
            ):
                separating_from_overlap = True
            if (
                _time_to_collision(
                    soldier,
                    desired,
                    neighbor,
                    fallback_radius=self.config.fallback_unit_radius,
                    horizon=self.config.avoidance_horizon,
                    stop_time=desired_stop_time,
                )
                is not None
            ):
                free_path = False
                break
        if free_path:
            return self._apply_walls(
                soldier,
                desired,
                blocked_by=(),
                reason="separate" if separating_from_overlap else "free",
                ttc=None,
                field_width=field_width,
                field_height=field_height,
            )

        best: tuple[float, Vec2, float | None, int | None, float] | None = None

        base_direction = desired.normalized()
        for speed_scale in self.config.candidate_speed_scales:
            speed = desired.length() * speed_scale
            for angle in self.config.candidate_angles_degrees:
                candidate = base_direction.rotated(math.radians(angle)) * speed
                candidate = self._apply_walls(
                    soldier,
                    candidate,
                    blocked_by=(),
                    field_width=field_width,
                    field_height=field_height,
                ).velocity
                _hard_score, ttc, blocking_id = _candidate_score(
                    soldier,
                    desired,
                    candidate,
                    neighbors,
                    fallback_radius=self.config.fallback_unit_radius,
                    horizon=self.config.avoidance_horizon,
                    stop_time=_arrival_time(soldier.pos, candidate, arrival_zone),
                )
                # Prefer genuinely collision-free candidates, then allow
                # collision-penalized sliding candidates instead of freezing.
                score = _sliding_score(
                    desired,
                    candidate,
                    ttc,
                    horizon=self.config.avoidance_horizon,
                    blocked_ticks=blocked_ticks,
                    blocked_window_ticks=self.config.blocked_window_ticks,
                    detour_sign=soldier.detour_sign,
                    previous=soldier.velocity,
                )
                item = (score, candidate, ttc, blocking_id, angle)
                if best is None or score < best[0]:
                    best = item

        selected = best
        if selected is None:
            return self._apply_walls(
                soldier,
                Vec2(0.0, 0.0),
                blocked_by=tuple(item.id for item in neighbors[:4]),
                reason="solver_empty",
                field_width=field_width,
                field_height=field_height,
            )

        score, velocity, ttc, blocking_id, angle = selected
        if ttc is None:
            reason = "avoid"
        elif blocked_ticks >= self.config.blocked_window_ticks:
            reason = "detour"
        else:
            reason = "sliding"
        blocked_by = (blocking_id,) if blocking_id is not None else ()
        return self._apply_walls(
            soldier,
            velocity,
            blocked_by=blocked_by,
            reason=reason,
            ttc=ttc,
            angle=angle,
            field_width=field_width,
            field_height=field_height,
        )

    def _apply_walls(
        self,
        soldier: Soldier2D,
        velocity: Vec2,
        *,
        blocked_by: tuple[int, ...],
        reason: str = "free",
        ttc: float | None = None,
        angle: float = 0.0,
        field_width: float,
        field_height: float,
    ) -> SteeringResult:
        """Slide along a border instead of pushing into it."""
        wall_contact = False
        x = velocity.x
        y = velocity.y
        radius = unit_radius(soldier.unit, self.config.fallback_unit_radius)
        if soldier.x <= radius and x < 0:
            x = 0.0
            wall_contact = True
        elif soldier.x >= field_width - radius and x > 0:
            x = 0.0
            wall_contact = True
        if soldier.y <= radius and y < 0:
            y = 0.0
            wall_contact = True
        elif soldier.y >= field_height - radius and y > 0:
            y = 0.0
            wall_contact = True

        if wall_contact and reason == "free":
            reason = "wall"
        return SteeringResult(
            velocity=Vec2(x, y),
            reason=reason,
            blocked_by=blocked_by,
            blocked_ticks=0,
            time_to_collision=ttc,
            candidate_angle=angle,
            wall_contact=wall_contact,
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

        first_radius = unit_bounding_radius(
            first.unit,
            self.config.fallback_unit_radius,
        )
        second_radius = unit_bounding_radius(
            second.unit,
            self.config.fallback_unit_radius,
        )
        first.x = min(max(first.x, first_radius), field_width - first_radius)
        first.y = min(max(first.y, first_radius), field_height - first_radius)
        second.x = min(max(second.x, second_radius), field_width - second_radius)
        second.y = min(max(second.y, second_radius), field_height - second_radius)
        return correction
