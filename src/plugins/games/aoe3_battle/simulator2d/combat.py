"""Data-driven attack eligibility and damage in the 2D battlefield."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .aoe import resolve_aoe
from .compat import EventType
from .config import Simulation2DConfig
from .model import AttackMode, Soldier2D
from .spatial import SpatialHash

logger = logging.getLogger("aoe3_battle.simulator2d.combat")


@dataclass(frozen=True)
class SlotStats:
    slot: str
    base_damage: float
    num_projectiles: int
    multipliers: list
    damage_type: str
    aoe_radius: int
    damage_cap_proto: float
    area_sort_mode: str
    outer_damage_area_distance: float
    outer_damage_area_factor: float


def combat_slot_stats(unit, mode: AttackMode) -> SlotStats | None:
    """Map an attack mode to the unit's ranged/melee data slot."""
    if mode == AttackMode.MELEE:
        return SlotStats(
            slot="melee",
            base_damage=unit.attack_melee,
            num_projectiles=unit.num_projectiles_melee,
            multipliers=unit.multipliers_melee,
            damage_type=unit.damage_type_melee,
            aoe_radius=unit.aoe_radius_melee,
            damage_cap_proto=unit.damage_cap_melee,
            area_sort_mode=unit.area_sort_mode_melee,
            outer_damage_area_distance=unit.outer_damage_area_distance_melee,
            outer_damage_area_factor=unit.outer_damage_area_factor_melee,
        )
    if mode == AttackMode.RANGED:
        return SlotStats(
            slot="ranged",
            base_damage=unit.attack_ranged,
            num_projectiles=unit.num_projectiles_ranged,
            multipliers=unit.multipliers_ranged,
            damage_type=unit.damage_type_ranged,
            aoe_radius=unit.aoe_radius_ranged,
            damage_cap_proto=unit.damage_cap_ranged,
            area_sort_mode=unit.area_sort_mode_ranged,
            outer_damage_area_distance=unit.outer_damage_area_distance_ranged,
            outer_damage_area_factor=unit.outer_damage_area_factor_ranged,
        )
    return None


def armor_for_damage_type(damage_type: str, target: Soldier2D) -> float:
    if damage_type == "Siege":
        return target.unit.armor_siege
    if damage_type == "Hand":
        return target.unit.armor_melee
    if damage_type == "Ranged":
        return target.unit.armor_ranged
    return target.unit.armor_ranged


def calc_multiplier(multipliers: list, target: Soldier2D) -> float:
    if not multipliers or not target.unit.type:
        return 1.0
    target_types = {item.lower() for item in target.unit.type}
    result = 1.0
    for multiplier in multipliers:
        clean = multiplier.vs.rstrip(" *").lower()
        if clean in target_types:
            result *= multiplier.value
    return result


