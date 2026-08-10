"""深海任务：报名房间与开局命令。"""

from __future__ import annotations

from dataclasses import dataclass, field

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import to_me

from core import game_base, user
from core.errors import GameAlreadyRunningError
from core.types import User


@dataclass
class PendingRoom:
    group_id: int
    host_id: int
    difficulty: int
    players: dict[int, User] = field(default_factory=dict)


_rooms: dict[int, PendingRoom] = {}


def _parse_difficulty(text: str) -> int | None:
    parts = text.strip().split()
    if not parts:
        return None
    for part in parts:
        if part.isdigit():
            value = int(part)
            if value > 0:
                return value
    return None


def _room_line(room: PendingRoom) -> str:
    names = "、".join(f"@{p.nickname}" for p in room.players.values())
    return (
        f"🌊 深海任务房间\n"
        f"目标难度：{room.difficulty}\n"
        f"人数：{len(room.players)} / 5（至少 3 人）\n"
        f"玩家：{names}\n"
        "💡 @我 加入 加入房间；房主 @我 开始 发牌"
    )


_start_room = on_command(
    "深海任务",
    aliases={"deep_sea_mission"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_start_room.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()) -> None:
    group_id = int(event.group_id)
    if game_base.get_runner_by_group(group_id) is not None:
        await matcher.finish("⚠️ 本群已有进行中的游戏，先 @我 结束 终止当前游戏。")
        return
    difficulty = _parse_difficulty(args.extract_plain_text())
    if difficulty is None:
        await matcher.finish("⚠️ 请指定任务总难度，例如：@我 深海任务 8")
        return
    player = await user.get(int(event.user_id), group_id)
    room = PendingRoom(
        group_id=group_id,
        host_id=player.qq_id,
        difficulty=difficulty,
        players={player.qq_id: player},
    )
    _rooms[group_id] = room
    await matcher.finish(_room_line(room))


_join_room = on_command(
    "加入",
    aliases={"join", "参战"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_join_room.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    room = _rooms.get(group_id)
    if room is None:
        await matcher.finish("当前没有等待中的深海任务房间。")
        return
    if game_base.get_runner_by_group(group_id) is not None:
        _rooms.pop(group_id, None)
        await matcher.finish("⚠️ 本群已有进行中的游戏，等待房间已取消。")
        return
    player = await user.get(int(event.user_id), group_id)
    if player.qq_id in room.players:
        await matcher.finish(_room_line(room))
        return
    if len(room.players) >= 5:
        await matcher.finish("⚠️ 深海任务最多 5 人。")
        return
    room.players[player.qq_id] = player
    await matcher.finish(_room_line(room))


_leave_room = on_command(
    "离开",
    aliases={"leave", "退出房间"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_leave_room.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    room = _rooms.get(group_id)
    if room is None:
        await matcher.finish("当前没有等待中的深海任务房间。")
        return
    qq_id = int(event.user_id)
    room.players.pop(qq_id, None)
    if not room.players:
        _rooms.pop(group_id, None)
        await matcher.finish("深海任务房间已取消。")
        return
    if qq_id == room.host_id:
        room.host_id = next(iter(room.players))
    await matcher.finish(_room_line(room))


_begin_room = on_command(
    "开始",
    aliases={"start"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_begin_room.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    room = _rooms.get(group_id)
    if room is None:
        await matcher.finish("当前没有等待中的深海任务房间。")
        return
    if int(event.user_id) != room.host_id:
        await matcher.finish("⚠️ 只有房主可以开始深海任务。")
        return
    if len(room.players) < 3:
        await matcher.finish("⚠️ 深海任务至少需要 3 名玩家。")
        return
    if game_base.get_runner_by_group(group_id) is not None:
        _rooms.pop(group_id, None)
        await matcher.finish("⚠️ 本群已有进行中的游戏，等待房间已取消。")
        return
    players = list(room.players.values())
    _rooms.pop(group_id, None)
    try:
        await game_base.create_and_start(
            "deep_sea_mission",
            group_id=group_id,
            host_id=room.host_id,
            players=players,
            config={"mode": "mission", "difficulty": room.difficulty},
        )
    except GameAlreadyRunningError as e:
        await matcher.finish(f"⚠️ {e}")
    except Exception as e:  # noqa: BLE001
        await matcher.finish(f"⚠️ 深海任务启动失败：{e}")
