"""系统通用指令：/help /menu /profile /balance /ping /榜"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message
from nonebot.rule import to_me

from core import economy, render, user
from core.game_base import list_games
from core.render import MenuItem


# -------------------- /测试 --------------------
_ping = on_command("测试", aliases={"ping"}, rule=to_me(), priority=3, block=True)


@_ping.handle()
async def _(matcher: Matcher) -> None:
    await matcher.finish("pong 🏓")


# -------------------- /帮助 --------------------
_help = on_command("帮助", aliases={"help", "说明"}, rule=to_me(), priority=3, block=True)

HELP_TEXT = render.text_card(
    "使用帮助",
    [
        "所有指令都需要 @我",
        "",
        "🎮 @我 海龟汤      快速开一局海龟汤",
        "🎮 @我 趣味问答    快速开一局趣味问答（随机类型）",
        "⚔️ @我 斗蛐蛐      帝国3兵种对战（押注模式）",
        "⚔️ @我 斗蛐蛐 单挑  帝国3兵种 1v1",
        "⚔️ @我 斗蛐蛐 2000  自定义资源（1000-5000）",
        "",
        "游戏中：",
        "💬 @我 你的问题    直接提问（海龟汤）",
        "💬 @我 汤底:答案   宣告答案（海龟汤）",
        "🔮 @我 提示        花金币买一条关键线索",
        "📊 @我 状态        查看进度",
        "🐢 @我 汤面        重新查看题面（海龟汤）",
        "📜 @我 回顾        关键线索回顾（海龟汤）",
        "🎲 @我 1 / @我 2   押注红/蓝方（斗蛐蛐）",
        "⚔️ @我 开战        跳过等待直接开打（斗蛐蛐）",
        "🏳 @我 结束        投降 / 终止游戏",
        "",
        "其他：",
        "📋 @我 菜单        游戏大厅",
        "📊 @我 资料        个人信息",
        "💰 @我 金币        金币余额",
        "🏆 @我 榜          积分榜 TOP 10",
        "🍱 @我 吃什么      今天吃什么",
        "🃏 @我 查卡 卡名    游戏王卡片查询",
        "🃏 @我 随机卡       随机一张游戏王卡",
        "🏰 @我 aoe3 兵种名  帝国时代3兵种查询",
        "🏰 @我 aoe3 对比 A B 兵种对比",
        "🏰 @我 aoe3 克制 类型 克制查询",
        "🏰 @我 aoe3 文明 名称 文明兵种",
        "🔍 @我 查资料 问题  联网搜索+AI回答",
        "🏓 @我 测试        测试是否在线",
    ],
    emoji="📜",
)


@_help.handle()
async def _(matcher: Matcher) -> None:
    await matcher.finish(HELP_TEXT)


# -------------------- /菜单 --------------------
_menu = on_command(
    "菜单",
    aliases={"menu", "games", "大厅", "游戏"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_menu.handle()
async def _(matcher: Matcher, event: MessageEvent) -> None:
    # 游戏 ID → 快捷开局指令的映射
    _QUICK_CMD: dict[str, str] = {
        "turtle_soup": "@我 海龟汤",
        "trivia": "@我 趣味问答",
        "aoe3_battle": "@我 斗蛐蛐",
    }

    games = list_games()
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
                command=_QUICK_CMD.get(g.id, f"@我 {g.name}"),
            )
        )

    # —— 小工具区（非游戏） ——
    items.append(
        MenuItem(
            emoji="🍱",
            name="今天吃什么",
            subtitle="选择困难症一键甩锅 · 小工具",
            command="@我 吃什么",
        )
    )
    items.append(
        MenuItem(
            emoji="🃏",
            name="游戏王查卡",
            subtitle="查卡片信息 · 小工具",
            command="@我 查卡 卡名",
        )
    )
    items.append(
        MenuItem(
            emoji="🏰",
            name="帝国时代3百科",
            subtitle="AoE3 兵种查询/对比/克制 · 小工具",
            command="@我 aoe3 兵种名",
        )
    )

    if not items:
        await matcher.finish("🎮 大厅暂无可用游戏")
        return

    # 个人金币
    qq_id = int(event.user_id)
    coin = await economy.balance(qq_id, "coin")
    footer = [
        f"💰 金币：{coin}",
        "🎮 开始游戏：@我 海龟汤 / @我 趣味问答 / @我 斗蛐蛐",
        "📜 @我 帮助 查看帮助",
    ]

    await matcher.finish(render.menu("游戏大厅", items, footer=footer))


# -------------------- /资料 --------------------
_profile = on_command("资料", aliases={"profile", "我的资料", "个人资料"}, rule=to_me(), priority=3, block=True)


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
_balance = on_command("金币", aliases={"balance", "余额"}, rule=to_me(), priority=3, block=True)


@_balance.handle()
async def _(matcher: Matcher, event: MessageEvent, args: Message = CommandArg()) -> None:
    qq_id = int(event.user_id)
    currency = args.extract_plain_text().strip() or "coin"
    amount = await economy.balance(qq_id, currency)
    await matcher.finish(f"💰 {currency}：{amount}")


# -------------------- /榜 --------------------
# 跨游戏通用的积分榜。默认查 score（趣味问答等游戏的积分货币）。
#   /榜                    → score 榜 TOP 10
#   /榜 score              → 同上
#   /榜 coin               → 金币榜 TOP 10
#   /榜 我                 → 查自己 score + coin 排名
#   /榜 我 coin            → 查自己指定货币排名
_CURRENCY_LABELS: dict[str, tuple[str, str]] = {
    # currency_id → (显示名, emoji)
    "score": ("趣味分", "🏆"),
    "coin": ("金币", "💰"),
    "ticket": ("入场券", "🎟"),
}

_LEADERBOARD_TOP_LIMIT = 10


def _currency_label(currency: str) -> tuple[str, str]:
    return _CURRENCY_LABELS.get(currency, (currency, "🏅"))


async def _format_top(currency: str, viewer_qq_id: int) -> str:
    label, emoji = _currency_label(currency)
    entries = await economy.top_balances(currency, limit=_LEADERBOARD_TOP_LIMIT)

    if not entries:
        return render.text_card(
            f"{label}榜 · TOP {_LEADERBOARD_TOP_LIMIT}",
            ["（暂时还没有人上榜）"],
            emoji=emoji,
            footer="多玩几局游戏就能上榜咯~",
        )

    # 查昵称（批量，带缓存）
    users = await user.get_many([e.qq_id for e in entries])
    nick_map = {u.qq_id: u.nickname for u in users}

    lines: list[str] = []
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for e in entries:
        medal = medals.get(e.rank, f" {e.rank:>2}.")
        nick = nick_map.get(e.qq_id, str(e.qq_id))
        tag = " ← 你" if e.qq_id == viewer_qq_id else ""
        lines.append(f"{medal} {nick:<12} {e.balance:>6} {label}{tag}")

    footer_lines: list[str] = []
    viewer_in_top = any(e.qq_id == viewer_qq_id for e in entries)
    if not viewer_in_top:
        rank, bal = await economy.rank_of(viewer_qq_id, currency)
        if rank is not None:
            footer_lines.append(f"你：#{rank}（{bal} {label}）")
        elif bal > 0:
            footer_lines.append(f"你：{bal} {label}（未入榜）")
        else:
            footer_lines.append(f"你：0 {label}（未入榜，快去玩游戏吧）")

    total = await economy.count_in_leaderboard(currency)
    footer_lines.append(f"全服上榜人数：{total}")

    return render.text_card(
        f"{label}榜 · TOP {_LEADERBOARD_TOP_LIMIT}",
        lines,
        emoji=emoji,
        footer=footer_lines,
    )


async def _format_self(qq_id: int, specified: str | None) -> str:
    """/榜 我 [currency]"""
    # 没指定货币时，默认展示 score + coin 两个
    currencies: list[str] = (
        [specified] if specified else ["score", "coin"]
    )
    u = await user.get(qq_id)
    lines: list[str] = [f"昵称：{u.nickname}"]
    lines.append("")
    for cur in currencies:
        label, emoji = _currency_label(cur)
        rank, bal = await economy.rank_of(qq_id, cur)
        if rank is None:
            lines.append(f"{emoji} {label}：{bal}（未入榜）")
        else:
            lines.append(f"{emoji} {label}：{bal}（全服 #{rank}）")
    return render.text_card("我的排名", lines, emoji="📊")


_leaderboard = on_command(
    "榜",
    aliases={"rank", "排行", "排行榜", "leaderboard"},
    rule=to_me(),
    priority=3,
    block=True,
)


@_leaderboard.handle()
async def _(
    matcher: Matcher,
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    qq_id = int(event.user_id)
    raw = args.extract_plain_text().strip()
    tokens = raw.split() if raw else []

    # 空参数 → score 全局榜
    if not tokens:
        await matcher.finish(await _format_top("score", qq_id))
        return

    first = tokens[0].lower()

    # /榜 我 [currency]
    if first in ("我", "self", "me"):
        specified = tokens[1].lower() if len(tokens) > 1 else None
        if specified is not None and not economy.is_registered(specified):
            await matcher.finish(
                f"⚠️ 未知货币「{specified}」。可用：{'、'.join(sorted(_CURRENCY_LABELS))}"
            )
            return
        await matcher.finish(await _format_self(qq_id, specified))
        return

    # /榜 <currency>
    currency = first
    if not economy.is_registered(currency):
        await matcher.finish(
            f"⚠️ 未知货币「{currency}」。可用：{'、'.join(sorted(_CURRENCY_LABELS))}\n"
            f"或 @我 榜 我 查自己的排名"
        )
        return
    await matcher.finish(await _format_top(currency, qq_id))
