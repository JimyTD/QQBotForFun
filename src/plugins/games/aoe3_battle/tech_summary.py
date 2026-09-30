"""Player-facing summaries for selected civ-war technologies."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


_RESOURCE_NAMES = {
    "food": "食物",
    "wood": "木材",
    "gold": "金币",
    "influence": "影响力",
}

_TARGET_NAMES = {
    "AbstractInfantry": "步兵",
    "AbstractCavalry": "骑兵",
    "AbstractArtillery": "炮兵",
    "AbstractVillager": "村民",
    "AbstractBuilding": "建筑",
}


def _percent(value: float) -> str:
    pct = round((value - 1.0) * 100)
    return f"{pct:+d}%"


def _signed(value: float) -> str:
    return f"{value:+g}"


def _resource_name(resource: object) -> str:
    key = str(resource or "").lower()
    return _RESOURCE_NAMES.get(key, str(resource or "资源"))


def _target_summary(op: Mapping[str, Any]) -> str:
    unittype = str(op.get("unittype") or "")
    if unittype:
        for key, label in _TARGET_NAMES.items():
            if key in unittype:
                return label
        return unittype.replace("Abstract", "")
    targets = op.get("targets") or ()
    values = [
        str(target.get("value") or "")
        for target in targets
        if isinstance(target, Mapping)
        and target.get("type") == "ProtoUnit"
        and target.get("value")
    ]
    if len(values) == 1:
        return values[0]
    return ""


def _describe_op(op: Mapping[str, Any]) -> str:
    subtype = str(op.get("subtype") or "")
    amount = op.get("amount")
    if amount is None:
        return ""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return ""

    if subtype in {"Hitpoints", "HitPoints"}:
        return f"生命{_percent(value)}"
    if subtype == "Damage":
        return f"攻击{_percent(value)}"
    if subtype == "DamageBonus":
        target = _target_summary(op)
        return f"对{target}伤害{_signed(value)}" if target else f"额外伤害{_signed(value)}"
    if subtype == "DamageArea":
        return f"溅射范围{_signed(value)}"
    if subtype == "MaximumRange":
        return f"射程{_signed(value)}"
    if subtype == "MinimumRange":
        return f"最小射程{_signed(value)}"
    if subtype == "RateOfFire":
        return f"攻速调整为 {value:g} 秒"
    if subtype == "MaximumVelocity":
        return f"移速{_percent(value)}"
    if subtype in {"Armor", "ArmorSpecific"}:
        armor = "近战" if str(op.get("newtype") or "") in {"Hand", "Melee"} else "远程"
        return f"{armor}护甲{_signed(value)}"
    if subtype == "Cost":
        return f"{_resource_name(op.get('resource'))}造价{_percent(value)}"
    return ""


def _unique(parts: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part and part not in seen:
            seen.add(part)
            result.append(part)
    return tuple(result)


def format_tech_summary(
    name: str,
    *,
    combat_ops: Iterable[Mapping[str, Any]] = (),
    cost_ops: Iterable[Mapping[str, Any]] = (),
    recipients: Iterable[str] = (),
) -> str:
    """Return ``【units】name: effects``, or only the name when no wording exists."""
    effects = _unique(
        part
        for op in (*tuple(combat_ops), *tuple(cost_ops))
        for part in (_describe_op(op),)
    )
    body = f"{name}：{'，'.join(effects)}" if effects else name
    names = _unique(str(unit) for unit in recipients)
    if not names:
        return body
    return f"【{'、'.join(names)}】{body}"
