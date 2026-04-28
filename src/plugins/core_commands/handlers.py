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


# -------------------- /ping --------------------
_ping = on_command("ping", priority=10, block=True)


@_ping.handle()
async def _(matcher: Matcher) -> None:
    await matcher.finish("pong 🏓")


# -------------------- /help --------------------
_help = on_command("help", aliases={"帮助"}, priority=10, block=True)

HELP_TEXT = render.text_card(
    "使用帮助",
    [
        "🎮 /menu       查看游戏大厅",
        "🎮 /games      同 /menu",
        "🎮 /play <id>  开始一局游戏",
        "🏳 /quit       终止当前群内的游戏",
        "📊 /profile    查看个人信息",
        "💰 /balance    查看金币余额",
        "🏓 /ping       测试机器人是否在线",
        "📜 /help       显示本帮助",
    ],
    emoji="📜",
    footer="海龟汤：/play turtle_soup",
)


@_help.handle()
async def _(matcher: Matcher) -> None:
    await matcher.finish(HELP_TEXT)


# -------------------- /menu & /games --------------------
_menu = on_command("menu", aliases={"games", "大厅", "游戏"}, priority=10, block=True)


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
                subtitle=f"{g.min_players}-{g.max_players} 人 · {g.description}"
                if g.description
                else f"{g.min_players}-{g.max_players} 人",
                command=f"/play {g.id}",
            )
        )

    # 个人金币
    qq_id = int(event.user_id)
    coin = await economy.balance(qq_id, "coin")
    footer = [f"💰 金币：{coin}", "📜 /help 查看帮助"]

    await matcher.finish(render.menu("游戏大厅", items, footer=footer))


# -------------------- /profile --------------------
_profile = on_command("profile", aliases={"我的", "资料"}, priority=10, block=True)


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


# -------------------- /balance --------------------
_balance = on_command("balance", aliases={"金币", "余额"}, priority=10, block=True)


@_balance.handle()
async def _(matcher: Matcher, event: MessageEvent, args: Message = CommandArg()) -> None:
    qq_id = int(event.user_id)
    currency = args.extract_plain_text().strip() or "coin"
    amount = await economy.balance(qq_id, currency)
    await matcher.finish(f"💰 {currency}：{amount}")
