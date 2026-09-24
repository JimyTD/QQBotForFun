"""Bounded local visibility routing and collision-checked route shortcuts."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, replace
from enum import StrEnum

from .config import Simulation2DConfig
from .geometry import (
    CollisionShape,
    inside_field,
    shape_for_unit,
    steering_motion,
    swept_contact,
    unit_bounding_radius,
)
from .model import Soldier2D, Vec2
from .spatial import SpatialHash


def segment_distance_sq(start: Vec2, end: Vec2, point: Vec2) -> float:
    dx, dy = end.x - start.x, end.y - start.y
    px, py = point.x - start.x, point.y - start.y
    t = max(0.0, min(1.0, (px * dx + py * dy) / max(dx * dx + dy * dy, 1e-12)))
    return (dx * t - px) ** 2 + (dy * t - py) ** 2


def _clear(
    start: Vec2,
    end: Vec2,
    facing: float,
    shape: CollisionShape,
    obstacles: list[CollisionShape],
    config: Simulation2DConfig,
    field: tuple[float, float] | None = None,
    speed: float = 4.0,
) -> bool:
    angle = (
        math.atan2(end.y - start.y, end.x - start.x)
        if (end - start).length_sq() > 1e-12
        else facing
    )
    motion = steering_motion(
        replace(shape, x=start.x, y=start.y, angle=facing),
        end.x - start.x,
        end.y - start.y,
        angle,
        (end - start).length() / max(speed, 1e-9),
        config.movement_turn_rate,
    )
    return motion.clear(
        obstacles,
        field=field,
        tolerance=config.separation_slop,
        padding=config.avoidance_margin * 0.5,
    )


def route_clear(
    soldier: Soldier2D,
    end: Vec2,
    spatial: SpatialHash,
    config: Simulation2DConfig,
    *,
    target_id: int | None = None,
    field: tuple[float, float] | None = None,
) -> bool:
    radius = unit_bounding_radius(soldier.unit, config.fallback_unit_radius)
    midpoint = (soldier.pos + end) * 0.5
    neighbors = spatial.query_circle(
        midpoint,
        (end - soldier.pos).length() * 0.5
        + radius
        + max(config.max_known_unit_radius, config.fallback_unit_radius)
        + config.avoidance_margin * 0.5,
        predicate=lambda other: other.id not in (soldier.id, target_id),
    )
    shape = shape_for_unit(
        soldier.unit, soldier.x, soldier.y, soldier.facing, config.fallback_unit_radius
    )
    obstacles = [
        shape_for_unit(other.unit, other.x, other.y, other.facing, config.fallback_unit_radius)
        for other in neighbors
    ]
    return _clear(
        soldier.pos, end, soldier.facing, shape, obstacles, config, field, soldier.effective_speed
    )


@dataclass(frozen=True)
class DetourPlan:
    sign: int
    points: tuple[Vec2, ...]
    cost: float


class RouteStatus(StrEnum):
    DIRECT = "direct"
    FOUND = "found"
    LOCAL_NO_ROUTE = "local_no_route"
    BUDGET_EXHAUSTED = "budget_exhausted"
    COST_LIMIT = "cost_limit"


@dataclass(frozen=True)
class RouteSearch:
    status: RouteStatus
    plan: DetourPlan | None = None
    expanded: int = 0


def search_detour(
    soldier: Soldier2D,
    target: Soldier2D,
    spatial: SpatialHash,
    config: Simulation2DConfig,
    field_width: float,
    field_height: float,
    *,
    arrival_distance: float | None = None,
    expansion_budget: int | None = None,
) -> RouteSearch:
    forward = (target.pos - soldier.pos).normalized()
    if forward.length_sq() < 1e-12:
        return RouteSearch(RouteStatus.DIRECT)
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
    shape = shape_for_unit(
        soldier.unit, soldier.x, soldier.y, soldier.facing, config.fallback_unit_radius
    )
    obstacles = [
        shape_for_unit(other.unit, other.x, other.y, other.facing, config.fallback_unit_radius)
        for other in bodies
    ]
    field = (field_width, field_height)
    stop_distance = max(
        0.0,
        (soldier.effective_melee_range if arrival_distance is None else arrival_distance)
        - config.stop_check_slack,
    )
    travel = min(reach * 0.8, max(0.0, soldier.distance_to(target) - stop_distance))
    goal = soldier.pos + forward * travel
    if _clear(
        soldier.pos, goal, soldier.facing, shape, obstacles, config, field, soldier.effective_speed
    ):
        return RouteSearch(RouteStatus.DIRECT)

    def in_field(p: Vec2) -> bool:
        return 0.0 <= p.x <= field_width and 0.0 <= p.y <= field_height

    orientations = [math.atan2(forward.y, forward.x)]
    if not shape.is_circular:
        orientations.append(soldier.facing)

    def available_node(point: Vec2) -> bool:
        for angle in orientations:
            posed = replace(shape, x=point.x, y=point.y, angle=angle)
            if inside_field(posed, *field) and all(
                swept_contact(posed, other, 0, 0, padding=config.avoidance_margin * 0.5) is None
                for other in obstacles
            ):
                return True
        return False

    goals = [goal]
    if soldier.distance_to(target) - stop_distance <= reach * 0.8:
        goals = [
            target.pos - forward.rotated(index * math.pi / 4) * stop_distance for index in range(8)
        ]
    goals = [p for p in goals if in_field(p) and available_node(p)]

    # Sample the combined ellipse supports, not only the enclosing circle.
    # Every edge (including its entry turn) is checked by the motion solver.
    nodes = [soldier.pos, *goals]
    goal_indices = set(range(1, len(nodes)))
    obstacle_start = len(nodes)
    obstacles.sort(key=lambda item: segment_distance_sq(soldier.pos, goal, Vec2(item.x, item.y)))
    for obstacle in obstacles[: config.navigation_max_obstacles]:
        for angle in orientations:
            oriented = replace(shape, angle=angle)
            for index in range(8):
                normal = forward.rotated(index * math.pi / 4)
                ax, ay = oriented.support(normal.x, normal.y)
                bx, by = obstacle.support(normal.x, normal.y)
                margin = config.avoidance_margin * 0.5 + 0.025
                point = Vec2(
                    obstacle.x + (ax + bx + normal.x * margin) / math.cos(math.pi / 8),
                    obstacle.y + (ay + by + normal.y * margin) / math.cos(math.pi / 8),
                )
                if in_field(point) and available_node(point):
                    nodes.append(point)
    # Local contour points can themselves be valid firing positions. Do not
    # require a ranged unit to reach one of eight distant circle samples.
    if arrival_distance is not None:
        for index in range(obstacle_start, len(nodes)):
            distance = (nodes[index] - target.pos).length()
            if distance <= stop_distance and (
                not soldier.has_ranged
                or distance >= soldier.effective_ranged_range_min
                or (soldier.has_melee and distance <= soldier.effective_melee_range)
            ):
                goal_indices.add(index)
        goals = [nodes[index] for index in sorted(goal_indices)]
    if not goals:
        return RouteSearch(RouteStatus.LOCAL_NO_ROUTE)
    # Candidate corners can extend beyond the original local query. Include
    # every static obstruction in that envelope before approving any edge.
    margin = (
        radius
        + max(config.max_known_unit_radius, config.fallback_unit_radius)
        + config.avoidance_margin
    )
    envelope = spatial.query_box(
        min(p.x for p in nodes) - margin,
        max(p.x for p in nodes) + margin,
        min(p.y for p in nodes) - margin,
        max(p.y for p in nodes) + margin,
    )
    obstacles = [
        shape_for_unit(other.unit, other.x, other.y, other.facing, config.fallback_unit_radius)
        for other in envelope
        if other.id not in (soldier.id, target.id)
        and (
            other.stopped
            or other.velocity.length() < other.unit.speed * 0.25
            or other.no_progress_ticks >= config.blocked_window_ticks
        )
    ]
    preferred = soldier.detour_sign if soldier.detour_ticks else (1 if soldier.id % 2 == 0 else -1)
    initial = (0, soldier.facing)
    costs = {initial: 0.0}
    previous = {}
    edges = {}

    def heuristic(point):
        return min((point - end).length() for end in goals)

    queue = [(heuristic(soldier.pos), 0.0, initial)]
    cost_limit = (
        max(4.0, soldier.distance_to(target) * config.navigation_max_stretch) - stop_distance
    )
    expanded = set()
    budget = config.navigation_max_expansions if expansion_budget is None else expansion_budget
    while queue and len(expanded) < budget:
        estimate, cost, state = heapq.heappop(queue)
        if estimate > cost_limit:
            return RouteSearch(RouteStatus.COST_LIMIT, expanded=len(expanded))
        if state in expanded:
            continue
        current, facing = state
        if current in goal_indices:
            states = [state]
            while states[-1] != initial:
                states.append(previous[states[-1]])
            points = [nodes[s[0]] for s in reversed(states[:-1])]
            # String-pull only across verified clear segments, never across bodies.
            pulled = []
            start = soldier.pos
            # Circular bodies have no entry-angle state. For ellipses preserve
            # the verified turns; later shortcuts use the same motion contract.
            if not shape.is_circular:
                pulled, points = points, []
            while points:
                index = next(
                    i
                    for i in range(len(points) - 1, -1, -1)
                    if _clear(
                        start,
                        points[i],
                        soldier.facing,
                        shape,
                        obstacles,
                        config,
                        field,
                        soldier.effective_speed,
                    )
                )
                start = points[index]
                pulled.append(start)
                points = points[index + 1 :]
            cross = (pulled[0] - soldier.pos).dot(lateral)
            sign = (1 if cross > 0 else -1) if abs(cross) > 1e-8 else preferred
            return RouteSearch(
                RouteStatus.FOUND, DetourPlan(sign, tuple(pulled), cost), len(expanded)
            )
        expanded.add(state)
        ordered = sorted(
            range(obstacle_start, len(nodes)), key=lambda i: (nodes[i] - nodes[current]).length_sq()
        )
        candidates = dict.fromkeys([*sorted(goal_indices), *ordered[:24]])
        for neighbor in candidates:
            dx, dy = nodes[neighbor].x - nodes[current].x, nodes[neighbor].y - nodes[current].y
            motion = steering_motion(
                replace(shape, x=nodes[current].x, y=nodes[current].y, angle=facing),
                dx,
                dy,
                math.atan2(dy, dx),
                math.hypot(dx, dy) / max(soldier.effective_speed, 1e-9),
                config.movement_turn_rate,
            )
            next_state = (neighbor, motion.at(1).angle if not shape.is_circular else soldier.facing)
            if neighbor == current or next_state in expanded:
                continue
            edge = (state, neighbor)
            if edge not in edges:
                edges[edge] = motion.clear(
                    obstacles,
                    field=field,
                    tolerance=config.separation_slop,
                    padding=config.avoidance_margin * 0.5,
                )
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
            if score < costs.get(next_state, math.inf):
                costs[next_state] = score
                previous[next_state] = state
                heapq.heappush(queue, (score + heuristic(nodes[neighbor]), score, next_state))
    return RouteSearch(
        RouteStatus.BUDGET_EXHAUSTED if queue else RouteStatus.LOCAL_NO_ROUTE,
        expanded=len(expanded),
    )


def plan_detour(
    soldier: Soldier2D,
    target: Soldier2D,
    spatial: SpatialHash,
    config: Simulation2DConfig,
    field_width: float,
    field_height: float,
) -> DetourPlan | None:
    """Compatibility helper; engine callers use the explicit search status."""
    return search_detour(soldier, target, spatial, config, field_width, field_height).plan
