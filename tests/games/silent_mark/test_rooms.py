"""报名房间的规则测试（对齐 `deep_sea_mission/test_commands.py` 的做法）。

房间规则全是"没人在群里看着也必须对"的硬逻辑（人数、房主、调试座位），
所以从 handler 里抽出来单独测，别让它只活在 nonebot 匹配器里。
"""

from __future__ import annotations

import nonebot

nonebot.init()

from core.types import User  # noqa: E402
from src.plugins.games.silent_mark.commands import (  # noqa: E402
    PendingRoom,
    _join_blockers,
    _preset_of,
    _required_players,
    _room_line,
    _rooms,
    _start_blockers,
    cancel_room,
    has_pending_room,
)
from src.plugins.games.silent_mark.engine import constants as C  # noqa: E402

GROUP = 424242


def _user(qq: int, name: str) -> User:
    return User(qq_id=qq, nickname=name, group_id=GROUP)


def _room(preset: str = "4standard", *, count: int = 1, host: int = 1) -> PendingRoom:
    room = PendingRoom(group_id=GROUP, host_id=host, preset=preset)
    for index in range(count):
        qq = 1 + index
        room.players[qq] = _user(qq, f"玩家{qq}")
        room.seat_owners[qq] = qq
    return room


# =====================================================================
# 房间状态
# =====================================================================
def test_lobby_commands_only_match_when_room_exists() -> None:
    _rooms.clear()
    try:
        assert has_pending_room(GROUP) is False
        _rooms[GROUP] = _room()
        assert has_pending_room(GROUP) is True
    finally:
        _rooms.clear()


def test_cancel_room_lets_anyone_clear_a_stuck_lobby() -> None:
    """房主挂机时的清场通道：`@我 结束` 会把等待中的房间也收掉。

    （全局 `结束` 本来就不校验房主，见 `game_launcher/handlers.py`）
    """
    _rooms.clear()
    try:
        _rooms[GROUP] = _room()
        assert cancel_room(GROUP) is True
        assert has_pending_room(GROUP) is False
        # 再取消一次是安全的（没房间就返回 False，不抛）
        assert cancel_room(GROUP) is False
    finally:
        _rooms.clear()


# =====================================================================
# 板子
# =====================================================================
def test_preset_token_accepts_id_label_alias_and_index() -> None:
    assert _preset_of("4standard") == "4standard"
    assert _preset_of("6gods") == "6gods"
    assert _preset_of("6人神职") == "6gods"  # 去空格的展示名（= 别名）
    assert _preset_of("6 人神职") == "6gods"  # 带空格的展示名也认
    assert _preset_of("1") == "4standard"  # 编号（与菜单顺序一致）
    assert _preset_of("不存在的板子") is None


def test_required_players_matches_every_preset() -> None:
    for preset in C.PRESETS:
        assert _required_players(preset) == sum(C.PRESETS[preset].roles.values())
    assert _required_players("4standard") == 4
    assert _required_players("6gods") == 6


# =====================================================================
# 人数：必须恰好等于板子人数
# =====================================================================
def test_join_is_blocked_once_the_preset_is_full() -> None:
    room = _room("4standard", count=4)
    blocked = _join_blockers(room)
    assert blocked is not None
    assert "已经满了" in blocked


def test_start_allows_fewer_players_because_ai_fills_the_gap() -> None:
    """人不够也能开 —— **AI 会补满**（房主不必凑人，这是默认行为）。"""
    assert _start_blockers(_room("4standard", count=3), 1) is None
    assert _start_blockers(_room("6gods", count=1), 1) is None  # 一个人也能开


def test_start_rejects_more_players_than_the_board() -> None:
    many = _room("4standard", count=5)
    blocked = _start_blockers(many, 1)
    assert blocked is not None
    assert "最多 4 人" in blocked and "现在 5 人" in blocked


def test_start_needs_an_exact_count_when_ai_fill_is_off() -> None:
    room = _room("4standard", count=3)
    room.ai_fill = False

    blocked = _start_blockers(room, 1)
    assert blocked is not None
    assert "关掉了 AI 补位" in blocked
    assert "AI 开" in blocked  # 要告诉房主怎么恢复

    room.ai_fill = True
    assert _start_blockers(room, 1) is None


def test_only_the_host_can_start() -> None:
    room = _room("4standard", count=4)
    blocked = _start_blockers(room, 2)
    assert blocked is not None and "只有房主" in blocked
    # 但提示里要告诉所有人"结束"是人人可用的
    assert "结束" in blocked
    assert _start_blockers(room, 1) is None


# =====================================================================
# 房间面板
# =====================================================================
def test_room_line_marks_host_debug_seat_and_missing_count() -> None:
    room = _room("6gods", count=2)
    debug_owner = 1
    debug_seat = 9_000_000_000_000_001
    room.players[debug_seat] = _user(debug_seat, "玩家1-调试1")
    room.seat_owners[debug_seat] = debug_owner

    text = _room_line(room)
    assert "6 人神职" in text
    assert "3 / 6" in text and "还差 3 人" in text
    assert "AI 会补满" in text  # 人不够不是问题，AI 会补齐
    assert "（房主）" in text
    assert "[调试位]" in text
    # 面板要写清"谁加机器人为好友"这件事——本作所有私密信息都靠私聊
    assert "加机器人" in text or "加机器人为好友" in text
