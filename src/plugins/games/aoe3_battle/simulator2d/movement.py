"""Local collision avoidance and overlap resolution for the 2D engine."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from .config import CollisionMode, Simulation2DConfig
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
    radius: float,
    horizon: float,
) -> float | None:
    relative_position = Vec2(neighbor.x - soldier.x, neighbor.y - soldier.y)
    relative_velocity = velocity if neighbor.stopped else velocity - neighbor.velocity
    combined_radius = radius * 2.0

    if relative_position.length_sq() <= combined_radius * combined_radius:
        # Already overlapping: only an outward-moving velocity is admissible.
        returning_to_contact = relative_position.dot(relative_velocity) >= 0.0
        return 0.0 if returning_to_contact else None

    c = relative_position.dot(relative_position) - combined_radius * combined_radius
    a = relative_velocity.dot(relative_velocity)
    if a <= 1e-12:
        return None
    b = relative_position.dot(relative_velocity)
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


def _candidate_score(
    soldier: Soldier2D,
    preferred: Vec2,
    candidate: Vec2,
    neighbors: list[Soldier2D],
    *,
    radius: float,
    horizon: float,
) -> tuple[float, float | None, int | None]:
    nearest_ttc: float | None = None
    blocking_id: int | None = None
    currently_overlapping = False
    for neighbor in neighbors:
        if neighbor.distance_sq_to(soldier) < (radius * 2.0) ** 2:
            currently_overlapping = True
        ttc = _time_to_collision(
            soldier,
            candidate,
            neighbor,
            radius=radius,
            horizon=horizon,
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
) -> float:
    """Score candidates with collision as a smooth penalty, not a hard veto.

    A hard veto makes a unit stand still when an entire friendly front row
    blocks it.  A smooth penalty lets it choose the least-colliding tangential
    direction and slide along the formation edge.
    """
    collision_penalty = (
        0.0
        if nearest_ttc is None
        else 35.0 * (1.0 - nearest_ttc / max(horizon, 1e-9))
    )
    preferred_dir = preferred.normalized()
    candidate_dir = candidate.normalized()
    forward_penalty = 1.0 - max(-1.0, min(1.0, preferred_dir.dot(candidate_dir)))
    displacement = candidate.length()
    progress_bonus = displacement * (2.5 if blocked_ticks > 0 else 0.8)
    return (
        collision_penalty
        + forward_penalty * 4.0
        + progress_bonus
    )


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
                - max(0.0, item.velocity.dot(
                    Vec2(item.x - soldier.x, item.y - soldier.y).normalized()
                )),
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

        if blocked_ticks >= self.config.blocked_window_ticks:
            desired = desired.rotated(
                math.radians(self.config.detour_angle_degrees)
                * soldier.detour_sign
            )

        free_path = True
        separating_from_overlap = False
        for neighbor in neighbors:
            if neighbor.distance_sq_to(soldier) < (
                self.config.unit_radius * 2.0
            ) ** 2:
                separating_from_overlap = True
            if _time_to_collision(
                soldier,
                desired,
                neighbor,
                radius=self.config.unit_radius,
                horizon=self.config.avoidance_horizon,
            ) is not None:
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
        best_progress: tuple[float, Vec2, float | None, int | None, float] | None = None

        base_direction = desired.normalized()
        for speed_scale in self.config.candidate_speed_scales:
            speed = soldier.unit.speed * speed_scale
            for angle in self.config.candidate_angles_degrees:
                candidate = base_direction.rotated(math.radians(angle)) * speed
                _hard_score, ttc, blocking_id = _candidate_score(
                    soldier,
                    desired,
                    candidate,
                    neighbors,
                    radius=self.config.unit_radius,
                    horizon=self.config.avoidance_horizon,
                )
                # Prefer genuinely collision-free candidates, then allow
                # collision-penalized sliding candidates instead of freezing.
                score = (
                    _sliding_score(
                        desired,
                        candidate,
                        ttc,
                        horizon=self.config.avoidance_horizon,
                        blocked_ticks=blocked_ticks,
                        blocked_window_ticks=self.config.blocked_window_ticks,
                        detour_sign=soldier.detour_sign,
                    )
                )
                item = (score, candidate, ttc, blocking_id, angle)
                if best is None or score < best[0]:
                    best = item
                # Keep the best candidate that actually has a meaningful
                # tangential displacement.  This is what turns a blocked
                # front into side-flow instead of a nearly zero stuck step.
                if (
                    item[1].length() >= soldier.unit.speed * 0.25
                    and (best_progress is None or score < best_progress[0])
                ):
                    best_progress = item

        selected = best_progress or best
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
        radius = self.config.unit_radius
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
            for overlap, first, second, distance in pairs[:pair_limit]:
                if overlap <= self.config.separation_slop:
                    continue
                dx = second.x - first.x
                dy = second.y - first.y
                if distance <= 1e-9:
                    angle = math.radians((first.id * 37 + second.id * 17) % 360)
                    nx = math.cos(angle)
                    ny = math.sin(angle)
                else:
                    nx = dx / distance
                    ny = dy / distance
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
                        min(overlap, self.config.unit_radius * 0.35)
                        if self.config.collision_mode == CollisionMode.SOFT
                        else overlap
                    ),
                    field_width=field_width,
                    field_height=field_height,
                    max_correction=allowed,
                )
                correction_budget[first.id] = correction_budget.get(
                    first.id,
                    self.config.max_position_correction_per_tick,
                ) - applied
                correction_budget[second.id] = correction_budget.get(
                    second.id,
                    self.config.max_position_correction_per_tick,
                ) - applied

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
        minimum = self.config.unit_radius * 2.0
        for soldier in sorted(alive, key=lambda item: item.id):
            nearby = self.spatial_hash.query_circle(
                soldier.pos,
                minimum * 1.05,
                predicate=lambda other, soldier_id=soldier.id: (
                    other.id > soldier_id
                ),
            )
            for other in nearby:
                distance = soldier.distance_to(other)
                overlap = minimum - distance
                if overlap > self.config.separation_slop:
                    pairs.append((overlap, soldier, other, distance))
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
        minimum = self.config.unit_radius * 2.0
        for soldier in sorted(alive, key=lambda item: item.id):
            nearby = self.spatial_hash.query_circle(
                soldier.pos,
                minimum * 1.05,
                predicate=lambda other, soldier_id=soldier.id: (
                    other.id > soldier_id
                ),
            )
            for other in nearby:
                distance = soldier.distance_to(other)
                overlap = minimum - distance
                if overlap <= self.config.separation_slop:
                    continue
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

        radius = self.config.unit_radius
        first.x = min(max(first.x, radius), field_width - radius)
        first.y = min(max(first.y, radius), field_height - radius)
        second.x = min(max(second.x, radius), field_width - radius)
        second.y = min(max(second.y, radius), field_height - radius)
        return correction
