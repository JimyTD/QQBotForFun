"""静夜标记 · 状态形状定义与构造函数。

状态是**普通 dict**（不是 dataclass），原因有三：

1. 它要能直接塞进 ``GameContext.state`` 并 JSON 往返；
2. 源项目的 ``GameState`` 本身就是结构化对象（TS interface），dict 是最近似映射；
3. CLI 适配器可以手工造出同构 dict 喂给规则函数（深海任务就是这么做的）。

本模块只放**形状**（TypedDict，供阅读与类型检查）与**构造函数**，
不放业务规则（业务规则在 ``resolve`` / ``roles`` / ``fallback`` / ``private_info``）。

字段命名：相对源项目统一 camelCase → snake_case，例如
``nightActions`` → ``night_actions``、``nightCurrentRole`` → ``night_current_role``、
``roleState.antidoteUsed`` → ``role_state.antidote_used``。

玩家标识：``pid: str``（语义等价源项目 ``userId: string``）。
本内核**永不接触 QQ 号**；``ctx.state["seat_owners"]``（pid → qq_id）由游戏本体维护。
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

# 常量模块用短别名 C：本文件高频引用，长名会明显拖长行
from . import constants as C  # noqa: N812


# =====================================================================
# 物品
# =====================================================================
class ItemDict(TypedDict):
    """随身物品。存活时 only 类型可见；死亡后 ``revealed=True`` 成为遗物。"""

    type: str  # MOONSTONE | BALANCE | HOUND_WHISTLE
    value: int | str  # 月光石/猎犬哨是数字，天平徽章是 balanced/unbalanced
    revealed: bool


# =====================================================================
# 玩家
# =====================================================================
class PlayerDict(TypedDict):
    pid: str
    nickname: str
    seat: int
    role: str
    faction: str  # GOOD | EVIL
    alive: bool
    items: list[ItemDict]
    role_state: dict[str, Any]  # 见 roles.new_role_state()


# =====================================================================
# 夜晚行动
# =====================================================================
class WolfNightAction(TypedDict):
    target: NotRequired[str | None]
    votes: NotRequired[dict[str, str]]  # pid → 目标 pid


class WitchNightAction(TypedDict):
    action: str  # none | antidote | poison
    target: NotRequired[str | None]


class TargetNightAction(TypedDict):
    target: str | None


class NightActionsDict(TypedDict):
    guard: NotRequired[TargetNightAction | None]
    wolves: NotRequired[WolfNightAction | None]
    witch: NotRequired[WitchNightAction | None]
    seer: NotRequired[TargetNightAction | None]
    gravedigger: NotRequired[TargetNightAction | None]


# =====================================================================
# 标记 / 投票 / 死亡
# =====================================================================
class IdentityMarkDict(TypedDict):
    identity: str  # 中文身份标签
    reason: str  # 理由 key


class EvaluationMarkDict(TypedDict):
    target: str  # pid
    identity: str
    reason: str


class PlayerMarksDict(TypedDict):
    player: str  # pid
    round: int
    identity_mark: IdentityMarkDict
    evaluation_marks: list[EvaluationMarkDict]


class VoteRecordDict(TypedDict):
    voter: str  # pid
    target: str  # pid


class DeathRecordDict(TypedDict):
    pid: str
    seat: int
    cause: str
    round: int
    relics: list[ItemDict]


class PendingTriggerDict(TypedDict):
    """死亡触发链的一项。

    ``type`` **只会是** ``hunter_shoot``（猎人开枪）或 ``wolf_king_drag``（白狼王带人）
    —— 这是 ``roles`` 里唯一两个会由 ``on_death`` 入队的事件。

    说明（避免后来人误以为还有两种）：
    - 源项目的类型联合里还写了 ``fool_immunity`` / ``knight_duel``，但它们**从未入队**：
      白痴免疫走 ``on_exile`` 回调、骑士决斗走独立的 ``day_knight`` 阶段，
      两者都不经过本队列。本移植版**不保留这两个不可达分支**（只在注释里说明缘由，
      不写死代码）。
    - 源项目还带一个固定 60 秒的 ``timeout`` 字段；QQ 侧的等待时长由游戏本体按通道
      决定（私聊 ask 的 timeout），因此不放入状态。
    """

    type: str  # 仅 hunter_shoot | wolf_king_drag
    pid: str


# =====================================================================
# 完整对局状态
# =====================================================================
class HistoryDict(TypedDict):
    rounds: list[NightActionsDict]  # 已结算的夜晚，索引 i 对应第 i+1 轮
    marks: list[PlayerMarksDict]
    votes: list[list[VoteRecordDict]]
    deaths: list[DeathRecordDict]


class GameStateDict(TypedDict):
    status: str  # playing | finished
    round: int
    phase: str
    players: list[PlayerDict]
    night_actions: NightActionsDict
    night_current_role: str | None
    marking_order: list[str]  # pid 列表，按座位排序
    marking_current: int
    pending_triggers: list[PendingTriggerDict]
    history: HistoryDict
    winner: str | None  # GOOD | EVIL
    #: 终局原因码（`resolve.check_win_condition` 返回的 reason，供结算文案使用）
    end_reason_code: NotRequired[str | None]
    # ---- 由游戏本体维护（规则内核不读写）----
    win_condition: NotRequired[str]  # edge | city
    seat_owners: NotRequired[dict[str, int]]  # pid → qq_id（AI 座位无此项）
    settings: NotRequired[dict[str, Any]]
    panel_message_id: NotRequired[int | None]
    private_message_ids: NotRequired[dict[str, int]]


# =====================================================================
# 构造函数
# =====================================================================
def empty_night_actions() -> NightActionsDict:
    """一轮夜晚的空白行动表（对应源项目 ``createEmptyNightActions``）。"""
    return {
        "guard": None,
        "wolves": None,
        "witch": None,
        "seer": None,
        "gravedigger": None,
    }


def empty_history() -> HistoryDict:
    return {"rounds": [], "marks": [], "votes": [], "deaths": []}


def empty_state(players: list[PlayerDict], *, win_condition: str = C.WIN_EDGE) -> GameStateDict:
    """造一个刚开局、处于第 1 轮夜晚的空白状态。

    仅供测试与 CLI 适配器使用；真实开局由 ``game.py``（M1）负责分配身份/座位/物品。
    """
    return {
        "status": "playing",
        "round": 1,
        "phase": C.PHASE_NIGHT,
        "players": players,
        "night_actions": empty_night_actions(),
        "night_current_role": None,
        "marking_order": [],
        "marking_current": 0,
        "pending_triggers": [],
        "history": empty_history(),
        "winner": None,
        "win_condition": win_condition,
    }


def find_player(state: GameStateDict, pid: str | None) -> PlayerDict | None:
    """按 pid 找玩家。``pid`` 为 None/空时返回 None（源项目的常见写法）。"""
    if not pid:
        return None
    for player in state["players"]:
        if player["pid"] == pid:
            return player
    return None


def alive_players(state: GameStateDict) -> list[PlayerDict]:
    return [p for p in state["players"] if p["alive"]]
