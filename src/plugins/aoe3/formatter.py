"""AoE3 属性卡片文本渲染。"""

from __future__ import annotations

from .attack_actions import AttackAction, priority_shots, soldier_attacks
from .i18n import t_age, t_list, t_mult_vs
from .models import Multiplier, Unit

_DAMAGE_TYPE_ZH = {"Siege": "攻城", "Hand": "近战", "Ranged": "远程"}


def _damage_type_zh(damage_type: str) -> str:
    return _DAMAGE_TYPE_ZH.get(damage_type, damage_type or "-")


def _range_text(action: AttackAction) -> str:
    if not action.range_max:
        return ""
    if action.range_min:
        return f"{action.range_min:g}-{action.range_max:g}"
    return f"{action.range_max:g}"


def _compare_damage(action: AttackAction | None) -> str:
    if action is None:
        return "-"
    damage = f"{action.damage:g}"
    if action.num_projectiles > 1:
        damage = f"{damage}×{action.num_projectiles}"
    return damage


def _brief_attacks(unit: Unit) -> str:
    """一行摘要。没有开着且打得中人的模式时不写攻击。"""
    if not soldier_attacks(unit.attack_actions):
        return ""
    return " / ".join(
        f"{action.name} {action.damage:g}"
        for action in priority_shots(unit.attack_actions)
    )


def _fmt_mult(mults: list[Multiplier]) -> str:
    """格式化克制倍率列表（已汉化）。"""
    if not mults:
        return ""
    parts = [f"{t_mult_vs(m.vs)} x{m.value:g}" for m in mults]
    return "  → " + " | ".join(parts)


def _fmt_resist(unit: Unit) -> str:
    """格式化抗性。"""
    parts = []
    if unit.armor_melee:
        parts.append(f"{unit.armor_melee:.0%}近战")
    if unit.armor_ranged:
        parts.append(f"{unit.armor_ranged:.0%}远程")
    return " ".join(parts) if parts else "无"


def _unit_display_name(u: Unit) -> str:
    """获取展示用名称。"""
    return u.name if u.name != u.name_en else u.name_en


_DESCRIPTION_MAX_LEN = 320


def format_unit_tooltip(unit: Unit, *, max_len: int = _DESCRIPTION_MAX_LEN) -> str | None:
    """游戏内 rollover 描述，优先中文。查询卡片与斗蛐蛐阵容共用。"""
    text = (unit.description or unit.description_en or "").strip()
    if not text:
        return None
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def append_unit_tooltip(lines: list[str], unit: Unit, indent: str = "") -> None:
    """向面板行列表追加 tooltip（有则追加一行）。"""
    text = format_unit_tooltip(unit)
    if text:
        lines.append(f"{indent}📜 {text}")


