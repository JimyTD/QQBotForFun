"""AoE3 斗蛐蛐 —— 播报层。

将模拟器输出的结构化事件流转换为播报文本。

两种播报模式（群级别持久设置）：
- "brief"（极简，默认）：开战 → 全灭播报 → 最终战报
- "detailed"（详细）：开战 → 首次攻击模式 + 5段动态窗口 + 全灭播报 → 最终战报
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .simulator import (
    BattleEvent,
    BattleResult,
    EventType,
    Side,
)
from .phrases import (
    ACTION_WORDS,
    FIRST_ATTACK_MODE_TEMPLATES,
    UNIT_WIPED_TEMPLATES,
)

# =====================================================================
# 播报模式常量
# =====================================================================
MODE_BRIEF = "brief"
MODE_DETAILED = "detailed"

# 详细模式下等分窗口数量上限
DETAILED_WINDOW_COUNT = 5

# =====================================================================
# 伤害分类
# =====================================================================
_GUNPOWDER_TAGS = {
    "AbstractGunpowderTrooper", "AbstractMusketeer", "AbstractRifleman",
}
_ARCHER_TAGS = {"AbstractArcher"}
_ARTILLERY_TAGS = {"AbstractArtillery"}


def _classify_attack(
    attack_mode: str,
    damage_type: str,
    unit_type: list[str] | None = None,
) -> str:
    """根据攻击模式 + 伤害类型 + 单位标签选定术语分类。"""
    type_set = set(unit_type) if unit_type else set()

    if attack_mode in ("ranged", "ranged_penalized"):
        if damage_type == "Siege":
            if type_set & _ARTILLERY_TAGS:
                return "ranged_siege_art"
            return "ranged_siege"
        if type_set & _GUNPOWDER_TAGS:
            return "ranged_gunpowder"
        if type_set & _ARCHER_TAGS:
            return "ranged_archer"
        return "ranged_normal"

    if damage_type == "Siege":
        return "melee_siege"
    return "melee_hand"


def _pick_action_word(
    kill_count: int,
    rng: random.Random,
    attack_class: str = "ranged_normal",
) -> str:
    """按死亡数 + 伤害分类选动词。"""
    words = ACTION_WORDS.get(attack_class, ACTION_WORDS["ranged_normal"])
    if kill_count <= 1:
        return rng.choice(words["1"])
    elif kill_count <= 3:
        return rng.choice(words["2-3"])
    else:
        return rng.choice(words["4+"])


def _side_emoji(side: str) -> str:
    return "🔴" if side == "red" else "🔵"


def _side_label(side: str) -> str:
    return "红方" if side == "red" else "蓝方"


# =====================================================================
# 播报片段
# =====================================================================
@dataclass
class BroadcastSegment:
    """一条播报消息。"""
    text: str
    is_key_event: bool = False
    should_sleep: bool = True
    time_start: float = 0.0
    time_end: float = 0.0


# =====================================================================
# 播报生成器
# =====================================================================
class Broadcaster:
    """将事件流转换为播报文本序列。

    Args:
        result: 战斗结果
        mode: 播报模式 ("brief" 或 "detailed")
        seed: 随机种子
    """

    def __init__(
        self,
        result: BattleResult,
        *,
        mode: str = MODE_BRIEF,
        seed: int | None = None,
    ) -> None:
        self.result = result
        self.mode = mode if mode in (MODE_BRIEF, MODE_DETAILED) else MODE_BRIEF
        self._rng = random.Random(seed)
        self._segments: list[BroadcastSegment] = []

    def generate(self) -> list[BroadcastSegment]:
        """生成完整播报序列。"""
        self._segments = []
        events = self.result.events

        # 1. 开战
        self._emit_battle_start()

        # 2. 详细模式：首次攻击模式 + 动态窗口
        if self.mode == MODE_DETAILED:
            self._emit_detailed_segments(events)

        # 3. 全灭播报（两种模式都有）
        self._emit_unit_wiped(events)

        return self._segments

    # ------------------------------------------------------------------
    # 开战
    # ------------------------------------------------------------------
    def _emit_battle_start(self) -> None:
        """开战播报。"""
        r = self.result

        if len(r.red_army) > 1:
            red_desc = " + ".join(f"{s.count}{s.unit.name}" for s in r.red_army)
        else:
            red_desc = f"{r.red_count} {r.red_unit.name}"

        if len(r.blue_army) > 1:
            blue_desc = " + ".join(f"{s.count}{s.unit.name}" for s in r.blue_army)
        else:
            blue_desc = f"{r.blue_count} {r.blue_unit.name}"

        self._segments.append(BroadcastSegment(
            text=(
                f"⚔️ 战斗打响！"
                f"🔴 [{red_desc}] vs "
                f"🔵 [{blue_desc}]"
            ),
            is_key_event=True,
            time_start=0,
            time_end=0,
        ))

    # ------------------------------------------------------------------
    # 详细模式：动态窗口播报
    # ------------------------------------------------------------------
    def _emit_detailed_segments(self, events: list[BattleEvent]) -> None:
        """详细模式：首次攻击模式 + 等分时间轴为5段。"""
        # 首次攻击模式
        self._emit_first_attack_mode(events)

        # 等分时间轴
        duration = self.result.duration
        if duration <= 0:
            return

        window_size = duration / DETAILED_WINDOW_COUNT
        red_remaining = self.result.red_count
        blue_remaining = self.result.blue_count

        for i in range(DETAILED_WINDOW_COUNT):
            w_start = i * window_size
            w_end = (i + 1) * window_size

            # 收集窗口内死亡事件
            deaths = [
                e for e in events
                if w_start <= e.time < w_end
                and e.event_type == EventType.DEATH
            ]

            if not deaths:
                # 更新计数但不输出
                continue

            # 统计
            red_deaths = [d for d in deaths if d.data["side"] == "red"]
            blue_deaths = [d for d in deaths if d.data["side"] == "blue"]
            red_remaining -= len(red_deaths)
            blue_remaining -= len(blue_deaths)

            # 构建消息
            lines = [f"⏱ {w_start:.0f}-{w_end:.0f}s"]

            # 蓝方造成红方死亡
            if red_deaths:
                killer_class = _classify_attack(
                    red_deaths[0].data.get("killer_attack_mode", "ranged"),
                    red_deaths[0].data.get("killer_damage_type", "Ranged"),
                    red_deaths[0].data.get("killer_unit_type", []),
                )
                action = _pick_action_word(len(red_deaths), self._rng, killer_class)
                killer_name = red_deaths[0].data.get("killer_name", "?")
                lines.append(
                    f"🔵 {killer_name}{action} → "
                    f"🔴 {red_deaths[0].data['soldier_name']} -{len(red_deaths)}"
                )

            # 红方造成蓝方死亡
            if blue_deaths:
                killer_class = _classify_attack(
                    blue_deaths[0].data.get("killer_attack_mode", "ranged"),
                    blue_deaths[0].data.get("killer_damage_type", "Ranged"),
                    blue_deaths[0].data.get("killer_unit_type", []),
                )
                action = _pick_action_word(len(blue_deaths), self._rng, killer_class)
                killer_name = blue_deaths[0].data.get("killer_name", "?")
                lines.append(
                    f"🔴 {killer_name}{action} → "
                    f"🔵 {blue_deaths[0].data['soldier_name']} -{len(blue_deaths)}"
                )

            # 战况行
            lines.append(
                f"📊 🔴 {red_remaining}/{self.result.red_count}"
                f" vs 🔵 {blue_remaining}/{self.result.blue_count}"
            )

            self._segments.append(BroadcastSegment(
                text="\n".join(lines),
                time_start=w_start,
                time_end=w_end,
            ))

    def _emit_first_attack_mode(self, events: list[BattleEvent]) -> None:
        """首次攻击模式播报（首次远程/近战）。"""
        seen_modes: set[str] = set()
        for e in events:
            if e.event_type != EventType.ATTACK:
                continue
            if e.data.get("is_splash"):
                continue
            mode = e.data["mode"]
            effective_mode = "melee" if mode == "ranged_penalized" else mode
            if effective_mode in seen_modes:
                continue
            seen_modes.add(effective_mode)
            templates = FIRST_ATTACK_MODE_TEMPLATES.get(effective_mode)
            if templates:
                atk_emoji = _side_emoji(e.data["attacker_side"])
                self._segments.append(BroadcastSegment(
                    text=self._rng.choice(templates).format(
                        time=e.time,
                        attacker_emoji=atk_emoji,
                        attacker_name=e.data["attacker_name"],
                    ),
                    is_key_event=True,
                    time_start=e.time,
                    time_end=e.time,
                ))
            if len(seen_modes) >= 2:
                break

    # ------------------------------------------------------------------
    # 全灭播报（两种模式都显示）
    # ------------------------------------------------------------------
    def _emit_unit_wiped(self, events: list[BattleEvent]) -> None:
        """当某个兵种全部阵亡时播报。按实际全灭时间排序。"""
        # 从 army slots 获取每种兵的总数
        unit_totals: dict[tuple[str, str, str], int] = {}  # (side, unit_id, unit_name) -> count

        for slot in self.result.red_army:
            unit_totals[("red", slot.unit.id, slot.unit.name)] = slot.count
        for slot in self.result.blue_army:
            unit_totals[("blue", slot.unit.id, slot.unit.name)] = slot.count

        # 按 side+unit_id 统计死亡数和最后死亡时间
        death_counts: dict[tuple[str, str], int] = {}
        death_times: dict[tuple[str, str], float] = {}

        for e in events:
            if e.event_type != EventType.DEATH:
                continue
            unit_id = e.data.get("soldier_unit_id", "")
            if not unit_id:
                unit_id = e.data.get("soldier_name", "")
            key = (e.data["side"], unit_id)
            death_counts[key] = death_counts.get(key, 0) + 1
            death_times[key] = e.time

        # 收集全灭事件并按时间排序
        wiped_events: list[tuple[float, str, str, int]] = []  # (time, emoji, unit_name, count)
        for (side, unit_id, unit_name), total in unit_totals.items():
            key = (side, unit_id)
            died = death_counts.get(key, 0)
            if died >= total and total > 0:
                emoji = _side_emoji(side)
                time = death_times.get(key, 0)
                wiped_events.append((time, emoji, unit_name, total))

        # 按全灭时间排序后输出
        wiped_events.sort(key=lambda x: x[0])
        for time, emoji, unit_name, count in wiped_events:
            tpl = self._rng.choice(UNIT_WIPED_TEMPLATES)
            self._segments.append(BroadcastSegment(
                text=tpl.format(emoji=emoji, unit_name=unit_name, count=count),
                is_key_event=True,
                time_start=time,
                time_end=time,
            ))


# =====================================================================
# 最终战报生成
# =====================================================================
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

    # 红方
    red_all = result.red_alive + result.red_dead
    for slot in result.red_army:
        soldiers_of_type = [s for s in red_all if s.unit.id == slot.unit.id]
        alive_of_type = [s for s in result.red_alive if s.unit.id == slot.unit.id]
        kills = sum(s.kills for s in soldiers_of_type)
        dmg = sum(s.total_damage_dealt for s in soldiers_of_type)
        if len(alive_of_type) == 0:
            status = "全灭"
        else:
            status = f"存活{len(alive_of_type)}"
        lines.append(
            f"🔴 {slot.unit.name} ×{slot.count}"
            f" → {status}/击杀{kills}/伤害{dmg:.0f}"
        )
    lines.append("──────────")

    # 蓝方
    blue_all = result.blue_alive + result.blue_dead
    for slot in result.blue_army:
        soldiers_of_type = [s for s in blue_all if s.unit.id == slot.unit.id]
        alive_of_type = [s for s in result.blue_alive if s.unit.id == slot.unit.id]
        kills = sum(s.kills for s in soldiers_of_type)
        dmg = sum(s.total_damage_dealt for s in soldiers_of_type)
        if len(alive_of_type) == 0:
            status = "全灭"
        else:
            status = f"存活{len(alive_of_type)}"
        lines.append(
            f"🔵 {slot.unit.name} ×{slot.count}"
            f" → {status}/击杀{kills}/伤害{dmg:.0f}"
        )
    lines.append("")

    # MVP（仅胜方评选）
    all_soldiers = (
        result.red_alive + result.red_dead
        + result.blue_alive + result.blue_dead
    )

    if result.winner is not None:
        mvp_candidates = [s for s in all_soldiers if s.side == result.winner]
    else:
        mvp_candidates = []

    if mvp_candidates:
        mvp_candidates.sort(
            key=lambda s: s.total_damage_dealt * 0.5 + s.kills * 50,
            reverse=True,
        )
        mvp = mvp_candidates[0]
        mvp_score = mvp.total_damage_dealt * 0.5 + mvp.kills * 50
        mvp_emoji = _side_emoji(mvp.side.value)
        lines.append(
            f"🎖 MVP：{mvp_emoji} {mvp.name} #{mvp.id}"
        )
        lines.append(
            f"   伤害 {mvp.total_damage_dealt:.0f} / "
            f"击杀 {mvp.kills} / "
            f"综合分 {mvp_score:.1f}"
        )

    return "\n".join(lines)
