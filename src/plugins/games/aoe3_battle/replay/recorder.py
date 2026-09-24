"""Capture simulator frames and battle events into a replay."""

from __future__ import annotations

from typing import Any

from ..battle_contract import BattleResult
from .model import Replay, ReplayEvent, ReplayFrame


class ReplayRecorder:
    """Frame-callback adapter that keeps only public replay data."""

    def __init__(
        self,
        *,
        session_id: str,
        mode: str,
        match_label: str = "",
        red_label: str = "红方",
        blue_label: str = "蓝方",
        red_count: int = 0,
        blue_count: int = 0,
    ) -> None:
        self.session_id = session_id
        self.mode = mode
        self.match_label = match_label
        self.red_label = red_label
        self.blue_label = blue_label
        self.red_count = red_count
        self.blue_count = blue_count
        self.frames: list[ReplayFrame] = []
        self.events: list[ReplayEvent] = []
        self.result: dict[str, Any] = {}
        self._last_tick = -1

    def frame_callback(self, frame: dict[str, Any]) -> None:
        """Receive one frame from ``BattleSimulator2D``."""
        tick = int(frame.get("tick", 0))
        if tick <= self._last_tick:
            return
        self._last_tick = tick
        units = [
            {
                "id": unit.get("id"),
                "side": unit.get("side"),
                "unit_id": unit.get("unit_id"),
                "name": unit.get("name"),
                "x": unit.get("x", 0.0),
                "y": unit.get("y", 0.0),
                "hp": unit.get("hp", 0.0),
                "max_hp": unit.get("max_hp", 0.0),
                "stopped": bool(unit.get("stopped")),
                "target_id": unit.get("target_id"),
                "radius": (
                    unit.get("radius")
                    if unit.get("radius") is not None
                    else 0.45
                ),
            }
            for unit in frame.get("units") or []
        ]
        sides: dict[str, dict[str, Any]] = {}
        for side, data in (frame.get("sides") or {}).items():
            if not isinstance(data, dict):
                continue
            sides[side] = {
                "alive": data.get("alive", 0),
                "initial_count": data.get("initial_count", 0),
                "hp_ratio": data.get("hp_ratio", 0.0),
                "composition": list(data.get("composition") or []),
            }
        self.frames.append(
            ReplayFrame(
                tick=tick,
                time=float(frame.get("time", 0.0)),
                units=units,
                sides=sides,
                summary={},
                field=dict(frame.get("field") or {}),
                status=str(frame.get("status") or "running"),
                winner=frame.get("winner"),
            )
        )

    def capture_result(self, result: BattleResult) -> None:
        """Attach the final result after the simulator finishes."""
        self.events = []
        last_attack_position: dict[int, tuple[float, float, float, float]] = {}
        unit_positions: dict[int, tuple[float, float]] = {}
        previous_unit_positions: dict[int, tuple[float, float]] = {}
        frame_index = 0
        for event in result.events:
            position = None
            event_type = event.event_type.value
            while (
                frame_index + 1 < len(self.frames)
                and self.frames[frame_index + 1].time <= event.time
            ):
                previous_unit_positions = {
                    int(unit["id"]): (
                        float(unit.get("x", 0.0)),
                        float(unit.get("y", 0.0)),
                    )
                    for unit in self.frames[frame_index].units
                    if unit.get("id") is not None
                }
                frame_index += 1
            event_frame = self.frames[frame_index] if self.frames else None
            if event_frame is not None:
                for unit in event_frame.units:
                    unit_id = unit.get("id")
                    if unit_id is not None:
                        unit_positions[int(unit_id)] = (
                            float(unit.get("x", 0.0)),
                            float(unit.get("y", 0.0)),
                        )
            position_target_id = (
                event.data.get("target_id")
                if event_type == "ATTACK"
                else event.data.get("main_target_id")
                if event_type == "AOE_SPLASH"
                else None
            )
            if position_target_id is not None:
                frame = self.frames[frame_index] if self.frames else None
                target = next(
                    (
                        unit
                        for unit in (frame.units if frame is not None else [])
                        if int(unit.get("id", -1)) == int(position_target_id)
                    ),
                    None,
                )
                if target is not None:
                    position = (
                        float(target.get("x", 0.0)),
                        float(target.get("y", 0.0)),
                    )
            if event_type == "ATTACK":
                attacker_id = event.data.get("attacker_id")
                target_id = event.data.get("target_id")
                if target_id is not None:
                    attacker_position = None
                    if attacker_id is not None:
                        attacker_position = unit_positions.get(int(attacker_id))
                        if attacker_position is None:
                            attacker = next(
                                (
                                    unit
                                    for unit in (
                                        event_frame.units
                                        if event_frame is not None
                                        else []
                                    )
                                    if int(unit.get("id", -1)) == int(attacker_id)
                                ),
                                None,
                            )
                            if attacker is not None:
                                attacker_position = (
                                    float(attacker.get("x", 0.0)),
                                    float(attacker.get("y", 0.0)),
                                )
                    target_position = (
                        unit_positions.get(int(target_id))
                        or previous_unit_positions.get(int(target_id))
                        or position
                        or attacker_position
                    )
                    if attacker_position is None and target_position is not None:
                        attacker_position = target_position
                    if attacker_position is not None and target_position is not None:
                        position = target_position
                        last_attack_position[int(target_id)] = (
                            attacker_position[0],
                            attacker_position[1],
                            target_position[0],
                            target_position[1],
                        )
            if (
                position is None
                and event_type == "AOE_SPLASH"
                and event.data.get("impact_x") is not None
                and event.data.get("impact_y") is not None
            ):
                position = (
                    float(event.data["impact_x"]),
                    float(event.data["impact_y"]),
                )
            elif event_type == "DEATH":
                soldier_id = event.data.get("soldier_id")
                if soldier_id is not None:
                    attack_position = last_attack_position.get(int(soldier_id))
                    if attack_position is not None:
                        position = (attack_position[2], attack_position[3])
                        event.data["visual_attacker_x"] = attack_position[0]
                        event.data["visual_attacker_y"] = attack_position[1]
                        event.data["visual_target_x"] = attack_position[2]
                        event.data["visual_target_y"] = attack_position[3]
            if (
                event_type in {"ATTACK", "AOE_SPLASH"}
                and position is not None
                and event.data.get("visual_target_x") is None
            ):
                event.data["visual_target_x"] = position[0]
                event.data["visual_target_y"] = position[1]
            self.events.append(
                ReplayEvent(
                    tick=event.tick,
                    time=event.time,
                    event_type=event_type,
                    data=dict(event.data),
                    x=position[0] if position else None,
                    y=position[1] if position else None,
                )
            )
        red_all = result.red_alive + result.red_dead
        blue_all = result.blue_alive + result.blue_dead
        self.result = {
            "winner": result.winner.value if result.winner else None,
            "duration": result.duration,
            "ticks": result.ticks,
            "timeout": result.timeout,
            "red_alive": len(result.red_alive),
            "blue_alive": len(result.blue_alive),
            "red_dead": len(result.red_dead),
            "blue_dead": len(result.blue_dead),
            "red_damage": round(
                sum(soldier.total_damage_dealt for soldier in red_all),
                1,
            ),
            "red_raw_damage": round(
                sum(soldier.raw_damage_dealt for soldier in red_all),
                1,
            ),
            "red_overkill_damage": round(
                sum(soldier.overkill_damage for soldier in red_all),
                1,
            ),
            "blue_damage": round(
                sum(soldier.total_damage_dealt for soldier in blue_all),
                1,
            ),
            "blue_raw_damage": round(
                sum(soldier.raw_damage_dealt for soldier in blue_all),
                1,
            ),
            "blue_overkill_damage": round(
                sum(soldier.overkill_damage for soldier in blue_all),
                1,
            ),
            "red_kills": sum(soldier.kills for soldier in red_all),
            "blue_kills": sum(soldier.kills for soldier in blue_all),
            "red_loss": sum(
                sum(soldier.unit.cost.values())
                for soldier in result.red_dead
            ),
            "blue_loss": sum(
                sum(soldier.unit.cost.values())
                for soldier in result.blue_dead
            ),
            "unit_losses": {
                "red": _unit_losses(result.red_dead),
                "blue": _unit_losses(result.blue_dead),
            },
            "mvp": _mvp(result.red_alive + result.blue_alive),
        }

    def build(self) -> Replay:
        """Return an immutable-by-convention replay payload."""
        return Replay(
            session_id=self.session_id,
            mode=self.mode,
            match_label=self.match_label,
            red_label=self.red_label,
            blue_label=self.blue_label,
            red_count=self.red_count,
            blue_count=self.blue_count,
            frames=self.frames,
            events=self.events,
            result=self.result,
        )


