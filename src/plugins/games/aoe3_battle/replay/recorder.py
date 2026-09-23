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
        last_attack_target: dict[int, tuple[float, float]] = {}
        frame_index = 0
        for event in result.events:
            position = None
            event_type = event.event_type.value
            position_target_id = (
                event.data.get("target_id")
                if event_type == "ATTACK"
                else event.data.get("main_target_id")
                if event_type == "AOE_SPLASH"
                else None
            )
            if position_target_id is not None:
                while (
                    frame_index + 1 < len(self.frames)
                    and self.frames[frame_index + 1].time <= event.time
                ):
                    frame_index += 1
                frame = self.frames[frame_index]
                target = next(
                    (
                        unit
                        for unit in frame.units
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
                        last_attack_target[int(position_target_id)] = position
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
                    position = last_attack_target.get(int(soldier_id))
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
        self.result = {
            "winner": result.winner.value if result.winner else None,
            "duration": result.duration,
            "ticks": result.ticks,
            "timeout": result.timeout,
            "red_alive": len(result.red_alive),
            "blue_alive": len(result.blue_alive),
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
