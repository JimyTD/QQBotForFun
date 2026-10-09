"""AoE3 科技效果运行时应用。

科技 parser 将游戏 ``techtreey.xml`` 的效果规整为 ``scope`` + ``ops`` 后，
由本模块把**已明确选定**的科技作用到 Unit 副本。它不读取科技池、不选择科技、
也不引入随机性；未来的文明科技树和主城国策共用这套效果语义。
"""
from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from .attack_actions import AttackAction
from .models import Multiplier, Unit

# ------------------------------------------------------------------
# 应用
# ------------------------------------------------------------------

def _op_dedup_key(op: dict, unit: Unit) -> tuple[str, ...]:
    """为 op 生成去重键：同键的多条 op 只保留最强的一条。

    键的构成取决于 stat 类型：
      - range/aoe/rof/mult: 按动作名，不是按槽
      - 全局 (hp/damage/speed): (stat, kind)
      - armor: (stat, kind, armor_kind)
      - cost: (stat, kind, resource)
    """
    stat = op["stat"]
    kind = op["kind"]

    if stat in ("range", "aoe", "rof"):
        # 同一科技常为多个动作各写一条；键必须带动作名与 subtype，
        # 否则只剩第一行生效。allactions 没有动作名，仍由应用阶段统一展开。
        return (
            f"{stat}:{kind}:{op.get('subtype', '')}:{op.get('action', '')}",
        )
    if stat == "mult":
        vs = op.get("vs", "")
        action = op.get("action", "")
        return (f"mult:{kind}:{action}:{vs}",)
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


def _stat_winners(ops: list[dict], action_names: set[str]) -> list[tuple[str, dict]]:
    """同一动作、同一项效果只留数值最大的一条。allactions 覆盖当前列表里的每一条。"""
    best: dict[tuple[str, str, str, str, str], dict] = {}
    order: list[tuple[str, str, str, str, str]] = []
    for op in ops:
        if op.get("stat") not in {"range", "aoe", "rof", "mult"}:
            continue
        if op.get("allactions") or not op.get("action"):
            names = action_names
        else:
            names = {str(op["action"])} & action_names
        vs = str(op.get("vs") or "") if op.get("stat") == "mult" else ""
        for name in names:
            key = (
                str(op["stat"]),
                str(op["kind"]),
                vs,
                str(op.get("subtype") or ""),
                name,
            )
            if key not in best:
                best[key] = op
                order.append(key)
            elif float(op["value"]) > float(best[key]["value"]):
                best[key] = op
    return [(key[4], best[key]) for key in order]


def _apply_stat_to_action(
    action: AttackAction,
    origin: AttackAction,
    op: dict,
) -> AttackAction:
    stat = op["stat"]
    kind = op["kind"]
    val = float(op["value"])
    if stat == "range" and kind == "add":
        field_name = "range_min" if op.get("subtype") == "MinimumRange" else "range_max"
        current = float(getattr(action, field_name))
        if current <= 0 and field_name != "range_min":
            return action
        return dataclasses.replace(action, **{field_name: round(current + val, 2)})
    if stat == "range" and kind == "set":
        field_name = "range_min" if op.get("subtype") == "MinimumRange" else "range_max"
        return dataclasses.replace(action, **{field_name: round(val, 2)})
    if stat == "aoe" and kind == "add":
        return dataclasses.replace(action, aoe_radius=round(action.aoe_radius + val, 2))
    if stat == "rof":
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
    if stat == "mult" and kind == "add":
        vs = str(op.get("vs") or "")
        if not vs:
            return action
        found = False
        updated = []
        for bonus in action.multipliers:
            if bonus.vs == vs:
                updated.append(dataclasses.replace(bonus, value=round(bonus.value + val, 4)))
                found = True
            else:
                updated.append(bonus)
        if not found:
            updated.append(Multiplier(vs=vs, value=round(1.0 + val, 4)))
        return dataclasses.replace(action, multipliers=tuple(updated))
    return action


def _apply_named_action_stats(changes: dict, unit: Unit, base: Unit, ops: list[dict]) -> None:
    """射程、溅射、射速、倍率按动作名改当前列表。槽字段另走代表动作归桶。"""
    current = list(changes.get("attack_actions", unit.attack_actions))
    if not current:
        return
    origin_actions = changes.get("_attack_origin", base.attack_actions)
    base_by = {action.name: action for action in origin_actions}
    winners = _stat_winners(ops, {action.name for action in current})
    if not winners:
        return
    updated = list(current)
    changed = False
    for name, op in winners:
        origin = base_by.get(name)
        for index, action in enumerate(updated):
            if action.name != name:
                continue
            nxt = _apply_stat_to_action(action, origin or action, op)
            if nxt != action:
                updated[index] = nxt
                changed = True
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
        elif stat == "hp" and kind == "percent":
            changes["hp"] = round(changes.get("hp", unit.hp) * val, 1)
        elif stat == "hp" and kind == "set":
            changes["hp"] = round(val, 1)
        elif stat == "damage" and kind in {"mult", "add", "set", "percent"}:
            def _next_damage(
                action: AttackAction,
                origin: AttackAction,
                *,
                kind: str = kind,
                val: float = val,
            ) -> AttackAction:
                if kind == "mult":
                    inc = val - 1.0
                    return dataclasses.replace(
                        action,
                        damage=round(action.damage + origin.damage * inc, 2),
                        damage_cap=(
                            round(action.damage_cap + origin.damage_cap * inc, 2)
                            if origin.damage_cap
                            else action.damage_cap
                        ),
                    )
                if kind == "add":
                    return dataclasses.replace(action, damage=round(action.damage + val, 2))
                if kind == "percent":
                    return dataclasses.replace(
                        action,
                        damage=round(action.damage * val, 2),
                    )
                return dataclasses.replace(action, damage=round(val, 2))

            _retarget_actions(
                changes,
                unit,
                base,
                {**op, "action": "", "allactions": True},
                _next_damage,
            )
        elif stat == "recharge" and _recharge_targets_unit(op, unit):
            def _next_recharge(
                action: AttackAction,
                origin: AttackAction,
                *,
                kind: str = kind,
                val: float = val,
            ) -> AttackAction:
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
        elif stat == "cost":
            resource = op.get("resource", "")
            if not resource:
                continue
            cur_cost = dict(changes.get("cost", unit.cost))
            current = cur_cost.get(resource, unit.cost.get(resource, 0))
            if kind == "mult":
                new_value = current + base.cost.get(resource, 0) * (val - 1.0)
            elif kind == "add":
                new_value = current + val
            elif kind == "percent":
                new_value = current * val
            elif kind == "set":
                new_value = val
            else:
                continue
            new_value = max(0, round(new_value))
            if new_value:
                cur_cost[resource] = new_value
            else:
                cur_cost.pop(resource, None)
            changes["cost"] = cur_cost
        # range / aoe / rof / mult 只经上面 _apply_named_action_stats 落到动作列表

    _apply_named_action_stats(changes, unit, base, tech["ops"])

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
    from src.plugins.games.aoe3_battle.tech_summary import format_runtime_tech_summary

    if not red_techs and not blue_techs:
        return []
    lines = [title + "："]
    for t in red_techs:
        lines.append(f"   🔴 {format_runtime_tech_summary(t)}")
    for t in blue_techs:
        lines.append(f"   🔵 {format_runtime_tech_summary(t)}")
    return lines
