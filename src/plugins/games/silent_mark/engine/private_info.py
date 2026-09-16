"""静夜标记 · 信息防火墙（私有信息裁剪）。

逐条转写自源项目 ``shared/privateInfo.ts``。

本模块是**玩家私有信息的唯一出口**：

- 游戏本体下发给真人玩家（开局 / 阶段切换 / 主动查询）；
- AI 上下文构建器（M4）**复用同一份推导**，避免"真人看到的"和"AI 看到的"漂移。

因此这里新增任何字段都必须同时考虑：它会不会让 AI 拿到不该拿的信息？
**绝不包含他人的私有信息。**
"""

from __future__ import annotations

from typing import Any

# 常量模块用短别名 C：本文件高频引用，长名会明显拖长行
from . import constants as C  # noqa: N812
from .types import GameStateDict, PlayerDict


def build_my_private_info(state: GameStateDict, player: PlayerDict) -> dict[str, Any]:
    """构建"我的私有信息"。返回普通 dict（无私有信息时为空 dict）。

    1. 只输出该玩家**自己有权看到**的内容；
    2. 已结算的夜晚来自 ``history.rounds``（索引 i 对应第 i+1 轮）；
    3. 若当前正处于**夜晚进行中**，把本夜尚未结算的行动也一并计入，
       保证玩家刚做出的操作立刻可见。
    """
    info: dict[str, Any] = {}
    rounds = _visible_rounds(state)

    def faction_of(pid: str | None) -> str | None:
        if not pid:
            return None
        for p in state["players"]:
            if p["pid"] == pid:
                return p["faction"]
        return None

    role = player["role"]
    role_state = player["role_state"]

    if role in (C.SEER, C.GRAVEDIGGER):
        kind = "seer" if role == C.SEER else "gravedigger"
        investigations: list[dict[str, Any]] = []
        for entry in rounds:
            slot = entry["actions"].get(kind)
            target = slot.get("target") if slot else None
            if not target:
                continue
            faction = faction_of(target)
            if not faction:
                continue
            investigations.append(
                {
                    "round": entry["round"],
                    "kind": kind,
                    "target": target,
                    "faction": faction,
                }
            )
        info["investigations"] = investigations

    elif role == C.WITCH:
        potion_history: list[dict[str, Any]] = []
        for entry in rounds:
            slot = entry["actions"].get("witch")
            if not slot or slot.get("action") == "none":
                continue
            potion_history.append(
                {
                    "round": entry["round"],
                    "potion": slot["action"],
                    "target": slot.get("target"),
                }
            )
        info["witch"] = {
            "antidote_used": bool(role_state.get("antidote_used")),
            "poison_used": bool(role_state.get("poison_used")),
            "potion_history": potion_history,
        }

    elif role == C.GUARD:
        history: list[dict[str, Any]] = []
        for entry in rounds:
            slot = entry["actions"].get("guard")
            target = slot.get("target") if slot else None
            if not target:
                continue
            history.append({"round": entry["round"], "target": target})
        info["guard"] = {
            "last_guard_target": role_state.get("last_guard_target"),
            "history": history,
        }

    elif role in C.WOLF_ROLES:
        wolf_attacks: list[dict[str, Any]] = []
        for entry in rounds:
            slot = entry["actions"].get("wolves")
            target = slot.get("target") if slot else None
            if not target:
                continue
            wolf_attacks.append({"round": entry["round"], "target": target})
        info["wolf_attacks"] = wolf_attacks

    elif role == C.HUNTER:
        info["hunter_can_shoot"] = bool(role_state.get("can_shoot"))

    elif role == C.KNIGHT:
        info["knight_duel_used"] = bool(role_state.get("duel_used"))

    elif role == C.FOOL:
        info["fool_immunity_used"] = bool(role_state.get("immunity_used"))

    return info


def _visible_rounds(state: GameStateDict) -> list[dict[str, Any]]:
    """可见的夜晚列表：已结算的 + （若正处夜晚）进行中的那一夜。"""
    rounds: list[dict[str, Any]] = [
        {"round": i + 1, "actions": actions}
        for i, actions in enumerate(state["history"]["rounds"])
    ]
    if (
        state["phase"] == C.PHASE_NIGHT
        and len(state["history"]["rounds"]) < state["round"]
    ):
        rounds.append({"round": state["round"], "actions": state["night_actions"]})
    return rounds
