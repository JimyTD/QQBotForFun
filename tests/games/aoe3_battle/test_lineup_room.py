"""配兵房间群消息：不公布单人配兵结果，全员就绪才提示开始。"""

from __future__ import annotations

import nonebot

nonebot.init()

from src.plugins.games.aoe3_battle.lineup_room import (  # noqa: E402
    LineupRoom,
    Seat,
    format_all_ready,
    format_room,
)


def _room(*seats: Seat, tournament: bool = False) -> LineupRoom:
    return LineupRoom(
        group_id=1,
        host_id=seats[0].user_id,
        tournament=tournament,
        age=4,
        budget=10000,
        field_length=36.0,
        seats=list(seats),
    )


def test_room_card_lists_names_without_armies_or_host():
    room = _room(Seat(user_id=7, nickname="JimyTD", is_host=True, army=object()))
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
    room = _room(Seat(user_id=7, nickname="JimyTD", is_host=True, army=object()))
    text = format_all_ready(room)
    assert "全体玩家已配好" in text
    assert "空位 1，开始时补 AI" in text
    assert "空位 1，开始时补 AI\n\n@我 开始" in text
    assert text.endswith("@我 开始")
    assert "房主" not in text


def test_full_room_ready_prompt_has_no_empty_seats():
    room = _room(
        Seat(user_id=7, nickname="JimyTD", is_host=True, army=object()),
        Seat(user_id=8, nickname="客人", is_host=False, army=object()),
    )
    text = format_all_ready(room)
    assert "全体玩家已配好" in text
    assert "空位" not in text
    assert text.split("\n\n") == ["⚔️ 配兵 · 全体玩家已配好", "@我 开始"]
    assert text.endswith("@我 开始")
    assert "房主" not in text
