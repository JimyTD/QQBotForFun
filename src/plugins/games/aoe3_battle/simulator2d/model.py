"""Data types used by the 2D battle engine."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from ....aoe3.models import Unit
from .compat import Side
from .geometry import unit_radius


class AttackMode(StrEnum):
    """The attack slot selected for one volley."""

    RANGED = "ranged"
    MELEE = "melee"


class ArtilleryState(StrEnum):
    """One-way artillery readiness state."""

    LIMBER = "limber"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"


@dataclass(frozen=True)
class Vec2:
    """Small immutable 2D vector."""

    x: float
    y: float

    def __add__(self, other: Vec2) -> Vec2:
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vec2:
        return Vec2(self.x * scalar, self.y * scalar)

    def __truediv__(self, scalar: float) -> Vec2:
        return Vec2(self.x / scalar, self.y / scalar)

    def dot(self, other: Vec2) -> float:
        return self.x * other.x + self.y * other.y

    def length_sq(self) -> float:
        return self.dot(self)

    def length(self) -> float:
        return math.sqrt(self.length_sq())

    def normalized(self) -> Vec2:
        length = self.length()
        if length <= 1e-12:
            return Vec2(0.0, 0.0)
        return self / length

    def rotated(self, radians: float) -> Vec2:
        c = math.cos(radians)
        s = math.sin(radians)
        return Vec2(self.x * c - self.y * s, self.x * s + self.y * c)

    def clamped_length(self, maximum: float) -> Vec2:
        length = self.length()
        if length <= maximum or length <= 1e-12:
            return self
        return self * (maximum / length)


@dataclass
class Soldier2D:
    """One independently simulated soldier."""

    id: int
    side: Side
    unit: Unit
    hp: float
    max_hp: float
    x: float
    y: float
    facing: float = 0.0
    attack_ready_at: float = 0.0
    aim_ready_at: float | None = None
    prepared_mode: AttackMode | None = None
    reconsider_attack_mode: bool = False
    artillery_state: ArtilleryState = ArtilleryState.LIMBER
    deploy_ready_at: float = 0.0
    target_id: int | None = None
    move_target_id: int | None = None
    move_target_tick: int = -1
    alive: bool = True
    stopped: bool = False
    total_damage_dealt: float = 0.0
    kills: int = 0

    velocity_x: float = 0.0
    velocity_y: float = 0.0
    previous_velocity_x: float = 0.0
    previous_velocity_y: float = 0.0
    last_progress_x: float = 0.0
    last_progress_y: float = 0.0
    no_progress_ticks: int = 0
    detour_sign: int = 1
    detour_ticks: int = 0
    blocked_target_id: int | None = None
    detour_waypoint_x: float | None = None
    detour_waypoint_y: float | None = None
    detour_active_ticks: int = 0
    detour_remaining: list[Vec2] = field(default_factory=list)
    detour_target_id: int | None = None
    detour_retry_tick: int = 0
    navigation_status: str = "unplanned"
    navigation_expanded: int = 0
    navigation_retry_level: int = 0
    navigation_target_id: int | None = None
    progress_goal: tuple | None = None
    progress_best_distance: float = float("inf")
    motion_samples: list[Vec2] = field(default_factory=list)
    oscillating: bool = False
    motion_stalled: bool = False
    last_motion_log_tick: int = -1000
    detour_replans: int = 0
    detour_shortcuts: int = 0
    last_steer_reason: str = "init"

    has_ranged: bool = False
    has_melee: bool = False
    effective_melee_range: float = 1.5
    effective_ranged_attack: float = 0.0
    effective_ranged_range: float = 0.0
    effective_ranged_rof: float = 0.0
    effective_ranged_range_min: float = 0.0

    @property
    def is_artillery(self) -> bool:
        return self.unit.has_limber_stance

    @property
    def can_attack(self) -> bool:
        return not self.is_artillery or self.artillery_state == ArtilleryState.DEPLOYED

    @property
    def speed_multiplier(self) -> float:
        if self.artillery_state == ArtilleryState.DEPLOYED:
            return self.unit.deployed_speed_multiplier
        return 1.0

    @property
    def effective_speed(self) -> float:
        return self.unit.speed * self.speed_multiplier

    @property
    def name(self) -> str:
        return self.unit.name or self.unit.name_en

    @property
    def hp_pct(self) -> float:
        return self.hp / self.max_hp if self.max_hp > 0 else 0.0

    @property
    def pos(self) -> Vec2:
        return Vec2(self.x, self.y)

    @property
    def velocity(self) -> Vec2:
        return Vec2(self.velocity_x, self.velocity_y)

    def distance_sq_to(self, other: Soldier2D) -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        return dx * dx + dy * dy

    def distance_to(self, other: Soldier2D) -> float:
        return math.sqrt(self.distance_sq_to(other))

    def radius(self, fallback: float) -> float:
        return unit_radius(self.unit, fallback)


@dataclass
class TickSummary:
    """Compact per-tick diagnostics."""

    tick: int
    alive_red: int
    alive_blue: int
    movers: int
    attackers: int
    blocked: int
    wall_contacts: int
    collision_pairs: int
    max_overlap: float
    avg_speed: float
    solver_fallbacks: int
    extra: dict[str, float | int | str] = field(default_factory=dict)