def render_unit_card(unit: Unit) -> str:
    """渲染完整属性卡片文本。"""
    lines: list[str] = []

    # 标题
    if unit.name != unit.name_en:
        lines.append(f"🏰 {unit.name} ({unit.name_en})")
    else:
        lines.append(f"🏰 {unit.name_en}")
    lines.append("━" * 20)

    # 基本信息
    info_parts = []
    if unit.age:
        lines.append(f"时代：{t_age(unit.age)}")
    if unit.pop:
        info_parts.append(f"人口：{unit.pop}")
    if unit.train_time:
        info_parts.append(f"训练：{round(unit.train_time):g}s")
    if info_parts:
        lines.append(" | ".join(info_parts))

    if unit.cost:
        lines.append(f"费用：{unit.cost_str}")

    if unit.trained_at:
        lines.append(f"训练于：{' / '.join(t_list('trained_at', unit.trained_at))}")

    # 基础属性
    lines.append("")
    lines.append("📊 基础属性")
    stat_parts = []
    if unit.hp:
        stat_parts.append(f"HP：{round(unit.hp)}")
    if unit.speed:
        stat_parts.append(f"速度：{unit.speed:g}")
    if unit.los:
        stat_parts.append(f"视野：{unit.los:g}")
    if stat_parts:
        lines.append(" | ".join(stat_parts))
    lines.append(f"抗性：{_fmt_resist(unit)}")

    for action in priority_shots(unit.attack_actions):
        lines.append("")
        title = action.name + ("（关）" if not action.enabled else "")
        lines.append(title)
        damage = f"{action.damage:g}"
        if action.num_projectiles > 1:
            damage = f"{damage}×{action.num_projectiles}发"
        atk_parts = [f"  {damage}伤害", f"{_damage_type_zh(action.damage_type)}伤害"]
        rng = _range_text(action)
        if rng:
            atk_parts.append(f"射程{rng}")
        if action.rof:
            atk_parts.append(f"射速{action.rof:g}s")
        if action.windup:
            atk_parts.append(f"前摇{action.windup:g}s")
        if action.aoe_radius:
            atk_parts.append(f"AOE{action.aoe_radius:g}")
        if action.charge and action.recharge > 0:
            atk_parts.append(f"蓄力{action.recharge:g}s")
        lines.append(" | ".join(atk_parts))
        mult_str = _fmt_mult(list(action.multipliers))
        if mult_str:
            lines.append(mult_str)

    # 类型 + 文明
    if unit.type:
        from src.plugins.aoe3.type_display import format_unit_types
        types_zh = format_unit_types(unit)
        if types_zh:
            lines.append("")
            lines.append(f"📋 类型：{' / '.join(types_zh)}")
    if unit.civs:
        lines.append(f"文明：{'、'.join(t_list('civs', unit.civs))}")

    tooltip = format_unit_tooltip(unit)
    if tooltip:
        lines.append("")
        lines.append("📜 说明")
        lines.append(tooltip)

    return "\n".join(lines)


def render_unit_brief(unit: Unit) -> str:
    """渲染简短单行摘要（用于列表展示）。"""
    name = _unit_display_name(unit)
    atk = _brief_attacks(unit)
    atk_part = f" | {atk}" if atk else ""
    return f"{name} | HP {round(unit.hp)}{atk_part} | {unit.cost_str}"


def _fmt_compare_mults(mults_a: list[Multiplier], mults_b: list[Multiplier]) -> list[str]:
    """格式化对比视图中的倍率信息。合并双方的克制目标，左右对比展示。"""
    if not mults_a and not mults_b:
        return []

    # 收集所有 vs 目标，保持出现顺序
    seen: set[str] = set()
    all_vs: list[str] = []
    for m in mults_a + mults_b:
        if m.vs not in seen:
            seen.add(m.vs)
            all_vs.append(m.vs)

    map_a = {m.vs: m.value for m in mults_a}
    map_b = {m.vs: m.value for m in mults_b}

    lines: list[str] = []
    for vs in all_vs:
        va = f"x{map_a[vs]:g}" if vs in map_a else "-"
        vb = f"x{map_b[vs]:g}" if vs in map_b else "-"
        vs_zh = t_mult_vs(vs)
        lines.append(f"  {vs_zh}: {va}  │  {vb}")

    return lines