class CombatSystem:
    """2D target acquisition, volley resolution, and circular AOE."""

    def __init__(
        self,
        *,
        config: Simulation2DConfig,
        rng,
        spatial_hash: SpatialHash,
        soldier_map: dict[int, Soldier2D],
        emit,
        tick_getter,
        damage_callback,
        field_width: float,
        field_height: float,
    ) -> None:
        self.config = config
        self.rng = rng
        self.spatial_hash = spatial_hash
        self.soldier_map = soldier_map
        self.emit = emit
        self.tick_getter = tick_getter
        self.damage_callback = damage_callback
        self.field_width = field_width
        self.field_height = field_height

    @property
    def now(self) -> float:
        return self.tick_getter() * self.config.tick_interval

    def interrupt_preparation(self, soldier: Soldier2D) -> None:
        """A movement command cancels preparation, never the weapon cooldown."""
        soldier.aim_ready_at = None
        soldier.prepared_mode = None
        soldier.reconsider_attack_mode = False
        soldier.target_id = None

    def is_mode_valid(
        self,
        soldier: Soldier2D,
        target: Soldier2D,
        mode: AttackMode,
    ) -> bool:
        if not target.alive or target.side == soldier.side:
            return False
        distance = soldier.distance_to(target)
        if mode == AttackMode.MELEE:
            return soldier.has_melee and distance <= soldier.effective_melee_range
        return (
            soldier.has_ranged
            and soldier.effective_ranged_range_min <= distance <= soldier.effective_ranged_range
        )

    def prepare_attack(self, soldier: Soldier2D, target: Soldier2D) -> AttackMode | None:
        mode = soldier.prepared_mode
        # Keep the selected action through aiming and the ROF wait. Reconsider
        # after a shot or when that action is no longer legal, not on range jitter.
        if (
            mode is None
            or soldier.reconsider_attack_mode
            or not self.is_mode_valid(soldier, target, mode)
        ):
            mode = self.determine_attack_mode(soldier, target)
        if mode is None:
            return None
        if soldier.prepared_mode != mode or soldier.aim_ready_at is None:
            windup = (
                soldier.unit.windup_melee
                if mode == AttackMode.MELEE
                else soldier.unit.windup_ranged
            )
            soldier.prepared_mode = mode
            soldier.aim_ready_at = self.now + max(0.0, windup)
        soldier.reconsider_attack_mode = False
        return mode

    def attack_candidates(self, soldier: Soldier2D) -> list[Soldier2D]:
        """Return living enemies currently inside a legal attack envelope."""
        if not soldier.has_ranged and not soldier.has_melee:
            return []
        radius = max(
            soldier.effective_ranged_range if soldier.has_ranged else 0.0,
            soldier.effective_melee_range if soldier.has_melee else 0.0,
        )
        if radius <= 0:
            return []

        enemies = self.spatial_hash.query_circle(
            soldier.pos,
            radius + self.config.stop_check_slack,
            predicate=lambda other: other.alive and other.side != soldier.side,
        )
        result: list[Soldier2D] = []
        for enemy in enemies:
            if self.determine_attack_mode(soldier, enemy) is not None:
                result.append(enemy)
        result.sort(key=lambda item: (item.distance_sq_to(soldier), item.id))
        return result

    def can_commit_to_attack(
        self,
        soldier: Soldier2D,
        candidates: list[Soldier2D] | None = None,
    ) -> bool:
        """Return whether stopping now leads to a usable attack cycle.

        Ranged units may stop at their firing envelope.  A melee-capable unit
        should not freeze merely because a distant enemy is technically inside
        its ranged maximum; it should keep advancing until a real attack mode
        is available.
        """
        candidates = candidates if candidates is not None else self.attack_candidates(soldier)
        if not candidates:
            return False
        if soldier.has_melee and not soldier.has_ranged:
            return any(
                soldier.distance_to(target) <= soldier.effective_melee_range
                for target in candidates
            )
        return True

    def nearest_enemy(self, soldier: Soldier2D) -> Soldier2D | None:
        """Find the nearest living enemy without scanning the whole battlefield."""
        best: Soldier2D | None = None
        radius = self.config.nearest_search_min_radius
        max_radius = max(
            self.field_width,
            self.field_height,
            self.config.nearest_search_max_radius,
        )
        while radius <= max_radius:
            candidates = self.spatial_hash.query_circle(
                soldier.pos,
                radius,
                predicate=lambda other: other.alive and other.side != soldier.side,
            )
            if candidates:
                candidates.sort(key=lambda item: (item.distance_sq_to(soldier), item.id))
                best = candidates[0]
                break
            radius *= 2.0

        return best

    def acquire_target(self, soldier: Soldier2D) -> None:
        if not soldier.stopped:
            soldier.target_id = None
            return
        if soldier.stopped and soldier.target_id is not None:
            existing = self.soldier_map.get(soldier.target_id)
            if (
                existing is not None
                and existing.alive
                and self.determine_attack_mode(soldier, existing) is not None
            ):
                self.prepare_attack(soldier, existing)
                return

        candidates = self.attack_candidates(soldier)
        if not candidates:
            soldier.target_id = None
            return
        target = candidates[0]
        soldier.target_id = target.id
        self.prepare_attack(soldier, target)
        self.emit(
            EventType.TARGET_LOCK,
            {
                "soldier_id": soldier.id,
                "soldier_name": soldier.name,
                "side": soldier.side.value,
                "target_id": target.id,
                "target_name": target.name,
                "distance": round(soldier.distance_to(target), 2),
                "engine": "2d",
            },
        )

    def determine_attack_mode(
        self,
        soldier: Soldier2D,
        target: Soldier2D,
    ) -> AttackMode | None:
        if self.is_mode_valid(soldier, target, AttackMode.MELEE):
            return AttackMode.MELEE
        if self.is_mode_valid(soldier, target, AttackMode.RANGED):
            return AttackMode.RANGED

        return None

    def calc_damage(
        self,
        attacker: Soldier2D,
        target: Soldier2D,
        mode: AttackMode,
    ) -> float:
        stats = combat_slot_stats(attacker.unit, mode)
        if stats is None:
            return 0.0
        multiplier = calc_multiplier(stats.multipliers, target)
        armor = armor_for_damage_type(stats.damage_type, target)
        damage = stats.base_damage * stats.num_projectiles * multiplier * (1.0 - armor)
        return max(0.0, damage)

    def process_attacks(self, soldiers: list[Soldier2D]) -> int:
        """Resolve simultaneous fire for the current tick."""
        volley: list[tuple[Soldier2D, Soldier2D, AttackMode, float]] = []
        for soldier in soldiers:
            if not soldier.alive:
                continue
            if not soldier.stopped:
                continue
            if soldier.target_id is None:
                continue
            target = self.soldier_map.get(soldier.target_id)
            if target is None or not target.alive:
                soldier.target_id = None
                continue
            mode = self.prepare_attack(soldier, target)
            if mode is None:
                soldier.stopped = False
                soldier.target_id = None
                continue
            assert soldier.aim_ready_at is not None
            if self.now + 1e-9 < max(soldier.attack_ready_at, soldier.aim_ready_at):
                continue
            damage = self.calc_damage(soldier, target, mode)
            if mode == AttackMode.MELEE:
                rof = (
                    soldier.unit.rof_melee
                    if soldier.unit.rof_melee > 0
                    else self.config.default_rof_melee
                )
            else:
                rof = (
                    soldier.effective_ranged_rof
                    if soldier.effective_ranged_rof > 0
                    else self.config.default_rof_ranged
                )
            soldier.attack_ready_at = self.now + rof
            soldier.reconsider_attack_mode = True
            volley.append((soldier, target, mode, damage))

        if not volley:
            return 0

        self.rng.shuffle(volley)
        for soldier, target, mode, damage in volley:
            if not target.alive:
                continue
            self.damage_callback(soldier, target, damage, mode, is_splash=False)
            stats = combat_slot_stats(soldier.unit, mode)
            if stats is not None and stats.aoe_radius > 0:
                self.process_aoe(
                    soldier,
                    target,
                    mode,
                    slot_stats=stats,
                )
        return len(volley)

    def process_aoe(
        self,
        attacker: Soldier2D,
        main_target: Soldier2D,
        mode: AttackMode,
        *,
        slot_stats: SlotStats | None = None,
    ) -> int:
        stats = slot_stats or combat_slot_stats(attacker.unit, mode)
        if stats is None or stats.aoe_radius <= 0:
            return 0

        base_attack = stats.base_damage * stats.num_projectiles
        # User-approved fallback for missing caps; never replace a real cap.
        damage_cap = stats.damage_cap_proto if stats.damage_cap_proto > 0 else base_attack * 2.0
        hits = resolve_aoe(
            attacker=attacker,
            main_target=main_target,
            radius=float(stats.aoe_radius),
            base_damage=base_attack,
            damage_cap=damage_cap,
            area_sort_mode=stats.area_sort_mode,
            outer_distance=stats.outer_damage_area_distance,
            outer_factor=stats.outer_damage_area_factor,
            spatial_hash=self.spatial_hash,
        )

        for hit in hits:
            target = hit.target
            multiplier = calc_multiplier(stats.multipliers, target)
            armor = armor_for_damage_type(stats.damage_type, target)
            final_damage = max(
                0.0,
                hit.damage * multiplier * (1.0 - armor),
            )
            self.emit(
                EventType.AOE_SPLASH,
                {
                    "attacker_id": attacker.id,
                    "attacker_name": attacker.name,
                    "main_target_id": main_target.id,
                    "splash_target_id": target.id,
                    "splash_target_name": target.name,
                    "splash_damage": round(final_damage, 1),
                    "distance": round(hit.distance, 3),
                    "distance_factor": round(hit.distance_factor, 4),
                    "area_sort_mode": stats.area_sort_mode,
                    "engine": "2d",
                },
            )
            self.damage_callback(
                attacker,
                target,
                final_damage,
                mode,
                is_splash=True,
            )
        return len(hits)
