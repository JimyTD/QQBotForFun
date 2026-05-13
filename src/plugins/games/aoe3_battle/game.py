"""AoE3 斗蛐蛐 —— 游戏主逻辑。

GameBase 子类，实现完整的游戏状态机：
  开局 → 生成阵容 → 广播面板 → 押注阶段 → 战斗模拟 → 分批播报 → 结算

设计文档：docs/games/aoe3-battle.md
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from core import economy, render, session
from core.game_base import GameBase, GameMode, register_game
from core.errors import InsufficientFundsError
from core.types import EndReason, GameContext

from src.plugins.aoe3.repository import UnitRepo

from .broadcaster import (
    Broadcaster,
    BroadcastSegment,
    format_battle_report,
)
from .lineup import (
    MatchLineup,
    format_matchup_panel,
    format_side_panel,
    format_vs_banner,
    generate_bet_lineup,
    generate_duel_lineup,
)
from .simulator import BattleResult, BattleSimulator, Side

logger = logging.getLogger("aoe3_battle.game")

# =====================================================================
# 常量
# =====================================================================
ENTRY_FEE = 5                # 入场券（金币）
PARTICIPATION_REWARD = 1     # 参与奖（金币）
BROADCAST_SLEEP = 2.0        # 播报间隔（秒）


# =====================================================================
# 游戏注册
# =====================================================================
@register_game
class AoE3BattleGame(GameBase):
    """帝国3电子斗蛐蛐。"""

    id = "aoe3_battle"
    name = "帝国3斗蛐蛐"
    description = "兵种对战模拟 · 押注 / 单挑"
    min_players = 0            # 无人押注也能打
    max_players = 50
    version = "1.0"
    serialize_actions = False
    event_driven = True        # 群消息转给 on_player_action

    MODES = [
        GameMode(
            id="bet",
            name="押注模式",
            description="随机双方阵容，群殴对决",
            aliases=("押注", "斗蛐蛐", "默认"),
        ),
        GameMode(
            id="duel",
            name="单挑模式",
            description="随机两个兵种，真 1v1",
            aliases=("单挑", "1v1"),
        ),
    ]

    # ---- 生命周期 ----

    async def on_create(self, ctx: GameContext) -> None:
        """开局：生成阵容，初始化状态。"""
        mode_id = (ctx.config or {}).get("mode", "bet")
        repo = UnitRepo.get()
        rng = random.Random()

        if mode_id == "duel":
            match = generate_duel_lineup(repo, rng=rng)
        else:
            match = generate_bet_lineup(repo, rng=rng)

        # 序列化阵容到 state（供持久化）
        ctx.state.update(
            mode=mode_id,
            phase="betting",          # betting → fighting → ended
            # 阵容信息（序列化为可 JSON 的格式）
            red_unit_id=match.red.unit.id,
            red_unit_name=match.red.unit.name,
            red_count=match.red.count,
            red_total_cost=match.red.total_cost,
            red_pop=match.red.pop,
            blue_unit_id=match.blue.unit.id,
            blue_unit_name=match.blue.unit.name,
            blue_count=match.blue.count,
            blue_total_cost=match.blue.total_cost,
            blue_pop=match.blue.pop,
            # 押注记录：{str(qq_id): "red"|"blue"}
            bets={},
            # 缓存 MatchLineup 对象（不持久化，仅运行时用）
        )

        # 运行时缓存（不进 state）
        self._match: MatchLineup = match
        self._battle_task: asyncio.Task[Any] | None = None

    async def on_start(self, ctx: GameContext) -> None:
        """广播对阵面板（图片+详情+VS总览），进入押注阶段。"""
        import base64
        from nonebot.adapters.onebot.v11 import Message, MessageSegment

        from src.plugins.aoe3.repository import UnitRepo as _UnitRepo

        match = self._match
        mode = ctx.state["mode"]

        # ── 发红方（图片 + 详情）──
        red_text = format_side_panel(match.red, "red", mode)
        red_msg = Message()
        icon_path = _UnitRepo.get().get_icon_path(match.red.unit)
        if icon_path:
            b64 = base64.b64encode(icon_path.read_bytes()).decode()
            red_msg.append(MessageSegment.image(f"base64://{b64}"))
        red_msg.append(MessageSegment.text(red_text))
        await session.broadcast(ctx.group_id, red_msg)

        # ── 发蓝方（图片 + 详情）──
        blue_text = format_side_panel(match.blue, "blue", mode)
        blue_msg = Message()
        icon_path = _UnitRepo.get().get_icon_path(match.blue.unit)
        if icon_path:
            b64 = base64.b64encode(icon_path.read_bytes()).decode()
            blue_msg.append(MessageSegment.image(f"base64://{b64}"))
        blue_msg.append(MessageSegment.text(blue_text))
        await session.broadcast(ctx.group_id, blue_msg)

        # ── 发 VS 总览 + 押注提示 ──
        vs_text = format_vs_banner(match)
        await session.broadcast(ctx.group_id, vs_text)

        logger.info(
            "[aoe3_battle] 对局 %s 开始，模式=%s 🔴 %s ×%d vs 🔵 %s ×%d",
            ctx.session_id, ctx.state["mode"],
            ctx.state["red_unit_name"], ctx.state["red_count"],
            ctx.state["blue_unit_name"], ctx.state["blue_count"],
        )

    async def on_player_action(
        self, ctx: GameContext, player_id: int, message: str
    ) -> None:
        """处理群消息：押注1 / 押注2 / 开战。"""
        text = message.strip()
        phase = ctx.state.get("phase", "ended")

        if phase == "betting":
            await self._handle_betting(ctx, player_id, text)
        # fighting / ended 阶段不处理玩家消息

    async def on_timeout(self, ctx: GameContext) -> None:
        """整局超时。"""
        if ctx.state.get("phase") == "betting":
            await session.broadcast(ctx.group_id, "⏱ 斗蛐蛐超时，本局结束。")

    async def on_end(self, ctx: GameContext, reason: EndReason) -> None:
        """清理。"""
        # 注意：不在这里 cancel _battle_task —— 如果 _run_battle 内部
        # 调用了 runner.end()，cancel 自己会导致 runner.end() 的 finally
        # 块里的 await 被 CancelledError 打断，_runner_by_group.pop 被跳过。
        logger.info(
            "[aoe3_battle] 对局 %s 结束，reason=%s",
            ctx.session_id, reason.value,
        )

    # ================================================================
    # 押注阶段
    # ================================================================
    async def _handle_betting(
        self, ctx: GameContext, player_id: int, text: str
    ) -> None:
        """处理押注阶段的玩家消息。"""
        bets: dict[str, str] = ctx.state.get("bets", {})
        pid_str = str(player_id)

        if text == "押注1":
            if pid_str in bets:
                await session.broadcast(
                    ctx.group_id,
                    "⚠️ 你已经押过了（锁死第一笔）",
                    at=player_id,
                )
                return
            # 扣入场券
            ok = await self._charge_entry_fee(ctx, player_id)
            if not ok:
                return
            bets[pid_str] = "red"
            ctx.state["bets"] = bets
            await session.broadcast(
                ctx.group_id,
                f"✅ 押了 🔴 红方（1号），入场券 {ENTRY_FEE} 金币已扣除",
                at=player_id,
            )
            logger.info(
                "[aoe3_battle] %s 玩家 %d 押注红方",
                ctx.session_id, player_id,
            )

        elif text == "押注2":
            if pid_str in bets:
                await session.broadcast(
                    ctx.group_id,
                    "⚠️ 你已经押过了（锁死第一笔）",
                    at=player_id,
                )
                return
            ok = await self._charge_entry_fee(ctx, player_id)
            if not ok:
                return
            bets[pid_str] = "blue"
            ctx.state["bets"] = bets
            await session.broadcast(
                ctx.group_id,
                f"✅ 押了 🔵 蓝方（2号），入场券 {ENTRY_FEE} 金币已扣除",
                at=player_id,
            )
            logger.info(
                "[aoe3_battle] %s 玩家 %d 押注蓝方",
                ctx.session_id, player_id,
            )

        elif text == "开战":
            # 任意群友可发开战
            await self._start_battle(ctx)

    async def _charge_entry_fee(
        self, ctx: GameContext, player_id: int
    ) -> bool:
        """扣入场券，余额不足返回 False。"""
        try:
            await economy.deduct(
                player_id,
                ENTRY_FEE,
                reason=f"aoe3_battle_entry:{ctx.session_id}",
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

    # ================================================================
    # 战斗阶段
    # ================================================================
    async def _start_battle(self, ctx: GameContext) -> None:
        """切换到战斗阶段，跑模拟 + 播报 + 结算。"""
        if ctx.state.get("phase") != "betting":
            return
        ctx.state["phase"] = "fighting"

        bets: dict[str, str] = ctx.state.get("bets", {})
        bet_count = len(bets)
        if bet_count > 0:
            await session.broadcast(
                ctx.group_id,
                f"🎲 押注截止！共 {bet_count} 人参与",
            )
        else:
            await session.broadcast(
                ctx.group_id,
                "🎲 无人押注，直接开打！",
            )

        # 异步执行战斗（避免阻塞消息处理）
        self._battle_task = asyncio.create_task(
            self._run_battle(ctx)
        )

    async def _run_battle(self, ctx: GameContext) -> None:
        """执行战斗模拟 + 播报 + 结算。"""
        try:
            match = self._match

            # 1. 跑模拟
            sim = BattleSimulator(
                match.red.unit, match.red.count,
                match.blue.unit, match.blue.count,
            )
            result = sim.run()

            # 2. 播报
            bc = Broadcaster(result)
            segments = bc.generate()

            for seg in segments:
                await session.broadcast(ctx.group_id, seg.text)
                if seg.should_sleep:
                    await asyncio.sleep(BROADCAST_SLEEP)

            # 3. 最终战报 + 押注结算
            report = format_battle_report(result)
            settlement = await self._settle_bets(ctx, result)

            # 合并战报和结算为一条消息
            if settlement:
                full_report = f"{report}\n\n{settlement}"
            else:
                full_report = report

            await session.broadcast(ctx.group_id, full_report)

            # 4. 结束对局
            ctx.state["phase"] = "ended"
            from core import game_base as gb
            runner = gb.get_runner(ctx.session_id)
            if runner is not None:
                await runner.end(EndReason.COMPLETED)

        except asyncio.CancelledError:
            logger.info("[aoe3_battle] %s 战斗任务被取消", ctx.session_id)
        except Exception as e:
            logger.exception("[aoe3_battle] %s 战斗执行出错: %s", ctx.session_id, e)
            try:
                await session.broadcast(ctx.group_id, f"⚠️ 战斗模拟出错：{e}")
            except Exception:
                pass
            ctx.state["phase"] = "ended"
            from core import game_base as gb
            runner = gb.get_runner(ctx.session_id)
            if runner is not None:
                await runner.end(EndReason.ERROR)

    # ================================================================
    # 押注结算
    # ================================================================
    async def _settle_bets(
        self, ctx: GameContext, result: BattleResult
    ) -> str:
        """结算押注，返回结算文本。"""
        bets: dict[str, str] = ctx.state.get("bets", {})
        if not bets:
            return ""

        winner_side = result.winner.value if result.winner else None
        lines = ["━━━ 押注结算 ━━━"]

        if winner_side is None:
            # 平局：全额退还入场券
            for pid_str in bets:
                pid = int(pid_str)
                await self.award(
                    pid, ENTRY_FEE,
                    reason=f"aoe3_battle_refund:{ctx.session_id}",
                    currency="coin",
                )
            lines.append("平局！入场券全额退还")
            # 参与奖
            for pid_str in bets:
                pid = int(pid_str)
                await self.award(
                    pid, PARTICIPATION_REWARD,
                    reason=f"aoe3_battle_participate:{ctx.session_id}",
                    currency="coin",
                )
            lines.append(f"全员参与奖：+{PARTICIPATION_REWARD} 金币")
            return "\n".join(lines)

        # 分组
        winners = [int(k) for k, v in bets.items() if v == winner_side]
        losers = [int(k) for k, v in bets.items() if v != winner_side]

        loser_pool = len(losers) * ENTRY_FEE  # 输家池

        if winners and losers:
            # 正常结算：赢家平分输家池
            per_winner = loser_pool // len(winners)
            remainder = loser_pool % len(winners)

            for pid in winners:
                # 退还入场券 + 分得奖金
                reward = ENTRY_FEE + per_winner
                await self.award(
                    pid, reward,
                    reason=f"aoe3_battle_win:{ctx.session_id}",
                    currency="coin",
                )

            # 余数给第一个赢家
            if remainder > 0:
                await self.award(
                    winners[0], remainder,
                    reason=f"aoe3_battle_win_remainder:{ctx.session_id}",
                    currency="coin",
                )

            # 押对文案
            winner_emoji = "🔴" if winner_side == "red" else "🔵"
            winner_label = "红方" if winner_side == "red" else "蓝方"

            if len(winners) <= 5:
                winner_mentions = " ".join(f"@{pid}" for pid in winners)
            else:
                winner_mentions = (
                    " ".join(f"@{pid}" for pid in winners[:5])
                    + f" 等 {len(winners)} 人"
                )

            lines.append(f"押对 {winner_emoji}{winner_label}：{winner_mentions}（{len(winners)} 人）")
            lines.append(f"每人 +{per_winner + ENTRY_FEE} 金币（含退还入场券）")
            lines.append(f"押错：{len(losers)} 人，每人 -{ENTRY_FEE} 金币")

        elif winners and not losers:
            # 只有赢家没有输家：退还入场券 + 参与奖
            for pid in winners:
                await self.award(
                    pid, ENTRY_FEE,
                    reason=f"aoe3_battle_refund:{ctx.session_id}",
                    currency="coin",
                )
            lines.append("只有一方有人押注，退还入场券")

        elif losers and not winners:
            # 只有输家没有赢家：输家已扣费，不退
            lines.append("只有一方有人押注，无赢家分池")

        # 参与奖（所有押注者）
        for pid_str in bets:
            pid = int(pid_str)
            await self.award(
                pid, PARTICIPATION_REWARD,
                reason=f"aoe3_battle_participate:{ctx.session_id}",
                currency="coin",
            )
        lines.append(f"全员参与奖：+{PARTICIPATION_REWARD} 金币")

        return "\n".join(lines)
