"""红警2斗蛐蛐 —— 战报与事件摘要（纯文本）。"""

from __future__ import annotations

from dataclasses import dataclass

from .locale import localized_actor_name, localized_weapon_label
from .repo import load_actors
from .simulator import BattleResult, EventType, Side


def _label_actor(actor_id: str) -> str:
    actors = load_actors()
    a = actors.get(actor_id)
    return localized_actor_name(actor_id, a.name if a else actor_id)


def _label_weapon(weapon_id: str) -> str:
    return localized_weapon_label(weapon_id)


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
                    f"💥 {_label_actor(p['attacker'])} 击毁 "
                    f"{_label_actor(p['target'])}（{_label_weapon(p['weapon'])}）"
                )
            elif ev.type == EventType.CRUSH:
                lines.append(
                    f"🛞 {_label_actor(p['crusher'])} 碾压 {_label_actor(p['victim'])}"
                )
            elif ev.type == EventType.DEATH and ev.tick > 0:
                pass  # 已在 ATTACK 0hp 报过

        if not lines:
            for ev in self.result.events:
                if ev.type != EventType.ATTACK:
                    continue
                p = ev.payload
                lines.append(
                    f"⚔ {_label_actor(p['attacker'])} → {_label_actor(p['target'])} "
                    f"-{p['damage']} (剩{p['target_hp']}HP)"
                )
                if len(lines) >= self.max_lines:
                    break

        if lines:
            text = "━━━ 战斗速递 ━━━\n" + "\n".join(lines[: self.max_lines])
            segs.append(BroadcastSegment(text, should_sleep=True))

        # 战报 + 押注结算由 game._run_battle 合并为一条发送（避免与结算重复）
        return segs
