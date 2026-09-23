"""Combat rules shared conceptually with the 1D engine, in 2D space."""

from __future__ import annotations

import logging
from dataclasses import dataclass

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
        )
    if mode in (AttackMode.RANGED, AttackMode.RANGED_PENALIZED):
        return SlotStats(
            slot="ranged",
            base_damage=unit.attack_ranged,
            num_projectiles=unit.num_projectiles_ranged,
            multipliers=unit.multipliers_ranged,
            damage_type=unit.damage_type_ranged,
            aoe_radius=unit.aoe_radius_ranged,
            damage_cap_proto=unit.damage_cap_ranged,
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
                candidates.sort(
                    key=lambda item: (item.distance_sq_to(soldier), item.id)
                )
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
                return

        candidates = self.attack_candidates(soldier)
        if not candidates:
            soldier.target_id = None
            return
        target = candidates[0]
        soldier.target_id = target.id
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
        distance = soldier.distance_to(target)

        if distance <= soldier.effective_melee_range:
            if soldier.has_melee:
                return AttackMode.MELEE
            if soldier.has_ranged:
                return AttackMode.RANGED_PENALIZED

        if (
            soldier.has_ranged
            and soldier.effective_ranged_range_min
            <= distance
            <= soldier.effective_ranged_range
        ):
            return AttackMode.RANGED

        if (
            soldier.has_ranged
            and distance < soldier.effective_ranged_range_min
        ):
            if soldier.has_melee:
                return None
            return AttackMode.RANGED_PENALIZED

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
        if mode == AttackMode.RANGED_PENALIZED:
            damage *= self.config.close_range_penalty
        return max(1.0, damage)

    def process_attacks(self, soldiers: list[Soldier2D]) -> int:
        """Resolve simultaneous fire for the current tick."""
        volley: list[tuple[Soldier2D, Soldier2D, AttackMode, float]] = []
        for soldier in soldiers:
            if not soldier.alive or not soldier.stopped:
                continue
            if soldier.attack_cd > 0:
                soldier.attack_cd -= self.config.tick_interval
                if soldier.attack_cd > 0.001:
                    continue
            if soldier.target_id is None:
                continue
            target = self.soldier_map.get(soldier.target_id)
            if target is None:
                soldier.target_id = None
                continue
            mode = self.determine_attack_mode(soldier, target)
            if mode is None:
                soldier.stopped = False
                soldier.target_id = None
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
            soldier.attack_cd = rof
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

        radius = float(stats.aoe_radius)
        candidates = self.spatial_hash.query_circle(
            main_target.pos,
            radius,
            predicate=lambda other: (
                other.alive
                and other.id != main_target.id
                and other.side != attacker.side
            ),
        )
        candidates.sort(key=lambda item: (item.distance_sq_to(main_target), item.id))
        if not candidates:
            return 0

        max_splash = round(radius)
        splash_count = min(max_splash, len(candidates))
        splash_targets = self.rng.sample(candidates, splash_count)
        base_attack = stats.base_damage * stats.num_projectiles
        damage_cap = (
            stats.damage_cap_proto
            if stats.damage_cap_proto > 0
            else base_attack * 2.0
        )
        splash_damage = min(damage_cap / splash_count, base_attack)

        for target in splash_targets:
            multiplier = calc_multiplier(stats.multipliers, target)
            armor = armor_for_damage_type(stats.damage_type, target)
            final_damage = max(
                1.0,
                splash_damage * multiplier * (1.0 - armor),
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
        return splash_count
