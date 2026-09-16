"""M5：复盘渲染 + 报名房间超时清理。

复盘里最要紧的是**信息防火墙**：对局进行中，复盘只能用公开口径的死因 ——
一句"被毒死"就等于把女巫当晚的用药摊在群里。只有终局之后才允许写真实死因。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import nonebot

# `commands` 里是模块级 `on_command(...)`：必须先初始化 NoneBot 才能导入
# （与 `test_rooms.py` 同做法）
nonebot.init()

from core import session  # noqa: E402
from src.plugins.games.silent_mark import commands, views  # noqa: E402
from src.plugins.games.silent_mark.engine import constants as C  # noqa: E402


def _player(pid: str, seat: int, role: str, faction: str, *, alive: bool = True) -> dict:
    return {
        "pid": pid,
        "nickname": f"P{seat}",
        "seat": seat,
        "role": role,
        "faction": faction,
        "alive": alive,
        "items": [],
        "role_state": {},
    }


PLAYERS = [
    _player("1", 1, C.WEREWOLF, C.EVIL),
    _player("2", 2, C.SEER, C.GOOD),
    _player("3", 3, C.WITCH, C.GOOD, alive=False),
    _player("4", 4, C.VILLAGER, C.GOOD, alive=False),
]

SETTINGS = {
    "mode": "preset",
    "preset": "4standard",
    "roles": {C.WEREWOLF: 1, C.SEER: 1, C.WITCH: 1, C.VILLAGER: 1},
    "items": {"enabled": True, "pool": list(C.BASIC_ITEM_POOL)},
}


def _state(*, winner: str | None) -> dict:
    return {
        "status": "finished" if winner else "playing",
        "round": 2,
        "phase": C.PHASE_GAME_OVER if winner else C.PHASE_DAY_MARKING,
        "players": PLAYERS,
        "night_actions": {
            "guard": None,
            "wolves": None,
            "witch": None,
            "seer": None,
            "gravedigger": None,
        },
        "marking_order": [],
        "marking_current": 0,
        "pending_triggers": [],
        "history": {
            "rounds": [],
            "marks": [
                {
                    "player": "1",
                    "round": 1,
                    "identity_mark": {"identity": "平民", "reason": C.REASON_INTUITION},
                    "evaluation_marks": [
                        {
                            "target": "2",
                            "identity": C.IDENTITY_WOLF,
                            "reason": C.REASON_MARK_ANALYSIS,
                        }
                    ],
                }
            ],
            "votes": [[{"voter": "1", "target": "2"}, {"voter": "2", "target": "1"}]],
            "deaths": [
                {
                    "pid": "3",
                    "seat": 3,
                    "cause": C.DEATH_POISONED,  # 夜间：复盘进行中不能写"被毒死"
                    "round": 1,
                    "relics": [
                        {"type": C.MOONSTONE, "value": 1, "revealed": True},
                    ],
                },
                {
                    "pid": "4",
                    "seat": 4,
                    "cause": C.DEATH_EXILED,  # 白天公开事件，照写
                    "round": 2,
                    "relics": [],
                },
            ],
        },
        "winner": winner,
        "end_reason_code": "wolves_eliminated" if winner else None,
    }


def test_replay_has_one_page_per_round_plus_overview() -> None:
    pages = views.render_replay(_state(winner=None), SETTINGS, reveal_all=False)

    assert len(pages) == 3  # 概览 + 第 1 轮 + 第 2 轮
    assert "静夜标记 · 复盘" in pages[0]
    assert "4人标准" in pages[0] or "4 人标准" in pages[0]
    assert "第 1 轮" in pages[1]
    assert "第 2 轮" in pages[2]


def test_replay_keeps_night_cause_secret_while_the_game_is_running() -> None:
    pages = views.render_replay(_state(winner=None), SETTINGS, reveal_all=False)
    body = "\n".join(pages)

    assert "被狼人袭击" in body
    assert "被毒死" not in body, "进行中的复盘泄露了女巫的用药"
    # 白天事件（放逐）本来就公开，照写
    assert "被放逐" in body
    # 遗物是公开的
    assert "月光石" in body


def test_replay_reveals_real_causes_and_roles_after_the_game() -> None:
    pages = views.render_replay(_state(winner=C.GOOD), SETTINGS, reveal_all=True)
    body = "\n".join(pages)

    assert "被毒死" in body
    assert "好人阵营胜利" in body
    assert "全部身份：" in body


def test_replay_includes_marks_and_votes() -> None:
    body = "\n".join(views.render_replay(_state(winner=None), SETTINGS, reveal_all=False))

    assert "标记发言：" in body
    assert "声明平民" in body
    assert "投票：" in body and "→" in body


# =====================================================================
# 报名房间超时清理
# =====================================================================
async def test_room_expiry_removes_only_its_own_room() -> None:
    mine = commands.PendingRoom(group_id=999001, host_id=1)
    newer = commands.PendingRoom(group_id=999001, host_id=2)
    commands._rooms[999001] = newer  # type: ignore[attr-defined]
    try:
        await commands._expire_room(999001, mine)  # type: ignore[arg-type]
        assert commands._rooms[999001] is newer, "过期回调误删了后来的房间"
    finally:
        commands._rooms.pop(999001, None)  # type: ignore[attr-defined]


async def test_room_expiry_drops_the_room_and_announces() -> None:
    room = commands.PendingRoom(group_id=999002, host_id=1)
    commands._rooms[999002] = room  # type: ignore[attr-defined]
    broadcast = AsyncMock()
    try:
        with patch.object(session, "broadcast", broadcast):
            await commands._expire_room(999002, room)  # type: ignore[arg-type]
    finally:
        commands._rooms.pop(999002, None)  # type: ignore[attr-defined]

    assert 999002 not in commands._rooms  # type: ignore[attr-defined]
    assert broadcast.await_count == 1
    assert "已自动取消" in broadcast.await_args.args[1]


async def test_room_expiry_never_raises_when_announcing_fails() -> None:
    """清理是尽力而为：连广播都发不出去，也不能留下脏房间。"""
    room = commands.PendingRoom(group_id=999003, host_id=1)
    commands._rooms[999003] = room  # type: ignore[attr-defined]
    try:
        with patch.object(session, "broadcast", AsyncMock(side_effect=RuntimeError("boom"))):
            await commands._expire_room(999003, room)  # type: ignore[arg-type]
    finally:
        commands._rooms.pop(999003, None)  # type: ignore[attr-defined]

    assert 999003 not in commands._rooms  # type: ignore[attr-defined]


async def test_scheduling_expiry_without_a_scheduler_is_not_an_error() -> None:
    """CLI / 没装调度器时：安静跳过，绝不能让建房失败。"""
    room = commands.PendingRoom(group_id=999004, host_id=1)
    with patch.dict("sys.modules", {"core.scheduler": None}):
        await commands._schedule_room_expiry(999004, room)  # type: ignore[arg-type]
    await commands._cancel_room_expiry(999004)
