"""静夜标记 · 角色处理器。

逐条转写自源项目 ``server/game/roles/*``。每个角色是 ``BaseRole`` 的子类，
提供四类能力：

- ``perform_night_action``：写入 ``state["night_actions"]``，返回是否被受理；
- ``get_available_targets``：本夜合法目标（服务端是唯一权威，客户端/CLI 只是展示）；
- ``on_death``：死亡时是否需要进入触发链（猎人开枪 / 白狼王带人）；
- ``on_exile``：被放逐时是否阻断出局（白痴免疫）。

**目标合法性由两层共同保证**（与源项目分工一致，不要混为一谈）：

1. 调用方（状态机）用 ``get_available_targets`` 构造合法目标集合，
   在写入前拦截「不在集合内」的目标——源项目的 ``GameManager.validateAction``
   就是拿这个集合做校验的；
2. ``perform_night_action`` 自身只校验**角色能力层面**的约束
   （药水是否已用过、是否连续两晚守同一人、守墓人是否选到活人等），
   不重复做目标集合校验。

因此直接调用 ``perform_night_action`` 传入一个非法目标时，某些角色**不会**报错
（例如狼人可以记一票队友）——这是刻意保持与源项目一致的行为。
"""

from __future__ import annotations

import random
from typing import Any, ClassVar

# 常量模块用短别名 C：本文件高频引用，长名会明显拖长行
from . import constants as C  # noqa: N812
from .types import GameStateDict, PlayerDict


class BaseRole:
    """所有角色的接口。默认实现均为「无能力」，未知角色降级为平民。"""

    role: ClassVar[str] = ""
    faction: ClassVar[str] = C.GOOD
    has_night_action: ClassVar[bool] = False

    def perform_night_action(
        self,
        state: GameStateDict,
        player: PlayerDict,
        *,
        target: str | None = None,
        potion: str | None = None,
    ) -> bool:
        """执行夜晚行动。返回 True 表示已被受理（写入状态）。"""
        return False

    def get_available_targets(self, state: GameStateDict, player: PlayerDict) -> list[str]:
        """本夜可选目标（pid 列表）。"""
        return []

    def on_death(
        self, state: GameStateDict, player: PlayerDict, cause: str
    ) -> dict[str, Any] | None:
        """死亡触发。返回 ``{"type": ..., "pid": ...}`` 或 None。"""
        return None

    def on_exile(self, state: GameStateDict, player: PlayerDict) -> bool:
        """被放逐时的特殊处理。返回 True 表示阻断出局（白痴免疫）。"""
        return False


# =====================================================================
# 狼人 / 白狼王
# =====================================================================
class Werewolf(BaseRole):
    """狼人。所有存活狼人各投一票，全部投完才定目标；平票随机。

    可自刀（合法策略），但合法目标里**排除狼队友**。
    """

    role: ClassVar[str] = C.WEREWOLF
    faction: ClassVar[str] = C.EVIL
    has_night_action: ClassVar[bool] = True

    def perform_night_action(
        self,
        state: GameStateDict,
        player: PlayerDict,
        *,
        target: str | None = None,
        potion: str | None = None,
    ) -> bool:
        if not target:
            return False

        night = state["night_actions"]
        wolves_action = night.get("wolves")
        if wolves_action is None:
            wolves_action = {"target": None, "votes": {}}
            night["wolves"] = wolves_action
        votes = wolves_action.setdefault("votes", {})
        votes[player["pid"]] = target

        alive_wolves = [
            p for p in state["players"] if p["alive"] and p["role"] in C.WOLF_ROLES
        ]
        if all(wolf["pid"] in votes for wolf in alive_wolves):
            wolves_action["target"] = _tally_wolf_votes(votes)
        return True

    def get_available_targets(self, state: GameStateDict, player: PlayerDict) -> list[str]:
        teammates = {
            p["pid"]
            for p in state["players"]
            if p["alive"] and p["faction"] == C.EVIL and p["pid"] != player["pid"]
        }
        return [
            p["pid"]
            for p in state["players"]
            if p["alive"] and p["pid"] not in teammates
        ]


