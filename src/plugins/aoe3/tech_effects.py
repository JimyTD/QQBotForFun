"""AoE3 科技效果运行时应用。

科技 parser 将游戏 ``techtreey.xml`` 的效果规整为 ``scope`` + ``ops`` 后，
由本模块把**已明确选定**的科技作用到 Unit 副本。它不读取科技池、不选择科技、
也不引入随机性；未来的文明科技树和主城国策共用这套效果语义。
"""
from __future__ import annotations

import dataclasses
from typing import Sequence

from .attack_actions import AttackAction
from .models import Multiplier, Unit


# ------------------------------------------------------------------
# 应用
# ------------------------------------------------------------------

def _slots_for_op(op: dict, unit: Unit) -> list[str]:
    """op 的 action 落 ranged/melee 哪些槽（与 upgrades_parser._slots_for_action 同源逻辑）。"""
    allact = op.get("allactions", False)
    action = op.get("action")
    if allact or not action:
        slots = []
        if unit.attack_ranged:
            slots.append("ranged")
        if unit.attack_melee:
            slots.append("melee")
        return slots
    if action == unit.protoaction_ranged:
        return ["ranged"] if unit.attack_ranged else []
    if action == unit.protoaction_melee:
        return ["melee"] if unit.attack_melee else []
    return []


def _op_dedup_key(op: dict, unit: Unit) -> tuple[str, ...]:
    """为 op 生成去重键：同键的多条 op 只保留最强的一条。

    键的构成取决于 stat 类型：
      - slot-routed (range/aoe/rof): (stat, kind, slot)
      - mult: (stat, kind, slot, vs)
      - 全局 (hp/damage/speed): (stat, kind)
      - armor: (stat, kind, armor_kind)
      - cost: (stat, kind, resource)

    返回 tuple 列表（一条 op 可能命中多个 slot，则生成多个键）。
    """
    stat = op["stat"]
    kind = op["kind"]

    if stat in ("range", "aoe", "rof"):
        slots = _slots_for_op(op, unit)
        return tuple(f"{stat}:{kind}:{s}" for s in slots) if slots else (f"{stat}:{kind}:",)
    if stat == "mult":
        vs = op.get("vs", "")
        slots = _slots_for_op(op, unit)
        return tuple(f"mult:{kind}:{s}:{vs}" for s in slots) if slots else (f"mult:{kind}::{vs}",)
    if stat == "action_enable":
        return (f"action_enable:{op.get('action', '')}",)
    if stat == "initial_tactic":
        return (f"initial_tactic:{op.get('tactic', '')}",)
    if stat == "recharge":
        targets = ",".join(
            sorted(
                str(target.get("value") or "")
                for target in op.get("targets") or ()
                if isinstance(target, dict)
            )
        )
        return (f"recharge:{kind}:{op.get('action', '')}:{targets}",)
    if stat == "armor":
        return (f"armor:{kind}:{op.get('armor_kind', '')}",)
    if stat == "cost":
        return (f"cost:{kind}:{op.get('resource', '')}",)
    # hp, damage, speed 等全局 stat
    return (f"{stat}:{kind}",)


def _deduplicate_ops(ops: list[dict], unit: Unit) -> list[dict]:
    """同一科技内按去重键分组，每组只保留 value 最大的 op。

    科技列出多条 action 变体是为覆盖不同兵种的代表动作名，对单个兵只应生效一次。
    数据中偶有 parser 合并产生的重复（如同 stat 不同 value），取最大值。
    """
    seen: dict[str, dict] = {}  # key → best op
    result_keys: list[str] = []  # 保持首次出现顺序

    for op in ops:
        keys = _op_dedup_key(op, unit)
        for k in keys:
            if k not in seen:
                seen[k] = op
                result_keys.append(k)
            elif op["value"] > seen[k]["value"]:
                seen[k] = op

    # 同一 op 可能产生多个 key（多 slot），去重保留唯一 op
    emitted: set[int] = set()
    result: list[dict] = []
    for k in result_keys:
        op = seen[k]
        op_id = id(op)
        if op_id not in emitted:
            emitted.add(op_id)
            result.append(op)
    return result


_ROF_FLOOR = 0.1