def render_compare(a: Unit, b: Unit) -> str:
    """渲染两个单位的左右对比卡片（含倍率）。"""
    lines: list[str] = []

    def _n(u: Unit) -> str:
        return _unit_display_name(u)

    lines.append("⚔️ 兵种对比")
    lines.append("━" * 20)
    lines.append(f"【{_n(a)}】 vs 【{_n(b)}】")
    lines.append("")

    def _row(label: str, va: str, vb: str) -> str:
        return f"{label}  {va}  │  {vb}"

    # ── 基础属性 ──
    lines.append(_row("HP", str(a.hp), str(b.hp)))
    lines.append(_row("费用", a.cost_str, b.cost_str))
    lines.append(_row("人口", str(a.pop), str(b.pop)))
    lines.append(_row("速度", f"{a.speed:g}", f"{b.speed:g}"))
    lines.append(_row("近战抗性", f"{a.armor_melee:.0%}", f"{b.armor_melee:.0%}"))
    lines.append(_row("远程抗性", f"{a.armor_ranged:.0%}", f"{b.armor_ranged:.0%}"))

    shots_a = priority_shots(a.attack_actions)
    shots_b = priority_shots(b.attack_actions)
    for index in range(max(len(shots_a), len(shots_b))):
        left = shots_a[index] if index < len(shots_a) else None
        right = shots_b[index] if index < len(shots_b) else None
        lines.append("")
        lines.append(_row(
            f"攻击{index + 1}",
            left.name if left else "-",
            right.name if right else "-",
        ))
        lines.append(_row(
            "  伤害",
            _compare_damage(left),
            _compare_damage(right),
        ))
        lines.append(_row(
            "  伤害类型",
            _damage_type_zh(left.damage_type) if left else "-",
            _damage_type_zh(right.damage_type) if right else "-",
        ))
        lines.append(_row(
            "  射程",
            (_range_text(left) or "-") if left else "-",
            (_range_text(right) or "-") if right else "-",
        ))
        if (left and left.rof) or (right and right.rof):
            lines.append(_row(
                "  射速",
                f"{left.rof:g}s" if left and left.rof else "-",
                f"{right.rof:g}s" if right and right.rof else "-",
            ))
        if (left and left.windup) or (right and right.windup):
            lines.append(_row(
                "  前摇",
                f"{left.windup:g}s" if left and left.windup else "-",
                f"{right.windup:g}s" if right and right.windup else "-",
            ))
        if (left and left.aoe_radius) or (right and right.aoe_radius):
            lines.append(_row(
                "  AOE",
                f"{left.aoe_radius:g}" if left and left.aoe_radius else "-",
                f"{right.aoe_radius:g}" if right and right.aoe_radius else "-",
            ))
        if (left and left.charge and left.recharge > 0) or (
            right and right.charge and right.recharge > 0
        ):
            lines.append(_row(
                "  蓄力",
                f"{left.recharge:g}s" if left and left.charge and left.recharge > 0 else "-",
                f"{right.recharge:g}s" if right and right.charge and right.recharge > 0 else "-",
            ))
        if (left and not left.enabled) or (right and not right.enabled):
            lines.append(_row(
                "  状态",
                "关" if left and not left.enabled else ("开" if left else "-"),
                "关" if right and not right.enabled else ("开" if right else "-"),
            ))
        mult_lines = _fmt_compare_mults(
            list(left.multipliers) if left else [],
            list(right.multipliers) if right else [],
        )
        if mult_lines:
            lines.append("  克制倍率:")
            lines.extend(mult_lines)

    # ── 类型 ──
    lines.append("")
    type_a = " / ".join(t_list("tags", a.type)) if a.type else "-"
    type_b = " / ".join(t_list("tags", b.type)) if b.type else "-"
    lines.append(f"类型A: {type_a}")
    lines.append(f"类型B: {type_b}")

    return "\n".join(lines)


def render_civ_units(units: list[Unit], civ: str) -> str:
    """渲染文明兵种列表。"""
    if not units:
        return f"未找到「{civ}」的兵种。"

    trainable = [u for u in units if u.is_trainable]
    trainable.sort(
        key=lambda unit: (
            any(tag.startswith("AbstractConsulate") for tag in unit.type),
            unit.age,
            unit.name,
        )
    )

    lines = [f"🏰 {civ} 可用兵种 ({len(trainable)} 个)", "━" * 36]

    for u in trainable:
        name = _unit_display_name(u)
        atk = _brief_attacks(u)
        atk_part = f" │ {atk}" if atk else ""
        age_zh = t_age(u.age) if u.age else "?"
        source = (
            "领事馆"
            if any(tag.startswith("AbstractConsulate") for tag in u.type)
            else "本单位"
        )
        lines.append(
            f"  {name:<16} │ {age_zh} │ {source} │ HP {round(u.hp)}{atk_part}"
        )

    return "\n".join(lines)
