"""从 vendor/openra-ra2 导出斗蛐蛐用 JSON（权威数据，禁止手填数值）。

用法:
    uv run python scripts/crawler/openra_ra2_export.py
    uv run python scripts/crawler/openra_ra2_export.py --vendor path/to/openra-ra2
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from plugins.games.ra2_battle.openra_yaml import (  # noqa: E402
    load_rules_dir,
    load_weapons_dir,
    merge_actor,
    merge_weapon,
    parse_wdist,
    split_csv,
    trait_blocks,
)

DEFAULT_VENDOR = _ROOT / "vendor" / "openra-ra2"
OUT_DIR = _ROOT / "data" / "ra2"


def _nested_get(node: dict[str, Any], *keys: str) -> Any:
    cur: Any = node
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _export_locomotors(world_merged: dict[str, Any]) -> dict[str, dict[str, Any]]:
    locos: dict[str, dict[str, Any]] = {}
    for key, block in world_merged.items():
        if not key.startswith("Locomotor@"):
            continue
        name = block.get("Name")
        if not name:
            continue
        locos[str(name)] = {
            "name": str(name),
            "shares_cell": bool(block.get("SharesCell", False)),
            "crushes": split_csv(block.get("Crushes")),
        }
    return locos


def _export_warheads(merged: dict[str, Any]) -> list[dict[str, Any]]:
    warheads: list[dict[str, Any]] = []
    for key, block in merged.items():
        if not key.startswith("Warhead@"):
            continue
        wh_type = key.split("@", 1)[-1]
        if isinstance(block, str):
            wh_name = block
            damage = 0
            versus_raw: dict[str, Any] = {}
            spread = None
        elif isinstance(block, dict):
            wh_name = str(block.get("@value", wh_type))
            damage = int(block.get("Damage", 0))
            versus_raw = block.get("Versus") or {}
            spread = parse_wdist(block.get("Spread"))
        else:
            continue
        if "Dam" not in wh_type and damage == 0:
            continue
        versus: dict[str, int] = {}
        if isinstance(versus_raw, dict):
            for armor, pct in versus_raw.items():
                try:
                    versus[str(armor)] = int(pct)
                except (TypeError, ValueError):
                    pass
        falloff_raw = block.get("Falloff") if isinstance(block, dict) else None
        falloff: list[int] = []
        if falloff_raw:
            falloff = [int(x.strip()) for x in str(falloff_raw).split(",") if x.strip()]
        delay = int(block.get("Delay", 0)) if isinstance(block, dict) else 0
        warheads.append({
            "id": key,
            "type": wh_name,
            "damage": damage,
            "versus": versus,
            "spread": spread,
            "falloff": falloff,
            "delay": delay,
        })
    return warheads


def _export_weapons(raw_weapons: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    out: dict[str, dict[str, Any]] = {}
    for wid in raw_weapons:
        if wid.startswith("^"):
            continue
        try:
            merged = merge_weapon(wid, raw_weapons, cache)
        except (KeyError, ValueError):
            continue
        warheads = _export_warheads(merged)
        if not warheads:
            continue
        proj = _nested_get(merged, "Projectile") or {}
        out[wid] = {
            "id": wid,
            "reload_delay": int(merged.get("ReloadDelay", 1)),
            "range": parse_wdist(merged.get("Range")),
            "min_range": parse_wdist(merged.get("MinRange")),
            "burst": int(merged.get("Burst", 1)),
            "burst_delays": [
                int(x) for x in (merged.get("BurstDelays") or [])
            ] if isinstance(merged.get("BurstDelays"), list) else [],
            "valid_targets": split_csv(merged.get("ValidTargets")),
            "invalid_targets": split_csv(merged.get("InvalidTargets")),
            "projectile_speed": parse_wdist(proj.get("Speed")) if isinstance(proj, dict) else None,
            "projectile_blockable": _projectile_blockable(proj),
            "warheads": warheads,
        }
    return out


def _targetable_active(block: dict[str, Any]) -> bool:
    """斗蛐蛐默认状态：只启用「平时成立」的 Targetable（!parachute 等）。"""
    cond = block.get("RequiresCondition")
    if cond is None:
        return True
    c = str(cond).strip()
    if c.startswith("!"):
        return True
    if any(
        m in c
        for m in ("parachute", "rank-elite", "damaged", "controlled", "stance-", "assault-move")
    ):
        return False
    return False


def _export_auto_target(merged: dict[str, Any]) -> list[dict[str, Any]]:
    priorities: list[dict[str, Any]] = []
    for key, block in trait_blocks(merged, "AutoTargetPriority"):
        priorities.append({
            "id": key,
            "valid_targets": split_csv(block.get("ValidTargets")),
            "invalid_targets": split_csv(block.get("InvalidTargets")),
            "requires_condition": block.get("RequiresCondition"),
        })
    if not priorities and trait_blocks(merged, "AutoTarget"):
        priorities.append({
            "id": "AutoTarget@fallback",
            "valid_targets": ["Infantry", "Vehicle", "Air"],
            "invalid_targets": ["NoAutoTarget"],
            "requires_condition": None,
        })
    return priorities


def _export_gains_experience(merged: dict[str, Any]) -> dict[str, Any] | None:
    block = merged.get("GainsExperience")
    if not isinstance(block, dict):
        return None
    cond = block.get("Conditions") or {}
    if not isinstance(cond, dict):
        return None
    return {
        "conditions": {str(k): str(v) for k, v in cond.items()},
        "experience_modifier": int(block.get("ExperienceModifier", -1)),
    }


def _export_veterancy_rules(raw_rules: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cache: dict[str, dict[str, Any]] = {}
    merged = merge_actor("^GainsExperience", raw_rules, cache)

    def _mod(trait: str, cond: str) -> int:
        for key, block in trait_blocks(merged, trait):
            if not isinstance(block, dict):
                continue
            if str(block.get("RequiresCondition", "")).strip() == cond:
                return int(block.get("Modifier", 100))
        return 100

    regen = merged.get("ChangesHealth@ELITE") or {}
    return {
        "firepower_veteran": _mod("FirepowerMultiplier", "rank-veteran && !rank-elite"),
        "firepower_elite": _mod("FirepowerMultiplier", "rank-elite"),
        "damage_received_veteran": _mod("DamageMultiplier", "rank-veteran && !rank-elite"),
        "damage_received_elite": _mod("DamageMultiplier", "rank-elite"),
        "speed_veteran": _mod("SpeedMultiplier", "rank-veteran && !rank-elite"),
        "speed_elite": _mod("SpeedMultiplier", "rank-elite"),
        "reload_delay_veteran": _mod("ReloadDelayMultiplier", "rank-veteran && !rank-elite"),
        "reload_delay_elite": _mod("ReloadDelayMultiplier", "rank-elite"),
        "regen_step": int(regen.get("Step", 0)) if isinstance(regen, dict) else 0,
        "regen_delay": int(regen.get("Delay", 100)) if isinstance(regen, dict) else 100,
    }


def _export_armaments(merged: dict[str, Any]) -> list[dict[str, Any]]:
    arms: list[dict[str, Any]] = []
    for key, block in trait_blocks(merged, "Armament"):
        weapon = block.get("Weapon")
        if not weapon:
            continue
        arms.append({
            "id": key,
            "weapon": str(weapon),
            "requires_condition": block.get("RequiresCondition"),
            "name": block.get("Name", "primary"),
        })
    return arms


def _is_battle_pool(merged: dict[str, Any]) -> bool:
    if "Health" not in merged or "Mobile" not in merged:
        return False
    if "Buildable" not in merged:
        return False
    cats = _nested_get(merged, "MapEditorData", "Categories") or ""
    cat_s = str(cats).lower()
    if "structure" in cat_s or "building" in cat_s:
        return False
    return True


def _projectile_blockable(proj: Any) -> bool:
    if not isinstance(proj, dict):
        return False
    kind = str(proj.get("@value", ""))
    if kind in ("ArcLaserZap", "LaserZap", "InstantHit"):
        return False
    if proj.get("Blockable") is False:
        return False
    return bool(proj.get("Speed") or parse_wdist(proj.get("Speed")))


def _export_targetable_layers(merged: dict[str, Any]) -> list[dict[str, Any]]:
    """导出全部 Targetable 层；战中由 effective_target_types() 按 RequiresCondition 求值。"""
    layers: list[dict[str, Any]] = []
    for key, tb in trait_blocks(merged, "Targetable"):
        tt = split_csv(tb.get("TargetTypes"))
        if not tt:
            continue
        layers.append({
            "id": key,
            "types": tt,
            "requires_condition": tb.get("RequiresCondition"),
        })
    return layers


def _export_target_types(merged: dict[str, Any]) -> list[str]:
    """斗蛐蛐默认态下成立的 TargetTypes（fallback；战中见 effective_target_types）。"""
    types: set[str] = set()
    for key, tb in trait_blocks(merged, "Targetable"):
        tt = split_csv(tb.get("TargetTypes"))
        if not tt:
            continue
        if "MindControl" in tt:
            types.update(tt)
            continue
        if _targetable_active(tb):
            types.update(tt)
    return sorted(types)


def _export_speed(merged: dict[str, Any]) -> int:
    mobile = merged.get("Mobile") or {}
    if mobile.get("Speed") is not None:
        return int(mobile["Speed"])
    aircraft = merged.get("Aircraft") or {}
    if aircraft.get("Speed") is not None:
        return int(aircraft["Speed"])
    return 1


def _export_carrier_parent(merged: dict[str, Any]) -> dict[str, Any] | None:
    block = merged.get("CarrierParent")
    if not isinstance(block, dict):
        return None
    actors_raw = str(block.get("Actors", ""))
    actors = [a.strip() for a in actors_raw.split(",") if a.strip()]
    if not actors:
        return None
    return {
        "actors": actors,
        "respawn_ticks": int(block.get("RespawnTicks", 300)),
        "spawn_all_at_once": bool(block.get("SpawnAllAtOnce", True)),
    }


def _export_ammo_max(merged: dict[str, Any]) -> int | None:
    pool = merged.get("AmmoPool")
    if isinstance(pool, dict) and pool.get("Ammo") is not None:
        return int(pool["Ammo"])
    return None


def _build_actor_record(
    aid: str,
    merged: dict[str, Any],
    locomotors: dict[str, dict[str, Any]],
    *,
    spawn_only: bool,
) -> dict[str, Any]:
    mobile = merged.get("Mobile") or {}
    loc_name = str(mobile.get("Locomotor", "foot"))
    if "CarrierChild" in merged or (merged.get("Aircraft") and not mobile):
        loc_name = "aircraft"
    loc = locomotors.get(loc_name, {"shares_cell": False, "crushes": []})

    tooltip = merged.get("Tooltip") or {}
    name = tooltip.get("Name") or aid
    buildable = merged.get("Buildable") or {}
    desc = buildable.get("Description") or ""

    turret = merged.get("Turreted")
    turret_turn = (
        int(turret["TurnSpeed"]) if isinstance(turret, dict) and turret.get("TurnSpeed") else None
    )
    attack_t = merged.get("AttackTurreted") or {}
    facing_tol = (
        int(attack_t["FacingTolerance"])
        if isinstance(attack_t, dict) and attack_t.get("FacingTolerance") is not None
        else 512
    )
    rearm = merged.get("Rearmable")
    rearm_actors: list[str] = []
    if isinstance(rearm, dict) and rearm.get("RearmActors"):
        rearm_actors = split_csv(rearm.get("RearmActors"))
    takeoff = 0
    if "CarrierChild" in merged and merged.get("Aircraft"):
        takeoff = 8

    bp = merged.get("BlocksProjectiles")
    blocks = isinstance(bp, dict)
    bp_height = parse_wdist(bp.get("Height")) if blocks else None
    bp_rels = split_csv(bp.get("ValidRelationships")) if blocks else []

    return {
        "id": aid,
        "name": str(name),
        "description": str(desc).strip(),
        "categories": str(_nested_get(merged, "MapEditorData", "Categories") or ""),
        "cost": int(_nested_get(merged, "Valued", "Cost") or 0),
        "hp": int(_nested_get(merged, "Health", "HP") or 1),
        "armor": str(_nested_get(merged, "Armor", "Type") or "None"),
        "speed": _export_speed(merged),
        "locomotor": loc_name,
        "shares_cell": bool(loc.get("shares_cell", False)),
        "crushes": list(loc.get("crushes", [])),
        "target_types": _export_target_types(merged),
        "targetable_layers": _export_targetable_layers(merged),
        "crushable": "Crushable" in merged,
        "armaments": _export_armaments(merged),
        "auto_target_priorities": _export_auto_target(merged),
        "gains_experience": _export_gains_experience(merged),
        "spawn_only": spawn_only,
        "mind_controllable": "MindControllable" in merged,
        "mind_controller": "MindController" in merged,
        "carrier_parent": _export_carrier_parent(merged),
        "carrier_child": "CarrierChild" in merged,
        "ammo_max": _export_ammo_max(merged),
        "turret_turn_speed": turret_turn,
        "facing_tolerance": facing_tol if turret_turn else None,
        "rearmable_actors": rearm_actors,
        "takeoff_ticks": takeoff,
        "blocks_projectiles": blocks,
        "blocks_projectiles_height": bp_height if bp_height is not None else 1024,
        "blocks_projectiles_relationships": bp_rels,
    }


def _export_actors(
    raw_rules: dict[str, dict[str, Any]],
    locomotors: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    out: dict[str, dict[str, Any]] = {}
    spawn_ids: set[str] = set()

    for aid in raw_rules:
        if aid.startswith("^"):
            continue
        try:
            merged = merge_actor(aid, raw_rules, cache)
        except (KeyError, ValueError):
            continue
        if not _is_battle_pool(merged):
            continue
        rec = _build_actor_record(aid, merged, locomotors, spawn_only=False)
        out[aid] = rec
        cp = rec.get("carrier_parent")
        if isinstance(cp, dict):
            spawn_ids.update(cp.get("actors", []))

    for sid in sorted(spawn_ids):
        if sid in out or sid.startswith("^"):
            continue
        try:
            merged = merge_actor(sid, raw_rules, cache)
        except (KeyError, ValueError):
            continue
        if "Health" not in merged:
            continue
        out[sid] = _build_actor_record(sid, merged, locomotors, spawn_only=True)

    return out


def export(vendor_ra2: Path) -> Path:
    mod = vendor_ra2 / "mods" / "ra2"
    rules_dir = mod / "rules"
    weapons_dir = mod / "weapons"
    if not rules_dir.is_dir():
        raise FileNotFoundError(f"未找到规则目录: {rules_dir}，请先克隆 vendor/openra-ra2")

    raw_rules = load_rules_dir(rules_dir)
    raw_weapons = load_weapons_dir(weapons_dir)

    world_cache: dict[str, dict[str, Any]] = {}
    world_merged = merge_actor("^BaseWorld", raw_rules, world_cache)
    locomotors = _export_locomotors(world_merged)
    weapons = _export_weapons(raw_weapons)
    actors = _export_actors(raw_rules, locomotors)
    veterancy = _export_veterancy_rules(raw_rules)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("locomotors.json", locomotors),
        ("weapons.json", weapons),
        ("actors.json", actors),
        ("veterancy.json", veterancy),
    ):
        path = OUT_DIR / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "source": "OpenRA/ra2",
        "vendor_path": str(vendor_ra2.resolve()),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "actor_count": len(actors),
        "weapon_count": len(weapons),
        "locomotor_count": len(locomotors),
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"导出完成: {len(actors)} 单位, {len(weapons)} 武器 -> {OUT_DIR}")
    return OUT_DIR


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--vendor", type=Path, default=DEFAULT_VENDOR)
    args = p.parse_args()
    export(args.vendor.resolve())


if __name__ == "__main__":
    main()
