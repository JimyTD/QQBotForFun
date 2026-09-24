"""AoE3 斗蛐蛐 —— 最终战报与公共格式。

正式群局不再生成逐窗口过程播报；本模块保留最终文字战报、血条和资源损失
统计，供普通对局与 CLI 复用，并为回放结尾汇总提供同一份结果口径。
"""

from __future__ import annotations

from .battle_contract import BattleResult, Side

# =====================================================================
# 血条渲染
# =====================================================================
_HP_BAR_LEN = 10


def _hp_bar(current: float, maximum: float, filled: str, empty: str = "⬛") -> str:
    """生成 emoji 血条。"""
    if maximum <= 0:
        return empty * _HP_BAR_LEN
    pct = max(0.0, min(1.0, current / maximum))
    filled_count = round(pct * _HP_BAR_LEN)
    return filled * filled_count + empty * (_HP_BAR_LEN - filled_count)


def _hp_summary(current: float, maximum: float) -> str:
    """百分比 + 数值，全灭时特殊显示。"""
    if maximum <= 0:
        return "0%"
    pct = max(0.0, current / maximum) * 100
    if current <= 0:
        return "0%"
    return f"{pct:.0f}%  ({current:.0f}/{maximum:.0f})"


# =====================================================================
# 最终战报生成
# =====================================================================
def battle_resource_loss(result: BattleResult) -> tuple[int, int]:
    """返回双方阵亡单位的训练资源损失（不含人口折算）。"""
    red_loss = sum(sum(s.unit.cost.values()) for s in result.red_dead)
    blue_loss = sum(sum(s.unit.cost.values()) for s in result.blue_dead)
    return red_loss, blue_loss


def format_battle_report(result: BattleResult) -> str:
    """生成最终战报文本。"""
    lines = []

    # 标题
    lines.append("🏆 ━━━ 战斗结果 ━━━")

    # 胜负
    if result.winner is None:
        lines.append("结果：平局")
    elif result.winner == Side.RED:
        lines.append("胜方：🔴 红方（1号）")
    else:
        lines.append("胜方：🔵 蓝方（2号）")

    if result.timeout:
        lines.append("（超时判定 — 按剩余资源价值）")

    lines.append(f"战斗时长：{result.duration:.1f} 秒")
    lines.append("")

    # 血条
    red_all = result.red_alive + result.red_dead
    blue_all = result.blue_alive + result.blue_dead
    red_max_hp = sum(s.max_hp for s in red_all)
    red_cur_hp = sum(s.hp for s in result.red_alive)
    blue_max_hp = sum(s.max_hp for s in blue_all)
    blue_cur_hp = sum(s.hp for s in result.blue_alive)

    lines.append(f"🔴 {_hp_bar(red_cur_hp, red_max_hp, '🟥')}  {_hp_summary(red_cur_hp, red_max_hp)}")
    lines.append(f"🔵 {_hp_bar(blue_cur_hp, blue_max_hp, '🟦')}  {_hp_summary(blue_cur_hp, blue_max_hp)}")
    red_loss, blue_loss = battle_resource_loss(result)
    lines.append(f"💸 战损资源：红方 {red_loss} ｜ 蓝方 {blue_loss}")
    lines.append("")

    # 红方
    for slot in result.red_army:
        soldiers_of_type = [s for s in red_all if s.unit.id == slot.unit.id]
        alive_of_type = [s for s in result.red_alive if s.unit.id == slot.unit.id]
        kills = sum(s.kills for s in soldiers_of_type)
        dmg = sum(s.total_damage_dealt for s in soldiers_of_type)
        status = f"存活{len(alive_of_type)}"
        lines.append(
            f"🔴 {slot.unit.name} ×{slot.count}"
            f" → {status}/击杀{kills}/有效伤害{dmg:.0f}"
        )
    lines.append("──────────")

    # 蓝方
    for slot in result.blue_army:
        soldiers_of_type = [s for s in blue_all if s.unit.id == slot.unit.id]
        alive_of_type = [s for s in result.blue_alive if s.unit.id == slot.unit.id]
        kills = sum(s.kills for s in soldiers_of_type)
        dmg = sum(s.total_damage_dealt for s in soldiers_of_type)
        status = f"存活{len(alive_of_type)}"
        lines.append(
            f"🔵 {slot.unit.name} ×{slot.count}"
            f" → {status}/击杀{kills}/有效伤害{dmg:.0f}"
        )

    return "\n".join(lines)