def _unit_losses(soldiers: list[Any]) -> list[dict[str, Any]]:
    """Aggregate dead soldiers by unit id for the replay outro."""
    counts: dict[str, dict[str, Any]] = {}
    for soldier in soldiers:
        unit = soldier.unit
        item = counts.setdefault(
            unit.id,
            {
                "unit_id": unit.id,
                "name": unit.name or unit.name_en,
                "count": 0,
            },
        )
        item["count"] += 1
    return sorted(counts.values(), key=lambda item: item["unit_id"])


def _mvp(soldiers: list[Any]) -> dict[str, Any] | None:
    """Return the highest combined damage/kill contribution."""
    if not soldiers:
        return None
    soldier = max(
        soldiers,
        key=lambda item: item.total_damage_dealt * 0.5 + item.kills * 50,
    )
    return {
        "name": soldier.unit.name or soldier.unit.name_en,
        "side": soldier.side.value,
        "damage": round(soldier.total_damage_dealt, 1),
        "raw_damage": round(soldier.raw_damage_dealt, 1),
        "overkill_damage": round(soldier.overkill_damage, 1),
        "kills": soldier.kills,
    }


class ReplaySession:
    """One battle's recorder plus convenience callback.

    The context manager keeps the integration point small at simulator
    construction and guarantees the final result is attached.
    """

    def __init__(
        self,
        *,
        session_id: str,
        mode: str,
        match_label: str = "",
        red_label: str = "红方",
        blue_label: str = "蓝方",
        red_count: int = 0,
        blue_count: int = 0,
    ) -> None:
        self.recorder = ReplayRecorder(
            session_id=session_id,
            mode=mode,
            match_label=match_label,
            red_label=red_label,
            blue_label=blue_label,
            red_count=red_count,
            blue_count=blue_count,
        )

    @property
    def frame_callback(self):
        return self.recorder.frame_callback

    def finish(self, result: BattleResult) -> Replay:
        self.recorder.capture_result(result)
        return self.recorder.build()
