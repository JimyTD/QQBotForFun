"""系统通用指令：/help /menu /profile /balance /ping"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message

from core import economy, render, user
from core.game_base import list_games
from core.render import MenuItem


# -------------------- /测试 --------------------
_ping = on_command("测试", aliases={"ping"}, priority=10, block=True)


@_ping.handle()
async def _(matcher: Matcher) -> None:
    await matcher.finish("pong 🏓")


# -------------------- /帮助 --------------------
_help = on_command("帮助", aliases={"help", "说明"}, priority=10, block=True)

HELP_TEXT = render.text_card(
    "使用帮助",
    [
        "🎮 /开始       选择游戏开始（引导式）",
        "🎮 /开始 <ID>  跳过选游戏直接进模式选择",
        "🎮 /开始 <ID> <模式>  两步都跳过直接开局",
        "📋 /菜单       查看游戏大厅",
        "🏳 /结束       终止当前群内的游戏或选择",
        "📊 /资料       查看个人信息",
        "💰 /金币       查看金币余额",
        "🏓 /测试       测试机器人是否在线",
        "📜 /帮助       显示本帮助",
    ],
    emoji="📜",
    footer="游戏进行中 @机器人 + 数字 可做选择",
)


@_help.handle()
async def _(matcher: Matcher) -> None:
    await matcher.finish(HELP_TEXT)


# -------------------- /菜单 --------------------
_menu = on_command(
    "菜单",
    aliases={"menu", "games", "大厅", "游戏"},
    priority=10,
    block=True,
)


@_menu.handle()
async def _(matcher: Matcher, event: MessageEvent) -> None:
    games = list_games()
    if not games:
        await matcher.finish("🎮 大厅暂无可用游戏")
        return

    items: list[MenuItem] = []
    for g in games:
        emoji = getattr(g, "emoji", "🎮")
        items.append(
            MenuItem(
                emoji=emoji,
                name=g.name,
                subtitle=(
                    f"{g.min_players}-{g.max_players} 人 · {g.description}"
                    if g.description
                    else f"{g.min_players}-{g.max_players} 人"
                ),
                command=f"/开始 {g.id}",
            )
        )

    # 个人金币
    qq_id = int(event.user_id)
    coin = await economy.balance(qq_id, "coin")
    footer = [
        f"💰 金币：{coin}",
        "🎮 开始游戏：/开始",
        "📜 /帮助 查看帮助",
    ]

    await matcher.finish(render.menu("游戏大厅", items, footer=footer))


# -------------------- /资料 --------------------
_profile = on_command("资料", aliases={"profile", "我的"}, priority=10, block=True)


@_profile.handle()
async def _(matcher: Matcher, event: MessageEvent) -> None:
    qq_id = int(event.user_id)
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    u = await user.get(qq_id, group_id)
    coin = await economy.balance(qq_id, "coin")
    items = await economy.list_items(qq_id)

    lines = [
        f"昵称：{u.nickname}",
        f"QQ  ：{qq_id}",
        "",
        f"💰 金币：{coin}",
    ]
    if items:
        lines.append("🎒 道具：")
        for item_id, count in items.items():
            lines.append(f"  · {item_id} × {count}")
    else:
        lines.append("🎒 道具：（空）")

    await matcher.finish(render.text_card("个人资料", lines, emoji="📊"))


# -------------------- /金币 --------------------
_balance = on_command("金币", aliases={"balance", "余额"}, priority=10, block=True)


@_balance.handle()
async def _(matcher: Matcher, event: MessageEvent, args: Message = CommandArg()) -> None:
    qq_id = int(event.user_id)
    currency = args.extract_plain_text().strip() or "coin"
    amount = await economy.balance(qq_id, currency)
    await matcher.finish(f"💰 {currency}：{amount}")