def _apply_rof(
    changes: dict,
    unit: Unit,
    base: Unit,
    op: dict,
    kind: str,
    val: float,
) -> None:
    """Apply one rate-of-fire op onto the representative attack slot.

    Assign overwrites the interval. Absolute adds seconds. BasePercent adds
    ``base_interval * (amount - 1)`` onto the current interval, the same way
    hit points treat BasePercent. The interval stays at least 0.1 seconds.
    """
    for slot in _slots_for_op(op, unit):
        field = {"ranged": "rof_ranged", "melee": "rof_melee"}.get(slot)
        if field is None:
            continue
        current = float(changes.get(field, getattr(unit, field)))
        if kind == "set":
            new = val
        elif current <= 0:
            continue
        elif kind == "add":
            new = current + val
        elif kind == "mult":
            new = current + float(getattr(base, field)) * (val - 1.0)
        else:
            continue
        changes[field] = round(max(_ROF_FLOOR, new), 3)

    def _next_rof(action: AttackAction, origin: AttackAction) -> AttackAction:
        if kind == "set":
            new = val
        elif action.rof <= 0:
            return action
        elif kind == "add":
            new = action.rof + val
        elif kind == "mult":
            new = action.rof + origin.rof * (val - 1.0)
        else:
            return action
        return dataclasses.replace(action, rof=round(max(_ROF_FLOOR, new), 3))

    _retarget_actions(changes, unit, base, op, _next_rof)


def _recharge_targets_unit(op: dict, unit: Unit) -> bool:
    """冷却效果只打到写明的原型。没写目标时，这名兵身上的蓄力都改。"""
    targets = [
        str(target.get("value") or "")
        for target in op.get("targets") or ()
        if isinstance(target, dict)
        and target.get("type") == "ProtoUnit"
        and target.get("value")
    ]
    if not targets:
        return True
    tags = {unit.id.lower(), *(item.lower() for item in unit.type)}
    return any(target.lower() in tags for target in targets)


def _action_names(op: dict, actions: list[AttackAction]) -> set[str] | None:
    """None means every mode. A named mode that is not on this unit matches nothing."""
    if op.get("allactions") or not op.get("action"):
        return None
    return {str(op["action"])}


def _retarget_actions(changes: dict, unit: Unit, base: Unit, op: dict, mapper) -> None:
    current = list(changes.get("attack_actions", unit.attack_actions))
    if not current:
        return
    names = _action_names(op, current)
    origin_actions = changes.get("_attack_origin", base.attack_actions)
    base_by = {action.name: action for action in origin_actions}
    updated: list[AttackAction] = []
    changed = False
    for action in current:
        if names is not None and action.name not in names:
            updated.append(action)
            continue
        nxt = mapper(action, base_by.get(action.name, action))
        updated.append(nxt)
        changed = changed or nxt != action
    if changed:
        changes["attack_actions"] = updated


