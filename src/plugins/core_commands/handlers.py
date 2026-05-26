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

_SCOPE_GLOBAL = "全服"
_SCOPE_GROUP = "本群"


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
        "━━━ 🎮 开始游戏 ━━━",
        "海龟汤          情景推理（AI主持）",
        "趣味问答        六类线索猜答案",
        "斗蛐蛐          帝国3兵种对战押注",
        "红警斗蛐蛐      红警2兵种对战（OpenRA数据）",
        "",
        "━━━ 🐢 海龟汤 ━━━",
        "直接提问        向汤主提问",
        "汤底:答案       宣告最终答案",
        "提示            花金币买关键线索",
        "汤面            重看题面",
        "回顾            已获线索回顾",
        "状态            查看当前进度",
        "结束            投降终止",
        "",
        "━━━ ⚔️ 斗蛐蛐 ━━━",
        "斗蛐蛐          押注模式（群殴，默认）",
        "斗蛐蛐 单挑     1v1 模式",
        "斗蛐蛐 乱斗     黑名单乱斗（怪物/英雄互殴）",
        "斗蛐蛐 5000     自定义资源（1000-50000，默认10000）",
        "斗蛐蛐自选 兵种  自选1-2个兵种对决",
        "红警斗蛐蛐      红警2押注（默认预算5000）",
        "红警斗蛐蛐 单挑 红警2 1v1",
        "红警斗蛐蛐 3000 自定义造价（500-50000）",
        "1 / 2           押注红/蓝方",
        "开战            跳过等待直接开打",
        "结束            终止对局",
        "",
        "━━━ 🔍 信息查询 ━━━",
        "查资料 问题     联网搜索+AI回答",
        "aoe3 兵种名     帝国3兵种查询",
        "aoe3 对比 A B   兵种对比",
        "aoe3 文明 名称  文明兵种一览",
        "查卡 卡名       游戏王卡片查询",
        "随机卡          随机一张游戏王卡",
        "",
        "━━━ 🛠️ 日常工具 ━━━",
        "签到            每日签到领金币",
        "吃什么          今天吃什么",
        "菜单            游戏大厅",
        "",
        "━━━ ⚙️ 个人中心 ━━━",
        "资料            个人信息",
        "榜              积分榜 TOP 10",
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
        "ra2_battle": "@我 红警斗蛐蛐",
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
    items.append(
        MenuItem(
            emoji="📅",
            name="每日签到",
            subtitle="每天签到领金币 + 积分，连续签到有加成",
            command="@我 签到",
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
        "🎮 开始游戏：@我 海龟汤 / @我 趣味问答 / @我 斗蛐蛐 / @我 红警斗蛐蛐",
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

    # 签到信息
    try:
        from src.plugins.tools.checkin.storage import get_checkin_record

        checkin = await get_checkin_record(qq_id)
    except Exception:
        checkin = None

    lines = [
        f"昵称：{u.nickname}",
        f"QQ  ：{qq_id}",
        "",
        f"💰 金币：{coin}",
    ]

    # 签到区
    if checkin is not None:
        lines.append(f"📅 连续签到：{checkin.streak} 天")
        lines.append(f"📅 累计签到：{checkin.total_checkins} 天")
    else:
        lines.append("📅 签到：尚未签到（@我 签到）")

    lines.append("")
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


async def _get_group_member_ids(group_id: int | None) -> set[int] | None:
    """获取群成员 qq_id 集合；私聊或获取失败时返回 None（回退全局）。"""
    if group_id is None:
        return None
    members = await user.get_group_members(group_id)
    if not members:
        return None
    return {m.qq_id for m in members}


async def _format_top(
    currency: str, viewer_qq_id: int, *, among: set[int] | None = None
) -> str:
    scope = _SCOPE_GROUP if among else _SCOPE_GLOBAL
    label, emoji = _currency_label(currency)
    entries = await economy.top_balances(
        currency, limit=_LEADERBOARD_TOP_LIMIT, among=among
    )

    if not entries:
        return render.text_card(
            f"{label}榜 · {scope} TOP {_LEADERBOARD_TOP_LIMIT}",
            ["（暂时还没有人上榜）"],
            emoji=emoji,
            footer="多玩几局游戏就能上榜咯~",
        )

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
        rank, bal = await economy.rank_of(viewer_qq_id, currency, among=among)
        if rank is not None:
            footer_lines.append(f"你：#{rank}（{bal} {label}）")
        elif bal > 0:
            footer_lines.append(f"你：{bal} {label}（未入榜）")
        else:
            footer_lines.append(f"你：0 {label}（未入榜，快去玩游戏吧）")

    total = await economy.count_in_leaderboard(currency, among=among)
    footer_lines.append(f"{scope}上榜人数：{total}")

    return render.text_card(
        f"{label}榜 · {scope} TOP {_LEADERBOARD_TOP_LIMIT}",
        lines,
        emoji=emoji,
        footer=footer_lines,
    )


async def _format_self(
    qq_id: int, specified: str | None, *, among: set[int] | None = None
) -> str:
    """/榜 我 [currency]"""
    scope = _SCOPE_GROUP if among else _SCOPE_GLOBAL
    currencies: list[str] = (
        [specified] if specified else ["score", "coin"]
    )
    u = await user.get(qq_id)
    lines: list[str] = [f"昵称：{u.nickname}"]
    lines.append("")
    for cur in currencies:
        label, emoji = _currency_label(cur)
        rank, bal = await economy.rank_of(qq_id, cur, among=among)
        if rank is None:
            lines.append(f"{emoji} {label}：{bal}（未入榜）")
        else:
            lines.append(f"{emoji} {label}：{bal}（{scope} #{rank}）")
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
    group_id = event.group_id if isinstance(event, GroupMessageEvent) else None
    among = await _get_group_member_ids(group_id)

    raw = args.extract_plain_text().strip()
    tokens = raw.split() if raw else []

    if not tokens:
        await matcher.finish(await _format_top("score", qq_id, among=among))
        return

    first = tokens[0].lower()

    if first in ("我", "self", "me"):
        specified = tokens[1].lower() if len(tokens) > 1 else None
        if specified is not None and not economy.is_registered(specified):
            await matcher.finish(
                f"⚠️ 未知货币「{specified}」。可用：{'、'.join(sorted(_CURRENCY_LABELS))}"
            )
            return
        await matcher.finish(await _format_self(qq_id, specified, among=among))
        return

    currency = first
    if not economy.is_registered(currency):
        await matcher.finish(
            f"⚠️ 未知货币「{currency}」。可用：{'、'.join(sorted(_CURRENCY_LABELS))}\n"
            f"或 @我 榜 我 查自己的排名"
        )
        return
    await matcher.finish(await _format_top(currency, qq_id, among=among))
