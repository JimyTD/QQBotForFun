"""Independent 2D battle simulator that preserves the 1D public contract."""

from __future__ import annotations

import logging
import math
import random
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from itertools import pairwise
from typing import Any

from src.plugins.aoe3.models import Unit

from .combat import CombatSystem
from .compat import ArmySlot, BattleEvent, BattleResult, EventType, Side
from .config import Simulation2DConfig
from .formation import build_deployment
from .geometry import (
    PoseMotion,
    angle_delta,
    shape_for_unit,
    steering_motion,
    unit_bounding_radius,
    unit_radius,
)
from .model import ArtilleryState, AttackMode, Soldier2D, TickSummary, Vec2
from .movement import CollisionResolver, LocalAvoidance, SteeringResult
from .navigation import RouteStatus, route_clear, search_detour, segment_distance_sq
from .spatial import SpatialHash
from .trace import FlightRecorder

logger = logging.getLogger("aoe3_battle.simulator2d")

VISUAL_EVENT_LIFETIMES = {
    EventType.ATTACK: 0.25,
    EventType.AOE_SPLASH: 0.5,
    EventType.DEATH: 0.6,
}


class BattleSimulator2D:
    """Production 2D battle simulator.

    It exposes the same constructor shape and ``run()`` result contract as the
    historical 1D implementation.
    """

    def __init__(
        self,
        red_unit: Unit | None = None,
        red_count: int = 0,
        blue_unit: Unit | None = None,
        blue_count: int = 0,
        *,
        red_army: list[tuple[Unit, int]] | None = None,
        blue_army: list[tuple[Unit, int]] | None = None,
        field_length: float | None = None,
        max_ticks: int | None = None,
        seed: int | None = None,
        duel_mode: bool = False,
        row_spacing: float | None = None,
        row_capacity: int | None = None,
        session_id: str = "local",
        trace: bool = False,
        frame_callback: Callable[[dict[str, Any]], None] | None = None,
        match_label: str = "",
        config: Simulation2DConfig | None = None,
    ) -> None:
        base = config or Simulation2DConfig()
        if (
            field_length is not None
            or max_ticks is not None
            or row_spacing is not None
            or row_capacity is not None
        ):
            base = Simulation2DConfig(
                **{
                    **asdict(base),
                    "field_length": (base.field_length if field_length is None else field_length),
                    "max_ticks": base.max_ticks if max_ticks is None else max_ticks,
                    "row_spacing": (base.row_spacing if row_spacing is None else row_spacing),
                    "max_columns": (
                        base.max_columns
                        if row_capacity is None
                        else max(base.min_columns, row_capacity)
                    ),
                }
            )
        self.config = base
        if self.config.max_known_unit_radius <= 0:
            known_units = [
                unit for unit, _count in (red_army or [(red_unit, red_count)]) if unit is not None
            ] + [
                unit
                for unit, _count in (blue_army or [(blue_unit, blue_count)])
                if unit is not None
            ]
            max_radius = max(
                (
                    unit_bounding_radius(unit, self.config.fallback_unit_radius)
                    for unit in known_units
                ),
                default=self.config.fallback_unit_radius,
            )
            self.config = Simulation2DConfig(
                **{
                    **asdict(self.config),
                    "max_known_unit_radius": max_radius,
                }
            )

        if red_army is not None:
            self.red_army = [ArmySlot(unit, count) for unit, count in red_army]
        elif red_unit is not None:
            self.red_army = [ArmySlot(red_unit, red_count)]
        else:
            raise ValueError("必须提供 red_unit 或 red_army")

        if blue_army is not None:
            self.blue_army = [ArmySlot(unit, count) for unit, count in blue_army]
        elif blue_unit is not None:
            self.blue_army = [ArmySlot(blue_unit, blue_count)]
        else:
            raise ValueError("必须提供 blue_unit 或 blue_army")

        self.red_count = sum(slot.count for slot in self.red_army)
        self.blue_count = sum(slot.count for slot in self.blue_army)
        self.initial_total_hp = {
            Side.RED: sum(slot.unit.hp * slot.count for slot in self.red_army),
            Side.BLUE: sum(slot.unit.hp * slot.count for slot in self.blue_army),
        }
        self.seed = seed
        self.session_id = session_id
        self.duel_mode = duel_mode
        self._rng = random.Random(seed)
        self._tick = 0
        self._events: list[BattleEvent] = []
        self._pending_visual_events: list[dict[str, Any]] = []
        self._soldiers: list[Soldier2D] = []
        self._soldier_map: dict[int, Soldier2D] = {}
        self._next_id = 1
        self._any_attack_happened = False
        self._field_width = self.config.field_length
        self._field_height = self.config.field_length
        self._solver_fallbacks = 0
        self._trace_enabled = trace
        self._frame_callback = frame_callback
        self.match_label = match_label
        self._trace = FlightRecorder(
            session_id=session_id,
            seed=seed,
            config=self.config,
            enabled=trace,
        )
        self._spatial_hash = SpatialHash(self.config.spatial_cell_size)
        self._movement = LocalAvoidance(self.config, self._spatial_hash)
        self._collisions = CollisionResolver(self.config, self._spatial_hash)
        self._combat: CombatSystem | None = None
        self._current_summary = TickSummary(
            tick=0,
            alive_red=self.red_count,
            alive_blue=self.blue_count,
            movers=0,
            attackers=0,
            blocked=0,
            wall_contacts=0,
            collision_pairs=0,
            max_overlap=0.0,
            avg_speed=0.0,
            solver_fallbacks=0,
        )

    def _create_soldier(
        self,
        soldier_id: int,
        side: Side,
        unit: Unit,
        position: Vec2,
    ) -> Soldier2D:
        soldier = Soldier2D(
            id=soldier_id,
            side=side,
            unit=unit,
            hp=float(unit.hp),
            max_hp=float(unit.hp),
            x=position.x,
            y=position.y,
            facing=0.0 if side == Side.RED else math.pi,
        )
        soldier.detour_sign = 1 if soldier_id % 2 == 0 else -1
        soldier.has_ranged = unit.attack_ranged > 0 and unit.range > 0
        soldier.has_melee = unit.attack_melee > 0
        soldier.effective_melee_range = (
            unit.range_melee
            if soldier.has_melee and unit.range_melee > 0
            else self.config.melee_range
        )
        if soldier.has_ranged:
            soldier.effective_ranged_attack = unit.attack_ranged
            soldier.effective_ranged_range = unit.range
            soldier.effective_ranged_rof = (
                unit.rof_ranged if unit.rof_ranged > 0 else self.config.default_rof_ranged
            )
            soldier.effective_ranged_range_min = unit.range_min
        return soldier

    def _init_soldiers(self) -> None:
        deployment = build_deployment(
            self.red_army,
            self.blue_army,
            self.config,
        )
        self._field_width = deployment.field_width
        self._field_height = deployment.field_height

        ordered_units = []
        red_units = _ordered_formation_units(self.red_army)
        blue_units = _ordered_formation_units(self.blue_army)
        ordered_units.extend(red_units)
        ordered_units.extend(blue_units)

        if len(ordered_units) != len(deployment.positions):
            raise RuntimeError(
                "formation placement mismatch: "
                f"units={len(ordered_units)} positions={len(deployment.positions)}"
            )

        side_for_index = [
            *(Side.RED for _ in red_units),
            *(Side.BLUE for _ in blue_units),
        ]
        for unit, side, position in zip(
            ordered_units,
            side_for_index,
            deployment.positions,
            strict=True,
        ):
            soldier = self._create_soldier(self._next_id, side, unit, position)
            self._next_id += 1
            self._soldiers.append(soldier)
            self._soldier_map[soldier.id] = soldier

        self._spatial_hash.rebuild(self._soldiers)
        self._combat = CombatSystem(
            config=self.config,
            rng=self._rng,
            spatial_hash=self._spatial_hash,
            soldier_map=self._soldier_map,
            emit=self._emit,
            tick_getter=lambda: self._tick,
            damage_callback=self._apply_damage,
            field_width=self._field_width,
            field_height=self._field_height,
        )
        logger.info(
            "2D init session=%s seed=%s red=%d blue=%d field=(%.1f,%.1f) "
            "red_rows=%d blue_rows=%d red_cols=%d blue_cols=%d",
            self.session_id,
            self.seed,
            self.red_count,
            self.blue_count,
            self._field_width,
            self._field_height,
            deployment.rows[Side.RED],
            deployment.rows[Side.BLUE],
            deployment.columns[Side.RED],
            deployment.columns[Side.BLUE],
        )
        if logger.isEnabledFor(logging.DEBUG):
            for soldier in self._soldiers:
                logger.debug(
                    "2D spawn session=%s tick=%d agent=%d side=%s unit=%s "
                    "pos=(%.3f,%.3f) hp=%.1f ranged=%s melee=%s",
                    self.session_id,
                    self._tick,
                    soldier.id,
                    soldier.side.value,
                    soldier.name,
                    soldier.x,
                    soldier.y,
                    soldier.hp,
                    soldier.has_ranged,
                    soldier.has_melee,
                )

    def _emit(
        self,
        event_type: EventType,
        data: dict[str, Any] | None = None,
    ) -> None:
        payload = dict(data or {})
        payload.setdefault("engine", "2d")
        event = BattleEvent(
            tick=self._tick,
            time=self._tick * self.config.tick_interval,
            event_type=event_type,
            data=payload,
        )
        self._events.append(event)
        if self._frame_callback is not None:
            visual_event = self._visual_event(event)
            if visual_event is not None:
                self._pending_visual_events.append(visual_event)

    def _visual_event(self, event: BattleEvent) -> dict[str, Any] | None:
        """Translate one battle event into a display event for the live viewer.

        The battle event remains the source of truth.  This helper only
        resolves the event's world position and attaches its display lifetime.
        """
        lifetime = VISUAL_EVENT_LIFETIMES.get(event.event_type)
        if lifetime is None:
            return None

        event_data = event.data
        if event.event_type == EventType.ATTACK:
            if event_data.get("is_splash"):
                return None
            attacker = self._soldier_map.get(int(event_data.get("attacker_id", -1)))
            target = self._soldier_map.get(int(event_data.get("target_id", -1)))
            if attacker is None or target is None:
                return None
            payload = {
                "type": "attack",
                "attacker_id": attacker.id,
                "target_id": target.id,
                "mode": event_data.get("mode"),
                "attacker_x": round(attacker.x, 3),
                "attacker_y": round(attacker.y, 3),
                "x": round(target.x, 3),
                "y": round(target.y, 3),
            }
        elif event.event_type == EventType.AOE_SPLASH:
            main_target = self._soldier_map.get(int(event_data.get("main_target_id", -1)))
            if main_target is None:
                return None
            group_id = ":".join(
                (
                    str(event.tick),
                    str(event_data.get("attacker_id")),
                    str(event_data.get("main_target_id")),
                )
            )
            payload = {
                "type": "aoe",
                "aoe_group_id": group_id,
                "splash_target_id": event_data.get("splash_target_id"),
                "x": round(main_target.x, 3),
                "y": round(main_target.y, 3),
                "radius": event_data.get("radius", 3.0),
            }
        else:
            target = self._soldier_map.get(int(event_data.get("soldier_id", -1)))
            if target is None:
                return None
            payload = {
                "type": "death",
                "unit_id": target.id,
                "x": round(target.x, 3),
                "y": round(target.y, 3),
            }

        payload["time"] = round(event.time, 3)
        payload["expires_at"] = round(event.time + lifetime, 3)
        return payload

    def _emit_visual_frame(
        self,
        *,
        status: str,
        winner: Side | None,
        timeout: bool,
    ) -> None:
        """Publish a read-only snapshot for the optional development renderer."""
        if self._frame_callback is None:
            return
        summary = self._current_summary
        sides = {side.value: self._side_visual_summary(side) for side in (Side.RED, Side.BLUE)}
        visual_events = self._pending_visual_events
        self._pending_visual_events = []
        self._frame_callback(
            {
                "engine": "2d",
                "collision_mode": self.config.collision_mode.value,
                "match_label": self.match_label,
                "status": status,
                "tick": self._tick,
                "time": round(self._tick * self.config.tick_interval, 3),
                "field": {
                    "width": round(self._field_width, 3),
                    "height": round(self._field_height, 3),
                },
                "winner": winner.value if winner is not None else None,
                "timeout": timeout,
                "visual_events": visual_events,
                "summary": {
                    "alive_red": summary.alive_red,
                    "alive_blue": summary.alive_blue,
                    "movers": summary.movers,
                    "attackers": summary.attackers,
                    "blocked": summary.blocked,
                    "wall_contacts": summary.wall_contacts,
                    "collision_pairs": summary.collision_pairs,
                    "max_overlap": round(summary.max_overlap, 4),
                    "avg_speed": round(summary.avg_speed, 3),
                    "solver_fallbacks": summary.solver_fallbacks,
                    "no_progress_units": int(summary.extra.get("no_progress_units", 0)),
                    "max_no_progress_ticks": int(summary.extra.get("max_no_progress_ticks", 0)),
                },
                "sides": sides,
                "units": [
                    {
                        "id": soldier.id,
                        "side": soldier.side.value,
                        "unit_id": soldier.unit.id,
                        "name": soldier.name,
                        "x": round(soldier.x, 3),
                        "y": round(soldier.y, 3),
                        "hp": round(soldier.hp, 1),
                        "max_hp": round(soldier.max_hp, 1),
                        "alive": soldier.alive,
                        "stopped": soldier.stopped,
                        "target_id": soldier.target_id,
                        "move_target_id": soldier.move_target_id,
                        "has_ranged": soldier.has_ranged,
                        "has_melee": soldier.has_melee,
                        "melee_range": soldier.effective_melee_range,
                        "ranged_range": soldier.effective_ranged_range,
                        "ranged_range_min": soldier.effective_ranged_range_min,
                        "attack_cd": round(
                            max(
                                0.0,
                                soldier.attack_ready_at - self._tick * self.config.tick_interval,
                            ),
                            3,
                        ),
                        "aim_cd": (
                            round(
                                max(
                                    0.0,
                                    soldier.aim_ready_at - self._tick * self.config.tick_interval,
                                ),
                                3,
                            )
                            if soldier.aim_ready_at is not None
                            else None
                        ),
                        "prepared_mode": soldier.prepared_mode.value
                        if soldier.prepared_mode is not None
                        else None,
                        "artillery_state": (
                            soldier.artillery_state.value if soldier.is_artillery else None
                        ),
                        "deploy_cd": (
                            round(
                                max(
                                    0.0,
                                    soldier.deploy_ready_at
                                    - self._tick * self.config.tick_interval,
                                ),
                                3,
                            )
                            if soldier.is_artillery
                            else None
                        ),
                        "kills": soldier.kills,
                        "damage": round(soldier.total_damage_dealt, 1),
                        "steer_reason": soldier.last_steer_reason,
                        "no_progress_ticks": soldier.no_progress_ticks,
                        "radius": unit_radius(soldier.unit, self.config.fallback_unit_radius),
                        "facing": soldier.facing,
                        "velocity": [round(soldier.velocity_x, 3), round(soldier.velocity_y, 3)],
                        "detour_sign": soldier.detour_sign,
                        "oscillating": soldier.oscillating,
                        "motion_stalled": soldier.motion_stalled,
                        "detour_replans": soldier.detour_replans,
                        "navigation_status": soldier.navigation_status,
                        "navigation_expanded": soldier.navigation_expanded,
                        "detour_shortcuts": soldier.detour_shortcuts,
                        "detour_path": (
                            [
                                [soldier.detour_waypoint_x, soldier.detour_waypoint_y],
                                *[[p.x, p.y] for p in soldier.detour_remaining],
                            ]
                            if soldier.detour_waypoint_x is not None
                            else []
                        ),
                    }
                    for soldier in self._soldiers
                    if soldier.alive
                ],
            }
        )

    def _side_visual_summary(self, side: Side) -> dict[str, Any]:
        alive = self._alive(side)
        stopped = sum(1 for soldier in alive if soldier.stopped)
        moving = len(alive) - stopped
        total_hp = sum(soldier.hp for soldier in alive)
        total_damage = sum(soldier.total_damage_dealt for soldier in alive)
        kills = sum(soldier.kills for soldier in alive)
        initial_hp = self.initial_total_hp[side]
        return {
            "side": side.value,
            "initial_count": (self.red_count if side == Side.RED else self.blue_count),
            "alive": len(alive),
            "dead": ((self.red_count if side == Side.RED else self.blue_count) - len(alive)),
            "stopped": stopped,
            "moving": moving,
            "total_hp": round(total_hp, 1),
            "total_max_hp": round(initial_hp, 1),
            "hp_ratio": round(total_hp / initial_hp, 4) if initial_hp > 0 else 0.0,
            "total_damage": round(total_damage, 1),
            "kills": kills,
            "composition": self._army_visual_summary(side),
        }

    def _army_visual_summary(self, side: Side) -> list[dict[str, Any]]:
        army = self.red_army if side == Side.RED else self.blue_army
        return [
            {
                "unit_id": slot.unit.id,
                "name": slot.unit.name or slot.unit.name_en,
                "count": slot.count,
            }
            for slot in army
        ]

    def _alive(self, side: Side | None = None) -> list[Soldier2D]:
        if side is None:
            return [soldier for soldier in self._soldiers if soldier.alive]
        return [soldier for soldier in self._soldiers if soldier.alive and soldier.side == side]

    def _nearest_enemy(self, soldier: Soldier2D) -> Soldier2D | None:
        assert self._combat is not None
        return self._combat.nearest_enemy(soldier)

    def _desired_velocity(self, soldier: Soldier2D) -> tuple[Vec2, Soldier2D | None]:
        if soldier.has_ranged and not soldier.has_melee and soldier.effective_ranged_range_min > 0:
            nearest = self._nearest_enemy(soldier)
            if (
                nearest is not None
                and soldier.distance_to(nearest) < soldier.effective_ranged_range_min
            ):
                self._clear_detour(soldier)
                soldier.motion_samples.clear()
                soldier.oscillating = soldier.motion_stalled = False
                soldier.move_target_id = nearest.id
                return Vec2(0.0, 0.0), nearest
        if soldier.oscillating or soldier.motion_stalled:
            self._clear_detour(soldier)
            soldier.motion_samples.clear()
            soldier.oscillating = False
            soldier.motion_stalled = False
            soldier.progress_goal = None
            candidates = self._spatial_hash.query_circle(
                soldier.pos,
                self.config.avoidance_radius * 2,
                predicate=lambda other: other.side != soldier.side,
            )
            candidates.sort(key=lambda other: soldier.distance_sq_to(other))
            reachable = next(
                (
                    other
                    for other in candidates[:8]
                    if route_clear(
                        soldier,
                        other.pos,
                        self._spatial_hash,
                        self.config,
                        target_id=other.id,
                        field=(self._field_width, self._field_height),
                    )
                ),
                None,
            )
            if reachable is not None:
                soldier.move_target_id = reachable.id
            soldier.blocked_target_id = soldier.move_target_id
            soldier.no_progress_ticks = self.config.blocked_window_ticks
            soldier.detour_retry_tick = self._tick
        if soldier.detour_target_id is not None:
            route_target = self._soldier_map.get(soldier.detour_target_id)
            if route_target is None or not route_target.alive:
                self._clear_detour(soldier)
                soldier.move_target_id = None
            elif (self._tick + soldier.id) % self.config.target_refresh_ticks == 0:
                self._shorten_detour(soldier, route_target)
        if soldier.detour_waypoint_x is not None:
            waypoint = Vec2(soldier.detour_waypoint_x, soldier.detour_waypoint_y or 0.0)
            direction = waypoint - soldier.pos
            if direction.length() <= 0.08:
                if soldier.detour_remaining:
                    waypoint = soldier.detour_remaining.pop(0)
                    soldier.detour_waypoint_x = waypoint.x
                    soldier.detour_waypoint_y = waypoint.y
                    soldier.no_progress_ticks = 0
                    direction = waypoint - soldier.pos
                    return direction.clamped_length(
                        soldier.unit.speed * self.config.tick_interval
                    ) / self.config.tick_interval, None
                self._clear_detour(soldier)
            elif soldier.no_progress_ticks >= self.config.detour_commit_ticks:
                self._clear_detour(soldier)
                soldier.detour_retry_tick = self._tick + self.config.blocked_window_ticks
            else:
                soldier.detour_active_ticks += 1
                return direction.clamped_length(
                    soldier.unit.speed * self.config.tick_interval
                ) / self.config.tick_interval, None

        target = None
        if soldier.move_target_id is not None:
            target = self._soldier_map.get(soldier.move_target_id)
            if target is None or not target.alive:
                soldier.move_target_id = None
                target = None
        if target is None:
            target = self._nearest_enemy(soldier)
            if target is None:
                return Vec2(0.0, 0.0), None
            soldier.move_target_id = target.id
            soldier.move_target_tick = self._tick

        if (
            soldier.no_progress_ticks >= self.config.blocked_window_ticks
            and soldier.blocked_target_id == target.id
            and self._tick >= soldier.detour_retry_tick
        ):
            route_status = self._set_detour_waypoint(soldier, target)
            if soldier.detour_waypoint_x is not None:
                waypoint = Vec2(soldier.detour_waypoint_x, soldier.detour_waypoint_y)
                return (waypoint - soldier.pos).normalized() * soldier.unit.speed, target
            alternatives = self._spatial_hash.query_circle(
                soldier.pos,
                self.config.avoidance_radius * 2.0,
                predicate=lambda other: other.alive and other.side != soldier.side,
            )
            alternatives = [candidate for candidate in alternatives if candidate.id != target.id]
            if route_status in (RouteStatus.DIRECT, RouteStatus.BUDGET_EXHAUSTED):
                alternatives = []
            alternatives.sort(key=lambda candidate: soldier.distance_sq_to(candidate))
            alternatives = [
                candidate
                for candidate in alternatives[:8]
                if route_clear(
                    soldier,
                    candidate.pos,
                    self._spatial_hash,
                    self.config,
                    target_id=candidate.id,
                    field=(self._field_width, self._field_height),
                )
            ]
            if alternatives:

                def target_score(candidate: Soldier2D) -> tuple[int, float, int]:
                    crowd = self._spatial_hash.query_circle(
                        candidate.pos,
                        unit_radius(
                            candidate.unit,
                            self.config.fallback_unit_radius,
                        )
                        * 3.5,
                        predicate=lambda other: other.alive and other.side == soldier.side,
                    )
                    return (
                        len(crowd),
                        soldier.distance_sq_to(candidate),
                        candidate.id,
                    )

                alternatives.sort(key=target_score)
                target = alternatives[0]
                soldier.move_target_id = target.id
                soldier.blocked_target_id = None
                soldier.no_progress_ticks = 0
        elif soldier.no_progress_ticks <= 1:
            soldier.blocked_target_id = target.id

        direction = Vec2(target.x - soldier.x, target.y - soldier.y)
        distance = direction.length()
        if distance <= 1e-9:
            return Vec2(0.0, 0.0), target

        assert self._combat is not None
        if self._combat.determine_attack_mode(soldier, target) is not None:
            return Vec2(0.0, 0.0), target
        if (
            soldier.has_ranged
            and not soldier.has_melee
            and distance < soldier.effective_ranged_range_min
        ):
            return Vec2(0.0, 0.0), target
        desired_distance = self._approach_range(soldier, target)

        if self._tick >= soldier.detour_retry_tick:
            lookahead = soldier.pos + direction.normalized() * min(
                distance, self.config.avoidance_radius
            )
            blockers = self._spatial_hash.query_circle(
                soldier.pos,
                self.config.avoidance_radius,
                predicate=lambda other: other.stopped and other.id not in (soldier.id, target.id),
            )
            if any(
                segment_distance_sq(soldier.pos, lookahead, other.pos)
                < (
                    unit_bounding_radius(soldier.unit, self.config.fallback_unit_radius)
                    + unit_bounding_radius(other.unit, self.config.fallback_unit_radius)
                )
                ** 2
                for other in blockers
            ):
                self._set_detour_waypoint(soldier, target)
                if soldier.detour_waypoint_x is not None:
                    waypoint = Vec2(soldier.detour_waypoint_x, soldier.detour_waypoint_y)
                    return (waypoint - soldier.pos).normalized() * soldier.unit.speed, target
        heading = direction.normalized()
        # Do not brake over the avoidance horizon. Clip only the last tick's
        # travel to the attack envelope; collision prediction models that stop.
        arrival_speed = max(
            0.0,
            (distance - desired_distance + self.config.stop_check_slack)
            / self.config.tick_interval,
        )
        return heading * min(soldier.unit.speed, arrival_speed), target

    def _approach_range(self, soldier: Soldier2D, target: Soldier2D) -> float:
        if soldier.has_ranged and soldier.distance_to(target) > soldier.effective_ranged_range:
            return soldier.effective_ranged_range
        return soldier.effective_melee_range

    def _shorten_detour(self, soldier: Soldier2D, target: Soldier2D) -> None:
        if soldier.detour_waypoint_x is None:
            return
        if route_clear(
            soldier,
            target.pos,
            self._spatial_hash,
            self.config,
            target_id=target.id,
            field=(self._field_width, self._field_height),
        ):
            self._clear_detour(soldier)
            soldier.detour_shortcuts += 1
            return
        for index in range(len(soldier.detour_remaining) - 1, -1, -1):
            point = soldier.detour_remaining[index]
            if route_clear(
                soldier,
                point,
                self._spatial_hash,
                self.config,
                target_id=target.id,
                field=(self._field_width, self._field_height),
            ):
                soldier.detour_waypoint_x, soldier.detour_waypoint_y = point.x, point.y
                soldier.detour_remaining = soldier.detour_remaining[index + 1 :]
                soldier.detour_shortcuts += 1
                soldier.no_progress_ticks = 0
                break

    def _set_detour_waypoint(
        self,
        soldier: Soldier2D,
        target: Soldier2D,
    ) -> RouteStatus:
        if soldier.navigation_target_id != target.id:
            soldier.navigation_retry_level = 0
            soldier.navigation_target_id = target.id
        search = search_detour(
            soldier,
            target,
            self._spatial_hash,
            self.config,
            self._field_width,
            self._field_height,
            arrival_distance=self._approach_range(soldier, target),
            expansion_budget=self.config.navigation_max_expansions
            * (1 + soldier.navigation_retry_level),
        )
        previous_status = soldier.navigation_status
        soldier.navigation_status = search.status.value
        soldier.navigation_expanded = search.expanded
        soldier.navigation_retry_level = 1 if search.status == RouteStatus.BUDGET_EXHAUSTED else 0
        soldier.detour_retry_tick = self._tick + self.config.blocked_window_ticks
        if search.status == RouteStatus.BUDGET_EXHAUSTED:
            soldier.detour_retry_tick += self.config.blocked_window_ticks
        if search.status != previous_status and search.status not in (
            RouteStatus.FOUND,
            RouteStatus.DIRECT,
        ):
            logger.debug(
                "2d-navigation session=%s tick=%d unit=%d target=%d status=%s expanded=%d",
                self.session_id,
                self._tick,
                soldier.id,
                target.id,
                search.status.value,
                search.expanded,
            )
        plan = search.plan
        if plan is None:
            return search.status
        waypoint, *remaining = plan.points
        soldier.detour_sign = plan.sign
        soldier.detour_waypoint_x = waypoint.x
        soldier.detour_waypoint_y = waypoint.y
        soldier.detour_remaining = remaining
        soldier.detour_target_id = target.id
        soldier.detour_active_ticks = 0
        soldier.detour_ticks = self.config.detour_commit_ticks
        soldier.no_progress_ticks = 0
        soldier.detour_replans += 1
        direct = soldier.distance_to(target)
        if (
            plan.cost > direct * 3
            and plan.cost - direct > 4
            and self._tick - soldier.last_motion_log_tick >= 50
        ):
            logger.warning(
                "2d-motion long-route session=%s tick=%d unit=%d direct=%.2f route=%.2f",
                self.session_id,
                self._tick,
                soldier.id,
                direct,
                plan.cost,
            )
            soldier.last_motion_log_tick = self._tick
        return search.status

    def _clear_detour(self, soldier: Soldier2D) -> None:
        soldier.detour_waypoint_x = None
        soldier.detour_waypoint_y = None
        soldier.detour_remaining.clear()
        soldier.detour_target_id = None
        soldier.detour_active_ticks = 0
        soldier.no_progress_ticks = 0
        soldier.blocked_target_id = None

    def _process_movement(self) -> TickSummary:
        alive = self._alive()
        tick_starts = {s.id: s.pos for s in alive}
        self._spatial_hash.rebuild(alive)
        decisions: list[dict[str, Any]] = []
        movers = 0
        blocked = 0
        attackers = 0
        wall_contacts = 0
        solver_fallbacks = 0
        speed_total = 0.0

        move_order = list(alive)
        self._rng.shuffle(move_order)
        desired_velocities: dict[int, Vec2] = {}
        arrival_zones: dict[int, tuple[Vec2, float]] = {}
        steering = {}

        for soldier in alive:
            if soldier.artillery_state == ArtilleryState.DEPLOYING:
                desired_velocities[soldier.id] = Vec2(0.0, 0.0)
                continue
            if not soldier.stopped:
                desired, target = self._desired_velocity(soldier)
                desired_velocities[soldier.id] = desired
                if target is not None and soldier.detour_waypoint_x is None:
                    arrival_zones[soldier.id] = (
                        target.pos,
                        max(
                            0.0,
                            self._approach_range(soldier, target) - self.config.stop_check_slack,
                        ),
                    )
                elif soldier.detour_waypoint_x is not None:
                    arrival_zones[soldier.id] = (
                        Vec2(soldier.detour_waypoint_x, soldier.detour_waypoint_y),
                        0.0,
                    )
                if desired_velocities[soldier.id].length_sq() > 1e-8:
                    assert self._combat is not None
                    self._combat.interrupt_preparation(soldier)

        for soldier in move_order:
            if not soldier.alive:
                continue
            if soldier.stopped:
                soldier.velocity_x = 0.0
                soldier.velocity_y = 0.0
                soldier.motion_samples.clear()
                soldier.oscillating = False
                soldier.motion_stalled = False
                soldier.progress_goal = None
                continue

            desired = desired_velocities.get(soldier.id, Vec2(0.0, 0.0))
            soldier.detour_ticks = max(0, soldier.detour_ticks - 1)

            steering[soldier.id] = self._movement.choose_velocity(
                soldier,
                desired,
                field_width=self._field_width,
                field_height=self._field_height,
                blocked_ticks=soldier.no_progress_ticks,
                arrival_zone=arrival_zones.get(soldier.id),
            )

        for soldier in move_order:
            if soldier.id not in steering:
                continue
            result = steering[soldier.id]
            soldier.previous_velocity_x = soldier.velocity_x
            soldier.previous_velocity_y = soldier.velocity_y
            soldier.velocity_x = result.velocity.x
            soldier.velocity_y = result.velocity.y
            soldier.last_steer_reason = (
                "detour" if soldier.detour_waypoint_x is not None else result.reason
            )
            if (
                result.reason == "desired_zero"
                and soldier.has_ranged
                and not soldier.has_melee
                and soldier.move_target_id in self._soldier_map
                and soldier.distance_to(self._soldier_map[soldier.move_target_id])
                < soldier.effective_ranged_range_min
            ):
                soldier.last_steer_reason = "minimum_range"
            if result.reason.startswith(("avoid", "fallback", "detour")):
                blocked += 1
            if result.reason == "fallback" or result.reason == "solver_empty":
                solver_fallbacks += 1
            if result.wall_contact:
                wall_contacts += 1
            if result.velocity.length_sq() > 1e-8:
                movers += 1
                speed_total += result.velocity.length()

            if logger.isEnabledFor(logging.DEBUG) and (
                self._tick % self.config.trace_agent_sample_every_ticks == 0
                or result.reason in ("fallback", "solver_empty")
            ):
                decisions.append(self._decision_record(soldier, result))

        self._integrate_movement(alive, move_order, steering)
        # Movement integration changed coordinates, so the collision resolver
        # below needs a fresh index.  Stopped units are treated as fixed
        # obstacles by the resolver itself.
        self._spatial_hash.rebuild(alive)
        resolution = self._collisions.resolve(
            alive,
            field_width=self._field_width,
            field_height=self._field_height,
        )
        self._spatial_hash.rebuild(alive)

        for soldier in alive:
            delta = soldier.pos - tick_starts[soldier.id]
            soldier.velocity_x = delta.x / self.config.tick_interval
            soldier.velocity_y = delta.y / self.config.tick_interval

        if (
            resolution.max_overlap > self.config.max_overlap_for_log
            and self._tick % self.config.trace_summary_every_ticks == 0
        ):
            logger.warning(
                "2D overlap session=%s tick=%d residual_max=%.4f "
                "residual_pairs=%d corrections=%d "
                "details=%s",
                self.session_id,
                self._tick,
                resolution.max_overlap,
                resolution.residual_pairs,
                resolution.corrections,
                resolution.details[:8],
            )

        summary = TickSummary(
            tick=self._tick,
            alive_red=len(self._alive(Side.RED)),
            alive_blue=len(self._alive(Side.BLUE)),
            movers=movers,
            attackers=attackers,
            blocked=blocked,
            wall_contacts=wall_contacts,
            collision_pairs=resolution.residual_pairs,
            max_overlap=resolution.max_overlap,
            avg_speed=speed_total / movers if movers else 0.0,
            solver_fallbacks=solver_fallbacks,
            extra={
                "collision_corrections": resolution.corrections,
                "initial_max_overlap": resolution.initial_max_overlap,
                "no_progress_units": sum(1 for soldier in alive if soldier.no_progress_ticks > 0),
                "max_no_progress_ticks": max(
                    (soldier.no_progress_ticks for soldier in alive),
                    default=0,
                ),
                "field_width": round(self._field_width, 2),
                "field_height": round(self._field_height, 2),
                "oscillating_units": sum(s.oscillating for s in alive),
                "detour_replans": sum(s.detour_replans for s in alive),
                "detour_shortcuts": sum(s.detour_shortcuts for s in alive),
            },
        )
        self._solver_fallbacks += solver_fallbacks
        self._current_summary = summary
        if logger.isEnabledFor(logging.DEBUG) and (
            self._tick % self.config.trace_summary_every_ticks == 0
            or resolution.max_overlap > self.config.max_overlap_for_log
        ):
            logger.debug(
                "2D tick session=%s tick=%d alive=%d/%d movers=%d blocked=%d "
                "wall=%d collisions=%d max_overlap=%.4f avg_speed=%.3f "
                "fallbacks=%d",
                self.session_id,
                self._tick,
                summary.alive_red,
                summary.alive_blue,
                summary.movers,
                summary.blocked,
                summary.wall_contacts,
                summary.collision_pairs,
                summary.max_overlap,
                summary.avg_speed,
                summary.solver_fallbacks,
            )
        self._trace.record_tick(
            self._tick,
            summary=summary,
            decisions=decisions,
            collision_details=resolution.details,
        )
        return summary

    def _decision_record(self, soldier: Soldier2D, result) -> dict[str, Any]:
        target = self._soldier_map.get(soldier.target_id) if soldier.target_id is not None else None
        return {
            "agent": soldier.id,
            "side": soldier.side.value,
            "unit": soldier.name,
            "state": "blocked" if soldier.no_progress_ticks else "advance",
            "pos": [round(soldier.x, 3), round(soldier.y, 3)],
            "velocity": [round(result.velocity.x, 3), round(result.velocity.y, 3)],
            "target": target.id if target is not None else None,
            "distance": (round(soldier.distance_to(target), 3) if target is not None else None),
            "reason": result.reason,
            "blocked_by": list(result.blocked_by),
            "ttc": (
                round(result.time_to_collision, 4) if result.time_to_collision is not None else None
            ),
            "angle": round(result.candidate_angle, 2),
            "requested_facing": result.facing,
            "turn_fraction": result.turn_fraction,
            "no_progress_ticks": soldier.no_progress_ticks,
        }

    def _integrate_movement(
        self,
        alive: list[Soldier2D],
        move_order: list[Soldier2D],
        commands: dict[int, SteeringResult] | None = None,
    ) -> None:
        substeps = max(1, self.config.movement_substeps)
        dt = self.config.tick_interval
        starts = {s.id: s.pos for s in move_order}
        motions = {}
        for soldier in move_order:
            shape = shape_for_unit(
                soldier.unit, soldier.x, soldier.y, soldier.facing, self.config.fallback_unit_radius
            )
            command = commands.get(soldier.id) if commands else None
            if command is not None and command.facing is not None:
                motions[soldier.id] = PoseMotion(
                    shape,
                    soldier.velocity_x * dt,
                    soldier.velocity_y * dt,
                    angle_delta(soldier.facing, command.facing),
                    command.turn_fraction,
                )
            else:
                heading = (
                    math.atan2(soldier.velocity_y, soldier.velocity_x)
                    if soldier.velocity.length_sq() > 1e-12
                    else soldier.facing
                )
                motions[soldier.id] = steering_motion(
                    shape,
                    soldier.velocity_x * dt,
                    soldier.velocity_y * dt,
                    heading,
                    dt,
                    self.config.movement_turn_rate,
                )
        halted = set()
        goals = {}
        for soldier in move_order:
            if soldier.detour_waypoint_x is not None:
                goals[soldier.id] = Vec2(soldier.detour_waypoint_x, soldier.detour_waypoint_y)
            elif soldier.move_target_id in self._soldier_map:
                goals[soldier.id] = self._soldier_map[soldier.move_target_id].pos
        for substep in range(substeps):
            for soldier in move_order:
                if not soldier.alive or soldier.stopped or soldier.id in halted:
                    continue
                previous = soldier.pos
                motion = motions[soldier.id]
                start, end = substep / substeps, (substep + 1) / substeps
                executed = self._execute_motion(soldier, motion, start, end)
                if executed < end - 1e-9:
                    halted.add(soldier.id)
                self._spatial_hash.update(soldier, previous)
        for soldier in move_order:
            if soldier.stopped or not soldier.alive or soldier.last_steer_reason == "minimum_range":
                continue
            if soldier.artillery_state == ArtilleryState.DEPLOYING:
                soldier.no_progress_ticks = 0
                soldier.motion_samples.clear()
                soldier.oscillating = False
                soldier.motion_stalled = False
                continue
            goal = goals.get(soldier.id)
            displacement = soldier.pos - starts[soldier.id]
            goal_key = (
                ("route", goal.x, goal.y)
                if soldier.detour_waypoint_x is not None
                else ("target", soldier.move_target_id)
            )
            distance = (soldier.pos - goal).length() if goal is not None else 0.0
            if goal is None:
                soldier.no_progress_ticks = (
                    0
                    if displacement.length() >= self.config.blocked_progress_epsilon
                    else soldier.no_progress_ticks + 1
                )
            elif goal_key != soldier.progress_goal:
                soldier.progress_goal = goal_key
                soldier.progress_best_distance = distance
                soldier.no_progress_ticks = 0
            elif distance < soldier.progress_best_distance - self.config.blocked_progress_epsilon:
                soldier.progress_best_distance = distance
                soldier.no_progress_ticks = 0
            else:
                soldier.no_progress_ticks += 1
            if soldier.no_progress_ticks == 0:
                soldier.last_progress_x = displacement.x / self.config.tick_interval
                soldier.last_progress_y = displacement.y / self.config.tick_interval
            soldier.motion_samples.append(soldier.pos)
            del soldier.motion_samples[: -self.config.progress_window_ticks - 1]
            samples = soldier.motion_samples
            soldier.oscillating = False
            soldier.motion_stalled = False
            if len(samples) >= 9:
                recent = samples[-9:]
                deltas = [b - a for a, b in pairwise(recent)]
                reversals = sum(a.dot(b) < -0.001 for a, b in pairwise(deltas))
                soldier.oscillating = (
                    reversals >= 4
                    and sum(d.length() for d in deltas) > 1.0
                    and (recent[-1] - recent[0]).length() < 0.5
                )
            if len(samples) > self.config.progress_window_ticks:
                path = sum((b - a).length() for a, b in pairwise(samples))
                net = (samples[-1] - samples[0]).length()
                soldier.oscillating = soldier.oscillating or (path > 1.5 and net < 0.6)
                soldier.motion_stalled = net < 0.2 and path <= 1.5
            if soldier.oscillating or soldier.motion_stalled:
                soldier.no_progress_ticks = max(
                    soldier.no_progress_ticks, self.config.blocked_window_ticks
                )
                if self._tick - soldier.last_motion_log_tick >= 50:
                    path = sum((b - a).length() for a, b in pairwise(samples))
                    net = (samples[-1] - samples[0]).length()
                    logger.warning(
                        "2d-motion %s session=%s tick=%d unit=%d target=%s path=%.2f net=%.2f route=%s navigation=%s expanded=%d",
                        "stall" if soldier.motion_stalled else "oscillation",
                        self.session_id,
                        self._tick,
                        soldier.id,
                        soldier.move_target_id,
                        path,
                        net,
                        soldier.detour_waypoint_x is not None,
                        soldier.navigation_status,
                        soldier.navigation_expanded,
                    )
                    soldier.last_motion_log_tick = self._tick

    def _execute_motion(
        self, soldier: Soldier2D, motion: PoseMotion, start: float, end: float
    ) -> float:
        """Execute the selected pose trajectory, clipping only if the scene changed."""
        destination = motion.at(end)
        nearby = self._spatial_hash.query_circle(
            soldier.pos,
            max(
                unit_radius(
                    soldier.unit,
                    self.config.fallback_unit_radius,
                )
                * 3.0,
                self.config.avoidance_radius,
                unit_bounding_radius(soldier.unit, self.config.fallback_unit_radius)
                + self.config.max_known_unit_radius,
            )
            + math.hypot(destination.x - soldier.x, destination.y - soldier.y),
            predicate=lambda other, soldier_id=soldier.id: other.id != soldier_id and other.alive,
        )
        obstacles = [
            shape_for_unit(
                other.unit, other.x, other.y, other.facing, self.config.fallback_unit_radius
            )
            for other in nearby
        ]

        def clear(fraction):
            return motion.clear(
                obstacles,
                start=start,
                end=fraction,
                field=(self._field_width, self._field_height),
                tolerance=self.config.separation_slop,
            )

        if not clear(end):
            low, high = start, end
            for _ in range(10):
                middle = (low + high) * 0.5
                if clear(middle):
                    low = middle
                else:
                    high = middle
            end = low
        pose = motion.at(end)
        soldier.x, soldier.y, soldier.facing = pose.x, pose.y, pose.angle
        return end

    def _refresh_stopped(self) -> None:
        assert self._combat is not None
        for soldier in self._alive():
            candidates = self._combat.attack_candidates(soldier)
            can_stop = self._combat.can_commit_to_attack(soldier, candidates)
            if can_stop and candidates:
                self._clear_detour(soldier)
                if not soldier.stopped:
                    soldier.stopped = True
                    soldier.move_target_id = None
                soldier.target_id = soldier.target_id or candidates[0].id
            else:
                soldier.stopped = False
                soldier.target_id = None

    def _process_artillery_states(self) -> None:
        """Advance the one-way Limber -> Deploying -> Deployed lifecycle."""
        assert self._combat is not None
        now = self._tick * self.config.tick_interval
        for soldier in self._alive():
            if not soldier.is_artillery:
                continue
            if soldier.artillery_state == ArtilleryState.DEPLOYING:
                if now + 1e-9 >= soldier.deploy_ready_at:
                    soldier.artillery_state = ArtilleryState.DEPLOYED
                continue
            if soldier.artillery_state != ArtilleryState.LIMBER:
                continue
            if self._combat.has_valid_target(soldier):
                soldier.artillery_state = ArtilleryState.DEPLOYING
                soldier.deploy_ready_at = now + soldier.unit.deploy_time
                soldier.stopped = False
                soldier.target_id = None
                self._combat.interrupt_preparation(soldier)

    def _apply_damage(
        self,
        attacker: Soldier2D,
        target: Soldier2D,
        damage: float,
        mode: AttackMode,
        *,
        is_splash: bool = False,
    ) -> None:
        old_hp = target.hp
        target.hp -= damage
        attacker.total_damage_dealt += damage
        damage_type = (
            attacker.unit.damage_type_melee
            if mode == AttackMode.MELEE
            else attacker.unit.damage_type_ranged
        ) or ("Hand" if mode == AttackMode.MELEE else "Ranged")

        self._emit(
            EventType.ATTACK,
            {
                "attacker_id": attacker.id,
                "attacker_name": attacker.name,
                "attacker_side": attacker.side.value,
                "attacker_unit_type": attacker.unit.type,
                "attacker_has_ranged": attacker.has_ranged,
                "target_id": target.id,
                "target_name": target.name,
                "target_side": target.side.value,
                "damage": round(damage, 1),
                "mode": mode.value,
                "damage_type": damage_type,
                "target_hp_before": round(old_hp, 1),
                "target_hp_after": round(max(0.0, target.hp), 1),
                "is_splash": is_splash,
            },
        )

        if target.hp <= 0:
            target.hp = 0.0
            target.alive = False
            attacker.kills += 1
            side_alive = len(self._alive(target.side))
            side_total = self.red_count if target.side == Side.RED else self.blue_count
            self._emit(
                EventType.DEATH,
                {
                    "soldier_id": target.id,
                    "soldier_name": target.name,
                    "soldier_unit_id": target.unit.id,
                    "side": target.side.value,
                    "killer_id": attacker.id,
                    "killer_name": attacker.name,
                    "killer_side": attacker.side.value,
                    "killer_unit_type": attacker.unit.type,
                    "killer_has_ranged": attacker.has_ranged,
                    "killer_attack_mode": mode.value,
                    "killer_damage_type": damage_type,
                    "remaining": side_alive,
                    "total": side_total,
                    "overkill": round(-target.hp + damage - old_hp, 1),
                },
            )
            logger.info(
                "2D death session=%s tick=%d target=%d side=%s killer=%d remaining=%d/%d",
                self.session_id,
                self._tick,
                target.id,
                target.side.value,
                attacker.id,
                side_alive,
                side_total,
            )
            for soldier in self._alive():
                if soldier.target_id == target.id:
                    soldier.target_id = None

    def _check_winner(self) -> Side | None:
        red_alive = len(self._alive(Side.RED))
        blue_alive = len(self._alive(Side.BLUE))
        if red_alive == 0 and blue_alive == 0:
            return None
        if red_alive == 0:
            return Side.BLUE
        if blue_alive == 0:
            return Side.RED
        return None

    def _timeout_winner(self) -> Side | None:
        if self.duel_mode:
            return None
        red_value = sum(
            sum(soldier.unit.cost.values()) + self.config.pop_house_cost * soldier.unit.pop
            for soldier in self._alive(Side.RED)
        )
        blue_value = sum(
            sum(soldier.unit.cost.values()) + self.config.pop_house_cost * soldier.unit.pop
            for soldier in self._alive(Side.BLUE)
        )
        if red_value > blue_value:
            return Side.RED
        if blue_value > red_value:
            return Side.BLUE
        return None

    def run(self) -> BattleResult:
        """Run the full simulation and return the shared result contract."""
        red_desc = " + ".join(f"{slot.unit.name}x{slot.count}" for slot in self.red_army)
        blue_desc = " + ".join(f"{slot.unit.name}x{slot.count}" for slot in self.blue_army)
        logger.info(
            "=== 2D battle start === session=%s seed=%s red=[%s](%d) blue=[%s](%d) max_ticks=%d",
            self.session_id,
            self.seed,
            red_desc,
            self.red_count,
            blue_desc,
            self.blue_count,
            self.config.max_ticks,
        )
        started = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            self._init_soldiers()
            self._emit(
                EventType.BATTLE_START,
                {
                    "red_army": [
                        {"name": slot.unit.name, "count": slot.count, "hp": slot.unit.hp}
                        for slot in self.red_army
                    ],
                    "blue_army": [
                        {"name": slot.unit.name, "count": slot.count, "hp": slot.unit.hp}
                        for slot in self.blue_army
                    ],
                    "red_count": self.red_count,
                    "blue_count": self.blue_count,
                    "field_length": self._field_width,
                    "field_width": self._field_width,
                    "field_height": self._field_height,
                    "engine": "2d",
                },
            )

            winner: Side | None = None
            timeout = False
            for tick in range(self.config.max_ticks):
                self._tick = tick
                self._process_artillery_states()
                self._refresh_stopped()
                summary = self._process_movement()
                assert self._combat is not None
                for soldier in self._alive():
                    self._combat.acquire_target(soldier)
                summary.attackers = self._combat.process_attacks(self._alive())
                winner = self._check_winner()
                self._emit_visual_frame(
                    status="running",
                    winner=winner,
                    timeout=False,
                )
                if winner is not None or (
                    len(self._alive(Side.RED)) == 0 and len(self._alive(Side.BLUE)) == 0
                ):
                    break
            else:
                timeout = True
                winner = self._timeout_winner()

            self._emit_visual_frame(
                status="finished",
                winner=winner,
                timeout=timeout,
            )

            duration = (self._tick + 1) * self.config.tick_interval
            self._emit(
                EventType.BATTLE_END,
                {
                    "winner": winner.value if winner else "draw",
                    "duration": round(duration, 1),
                    "ticks": self._tick + 1,
                    "timeout": timeout,
                    "red_alive": len(self._alive(Side.RED)),
                    "red_total": self.red_count,
                    "blue_alive": len(self._alive(Side.BLUE)),
                    "blue_total": self.blue_count,
                },
            )
            logger.info(
                "=== 2D battle end === session=%s winner=%s duration=%.1fs "
                "ticks=%d timeout=%s alive=%d/%d solver_fallbacks=%d",
                self.session_id,
                winner.value if winner else "draw",
                duration,
                self._tick + 1,
                timeout,
                len(self._alive(Side.RED)),
                len(self._alive(Side.BLUE)),
                self._solver_fallbacks,
            )
            return BattleResult(
                winner=winner,
                events=self._events,
                ticks=self._tick + 1,
                duration=duration,
                red_alive=self._alive(Side.RED),
                blue_alive=self._alive(Side.BLUE),
                red_dead=[
                    soldier
                    for soldier in self._soldiers
                    if not soldier.alive and soldier.side == Side.RED
                ],
                blue_dead=[
                    soldier
                    for soldier in self._soldiers
                    if not soldier.alive and soldier.side == Side.BLUE
                ],
                red_army=list(self.red_army),
                blue_army=list(self.blue_army),
                red_count=self.red_count,
                blue_count=self.blue_count,
                timeout=timeout,
            )
        except Exception as exc:
            logger.exception(
                "2D simulation failed session=%s tick=%d seed=%s",
                self.session_id,
                self._tick,
                self.seed,
            )
            self._trace.flush(
                reason="exception",
                context={
                    "timestamp": started,
                    "tick": self._tick,
                    "error": repr(exc),
                },
            )
            raise


def _ordered_formation_units(army: list[ArmySlot]) -> list[Unit]:
    units: list[Unit] = []
    for slot in sorted(
        army,
        key=lambda item: (item.unit.range, -item.unit.speed, item.unit.id),
    ):
        units.extend([slot.unit] * slot.count)
    return units
