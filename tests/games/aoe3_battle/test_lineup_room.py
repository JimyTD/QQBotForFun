"""配兵房间群消息：不公布单人配兵结果，全员就绪才提示开始。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import nonebot

nonebot.init()

from src.plugins.games.aoe3_battle.lineup_room import (  # noqa: E402
    LineupRoom,
    Seat,
    _leave,
    _rooms,
    _start,
    format_all_ready,
    format_room,
)


def _event(*, group_id: int, user_id: int):
    return SimpleNamespace(group_id=group_id, user_id=user_id)


class _Army:
    def to_dict(self):
        return {"slots": []}


def _room(*seats: Seat, tournament: bool = False) -> LineupRoom:
    return LineupRoom(
        group_id=1,
        tournament=tournament,
        age=4,
        budget=10000,
        field_length=36.0,
        seats=list(seats),
    )


def test_room_card_lists_names_without_armies_or_host():
    room = _room(Seat(user_id=7, nickname="JimyTD", army=object()))
    text = format_room(room)
    assert "JimyTD" in text
    assert "空位 1" in text
    assert "@我 加入 / @我 离开" in text
    assert "房主" not in text
    assert "已备好" not in text
    assert "风云" not in text
    assert text.split("\n\n") == [
        "⚔️ 配兵 · 4时代 · 军费 10000",
        "1. JimyTD\n空位 1",
        "@我 加入 / @我 离开",
    ]


def test_all_human_players_ready_prompts_start():
    room = _room(Seat(user_id=7, nickname="JimyTD", army=object()))
    text = format_all_ready(room)
    assert "全体玩家已配好" in text
    assert "空位 1，开始时补 AI" in text
    assert "空位 1，开始时补 AI\n\n@我 开始" in text
    assert text.endswith("@我 开始")
    assert "房主" not in text


def test_full_room_ready_prompt_has_no_empty_seats():
    room = _room(
        Seat(user_id=7, nickname="JimyTD", army=object()),
        Seat(user_id=8, nickname="客人", army=object()),
    )
    text = format_all_ready(room)
    assert "全体玩家已配好" in text
    assert "空位" not in text
    assert text.split("\n\n") == ["⚔️ 配兵 · 全体玩家已配好", "@我 开始"]
    assert text.endswith("@我 开始")
    assert "房主" not in text


async def test_any_seat_can_start_when_everyone_is_ready():
    room = _room(
        Seat(user_id=7, nickname="JimyTD", army=_Army()),
        Seat(user_id=8, nickname="客人", army=_Army()),
    )
    _rooms[room.group_id] = room
    with patch(
        "src.plugins.games.aoe3_battle.lineup_room.game_base.create_and_start",
        new_callable=AsyncMock,
    ) as start:
        try:
            event = _event(group_id=room.group_id, user_id=8)
            assert await _start(event) is None
            start.assert_awaited_once()
            assert start.await_args.kwargs["host_id"] == 8
        finally:
            _rooms.pop(room.group_id, None)


async def test_layout_opener_leaving_keeps_room_alive_and_last_leave_closes_it():
    room = _room(
        Seat(user_id=7, nickname="JimyTD"),
        Seat(user_id=8, nickname="客人"),
    )
    _rooms[room.group_id] = room
    try:
        first = _event(group_id=room.group_id, user_id=7)
        text = await _leave(first)
        assert "解散" not in text
        assert room.group_id in _rooms
        assert [seat.user_id for seat in room.seats] == [8]

        last = _event(group_id=room.group_id, user_id=8)
        text = await _leave(last)
        assert "解散" in text
        assert room.group_id not in _rooms
    finally:
        _rooms.pop(room.group_id, None)
