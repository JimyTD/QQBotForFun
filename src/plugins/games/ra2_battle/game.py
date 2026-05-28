"""红警2斗蛐蛐 —— 群玩法（押注规则对齐 aoe3_battle，面板为红警 OpenRA 简介）。"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from core import economy, session
from core.errors import InsufficientFundsError
from core.game_base import GameBase, GameMode, register_game
from core.group_config import get_group_config
from core.types import EndReason, GameContext

from .broadcaster import (
    BROADCAST_MODE_CONFIG_KEY,
    MODE_BRIEF,
    Broadcaster,
    format_battle_report,
)
from .lineup import (
    BUDGET_DEFAULT,
    BUDGET_MAX,
    BUDGET_MIN,
    MatchLineup,
    SideLineup,
    format_side_panel,
    format_vs_banner,
    generate_bet_lineup,
    generate_duel_lineup,
)
from .simulator import BattleSimulator

logger = logging.getLogger("ra2_battle.game")

ENTRY_FEE = 5
PARTICIPATION_REWARD = 1
BROADCAST_SLEEP = 2.0


async def _broadcast_side_panel(
    group_id: int,
    side: SideLineup,
    *,
    color: str,
    mode: str,
    initial_stars: int,
) -> None:
    """发送单方阵容：每个兵种 icon 单独一条消息，再发文字详情。

    NapCat 对「多图 + 长文」合成一条消息易失败并静默降级为纯文本；
    拆开发送更稳，也与帝国斗蛐蛐「先看头像再看属性」的阅读顺序一致。
    """
    import base64

    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    from .icons import get_icon_path

    missing: list[str] = []
    sent = 0
    for slot in side.slots:
        icon_path = get_icon_path(slot.actor_id)
        if icon_path is None:
            missing.append(slot.actor_id)
            continue
        b64 = base64.b64encode(icon_path.read_bytes()).decode()
        img_msg = Message(MessageSegment.image(f"base64://{b64}"))
        try:
            await session.broadcast(group_id, img_msg)
            sent += 1
        except Exception:
            logger.warning(
                "[ra2_battle] icon 发送失败 side=%s actor=%s path=%s",
                color, slot.actor_id, icon_path,
                exc_info=True,
            )

    text = format_side_panel(side, color, mode, initial_stars=initial_stars)
    await session.broadcast(group_id, text)

    logger.info(
        "[ra2_battle] 面板 %s icons=%d/%d missing=%s",
        color, sent, len(side.slots), missing or "-",
    )
    if missing:
        logger.warning(
            "[ra2_battle] 缺 PNG（resources/ra2/icons/{{id}}.png）: %s",
            ", ".join(missing),
        )


@register_game
class Ra2BattleGame(GameBase):
    """红警2斗蛐蛐（OpenRA 数据 · 二维战场）。"""

    id = "ra2_battle"
    name = "红警2斗蛐蛐"
    description = "OpenRA 数据 · 二维空旷战场 · 押注 / 单挑"
    min_players = 0
    max_players = 50
    version = "0.2"
    serialize_actions = False
    event_driven = True

    MODES = [
        GameMode(
            id="bet",
            name="押注模式",
            description="随机双方阵容，二维对冲",
            aliases=("红警斗蛐蛐", "红警", "默认"),
        ),
        GameMode(
            id="duel",
            name="单挑模式",
            description="随机两种单位各 1 个",
            aliases=("红警单挑", "红警1v1"),
        ),
    ]

    async def on_create(self, ctx: GameContext) -> None:
        mode_id = (ctx.config or {}).get("mode", "bet")
        budget = int((ctx.config or {}).get("budget", BUDGET_DEFAULT))
        budget = max(BUDGET_MIN, min(BUDGET_MAX, budget))
        rng = random.Random()

        if mode_id == "duel":
            match = generate_duel_lineup(rng=rng)
        else:
            match = generate_bet_lineup(budget=budget, rng=rng)

        if "initial_stars" in (ctx.config or {}):
            initial_stars = int(ctx.config["initial_stars"])
            if initial_stars not in (0, 1, 3):
                initial_stars = match.initial_stars
        else:
            initial_stars = match.initial_stars

        ctx.state.update(
            mode=mode_id,
            phase="betting",
            budget=budget,
            initial_stars=initial_stars,
            red_army=[
                {"actor_id": s.actor_id, "name": s.name, "count": s.count}
                for s in match.red.slots
            ],
            blue_army=[
                {"actor_id": s.actor_id, "name": s.name, "count": s.count}
                for s in match.blue.slots
            ],
            bets={},
        )
        self._match: MatchLineup = match
        self._battle_task: asyncio.Task[Any] | None = None

    async def on_start(self, ctx: GameContext) -> None:
        match = self._match
        mode = ctx.state["mode"]
        stars = int(ctx.state.get("initial_stars", 0))

        await _broadcast_side_panel(
            ctx.group_id, match.red,
            color="red", mode=mode, initial_stars=stars,
        )
        await _broadcast_side_panel(
            ctx.group_id, match.blue,
            color="blue", mode=mode, initial_stars=stars,
        )

        await session.broadcast(ctx.group_id, format_vs_banner(match))
        logger.info(
            "[ra2_battle] 对局 %s 开始 mode=%s 🔴 %s vs 🔵 %s",
            ctx.session_id,
            mode,
            ctx.state["red_army"],
            ctx.state["blue_army"],
        )

    async def on_player_action(
        self, ctx: GameContext, player_id: int, message: str
    ) -> bool:
        text = message.strip()
        if ctx.state.get("phase") == "betting":
            return await self._handle_betting(ctx, player_id, text)
        return False

    def in_game_hint(self, ctx: GameContext) -> str:
        phase = ctx.state.get("phase", "ended")
        if phase == "fighting":
            return (
                "⚔️ 红警斗蛐蛐战斗进行中，请稍候…\n"
                "💡 播报结束后 @我 结束 可开新局"
            )
        return (
            "⚔️ 红警斗蛐蛐押注中\n"
            "💡 @我 押注1 / 押注2 / 开战\n"
            "💡 @我 结束 可终止本局"
        )

    async def on_timeout(self, ctx: GameContext) -> None:
        if ctx.state.get("phase") == "betting":
            await session.broadcast(ctx.group_id, "⏱ 红警斗蛐蛐超时，本局结束。")

    async def on_end(self, ctx: GameContext, reason: EndReason) -> None:
        logger.info("[ra2_battle] 对局 %s 结束 reason=%s", ctx.session_id, reason.value)

    async def _handle_betting(
        self, ctx: GameContext, player_id: int, text: str
    ) -> bool:
        bets: dict[str, str] = ctx.state.get("bets", {})
        pid_str = str(player_id)

        if text == "押注1":
            if pid_str in bets:
                await session.broadcast(
                    ctx.group_id,
                    "⚠️ 你已经押过了（锁死第一笔）",
                    at=player_id,
                )
                return True
            if not await self._charge_entry_fee(ctx, player_id):
                return True
            bets[pid_str] = "red"
            ctx.state["bets"] = bets
            await session.broadcast(
                ctx.group_id,
                f"✅ 押了 🔴 红方（1号），入场券 {ENTRY_FEE} 金币已扣除",
                at=player_id,
            )
            logger.info("[ra2_battle] %s 玩家 %d 押注红方", ctx.session_id, player_id)
            return True

        if text == "押注2":
            if pid_str in bets:
                await session.broadcast(
                    ctx.group_id,
                    "⚠️ 你已经押过了（锁死第一笔）",
                    at=player_id,
                )
                return True
            if not await self._charge_entry_fee(ctx, player_id):
                return True
            bets[pid_str] = "blue"
            ctx.state["bets"] = bets
            await session.broadcast(
                ctx.group_id,
                f"✅ 押了 🔵 蓝方（2号），入场券 {ENTRY_FEE} 金币已扣除",
                at=player_id,
            )
            logger.info("[ra2_battle] %s 玩家 %d 押注蓝方", ctx.session_id, player_id)
            return True

        if text == "开战":
            await self._start_battle(ctx)
            return True

        return False

    async def _charge_entry_fee(self, ctx: GameContext, player_id: int) -> bool:
        try:
            await economy.deduct(
                player_id,
                ENTRY_FEE,
                reason=f"ra2_battle_entry:{ctx.session_id}",
                currency="coin",
            )
            return True
        except InsufficientFundsError:
            await session.broadcast(
                ctx.group_id,
                f"⚠️ 金币不足（需要 {ENTRY_FEE} 金币入场券）",
                at=player_id,
            )
            return False

    async def _start_battle(self, ctx: GameContext) -> None:
        if ctx.state.get("phase") != "betting":
            return
        ctx.state["phase"] = "fighting"
        bets = ctx.state.get("bets", {})
        if bets:
            await session.broadcast(
                ctx.group_id,
                f"🎲 押注截止！共 {len(bets)} 人参与",
            )
        else:
            await session.broadcast(ctx.group_id, "🎲 无人押注，直接开打！")
        self._battle_task = asyncio.create_task(self._run_battle(ctx))

    async def _run_battle(self, ctx: GameContext) -> None:
        try:
            match = self._match
            stars = int(ctx.state.get("initial_stars", 0))
            if stars not in (0, 1, 3):
                stars = 0
            red = [(s.actor_id, s.count, stars) for s in match.red.slots]
            blue = [(s.actor_id, s.count, stars) for s in match.blue.slots]

            t0 = time.perf_counter()
            result = BattleSimulator(red, blue).run()
            sim_ms = (time.perf_counter() - t0) * 1000
            logger.info(
                "[ra2_battle] %s 模拟完成 ticks=%d 耗时=%.1fms 胜=%s",
                ctx.session_id,
                result.ticks,
                sim_ms,
                result.winner.value if result.winner else "draw",
            )

            bc = Broadcaster(
                result,
                mode=await get_group_config(
                    ctx.group_id, BROADCAST_MODE_CONFIG_KEY, default=MODE_BRIEF
                ),
            )
            for seg in bc.generate():
                await session.broadcast(ctx.group_id, seg.text)
                if seg.should_sleep:
                    await asyncio.sleep(BROADCAST_SLEEP)

            report = format_battle_report(result)
            settlement = await self._settle_bets(ctx, result)
            full = f"{report}\n\n{settlement}" if settlement else report
            await session.broadcast(ctx.group_id, full)

            ctx.state["phase"] = "ended"
            from core import game_base as gb

            runner = gb.get_runner(ctx.session_id)
            if runner is not None:
                await runner.end(EndReason.COMPLETED)
        except asyncio.CancelledError:
            logger.info("[ra2_battle] %s 战斗任务被取消", ctx.session_id)
        except Exception as e:
            logger.exception("[ra2_battle] %s 战斗执行出错: %s", ctx.session_id, e)
            try:
                await session.broadcast(ctx.group_id, f"⚠️ 战斗模拟出错：{e}")
            except Exception:
                pass
            ctx.state["phase"] = "ended"
            from core import game_base as gb

            runner = gb.get_runner(ctx.session_id)
            if runner is not None:
                await runner.end(EndReason.ERROR)

    async def _settle_bets(self, ctx: GameContext, result) -> str:
        """与 aoe3_battle 完全一致的押注结算。"""
        bets: dict[str, str] = ctx.state.get("bets", {})
        if not bets:
            return ""

        winner_side = result.winner.value if result.winner else None
        lines = ["━━━ 押注结算 ━━━"]

        if winner_side is None:
            for pid_str in bets:
                await self.award(
                    int(pid_str),
                    ENTRY_FEE,
                    reason=f"ra2_battle_refund:{ctx.session_id}",
                    currency="coin",
                )
            lines.append("平局！入场券全额退还")
            for pid_str in bets:
                await self.award(
                    int(pid_str),
                    PARTICIPATION_REWARD,
                    reason=f"ra2_battle_participate:{ctx.session_id}",
                    currency="coin",
                )
            lines.append(f"全员参与奖：+{PARTICIPATION_REWARD} 金币")
            return "\n".join(lines)

        winners = [int(k) for k, v in bets.items() if v == winner_side]
        losers = [int(k) for k, v in bets.items() if v != winner_side]
        loser_pool = len(losers) * ENTRY_FEE

        if winners and losers:
            per_winner = loser_pool // len(winners)
            remainder = loser_pool % len(winners)
            for pid in winners:
                await self.award(
                    pid,
                    ENTRY_FEE + per_winner,
                    reason=f"ra2_battle_win:{ctx.session_id}",
                    currency="coin",
                )
            if remainder > 0:
                await self.award(
                    winners[0],
                    remainder,
                    reason=f"ra2_battle_win_remainder:{ctx.session_id}",
                    currency="coin",
                )
            winner_emoji = "🔴" if winner_side == "red" else "🔵"
            winner_label = "红方" if winner_side == "red" else "蓝方"
            if len(winners) <= 5:
                winner_mentions = " ".join(f"@{pid}" for pid in winners)
            else:
                winner_mentions = (
                    " ".join(f"@{pid}" for pid in winners[:5])
                    + f" 等 {len(winners)} 人"
                )
            lines.append(
                f"押对 {winner_emoji}{winner_label}：{winner_mentions}（{len(winners)} 人）"
            )
            lines.append(f"每人 +{per_winner + ENTRY_FEE} 金币（含退还入场券）")
            lines.append(f"押错：{len(losers)} 人，每人 -{ENTRY_FEE} 金币")
        elif winners and not losers:
            for pid in winners:
                await self.award(
                    pid,
                    ENTRY_FEE,
                    reason=f"ra2_battle_refund:{ctx.session_id}",
                    currency="coin",
                )
            lines.append("只有一方有人押注，退还入场券")
        elif losers and not winners:
            lines.append("只有一方有人押注，无赢家分池")

        for pid_str in bets:
            await self.award(
                int(pid_str),
                PARTICIPATION_REWARD,
                reason=f"ra2_battle_participate:{ctx.session_id}",
                currency="coin",
            )
        lines.append(f"全员参与奖：+{PARTICIPATION_REWARD} 金币")
        return "\n".join(lines)
