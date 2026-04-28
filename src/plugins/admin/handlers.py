"""管理员指令：/admin grant /admin revoke /admin coin /admin reload"""

from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from core import economy, permission

_admin = on_command("admin", priority=5, block=True)


HELP = (
    "/admin grant <qq>     授予管理员\n"
    "/admin revoke <qq>    撤销管理员\n"
    "/admin coin <qq> <n>  调整金币（可负）\n"
    "/admin check <qq>     查询用户状态\n"
)


@_admin.handle()
async def _(
    matcher: Matcher,
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    qq_id = int(event.user_id)
    if not await permission.is_admin(qq_id):
        await matcher.finish("🔒 需要管理员权限")
        return

    parts = args.extract_plain_text().strip().split()
    if not parts:
        await matcher.finish(HELP)
        return

    sub = parts[0]
    rest = parts[1:]

    if sub == "grant" and len(rest) == 1:
        target = int(rest[0])
        await permission.grant_admin(target, granted_by=qq_id)
        await matcher.finish(f"✅ 已授予 {target} 管理员权限")

    elif sub == "revoke" and len(rest) == 1:
        target = int(rest[0])
        await permission.revoke_admin(target)
        await matcher.finish(f"✅ 已撤销 {target} 的管理员权限")

    elif sub == "coin" and len(rest) == 2:
        target = int(rest[0])
        delta = int(rest[1])
        if delta >= 0:
            new_bal = await economy.add(target, delta, reason=f"admin_grant_by_{qq_id}")
        else:
            new_bal = await economy.add(target, delta, reason=f"admin_deduct_by_{qq_id}")
        await matcher.finish(f"✅ {target} 金币 {delta:+d} → {new_bal}")

    elif sub == "check" and len(rest) == 1:
        target = int(rest[0])
        coin = await economy.balance(target, "coin")
        items = await economy.list_items(target)
        is_adm = await permission.is_admin(target)
        lines = [
            f"QQ：{target}",
            f"管理员：{'是' if is_adm else '否'}",
            f"金币：{coin}",
            f"道具：{len(items)} 种",
        ]
        await matcher.finish("\n".join(lines))

    else:
        await matcher.finish(HELP)