def _apply_one_tech(unit: Unit, tech: dict, base: Unit) -> Unit:
    """把一条已选科技叠到单位上，返回新副本（无效不动）。

    base: tier 升级前的原始 Unit，用于 BasePercent 加算（AoE3 所有 BasePercent
    效果加算于原始基础值，而非乘在 tier 之后的值上）。

    去重原则：同一条科技内，同一 (stat, kind, 目标键) 只生效一次。
    科技列出多条 action 变体是为覆盖不同兵种的代表动作名，实际对单个兵只取
    首次命中（值相同时无差别；值不同时取最大值的 op 先到先得，见 _best_ops）。
    """
    scope = set(tech["scope"])
    unit_tags = set(unit.type) | {unit.id}
    if not (scope & unit_tags):
        return unit

    # 预处理：按 (stat, kind, 目标键) 分组，每组只保留最强的一条 op
    best_ops = _deduplicate_ops(tech["ops"], unit)
    best_ops.sort(key=lambda op: op["stat"] != "initial_tactic")

    changes: dict = {}
    for op in best_ops:
        stat = op["stat"]
        kind = op["kind"]
        val = op["value"]

        if stat == "hp" and kind == "mult":
            changes["hp"] = round(
                changes.get("hp", unit.hp) + base.hp * (val - 1.0),
                1,
            )
        elif stat == "hp" and kind == "add":
            changes["hp"] = round(changes.get("hp", unit.hp) + val, 1)
        elif stat == "damage" and kind == "mult":
            inc = val - 1.0
            if unit.attack_ranged:
                changes["attack_ranged"] = round(
                    changes.get("attack_ranged", unit.attack_ranged)
                    + base.attack_ranged * inc, 2)
                if unit.damage_cap_ranged:
                    changes["damage_cap_ranged"] = round(
                        changes.get("damage_cap_ranged", unit.damage_cap_ranged)
                        + base.damage_cap_ranged * inc, 2)
            if unit.attack_melee:
                changes["attack_melee"] = round(
                    changes.get("attack_melee", unit.attack_melee)
                    + base.attack_melee * inc, 2)
                if unit.damage_cap_melee:
                    changes["damage_cap_melee"] = round(
                        changes.get("damage_cap_melee", unit.damage_cap_melee)
                        + base.damage_cap_melee * inc, 2)
            _retarget_actions(
                changes,
                unit,
                base,
                {**op, "action": "", "allactions": True},
                lambda action, origin: dataclasses.replace(
                    action,
                    damage=round(action.damage + origin.damage * inc, 2),
                    damage_cap=(
                        round(action.damage_cap + origin.damage_cap * inc, 2)
                        if origin.damage_cap
                        else action.damage_cap
                    ),
                ),
            )
        elif stat == "range" and kind == "add":
            for s in _slots_for_op(op, unit):
                if s == "ranged" and unit.range:
                    changes["range"] = round(
                        changes.get("range", unit.range) + val, 2)
                elif s == "melee" and unit.range_melee:
                    changes["range_melee"] = round(
                        changes.get("range_melee", unit.range_melee) + val, 2)
            field_name = (
                "range_min" if op.get("subtype") == "MinimumRange" else "range_max"
            )
            _retarget_actions(
                changes,
                unit,
                base,
                op,
                lambda action, _origin, field_name=field_name: (
                    action
                    if getattr(action, field_name) <= 0
                    else dataclasses.replace(
                        action,
                        **{field_name: round(getattr(action, field_name) + val, 2)},
                    )
                ),
            )
        elif stat == "aoe" and kind == "add":
            for s in _slots_for_op(op, unit):
                if s == "ranged":
                    changes["aoe_radius_ranged"] = round(
                        changes.get("aoe_radius_ranged", unit.aoe_radius_ranged) + val, 2)
                elif s == "melee":
                    changes["aoe_radius_melee"] = round(
                        changes.get("aoe_radius_melee", unit.aoe_radius_melee) + val, 2)
            _retarget_actions(
                changes,
                unit,
                base,
                op,
                lambda action, _origin: dataclasses.replace(
                    action,
                    aoe_radius=round(action.aoe_radius + val, 2),
                ),
            )
        elif stat == "recharge" and _recharge_targets_unit(op, unit):
            def _next_recharge(action: AttackAction, origin: AttackAction) -> AttackAction:
                if not action.charge:
                    return action
                if kind == "set":
                    new = val
                elif kind == "add":
                    new = action.recharge + val
                elif kind == "mult":
                    new = action.recharge + origin.recharge * (val - 1.0)
                else:
                    return action
                return dataclasses.replace(action, recharge=round(max(0.0, new), 4))

            _retarget_actions(changes, unit, base, op, _next_recharge)
        elif stat == "initial_tactic":
            tactic = str(op.get("tactic") or "")
            template = unit.attack_actions_by_tactic.get(tactic)
            if template is None:
                continue
            origin = base.attack_actions_by_tactic.get(tactic, template)
            changes["attack_actions"] = [
                dataclasses.replace(action) for action in template
            ]
            changes["_attack_origin"] = list(origin)
        elif stat == "action_enable" and op.get("action"):
            enabled = float(val) != 0.0
            _retarget_actions(
                changes,
                unit,
                base,
                op,
                lambda action, _origin, enabled=enabled: dataclasses.replace(
                    action,
                    enabled=enabled,
                ),
            )
        elif stat == "rof":
            _apply_rof(changes, unit, base, op, kind, val)
        elif stat == "speed":
            cur = changes.get("speed", unit.speed)
            if kind == "mult":
                changes["speed"] = round(cur * val, 3)
            elif kind == "add":
                changes["speed"] = round(cur + val, 3)
            elif kind == "set":
                changes["speed"] = round(val, 3)
        elif stat == "armor" and kind == "add":
            ak = op.get("armor_kind", "")
            if ak == "melee":
                changes["armor_melee"] = round(
                    changes.get("armor_melee", unit.armor_melee) + val, 3)
            elif ak == "ranged":
                changes["armor_ranged"] = round(
                    changes.get("armor_ranged", unit.armor_ranged) + val, 3)
        elif stat == "cost" and kind == "mult":
            resource = op.get("resource", "")
            if resource:
                cur_cost = dict(changes.get("cost", unit.cost))
                new_value = max(0, round(
                    cur_cost.get(resource, unit.cost.get(resource, 0))
                    + base.cost.get(resource, 0) * (val - 1.0)))
                if new_value:
                    cur_cost[resource] = new_value
                else:
                    cur_cost.pop(resource, None)
                changes["cost"] = cur_cost
        elif stat == "mult" and kind == "add":
            vs = op.get("vs", "")
            if not vs:
                continue
            for s in _slots_for_op(op, unit):
                field_name = f"multipliers_{s}"
                cur_list = changes.get(field_name) or list(getattr(unit, field_name))
                new_list = []
                found = False
                for m in cur_list:
                    if m.vs == vs:
                        new_list.append(
                            dataclasses.replace(
                                m,
                                value=round(m.value + val, 4),
                            )
                        )
                        found = True
                    else:
                        new_list.append(m)
                if not found:
                    new_list.append(Multiplier(vs=vs, value=round(1.0 + val, 4)))
                changes[field_name] = new_list

            def _next_multiplier(action: AttackAction, _origin: AttackAction) -> AttackAction:
                found_bonus = False
                updated_bonuses = []
                for bonus in action.multipliers:
                    if bonus.vs == vs:
                        updated_bonuses.append(
                            dataclasses.replace(bonus, value=round(bonus.value + val, 4))
                        )
                        found_bonus = True
                    else:
                        updated_bonuses.append(bonus)
                if not found_bonus:
                    updated_bonuses.append(Multiplier(vs=vs, value=round(1.0 + val, 4)))
                return dataclasses.replace(action, multipliers=tuple(updated_bonuses))

            _retarget_actions(changes, unit, base, op, _next_multiplier)

    if not changes:
        return unit
    changes.pop("_attack_origin", None)
    return dataclasses.replace(unit, **changes)


