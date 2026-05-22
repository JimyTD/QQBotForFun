"""加载 OpenRA 导出的 JSON（data/ra2）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "ra2"


@dataclass(frozen=True)
class ArmamentDef:
    id: str
    weapon: str
    requires_condition: str | None
    name: str


@dataclass(frozen=True)
class GainsExperienceDef:
    conditions: tuple[tuple[int, str], ...]
    experience_modifier: int


@dataclass(frozen=True)
class VeterancyRules:
    firepower_veteran: int
    firepower_elite: int
    damage_received_veteran: int
    damage_received_elite: int
    speed_veteran: int
    speed_elite: int
    reload_delay_veteran: int
    reload_delay_elite: int
    regen_step: int
    regen_delay: int


@dataclass(frozen=True)
class CarrierParentDef:
    actors: tuple[str, ...]
    respawn_ticks: int
    spawn_all_at_once: bool


@dataclass(frozen=True)
class AutoTargetPriority:
    id: str
    valid_targets: tuple[str, ...]
    invalid_targets: tuple[str, ...]
    requires_condition: str | None


@dataclass(frozen=True)
class ActorDef:
    id: str
    name: str
    description: str
    categories: str
    cost: int
    hp: int
    armor: str
    speed: int
    locomotor: str
    shares_cell: bool
    crushes: tuple[str, ...]
    target_types: tuple[str, ...]
    crushable: bool
    armaments: tuple[ArmamentDef, ...]
    targetable_layers: tuple[TargetableLayerDef, ...]
    auto_target_priorities: tuple[AutoTargetPriority, ...]
    gains_experience: GainsExperienceDef | None = None
    spawn_only: bool = False
    mind_controllable: bool = False
    mind_controller: bool = False
    carrier_parent: CarrierParentDef | None = None
    carrier_child: bool = False
    ammo_max: int | None = None
    turret_turn_speed: int | None = None
    facing_tolerance: int | None = None
    rearmable_actors: tuple[str, ...] = ()
    takeoff_ticks: int = 0
    blocks_projectiles: bool = False
    blocks_projectiles_height: int = 0
    blocks_projectiles_relationships: tuple[str, ...] = ()


@dataclass(frozen=True)
class TargetableLayerDef:
    id: str
    types: tuple[str, ...]
    requires_condition: str | None


@dataclass(frozen=True)
class WarheadDef:
    id: str
    type: str
    damage: int
    versus: dict[str, int]
    spread: int | None
    falloff: tuple[int, ...] = ()
    delay: int = 0


@dataclass(frozen=True)
class WeaponDef:
    id: str
    reload_delay: int
    range: int | None
    min_range: int | None
    burst: int
    burst_delays: tuple[int, ...]
    valid_targets: tuple[str, ...]
    invalid_targets: tuple[str, ...]
    projectile_speed: int | None
    warheads: tuple[WarheadDef, ...]
    projectile_blockable: bool = False


def _data_path(name: str) -> Path:
    p = _DATA_DIR / name
    if not p.is_file():
        raise FileNotFoundError(
            f"缺少 {p}，请先运行: uv run python scripts/crawler/openra_ra2_export.py"
        )
    return p


@lru_cache(maxsize=1)
def load_actors() -> dict[str, ActorDef]:
    raw = json.loads(_data_path("actors.json").read_text(encoding="utf-8"))
    out: dict[str, ActorDef] = {}
    for aid, node in raw.items():
        arms = tuple(
            ArmamentDef(
                id=a["id"],
                weapon=a["weapon"],
                requires_condition=a.get("requires_condition"),
                name=a.get("name", "primary"),
            )
            for a in node.get("armaments", [])
        )
        atp = tuple(
            AutoTargetPriority(
                id=p["id"],
                valid_targets=tuple(p.get("valid_targets", [])),
                invalid_targets=tuple(p.get("invalid_targets", [])),
                requires_condition=p.get("requires_condition"),
            )
            for p in node.get("auto_target_priorities", [])
        )
        ge_raw = node.get("gains_experience")
        ge: GainsExperienceDef | None = None
        if isinstance(ge_raw, dict):
            cond = ge_raw.get("conditions") or {}
            ge = GainsExperienceDef(
                conditions=tuple(
                    (int(k), str(v)) for k, v in sorted(cond.items(), key=lambda x: int(x[0]))
                ),
                experience_modifier=int(ge_raw.get("experience_modifier", -1)),
            )
        cp_raw = node.get("carrier_parent")
        cp: CarrierParentDef | None = None
        if isinstance(cp_raw, dict):
            cp = CarrierParentDef(
                actors=tuple(cp_raw.get("actors", [])),
                respawn_ticks=int(cp_raw.get("respawn_ticks", 300)),
                spawn_all_at_once=bool(cp_raw.get("spawn_all_at_once", True)),
            )
        layers = tuple(
            TargetableLayerDef(
                id=layer["id"],
                types=tuple(layer.get("types", [])),
                requires_condition=layer.get("requires_condition"),
            )
            for layer in node.get("targetable_layers", [])
        )
        out[aid] = ActorDef(
            id=aid,
            name=node["name"],
            description=str(node.get("description", "")),
            categories=str(node.get("categories", "")),
            cost=int(node.get("cost", 0)),
            hp=int(node["hp"]),
            armor=str(node.get("armor", "None")),
            speed=int(node.get("speed", 1)),
            locomotor=str(node.get("locomotor", "foot")),
            shares_cell=bool(node.get("shares_cell", False)),
            crushes=tuple(node.get("crushes", [])),
            target_types=tuple(node.get("target_types", [])),
            crushable=bool(node.get("crushable", False)),
            armaments=arms,
            targetable_layers=layers,
            auto_target_priorities=atp,
            gains_experience=ge,
            spawn_only=bool(node.get("spawn_only", False)),
            mind_controllable=bool(node.get("mind_controllable", False)),
            mind_controller=bool(node.get("mind_controller", False)),
            carrier_parent=cp,
            carrier_child=bool(node.get("carrier_child", False)),
            ammo_max=node.get("ammo_max"),
            turret_turn_speed=node.get("turret_turn_speed"),
            facing_tolerance=node.get("facing_tolerance"),
            rearmable_actors=tuple(node.get("rearmable_actors", [])),
            takeoff_ticks=int(node.get("takeoff_ticks", 0)),
            blocks_projectiles=bool(node.get("blocks_projectiles", False)),
            blocks_projectiles_height=int(node.get("blocks_projectiles_height", 0)),
            blocks_projectiles_relationships=tuple(
                node.get("blocks_projectiles_relationships", [])
            ),
        )
    return out


def load_battle_pool_actors() -> dict[str, ActorDef]:
    """可编入斗蛐蛐随机阵容的单位（黑名单 + spawn_only 已排除）。"""
    from .battle_pool import is_lineup_eligible

    return {k: v for k, v in load_actors().items() if is_lineup_eligible(v)}


@lru_cache(maxsize=1)
def load_veterancy_rules() -> VeterancyRules:
    raw = json.loads(_data_path("veterancy.json").read_text(encoding="utf-8"))
    return VeterancyRules(
        firepower_veteran=int(raw["firepower_veteran"]),
        firepower_elite=int(raw["firepower_elite"]),
        damage_received_veteran=int(raw["damage_received_veteran"]),
        damage_received_elite=int(raw["damage_received_elite"]),
        speed_veteran=int(raw["speed_veteran"]),
        speed_elite=int(raw["speed_elite"]),
        reload_delay_veteran=int(raw["reload_delay_veteran"]),
        reload_delay_elite=int(raw["reload_delay_elite"]),
        regen_step=int(raw.get("regen_step", 0)),
        regen_delay=int(raw.get("regen_delay", 100)),
    )


@lru_cache(maxsize=1)
def load_weapons() -> dict[str, WeaponDef]:
    raw = json.loads(_data_path("weapons.json").read_text(encoding="utf-8"))
    out: dict[str, WeaponDef] = {}
    for wid, node in raw.items():
        whs = tuple(
            WarheadDef(
                id=w["id"],
                type=w["type"],
                damage=int(w["damage"]),
                versus=dict(w.get("versus", {})),
                spread=w.get("spread"),
                falloff=tuple(w.get("falloff", [])),
                delay=int(w.get("delay", 0)),
            )
            for w in node.get("warheads", [])
        )
        out[wid] = WeaponDef(
            id=wid,
            reload_delay=int(node.get("reload_delay", 1)),
            range=node.get("range"),
            min_range=node.get("min_range"),
            burst=int(node.get("burst", 1)),
            burst_delays=tuple(node.get("burst_delays", [])),
            valid_targets=tuple(node.get("valid_targets", [])),
            invalid_targets=tuple(node.get("invalid_targets", [])),
            projectile_speed=node.get("projectile_speed"),
            projectile_blockable=bool(node.get("projectile_blockable", False)),
            warheads=whs,
        )
    return out


@lru_cache(maxsize=1)
def _weapon_index() -> dict[str, str]:
    return {k.lower(): k for k in load_weapons()}


def resolve_weapon(weapon_id: str) -> WeaponDef | None:
    weapons = load_weapons()
    if weapon_id in weapons:
        return weapons[weapon_id]
    key = _weapon_index().get(weapon_id.lower())
    return weapons.get(key) if key else None
