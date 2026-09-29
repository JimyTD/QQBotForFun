"""Signup room for 配兵 and 配兵锦标赛.

The room blocks other cricket battles until it is cancelled or the match
starts. Army building happens in private messages.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from nonebot import on_command, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule, to_me

from core import game_base, session
from core.errors import GameAlreadyRunningError, WhisperFailedError
from core.types import User
from src.plugins.aoe3.repository import UnitRepo
from src.plugins.games.aoe3_battle.lineup_draft import CompiledArmy, compile_ai_army
from src.plugins.games.aoe3_battle.lineup_wizard import Wizard, advance, opening_prompt

_rooms: dict[int, LineupRoom] = {}
_player_group: dict[int, int] = {}


@dataclass
class Seat:
    user_id: int
    nickname: str
    is_host: bool
    wizard: Wizard = field(default_factory=Wizard)
    army: CompiledArmy | None = None

    @property
    def ready(self) -> bool:
        return self.army is not None


@dataclass
class LineupRoom:
    group_id: int
    host_id: int
    tournament: bool
    age: int
    budget: int
    field_length: float
    seats: list[Seat] = field(default_factory=list)

    @property
    def capacity(self) -> int:
        return 8 if self.tournament else 2


def has_lineup_room(group_id: int) -> bool:
    return group_id in _rooms


def get_lineup_room(group_id: int) -> LineupRoom | None:
    return _rooms.get(group_id)


def cancel_lineup_room(group_id: int) -> bool:
    room = _rooms.pop(group_id, None)
    if room is None:
        return False
    for seat in room.seats:
        _player_group.pop(seat.user_id, None)
    return True


def format_room(room: LineupRoom) -> str:
    title = "配兵锦标赛" if room.tournament else "配兵"
    lines = [f"⚔️ {title} · {room.age}时代 · 军费 {room.budget}"]
    for index, seat in enumerate(room.seats, start=1):
        lines.append(f"{index}. {seat.nickname}")
    empty = room.capacity - len(room.seats)
    if empty:
        lines.append(f"空位 {empty}")
    lines.append("@我 加入 / @我 离开")
    return "\n".join(lines)


def format_all_ready(room: LineupRoom) -> str:
    """群提示：已报名的玩家都配完了。空位留给开始时的 AI。"""
    title = "配兵锦标赛" if room.tournament else "配兵"
    lines = [f"⚔️ {title} · 全体玩家已配好"]
    empty = room.capacity - len(room.seats)
    if empty:
        lines.append(f"空位 {empty}，开始时补 AI")
    lines.append("房主 @我 开始")
    return "\n".join(lines)


def _humans_ready(room: LineupRoom) -> bool:
    return bool(room.seats) and all(seat.ready for seat in room.seats)


def _nickname(event: GroupMessageEvent) -> str:
    sender = event.sender
    card = getattr(sender, "card", "") or ""
    nickname = getattr(sender, "nickname", "") or ""
    return card or nickname or str(event.user_id)


async def open_lineup_room(
    *,
    group_id: int,
    host_id: int,
    nickname: str,
    tournament: bool,
    age: int,
    budget: int,
    field_length: float,
) -> str | None:
    """Open a room and whisper the host. Returns an error string, or None."""
    if age not in {3, 4, 5}:
        return "⚠️ 配兵只开放 3～5 时代。先 @我 斗蛐蛐 3时代 再开房"
    if game_base.get_runner_by_group(group_id) is not None or has_lineup_room(group_id):
        return "⚠️ 本群已有进行中的斗蛐蛐，先 @我 结束"
    from src.plugins.games.aoe3_battle.rival_pick import has_pending

    if has_pending(group_id):
        return "⚠️ 本群正在选王中王主题，先 @我 结束"
    if host_id in _player_group:
        return "⚠️ 你已经在另一场配兵里"
    room = LineupRoom(
        group_id=group_id,
        host_id=host_id,
        tournament=tournament,
        age=age,
        budget=budget,
        field_length=field_length,
        seats=[Seat(user_id=host_id, nickname=nickname, is_host=True)],
    )
    try:
        await session.whisper(host_id, opening_prompt())
    except WhisperFailedError:
        return "⚠️ 请先加机器人为好友，配兵在私聊里进行"
    _rooms[group_id] = room
    _player_group[host_id] = group_id
    await session.broadcast(group_id, format_room(room))
    return None


async def _join(event: GroupMessageEvent) -> str:
    room = _rooms.get(int(event.group_id))
    if room is None:
        return "⚠️ 本群没有配兵房间"
    user_id = int(event.user_id)
    if any(seat.user_id == user_id for seat in room.seats):
        return "你已经在房间里"
    if len(room.seats) >= room.capacity:
        return "人满了"
    if user_id in _player_group:
        return "⚠️ 你已经在另一场配兵里"
    try:
        await session.whisper(user_id, opening_prompt())
    except WhisperFailedError:
        return "⚠️ 请先加机器人为好友，配兵在私聊里进行"
    room.seats.append(Seat(
        user_id=user_id,
        nickname=_nickname(event),
        is_host=False,
    ))
    _player_group[user_id] = room.group_id
    return format_room(room)


async def _leave(event: GroupMessageEvent) -> str:
    room = _rooms.get(int(event.group_id))
    if room is None:
        return "⚠️ 本群没有配兵房间"
    user_id = int(event.user_id)
    seat = next((item for item in room.seats if item.user_id == user_id), None)
    if seat is None:
        return "你不在这个房间里"
    if seat.is_host:
        cancel_lineup_room(room.group_id)
        return "房主已离开，配兵房间解散"
    room.seats.remove(seat)
    _player_group.pop(user_id, None)
    if _humans_ready(room):
        return f"{format_room(room)}\n\n{format_all_ready(room)}"
    return format_room(room)


async def _start(event: GroupMessageEvent) -> str | None:
    """Lock the room and launch the battle. None means the game has started."""
    room = _rooms.get(int(event.group_id))
    if room is None:
        return "⚠️ 本群没有配兵房间"
    user_id = int(event.user_id)
    if user_id != room.host_id:
        return "只有房主可以开始"
    missing = [seat.nickname for seat in room.seats if not seat.ready]
    if missing:
        return "还没配完：" + "、".join(missing)
    repo = UnitRepo.get()
    rng = random.Random()
    armies = [seat.army.to_dict() for seat in room.seats if seat.army is not None]
    while len(armies) < room.capacity:
        armies.append(compile_ai_army(
            repo, age=room.age, budget=room.budget, rng=rng,
        ).to_dict())
    mode = "lineup_tournament" if room.tournament else "lineup"
    config = {
        "mode": mode,
        "age": room.age,
        "budget": room.budget,
        "field_length": room.field_length,
        "armies": armies,
    }
    try:
        await game_base.create_and_start(
            "aoe3_battle",
            group_id=room.group_id,
            host_id=room.host_id,
            players=[
                User(
                    qq_id=seat.user_id,
                    nickname=seat.nickname,
                    group_id=room.group_id,
                )
                for seat in room.seats
            ],
            config=config,
        )
    except GameAlreadyRunningError as exc:
        return f"⚠️ {exc}"
    except Exception as exc:
        return f"⚠️ 启动失败：{exc}"
    cancel_lineup_room(room.group_id)
    return None


async def _on_private(user_id: int, text: str) -> None:
    group_id = _player_group.get(user_id)
    if group_id is None:
        return
    room = _rooms.get(group_id)
    if room is None:
        _player_group.pop(user_id, None)
        return
    seat = next((item for item in room.seats if item.user_id == user_id), None)
    if seat is None:
        return
    repo = UnitRepo.get()
    seat.wizard, reply = advance(
        seat.wizard,
        text,
        repo=repo,
        age=room.age,
        budget=room.budget,
        nickname=seat.nickname,
    )
    was_ready = seat.ready
    seat.army = seat.wizard.army
    try:
        await session.whisper(user_id, reply)
    except WhisperFailedError:
        return
    if seat.ready and not was_ready and _humans_ready(room):
        await session.broadcast(group_id, format_all_ready(room))


def _room_rule(event: GroupMessageEvent) -> bool:
    return has_lineup_room(int(event.group_id))


_ROOM = Rule(_room_rule)

_join_cmd = on_command("加入", rule=to_me() & _ROOM, priority=2, block=True)
_leave_cmd = on_command("离开", rule=to_me() & _ROOM, priority=2, block=True)
_start_cmd = on_command("开始", rule=to_me() & _ROOM, priority=2, block=True)


@_join_cmd.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    await matcher.finish(await _join(event))


@_leave_cmd.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    await matcher.finish(await _leave(event))


@_start_cmd.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    error = await _start(event)
    if error:
        await matcher.finish(error)


def _private_rule(event: PrivateMessageEvent) -> bool:
    return int(event.user_id) in _player_group


_private = on_message(rule=Rule(_private_rule), priority=2, block=True)


@_private.handle()
async def _(event: PrivateMessageEvent) -> None:
    text = event.get_plaintext().strip()
    if not text:
        return
    await _on_private(int(event.user_id), text)
