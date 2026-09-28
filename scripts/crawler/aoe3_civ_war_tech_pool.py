"""Generate the civ-war combat-tech pool from AoE3 game data.

The pool keeps a technology whenever it changes the combat behavior or the
resource cost of a playable unit. Non-combat effects are recorded separately
and are ignored at runtime. A technology with both a combat effect and a
shipment is preserved; only its shipment/economic effects are marked as
ignored. Unknown effect subtypes are kept in ``unknown_ops`` instead of being
silently treated as harmless, so future data refreshes stay auditable.

Usage:
    uv run python scripts/crawler/aoe3_civ_war_tech_pool.py
"""

from __future__ import annotations

import json
import re
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
IGNORED_SUBTYPES = {
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
    "InitialTactic",
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

IGNORED_EFFECT_TYPES = {
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
    dict[str, set[str]],
    dict[str, dict[str, int]],
]:
    """Return curated-civ ownership for techs, units, and home-city cards."""
    data = json.loads(CIVS_PATH.read_text(encoding="utf-8"))
    curated = set(data["_meta"]["curated_civs"])
    tech_owners: dict[str, set[str]] = {}
    unit_owners: dict[str, set[str]] = {}
    card_ages: dict[str, dict[str, int]] = {}
    for civ_id in curated:
        civ = data["civs"][civ_id]
        for tech in civ.get("unique_techs", ()):
            tech_owners.setdefault(tech, set()).add(civ_id)
        for unit_id in civ.get("units", ()):
            unit_owners.setdefault(unit_id.lower(), set()).add(civ_id)
    for unit_id, civ_ids in data.get("unit_civs", {}).items():
        for civ_id in civ_ids:
            if civ_id in curated:
                unit_owners.setdefault(unit_id.lower(), set()).add(civ_id)

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
    return tech_owners, unit_owners, card_ages


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
) -> tuple[str, str | None]:
    effect_type = op.get("effect_type") or ""
    subtype = op.get("subtype")
    if effect_type in {"Data", "Data2"}:
        if subtype in COMBAT_SUBTYPES:
            return "combat_ops", None
        if subtype in COST_SUBTYPES:
            return "cost_ops", None
        if subtype in IGNORED_SUBTYPES:
            return "ignored_ops", None
        return "unknown_ops", subtype or "<missing-subtype>"
    if effect_type in IGNORED_EFFECT_TYPES:
        return "ignored_ops", None
    return "unknown_ops", subtype or effect_type or "<missing-type>"


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
    unit_owners: dict[str, set[str]],
    card_ages: dict[str, dict[str, int]],
    census: Counter[tuple[str, str]],
) -> dict[str, Any] | None:
    tech_id = tech.get("name")
    if not tech_id:
        return None

    combat_ops: list[dict[str, Any]] = []
    cost_ops: list[dict[str, Any]] = []
    ignored_ops: list[dict[str, Any]] = []
    unknown_ops: list[dict[str, Any]] = []
    for effect in tech.findall("./effects/effect"):
        op = _normalise_op(effect)
        bucket, unknown = _classify_op(op)
        census[(op.get("effect_type") or "", op.get("subtype") or "<none>")] += 1
        if unknown is not None:
            op["unknown_reason"] = unknown
        if bucket == "combat_ops":
            combat_ops.append(op)
        elif bucket == "cost_ops":
            cost_ops.append(op)
        elif bucket == "ignored_ops":
            ignored_ops.append(op)
        else:
            unknown_ops.append(op)

    if not combat_ops and not cost_ops and not unknown_ops:
        return None

    display_id = (tech.findtext("displaynameid") or "").strip()
    rollover_id = (tech.findtext("rollovertextid") or "").strip()
    effective_ops = [*combat_ops, *cost_ops, *unknown_ops]
    targets = _unit_targets(effective_ops)
    civ_ids = sorted(tech_owners.get(tech_id, set()))
    if not civ_ids:
        civ_ids = sorted(
            {
                civ_id
                for target in targets
                for civ_id in unit_owners.get(target, set())
            }
        )
    flags = [flag.text for flag in tech.findall("flag") if flag.text]
    source_kind = "generic"
    if tech_id in tech_owners:
        source_kind = "owned"
    elif civ_ids:
        source_kind = "unit-derived"

    return {
        "id": tech_id,
        "name_zh": stringtable.get(display_id, ""),
        "description_zh": stringtable.get(rollover_id, ""),
        "source_flags": flags,
        "source_kind": source_kind,
        "civ_ids": civ_ids,
        "min_age": _tech_age(tech, card_ages=card_ages),
        "targets": targets,
        "review_status": "needs-review" if unknown_ops else "classified",
        "combat_ops": combat_ops,
        "cost_ops": cost_ops,
        "ignored_ops": ignored_ops,
        "unknown_ops": unknown_ops,
    }


def build_pool() -> dict[str, Any]:
    stringtable = _load_stringtable()
    tech_owners, unit_owners, card_ages = _load_civ_ownership()
    tech_root = ET.parse(TECHTREE_PATH).getroot()
    census: Counter[tuple[str, str]] = Counter()
    rows = [
        row
        for tech in tech_root.findall("tech")
        if (row := _parse_tech(
            tech,
            stringtable=stringtable,
            tech_owners=tech_owners,
            unit_owners=unit_owners,
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
                    and subtype not in IGNORED_SUBTYPES
                }
            ),
            "rule": (
                "保留战斗、成本和未知待审效果; 送兵、经济、人口、训练、"
                "建筑和解锁效果只记录在 ignored_ops"
            ),
        },
        "techs": rows,
    }


def main() -> None:
    pool = build_pool()
    OUTPUT_PATH.write_text(
        json.dumps(pool, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"techs={len(pool['techs'])}")
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