def _tally_wolf_votes(votes: dict[str, str]) -> str | None:
    """统计狼人票数。票数最高者为目标，平票随机选一个。"""
    counts: dict[str, int] = {}
    for target in votes.values():
        counts[target] = counts.get(target, 0) + 1

    best: list[str] = []
    max_votes = 0
    for target, count in counts.items():
        if count > max_votes:
            max_votes = count
            best = [target]
        elif count == max_votes:
            best.append(target)
    return random.choice(best) if best else None


class WolfKing(Werewolf):
    """白狼王。夜晚行动同狼人；额外能力：**仅被放逐时**可带走一名存活玩家。

    被女巫毒死、被骑士决斗杀死均不能带人（源项目 ``onDeath`` 只认 ``exiled``）。
    """

    role: ClassVar[str] = C.WOLF_KING

    def on_death(
        self, state: GameStateDict, player: PlayerDict, cause: str
    ) -> dict[str, Any] | None:
        if cause == C.DEATH_EXILED:
            return {"type": "wolf_king_drag", "pid": player["pid"]}
        return None


# =====================================================================
# 预言家 / 守墓人（查验类，共用专属理由【查验结论】）
# =====================================================================
class Seer(BaseRole):
    role: ClassVar[str] = C.SEER
    has_night_action: ClassVar[bool] = True

    def perform_night_action(
        self,
        state: GameStateDict,
        player: PlayerDict,
        *,
        target: str | None = None,
        potion: str | None = None,
    ) -> bool:
        if not target:
            return False
        state["night_actions"]["seer"] = {"target": target}
        return True

    def get_available_targets(self, state: GameStateDict, player: PlayerDict) -> list[str]:
        return [
            p["pid"]
            for p in state["players"]
            if p["alive"] and p["pid"] != player["pid"]
        ]


class Gravedigger(BaseRole):
    """守墓人。只能查验**已死亡**玩家；当夜无死者时自动跳过，有死者则必须选。"""

    role: ClassVar[str] = C.GRAVEDIGGER
    has_night_action: ClassVar[bool] = True

    def perform_night_action(
        self,
        state: GameStateDict,
        player: PlayerDict,
        *,
        target: str | None = None,
        potion: str | None = None,
    ) -> bool:
        if not target:
            has_dead = any(not p["alive"] for p in state["players"])
            if has_dead:
                return False
            state["night_actions"]["gravedigger"] = {"target": None}
            return True

        found = next((p for p in state["players"] if p["pid"] == target), None)
        if found is None or found["alive"]:
            return False
        state["night_actions"]["gravedigger"] = {"target": target}
        return True

    def get_available_targets(self, state: GameStateDict, player: PlayerDict) -> list[str]:
        return [p["pid"] for p in state["players"] if not p["alive"]]


# =====================================================================
# 女巫
# =====================================================================
class Witch(BaseRole):
    """女巫。解药/毒药各一瓶，全局各限一次。

    - 拿到"今夜被刀者"这一私有信息后才行动；
    - **首夜可自救，非首夜不可自救**；
    - 同一晚不可能双药（一次行动只写入一个 potion）。
    """

    role: ClassVar[str] = C.WITCH
    has_night_action: ClassVar[bool] = True

    def perform_night_action(
        self,
        state: GameStateDict,
        player: PlayerDict,
        *,
        target: str | None = None,
        potion: str | None = None,
    ) -> bool:
        role_state = player["role_state"]

        if potion == "antidote":
            if role_state.get("antidote_used"):
                return False
            wolves = state["night_actions"].get("wolves")
            victim = wolves.get("target") if wolves else None
            if victim == player["pid"] and state["round"] > 1:
                return False
            role_state["antidote_used"] = True
            state["night_actions"]["witch"] = {"action": "antidote", "target": victim}
        elif potion == "poison":
            if role_state.get("poison_used"):
                return False
            if not target:
                return False
            role_state["poison_used"] = True
            state["night_actions"]["witch"] = {"action": "poison", "target": target}
        else:
            state["night_actions"]["witch"] = {"action": "none", "target": None}
        return True

    def get_available_targets(self, state: GameStateDict, player: PlayerDict) -> list[str]:
        """毒药目标：所有存活的其他玩家（解药目标是系统给定的被刀者，不走此列表）。"""
        return [
            p["pid"]
            for p in state["players"]
            if p["alive"] and p["pid"] != player["pid"]
        ]


