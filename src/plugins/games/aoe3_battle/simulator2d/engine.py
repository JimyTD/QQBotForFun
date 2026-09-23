"""Independent 2D battle simulator that preserves the 1D public contract."""

from __future__ import annotations

import logging
import math
import random
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import Any

from src.plugins.aoe3.models import Unit

from .combat import CombatSystem
from .compat import ArmySlot, BattleEvent, BattleResult, EventType, Side
from .config import Simulation2DConfig
from .formation import build_deployment
from .model import AttackMode, Soldier2D, TickSummary, Vec2
from .movement import CollisionResolver, LocalAvoidance
from .spatial import SpatialHash
from .trace import FlightRecorder

logger = logging.getLogger("aoe3_battle.simulator2d")


class BattleSimulator2D:
    """2D replacement candidate for :class:`BattleSimulator`.

    It intentionally exposes the same constructor shape and ``run()`` result
    as the 1D implementation.  No production call site imports this class yet.
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
                    "field_length": (
                        base.field_length if field_length is None else field_length
                    ),
                    "max_ticks": base.max_ticks if max_ticks is None else max_ticks,
                    "row_spacing": (
                        base.row_spacing if row_spacing is None else row_spacing
                    ),
                    "max_columns": (
                        base.max_columns
                        if row_capacity is None
                        else max(base.min_columns, row_capacity)
                    ),
                }
            )
        self.config = base

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
        self.seed = seed
        self.session_id = session_id
        self.duel_mode = duel_mode
        self._rng = random.Random(seed)
        self._tick = 0
        self._events: list[BattleEvent] = []
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
        )
        soldier.has_ranged = unit.attack_ranged > 0 and unit.range > 0
        soldier.has_melee = unit.attack_melee > 0
        soldier.effective_melee_range = (
            unit.range_melee if soldier.has_melee and unit.range_melee > 0
            else self.config.melee_range
        )
        if soldier.has_ranged:
            soldier.effective_ranged_attack = unit.attack_ranged
            soldier.effective_ranged_range = unit.range
            soldier.effective_ranged_rof = (
                unit.rof_ranged
                if unit.rof_ranged > 0
                else self.config.default_rof_ranged
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
        self._events.append(
            BattleEvent(
                tick=self._tick,
                time=self._tick * self.config.tick_interval,
                event_type=event_type,
                data=payload,
            )
        )

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
        sides = {
            side.value: self._side_visual_summary(side)
            for side in (Side.RED, Side.BLUE)
        }
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
                    "no_progress_units": int(
                        summary.extra.get("no_progress_units", 0)
                    ),
                    "max_no_progress_ticks": int(
                        summary.extra.get("max_no_progress_ticks", 0)
                    ),
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
                        "attack_cd": round(soldier.attack_cd, 3),
                        "kills": soldier.kills,
                        "damage": round(soldier.total_damage_dealt, 1),
                        "steer_reason": soldier.last_steer_reason,
                        "no_progress_ticks": soldier.no_progress_ticks,
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
        total_max_hp = sum(soldier.max_hp for soldier in alive)
        total_damage = sum(soldier.total_damage_dealt for soldier in alive)
        kills = sum(soldier.kills for soldier in alive)
        return {
            "side": side.value,
            "initial_count": (
                self.red_count if side == Side.RED else self.blue_count
            ),
            "alive": len(alive),
            "dead": (
                (self.red_count if side == Side.RED else self.blue_count)
                - len(alive)
            ),
            "stopped": stopped,
            "moving": moving,
            "total_hp": round(total_hp, 1),
            "total_max_hp": round(total_max_hp, 1),
            "hp_ratio": round(total_hp / total_max_hp, 4)
            if total_max_hp > 0
            else 0.0,
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
        return [
            soldier
            for soldier in self._soldiers
            if soldier.alive and soldier.side == side
        ]

    def _nearest_enemy(self, soldier: Soldier2D) -> Soldier2D | None:
        assert self._combat is not None
        return self._combat.nearest_enemy(soldier)

    def _desired_velocity(self, soldier: Soldier2D) -> tuple[Vec2, Soldier2D | None]:
        if soldier.detour_waypoint_x is not None:
            waypoint = Vec2(soldier.detour_waypoint_x, soldier.detour_waypoint_y or 0.0)
            direction = waypoint - soldier.pos
            if direction.length() <= self.config.unit_radius * 1.2:
                soldier.detour_waypoint_x = None
                soldier.detour_waypoint_y = None
                soldier.detour_active_ticks = 0
                # Immediately reacquire the nearest reachable enemy; waiting
                # for the normal target refresh made exits feel sluggish.
                soldier.move_target_id = None
                soldier.blocked_target_id = None
                soldier.no_progress_ticks = 0
            elif soldier.detour_active_ticks > self.config.detour_commit_ticks * 2:
                soldier.detour_waypoint_x = None
                soldier.detour_waypoint_y = None
                soldier.detour_active_ticks = 0
                soldier.move_target_id = None
                soldier.blocked_target_id = None
            else:
                soldier.detour_active_ticks += 1
                return direction.normalized() * soldier.unit.speed, None

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
        ):
            self._set_detour_waypoint(soldier, target)
            alternatives = self._spatial_hash.query_circle(
                soldier.pos,
                self.config.avoidance_radius * 2.0,
                predicate=lambda other: (
                    other.alive and other.side != soldier.side
                ),
            )
            alternatives = [
                candidate
                for candidate in alternatives
                if candidate.id != target.id
            ]
            if alternatives:
                def target_score(candidate: Soldier2D) -> tuple[int, float, int]:
                    crowd = self._spatial_hash.query_circle(
                        candidate.pos,
                        self.config.unit_radius * 3.5,
                        predicate=lambda other: (
                            other.alive and other.side == soldier.side
                        ),
                    )
                    return (
                        len(crowd),
                        soldier.distance_sq_to(candidate),
                        candidate.id,
                    )

                alternatives.sort(
                    key=target_score
                )
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

        desired_distance = 0.0
        if soldier.has_ranged and not soldier.has_melee:
            desired_distance = max(
                soldier.effective_ranged_range_min,
                soldier.effective_ranged_range * 0.82,
            )
        elif soldier.has_ranged and soldier.has_melee:
            desired_distance = soldier.effective_melee_range * 0.85
        else:
            desired_distance = soldier.effective_melee_range * 0.85

        if distance <= max(desired_distance, soldier.effective_melee_range):
            return Vec2(0.0, 0.0), target

        return direction.normalized() * soldier.unit.speed, target

    def _set_detour_waypoint(
        self,
        soldier: Soldier2D,
        target: Soldier2D,
    ) -> None:
        """Choose a stable local waypoint around the blocking formation edge."""
        forward = Vec2(target.x - soldier.x, target.y - soldier.y).normalized()
        side_axis = Vec2(-forward.y, forward.x)
        # Project just beyond the nearby enemy/friendly crowd edge.
        nearby = self._spatial_hash.query_circle(
            soldier.pos,
            self.config.avoidance_radius * 1.8,
            predicate=lambda other: other.alive,
        )
        # Find the nearest blocker edge instead of a far-away lateral point.
        # The waypoint sits only just beyond the cluster edge, so the unit
        # brushes along the formation rather than running sideways first.
        candidates: list[tuple[int, int, float]] = []
        for sign in (1, -1):
            side = side_axis * sign
            lateral_values = [
                Vec2(other.x - soldier.x, other.y - soldier.y).dot(side)
                for other in nearby
                if Vec2(other.x - soldier.x, other.y - soldier.y).dot(forward)
                >= -0.5
            ]
            edge_lateral = (
                max(lateral_values)
                if sign > 0 and lateral_values
                else min(lateral_values)
                if lateral_values
                else 0.0
            )
            lateral_offset = edge_lateral + sign * (
                self.config.unit_radius * 4.0
            )
            # Deterministic alternating preference, with edge length as the
            # secondary criterion.  Pure nearest-edge geometry sends a whole
            # symmetric row to the same side.
            candidates.append(
                (
                    0 if sign == (1 if soldier.id % 2 == 0 else -1) else 1,
                    sign,
                    lateral_offset,
                )
            )

        _preference, soldier.detour_sign, lateral_offset = min(candidates)
        side = side_axis * soldier.detour_sign
        forward_offset = min(
            self.config.avoidance_radius,
            max(self.config.unit_radius * 1.0, abs(edge_lateral) * 0.15),
        )
        waypoint = soldier.pos + side * lateral_offset + forward * forward_offset
        soldier.detour_waypoint_x = waypoint.x
        soldier.detour_waypoint_y = waypoint.y
        soldier.detour_active_ticks = 0
        soldier.detour_ticks = self.config.detour_commit_ticks

    def _process_movement(self) -> TickSummary:
        alive = self._alive()
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

        for soldier in alive:
            if not soldier.stopped:
                desired_velocities[soldier.id] = self._desired_velocity(soldier)[0]

        for soldier in move_order:
            if not soldier.alive:
                continue
            if soldier.stopped:
                soldier.velocity_x = 0.0
                soldier.velocity_y = 0.0
                continue

            desired = desired_velocities.get(soldier.id, Vec2(0.0, 0.0))
            was_blocked = soldier.no_progress_ticks >= self.config.blocked_window_ticks
            if was_blocked:
                soldier.detour_ticks -= 1
                if soldier.detour_ticks <= 0:
                    soldier.detour_sign *= -1
                    soldier.detour_ticks = self.config.detour_commit_ticks

            result = self._movement.choose_velocity(
                soldier,
                desired,
                field_width=self._field_width,
                field_height=self._field_height,
                blocked_ticks=soldier.no_progress_ticks,
            )
            if soldier.detour_waypoint_x is not None:
                result = type(result)(
                    velocity=desired,
                    reason="detour",
                    blocked_by=result.blocked_by,
                    blocked_ticks=soldier.no_progress_ticks,
                    time_to_collision=None,
                    candidate_angle=0.0,
                    wall_contact=result.wall_contact,
                )
            soldier.previous_velocity_x = soldier.velocity_x
            soldier.previous_velocity_y = soldier.velocity_y
            soldier.velocity_x = result.velocity.x
            soldier.velocity_y = result.velocity.y
            soldier.last_steer_reason = result.reason
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
                decisions.append(
                    self._decision_record(soldier, result)
                )

        self._integrate_movement(alive, move_order)
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
                "no_progress_units": sum(
                    1 for soldier in alive if soldier.no_progress_ticks > 0
                ),
                "max_no_progress_ticks": max(
                    (soldier.no_progress_ticks for soldier in alive),
                    default=0,
                ),
                "field_width": round(self._field_width, 2),
                "field_height": round(self._field_height, 2),
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
        target = (
            self._soldier_map.get(soldier.target_id)
            if soldier.target_id is not None
            else None
        )
        return {
            "agent": soldier.id,
            "side": soldier.side.value,
            "unit": soldier.name,
            "state": "blocked" if soldier.no_progress_ticks else "advance",
            "pos": [round(soldier.x, 3), round(soldier.y, 3)],
            "velocity": [round(result.velocity.x, 3), round(result.velocity.y, 3)],
            "target": target.id if target is not None else None,
            "distance": (
                round(soldier.distance_to(target), 3)
                if target is not None
                else None
            ),
            "reason": result.reason,
            "blocked_by": list(result.blocked_by),
            "ttc": (
                round(result.time_to_collision, 4)
                if result.time_to_collision is not None
                else None
            ),
            "angle": round(result.candidate_angle, 2),
            "no_progress_ticks": soldier.no_progress_ticks,
        }

    def _integrate_movement(
        self,
        alive: list[Soldier2D],
        move_order: list[Soldier2D],
    ) -> None:
        substeps = max(1, self.config.movement_substeps)
        dt = self.config.tick_interval / substeps
        radius = self.config.unit_radius
        for _ in range(substeps):
            for soldier in move_order:
                if not soldier.alive or soldier.stopped:
                    continue
                start_x = soldier.x
                start_y = soldier.y
                proposed_x = soldier.x + soldier.velocity_x * dt
                proposed_y = soldier.y + soldier.velocity_y * dt
                blocked_x, blocked_y = self._blocked_axis_components(
                    soldier,
                    proposed_x,
                    proposed_y,
                )
                proposed_x = soldier.x + blocked_x * dt
                proposed_y = soldier.y + blocked_y * dt
                soldier.x = proposed_x
                soldier.y = proposed_y
                soldier.x = min(max(soldier.x, radius), self._field_width - radius)
                soldier.y = min(max(soldier.y, radius), self._field_height - radius)
                progress = math.hypot(soldier.x - start_x, soldier.y - start_y)
                if progress < self.config.blocked_progress_epsilon:
                    soldier.no_progress_ticks += 1
                else:
                    soldier.no_progress_ticks = 0
                    soldier.last_progress_x = soldier.velocity_x
                    soldier.last_progress_y = soldier.velocity_y

    def _blocked_axis_components(
        self,
        soldier: Soldier2D,
        proposed_x: float,
        proposed_y: float,
    ) -> tuple[float, float]:
        """Return movement components that do not impose overlap on neighbours."""
        if soldier.detour_waypoint_x is not None:
            waypoint = Vec2(
                soldier.detour_waypoint_x,
                soldier.detour_waypoint_y or 0.0,
            )
            direction = (waypoint - soldier.pos).normalized() * soldier.unit.speed
            return direction.x, direction.y

        minimum = self.config.unit_radius * 2.0
        nearby = self._spatial_hash.query_circle(
            soldier.pos,
            self.config.unit_radius * 3.0,
            predicate=lambda other, soldier_id=soldier.id: (
                other.id != soldier_id and other.alive
            ),
        )
        if not nearby:
            return soldier.velocity_x, soldier.velocity_y

        vx = soldier.velocity_x
        vy = soldier.velocity_y
        # Try the full step, axis-separated sliding, and a tangent projection.
        # The tangent projection is important when the blocker is not aligned
        # with the world axes: it preserves useful lateral motion instead of
        # freezing both components.
        blocking = min(
            nearby,
            key=lambda other: (
                (soldier.x + vx * self.config.tick_interval - other.x) ** 2
                + (soldier.y + vy * self.config.tick_interval - other.y) ** 2
            ),
        )
        normal = Vec2(soldier.x - blocking.x, soldier.y - blocking.y).normalized()
        tangent_velocity = Vec2(vx, vy) - normal * Vec2(vx, vy).dot(normal)
        if tangent_velocity.length_sq() < 1e-8:
            tangent_velocity = Vec2(-normal.y, normal.x) * soldier.unit.speed
            tangent_velocity = tangent_velocity * soldier.detour_sign
        for candidate_x, candidate_y in (
            (vx, vy),
            (vx, 0.0),
            (0.0, vy),
            (tangent_velocity.x, tangent_velocity.y),
            (0.0, 0.0),
        ):
            x = soldier.x + candidate_x * (self.config.tick_interval / 2.0)
            y = soldier.y + candidate_y * (self.config.tick_interval / 2.0)
            if all(
                (x - other.x) ** 2 + (y - other.y) ** 2
                >= (minimum - self.config.separation_slop) ** 2
                for other in nearby
            ):
                return candidate_x, candidate_y
        return 0.0, 0.0

    def _refresh_stopped(self) -> None:
        assert self._combat is not None
        for soldier in self._alive():
            if soldier.detour_waypoint_x is not None:
                soldier.stopped = False
                soldier.target_id = None
                continue
            candidates = self._combat.attack_candidates(soldier)
            can_stop = self._combat.can_commit_to_attack(soldier, candidates)
            if can_stop and not soldier.stopped:
                blockers = self._spatial_hash.query_circle(
                    soldier.pos,
                    self.config.unit_radius * 3.2,
                    predicate=lambda other, soldier_id=soldier.id, side=soldier.side: (
                        other.id != soldier_id
                        and other.stopped
                        and other.side != side
                    ),
                )
                if blockers:
                    nearest_blocker = min(
                        blockers,
                        key=lambda item: item.distance_sq_to(soldier),
                    )
                    separation = soldier.distance_to(nearest_blocker)
                    can_stop = separation >= self.config.unit_radius * 1.9
                    if can_stop and len(blockers) >= 3:
                        can_stop = separation >= self.config.unit_radius * 2.7
            if can_stop and candidates:
                if not soldier.stopped:
                    soldier.stopped = True
                    soldier.move_target_id = None
                    if soldier.has_melee and soldier.distance_to(candidates[0]) <= (
                        soldier.effective_melee_range
                    ):
                        soldier.attack_cd = soldier.unit.windup_melee
                    else:
                        soldier.attack_cd = soldier.unit.windup_ranged
                soldier.target_id = soldier.target_id or candidates[0].id
            else:
                soldier.stopped = False
                soldier.target_id = None

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
            side_total = (
                self.red_count if target.side == Side.RED else self.blue_count
            )
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
                "2D death session=%s tick=%d target=%d side=%s killer=%d "
                "remaining=%d/%d",
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
            sum(soldier.unit.cost.values())
            + self.config.pop_house_cost * soldier.unit.pop
            for soldier in self._alive(Side.RED)
        )
        blue_value = sum(
            sum(soldier.unit.cost.values())
            + self.config.pop_house_cost * soldier.unit.pop
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
            "=== 2D battle start === session=%s seed=%s red=[%s](%d) "
            "blue=[%s](%d) max_ticks=%d",
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
                    len(self._alive(Side.RED)) == 0
                    and len(self._alive(Side.BLUE)) == 0
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
