"""二维空旷战场斗蛐蛐模拟器（数据与行为规格来自 OpenRA/ra2）。"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .constants import (
    CELL_WDIST,
    DEFAULT_ARENA_H,
    DEFAULT_ARENA_W,
    DEFAULT_BURST_DELAY,
    INFANTRY_PER_CELL,
    MAX_TICKS,
    TICK_SECONDS,
)
from .carrier import (
    init_carrier_children,
    needs_rearm,
    tick_aircraft_takeoff,
    tick_carrier_respawn,
    tick_rearm,
)
from .projectile_lane import (
    check_inflight_intercept,
    find_projectile_blocker_between,
)
from .turret import tick_turret, turret_can_fire
from .damage import calc_damage, spread_falloff_permille
from .experience import (
    UnitVeterancy,
    apply_initial_stars,
    combat_multipliers,
    gives_experience_value,
    grant_experience,
    scaled_reload_delay,
    scaled_speed,
)
from .mind import apply_mind_control, is_mind_control_weapon, on_unit_death
from .pathfinder import astar
from .repo import ActorDef, ArmamentDef, WeaponDef, load_actors, load_veterancy_rules, resolve_weapon
from .targeting import (
    armament_allowed,
    auto_target_sort_key,
    can_auto_target,
    target_categories,
    effective_target_types,
    weapon_valid_against_unit,
)

logger = logging.getLogger("ra2_battle.simulator")


class Side(str, Enum):
    RED = "red"
    BLUE = "blue"


class EventType(str, Enum):
    BATTLE_START = "BATTLE_START"
    MOVE = "MOVE"
    ATTACK = "ATTACK"
    DEATH = "DEATH"
    CRUSH = "CRUSH"
    LEVEL_UP = "LEVEL_UP"
    MIND_CONTROL = "MIND_CONTROL"
    MIND_RELEASE = "MIND_RELEASE"
    SPAWN_CHILD = "SPAWN_CHILD"
    REARM = "REARM"
    INTERCEPT = "INTERCEPT"
    BATTLE_END = "BATTLE_END"


@dataclass
class BattleEvent:
    tick: int
    type: EventType
    payload: dict[str, Any]


@dataclass
class PendingHit:
    impact_tick: int
    fire_tick: int
    src_x: int
    src_y: int
    attacker_id: int
    victim_id: int
    weapon_id: str
    warhead_id: str


@dataclass
class UnitInstance:
    id: int
    actor_id: str
    side: Side
    actor: ActorDef
    x: int
    y: int
    hp: float
    max_hp: float
    target_id: int | None = None
    move_progress: float = 0.0
    ticks_since_shot: dict[str, int] = field(default_factory=dict)
    burst_left: dict[str, int] = field(default_factory=dict)
    fire_delay: dict[str, int] = field(default_factory=dict)
    active_weapon_id: str | None = None
    veterancy: UnitVeterancy = field(default_factory=UnitVeterancy)
    regen_cooldown: int = 0
    original_side: Side | None = None
    controlled_by_id: int | None = None
    controls_unit_id: int | None = None
    parent_carrier_id: int | None = None
    carrier_respawn_cooldown: int = 0
    ammo_left: int | None = None
    turret_facing: int = 0
    airborne: bool = True
    takeoff_ticks_left: int = 0
    rearm_ticks_left: int = 0
    alive: bool = True

    @property
    def cell(self) -> tuple[int, int]:
        return (self.x, self.y)


@dataclass
class BattleResult:
    winner: Side | None
    events: list[BattleEvent]
    duration: float
    ticks: int
    red_alive: list[UnitInstance]
    blue_alive: list[UnitInstance]
    red_dead: list[UnitInstance]
    blue_dead: list[UnitInstance]


def _wdist_between(a: tuple[int, int], b: tuple[int, int]) -> int:
    dx = (a[0] - b[0]) * CELL_WDIST
    dy = (a[1] - b[1]) * CELL_WDIST
    return int((dx * dx + dy * dy) ** 0.5)


def _damage_warheads(weapon: WeaponDef) -> list[Any]:
    return [
        wh
        for wh in weapon.warheads
        if wh.type in ("SpreadDamage", "TargetDamage")
    ]


def _primary_warhead(weapon: WeaponDef) -> Any:
    for wh in _damage_warheads(weapon):
        if wh.damage > 0:
            return wh
    whs = _damage_warheads(weapon)
    return whs[0] if whs else None


def _weapon_in_range(dist: int, weapon: WeaponDef) -> bool:
    if weapon.range is None:
        return False
    if dist > weapon.range:
        return False
    if weapon.min_range and dist < weapon.min_range:
        return False
    return True


def _projectile_travel_ticks(dist_wdist: int, weapon: WeaponDef) -> int:
    """每 tick 飞行 weapon.projectile_speed WDist，对齐弹道 Speed。"""
    spd = weapon.projectile_speed
    if not spd or spd <= 0:
        return 0
    return max(1, (dist_wdist + spd - 1) // spd)


def _burst_delay_ticks(weapon: WeaponDef, burst_index: int) -> int:
    """burst_index: 已打出几发后的下一发间隔（对齐 Armament.UpdateBurst）。"""
    delays = weapon.burst_delays
    if len(delays) == 1:
        return delays[0]
    if len(delays) > 1 and burst_index < len(delays):
        return delays[burst_index]
    return DEFAULT_BURST_DELAY


ArmyEntry = tuple[str, int] | tuple[str, int, int]


class BattleSimulator:
    def __init__(
        self,
        red: list[ArmyEntry],
        blue: list[ArmyEntry],
        *,
        width: int = DEFAULT_ARENA_W,
        height: int = DEFAULT_ARENA_H,
        seed: int | None = None,
        max_ticks: int = MAX_TICKS,
    ) -> None:
        self.actors = load_actors()
        self.width = width
        self.height = height
        self.max_ticks = max_ticks
        self._rng = random.Random(seed)
        self._veterancy_rules = load_veterancy_rules()
        self._events: list[BattleEvent] = []
        self._units: list[UnitInstance] = []
        self._by_id: dict[int, UnitInstance] = {}
        self._next_id = 1
        self._tick = 0
        self._pending: list[PendingHit] = []

        self._spawn_side(Side.RED, red, x_base=2)
        self._spawn_side(Side.BLUE, blue, x_base=width - 3)
        init_carrier_children(self)

    @staticmethod
    def _parse_army_entry(entry: ArmyEntry) -> tuple[str, int, int]:
        if len(entry) == 2:
            return entry[0], entry[1], 1
        return entry[0], entry[1], max(1, min(3, int(entry[2])))

    def _spawn_side(self, side: Side, army: list[ArmyEntry], x_base: int) -> None:
        row = self.height // 2
        y_off = 0
        for actor_id, count, stars in (
            self._parse_army_entry(e) for e in army
        ):
            if actor_id not in self.actors:
                raise KeyError(f"未知单位 {actor_id}，请先 export 或检查 actors.json")
            adef = self.actors[actor_id]
            for _ in range(count):
                y = row + y_off
                y_off += 1
                if y >= self.height:
                    y_off = 0
                    y = y_off
                u = UnitInstance(
                    id=self._next_id,
                    actor_id=actor_id,
                    side=side,
                    actor=adef,
                    x=x_base,
                    y=y,
                    hp=float(adef.hp),
                    max_hp=float(adef.hp),
                )
                if adef.gains_experience is not None:
                    apply_initial_stars(
                        u.veterancy, stars, adef, adef.gains_experience
                    )
                if adef.ammo_max is not None:
                    u.ammo_left = adef.ammo_max
                self._next_id += 1
                self._units.append(u)
                self._by_id[u.id] = u

    def _spawn_child(
        self,
        actor_id: str,
        side: Side,
        x: int,
        y: int,
        *,
        parent_id: int,
    ) -> UnitInstance | None:
        if actor_id not in self.actors:
            return None
        adef = self.actors[actor_id]
        u = UnitInstance(
            id=self._next_id,
            actor_id=actor_id,
            side=side,
            actor=adef,
            x=x,
            y=y,
            hp=float(adef.hp),
            max_hp=float(adef.hp),
            parent_carrier_id=parent_id,
        )
        if adef.ammo_max is not None:
            u.ammo_left = adef.ammo_max
        if adef.takeoff_ticks > 0:
            u.airborne = False
            u.takeoff_ticks_left = adef.takeoff_ticks
        self._next_id += 1
        self._units.append(u)
        self._by_id[u.id] = u
        self._emit(
            EventType.SPAWN_CHILD,
            {
                "unit_id": u.id,
                "actor_id": actor_id,
                "parent_id": parent_id,
                "at": [x, y],
            },
        )
        return u

    def _emit(self, etype: EventType, payload: dict[str, Any]) -> None:
        self._events.append(BattleEvent(self._tick, etype, payload))

    def _alive(self, side: Side | None = None) -> list[UnitInstance]:
        out = [u for u in self._units if u.alive]
        if side is not None:
            out = [u for u in out if u.side == side]
        return out

    def _cell_occupants(self, cell: tuple[int, int]) -> list[UnitInstance]:
        return [u for u in self._alive() if u.cell == cell]

    def _vehicle_blocks_cell(self, cell: tuple[int, int], mover: UnitInstance) -> bool:
        for u in self._cell_occupants(cell):
            if u.id == mover.id:
                continue
            if not u.actor.shares_cell:
                return True
            if u.actor.shares_cell and not mover.actor.shares_cell:
                return True
        return False

    def _infantry_count(self, cell: tuple[int, int]) -> int:
        return sum(1 for u in self._cell_occupants(cell) if u.actor.shares_cell)

    def _iter_armaments_vs(
        self, attacker: UnitInstance, target: UnitInstance
    ):
        dist = _wdist_between(attacker.cell, target.cell)
        for arm in attacker.actor.armaments:
            if not armament_allowed(arm, veterancy_level=attacker.veterancy.level):
                continue
            weapon = resolve_weapon(arm.weapon)
            if weapon is None:
                continue
            if not weapon_valid_against_unit(
                weapon,
                target.actor,
                target_types=effective_target_types(target),
            ):
                continue
            if not _weapon_in_range(dist, weapon):
                continue
            yield arm, weapon

    def _has_weapon_in_range(
        self, attacker: UnitInstance, target: UnitInstance
    ) -> bool:
        return any(True for _ in self._iter_armaments_vs(attacker, target))

    def _is_reloading(self, u: UnitInstance, weapon: WeaponDef) -> bool:
        return u.fire_delay.get(weapon.id, 0) > 0

    def _is_controlling(self, u: UnitInstance) -> bool:
        return u.controls_unit_id is not None

    def _can_check_fire(
        self, u: UnitInstance, target: UnitInstance, weapon: WeaponDef
    ) -> bool:
        if not target.alive or self._is_reloading(u, weapon):
            return False
        if u.ammo_left is not None and u.ammo_left <= 0:
            return False
        wid = weapon.id
        if u.burst_left.get(wid, 0) > 0:
            return True
        return u.ticks_since_shot.get(wid, 0) >= self._effective_reload_delay(
            u, weapon
        )

    def _splash_victims(
        self,
        attacker: UnitInstance,
        primary: UnitInstance,
        weapon: WeaponDef,
        wh: Any,
    ) -> list[tuple[UnitInstance, int]]:
        """返回 (受害者, 距爆心 WDist)。"""
        victims: list[tuple[UnitInstance, int]] = [(primary, 0)]
        if wh.type != "SpreadDamage" or not wh.spread:
            return victims
        spread = int(wh.spread)
        for other in self._alive():
            if other.id == primary.id or other.side == attacker.side:
                continue
            dist = _wdist_between(other.cell, primary.cell)
            if dist > spread:
                continue
            if not weapon_valid_against_unit(
                weapon,
                other.actor,
                target_types=effective_target_types(other),
            ):
                continue
            if not can_auto_target(
                attacker.actor,
                other.actor,
                is_controlling=self._is_controlling(attacker),
                target_unit=other,
            ):
                continue
            victims.append((other, dist))
        return victims

    def _apply_damage(
        self,
        u: UnitInstance,
        victim: UnitInstance,
        weapon: WeaponDef,
        dmg: int,
    ) -> None:
        victim_mult = combat_multipliers(
            victim.veterancy.level, self._veterancy_rules
        )
        dmg = dmg * victim_mult.damage_received // 100
        if dmg <= 0:
            return
        victim.hp -= dmg
        u.active_weapon_id = weapon.id
        self._emit(EventType.ATTACK, {
            "attacker_id": u.id,
            "attacker": u.actor_id,
            "target_id": victim.id,
            "target": victim.actor_id,
            "weapon": weapon.id,
            "damage": dmg,
            "target_hp": max(0, int(victim.hp)),
            "attacker_level": u.veterancy.level,
        })
        if victim.hp <= 0:
            victim.alive = False
            self._emit(EventType.DEATH, {
                "unit_id": victim.id,
                "actor_id": victim.actor_id,
                "killer_id": u.id,
            })
            on_unit_death(self, victim)
            self._on_kill(u, victim)

    def _resolve_hit(
        self,
        u: UnitInstance,
        target: UnitInstance,
        weapon: WeaponDef,
        wh: Any,
    ) -> None:
        if is_mind_control_weapon(weapon):
            apply_mind_control(self, u, target)
            return
        att_mult = combat_multipliers(u.veterancy.level, self._veterancy_rules)
        for victim, dist in self._splash_victims(u, target, weapon, wh):
            if not victim.alive:
                continue
            falloff = spread_falloff_permille(wh, dist)
            dmg = calc_damage(
                wh,
                victim.actor.armor,
                firepower_percent=att_mult.firepower,
                falloff_permille=falloff,
            )
            if dmg <= 0:
                continue
            self._apply_damage(u, victim, weapon, dmg)

    def _fire_one_shot(
        self,
        u: UnitInstance,
        target: UnitInstance,
        weapon: WeaponDef,
    ) -> None:
        warheads = _damage_warheads(weapon)
        if not warheads and not is_mind_control_weapon(weapon):
            return
        blocker = find_projectile_blocker_between(
            self, u, u.cell, target.cell, weapon
        )
        if blocker is not None:
            self._emit(EventType.INTERCEPT, {
                "attacker_id": u.id,
                "attacker": u.actor_id,
                "blocker_id": blocker.id,
                "blocker": blocker.actor_id,
                "target_id": target.id,
                "target": target.actor_id,
                "weapon": weapon.id,
            })
            return
        dist = _wdist_between(u.cell, target.cell)
        travel = _projectile_travel_ticks(dist, weapon)
        if is_mind_control_weapon(weapon):
            impact = self._tick + travel
            self._pending.append(
                PendingHit(
                    impact_tick=impact,
                    fire_tick=self._tick,
                    src_x=u.x,
                    src_y=u.y,
                    attacker_id=u.id,
                    victim_id=target.id,
                    weapon_id=weapon.id,
                    warhead_id=warheads[0].id if warheads else "",
                )
            )
            return
        for wh in warheads:
            impact = self._tick + travel + max(0, wh.delay)
            if travel > 0 or wh.delay > 0:
                self._pending.append(
                    PendingHit(
                        impact_tick=impact,
                        fire_tick=self._tick,
                        src_x=u.x,
                        src_y=u.y,
                        attacker_id=u.id,
                        victim_id=target.id,
                        weapon_id=weapon.id,
                        warhead_id=wh.id,
                    )
                )
            else:
                self._resolve_hit(u, target, weapon, wh)

    def _process_pending_hits(self) -> None:
        remaining: list[PendingHit] = []
        for hit in self._pending:
            if hit.impact_tick > self._tick:
                blocker = check_inflight_intercept(self, hit)
                if blocker is not None:
                    attacker = self._by_id.get(hit.attacker_id)
                    victim = self._by_id.get(hit.victim_id)
                    self._emit(EventType.INTERCEPT, {
                        "attacker_id": hit.attacker_id,
                        "attacker": attacker.actor_id if attacker else "",
                        "blocker_id": blocker.id,
                        "blocker": blocker.actor_id,
                        "target_id": hit.victim_id,
                        "target": victim.actor_id if victim else "",
                        "weapon": hit.weapon_id,
                    })
                    continue
                remaining.append(hit)
                continue
            attacker = self._by_id.get(hit.attacker_id)
            victim = self._by_id.get(hit.victim_id)
            if (
                attacker is None
                or victim is None
                or not attacker.alive
                or not victim.alive
            ):
                continue
            weapon = resolve_weapon(hit.weapon_id)
            if weapon is None:
                continue
            wh = next((w for w in weapon.warheads if w.id == hit.warhead_id), None)
            if wh is None:
                wh = _primary_warhead(weapon)
            if wh is None:
                continue
            self._resolve_hit(attacker, victim, weapon, wh)
        self._pending = remaining

    def _on_kill(self, killer: UnitInstance, victim: UnitInstance) -> None:
        if killer.side == victim.side:
            return
        ge = killer.actor.gains_experience
        if ge is None:
            return
        xp = gives_experience_value(victim.actor)
        gained = grant_experience(killer.veterancy, xp, killer.actor, ge)
        if gained > 0:
            self._emit(EventType.LEVEL_UP, {
                "unit_id": killer.id,
                "actor_id": killer.actor_id,
                "level": killer.veterancy.level,
                "experience": killer.veterancy.experience,
            })

    def _effective_reload_delay(self, u: UnitInstance, weapon: WeaponDef) -> int:
        mult = combat_multipliers(u.veterancy.level, self._veterancy_rules)
        return scaled_reload_delay(weapon.reload_delay, mult)

    def _update_burst(self, u: UnitInstance, weapon: WeaponDef) -> None:
        """对齐 Armament.UpdateBurst：连发间隔或进入 ReloadDelay。"""
        wid = weapon.id
        left = u.burst_left.get(wid, 0)
        if left > 0:
            idx = max(0, weapon.burst - left - 1)
            u.fire_delay[wid] = _burst_delay_ticks(weapon, idx)
        else:
            u.fire_delay[wid] = max(1, self._effective_reload_delay(u, weapon))
            u.burst_left[wid] = 0

    def _check_fire(
        self, u: UnitInstance, target: UnitInstance, weapon: WeaponDef
    ) -> None:
        """对齐 AttackBase.DoAttack → Armament.CheckFire（单武器）。"""
        loops = 0
        while self._can_check_fire(u, target, weapon) and target.alive:
            loops += 1
            if loops > 16:
                break
            wid = weapon.id
            if u.burst_left.get(wid, 0) <= 0:
                u.burst_left[wid] = weapon.burst
                u.ticks_since_shot[wid] = 0
            self._fire_one_shot(u, target, weapon)
            if u.ammo_left is not None:
                u.ammo_left = max(0, u.ammo_left - 1)
            u.burst_left[wid] = u.burst_left.get(wid, weapon.burst) - 1
            self._update_burst(u, weapon)
            if self._is_reloading(u, weapon):
                break

    def _acquire_target(self, u: UnitInstance) -> None:
        enemies = [
            e
            for e in self._alive()
            if e.side != u.side
            and can_auto_target(
                u.actor,
                e.actor,
                is_controlling=self._is_controlling(u),
                target_unit=e,
            )
        ]
        if not enemies:
            u.target_id = None
            return

        def sort_key(e: UnitInstance) -> tuple[int, int, int, int]:
            dist = _wdist_between(u.cell, e.cell)
            return auto_target_sort_key(
                u.actor,
                e.actor,
                in_weapon_range=self._has_weapon_in_range(u, e),
                distance=dist,
                target_hp=int(e.hp),
                is_controlling=self._is_controlling(u),
                target_unit=e,
            )

        best = min(enemies, key=sort_key)
        u.target_id = best.id

    def _try_crush(
        self, mover: UnitInstance, cell: tuple[int, int]
    ) -> None:
        if "infantry" not in mover.actor.crushes:
            return
        for v in list(self._cell_occupants(cell)):
            if not v.actor.crushable:
                continue
            if "Infantry" not in target_categories(v.actor):
                continue
            v.alive = False
            v.hp = 0
            on_unit_death(self, v)
            self._emit(EventType.CRUSH, {
                "crusher_id": mover.id,
                "crusher": mover.actor_id,
                "victim_id": v.id,
                "victim": v.actor_id,
            })
            self._on_kill(mover, v)

    def _move_unit(self, u: UnitInstance) -> None:
        if u.target_id is None:
            return
        target = self._by_id.get(u.target_id)
        if target is None or not target.alive:
            return
        if self._has_weapon_in_range(u, target) and not needs_rearm(u):
            return

        move_mult = combat_multipliers(u.veterancy.level, self._veterancy_rules)
        base_speed = max(1, u.actor.speed)
        if not u.airborne:
            base_speed = max(1, base_speed // 4)
        speed = scaled_speed(base_speed, move_mult)
        u.move_progress += speed
        if u.move_progress < CELL_WDIST:
            return
        u.move_progress -= CELL_WDIST

        blocked = lambda c, mv=u: self._vehicle_blocks_cell(c, mv)  # noqa: E731

        path = astar(u.cell, target.cell, self.width, self.height, blocked)
        if len(path) < 2:
            best: tuple[int, int] | None = None
            best_d = 10**9
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (u.x + dx, u.y + dy)
                if (
                    nxt[0] < 0
                    or nxt[1] < 0
                    or nxt[0] >= self.width
                    or nxt[1] >= self.height
                ):
                    continue
                if blocked(nxt):
                    continue
                d = _wdist_between(nxt, target.cell)
                if d < best_d:
                    best_d = d
                    best = nxt
            if best is None:
                return
            nxt = best
        else:
            nxt = path[1]

        self._try_crush(u, nxt)
        if u.actor.shares_cell:
            if self._infantry_count(nxt) >= INFANTRY_PER_CELL:
                return
        elif self._vehicle_blocks_cell(nxt, u):
            return

        ox, oy = u.x, u.y
        u.x, u.y = nxt
        self._emit(EventType.MOVE, {
            "unit_id": u.id,
            "actor_id": u.actor_id,
            "from": [ox, oy],
            "to": [u.x, u.y],
        })

    def _attack(self, u: UnitInstance) -> None:
        if u.target_id is None or needs_rearm(u) or not u.airborne:
            return
        target = self._by_id.get(u.target_id)
        if target is None or not target.alive or target.side == u.side:
            return
        if not turret_can_fire(u, target.cell):
            return
        for _arm, weapon in self._iter_armaments_vs(u, target):
            self._check_fire(u, target, weapon)

    def _check_winner(self) -> Side | None:
        r = self._alive(Side.RED)
        b = self._alive(Side.BLUE)
        if r and b:
            return None
        if r:
            return Side.RED
        if b:
            return Side.BLUE
        return None

    def _tick_unit(self, u: UnitInstance) -> None:
        """按单位交错：起飞/补给 → 锁敌 → 炮塔 → 移动 → 攻击。"""
        tick_aircraft_takeoff(u)
        tick_rearm(self, u)
        self._acquire_target(u)
        if u.target_id is not None:
            target = self._by_id.get(u.target_id)
            if (
                target is not None
                and target.alive
                and target.side != u.side
                and u.actor.turret_turn_speed
            ):
                tick_turret(u, target.cell)
        self._move_unit(u)
        self._attack(u)

    def _tick_unit_timers(self, u: UnitInstance) -> None:
        weapons_seen: set[str] = set()
        for arm in u.actor.armaments:
            if not armament_allowed(arm, veterancy_level=u.veterancy.level):
                continue
            w = resolve_weapon(arm.weapon)
            if w is None or w.id in weapons_seen:
                continue
            weapons_seen.add(w.id)
            wid = w.id
            fd = u.fire_delay.get(wid, 0)
            if fd > 0:
                u.fire_delay[wid] = fd - 1
            if u.burst_left.get(wid, 0) <= 0:
                ts = u.ticks_since_shot.get(wid, 0)
                need = self._effective_reload_delay(u, w)
                if ts < need:
                    u.ticks_since_shot[wid] = ts + 1
        step = self._veterancy_rules.regen_step
        delay = max(1, self._veterancy_rules.regen_delay)
        if step > 0 and u.veterancy.level == 1 and u.hp < u.max_hp:
            if u.regen_cooldown > 0:
                u.regen_cooldown -= 1
            else:
                u.hp = min(u.max_hp, u.hp + step)
                u.regen_cooldown = delay

    def run(self) -> BattleResult:
        self._emit(EventType.BATTLE_START, {
            "width": self.width,
            "height": self.height,
            "red_count": sum(
                1
                for u in self._units
                if u.side == Side.RED and u.parent_carrier_id is None
            ),
            "blue_count": sum(
                1
                for u in self._units
                if u.side == Side.BLUE and u.parent_carrier_id is None
            ),
        })

        winner: Side | None = None
        for tick in range(self.max_ticks):
            self._tick = tick
            self._process_pending_hits()
            for u in sorted(self._alive(), key=lambda x: x.id):
                self._tick_unit(u)
            for u in sorted(self._alive(), key=lambda x: x.id):
                self._tick_unit_timers(u)
            tick_carrier_respawn(self)
            winner = self._check_winner()
            if winner is not None:
                break

        duration = (self._tick + 1) * TICK_SECONDS
        self._emit(EventType.BATTLE_END, {
            "winner": winner.value if winner else "draw",
            "duration": round(duration, 2),
            "ticks": self._tick + 1,
        })

        alive = self._alive()
        dead = [u for u in self._units if not u.alive]
        return BattleResult(
            winner=winner,
            events=self._events,
            duration=duration,
            ticks=self._tick + 1,
            red_alive=[u for u in alive if u.side == Side.RED],
            blue_alive=[u for u in alive if u.side == Side.BLUE],
            red_dead=[u for u in dead if u.side == Side.RED],
            blue_dead=[u for u in dead if u.side == Side.BLUE],
        )
