"""AoE3 斗蛐蛐 —— 游戏主逻辑。

GameBase 子类，实现完整的游戏状态机：
  开局 → 生成阵容 → 广播面板 → 押注阶段 → 战斗模拟 → 分批播报 → 结算

设计文档：docs/games/aoe3-battle.md
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from pathlib import Path
from typing import Any

from core import economy, render, session
from core.game_base import GameBase, GameMode, register_game
from core.errors import InsufficientFundsError
from core.types import EndReason, GameContext

from src.plugins.aoe3.repository import UnitRepo

from .broadcaster import (
    Broadcaster,
    BroadcastSegment,
    _hp_bar,
    _hp_summary,
    format_battle_report,
    MODE_BRIEF,
)
from core.group_config import get_group_config
from .lineup import (
    Lineup,
    MatchLineup,
    UnitSlot,
    approx_lcm_budget,
    format_formation_panel,
    format_matchup_panel,
    format_side_panel,
    format_vs_banner,
    generate_bet_lineup,
    generate_blacklist_lineup,
    generate_custom_lineup,
    generate_duel_lineup,
    generate_rival_lineup,
    generate_tournament_lineup,
)
from .simulator import ArmySlot, BattleResult, BattleSimulator, Side
from .tournament import Tournament, TournamentStage

logger = logging.getLogger("aoe3_battle.game")

# =====================================================================
# 常量
# =====================================================================
ENTRY_FEE = 5                # 入场券（金币）
PARTICIPATION_REWARD = 1     # 参与奖（金币）
BROADCAST_SLEEP = 2.0        # 播报间隔（秒）
BUDGET_MIN = 1000            # 自定义资源下限
BUDGET_MAX = 50000           # 自定义资源上限
BUDGET_DEFAULT = 10000       # 默认资源
AGE_MIN = 2                  # 时代下限（2 时代无军改）
AGE_MAX = 5                  # 时代上限（帝王）
AGE_DEFAULT = 3              # 默认时代（§3.10.6：693 兵，默认即有改良）
BATTLE_LOG_DIR = Path(__file__).resolve().parents[4] / "logs" / "aoe3_battle"
BATTLE_LOG_KEEP = 5          # 保留最近 N 局（精简+完整各算一个文件）


def _dump_battle_log(
    session_id: str,
    match: MatchLineup,
    result: "BattleResult",
) -> None:
    """写出两份日志：精简版（可远程 cat）+ 完整版（本地 debug）。

    精简版（*.json）~5KB：阵容、结果、每个士兵终态统计、击杀链。
    完整版（*.full.json）~300KB+：包含全部事件流，scp 下来离线分析。
    """
    try:
        BATTLE_LOG_DIR.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{ts}_{session_id}"

        # ── 公共：阵容序列化 ──
        def _serialize_side(lineup) -> dict:
            slots = []
            for s in lineup.slots:
                u = s.unit
                slots.append({
                    "unit_id": u.id,
                    "unit_name": u.name,
                    "count": s.count,
                    "unit_cost": s.unit_cost,
                    "hp": u.hp,
                    "attack_ranged": u.attack_ranged,
                    "attack_melee": u.attack_melee,
                    "attack_siege": u.attack_siege,
                    "armor_ranged": u.armor_ranged,
                    "armor_melee": u.armor_melee,
                    "speed": u.speed,
                    "range": u.range,
                    "range_min": u.range_min,
                    "aoe_radius": u.aoe_radius,
                })
            return {
                "slots": slots,
                "total_cost": lineup.total_cost,
                "total_count": lineup.total_count,
                "total_pop": lineup.total_pop,
            }

        # ── 公共：结果 ──
        result_data: dict = {
            "winner": result.winner.value if result.winner else None,
            "duration": round(result.duration, 2),
            "ticks": result.ticks,
            "timeout": result.timeout,
            "red_alive": len(result.red_alive),
            "blue_alive": len(result.blue_alive),
        }

        # ── 精简版独有：按兵种汇总 & 击杀链 ──
        all_soldiers = (
            result.red_alive + result.red_dead
            + result.blue_alive + result.blue_dead
        )

        # 按（side, unit_name）汇总统计
        from collections import defaultdict
        _agg: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"count": 0, "alive": 0, "total_dmg": 0.0, "total_kills": 0}
        )
        for s in all_soldiers:
            key = (s.side.value, s.unit.name)
            _agg[key]["count"] += 1
            if s.alive:
                _agg[key]["alive"] += 1
            _agg[key]["total_dmg"] += s.total_damage_dealt
            _agg[key]["total_kills"] += s.kills

        unit_summary = []
        for (side, name), v in sorted(_agg.items()):
            unit_summary.append({
                "side": side,
                "name": name,
                "count": v["count"],
                "alive": v["alive"],
                "total_dmg": round(v["total_dmg"], 1),
                "total_kills": v["total_kills"],
                "avg_dmg": round(v["total_dmg"] / v["count"], 1),
            })

        # Top 3 个体（按综合分排序，仅供参考）
        top3 = sorted(
            all_soldiers,
            key=lambda s: s.total_damage_dealt * 0.5 + s.kills * 50,
            reverse=True,
        )[:3]
        top_individuals = [
            {
                "id": s.id, "name": s.unit.name, "side": s.side.value,
                "damage": round(s.total_damage_dealt, 1), "kills": s.kills,
                "alive": s.alive,
            }
            for s in top3
        ]

        # 击杀链：从事件流中提取 DEATH 事件
        from .simulator import EventType
        kill_chain = []
        for e in result.events:
            if e.event_type == EventType.DEATH:
                kill_chain.append({
                    "t": round(e.time, 1),
                    "victim": e.data.get("soldier_name", "?"),
                    "victim_id": e.data.get("soldier_id"),
                    "victim_side": e.data.get("side"),
                    "killer": e.data.get("killer_name", "?"),
                    "killer_id": e.data.get("killer_id"),
                    "remaining": e.data.get("remaining"),
                })

        # MVP
        mvp_data = None
        if all_soldiers:
            mvp = max(all_soldiers, key=lambda s: s.total_damage_dealt * 0.5 + s.kills * 50)
            mvp_data = {
                "id": mvp.id,
                "name": mvp.unit.name,
                "side": mvp.side.value,
                "damage": round(mvp.total_damage_dealt, 1),
                "kills": mvp.kills,
            }

        # 事件类型统计
        event_counts: dict[str, int] = {}
        for e in result.events:
            event_counts[e.event_type.value] = event_counts.get(e.event_type.value, 0) + 1

        header = {
            "session_id": session_id,
            "timestamp": ts,
            "mode": match.mode,
            "red": _serialize_side(match.red),
            "blue": _serialize_side(match.blue),
            "result": result_data,
            "mvp": mvp_data,
        }

        # ── 写精简版（远程 cat 用，目标 <4KB）──
        summary = {
            **header,
            "event_counts": event_counts,
            "unit_summary": unit_summary,
            "top3": top_individuals,
            "kill_chain": kill_chain,
        }
        summary_path = BATTLE_LOG_DIR / f"{base_name}.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # ── 写完整版（含全部事件流，本地 debug 用）──
        full_log = {
            **header,
            "events": [
                {
                    "time": round(e.time, 2),
                    "type": e.event_type.value,
                    "data": e.data,
                }
                for e in result.events
            ],
        }
        full_path = BATTLE_LOG_DIR / f"{base_name}.full.json"
        full_path.write_text(
            json.dumps(full_log, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "[aoe3_battle] 战斗日志已写入 %s (%.1fKB) + %s (%.1fKB)",
            summary_path.name,
            summary_path.stat().st_size / 1024,
            full_path.name,
            full_path.stat().st_size / 1024,
        )

        # 轮转：按 mtime 保留最近 N 局（精简+完整一起算）
        logs = sorted(BATTLE_LOG_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
        while len(logs) > BATTLE_LOG_KEEP * 2:
            old = logs.pop(0)
            old.unlink()
            logger.debug("[aoe3_battle] 清理旧战斗日志 %s", old.name)

    except Exception as e:  # noqa: BLE001
        logger.warning("[aoe3_battle] dump 战斗日志失败: %s", e, exc_info=True)


# =====================================================================
# 游戏注册
# =====================================================================
@register_game
class AoE3BattleGame(GameBase):
    """帝国3电子斗蛐蛐。"""

    id = "aoe3_battle"
    name = "帝国3斗蛐蛐"
    description = "兵种对战模拟 · 押注 / 单挑 / 黑名单乱斗 / 自选 / 王中王 / 锦标赛"
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
        GameMode(
            id="blacklist",
            name="黑名单乱斗",
            description="怪物 / 战役英雄 / 作弊码兵互殴，战力分平衡",
            aliases=("黑名单", "乱斗", "黑名单乱斗", "blacklist"),
        ),
        GameMode(
            id="custom",
            name="自选模式",
            description="自选 1~2 种兵对决，相同资源",
            aliases=("自选",),
        ),
        GameMode(
            id="rival",
            name="王中王",
            description="职能主题对决 · 表情选主题或指定主题",
            aliases=("王中王", "宿敌", "宿敌挑战"),
        ),
        GameMode(
            id="rival_tournament",
            name="王中王锦标赛",
            description="8 兵种单败淘汰锦标赛 · 表情选主题",
            aliases=("王中王锦标赛", "锦标赛", "tournament"),
        ),
    ]

    # ---- 生命周期 ----

    async def on_create(self, ctx: GameContext) -> None:
        """开局：生成阵容，初始化状态。"""
        mode_id = (ctx.config or {}).get("mode", "bet")
        budget = (ctx.config or {}).get("budget", BUDGET_DEFAULT)
        budget = max(BUDGET_MIN, min(BUDGET_MAX, int(budget)))

        # 时代（§3.10.6）：默认 3 时代；黑名单乱斗不启用（怪物互殴无改良意义）
        age = (ctx.config or {}).get("age", AGE_DEFAULT)
        age = max(AGE_MIN, min(AGE_MAX, int(age)))
        generic_techs_on = bool((ctx.config or {}).get("generic_techs", False))

        repo = UnitRepo.get()
        rng = random.Random()

        if mode_id == "duel":
            match = generate_duel_lineup(repo, age=age, rng=rng)
        elif mode_id == "blacklist":
            match = generate_blacklist_lineup(repo, rng=rng)
        elif mode_id == "custom":
            unit_names = (ctx.config or {}).get("unit_names", [])
            result = generate_custom_lineup(
                repo, unit_names, budget=budget, age=age, rng=rng
            )
            if isinstance(result, str):
                # 生成失败，广播错误信息并抛异常让框架结束对局
                await session.broadcast(ctx.group_id, result)
                raise ValueError(result)
            match = result
        elif mode_id == "rival":
            theme_id = (ctx.config or {}).get("rival_theme_id", "")
            result = generate_rival_lineup(
                repo, theme_id, budget=budget, age=age, rng=rng
            )
            if isinstance(result, str):
                await session.broadcast(ctx.group_id, result)
                raise ValueError(result)
            match = result
        elif mode_id == "rival_tournament":
            theme_id = (ctx.config or {}).get("rival_theme_id", "")
            t_result = generate_tournament_lineup(
                repo, theme_id, age=age, rng=rng
            )
            if isinstance(t_result, str):
                await session.broadcast(ctx.group_id, t_result)
                raise ValueError(t_result)
            from .rival_themes import get_theme_by_id
            theme = get_theme_by_id(theme_id)
            theme_title = theme.title if theme else theme_id
            tournament = Tournament.create(
                t_result, theme_title, age=age, rng=rng,
            )
            # 锦标赛用自己的 state 结构，不走普通 match 流程
            ctx.state.update(
                mode=mode_id,
                age=age,
                phase="tournament_betting",
                tournament=tournament.to_dict(),
                tournament_bets={},  # {str(qq_id): int(unit_idx)}
                budget=budget,
            )
            self._tournament = tournament
            self._battle_task = None
            return  # 提前返回，不走普通 match 的 state 序列化
        else:
            _defer = generic_techs_on and age is not None
            match = generate_bet_lineup(
                repo, rng=rng, budget=budget, age=age,
                defer_counts=_defer,
            )

        # 通用科技（roguelike 横向加成，叠在 tier 之上）
        if generic_techs_on and mode_id != "blacklist" and match.age is not None:
            from src.plugins.aoe3.generic_techs import (
                apply_generic_techs,
                format_tech_lines,
                select_techs,
            )
            from src.plugins.games.aoe3_battle.lineup import (
                _apply_lcm_balance,
                allocate_lineup_counts,
            )
            k = 2 if mode_id == "duel" else 4
            red_units = [s.unit for s in match.red.slots]
            blue_units = [s.unit for s in match.blue.slots]
            red_techs, blue_techs = select_techs(
                red_units, blue_units, match.age, k=k, rng=rng,
            )
            if red_techs or blue_techs:
                base_red = [repo.get_by_id(s.unit.id) for s in match.red.slots]
                base_blue = [repo.get_by_id(s.unit.id) for s in match.blue.slots]
                new_red = apply_generic_techs(red_units, red_techs, base_red)
                new_blue = apply_generic_techs(blue_units, blue_techs, base_blue)
                for i, slot in enumerate(match.red.slots):
                    match.red.slots[i] = UnitSlot(new_red[i], slot.count)
                for i, slot in enumerate(match.blue.slots):
                    match.blue.slots[i] = UnitSlot(new_blue[i], slot.count)
                match.generic_tech_lines = format_tech_lines(red_techs, blue_techs)
            # 科技应用完毕（cost 可能已变）→ 按最终 cost 分配数量（唯一一次）
            if mode_id != "duel":
                allocate_lineup_counts(match.red, budget)
                allocate_lineup_counts(match.blue, budget)
                _apply_lcm_balance(match.red, match.blue, budget)

        # 序列化阵容到 state（供持久化）
        ctx.state.update(
            mode=mode_id,
            age=match.age,
            phase="betting",          # betting → fighting → ended
            # 阵容信息（序列化为可 JSON 的格式）
            red_army=[{"unit_id": s.unit.id, "unit_name": s.unit.name, "count": s.count}
                      for s in match.red.slots],
            red_total_cost=match.red.total_cost,
            red_pop=match.red.total_pop,
            red_count=match.red.total_count,
            blue_army=[{"unit_id": s.unit.id, "unit_name": s.unit.name, "count": s.count}
                       for s in match.blue.slots],
            blue_total_cost=match.blue.total_cost,
            blue_pop=match.blue.total_pop,
            blue_count=match.blue.total_count,
            # 向后兼容：保留首个兵种信息
            red_unit_id=match.red.unit.id,
            red_unit_name=match.red.unit.name,
            blue_unit_id=match.blue.unit.id,
            blue_unit_name=match.blue.unit.name,
            # 押注记录：{str(qq_id): "red"|"blue"}
            bets={},
        )

        # 运行时缓存（不进 state）
        self._match: MatchLineup = match
        self._battle_task: asyncio.Task[Any] | None = None

    async def on_start(self, ctx: GameContext) -> None:
        """广播对阵面板（图片+详情+VS总览），进入押注阶段。"""
        import base64
        from nonebot.adapters.onebot.v11 import Message, MessageSegment

        from src.plugins.aoe3.repository import UnitRepo as _UnitRepo

        mode = ctx.state["mode"]

        # ── 锦标赛模式：发送赛前对阵图 + 押注提示 ──
        if mode == "rival_tournament":
            await self._tournament_on_start(ctx)
            return

        match = self._match

        # ── 发红方（图片 + 详情）──
        red_text = format_side_panel(match.red, "red", mode, opponent=match.blue)
        red_msg = Message()
        for slot in match.red.slots:
            icon_path = _UnitRepo.get().get_icon_path(slot.unit)
            if icon_path:
                b64 = base64.b64encode(icon_path.read_bytes()).decode()
                red_msg.append(MessageSegment.image(f"base64://{b64}"))
        red_msg.append(MessageSegment.text(red_text))
        await session.broadcast_rich(ctx.group_id, red_msg, red_text)

        # ── 发蓝方（图片 + 详情）──
        blue_text = format_side_panel(match.blue, "blue", mode, opponent=match.red)
        blue_msg = Message()
        for slot in match.blue.slots:
            icon_path = _UnitRepo.get().get_icon_path(slot.unit)
            if icon_path:
                b64 = base64.b64encode(icon_path.read_bytes()).decode()
                blue_msg.append(MessageSegment.image(f"base64://{b64}"))
        blue_msg.append(MessageSegment.text(blue_text))
        await session.broadcast_rich(ctx.group_id, blue_msg, blue_text)

        # ── 发 VS 总览 + 押注提示 ──
        vs_text = format_vs_banner(match)
        await session.broadcast(ctx.group_id, vs_text)

        # ── 发阵型面板（非单挑模式且人数 > 2 时才有意义）──
        if mode != "duel" and match.red.total_count + match.blue.total_count > 2:
            formation_text = format_formation_panel(match)
            await session.broadcast(ctx.group_id, formation_text)

        logger.info(
            "[aoe3_battle] 对局 %s 开始，模式=%s 🔴 %s vs 🔵 %s",
            ctx.session_id, ctx.state["mode"],
            " + ".join(f"{s['unit_name']}×{s['count']}" for s in ctx.state["red_army"]),
            " + ".join(f"{s['unit_name']}×{s['count']}" for s in ctx.state["blue_army"]),
        )

    async def on_player_action(
        self, ctx: GameContext, player_id: int, message: str
    ) -> bool:
        """处理群消息：押注1 / 押注2 / 开战。"""
        text = message.strip()
        phase = ctx.state.get("phase", "ended")

        # ── 锦标赛阶段 ──
        if phase.startswith("tournament_"):
            return await self._handle_tournament_action(ctx, player_id, text, phase)

        if phase == "betting":
            return await self._handle_betting(ctx, player_id, text)
        return False

    def in_game_hint(self, ctx: GameContext) -> str:
        phase = ctx.state.get("phase", "ended")
        if phase == "fighting":
            return (
                "⚔️ 斗蛐蛐战斗进行中，请稍候…\n"
                "💡 播报结束后 @我 结束 可开新局"
            )
        if phase == "tournament_betting":
            return (
                "🏆 锦标赛押注中\n"
                "💡 发送序号 1-8 押注夺冠 / 发送「开战」开始\n"
                "💡 @我 结束 可终止本局"
            )
        if phase.startswith("tournament_"):
            return (
                "🏆 锦标赛进行中\n"
                "💡 发送「开战」进入下一轮 / @我 结束 可终止本局"
            )
        return (
            "⚔️ 斗蛐蛐押注中\n"
            "💡 @我 押注1 / 押注2 / 开战\n"
            "💡 @我 结束 可终止本局"
        )

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
    ) -> bool:
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
                return True
            # 扣入场券
            ok = await self._charge_entry_fee(ctx, player_id)
            if not ok:
                return True
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
            return True

        if text == "押注2":
            if pid_str in bets:
                await session.broadcast(
                    ctx.group_id,
                    "⚠️ 你已经押过了（锁死第一笔）",
                    at=player_id,
                )
                return True
            ok = await self._charge_entry_fee(ctx, player_id)
            if not ok:
                return True
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
            return True

        if text == "开战":
            await self._start_battle(ctx)
            return True

        return False

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
            is_duel = ctx.state.get("mode") == "duel"
            sim = BattleSimulator(
                red_army=[(s.unit, s.count) for s in match.red.slots],
                blue_army=[(s.unit, s.count) for s in match.blue.slots],
                duel_mode=is_duel,
            )
            result = sim.run()

            # dump 战斗日志
            _dump_battle_log(ctx.session_id, match, result)

            # 2. 播报
            broadcast_mode = await get_group_config(
                ctx.group_id, "aoe3_battle.broadcast_mode", default=MODE_BRIEF
            )
            bc = Broadcaster(result, mode=broadcast_mode)
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

    # ================================================================
    # 锦标赛阶段
    # ================================================================

    def _get_tournament_icon_paths(self) -> list:
        """获取锦标赛 8 个兵种的图标路径列表。"""
        from pathlib import Path
        repo = UnitRepo.get()
        paths = []
        for tu in self._tournament.units:
            unit = repo.get_by_id(tu.unit_id)
            if unit:
                paths.append(repo.get_icon_path(unit))
            else:
                paths.append(None)
        return paths

    async def _tournament_send_bracket(
        self, ctx: GameContext, hint: str = ""
    ) -> None:
        """发送当前阶段的对阵图。"""
        import base64
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
        from .bracket_renderer import render_bracket

        icon_paths = self._get_tournament_icon_paths()
        data = self._tournament.get_bracket_data(hint=hint, icon_paths=icon_paths)
        png_bytes = render_bracket(data)

        b64 = base64.b64encode(png_bytes).decode()
        msg = Message()
        msg.append(MessageSegment.image(f"base64://{b64}"))
        await session.broadcast_rich(ctx.group_id, msg, "[锦标赛对阵图]")

    async def _tournament_send_ranking(self, ctx: GameContext) -> None:
        """发送最终排名图。"""
        import base64
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
        from .bracket_renderer import render_ranking

        icon_paths = self._get_tournament_icon_paths()
        data = self._tournament.get_ranking_data(icon_paths=icon_paths)
        png_bytes = render_ranking(data)

        b64 = base64.b64encode(png_bytes).decode()
        msg = Message()
        msg.append(MessageSegment.image(f"base64://{b64}"))
        await session.broadcast_rich(ctx.group_id, msg, "[最终排名]")

    async def _tournament_on_start(self, ctx: GameContext) -> None:
        """锦标赛开局：发送赛前对阵图 + 参赛兵种列表 + 押注提示。"""
        t = self._tournament

        # 参赛兵种列表
        lines = [f"🏆 王中王锦标赛 · {t.theme_title}", ""]
        lines.append("📋 参赛兵种：")
        for tu in t.units:
            lines.append(f"  {tu.idx + 1}. {tu.display_name}")
        lines.append("")
        lines.append("💰 发送序号 1-8 押注夺冠（扣 5 金币入场券）")
        lines.append("⚔️ 发送「开战」开始八强战")

        await session.broadcast(ctx.group_id, "\n".join(lines))

        # 发送赛前对阵图
        await self._tournament_send_bracket(
            ctx, hint="八强对阵已确定 · 发送「开战」开始八强战",
        )

        logger.info(
            "[aoe3_battle] 锦标赛 %s 开始，主题=%s，兵种=%s",
            ctx.session_id,
            t.theme_title,
            " / ".join(tu.display_name for tu in t.units),
        )

    async def _handle_tournament_action(
        self, ctx: GameContext, player_id: int, text: str, phase: str
    ) -> bool:
        """处理锦标赛阶段的群消息。"""
        if phase == "tournament_betting":
            return await self._handle_tournament_betting(ctx, player_id, text)

        if phase == "tournament_waiting":
            if text == "开战":
                await self._run_tournament_next_stage(ctx)
                return True
            return False

        # 战斗进行中不拦截
        return False

    async def _handle_tournament_betting(
        self, ctx: GameContext, player_id: int, text: str
    ) -> bool:
        """锦标赛押注：序号 1-8 押注夺冠 / 开战。"""
        bets: dict[str, int] = ctx.state.get("tournament_bets", {})
        pid_str = str(player_id)

        # 押注序号
        if text in ("1", "2", "3", "4", "5", "6", "7", "8"):
            if pid_str in bets:
                await session.broadcast(
                    ctx.group_id,
                    "⚠️ 你已经押过了（锁死第一笔）",
                    at=player_id,
                )
                return True

            ok = await self._charge_entry_fee(ctx, player_id)
            if not ok:
                return True

            unit_idx = int(text) - 1
            bets[pid_str] = unit_idx
            ctx.state["tournament_bets"] = bets

            tu = self._tournament.get_unit(unit_idx)
            await session.broadcast(
                ctx.group_id,
                f"✅ 押 {text}号 {tu.display_name} 夺冠，入场券 {ENTRY_FEE} 金币已扣除",
                at=player_id,
            )
            logger.info(
                "[aoe3_battle] %s 玩家 %d 锦标赛押注 %d号 %s",
                ctx.session_id, player_id, unit_idx + 1, tu.display_name,
            )
            return True

        if text == "开战":
            bet_count = len(bets)
            if bet_count > 0:
                await session.broadcast(
                    ctx.group_id,
                    f"🎲 押注截止！共 {bet_count} 人参与",
                )
            else:
                await session.broadcast(
                    ctx.group_id,
                    "🎲 无人押注，直接开战！",
                )
            # 推进到八强战
            self._tournament.try_advance()  # DRAW → QF
            ctx.state["phase"] = "tournament_fighting"
            self._battle_task = asyncio.create_task(
                self._run_tournament_round(ctx)
            )
            return True

        return False

    async def _run_tournament_round(self, ctx: GameContext) -> None:
        """执行当前轮次的所有比赛 → 播报 → 出图 → 等待「开战」或结束。"""
        try:
            t = self._tournament
            pending = t.get_current_round_matches()
            if not pending:
                # 尝试推进
                t.try_advance()
                pending = t.get_current_round_matches()

            budget = ctx.state.get("budget", BUDGET_DEFAULT)

            for match_obj in pending:
                # 一场比赛：双方各 1 兵种，LCM 平衡数量
                tu_a = t.get_unit(match_obj.unit_a_idx)
                tu_b = t.get_unit(match_obj.unit_b_idx)

                # LCM 平衡
                cost_a = sum(tu_a.unit.cost.values())
                cost_b = sum(tu_b.unit.cost.values())
                if cost_a <= 0:
                    cost_a = 1
                if cost_b <= 0:
                    cost_b = 1
                lcm_budget = approx_lcm_budget(cost_a, cost_b, budget)
                count_a = max(1, lcm_budget // cost_a)
                count_b = max(1, lcm_budget // cost_b)

                # 跑模拟
                sim = BattleSimulator(
                    red_army=[(tu_a.unit, count_a)],
                    blue_army=[(tu_b.unit, count_b)],
                )
                result = sim.run()

                # 确定胜者
                if result.winner == Side.RED:
                    winner_idx = match_obj.unit_a_idx
                elif result.winner == Side.BLUE:
                    winner_idx = match_obj.unit_b_idx
                else:
                    # 平局时随机决定（锦标赛不允许平局）
                    winner_idx = random.choice(
                        [match_obj.unit_a_idx, match_obj.unit_b_idx]
                    )

                t.record_result(match_obj.match_id, winner_idx)

                # 中间推进（败者组需要在 LR1/LR2 结束后填充 7TH/5TH）
                t.try_advance()

                # ── 合并战报（标题 + 血条 + 统计 + 胜者）──
                winner_tu = t.get_unit(winner_idx)
                loser_idx = match_obj.loser_idx
                assert loser_idx is not None
                loser_tu = t.get_unit(loser_idx)

                # 血条数据
                red_all = result.red_alive + result.red_dead
                blue_all = result.blue_alive + result.blue_dead
                red_max_hp = sum(s.max_hp for s in red_all)
                red_cur_hp = sum(s.hp for s in result.red_alive)
                blue_max_hp = sum(s.max_hp for s in blue_all)
                blue_cur_hp = sum(s.hp for s in result.blue_alive)

                # 每方统计
                red_same = [s for s in red_all if s.unit.id == tu_a.unit.id]
                blue_same = [s for s in blue_all if s.unit.id == tu_b.unit.id]
                red_alive_n = len([s for s in result.red_alive if s.unit.id == tu_a.unit.id])
                blue_alive_n = len([s for s in result.blue_alive if s.unit.id == tu_b.unit.id])
                red_kills = sum(s.kills for s in red_same)
                red_dmg = sum(s.total_damage_dealt for s in red_same)
                blue_kills = sum(s.kills for s in blue_same)
                blue_dmg = sum(s.total_damage_dealt for s in blue_same)

                red_status = "全灭" if red_alive_n == 0 else f"存活{red_alive_n}"
                blue_status = "全灭" if blue_alive_n == 0 else f"存活{blue_alive_n}"

                # 晋级文案
                mid = match_obj.match_id
                if mid.startswith("QF"):
                    promo = "，晋级四强"
                elif mid.startswith("SF"):
                    promo = "，晋级决赛"
                elif mid == "FINAL":
                    promo = "，夺得冠军！"
                else:
                    promo = ""

                # 组装一条消息
                report_lines = [
                    f"━━━ {match_obj.label} {tu_a.display_name} vs {tu_b.display_name} ⏱{result.duration:.1f}s ━━━",
                    f"🔴 {_hp_bar(red_cur_hp, red_max_hp, '🟥')}  {_hp_summary(red_cur_hp, red_max_hp)}",
                    f"🔵 {_hp_bar(blue_cur_hp, blue_max_hp, '🟥')}  {_hp_summary(blue_cur_hp, blue_max_hp)}",
                    f"🔴 {tu_a.display_name} ×{count_a} → {red_status}/击杀{red_kills}/伤害{red_dmg:.0f}",
                    f"🔵 {tu_b.display_name} ×{count_b} → {blue_status}/击杀{blue_kills}/伤害{blue_dmg:.0f}",
                    f"✅ {winner_tu.display_name} 胜{promo}",
                ]
                await session.broadcast(ctx.group_id, "\n".join(report_lines))
                await asyncio.sleep(2.0)

            # 先检查循环内 try_advance 后是否已进入出图阶段
            # （必须在第二次 try_advance 前检查，否则 QF_DONE/SF_DONE 会被跳过）
            if t.stage == TournamentStage.FINISHED:
                # 决赛结束 → 出最终对阵图 + 排名图 + 结算
                await self._tournament_send_bracket(ctx)
                await asyncio.sleep(1.0)
                await self._tournament_send_ranking(ctx)
                await asyncio.sleep(0.5)

                # 押注结算
                settlement = await self._settle_tournament_bets(ctx)
                if settlement:
                    await session.broadcast(ctx.group_id, settlement)

                ctx.state["phase"] = "ended"
                from core import game_base as gb
                runner = gb.get_runner(ctx.session_id)
                if runner is not None:
                    await runner.end(EndReason.COMPLETED)

            elif t.is_bracket_stage():
                # QF_DONE 或 SF_DONE → 出对阵图，等待「开战」
                stage_hints = {
                    TournamentStage.QF_DONE: "八强战结束 · 发送「开战」进入排位赛+半决赛",
                    TournamentStage.SF_DONE: "半决赛结束 · 发送「开战」进入季军战+决赛",
                }
                hint = stage_hints.get(t.stage, "")
                await self._tournament_send_bracket(ctx, hint=hint)
                ctx.state["phase"] = "tournament_waiting"

            else:
                # 非出图阶段 → 推进一次后再判断
                t.try_advance()
                ctx.state["tournament"] = t.to_dict()

                if t.stage == TournamentStage.FINISHED:
                    # 推进后进入结束状态
                    await self._tournament_send_bracket(ctx)
                    await asyncio.sleep(1.0)
                    await self._tournament_send_ranking(ctx)
                    await asyncio.sleep(0.5)

                    settlement = await self._settle_tournament_bets(ctx)
                    if settlement:
                        await session.broadcast(ctx.group_id, settlement)

                    ctx.state["phase"] = "ended"
                    from core import game_base as gb
                    runner = gb.get_runner(ctx.session_id)
                    if runner is not None:
                        await runner.end(EndReason.COMPLETED)

                elif t.is_bracket_stage():
                    # 推进后进入出图阶段（兜底）
                    stage_hints = {
                        TournamentStage.QF_DONE: "八强战结束 · 发送「开战」进入排位赛+半决赛",
                        TournamentStage.SF_DONE: "半决赛结束 · 发送「开战」进入季军战+决赛",
                    }
                    hint = stage_hints.get(t.stage, "")
                    await self._tournament_send_bracket(ctx, hint=hint)
                    ctx.state["phase"] = "tournament_waiting"

                else:
                    # 败者组等不出图的中间阶段：直接等待「开战」
                    stage_prompts = {
                        TournamentStage.LOSERS_DONE: "排位赛结束，发送「开战」进入半决赛",
                    }
                    prompt = stage_prompts.get(t.stage, "发送「开战」继续")
                    await session.broadcast(ctx.group_id, f"📋 {prompt}")
                    ctx.state["phase"] = "tournament_waiting"

        except asyncio.CancelledError:
            logger.info("[aoe3_battle] %s 锦标赛任务被取消", ctx.session_id)
        except Exception as e:
            logger.exception("[aoe3_battle] %s 锦标赛执行出错: %s", ctx.session_id, e)
            try:
                await session.broadcast(ctx.group_id, f"⚠️ 锦标赛执行出错：{e}")
            except Exception:
                pass
            ctx.state["phase"] = "ended"
            from core import game_base as gb
            runner = gb.get_runner(ctx.session_id)
            if runner is not None:
                await runner.end(EndReason.ERROR)

    async def _run_tournament_next_stage(self, ctx: GameContext) -> None:
        """「开战」后推进到下一轮并执行。"""
        t = self._tournament
        t.try_advance()
        ctx.state["phase"] = "tournament_fighting"
        self._battle_task = asyncio.create_task(
            self._run_tournament_round(ctx)
        )

    # ================================================================
    # 锦标赛押注结算
    # ================================================================

    async def _settle_tournament_bets(self, ctx: GameContext) -> str:
        """锦标赛押注结算。押中夺冠的兵种序号即为赢家。"""
        bets: dict[str, int] = ctx.state.get("tournament_bets", {})
        if not bets:
            return ""

        t = self._tournament
        if not t.final_ranks:
            return ""

        champion_idx = t.final_ranks[0]
        champion_name = t.get_unit(champion_idx).display_name

        lines = ["━━━ 锦标赛押注结算 ━━━"]
        lines.append(f"🏆 冠军：{champion_name}")

        winners = [int(k) for k, v in bets.items() if v == champion_idx]
        losers = [int(k) for k, v in bets.items() if v != champion_idx]

        loser_pool = len(losers) * ENTRY_FEE

        if winners and losers:
            per_winner = loser_pool // len(winners)
            remainder = loser_pool % len(winners)

            for pid in winners:
                reward = ENTRY_FEE + per_winner
                await self.award(
                    pid, reward,
                    reason=f"aoe3_tournament_win:{ctx.session_id}",
                    currency="coin",
                )
            if remainder > 0:
                await self.award(
                    winners[0], remainder,
                    reason=f"aoe3_tournament_win_r:{ctx.session_id}",
                    currency="coin",
                )

            if len(winners) <= 5:
                winner_mentions = " ".join(f"@{pid}" for pid in winners)
            else:
                winner_mentions = (
                    " ".join(f"@{pid}" for pid in winners[:5])
                    + f" 等 {len(winners)} 人"
                )

            lines.append(f"🎉 押对：{winner_mentions}（{len(winners)} 人）")
            lines.append(f"每人 +{per_winner + ENTRY_FEE} 金币（含退还入场券）")
            lines.append(f"押错：{len(losers)} 人，每人 -{ENTRY_FEE} 金币")

        elif winners and not losers:
            for pid in winners:
                await self.award(
                    pid, ENTRY_FEE,
                    reason=f"aoe3_tournament_refund:{ctx.session_id}",
                    currency="coin",
                )
            lines.append("全员押对，退还入场券")

        elif losers and not winners:
            lines.append("无人押中冠军，无赢家分池")

        # 参与奖
        for pid_str in bets:
            pid = int(pid_str)
            await self.award(
                pid, PARTICIPATION_REWARD,
                reason=f"aoe3_tournament_part:{ctx.session_id}",
                currency="coin",
            )
        lines.append(f"全员参与奖：+{PARTICIPATION_REWARD} 金币")

        return "\n".join(lines)
