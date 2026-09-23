"""Bounded local visibility routing and collision-checked route shortcuts."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from .config import Simulation2DConfig
from .geometry import unit_bounding_radius
from .model import Soldier2D, Vec2
from .spatial import SpatialHash


def segment_distance_sq(start: Vec2, end: Vec2, point: Vec2) -> float:
    dx, dy = end.x - start.x, end.y - start.y
    px, py = point.x - start.x, point.y - start.y
    t = max(0.0, min(1.0, (px * dx + py * dy) / max(dx * dx + dy * dy, 1e-12)))
    return (dx * t - px) ** 2 + (dy * t - py) ** 2


def _clear(start: Vec2, end: Vec2, obstacles: list[tuple[Vec2, float]]) -> bool:
    dx, dy = end.x - start.x, end.y - start.y
    length_sq = max(dx * dx + dy * dy, 1e-12)
    for center, radius in obstacles:
        px, py = center.x - start.x, center.y - start.y
        dot = px * dx + py * dy
        if px * px + py * py < radius * radius and dot <= 0:
            continue
        t = max(0.0, min(1.0, dot / length_sq))
        if (dx * t - px) ** 2 + (dy * t - py) ** 2 < radius * radius - 1e-9:
            return False
    return True


def route_clear(
    soldier: Soldier2D,
    end: Vec2,
    spatial: SpatialHash,
    config: Simulation2DConfig,
    *,
    target_id: int | None = None,
) -> bool:
    radius = unit_bounding_radius(soldier.unit, config.fallback_unit_radius)
    midpoint = (soldier.pos + end) * 0.5
    neighbors = spatial.query_circle(
        midpoint,
        (end - soldier.pos).length() * 0.5
        + radius
        + max(config.max_known_unit_radius, config.fallback_unit_radius),
        predicate=lambda other: other.id not in (soldier.id, target_id),
    )
    return _clear(
        soldier.pos,
        end,
        [
            (
                other.pos,
                radius
                + unit_bounding_radius(other.unit, config.fallback_unit_radius)
                + config.avoidance_margin * 0.5,
            )
            for other in neighbors
        ],
    )


@dataclass(frozen=True)
class DetourPlan:
    sign: int
    points: tuple[Vec2, ...]
    cost: float


def plan_detour(
    soldier: Soldier2D,
    target: Soldier2D,
    spatial: SpatialHash,
    config: Simulation2DConfig,
    field_width: float,
    field_height: float,
) -> DetourPlan | None:
    forward = (target.pos - soldier.pos).normalized()
    if forward.length_sq() < 1e-12:
        return None
    lateral = Vec2(-forward.y, forward.x)
    radius = unit_bounding_radius(soldier.unit, config.fallback_unit_radius)
    reach = max(config.avoidance_radius * 3, radius * 6)
    neighbors = spatial.query_circle(
        soldier.pos,
        reach + config.max_known_unit_radius,
        predicate=lambda other: other.id not in (soldier.id, target.id),
    )
    bodies = [
        other
        for other in neighbors
        if other.stopped
        or other.velocity.length() < other.unit.speed * 0.25
        or other.no_progress_ticks >= config.blocked_window_ticks
    ]
    obstacles = [
        (
            other.pos,
            radius
            + unit_bounding_radius(other.unit, config.fallback_unit_radius)
            + config.avoidance_margin * 0.5,
        )
        for other in bodies
    ]
    stop_distance = max(0.0, soldier.effective_melee_range - config.stop_check_slack)
    travel = min(reach * 0.8, max(0.0, soldier.distance_to(target) - stop_distance))
    goal = soldier.pos + forward * travel
    if not obstacles or _clear(soldier.pos, goal, obstacles):
        return None

    def in_field(p: Vec2) -> bool:
        return radius <= p.x <= field_width - radius and radius <= p.y <= field_height - radius

    goals = [goal]
    if soldier.distance_to(target) - stop_distance <= reach * 0.8:
        goals = [
            target.pos - forward.rotated(index * math.pi / 4) * stop_distance for index in range(8)
        ]
    goals = [
        p
        for p in goals
        if in_field(p)
        and all((p - center).length_sq() >= clearance**2 for center, clearance in obstacles)
    ]
    if not goals:
        return None

    # Circumscribed octagons give a conservative clearance envelope; unlike
    # a cluster rectangle they retain gaps between staggered rows and sizes.
    nodes = [soldier.pos, *goals]
    goal_indices = set(range(1, len(nodes)))
    obstacle_start = len(nodes)
    obstacles.sort(key=lambda item: segment_distance_sq(soldier.pos, goal, item[0]))
    for center, clearance in obstacles[: config.navigation_max_obstacles]:
        distance = (clearance + 0.025) / math.cos(math.pi / 8)
        for index in range(8):
            point = center + forward.rotated(index * math.pi / 4) * distance
            if in_field(point) and all((point - c).length_sq() >= r * r for c, r in obstacles):
                nodes.append(point)
    preferred = soldier.detour_sign if soldier.detour_ticks else (1 if soldier.id % 2 == 0 else -1)
    costs = {0: 0.0}
    previous = {}
    edges = {}

    def heuristic(point):
        return min((point - end).length() for end in goals)

    queue = [(heuristic(soldier.pos), 0.0, 0)]
    cost_limit = max(4.0, soldier.distance_to(target) * config.navigation_max_stretch) - stop_distance
    expanded = set()
    while queue and len(expanded) < config.navigation_max_expansions:
        estimate, cost, current = heapq.heappop(queue)
        if estimate > cost_limit:
            break
        if current in expanded:
            continue
        if current in goal_indices:
            indices = [current]
            while indices[-1] != 0:
                indices.append(previous[indices[-1]])
            points = [nodes[i] for i in reversed(indices[:-1])]
            # String-pull only across verified clear segments, never across bodies.
            pulled = []
            start = soldier.pos
            while points:
                index = next(
                    i for i in range(len(points) - 1, -1, -1) if _clear(start, points[i], obstacles)
                )
                start = points[index]
                pulled.append(start)
                points = points[index + 1 :]
            cross = (pulled[0] - soldier.pos).dot(lateral)
            sign = (1 if cross > 0 else -1) if abs(cross) > 1e-8 else preferred
            return DetourPlan(sign, tuple(pulled), cost)
        expanded.add(current)
        ordered = sorted(
            range(obstacle_start, len(nodes)), key=lambda i: (nodes[i] - nodes[current]).length_sq()
        )
        candidates = [*sorted(goal_indices), *ordered[:24]]
        for neighbor in candidates:
            if neighbor == current or neighbor in expanded:
                continue
            edge = (current, neighbor)
            if edge not in edges:
                edges[edge] = _clear(nodes[current], nodes[neighbor], obstacles)
            if not edges[edge]:
                continue
            score = cost + (nodes[current] - nodes[neighbor]).length()
            if current == 0 and (nodes[neighbor] - soldier.pos).dot(lateral) * preferred < 0:
                score += 0.005
            # Committed routes reserve space softly; no hard lanes or ID orders.
            if current == 0:
                score += sum(
                    0.08
                    for other in neighbors
                    if other.detour_waypoint_x is not None
                    and segment_distance_sq(
                        nodes[current],
                        nodes[neighbor],
                        Vec2(other.detour_waypoint_x, other.detour_waypoint_y),
                    )
                    < radius**2
                )
            if score < costs.get(neighbor, math.inf):
                costs[neighbor] = score
                previous[neighbor] = current
                heapq.heappush(queue, (score + heuristic(nodes[neighbor]), score, neighbor))
    return None
