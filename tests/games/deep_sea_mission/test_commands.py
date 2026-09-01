from __future__ import annotations

import nonebot

nonebot.init()

from src.plugins.games.deep_sea_mission.commands import (  # noqa: E402
    PendingRoom,
    _rooms,
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
