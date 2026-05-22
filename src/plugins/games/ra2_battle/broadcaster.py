"""红警2斗蛐蛐 —— 播报层（对齐 aoe3_battle 结构，共用群级 brief/detailed 设置）。"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .constants import TICK_SECONDS
from .locale import localized_actor_name
from .phrases import (
    ACTION_WORDS,
    FIRST_ATTACK_MODE_TEMPLATES,
    UNIT_WIPED_TEMPLATES,
)
from .repo import load_actors
from .simulator import BattleEvent, BattleResult, EventType, Side

MODE_BRIEF = "brief"
MODE_DETAILED = "detailed"
DETAILED_WINDOW_COUNT = 5

# 与 aoe3_battle 共用群配置键
BROADCAST_MODE_CONFIG_KEY = "aoe3_battle.broadcast_mode"

_MELEE_WEAPONS = frozenset({"DogJaw"})
_ARTILLERY_PREFIXES = ("105mm", "120mm", "155mm", "20mm")
_MISSILE_WEAPONS = frozenset({
    "Missile", "MissileE", "Medusa", "MedusaE", "Dragon", "DragonE",
    "HornetBomb", "ASWBomb", "SubTorpedo",
})
_ENERGY_WEAPONS = frozenset({
    "CRTeslaZap", "CRTeslaZapE", "CRRadBeamWeapon", "CRRadBeamWeaponE",
    "CRPrism", "CRPrismE", "DiskLaser", "DiskDrain",
})


def _label_actor(actor_id: str) -> str:
    actors = load_actors()
    a = actors.get(actor_id)
    return localized_actor_name(actor_id, a.name if a else actor_id)


def _side_emoji(side: str) -> str:
    return "🔴" if side == "red" else "🔵"


def _event_time(ev: BattleEvent) -> float:
    return ev.tick * TICK_SECONDS


def _classify_kill(attack_mode: str, weapon_id: str | None) -> str:
    if attack_mode == "crush":
        return "crush"
    if weapon_id in _MELEE_WEAPONS:
        return "melee"
    if weapon_id in _MISSILE_WEAPONS:
        return "ranged_missile"
    if weapon_id in _ENERGY_WEAPONS:
        return "ranged_energy"
    if weapon_id and any(weapon_id.startswith(p) for p in _ARTILLERY_PREFIXES):
        return "ranged_artillery"
    return "ranged_infantry"


def _pick_action_word(
    kill_count: int,
    rng: random.Random,
    attack_class: str = "ranged_infantry",
) -> str:
    words = ACTION_WORDS.get(attack_class, ACTION_WORDS["ranged_infantry"])
    if kill_count <= 1:
        return rng.choice(words["1"])
    if kill_count <= 3:
        return rng.choice(words["2-3"])
    return rng.choice(words["4+"])


@dataclass
class BroadcastSegment:
    text: str
    is_key_event: bool = False
    should_sleep: bool = True
    time_start: float = 0.0
    time_end: float = 0.0


class Broadcaster:
    """将事件流转换为播报文本序列。"""

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
        self._segments = []
        events = self.result.events
        self._emit_battle_start()
        if self.mode == MODE_DETAILED:
            self._emit_detailed_segments(events)
        self._emit_unit_wiped(events)
        return self._segments

    def _emit_battle_start(self) -> None:
        r = self.result
        if len(r.red_army) > 1:
            red_desc = " + ".join(
                f"{s.count}{_label_actor(s.actor_id)}" for s in r.red_army
            )
        elif r.red_army:
            red_desc = f"{r.red_count} {_label_actor(r.red_army[0].actor_id)}"
        else:
            red_desc = f"{r.red_count} 单位"

        if len(r.blue_army) > 1:
            blue_desc = " + ".join(
                f"{s.count}{_label_actor(s.actor_id)}" for s in r.blue_army
            )
        elif r.blue_army:
            blue_desc = f"{r.blue_count} {_label_actor(r.blue_army[0].actor_id)}"
        else:
            blue_desc = f"{r.blue_count} 单位"

        self._segments.append(BroadcastSegment(
            text=(
                f"⚔️ 战斗打响！"
                f"🔴 [{red_desc}] vs "
                f"🔵 [{blue_desc}]"
            ),
            is_key_event=True,
        ))

    def _emit_detailed_segments(self, events: list[BattleEvent]) -> None:
        self._emit_first_attack_mode(events)
        duration = self.result.duration
        if duration <= 0:
            return

        window_size = duration / DETAILED_WINDOW_COUNT
        red_remaining = self.result.red_count
        blue_remaining = self.result.blue_count

        for i in range(DETAILED_WINDOW_COUNT):
            w_start = i * window_size
            w_end = (i + 1) * window_size
            deaths = [
                e for e in events
                if w_start <= _event_time(e) < w_end
                and e.type == EventType.DEATH
            ]
            if not deaths:
                continue

            red_deaths = [d for d in deaths if d.payload["side"] == "red"]
            blue_deaths = [d for d in deaths if d.payload["side"] == "blue"]
            red_remaining -= len(red_deaths)
            blue_remaining -= len(blue_deaths)

            lines = [f"⏱ {w_start:.0f}-{w_end:.0f}s"]

            if red_deaths:
                p = red_deaths[0].payload
                killer_class = _classify_kill(
                    p.get("killer_attack_mode", "ranged"),
                    p.get("killer_weapon_id"),
                )
                action = _pick_action_word(len(red_deaths), self._rng, killer_class)
                killer_name = _label_actor(p["killer_name"])
                victim_name = _label_actor(red_deaths[0].payload["soldier_name"])
                lines.append(
                    f"🔵 {killer_name}{action} → "
                    f"🔴 {victim_name} -{len(red_deaths)}"
                )

            if blue_deaths:
                p = blue_deaths[0].payload
                killer_class = _classify_kill(
                    p.get("killer_attack_mode", "ranged"),
                    p.get("killer_weapon_id"),
                )
                action = _pick_action_word(len(blue_deaths), self._rng, killer_class)
                killer_name = _label_actor(p["killer_name"])
                victim_name = _label_actor(blue_deaths[0].payload["soldier_name"])
                lines.append(
                    f"🔴 {killer_name}{action} → "
                    f"🔵 {victim_name} -{len(blue_deaths)}"
                )

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
        seen_modes: set[str] = set()
        for e in events:
            if e.type == EventType.ATTACK:
                p = e.payload
                if p.get("is_splash"):
                    continue
                mode = p.get("mode", "ranged")
            elif e.type == EventType.CRUSH:
                mode = "crush"
                p = {
                    "attacker_side": self._crusher_side(e.payload["crusher_id"]),
                    "attacker_name": e.payload["crusher"],
                }
            else:
                continue

            if mode in seen_modes:
                continue
            seen_modes.add(mode)
            templates = FIRST_ATTACK_MODE_TEMPLATES.get(mode)
            if templates:
                t = _event_time(e)
                atk_emoji = _side_emoji(p.get("attacker_side", "red"))
                self._segments.append(BroadcastSegment(
                    text=self._rng.choice(templates).format(
                        time=t,
                        attacker_emoji=atk_emoji,
                        attacker_name=_label_actor(p.get("attacker_name", "")),
                    ),
                    is_key_event=True,
                    time_start=t,
                    time_end=t,
                ))
            if len(seen_modes) >= 3:
                break

    def _crusher_side(self, unit_id: int) -> str:
        for u in self.result.red_alive + self.result.red_dead:
            if u.id == unit_id:
                return u.side.value
        for u in self.result.blue_alive + self.result.blue_dead:
            if u.id == unit_id:
                return u.side.value
        return "red"

    def _emit_unit_wiped(self, events: list[BattleEvent]) -> None:
        unit_totals: dict[tuple[str, str], tuple[str, int]] = {}
        for slot in self.result.red_army:
            name = _label_actor(slot.actor_id)
            unit_totals[("red", slot.actor_id)] = (name, slot.count)
        for slot in self.result.blue_army:
            name = _label_actor(slot.actor_id)
            unit_totals[("blue", slot.actor_id)] = (name, slot.count)

        death_counts: dict[tuple[str, str], int] = {}
        death_times: dict[tuple[str, str], float] = {}
        for e in events:
            if e.type != EventType.DEATH:
                continue
            p = e.payload
            key = (p["side"], p["soldier_actor_id"])
            death_counts[key] = death_counts.get(key, 0) + 1
            death_times[key] = _event_time(e)

        wiped_events: list[tuple[float, str, str, int]] = []
        for (side, actor_id), (unit_name, total) in unit_totals.items():
            died = death_counts.get((side, actor_id), 0)
            if died >= total and total > 0:
                wiped_events.append((
                    death_times.get((side, actor_id), 0),
                    _side_emoji(side),
                    unit_name,
                    total,
                ))

        wiped_events.sort(key=lambda x: x[0])
        for time, emoji, unit_name, count in wiped_events:
            tpl = self._rng.choice(UNIT_WIPED_TEMPLATES)
            self._segments.append(BroadcastSegment(
                text=tpl.format(emoji=emoji, unit_name=unit_name, count=count),
                is_key_event=True,
                time_start=time,
                time_end=time,
            ))


def format_battle_report(result: BattleResult) -> str:
    """生成最终战报文本（对齐帝国斗蛐蛐）。"""
    lines = ["🏆 ━━━ 战斗结果 ━━━"]

    if result.winner is None:
        lines.append("结果：平局")
    elif result.winner == Side.RED:
        lines.append("胜方：🔴 红方（1号）")
    else:
        lines.append("胜方：🔵 蓝方（2号）")

    lines.append(f"战斗时长：{result.duration:.1f} 秒")
    lines.append("")

    red_all = result.red_alive + result.red_dead
    for slot in result.red_army:
        name = _label_actor(slot.actor_id)
        soldiers = [u for u in red_all if u.actor_id == slot.actor_id]
        alive = [u for u in result.red_alive if u.actor_id == slot.actor_id]
        kills = sum(u.kills for u in soldiers)
        dmg = sum(u.total_damage_dealt for u in soldiers)
        status = "全灭" if not alive else f"存活{len(alive)}"
        lines.append(
            f"🔴 {name} ×{slot.count} → {status}/击杀{kills}/伤害{dmg:.0f}"
        )
    lines.append("──────────")

    blue_all = result.blue_alive + result.blue_dead
    for slot in result.blue_army:
        name = _label_actor(slot.actor_id)
        soldiers = [u for u in blue_all if u.actor_id == slot.actor_id]
        alive = [u for u in result.blue_alive if u.actor_id == slot.actor_id]
        kills = sum(u.kills for u in soldiers)
        dmg = sum(u.total_damage_dealt for u in soldiers)
        status = "全灭" if not alive else f"存活{len(alive)}"
        lines.append(
            f"🔵 {name} ×{slot.count} → {status}/击杀{kills}/伤害{dmg:.0f}"
        )
    lines.append("")

    all_units = red_all + blue_all
    if result.winner is not None:
        mvp_candidates = [u for u in all_units if u.side == result.winner]
    else:
        mvp_candidates = []

    if mvp_candidates:
        mvp_candidates.sort(
            key=lambda u: u.total_damage_dealt * 0.5 + u.kills * 50,
            reverse=True,
        )
        mvp = mvp_candidates[0]
        mvp_score = mvp.total_damage_dealt * 0.5 + mvp.kills * 50
        lines.append(
            f"🎖 MVP：{_side_emoji(mvp.side.value)} "
            f"{_label_actor(mvp.actor_id)} #{mvp.id}"
        )
        lines.append(
            f"   伤害 {mvp.total_damage_dealt:.0f} / "
            f"击杀 {mvp.kills} / "
            f"综合分 {mvp_score:.1f}"
        )

    return "\n".join(lines)
