"""Generate the civ-war combat-tech pool from AoE3 game data.

The runtime pool keeps only effects that the battle model can consume:
combat effects and unit-cost effects. Non-combat effects are not written into
the runtime pool. Unclassified ``Data`` / ``Data2`` effects are reported as
generation errors so a game-data refresh cannot silently change combat
behavior.

The generator also validates the explicit per-civilization generic-tech pools
in ``seeds/aoe3/civ_war_generic_techs.json``. Auto-composed lineups are
expected to draw compensation techs from those pools only.

Usage:
    uv run python scripts/crawler/aoe3_civ_war_tech_pool.py
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TECHTREE_PATH = ROOT / "data" / "aoe3" / "raw" / "techtreey.xml"
STRINGTABLE_PATH = ROOT / "data" / "aoe3" / "raw" / "stringtabley_zh.xml"
CIVS_PATH = ROOT / "seeds" / "aoe3" / "civs.json"
HOMECITY_DIR = ROOT / "data" / "aoe3" / "raw" / "homecity"
OUTPUT_PATH = ROOT / "seeds" / "aoe3" / "civ_war_tech_pool.json"
GENERIC_PATH = ROOT / "seeds" / "aoe3" / "civ_war_generic_techs.json"
LINKS_PATH = ROOT / "seeds" / "aoe3" / "tech_links.json"
AVAILABLE_TECH_PATH = ROOT / "seeds" / "aoe3" / "civ_available_techs.json"

sys.path.insert(0, str(ROOT / "src"))

from plugins.aoe3.repository import UnitRepo  # noqa: E402
from plugins.games.aoe3_battle.lineup import (  # noqa: E402
    _is_building,
    _is_pure_healer,
    _is_ship,
    _is_villager,
)

# Technologies that are intentionally excluded from the runtime pool because
# they depend on mechanics the battle model does not implement. Excluding the
# whole row keeps the pool schema free of audit-only effect buckets.
EXCLUDED_TECH_IDS = {
    "DEHCMaguzawa",
}

NON_COMBAT_TARGET_TAGS = {
    "AbstractVillager",
    "AbstractBuilding",
    "AbstractWagon",
    "Building",
    "Ship",
    "AbstractWarShip",
    "Hero",
    "Guardian",
    "AbstractPet",
    "AbstractFindScout",
    "LogicalTypeLandEconomy",
}
NON_COMBAT_TARGET_PREFIXES = (
    "deSPC",
    "SPC",
)
NON_COMBAT_ACTIONS = {
    "AutoGatherFood",
    "AutoGatherGold",
    "AutoGatherInfluence",
    "AutoGatherWood",
    "Build",
    "Gather",
    "GatherField",
    "Repair",
    "TreeGatherRateBonus",
}

AGE_STATUS = {
    "Colonialize": 2,
    "Fortressize": 3,
    "Industrialize": 4,
    "Imperialize": 5,
}
CARD_AGE_TO_CIV_WAR_AGE = {
    0: 3,
    1: 3,
    2: 3,
    3: 3,
    4: 4,
    5: 5,
}

# Effects that can change combat behavior. This is intentionally broader than
# the current simulator field list: the pool records what the game data says,
# and the runtime decides what it can apply. ``Data2`` uses the same subtype
# vocabulary as ``Data`` and is handled through the same maps.
COMBAT_SUBTYPES = {
    # Core per-unit combat attributes.
    "Hitpoints",
    "HitPoints",
    "Damage",
    "DamageBonus",
    "DamageArea",
    "DamageCap",
    "MaximumRange",
    "MinimumRange",
    "RateOfFire",
    "MaximumVelocity",
    "ArmorSpecific",
    "Armor",
    "ArmorType",
    # Action / tactic mechanics that can alter what a unit can attack and how.
    "ActionAdd",
    "ActionAddAttachingUnit",
    "ActionEnable",
    "AttackPriority",
    "AutoAttackType",
    "DamageMultiplier",
    "DamageForAllHandLogicActions",
    "DamageForAllRangedLogicActions",
    "GarrisonBonusDamage",
    "HitPercent",
    "HitPercentType",
    "ProtoActionAdd",
    "RangeForAllRangedLogicActions",
    "RechargeTime",
    "SelfDamageMultiplier",
    "SetActionFlag",
    "SetProjectile",
    "SetTacticDataOverride",
    "Snare",
    "SpeedModifier",
    "TacticArmor",
    "TacticEnable",
    "InitialTactic",
    # Unit type changes can alter matchups and combat behavior.
    "AddContainedBonusType",
    "AddContainedType",
    "SetUnitType",
    # Persistent unit-state mechanics.
    "ContainedHitpointBonus",
    "ConversionDelay",
    "ConversionResistance",
    "DodgeChance",
    "EnableDodge",
    "UnitRegenAbsolute",
    "UnitRegenRate",
    "UnitRegenRateLimit",
    "VeterancyBonus",
    "VeterancyEnable",
    "UnitRegenIgnoreOnStealth",
}
COST_SUBTYPES = {"Cost"}
KNOWN_NON_COMBAT_SUBTYPES = {
    # Shipments / spawns / transforms that do not change the current lineup.
    "FreeHomeCityUnit",
    "FreeHomeCityUnitByKBQuery",
    "FreeHomeCityUnitByKBStat",
    "FreeHomeCityUnitByShipmentCount",
    "FreeHomeCityUnitByShipmentCountResource",
    "FreeHomeCityUnitIfTechObtainable",
    "FreeHomeCityUnitByTechActiveCount",
    "FreeHomeCityUnitByUnitCount",
    "FreeHomeCityUnitRandom",
    "FreeHomeCityUnitResource",
    "FreeHomeCityUnitResourceIfTechActive",
    "FreeHomeCityUnitResourceIfTechObtainable",
    "FreeHomeCityUnitShipped",
    "FreeHomeCityUnitTechActiveCycle",
    "FreeHomeCityUnitToGatherPoint",
    "PartisanUnit",
    "ResourceAsCratesByKBStat",
    "ResourceAsCratesByShipmentCount",
    "RevealEnemyLOS",
    "RevealLOS",
    "RevealMap",
    "AddTrain",
    "Enable",
    "RemoveUnits",
    "ReviveUnit",
    "ReplaceUnit",
    "TransformUnit",
    "DeadReplacement",
    "DeadTransform",
    # Economy, population, production and infrastructure.
    "AddTrickleByResource",
    "AutoGatherBonus",
    "BuildingWorkRate",
    "BuildLimit",
    "BuildLimitIncrement",
    "BuildBounty",
    "BuildBountySpecific",
    "CarryCapacity",
    "CommunityPlazaWeight",
    "BountyResourceExtra",
    "BountyResourceOverride",
    "BountySpecificBonus",
    "BuildPoints",
    "BuilderLimit",
    "CalculateInfluenceCost",
    "CostBuildingTechs",
    "DamageTimeoutTrickle",
    "FreeBuildPoints",
    "FreeBuildRate",
    "FreeRepair",
    "GatherBonus",
    "GatherResourceOverride",
    "GathererLimit",
    "GatheringMultiplier",
    "InventoryAmount",
    "InventoryRate",
    "InvestResource",
    "InvestmentEnable",
    "KillBounty",
    "LOS",
    "Lifespan",
    "LivestockExchangeRate",
    "LivestockMinCapacityKeepUnit",
    "LivestockRecoveryRate",
    "MaintainTrainPoints",
    "MaintainWorkRateMultiplier",
    "MaximumContained",
    "MaximumResourceTrickleRate",
    "MinimumResourceTrickleRate",
    "ModifyRate",
    "PopulationCount",
    "PopulationCap",
    "PopulationCapAddition",
    "PopulationCapBonus",
    "PopulationCapExtra",
    "PopulationScaling",
    "PopulationScalingCap",
    "PlayerSpecificTrainLimitPerAction",
    "ResearchPoints",
    "Resource",
    "ResourceByKBQuery",
    "ResourceByKBStat",
    "ResourceByUnitCount",
    "ResourceIfTechActive",
    "ResourceIfTechObtainable",
    "ResourceReturn",
    "ResourceReturnRate",
    "ResourceReturnRateTotalCost",
    "ResourceTrickleRate",
    "ScoreValue",
    "TrainPoints",
    "TrainBatchSize",
    "WorkRate",
    "WorkRateSpecific",
    "Yield",
    # UI, names, icons, presentation and source plumbing.
    "ActionDisplayName",
    "AgeUpCostAbsoluteKillXPFactor",
    "AgeUpCostAbsoluteRateCap",
    "AuxRechargeTime",
    "DisplayedRange",
    "AnimationRate",
    "CopyTacticAnims",
    "CopyTechIcon",
    "CopyUnitPortraitAndIcon",
    "EnemyShipmentDelay",
    "FakeConversion",
    "NextAgeUpCostAbsoluteShipmentRate",
    "NextAgeUpDoubleEffect",
    "NextAgeUpTimeAbsolute",
    "NextAgeUpTimeFactor",
    "NextAgeUpTimeFactorShipmentRate",
    "SetImpactEffect",
    "SetName",
    "TextOutput",
    "TextOutputTechName",
    "UIAlert",
    "UnitHelpOverride",
    "UpdateVisual",
    "UseRandomNames",
    # Other non-unit-combat state.
    "AddHomeCityCard",
    "AddSharedBuildLimitUnitType",
    "AllowedAge",
    "AlliedShipmentTax",
    "AlliedShipmentTaxResource",
    "BlockRandomCard",
    "Blockade",
    "CommandAdd",
    "CommandRemove",
    "CreatePower",
    "EnableAutoCrateGather",
    "EnableAutoFormations",
    "EnableTechXPReward",
    "EnableTradeRouteLOS",
    "ForbidTech",
    "GrantsPowerDuration",
    "HomeCityBucketCountIncrement",
    "HomeCityBucketCountPoints",
    "HomeCityBucketMaxCount",
    "HomeCityBucketMinCount",
    "HomeCityCardMakeInfinite",
    "HomeCityShipmentModifier",
    "InitiateRevolution",
    "Market",
    "MarketReset",
    "PlacementRulesOverride",
    "PowerDataOverride",
    "PowerROF",
    "RandomTech",
    "ResetActiveOnce",
    "ResetHomeCityCardCount",
    "ResetResendableCards",
    "ResourceExchange",
    "ResourceExchange2",
    "ResourceInventoryExchange",
    "RevertRevolution",
    "SendRandomCard",
    "SetAge",
    "SetCivFlag",
    "SetCivRelation",
    "SetForceFullTechUpdate",
    "SetNextResearchFree",
    "SetOnBuildingDeathTech",
    "SetOnShipmentSentTech",
    "SetOnTechResearchedTech",
    "SharedLOS",
    "ShipmentTax",
    "ShipmentTaxCardName",
    "ShipmentTaxPlayerName",
    "ShipmentTaxResource",
    "ShipmentTaxSpecific",
    "ShipmentTaxTollRegister",
    "SharedBuildLimitUnit",
    "SharedSettlerBuildLimit",
    "Sound",
    "SquareAura",
    "SplitCost",
    "SubCivAllianceCostMultiplier",
    "TechCostAbsoluteBountyRate",
    "TechStatus",
    "TradeMonopoly",
    "TradeRouteBonusTeam",
    "UpgradeAllTradeRoutes",
    "UpgradeSubCivAlliance",
    "UpgradeTradeRoute",
    "XPRate",
    "tributePenalty",
    "TrickleByUnitType",
}

UNSUPPORTED_COMBAT_SUBTYPES = {
    # Recognized as potentially combat-relevant, but not implemented by the
    # current simulator. Keeping these out of the runtime pool is deliberate.
    "EmpowerArea",
    "EmpowerModify",
}

KNOWN_NON_COMBAT_PROTO_UNIT_FLAGS = {
    "AllowGatheringWhenFull",
    "DisableRowWrapping",
    "DontTrainInBatches",
    "DrawnToCrates",
    "EnableShipmentTax",
    "EnterHotkeyContext",
    "ForceFullTechUpdate",
    "HasGatherPoint",
    "HeroName2",
    "MagnetDoesNotLockUnits",
    "ShowTactics",
    "ShowUnitResourceActionRates",
    "TotalAutoGatherRates",
    "UseSharedBuildLimit",
    # Scenario and non-lineup units. These never enter the civ-war regular
    # lineup, and their flags are scenario-control or non-combat metadata.
    "flagid:12",
    "flagid:42",
    "flagid:103",
    "flagid:173",
    "flagid:182",
    "flagid:197",
    "flagid:206",
    "flagid:230",
    "flagid:233",
    "flagid:235",
    "flagid:241",
    "ContainedHitPointBonusRate",
}

KNOWN_NON_COMBAT_EFFECT_TYPES = {
    "AddHomeCityCard",
    "AddTrickleByResource",
    "Blockade",
    "CommandAdd",
    "CommandRemove",
    "CreatePower",
    "ForbidTech",
    "HomeCityCardMakeInfinite",
    "InitiateRevolution",
    "RandomTech",
    "ReplaceUnit",
    "ResetActiveOnce",
    "ResetHomeCityCardCount",
    "ResetResendableCards",
    "ResourceExchange",
    "ResourceExchange2",
    "ResourceInventoryExchange",
    "RevertRevolution",
    "SetAge",
    "SetName",
    "SetOnBuildingDeathTech",
    "SetOnShipmentSentTech",
    "SetOnTechResearchedTech",
    "SharedLOS",
    "Sound",
    "TechStatus",
    "TextEffectOutput",
    "TextOutput",
    "TextOutputTechName",
    "TransformUnit",
    "UIAlert",
}

def _load_stringtable() -> dict[str, str]:
    text = STRINGTABLE_PATH.read_text(encoding="utf-8")
    return {
        locid: re.sub(r"<[^>]+>", "", value).strip()
        for locid, value in re.findall(
            r'<string _locid="(\d+)"[^>]*>(.*?)</string>',
            text,
            re.DOTALL,
        )
    }


def _load_civ_ownership() -> tuple[
    dict[str, set[str]],
    dict[str, dict[str, int]],
]:
    """Return explicit curated-civ tech ownership and home-city card ages."""
    available = json.loads(
        AVAILABLE_TECH_PATH.read_text(encoding="utf-8")
    )["civs"]
    tech_owners: dict[str, set[str]] = {}
    card_ages: dict[str, dict[str, int]] = {}
    for civ_id, tech_data in available.items():
        for tech in tech_data.get("all", ()):
            tech_owners.setdefault(tech, set()).add(civ_id)

    curated = set(available)
    for path in sorted(HOMECITY_DIR.glob("homecity*.xml")):
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            continue
        civ_id = (root.findtext("civ") or "").strip()
        if civ_id not in curated:
            continue
        for card in root.findall("./cards/card"):
            tech_id = (card.findtext("name") or "").strip()
            if not tech_id:
                continue
            tech_owners.setdefault(tech_id, set()).add(civ_id)
            raw_age = (card.findtext("age") or "").strip()
            try:
                age = int(raw_age)
            except ValueError:
                continue
            if age > 0:
                civ_card_ages = card_ages.setdefault(tech_id, {})
                civ_card_ages[civ_id] = min(
                    age,
                    civ_card_ages.get(civ_id, age),
                )
    return tech_owners, card_ages


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _target_refs(effect: ET.Element) -> list[dict[str, str]]:
    return [
        {
            "type": target.get("type") or "",
            "value": (target.text or "").strip(),
        }
        for target in effect.findall("target")
        if (target.text or "").strip()
    ]


def _tech_age(
    tech: ET.Element,
    *,
    card_ages: dict[str, dict[str, int]],
) -> int | None:
    for effect in tech.findall("./effects/effect"):
        if effect.get("type") == "SetAge" and (effect.text or "").strip():
            match = re.fullmatch(r"Age(\d)", (effect.text or "").strip())
            if match:
                return int(match.group(1)) + 1
    statuses = [
        (node.text or "").strip()
        for node in tech.findall("./prereqs/techstatus")
    ]
    ages = [AGE_STATUS[status] for status in statuses if status in AGE_STATUS]
    if ages:
        return max(3, max(ages))
    tech_id = tech.get("name") or ""
    card_values = [
        max(3, CARD_AGE_TO_CIV_WAR_AGE[age])
        for age in card_ages.get(tech_id, {}).values()
        if age in CARD_AGE_TO_CIV_WAR_AGE
    ]
    return min(card_values) if card_values else None


def _is_age_upgrade(tech: ET.Element) -> bool:
    """Return true for explicit or implicit age-up technologies."""
    flags = {flag.text for flag in tech.findall("flag") if flag.text}
    if "Shadow" in flags:
        return True
    return any(
        effect.get("type") == "SetAge"
        for effect in tech.findall("./effects/effect")
    )


def _normalise_op(effect: ET.Element) -> dict[str, Any]:
    result = {
        key: value
        for key, value in effect.attrib.items()
        if key != "type" and value
    }
    result["effect_type"] = effect.get("type") or ""
    result["targets"] = _target_refs(effect)
    if "amount" in result:
        result["amount"] = _number(result["amount"])
    return result


def _classify_op(
    op: dict[str, Any],
) -> str | None:
    effect_type = op.get("effect_type") or ""
    subtype = op.get("subtype")
    if effect_type in {"Data", "Data2"}:
        if subtype in COMBAT_SUBTYPES:
            return "combat_ops"
        if subtype in COST_SUBTYPES:
            return "cost_ops"
        if subtype in KNOWN_NON_COMBAT_SUBTYPES:
            return None
        if subtype in UNSUPPORTED_COMBAT_SUBTYPES:
            return "unsupported"
        if subtype == "ProtoUnitFlag":
            flagname = str(op.get("flagname") or "")
            flagid = str(op.get("flagid") or "")
            if flagname in KNOWN_NON_COMBAT_PROTO_UNIT_FLAGS:
                return None
            if flagid and f"flagid:{flagid}" in KNOWN_NON_COMBAT_PROTO_UNIT_FLAGS:
                return None
        return "unclassified"
    if effect_type in KNOWN_NON_COMBAT_EFFECT_TYPES:
        return None
    return "unclassified"


def _unit_targets(ops: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(target["value"]).lower()
            for op in ops
            for target in op.get("targets", ())
            if target.get("type") == "ProtoUnit"
        }
    )


def _parse_tech(
    tech: ET.Element,
    *,
    stringtable: dict[str, str],
    tech_owners: dict[str, set[str]],
    card_ages: dict[str, dict[str, int]],
    census: Counter[tuple[str, str]],
) -> dict[str, Any] | None:
    tech_id = tech.get("name")
    if not tech_id:
        return None
    if tech_id in EXCLUDED_TECH_IDS:
        return None

    combat_ops: list[dict[str, Any]] = []
    cost_ops: list[dict[str, Any]] = []
    unclassified: list[dict[str, Any]] = []
    for effect in tech.findall("./effects/effect"):
        op = _normalise_op(effect)
        bucket = _classify_op(op)
        census[(op.get("effect_type") or "", op.get("subtype") or "<none>")] += 1
        if bucket == "combat_ops":
            combat_ops.append(op)
        elif bucket == "cost_ops":
            cost_ops.append(op)
        elif bucket == "unsupported":
            unclassified.append(op)
        elif bucket == "unclassified":
            unclassified.append(op)

    if unclassified:
        tech_id = tech.get("name") or "<unnamed>"
        details = ", ".join(
            f"{op.get('effect_type')}/{op.get('subtype') or op.get('effect_type')}"
            for op in unclassified
        )
        raise ValueError(f"{tech_id}: unsupported effects: {details}")

    if not combat_ops and not cost_ops:
        return None

    display_id = (tech.findtext("displaynameid") or "").strip()
    rollover_id = (tech.findtext("rollovertextid") or "").strip()
    targets = _unit_targets([*combat_ops, *cost_ops])
    civ_ids = sorted(tech_owners.get(tech_id, set()))
    flags = [flag.text for flag in tech.findall("flag") if flag.text]
    source_kind = "global"
    if tech_id in tech_owners:
        source_kind = "owned"

    return {
        "id": tech_id,
        "name_zh": stringtable.get(display_id, ""),
        "description_zh": stringtable.get(rollover_id, ""),
        "source_flags": flags,
        "source_kind": source_kind,
        "civ_ids": civ_ids,
        "is_age_upgrade": _is_age_upgrade(tech),
        "min_age": _tech_age(tech, card_ages=card_ages),
        "targets": targets,
        "combat_ops": combat_ops,
        "cost_ops": cost_ops,
    }


def build_pool() -> dict[str, Any]:
    stringtable = _load_stringtable()
    tech_owners, card_ages = _load_civ_ownership()
    tech_root = ET.parse(TECHTREE_PATH).getroot()
    census: Counter[tuple[str, str]] = Counter()
    rows = [
        row
        for tech in tech_root.findall("tech")
        if (row := _parse_tech(
            tech,
            stringtable=stringtable,
            tech_owners=tech_owners,
            card_ages=card_ages,
            census=census,
        ))
    ]
    rows.sort(key=lambda row: row["id"])
    return {
        "_meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "source": "data/aoe3/raw/techtreey.xml",
            "doc": "docs/games/aoe3-civ-war-wip.md",
            "combat_subtypes": sorted(COMBAT_SUBTYPES),
            "cost_subtypes": sorted(COST_SUBTYPES),
            "effect_census": [
                {
                    "effect_type": effect_type,
                    "subtype": subtype,
                    "count": count,
                }
                for (effect_type, subtype), count in sorted(census.items())
            ],
            "unknown_subtypes": sorted(
                {
                    subtype
                    for effect_type, subtype in census
                    if effect_type in {"Data", "Data2"}
                    and subtype not in COMBAT_SUBTYPES
                    and subtype not in COST_SUBTYPES
                    and subtype not in KNOWN_NON_COMBAT_SUBTYPES
                    and subtype not in UNSUPPORTED_COMBAT_SUBTYPES
                }
            ),
            "rule": (
                "运行池只保留战斗和成本效果; 已知非战斗效果不写入; "
                "未识别或未支持效果使生成失败"
            ),
        },
        "techs": rows,
    }


def _generic_targets(row: dict[str, Any]) -> list[str]:
    values: set[str] = set()
    for op in [*row.get("combat_ops", ()), *row.get("cost_ops", ())]:
        for target in op.get("targets", ()):
            if target.get("type") == "ProtoUnit" and target.get("value"):
                values.add(str(target["value"]))
        unittype = op.get("unittype")
        if unittype:
            values.add(str(unittype))
    return sorted(values)


def _combat_unit_target_universe() -> tuple[set[str], set[str]]:
    """Return (unit ids, tags) that can appear in a civ-war lineup."""
    repo = UnitRepo.get()
    unit_ids: set[str] = set()
    unit_tags: set[str] = set()
    for unit in repo.all_units:
        if not unit.cost or not unit.has_attack or unit.hp <= 0:
            continue
        if (
            _is_building(unit)
            or _is_ship(unit)
            or _is_villager(unit)
            or _is_pure_healer(unit)
        ):
            continue
        unit_ids.add(unit.id.lower())
        unit_tags.update(unit.type)
    return unit_ids, unit_tags


def _has_eligible_generic_target(
    row: dict[str, Any],
    unit_ids: set[str],
    unit_tags: set[str],
) -> bool:
    for target in _generic_targets(row):
        if target.lower() in unit_ids or target in unit_tags:
            return True
    return False


_REVOLUTION_ID_PREFIXES = ("DEHCREV", "DEREV")


def _is_revolution_tech(row: dict[str, Any]) -> bool:
    """Match ``civ_war_techs.is_revolution_tech``.

    Revolution cards live in the same home-city file as ordinary cards, so
    ownership alone would let them into lineup selection and civ-war auto
    compensation. Both modes read this generic pool.
    """
    tech_id = str(row.get("id") or "")
    if tech_id.startswith(_REVOLUTION_ID_PREFIXES):
        return True
    return "RevoltTech" in set(row.get("source_flags") or ())


def _has_generic_combat_effect(row: dict[str, Any]) -> bool:
    return any(
        str(op.get("action") or "") not in NON_COMBAT_ACTIONS
        for op in row.get("combat_ops", ())
    )


def build_generic_tech_pool() -> dict[str, Any]:
    """Build the explicit per-civ generic compensation pool."""
    pool = build_pool()
    available = json.loads(
        AVAILABLE_TECH_PATH.read_text(encoding="utf-8")
    )["civs"]
    unit_ids, unit_tags = _combat_unit_target_universe()
    result: dict[str, list[str]] = {civ_id: [] for civ_id in available}
    for row in pool["techs"]:
        if row.get("is_age_upgrade"):
            continue
        if _is_revolution_tech(row):
            continue
        if not row.get("combat_ops") and not row.get("cost_ops"):
            continue
        if not _has_eligible_generic_target(row, unit_ids, unit_tags):
            continue
        if not _has_generic_combat_effect(row):
            continue
        for civ_id in row.get("civ_ids", ()):
            if civ_id in result:
                result[civ_id].append(row["id"])
    return {
        "_meta": {
            "doc": "docs/games/aoe3-civ-war-wip.md",
            "status": "generated_v1",
            "note": "自动组合只从对应文明的通用战斗科技池中选补偿科技。",
            "rule": (
                "文明真源可获得、非时代升级、非革命卡且能作用于国战参战单位类型的"
                "战斗/成本科技; 质变科技也允许入池。配兵与国战共用此池。"
            ),
        },
        "civs": {
            civ_id: sorted(tech_ids)
            for civ_id, tech_ids in result.items()
        },
    }


def main() -> None:
    pool = build_pool()
    OUTPUT_PATH.write_text(
        json.dumps(pool, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"techs={len(pool['techs'])}")
    print(f"wrote {OUTPUT_PATH}")

    generic = build_generic_tech_pool()
    GENERIC_PATH.write_text(
        json.dumps(generic, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "generic_techs="
        f"{sum(len(ids) for ids in generic['civs'].values())}"
    )
    print(f"wrote {GENERIC_PATH}")

    links = build_tech_links()
    LINKS_PATH.write_text(
        json.dumps(links, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"tech_links={len(links['techs'])}")
    print(f"wrote {LINKS_PATH}")


def build_tech_links() -> dict[str, Any]:
    """Unlock graph from techtreey.xml, used to settle a tech with what it unlocks.

    ``activates``: ``TechStatus active`` targets (the game researches them at once).
    ``obtains``: ``TechStatus obtainable`` targets.
    ``requires``: ``<techstatus status="Active">`` prerequisites.
    ``other_prereq``: any prerequisite the battle cannot evaluate (unit counts,
    stats, a specific age gate, or a non-Active status). Such a tech never fires
    from prerequisites alone.
    """
    root = ET.parse(TECHTREE_PATH).getroot()
    techs: dict[str, dict[str, Any]] = {}
    for tech in root.findall("tech"):
        name = (tech.get("name") or "").strip()
        if not name:
            continue
        activates: list[str] = []
        obtains: list[str] = []
        for effect in tech.findall("./effects/effect"):
            if effect.get("type") != "TechStatus":
                continue
            target = (effect.text or "").strip()
            status = (effect.get("status") or "").lower()
            if not target:
                continue
            if status == "active":
                activates.append(target)
            elif status == "obtainable":
                obtains.append(target)
        requires: list[str] = []
        other = False
        for prereq in tech.findall("./prereqs/*"):
            if (
                prereq.tag == "techstatus"
                and (prereq.get("status") or "").lower() == "active"
                and (prereq.text or "").strip()
            ):
                requires.append((prereq.text or "").strip())
            else:
                other = True
        flags = {flag.text for flag in tech.findall("flag") if flag.text}
        shadow = "Shadow" in flags
        if not (activates or obtains or requires or other or shadow):
            continue
        row: dict[str, Any] = {}
        if activates:
            row["activates"] = activates
        if obtains:
            row["obtains"] = obtains
        if requires:
            row["requires"] = requires
        if other:
            row["other_prereq"] = True
        if "OrPrereqs" in flags:
            row["or_prereqs"] = True
        if shadow:
            row["shadow"] = True
        if (tech.findtext("status") or "").strip().upper() == "OBTAINABLE":
            row["obtainable"] = True
        techs[name] = row
    return {
        "_meta": {
            "source": "data/aoe3/raw/techtreey.xml",
            "doc": "docs/wip/aoe3-tech-effects.md",
        },
        "techs": dict(sorted(techs.items())),
    }


if __name__ == "__main__":
    main()