# =====================================================================
# 守卫
# =====================================================================
class Guard(BaseRole):
    """守卫。可守自己，但**不可连续两晚守同一人**。"""

    role: ClassVar[str] = C.GUARD
    has_night_action: ClassVar[bool] = True

    def perform_night_action(
        self,
        state: GameStateDict,
        player: PlayerDict,
        *,
        target: str | None = None,
        potion: str | None = None,
    ) -> bool:
        if not target:
            return False
        role_state = player["role_state"]
        if role_state.get("last_guard_target") == target:
            return False
        role_state["last_guard_target"] = target
        state["night_actions"]["guard"] = {"target": target}
        return True

    def get_available_targets(self, state: GameStateDict, player: PlayerDict) -> list[str]:
        last = player["role_state"].get("last_guard_target")
        return [
            p["pid"]
            for p in state["players"]
            if p["alive"] and p["pid"] != last
        ]


# =====================================================================
# 猎人 / 白痴 / 骑士（无夜晚行动）
# =====================================================================
class Hunter(BaseRole):
    """猎人。被放逐/被刀/被决斗/被带走都能开枪，**被女巫毒死不能开枪**。"""

    role: ClassVar[str] = C.HUNTER

    def on_death(
        self, state: GameStateDict, player: PlayerDict, cause: str
    ) -> dict[str, Any] | None:
        role_state = player["role_state"]
        if not role_state.get("can_shoot"):
            return None
        if cause == C.DEATH_POISONED:
            # 被毒死：永久失去开枪能力（源项目在此处就地把 canShoot 置 false）
            role_state["can_shoot"] = False
            return None
        return {"type": "hunter_shoot", "pid": player["pid"]}


class Fool(BaseRole):
    """白痴。被放逐时免疫一次，之后**失去投票权但仍可放置标记**。"""

    role: ClassVar[str] = C.FOOL

    def on_exile(self, state: GameStateDict, player: PlayerDict) -> bool:
        role_state = player["role_state"]
        if not role_state.get("immunity_used"):
            role_state["immunity_used"] = True
            return True
        return False


class Knight(BaseRole):
    """骑士。无夜晚行动；白天可发动一次决斗（流程在状态机里，不在本类）。"""

    role: ClassVar[str] = C.KNIGHT


class Villager(BaseRole):
    """平民。无任何特殊能力。"""

    role: ClassVar[str] = C.VILLAGER


# =====================================================================
# 工厂
# =====================================================================
_ROLE_CLASSES: dict[str, type[BaseRole]] = {
    C.WEREWOLF: Werewolf,
    C.WOLF_KING: WolfKing,
    C.SEER: Seer,
    C.WITCH: Witch,
    C.GUARD: Guard,
    C.HUNTER: Hunter,
    C.GRAVEDIGGER: Gravedigger,
    C.FOOL: Fool,
    C.KNIGHT: Knight,
    C.VILLAGER: Villager,
}


def create_role(role: str) -> BaseRole:
    """按角色 key 造处理器。未实现的角色降级为平民（源项目同样处理）。"""
    return _ROLE_CLASSES.get(role, Villager)()


def new_role_state(role: str) -> dict[str, Any]:
    """角色的初始资源状态（源项目 ``GameManager.initRoleState``）。"""
    if role == C.WITCH:
        return {"antidote_used": False, "poison_used": False}
    if role == C.GUARD:
        return {"last_guard_target": None}
    if role == C.FOOL:
        return {"immunity_used": False}
    if role == C.KNIGHT:
        return {"duel_used": False}
    if role == C.HUNTER:
        return {"can_shoot": True}
    return {}


def has_voting_right(player: PlayerDict) -> bool:
    """该玩家当前是否有投票权。

    白痴被放逐免疫后失去投票权（但**仍可放置标记**，因此不参与标记顺序的排除）。
    """
    if player["role"] == C.FOOL and player["role_state"].get("immunity_used"):
        return False
    return True
