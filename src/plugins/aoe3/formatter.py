"""AoE3 属性卡片文本渲染。"""

from __future__ import annotations

from .i18n import t, t_age, t_list, t_mult_vs
from .models import Multiplier, Unit


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
        info_parts.append(f"训练：{unit.train_time}s")
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
        stat_parts.append(f"HP：{unit.hp}")
    if unit.speed:
        stat_parts.append(f"速度：{unit.speed:g}")
    if unit.los:
        stat_parts.append(f"视野：{unit.los:g}")
    if stat_parts:
        lines.append(" | ".join(stat_parts))
    lines.append(f"抗性：{_fmt_resist(unit)}")

    # 远程攻击
    if unit.attack_ranged:
        dtype_tag = ""
        if unit.damage_type_ranged and unit.damage_type_ranged != "Ranged":
            dtype_zh = {"Siege": "攻城", "Hand": "近战"}.get(unit.damage_type_ranged, unit.damage_type_ranged)
            dtype_tag = f"({dtype_zh}伤害)"
        lines.append("")
        lines.append(f"🏹 远程攻击{dtype_tag}")
        atk_parts = [f"  {unit.attack_ranged:g}伤害"]
        if unit.range:
            rng = f"{unit.range_min:g}-{unit.range:g}" if unit.range_min else f"{unit.range:g}"
            atk_parts.append(f"射程{rng}")
        if unit.rof_ranged:
            atk_parts.append(f"射速{unit.rof_ranged:g}s")
        if unit.aoe_radius_ranged:
            atk_parts.append(f"AOE{unit.aoe_radius_ranged}")
        lines.append(" | ".join(atk_parts))
        mult_str = _fmt_mult(unit.multipliers_ranged)
        if mult_str:
            lines.append(mult_str)

    # 近战攻击
    if unit.attack_melee:
        lines.append("")
        lines.append("⚔️ 近战攻击")
        atk_parts = [f"  {unit.attack_melee:g}伤害"]
        if unit.rof_melee:
            atk_parts.append(f"射速{unit.rof_melee:g}s")
        if unit.aoe_radius_melee:
            atk_parts.append(f"AOE{unit.aoe_radius_melee}")
        lines.append(" | ".join(atk_parts))
        mult_str = _fmt_mult(unit.multipliers_melee)
        if mult_str:
            lines.append(mult_str)

    # 攻城攻击
    if unit.attack_siege:
        lines.append("")
        lines.append("💣 攻城攻击")
        atk_parts = [f"  {unit.attack_siege:g}伤害"]
        if unit.range_siege:
            atk_parts.append(f"射程{unit.range_siege:g}")
        if unit.rof_siege:
            atk_parts.append(f"射速{unit.rof_siege:g}s")
        if unit.aoe_radius_siege:
            atk_parts.append(f"AOE{unit.aoe_radius_siege}")
        lines.append(" | ".join(atk_parts))
        mult_str = _fmt_mult(unit.multipliers_siege)
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

    return "\n".join(lines)


def render_unit_brief(unit: Unit) -> str:
    """渲染简短单行摘要（用于列表展示）。"""
    name = _unit_display_name(unit)
    atk = unit.attack_ranged or unit.attack_melee or unit.attack_siege or 0
    return f"{name} | HP {unit.hp} | ATK {atk:g} | {unit.cost_str}"


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

    # ── 远程攻击 ──
    if a.attack_ranged or b.attack_ranged:
        lines.append("")
        lines.append("🏹 远程攻击")
        lines.append(_row("  伤害", f"{a.attack_ranged:g}", f"{b.attack_ranged:g}"))
        # 伤害类型（仅当非标准 Ranged 时标注）
        def _dtype_tag(u: Unit) -> str:
            d = u.damage_type_ranged
            if d and d != "Ranged":
                return {"Siege": "攻城", "Hand": "近战"}.get(d, d)
            return "远程"
        lines.append(_row("  伤害类型", _dtype_tag(a), _dtype_tag(b)))
        lines.append(_row("  射程", f"{a.range:g}", f"{b.range:g}"))
        if a.rof_ranged or b.rof_ranged:
            lines.append(_row("  射速", f"{a.rof_ranged:g}s", f"{b.rof_ranged:g}s"))
        if a.aoe_radius_ranged or b.aoe_radius_ranged:
            lines.append(_row("  AOE", str(a.aoe_radius_ranged or "-"), str(b.aoe_radius_ranged or "-")))
        mult_lines = _fmt_compare_mults(a.multipliers_ranged, b.multipliers_ranged)
        if mult_lines:
            lines.append("  克制倍率:")
            lines.extend(mult_lines)

    # ── 近战攻击 ──
    if a.attack_melee or b.attack_melee:
        lines.append("")
        lines.append("⚔️ 近战攻击")
        lines.append(_row("  伤害", f"{a.attack_melee:g}", f"{b.attack_melee:g}"))
        if a.rof_melee or b.rof_melee:
            lines.append(_row("  射速", f"{a.rof_melee:g}s", f"{b.rof_melee:g}s"))
        if a.aoe_radius_melee or b.aoe_radius_melee:
            lines.append(_row("  AOE", str(a.aoe_radius_melee or "-"), str(b.aoe_radius_melee or "-")))
        mult_lines = _fmt_compare_mults(a.multipliers_melee, b.multipliers_melee)
        if mult_lines:
            lines.append("  克制倍率:")
            lines.extend(mult_lines)

    # ── 攻城攻击 ──
    if a.attack_siege or b.attack_siege:
        lines.append("")
        lines.append("💣 攻城攻击")
        lines.append(_row("  伤害", f"{a.attack_siege:g}", f"{b.attack_siege:g}"))
        if a.range_siege or b.range_siege:
            lines.append(_row("  射程", f"{a.range_siege:g}", f"{b.range_siege:g}"))
        if a.aoe_radius_siege or b.aoe_radius_siege:
            lines.append(_row("  AOE", str(a.aoe_radius_siege or "-"), str(b.aoe_radius_siege or "-")))
        mult_lines = _fmt_compare_mults(a.multipliers_siege, b.multipliers_siege)
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

    lines = [f"🏰 {civ} 可用兵种 ({len(trainable)} 个)", "━" * 30]

    for u in trainable:
        name = _unit_display_name(u)
        atk = u.attack_ranged or u.attack_melee or u.attack_siege or 0
        age_zh = t_age(u.age) if u.age else "?"
        lines.append(f"  {name:<15} │ {age_zh} │ HP {u.hp} ATK {atk:g}")

    return "\n".join(lines)
