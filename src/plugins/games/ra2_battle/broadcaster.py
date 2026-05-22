"""红警2斗蛐蛐 —— 战报与事件摘要（纯文本）。"""

from __future__ import annotations

from dataclasses import dataclass

from .simulator import BattleResult, EventType, Side


@dataclass
class BroadcastSegment:
    text: str
    should_sleep: bool = True


def format_battle_report(result: BattleResult) -> str:
    if result.winner == Side.RED:
        win_line = "🏆 胜方：🔴 红方"
    elif result.winner == Side.BLUE:
        win_line = "🏆 胜方：🔵 蓝方"
    else:
        win_line = "🏆 平局"

    red_n = len(result.red_alive)
    blue_n = len(result.blue_alive)
    return (
        "━━━ 红警2 战报 ━━━\n"
        f"{win_line}\n"
        f"时长 {result.duration:.1f}s · tick {result.ticks}\n"
        f"🔴 存活 {red_n} · 🔵 存活 {blue_n}"
    )


class Broadcaster:
    """极简播报：开战摘要 + 关键击杀 + 结尾战报。"""

    def __init__(self, result: BattleResult, *, max_lines: int = 12) -> None:
        self.result = result
        self.max_lines = max_lines

    def generate(self) -> list[BroadcastSegment]:
        segs: list[BroadcastSegment] = []
        lines: list[str] = []
        for ev in self.result.events:
            p = ev.payload
            if ev.type == EventType.ATTACK and p.get("target_hp", 1) == 0:
                lines.append(
                    f"💥 {p['attacker']} 击毁 {p['target']}（{p['weapon']}）"
                )
            elif ev.type == EventType.CRUSH:
                lines.append(f"🛞 {p['crusher']} 碾压 {p['victim']}")
            elif ev.type == EventType.DEATH and ev.tick > 0:
                pass  # 已在 ATTACK 0hp 报过

        if not lines:
            for ev in self.result.events:
                if ev.type != EventType.ATTACK:
                    continue
                p = ev.payload
                lines.append(
                    f"⚔ {p['attacker']} → {p['target']} -{p['damage']} "
                    f"(剩{p['target_hp']}HP)"
                )
                if len(lines) >= self.max_lines:
                    break

        if lines:
            text = "━━━ 战斗速递 ━━━\n" + "\n".join(lines[: self.max_lines])
            segs.append(BroadcastSegment(text, should_sleep=True))

        segs.append(
            BroadcastSegment(format_battle_report(self.result), should_sleep=False)
        )
        return segs