def apply_techs(
    units: Sequence[Unit],
    techs: list[dict],
    base_units: Sequence[Unit] | None = None,
) -> list[Unit]:
    """对一方的所有单位叠加已选科技列表，返回新副本列表。

    base_units: tier 升级前的原始 Unit 列表（与 units 同序），用于 BasePercent
    加算。如果为 None 则用 units 自身作为 base（适用于无 tier 的场景）。
    """
    if not techs:
        return list(units)
    result = []
    for i, u in enumerate(units):
        base = base_units[i] if base_units else u
        cur = u
        for t in techs:
            cur = _apply_one_tech(cur, t, base)
        result.append(cur)
    return result


# ------------------------------------------------------------------
# 战报展示
# ------------------------------------------------------------------

def format_tech_lines(
    red_techs: list[dict], blue_techs: list[dict], *, title: str = "🔬 本局科技"
) -> list[str]:
    """生成已选科技展示行（嵌入到 VS banner）。"""
    if not red_techs and not blue_techs:
        return []
    lines = [title + "："]
    for t in red_techs:
        lines.append(f"   🔴 {t['name_zh']}（{_brief_desc(t)}）")
    for t in blue_techs:
        lines.append(f"   🔵 {t['name_zh']}（{_brief_desc(t)}）")
    return lines


def _brief_desc(tech: dict) -> str:
    """一行简述科技效果。"""
    parts = []
    for op in tech["ops"]:
        stat = op["stat"]
        kind = op["kind"]
        val = op["value"]
        if stat == "hp" and kind == "mult":
            pct = round((val - 1) * 100)
            parts.append(f"血{'+' if pct > 0 else ''}{pct}%")
        elif stat == "damage" and kind == "mult":
            pct = round((val - 1) * 100)
            parts.append(f"攻{'+' if pct > 0 else ''}{pct}%")
        elif stat == "speed" and kind == "mult":
            pct = round((val - 1) * 100)
            parts.append(f"速{'+' if pct > 0 else ''}{pct}%")
        elif stat == "speed" and kind == "add":
            parts.append(f"速{'+' if val > 0 else ''}{val}")
        elif stat == "range" and kind == "add":
            parts.append(f"射程+{val}")
        elif stat == "aoe" and kind == "add":
            parts.append(f"AOE+{val}")
        elif stat == "rof" and kind == "set":
            parts.append(f"射击间隔改为{val:g}秒")
        elif stat == "rof" and kind == "add":
            parts.append(f"射击间隔{'+' if val > 0 else ''}{val:g}秒")
        elif stat == "rof" and kind == "mult":
            pct = round((val - 1) * 100)
            parts.append(f"射击间隔{'+' if pct > 0 else ''}{pct}%")
        elif stat == "armor" and kind == "add":
            ak = op.get("armor_kind", "")
            parts.append(f"{'近' if ak == 'melee' else '远'}防+{val}")
        elif stat == "cost" and kind == "mult":
            pct = round((val - 1) * 100)
            res = op.get("resource", "")
            parts.append(f"造价{res}{'+' if pct > 0 else ''}{pct}%")
        elif stat == "mult" and kind == "add":
            vs_short = op.get("vs", "").replace("Abstract", "")
            parts.append(f"vs{vs_short}+{val}")
        elif stat == "initial_tactic":
            parts.append("换成阵型")
        elif stat == "action_enable":
            parts.append("解锁攻击" if val else "关闭攻击")
        elif stat == "recharge" and kind == "mult":
            pct = round((val - 1) * 100)
            parts.append(f"蓄力冷却{'+' if pct > 0 else ''}{pct}%")
        elif stat == "recharge" and kind == "add":
            parts.append(f"蓄力冷却{'+' if val > 0 else ''}{val:g}秒")
        elif stat == "recharge" and kind == "set":
            parts.append(f"蓄力冷却改为{val:g}秒")
    scope = "/".join(s.replace("Abstract", "") for s in tech["scope"])
    return f"{scope}: {', '.join(parts)}" if parts else scope
