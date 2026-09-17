from __future__ import annotations

import nonebot

nonebot.init()

from src.plugins.games.deep_sea_mission.commands import (  # noqa: E402
    PendingRoom,
    _rooms,
    cancel_room,
    has_pending_room,
)


def test_lobby_commands_only_match_when_room_exists() -> None:
    _rooms.clear()
    try:
        assert has_pending_room(42) is False
        _rooms[42] = PendingRoom(group_id=42, host_id=1, difficulty=8)
        assert has_pending_room(42) is True
        assert has_pending_room(99) is False
    finally:
        _rooms.clear()


def test_cancel_room_clears_stuck_lobby() -> None:
    """房主挂机时的清场通道：`@我 结束` 会把等待中的房间也收掉。"""
    _rooms.clear()
    try:
        _rooms[42] = PendingRoom(group_id=42, host_id=1, difficulty=8)
        assert cancel_room(42) is True
        assert has_pending_room(42) is False
        # 再取消一次是安全的（没房间就返回 False，不抛）
        assert cancel_room(42) is False
    finally:
        _rooms.clear()


def test_quit_handler_room_imports_exist() -> None:
    """`@我 结束` 契约：`game_launcher.handlers._quit` 延迟导入的两个 cancel_room 必须存在。

    回归：深海任务漏了 cancel_room 时，那行 ImportError 会让**所有游戏**的
    `@我 结束` 直接崩掉（机器人毫无回应）——它跟本游戏无关，所以两个导入都钉住。
    """
    from src.plugins.games.deep_sea_mission.commands import cancel_room as deep_sea_cancel
    from src.plugins.games.silent_mark.commands import cancel_room as silent_mark_cancel

    assert callable(deep_sea_cancel)
    assert callable(silent_mark_cancel)
