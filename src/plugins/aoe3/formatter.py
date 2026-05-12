"""AoE3 属性卡片文本渲染。"""

from __future__ import annotations

from .models import Multiplier, Unit


def _fmt_mult(mults: list[Multiplier]) -> str:
    """格式化克制倍率列表。"""
    if not mults:
        return ""
    parts = [f"{m.vs} x{m.value:g}" for m in mults]
    return "  → " + " | ".join(parts)


def _fmt_resist(unit: Unit) -> str:
    """格式化抗性。"""
    parts = []
    if unit.armor_melee:
        parts.append(f"{unit.armor_melee:.0%}近战")
    if unit.armor_ranged:
        parts.append(f"{unit.armor_ranged:.0%}远程")
    return " ".join(parts) if parts else "无"


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
        info_parts.append(f"时代：{unit.age}")
    if unit.pop:
        info_parts.append(f"人口：{unit.pop}")
    if info_parts:
        lines.append(" | ".join(info_parts))

    if unit.cost:
        lines.append(f"费用：{unit.cost_str}")

    if unit.trained_at:
        lines.append(f"训练于：{' / '.join(unit.trained_at)}")

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
        lines.append("")
        lines.append("⚔️ 远程攻击")
        atk_parts = [f"  {unit.attack_ranged:g}伤害"]
        if unit.range:
            rng = f"{unit.range_min:g}-{unit.range:g}" if unit.range_min else f"{unit.range:g}"
            atk_parts.append(f"射程{rng}")
        if unit.rof_ranged:
            atk_parts.append(f"射速{unit.rof_ranged:g}s")
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
        lines.append(" | ".join(atk_parts))
        mult_str = _fmt_mult(unit.multipliers_siege)
        if mult_str:
            lines.append(mult_str)

    # 类型 + 文明
    if unit.type:
        lines.append("")
        lines.append(f"📋 类型：{unit.type_str}")
    if unit.civs:
        lines.append(f"文明：{'、'.join(unit.civs)}")

    return "\n".join(lines)


def render_unit_brief(unit: Unit) -> str:
    """渲染简短单行摘要（用于列表展示）。"""
    name = unit.name if unit.name != unit.name_en else unit.name_en
    atk = unit.attack_ranged or unit.attack_melee or unit.attack_siege or 0
    return f"{name} | HP {unit.hp} | ATK {atk:g} | {unit.cost_str}"


def render_compare(a: Unit, b: Unit) -> str:
    """渲染两个单位的对比卡片。"""
    lines: list[str] = []

    def _name(u: Unit) -> str:
        return u.name if u.name != u.name_en else u.name_en

    w = 18  # 列宽
    lines.append(f"{'⚔️ 兵种对比':^40}")
    lines.append("━" * 40)
    lines.append(f"{'':>{w}} │ {_name(a):<{w}}")
    lines.append(f"{'':>{w}} │ {_name(b):<{w}}")
    lines.append("─" * 40)

    def _row(label: str, va: str, vb: str) -> str:
        return f"{label:>{w}} │ {va:<{w}} │ {vb:<{w}}"

    lines.append(_row("HP", str(a.hp), str(b.hp)))
    lines.append(_row("费用", a.cost_str, b.cost_str))
    lines.append(_row("人口", str(a.pop), str(b.pop)))
    lines.append(_row("速度", f"{a.speed:g}", f"{b.speed:g}"))

    if a.attack_ranged or b.attack_ranged:
        lines.append(_row("远程攻击", f"{a.attack_ranged:g}", f"{b.attack_ranged:g}"))
        lines.append(_row("远程射程", f"{a.range:g}", f"{b.range:g}"))
    if a.attack_melee or b.attack_melee:
        lines.append(_row("近战攻击", f"{a.attack_melee:g}", f"{b.attack_melee:g}"))
    if a.attack_siege or b.attack_siege:
        lines.append(_row("攻城攻击", f"{a.attack_siege:g}", f"{b.attack_siege:g}"))

    lines.append(_row("近战抗性", f"{a.armor_melee:.0%}", f"{b.armor_melee:.0%}"))
    lines.append(_row("远程抗性", f"{a.armor_ranged:.0%}", f"{b.armor_ranged:.0%}"))

    return "\n".join(lines)


def render_counter_list(
    results: list[tuple[Unit, str, float]], target: str, *, limit: int = 10
) -> str:
    """渲染克制查询结果。"""
    if not results:
        return f"未找到克制「{target}」的兵种。"

    atk_type_zh = {"ranged": "远程", "melee": "近战", "siege": "攻城"}
    lines = [f"⚔️ 克制「{target}」的兵种 (倍率 ≥ 1.5x)", "━" * 30]

    for unit, atk_type, value in results[:limit]:
        name = unit.name if unit.name != unit.name_en else unit.name_en
        atk_zh = atk_type_zh.get(atk_type, atk_type)
        lines.append(f"  {name:<15} │ {atk_zh} x{value:g}")

    if len(results) > limit:
        lines.append(f"  … 还有 {len(results) - limit} 个")

    return "\n".join(lines)


def render_civ_units(units: list[Unit], civ: str) -> str:
    """渲染文明兵种列表（按类型分组）。"""
    if not units:
        return f"未找到「{civ}」的兵种。"

    # 按是否可训练分组
    trainable = [u for u in units if u.is_trainable]

    lines = [f"🏰 {civ} 可用兵种 ({len(trainable)} 个)", "━" * 30]

    for u in trainable:
        name = u.name if u.name != u.name_en else u.name_en
        atk = u.attack_ranged or u.attack_melee or u.attack_siege or 0
        lines.append(f"  {name:<15} │ {u.age or '?'} │ HP {u.hp} ATK {atk:g}")

    return "\n".join(lines)
