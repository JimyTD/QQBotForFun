"""静夜标记：报名房间与玩家指令。

指令表（全部需要 @机器人；房间类指令**只在本群有待开始房间时**才拦截）：

- ``静夜标记 [板子]``  创建报名房间并成为房主（本群没有进行中的对局时）
- ``加入`` / ``重复加入`` / ``离开``   报名房间内可用
- ``板子 <板子>``      房主换板子（仅报名阶段）
- ``踢人 <编号>``      房主按**报名编号**踢人（仅报名阶段）
- ``开始``             房主开局；人数必须**恰好等于**板子人数
- ``记录``             本局玩家随时私聊查看自己的身份与私有记录（群内指令消息会被撤回）

**这里刻意不注册 `结束`**：它是全局命令（`game_launcher`），任何群友都能终止本局，
不需要房主。⚠️ 而它的别名里有 `认输` —— 所以"单人出局"只用回复「退出」，
**不要**另立 `认输` 命令，否则会误杀整局。

房主权限只用于"房间里的事"（换板子 / 踢人 / 开始）。一旦开局，房主不再是特权身份。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from nonebot import on_command
from nonebot import logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import Rule, to_me

from core import game_base, llm, session, user
from core.errors import LLMConfigError, LLMError
from core.errors import GameAlreadyRunningError
from core.game_base import resolve_mode
from core.types import User

from . import custom_setup
from .engine import constants as C  # noqa: N812
from .game import DEFAULT_PRESET, SilentMarkGame

#: ⚠️ `LLMConfigError` 不是 `LLMError` 的子类（继承 GameError），两个都要接
_LLM_FAILURES = (LLMError, LLMConfigError)


# =====================================================================
# 报名房间
# =====================================================================
@dataclass
class PendingRoom:
    group_id: int
    host_id: int
    preset: str = DEFAULT_PRESET
    players: dict[int, User] = field(default_factory=dict)
    seat_owners: dict[int, int] = field(default_factory=dict)
    #: 自定义板子：`preset == "custom"` 时由 `custom_setup` 向导产出
    custom_roles: dict[str, int] | None = None
    win_condition: str = C.WIN_EDGE
    #: 随身物品开关（房主可以在房间里关掉）
    items_enabled: bool = True
    #: 默认 AI 补位：人数不够就用 AI 填满（房主可 `@我 AI 关` 关掉）
    ai_fill: bool = True

    @property
    def required_players(self) -> int:
        """本房间的板子需要多少人（自定义板子按向导产物算）。"""
        return _required_players(self.preset, self.custom_roles)

    def describe_preset(self) -> str:
        """板子的一句话描述：预设用预设文案，自定义用向导产物的文案。"""
        if self.preset == "custom":
            return custom_setup.CustomBoard(
                roles=dict(self.custom_roles or {}),
                win_condition=self.win_condition,
                items_enabled=self.items_enabled,
            ).describe()
        return _preset_label(self.preset)


_rooms: dict[int, PendingRoom] = {}


def has_pending_room(group_id: int) -> bool:
    return group_id in _rooms


def cancel_room(group_id: int) -> bool:
    """撤掉等待中的报名房间。供全局 `@我 结束` 使用（见 `game_launcher.handlers`）。"""
    return _rooms.pop(group_id, None) is not None


#: 报名房间空闲多久自动撤掉（秒）
ROOM_TTL_SECONDS = 30 * 60


def _room_tag(group_id: int) -> str:
    return f"silent_mark_room_{group_id}"


async def _expire_room(group_id: int, room: PendingRoom) -> None:
    """房间空闲超时：撤掉报名并公告。

    不清理的后果很具体：`_rooms` 里一直挂着这个群，之后谁 `@我 静夜标记`
    都会被告知"群里已有报名中的房间"，而房主早就散了。
    """
    if _rooms.get(group_id) is not room:
        return  # 已经换成新房间 / 已经开局，别误删
    _rooms.pop(group_id, None)
    try:
        await session.broadcast(
            group_id, "🌙 静夜标记报名已超时（30 分钟无人开始），房间已自动取消。"
        )
    except Exception:  # noqa: BLE001 — 清理是尽力而为，发不出消息也不能留着脏状态
        return


async def _schedule_room_expiry(group_id: int, room: PendingRoom) -> None:
    """挂一个一次性清理任务。**没有调度器时安静跳过**（CLI、插件未加载）。"""
    try:
        from core.scheduler import schedule_once

        await schedule_once(
            ROOM_TTL_SECONDS,
            _expire_room,
            tag=_room_tag(group_id),
            group_id=group_id,
            room=room,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[silent_mark] 房间超时清理未注册：{exc!r}")


async def _cancel_room_expiry(group_id: int) -> None:
    try:
        from core.scheduler import cancel

        await cancel(tag=_room_tag(group_id))
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[silent_mark] 取消房间超时清理失败：{exc!r}")


async def _is_pending_room(event: GroupMessageEvent) -> bool:
    return has_pending_room(int(event.group_id))


_PENDING_ROOM = Rule(_is_pending_room)


# =====================================================================
# 小工具
# =====================================================================
def _preset_of(token: str) -> str | None:
    """板子 token → 板子 id。

    支持 id / 展示名 / 别名 / 编号，统一交给 `resolve_mode` 解析（CLI 与 QQ 同一份）。
    展示名里有空格（``6 人神职``），而别名是去空格的（``6人神职``），
    所以这里两种都试一遍，玩家怎么写都能认。
    """
    for candidate in (token, token.replace(" ", "")):
        mode = resolve_mode(SilentMarkGame.MODES, candidate)
        if mode is not None:
            return mode.id
    return None


def _required_players(
    preset: str, custom_roles: dict[str, int] | None = None
) -> int:
    """板子需要多少人。

    ``custom`` 不在 `C.PRESETS` 里：人数由自定义向导产出（`PendingRoom.custom_roles`），
    所以这里必须能接住"没有预设"的情况，不能直接下标。
    """
    config = C.PRESETS.get(preset)
    if config is not None:
        return sum(config.roles.values())
    return sum(int(count) for count in (custom_roles or {}).values())


def _preset_label(preset: str) -> str:
    roles = C.PRESETS[preset].roles
    role_text = " · ".join(
        f"{C.ROLE_LABELS.get(role, role)}×{count}" for role, count in roles.items() if count
    )
    return f"{C.PRESET_LABELS.get(preset, preset)}（{role_text}）"


def _room_line(room: PendingRoom) -> str:
    required = room.required_players
    names = "、".join(
        (
            f"@{p.nickname}（房主）"
            if room.seat_owners.get(p.qq_id, p.qq_id) == room.host_id and p.qq_id == room.host_id
            else f"@{p.nickname}"
        )
        if room.seat_owners.get(p.qq_id, p.qq_id) == p.qq_id
        else f"@{p.nickname}[调试位]"
        for p in room.players.values()
    )
    numbered = "　".join(
        f"{index}. {p.nickname}" for index, p in enumerate(room.players.values(), 1)
    )
    missing = required - len(room.players)
    count_line = (
        f"人数：{len(room.players)} / {required}"
        + (f"（还差 {missing} 人）" if missing > 0 else " ✅")
    )
    return "\n".join(
        [
            "🌙 静夜标记 · 报名中",
            f"板子：{room.describe_preset()}",
            count_line,
            f"玩家：{names}",
            f"编号：{numbered}",
            "",
            "💡 @我 加入 报名；房主 @我 开始 开局；房主 @我 板子 6gods 换板子",
            "💡 报满后房主 @我 开始（人数必须与板子一致）",
            "💡 房主：@我 板子 自定义 配自己的板子；@我 物品 关 关掉随身物品",
            "⚠️ 请先加机器人为好友：身份牌、夜间行动、投票都走私聊",
        ]
    )


def _join_blockers(room: PendingRoom) -> str | None:
    """报名前的校验；返回 None = 可以加入，返回字符串 = 拒绝原因。"""
    required = room.required_players
    if len(room.players) >= required:
        return (
            f"⚠️ {room.describe_preset()} 正好 {required} 人，已经满了。\n"
            "💡 想更多人一起玩，房主可以 @我 板子 换个更大的板子。"
        )
    return None


def _start_blockers(room: PendingRoom, actor_id: int) -> str | None:
    """开局前的硬校验；返回 None = 可以开局，返回字符串 = 拒绝原因。

    唯一的人数规则是**恰好等于**板子人数（源项目同口径：不多也不少）。
    """
    if actor_id != room.host_id:
        return "⚠️ 只有房主可以开始。（想收掉整局随时 @我 结束，那个人人可用）"
    required = room.required_players
    if len(room.players) != required:
        return (
            f"⚠️ {room.describe_preset()} 需要恰好 {required} 人，"
            f"现在 {len(room.players)} 人。\n"
            "💡 房主可以 @我 板子 换个合身的板子。"
        )
    return None


def _new_debug_seat_id(room: PendingRoom) -> int:
    while True:
        seat_id = 9_000_000_000_000_000 + uuid.uuid4().int % 900_000_000_000_000
        if seat_id not in room.players:
            return seat_id


# =====================================================================
# 创建房间
# =====================================================================
_start_room = on_command(
    "静夜标记",
    aliases={"静夜", "silent_mark", "标记游戏"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_start_room.handle()
async def _(
    matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    group_id = int(event.group_id)
    if game_base.get_runner_by_group(group_id) is not None:
        await matcher.finish("⚠️ 本群已有进行中的游戏，先 @我 结束 终止当前游戏。")
        return

    token = args.extract_plain_text().strip()
    preset = DEFAULT_PRESET
    if token:
        resolved = _preset_of(token)
        if resolved is None:
            options = "、".join(m.id for m in SilentMarkGame.MODES)
            await matcher.finish(f"⚠️ 没有这个板子。可用：{options}")
            return
        preset = resolved

    player = await user.get(int(event.user_id), group_id)
    room = PendingRoom(
        group_id=group_id,
        host_id=player.qq_id,
        preset=preset,
        players={player.qq_id: player},
        seat_owners={player.qq_id: player.qq_id},
    )
    _rooms[group_id] = room
    await _schedule_room_expiry(group_id, room)
    if preset == "custom":
        # 房主一开口就要自定义 → 直接把向导跑起来（免得他再发一次"板子 自定义"）
        await _apply_custom_board(matcher, room)
        return
    await matcher.finish(_room_line(room))


# =====================================================================
# 房间内指令
# =====================================================================
def _stale_room(event: GroupMessageEvent) -> PendingRoom | None:
    """取房间；若本群已有对局在跑，说明房间是残留的，顺手清掉。"""
    group_id = int(event.group_id)
    room = _rooms.get(group_id)
    if room is None:
        return None
    if game_base.get_runner_by_group(group_id) is not None:
        _rooms.pop(group_id, None)
        return None
    return room


_join_room = on_command(
    "加入",
    aliases={"join", "报名"},
    rule=to_me() & _PENDING_ROOM,
    priority=3,
    block=True,
)


@_join_room.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    room = _stale_room(event)
    if room is None:
        return
    player = await user.get(int(event.user_id), int(event.group_id))
    if player.qq_id in room.players:
        await matcher.finish(_room_line(room))
        return
    blocked = _join_blockers(room)
    if blocked is not None:
        await matcher.finish(blocked)
        return
    room.players[player.qq_id] = player
    room.seat_owners[player.qq_id] = player.qq_id
    await matcher.finish(_room_line(room))


_duplicate_join = on_command(
    "重复加入",
    aliases={"调试加入", "debug_join"},
    rule=to_me() & _PENDING_ROOM,
    priority=3,
    block=True,
)


@_duplicate_join.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    """一个 QQ 多占一个座位（少数人想测 6 人局时用）。"""
    room = _stale_room(event)
    if room is None:
        return
    required = _required_players(room.preset)
    owner_already_seated = int(event.user_id) in room.seat_owners
    seats_needed = 1 if owner_already_seated else 2
    if len(room.players) + seats_needed > required:
        await matcher.finish(
            f"⚠️ {_preset_label(room.preset)} 需要 {required} 人，加不下更多调试座位了。"
        )
        return

    group_id = int(event.group_id)
    owner = await user.get(int(event.user_id), group_id)
    if owner.qq_id not in room.players:
        room.players[owner.qq_id] = owner
        room.seat_owners[owner.qq_id] = owner.qq_id
    seat_no = 1 + sum(1 for owner_id in room.seat_owners.values() if owner_id == owner.qq_id)
    seat_id = _new_debug_seat_id(room)
    room.players[seat_id] = User(
        qq_id=seat_id,
        nickname=f"{owner.nickname}-调试{seat_no}",
        group_id=group_id,
    )
    room.seat_owners[seat_id] = owner.qq_id
    await matcher.finish(_room_line(room))


_leave_room = on_command(
    "离开",
    aliases={"leave", "退出房间"},
    rule=to_me() & _PENDING_ROOM,
    priority=3,
    block=True,
)


@_leave_room.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    room = _stale_room(event)
    if room is None:
        return
    group_id = int(event.group_id)
    qq_id = int(event.user_id)
    for seat_id, owner_id in list(room.seat_owners.items()):
        if seat_id == qq_id or owner_id == qq_id:
            room.players.pop(seat_id, None)
            room.seat_owners.pop(seat_id, None)
    if not room.players:
        _rooms.pop(group_id, None)
        await matcher.finish("🌙 静夜标记房间已取消。")
        return
    if qq_id == room.host_id:
        # 房主走了就把房主顺延给下一个报名的人，房间不会因为房主跑了而卡死
        room.host_id = next(iter(room.players))
    await matcher.finish(_room_line(room))


_change_preset = on_command(
    "板子",
    aliases={"换板子", "preset"},
    rule=to_me() & _PENDING_ROOM,
    priority=3,
    block=True,
)


@_change_preset.handle()
async def _(
    matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    room = _stale_room(event)
    if room is None:
        return
    if int(event.user_id) != room.host_id:
        await matcher.finish("⚠️ 只有房主可以换板子。")
        return
    token = args.extract_plain_text().strip()
    if not token:
        options = "、".join(f"{m.name}[{m.id}]" for m in SilentMarkGame.MODES)
        await matcher.finish(f"用法：@我 板子 <板子>。可用：{options}")
        return
    preset = _preset_of(token)
    if preset is None:
        await matcher.finish("⚠️ 没有这个板子，@我 板子 可以看全部板子。")
        return
    if preset == "custom":
        await _apply_custom_board(matcher, room)
        return
    required = _required_players(preset)
    if len(room.players) > required:
        await matcher.finish(
            f"⚠️ {_preset_label(preset)} 只要 {required} 人，现在房间里有 {len(room.players)} 人。\n"
            "💡 先 @我 踢人 N 减到人数以内。"
        )
        return
    room.preset = preset
    await matcher.finish(_room_line(room))


async def _apply_custom_board(matcher: Matcher, room: PendingRoom) -> None:
    """跑一遍自定义向导，并把产物装进房间。

    向导全程在**私聊**里（群里不该出现"房主正在配板子"的问答刷屏），
    所以群里只在最后出一次结果。
    """
    board = await custom_setup.run_custom_wizard(room.host_id, timeout=None)
    if board is None:
        await matcher.finish("🛠 自定义板子已取消（没在私聊里走完向导）。")
        return
    if board.player_count < len(room.players):
        await matcher.finish(
            f"⚠️ 这套自定义板子只要 {board.player_count} 人，"
            f"现在房间里有 {len(room.players)} 人。\n"
            "💡 先 @我 踢人 N 减到人数以内，或者 @我 板子 自定义 重配一套。"
        )
        return
    room.preset = "custom"
    room.custom_roles = dict(board.roles)
    room.win_condition = board.win_condition
    room.items_enabled = board.items_enabled
    await matcher.finish(_room_line(room))


_items = on_command(
    "物品",
    aliases={"随身物品", "items"},
    rule=to_me() & _PENDING_ROOM,
    priority=3,
    block=True,
)


@_items.handle()
async def _(
    matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    room = _stale_room(event)
    if room is None:
        return
    if int(event.user_id) != room.host_id:
        await matcher.finish("⚠️ 只有房主可以改物品开关。")
        return
    token = args.extract_plain_text().strip().lower()
    if token in {"开", "on", "1", "true"}:
        room.items_enabled = True
    elif token in {"关", "off", "0", "false"}:
        room.items_enabled = False
    else:
        state = "开" if room.items_enabled else "关"
        await matcher.finish(f"用法：@我 物品 开 / @我 物品 关（当前：{state}）")
        return
    await matcher.finish(_room_line(room))


async def _test_ai() -> str:
    """`@我 AI 测试`：一次最小调用，确认 AI 链路真的通（而不是默默走兜底）。"""
    try:
        response = await llm.chat(
            [llm.LLMMessage(role="user", content="只回复两个字：可用")],
            scene="silent_mark_ai_name",
        )
    except _LLM_FAILURES as exc:
        return (
            f"⚠️ AI 不可用：{exc}\n"
            "（对局照样能开：AI 座位会自动走确定性兜底，只是不会「思考」）"
        )
    return f"🤖 AI 链路正常（{response.model}）：{response.content.strip()[:20]}"


_ai = on_command(
    "AI",
    aliases={"ai", "补位"},
    rule=to_me() & _PENDING_ROOM,
    priority=3,
    block=True,
)


@_ai.handle()
async def _(
    matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    room = _stale_room(event)
    if room is None:
        return
    if int(event.user_id) != room.host_id:
        await matcher.finish("⚠️ 只有房主可以改 AI 补位设置。")
        return
    token = args.extract_plain_text().strip().lower()
    if token in {"测试", "test"}:
        await matcher.finish(await _test_ai())
        return
    if token in {"开", "on", "1"}:
        room.ai_fill = True
    elif token in {"关", "off", "0"}:
        room.ai_fill = False
    else:
        gap = max(0, room.required_players - len(room.players))
        state = "开" if room.ai_fill else "关"
        await matcher.finish(
            f"🤖 AI 补位：{state}"
            + (f"（开局会补 {gap} 个座位）" if room.ai_fill and gap else "")
            + "\n用法：@我 AI 开 / @我 AI 关 / @我 AI 测试"
        )
        return
    await matcher.finish(_room_line(room))


_kick = on_command(
    "踢人",
    aliases={"kick"},
    rule=to_me() & _PENDING_ROOM,
    priority=3,
    block=True,
)


@_kick.handle()
async def _(
    matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()
) -> None:
    room = _stale_room(event)
    if room is None:
        return
    if int(event.user_id) != room.host_id:
        await matcher.finish("⚠️ 只有房主可以踢人。")
        return
    token = args.extract_plain_text().strip()
    if not token.isdigit():
        await matcher.finish("用法：@我 踢人 <编号>（编号见房间里的名单）")
        return
    index = int(token)
    ordered = list(room.players.values())
    if not 1 <= index <= len(ordered):
        await matcher.finish(f"⚠️ 编号要在 1~{len(ordered)} 之间。")
        return
    target = ordered[index - 1]
    for seat_id, owner_id in list(room.seat_owners.items()):
        if seat_id == target.qq_id or owner_id == target.qq_id:
            room.players.pop(seat_id, None)
            room.seat_owners.pop(seat_id, None)
    if not room.players:
        _rooms.pop(int(event.group_id), None)
        await matcher.finish("🌙 房间空了，已取消。")
        return
    if room.host_id not in room.players:
        room.host_id = next(iter(room.players))
    await matcher.finish(f"👢 已把 {target.nickname} 请出房间。\n\n" + _room_line(room))


# =====================================================================
# 开始
# =====================================================================
_begin_room = on_command(
    "开始",
    aliases={"发牌", "begin"},
    rule=to_me() & _PENDING_ROOM,
    priority=3,
    block=True,
)


@_begin_room.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    room = _stale_room(event)
    if room is None:
        return
    blocked = _start_blockers(room, int(event.user_id))
    if blocked is not None:
        await matcher.finish(blocked)
        return

    group_id = int(event.group_id)
    players = list(room.players.values())
    _rooms.pop(group_id, None)
    await _cancel_room_expiry(group_id)
    config: dict[str, object] = {
        "mode": room.preset,
        "items": room.items_enabled,
        # **默认 AI 补位**：人数不够就用 AI 填满（房主可 @我 AI 关 关掉）
        "ai_seats": (
            max(0, room.required_players - len(room.players))
            if room.ai_fill
            else 0
        ),
        "seat_owners": {
            str(seat_id): owner_id for seat_id, owner_id in room.seat_owners.items()
        },
    }
    if room.preset == "custom":
        # 自定义板子：把向导产物（角色表 + 胜负条件）一并交给游戏
        config.update(
            custom_setup.CustomBoard(
                roles=dict(room.custom_roles or {}),
                win_condition=room.win_condition,
                items_enabled=room.items_enabled,
            ).to_config()
        )
    try:
        await game_base.create_and_start(
            SilentMarkGame.id,
            group_id=group_id,
            host_id=room.host_id,
            players=players,
            config=config,
        )
    except GameAlreadyRunningError as e:
        await matcher.finish(f"⚠️ {e}")
    except Exception as e:  # noqa: BLE001
        await matcher.finish(f"⚠️ 静夜标记启动失败：{e}")


# =====================================================================
# 记录（本局玩家随时私聊查看）
# =====================================================================
_records = on_command(
    "记录",
    aliases={"我的记录", "my_records"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_records.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != SilentMarkGame.id:
        await matcher.finish("当前没有进行中的静夜标记。")
        return
    qq_id = int(event.user_id)
    pid = runner.game.pid_of(runner.ctx, qq_id)
    if pid is None:
        await matcher.finish("你不是本局玩家。")
        return
    # 群里的指令消息用完即撤（群里留干净），记录走私聊
    await session.delete_message(int(event.message_id))
    await session.whisper(qq_id, runner.game.my_records(runner.ctx, pid))
    matcher.stop_propagation()


# =====================================================================
# 复盘 / 面板（本局玩家随时可用）
# =====================================================================
async def _reply_with_pages(group_id: int, pages: list[str], *, label: str) -> None:
    """页数少就直接发，多了走**合并转发**。

    合并转发在这里比"分页"合适：复盘天然是"一条条看过去"的东西，
    转发消息在 QQ 里是可展开的一叠卡片，不会把群刷满。
    `session.send_forward` 自己带降级（转发失败会拆成多条广播）。
    """
    if len(pages) <= 2:
        for page in pages:
            await session.broadcast(group_id, page)
        return
    get_bot = getattr(session, "get_bot", None)
    uin = 0
    if get_bot is not None:
        try:
            uin = int(getattr(get_bot(), "self_id", 0) or 0)
        except (ValueError, RuntimeError, AttributeError):
            uin = 0
    await session.send_forward(
        group_id,
        [(uin, f"{label} · 第 {index} 页", page) for index, page in enumerate(pages, 1)],
        title=f"🌙 {label}",
    )


def _active_runner(group_id: int):
    runner = game_base.get_runner_by_group(group_id)
    if runner is None or runner.ctx.game_id != SilentMarkGame.id:
        return None
    return runner


_replay = on_command(
    "复盘",
    aliases={"回顾", "replay", "对局记录"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_replay.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    runner = _active_runner(group_id)
    if runner is None:
        await matcher.finish("当前没有进行中的静夜标记。")
        return
    # 群里的指令消息用完即撤（和 `记录` 一样，群里只留结果）
    await session.delete_message(int(event.message_id))
    await _reply_with_pages(group_id, runner.game.replay_pages(runner.ctx), label="静夜标记复盘")
    matcher.stop_propagation()


_panel = on_command(
    "面板",
    aliases={"看板", "局势", "board"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_panel.handle()
async def _(matcher: Matcher, event: GroupMessageEvent) -> None:
    group_id = int(event.group_id)
    runner = _active_runner(group_id)
    if runner is None:
        await matcher.finish("当前没有进行中的静夜标记。")
        return
    await session.delete_message(int(event.message_id))
    await runner.game.repost_board(runner.ctx)
    matcher.stop_propagation()
