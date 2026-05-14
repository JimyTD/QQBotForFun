"""AoE3 斗蛐蛐 —— 播报层。

将模拟器输出的结构化事件流转换为播报文本。
支持两种输出模式：
- CLI 终端彩色文本
- QQ 群纯文本消息

设计文档：docs/games/aoe3-battle.md §八
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .simulator import (
    BattleEvent,
    BattlePhase,
    BattleResult,
    EventType,
    Side,
    TICK_INTERVAL,
)

# =====================================================================
# 常量
# =====================================================================
WINDOW_SECONDS = 2.0         # 播报窗口（秒）
WINDOW_TICKS = int(WINDOW_SECONDS / TICK_INTERVAL)  # 20 ticks
MASS_CASUALTY_THRESHOLD = 4  # 重大伤亡阈值

# =====================================================================
# 动态选词（§8.5）
# =====================================================================
ACTION_WORDS: dict[str, list[str]] = {
    "1": ["开火", "击中", "点掉一个"],
    "2-3": ["齐射", "一轮射击", "连发"],
    "4+": ["集火屠戮", "致命齐射", "一波带走"],
}

# 沉默期填充话术（§8.4）
FILLER_APPROACHING = [
    "⏳ 双方仍在接近，剑拔弩张...",
    "⏳ 战鼓未响，杀机已生",
    "⏳ 红蓝双方逐渐靠近射程",
]

FILLER_FIGHTING = [
    "⏳ 双方激烈交火，暂无伤亡",
    "⏳ 装甲互啃，子弹打在肉身上像挠痒...",
    "⏳ 互相伤害中，HP 缓慢下降",
    "⏳ 重甲单位的较量，比的就是耐心",
]

FILLER_STALEMATE = [
    "⏳ 双方都已残血，下一击可能就是终结",
    "⏳ 鏖战至此，胜负只在一念之间",
]


def _pick_action_word(kill_count: int, rng: random.Random) -> str:
    """按死亡数选动词。"""
    if kill_count <= 1:
        return rng.choice(ACTION_WORDS["1"])
    elif kill_count <= 3:
        return rng.choice(ACTION_WORDS["2-3"])
    else:
        return rng.choice(ACTION_WORDS["4+"])


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
    is_key_event: bool = False   # 关键节点（开战/首杀/终结等）
    should_sleep: bool = True    # 是否需要 sleep（零伤亡填充不 sleep）
    time_start: float = 0.0
    time_end: float = 0.0


# =====================================================================
# 播报生成器
# =====================================================================
class Broadcaster:
    """将事件流转换为播报文本序列。"""

    def __init__(
        self,
        result: BattleResult,
        *,
        seed: int | None = None,
    ) -> None:
        self.result = result
        self._rng = random.Random(seed)
        self._segments: list[BroadcastSegment] = []

        # 运行时存活计数（用于战况行）
        self._red_remaining = result.red_count
        self._blue_remaining = result.blue_count

        # 沉默期填充状态
        self._filler_pools: dict[str, list[str]] = {
            BattlePhase.APPROACHING.value: list(FILLER_APPROACHING),
            BattlePhase.FIGHTING.value: list(FILLER_FIGHTING),
            BattlePhase.STALEMATE.value: list(FILLER_STALEMATE),
        }

    def generate(self) -> list[BroadcastSegment]:
        """生成完整播报序列。"""
        self._segments = []
        events = self.result.events

        # 1. 开战
        self._emit_battle_start(events)

        # 2. 按 2 秒窗口分批
        max_time = self.result.duration
        window_start = 0.0
        first_death_emitted = False
        half_red_emitted = False
        half_blue_emitted = False
        consecutive_silent = 0

        while window_start < max_time:
            window_end = window_start + WINDOW_SECONDS

            # 收集窗口内事件
            window_events = [
                e for e in events
                if window_start <= e.time < window_end
                and e.event_type in (EventType.ATTACK, EventType.DEATH,
                                     EventType.AOE_SPLASH)
            ]

            # 统计死亡
            deaths = [
                e for e in window_events if e.event_type == EventType.DEATH
            ]
            red_deaths = [d for d in deaths if d.data["side"] == "red"]
            blue_deaths = [d for d in deaths if d.data["side"] == "blue"]

            # 更新存活计数
            self._red_remaining -= len(red_deaths)
            self._blue_remaining -= len(blue_deaths)

            # ---- 关键节点 ----

            # 首杀
            if deaths and not first_death_emitted:
                first_death_emitted = True
                d = deaths[0]
                killer_emoji = _side_emoji(d.data["killer_side"])
                victim_emoji = _side_emoji(d.data["side"])
                self._segments.append(BroadcastSegment(
                    text=(
                        f"🩸 第 {d.time:.1f}s，"
                        f"{killer_emoji} {d.data['killer_name']}率先溅血，"
                        f"{victim_emoji} {d.data['soldier_name']} -1"
                    ),
                    is_key_event=True,
                    time_start=window_start,
                    time_end=window_end,
                ))

            # 重大伤亡（单个 tick 内同一攻击者造成 ≥4 人死亡）
            self._check_mass_casualty(deaths, window_start, window_end)

            # 半灭线
            for d in deaths:
                side = d.data["side"]
                remaining = d.data["remaining"]
                total = d.data["total"]
                if remaining <= total / 2:
                    if side == "red" and not half_red_emitted:
                        half_red_emitted = True
                        self._segments.append(BroadcastSegment(
                            text=f"⚠️ 🔴 已损失过半（剩 {remaining}/{total}），战况告急",
                            is_key_event=True,
                            time_start=window_start,
                            time_end=window_end,
                        ))
                    elif side == "blue" and not half_blue_emitted:
                        half_blue_emitted = True
                        self._segments.append(BroadcastSegment(
                            text=f"⚠️ 🔵 已损失过半（剩 {remaining}/{total}），战况告急",
                            is_key_event=True,
                            time_start=window_start,
                            time_end=window_end,
                        ))

            # ---- 标准/极简片段 ----
            if deaths:
                consecutive_silent = 0
                self._emit_window_segment(
                    window_start, window_end,
                    red_deaths, blue_deaths,
                    window_events,
                )
            else:
                consecutive_silent += 1
                # 沉默期填充（§8.4）
                if consecutive_silent >= 2 and consecutive_silent % 2 == 0:
                    self._emit_filler(window_start, window_end, window_events)

            window_start = window_end

        # 3. 终结
        self._emit_battle_end(events)

        return self._segments

    def _emit_battle_start(self, events: list[BattleEvent]) -> None:
        """开战播报。"""
        r = self.result

        # 多兵种时显示详细阵容
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

    def _emit_battle_end(self, events: list[BattleEvent]) -> None:
        """终结播报。"""
        r = self.result
        end_event = next(
            (e for e in events if e.event_type == EventType.BATTLE_END), None
        )
        if end_event is None:
            return

        d = end_event.data
        if d["winner"] == "draw":
            self._segments.append(BroadcastSegment(
                text=f"🏳️ 第 {d['duration']}s，战斗结束 — 平局！",
                is_key_event=True,
                time_start=end_event.time,
                time_end=end_event.time,
            ))
        else:
            winner_emoji = _side_emoji(d["winner"])
            loser_side = "blue" if d["winner"] == "red" else "red"
            # 找最后一个死亡事件
            last_death = None
            for e in reversed(events):
                if e.event_type == EventType.DEATH:
                    last_death = e
                    break

            if last_death and last_death.data["side"] == loser_side:
                killer_name = last_death.data["killer_name"]
                self._segments.append(BroadcastSegment(
                    text=(
                        f"☠️ 第 {last_death.time:.1f}s，"
                        f"{winner_emoji} {killer_name}踏平最后一名敌兵"
                    ),
                    is_key_event=True,
                    time_start=end_event.time,
                    time_end=end_event.time,
                ))
            else:
                winner_label = _side_label(d["winner"])
                self._segments.append(BroadcastSegment(
                    text=f"🏆 第 {d['duration']}s，{winner_emoji} {winner_label}获胜！",
                    is_key_event=True,
                    time_start=end_event.time,
                    time_end=end_event.time,
                ))

    def _check_mass_casualty(
        self,
        deaths: list[BattleEvent],
        window_start: float,
        window_end: float,
    ) -> None:
        """检查重大伤亡（单个 tick 内 ≥4 人死亡）。"""
        # 按 tick 分组
        by_tick: dict[int, list[BattleEvent]] = {}
        for d in deaths:
            by_tick.setdefault(d.tick, []).append(d)

        for tick, tick_deaths in by_tick.items():
            if len(tick_deaths) >= MASS_CASUALTY_THRESHOLD:
                # 找出主要攻击者（按 killer 分组）
                by_killer: dict[str, list[BattleEvent]] = {}
                for d in tick_deaths:
                    key = f"{d.data['killer_side']}:{d.data['killer_name']}"
                    by_killer.setdefault(key, []).append(d)

                for key, killer_deaths in by_killer.items():
                    if len(killer_deaths) >= MASS_CASUALTY_THRESHOLD:
                        d0 = killer_deaths[0]
                        killer_emoji = _side_emoji(d0.data["killer_side"])
                        victim_emoji = _side_emoji(d0.data["side"])
                        self._segments.append(BroadcastSegment(
                            text=(
                                f"💥 第 {d0.time:.1f}s，"
                                f"{killer_emoji} {d0.data['killer_name']}"
                                f"一炮带走 "
                                f"{victim_emoji} {d0.data['soldier_name']} ×{len(killer_deaths)}！"
                            ),
                            is_key_event=True,
                            time_start=window_start,
                            time_end=window_end,
                        ))

    def _emit_window_segment(
        self,
        window_start: float,
        window_end: float,
        red_deaths: list[BattleEvent],
        blue_deaths: list[BattleEvent],
        window_events: list[BattleEvent],
    ) -> None:
        """生成标准/极简播报片段。"""
        lines = [f"⏱ {window_start:.0f}-{window_end:.0f}s"]

        total_deaths = len(red_deaths) + len(blue_deaths)

        if total_deaths <= 2:
            # 极简片段
            parts = []
            if red_deaths:
                parts.append(f"🔴 -{len(red_deaths)}")
            if blue_deaths:
                parts.append(f"🔵 -{len(blue_deaths)}")
            lines.append(f"🔥 拉锯：{' / '.join(parts)}")
        else:
            # 标准片段
            # 蓝方造成的红方死亡
            if red_deaths:
                action = _pick_action_word(len(red_deaths), self._rng)
                # 找出攻击者兵种名
                killer_name = red_deaths[0].data.get("killer_name", "?")
                lines.append(
                    f"🔵 {killer_name}{action}，"
                    f"🔴 {red_deaths[0].data['soldier_name']} "
                    f"-{len(red_deaths)}"
                    f"（剩 {red_deaths[-1].data['remaining']}/{red_deaths[-1].data['total']}）"
                )
            # 红方造成的蓝方死亡
            if blue_deaths:
                action = _pick_action_word(len(blue_deaths), self._rng)
                killer_name = blue_deaths[0].data.get("killer_name", "?")
                lines.append(
                    f"🔴 {killer_name}{action}，"
                    f"🔵 {blue_deaths[0].data['soldier_name']} "
                    f"-{len(blue_deaths)}"
                    f"（剩 {blue_deaths[-1].data['remaining']}/{blue_deaths[-1].data['total']}）"
                )

        # 战况行
        # 从最后一个死亡事件获取当前存活数
        last_death = None
        for d in reversed(red_deaths + blue_deaths):
            last_death = d
            break

        # 战况行（使用全局存活计数）
        lines.append(
            f"📊 战况 🔴 {self._red_remaining}/{self.result.red_count}"
            f" vs 🔵 {self._blue_remaining}/{self.result.blue_count}"
        )

        self._segments.append(BroadcastSegment(
            text="\n".join(lines),
            time_start=window_start,
            time_end=window_end,
        ))

    def _emit_filler(
        self,
        window_start: float,
        window_end: float,
        window_events: list[BattleEvent],
    ) -> None:
        """沉默期填充消息。"""
        # 判断当前阶段
        has_attacks = any(
            e.event_type == EventType.ATTACK
            for e in self.result.events
            if e.time <= window_end
        )

        if not has_attacks:
            phase = BattlePhase.APPROACHING.value
        else:
            # 用存活人数比例近似判断僵持（§8.4：双方剩余 < 30% 为僵持期）
            red_pct = self._red_remaining / self.result.red_count if self.result.red_count else 0
            blue_pct = self._blue_remaining / self.result.blue_count if self.result.blue_count else 0
            if red_pct < 0.3 and blue_pct < 0.3:
                phase = BattlePhase.STALEMATE.value
            else:
                phase = BattlePhase.FIGHTING.value

        pool = self._filler_pools.get(phase, FILLER_FIGHTING)
        if not pool:
            # 池子用完，重置
            if phase == BattlePhase.APPROACHING.value:
                pool = list(FILLER_APPROACHING)
            elif phase == BattlePhase.STALEMATE.value:
                pool = list(FILLER_STALEMATE)
            else:
                pool = list(FILLER_FIGHTING)
            self._filler_pools[phase] = pool

        text = pool.pop(self._rng.randrange(len(pool)))

        self._segments.append(BroadcastSegment(
            text=text,
            should_sleep=False,
            time_start=window_start,
            time_end=window_end,
        ))


# =====================================================================
# 最终战报生成（§8.6）
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
    red_alive_count = len(result.red_alive)
    if red_alive_count == 0:
        lines.append("🔴 红方 全军覆没")
        for slot in result.red_army:
            lines.append(f"  · {slot.unit.name} ×{slot.count} → 0")
    else:
        lost = result.red_count - red_alive_count
        if lost == 0:
            lines.append("🔴 红方 零伤亡")
        else:
            lines.append("🔴 红方 残兵")
        # 按兵种统计存活
        for slot in result.red_army:
            alive_of_type = [s for s in result.red_alive if s.unit.id == slot.unit.id]
            dead_of_type = slot.count - len(alive_of_type)
            if len(alive_of_type) == 0:
                lines.append(f"  · {slot.unit.name} ×{slot.count} → 0")
            elif len(alive_of_type) == 1 and dead_of_type > 0:
                s = alive_of_type[0]
                lines.append(
                    f"  · {slot.unit.name} ×{len(alive_of_type)}"
                    f"（损失 {dead_of_type}/{slot.count}，HP {s.hp:.0f}/{s.max_hp:.0f}）"
                )
            else:
                lines.append(
                    f"  · {slot.unit.name} ×{len(alive_of_type)}"
                    f"（损失 {dead_of_type}/{slot.count}）"
                )
    lines.append("")

    # 蓝方
    blue_alive_count = len(result.blue_alive)
    if blue_alive_count == 0:
        lines.append("🔵 蓝方 全军覆没")
        for slot in result.blue_army:
            lines.append(f"  · {slot.unit.name} ×{slot.count} → 0")
    else:
        lost = result.blue_count - blue_alive_count
        if lost == 0:
            lines.append("🔵 蓝方 零伤亡")
        else:
            lines.append("🔵 蓝方 残兵")
        for slot in result.blue_army:
            alive_of_type = [s for s in result.blue_alive if s.unit.id == slot.unit.id]
            dead_of_type = slot.count - len(alive_of_type)
            if len(alive_of_type) == 0:
                lines.append(f"  · {slot.unit.name} ×{slot.count} → 0")
            elif len(alive_of_type) == 1 and dead_of_type > 0:
                s = alive_of_type[0]
                lines.append(
                    f"  · {slot.unit.name} ×{len(alive_of_type)}"
                    f"（损失 {dead_of_type}/{slot.count}，HP {s.hp:.0f}/{s.max_hp:.0f}）"
                )
            else:
                lines.append(
                    f"  · {slot.unit.name} ×{len(alive_of_type)}"
                    f"（损失 {dead_of_type}/{slot.count}）"
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
        # 综合分 = 伤害×0.5 + 击杀×50
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
