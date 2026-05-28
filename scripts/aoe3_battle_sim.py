"""AoE3 斗蛐蛐 —— 独立模拟器测试脚本。

纯模拟测试入口，不涉及押注/经济/群消息/状态机。
直接：选两个兵种和数量 → 跑模拟 → 打印事件流和结果。

用法：
    uv run python scripts/aoe3_battle_sim.py                          # 交互式
    uv run python scripts/aoe3_battle_sim.py --red musketeer:10 --blue pikeman:8  # 参数式
    uv run python scripts/aoe3_battle_sim.py --red 火枪手:10 --blue 长枪兵:8     # 中文也行
    uv run python scripts/aoe3_battle_sim.py --random                              # 随机押注模式阵容
    uv run python scripts/aoe3_battle_sim.py --duel                                # 随机单挑模式
    uv run python scripts/aoe3_battle_sim.py --blacklist                            # 黑名单乱斗

设计文档：docs/games/aoe3-battle.md §六
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
from pathlib import Path

# ---- 路径设置 ----
_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Windows UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from plugins.aoe3.repository import UnitRepo  # noqa: E402
from plugins.aoe3.models import Unit  # noqa: E402
from plugins.games.aoe3_battle.simulator import (  # noqa: E402
    BattleSimulator,
    BattleResult,
    EventType,
    Side,
    BattlePhase,
)
from plugins.games.aoe3_battle.lineup import (  # noqa: E402
    generate_bet_lineup,
    generate_blacklist_lineup,
    generate_duel_lineup,
    format_matchup_panel,
)
from plugins.games.aoe3_battle.broadcaster import (  # noqa: E402
    Broadcaster,
    format_battle_report,
)


# =====================================================================
# 颜色工具
# =====================================================================
class C:
    R = "\033[0m"
    B = "\033[1m"
    CYAN = "\033[36m"
    YEL = "\033[33m"
    GRN = "\033[32m"
    RED = "\033[31m"
    MAG = "\033[35m"
    DIM = "\033[2m"
    BLUE = "\033[34m"


def _side_color(side: str) -> str:
    return C.RED if side == "red" else C.BLUE


def _side_emoji(side: str) -> str:
    return "🔴" if side == "red" else "🔵"


# =====================================================================
# 事件流打印
# =====================================================================
def print_events(result: BattleResult, *, verbose: bool = False) -> None:
    """打印事件流。verbose=True 打印所有事件，否则只打印关键事件。"""
    print(f"\n{C.B}{C.CYAN}{'━' * 60}{C.R}")
    print(f"{C.B}{C.CYAN}  事件流{C.R}")
    print(f"{C.CYAN}{'━' * 60}{C.R}")

    for ev in result.events:
        d = ev.data
        t = f"[{ev.time:5.1f}s]"

        if ev.event_type == EventType.BATTLE_START:
            # 兼容新旧事件格式
            if "red_army" in d:
                red_desc = " + ".join(f"{s['name']}×{s['count']}" for s in d["red_army"])
                blue_desc = " + ".join(f"{s['name']}×{s['count']}" for s in d["blue_army"])
            else:
                red_desc = f"{d['red_unit']} ×{d['red_count']}"
                blue_desc = f"{d['blue_unit']} ×{d['blue_count']}"
            print(
                f"\n{C.B}⚔️  {t} 战斗开始！"
                f" {C.RED}{red_desc}{C.R}"
                f" vs"
                f" {C.BLUE}{blue_desc}{C.R}"
            )

        elif ev.event_type == EventType.DEATH:
            sc = _side_color(d["side"])
            kc = _side_color(d["killer_side"])
            print(
                f"  {C.RED}☠{C.R} {t} "
                f"{sc}{d['soldier_name']}#{d['soldier_id']}{C.R} 阵亡"
                f"（被 {kc}{d['killer_name']}#{d['killer_id']}{C.R} 击杀）"
                f" — {_side_emoji(d['side'])} 剩余 {d['remaining']}/{d['total']}"
            )

        elif ev.event_type == EventType.ATTACK and verbose:
            sc = _side_color(d["attacker_side"])
            tc = _side_color(d["target_side"])
            splash = " [溅射]" if d.get("is_splash") else ""
            print(
                f"  {C.DIM}{t} "
                f"{sc}{d['attacker_name']}#{d['attacker_id']}{C.R}"
                f"{C.DIM} → "
                f"{tc}{d['target_name']}#{d['target_id']}{C.R}"
                f"{C.DIM} {d['mode']} dmg={d['damage']}"
                f" hp={d['target_hp_before']}→{d['target_hp_after']}"
                f"{splash}{C.R}"
            )

        elif ev.event_type == EventType.TARGET_LOCK and verbose:
            sc = _side_color(d["side"])
            print(
                f"  {C.DIM}{t} 🎯 "
                f"{sc}{d['soldier_name']}#{d['soldier_id']}{C.R}"
                f"{C.DIM} 锁定 {d['target_name']}#{d['target_id']}"
                f" (dist={d['distance']}){C.R}"
            )

        elif ev.event_type == EventType.AOE_SPLASH and verbose:
            print(
                f"  {C.DIM}{t} 💥 AOE "
                f"{d['attacker_name']}#{d['attacker_id']}"
                f" → {d['splash_target_name']}#{d['splash_target_id']}"
                f" dmg={d['splash_damage']}{C.R}"
            )

        elif ev.event_type == EventType.BATTLE_END:
            winner = d["winner"]
            if winner == "draw":
                print(f"\n{C.B}{C.YEL}  🏳️ {t} 战斗结束 — 平局！{C.R}")
            else:
                wc = _side_color(winner)
                print(
                    f"\n{C.B}{wc}  🏆 {t} 战斗结束 — "
                    f"{_side_emoji(winner)} {'红方' if winner == 'red' else '蓝方'}胜利！{C.R}"
                )
            timeout_str = "（超时判定）" if d.get("timeout") else ""
            print(
                f"  时长: {d['duration']}s | "
                f"🔴 {d['red_alive']}/{d['red_total']} | "
                f"🔵 {d['blue_alive']}/{d['blue_total']}"
                f" {timeout_str}"
            )


# =====================================================================
# 战报打印
# =====================================================================
def print_report(result: BattleResult) -> None:
    """打印最终战报（支持多兵种）。"""
    print(f"\n{C.B}{C.CYAN}{'━' * 60}{C.R}")
    print(f"{C.B}{C.CYAN}  最终战报{C.R}")
    print(f"{C.CYAN}{'━' * 60}{C.R}")

    # 胜负
    if result.winner is None:
        print(f"  {C.B}{C.YEL}结果：平局{C.R}")
    elif result.winner == Side.RED:
        print(f"  {C.B}{C.RED}结果：🔴 红方胜利{C.R}")
    else:
        print(f"  {C.B}{C.BLUE}结果：🔵 蓝方胜利{C.R}")

    if result.timeout:
        print(f"  {C.YEL}（超时判定 — 按剩余资源价值）{C.R}")

    print(f"  战斗时长: {result.duration:.1f}s ({result.ticks} ticks)")
    print()

    # 双方统计（支持多兵种）
    for side, army, count, alive, dead, color, emoji in [
        (Side.RED, result.red_army, result.red_count,
         result.red_alive, result.red_dead, C.RED, "🔴"),
        (Side.BLUE, result.blue_army, result.blue_count,
         result.blue_alive, result.blue_dead, C.BLUE, "🔵"),
    ]:
        total_dmg = sum(s.total_damage_dealt for s in alive) + sum(
            s.total_damage_dealt for s in dead
        )
        total_kills = sum(s.kills for s in alive) + sum(s.kills for s in dead)

        # 阵容描述
        if len(army) > 1:
            army_desc = " + ".join(f"{s.unit.name}×{s.count}" for s in army)
        else:
            army_desc = f"{army[0].unit.name} ×{army[0].count}"

        print(
            f"  {color}{C.B}{emoji} [{army_desc}]{C.R}"
            f"  存活: {len(alive)}/{count}"
            f"  击杀: {total_kills}"
            f"  总伤害: {total_dmg:.0f}"
        )

        # 按兵种统计存活
        for slot in army:
            alive_of_type = [s for s in alive if s.unit.id == slot.unit.id]
            dead_of_type = slot.count - len(alive_of_type)
            if len(alive_of_type) == 0:
                print(f"    {slot.unit.name} ×{slot.count} → 0")
            elif len(alive_of_type) == 1 and dead_of_type > 0:
                s = alive_of_type[0]
                print(
                    f"    {slot.unit.name} ×{len(alive_of_type)}"
                    f"（损失 {dead_of_type}/{slot.count}，"
                    f"HP {s.hp:.0f}/{s.max_hp:.0f}）"
                )
            else:
                print(
                    f"    {slot.unit.name} ×{len(alive_of_type)}"
                    f"（损失 {dead_of_type}/{slot.count}）"
                )

    # MVP
    print(f"\n  {C.B}🏅 MVP{C.R}")
    all_soldiers = [s for s in (result.red_alive + result.red_dead +
                                result.blue_alive + result.blue_dead)]
    # MVP 综合分 = 伤害×0.5 + 击杀×50
    for s in all_soldiers:
        s._mvp_score = s.total_damage_dealt * 0.5 + s.kills * 50  # type: ignore[attr-defined]

    # 仅胜方评选
    if result.winner is not None:
        mvp_candidates = [
            s for s in all_soldiers if s.side == result.winner
        ]
    else:
        mvp_candidates = all_soldiers

    mvp_candidates.sort(key=lambda s: s._mvp_score, reverse=True)  # type: ignore[attr-defined]
    for i, s in enumerate(mvp_candidates[:3]):
        medal = ["🥇", "🥈", "🥉"][i]
        sc = _side_color(s.side.value)
        print(
            f"    {medal} {sc}{s.name}#{s.id}{C.R}"
            f"  伤害={s.total_damage_dealt:.0f}"
            f"  击杀={s.kills}"
            f"  综合分={s._mvp_score:.0f}"  # type: ignore[attr-defined]
            f"  {'💀' if not s.alive else '❤️'}"
        )

    print(f"\n{C.CYAN}{'━' * 60}{C.R}")


# =====================================================================
# 兵种搜索
# =====================================================================
def find_unit(repo: UnitRepo, query: str) -> Unit | None:
    """搜索兵种，返回最佳匹配。"""
    # 先尝试精确匹配 id
    by_id = repo.get_by_id(query)
    if by_id is not None:
        return by_id

    results = repo.search(query, limit=5)
    if not results:
        print(f"{C.RED}未找到兵种「{query}」{C.R}")
        return None
    # 精确匹配 name / name_en / alias → 直接返回
    q = query.strip().lower()
    if len(results) == 1:
        return results[0]
    for u in results:
        if (u.name.lower() == q or u.name_en.lower() == q
                or q in [a.lower() for a in u.aliases]):
            return u
    # 多个结果，让用户选
    print(f"找到多个匹配：")
    for i, u in enumerate(results, 1):
        cost_str = u.cost_str or "无费用"
        print(f"  {i}. {u.name} ({u.name_en}) — {cost_str} HP={u.hp}")
    while True:
        try:
            ch = input(f"{C.YEL}选择（1-{len(results)}）> {C.R}").strip()
            idx = int(ch)
            if 1 <= idx <= len(results):
                return results[idx - 1]
        except (ValueError, KeyboardInterrupt, EOFError):
            return None


def show_unit_brief(unit: Unit, label: str) -> None:
    """显示兵种简要信息。"""
    lines = [f"  {label}: {unit.name} ({unit.name_en})"]
    lines.append(f"    HP={unit.hp} 速度={unit.speed} 费用={unit.cost_str}")
    if unit.attack_ranged:
        lines.append(
            f"    远程: 攻击={unit.attack_ranged} 射程={unit.range}"
            f" 最小射程={unit.range_min} ROF={unit.rof_ranged}s"
        )
    if unit.attack_melee:
        lines.append(f"    近战: 攻击={unit.attack_melee} ROF={unit.rof_melee}s")
    if unit.attack_siege:
        lines.append(
            f"    攻城: 攻击={unit.attack_siege} 射程={unit.range_siege}"
            f" ROF={unit.rof_siege}s"
        )
    if unit.armor_ranged:
        lines.append(f"    远程抗性={unit.armor_ranged:.0%}")
    if unit.armor_melee:
        lines.append(f"    近战抗性={unit.armor_melee:.0%}")
    if unit.aoe_radius:
        lines.append(f"    AOE半径={unit.aoe_radius}")
    if unit.multipliers_ranged:
        mults = ", ".join(str(m) for m in unit.multipliers_ranged)
        lines.append(f"    远程倍率: {mults}")
    if unit.multipliers_melee:
        mults = ", ".join(str(m) for m in unit.multipliers_melee)
        lines.append(f"    近战倍率: {mults}")
    print("\n".join(lines))


# =====================================================================
# 交互式模式
# =====================================================================
def interactive_mode(repo: UnitRepo, verbose: bool = False, seed: int | None = None) -> None:
    """交互式选兵种 → 跑模拟。"""
    print(f"\n{C.B}{C.CYAN}=== AoE3 斗蛐蛐模拟器 ==={C.R}")
    print(f"{C.DIM}输入兵种名（中/英文均可），输入 quit 退出{C.R}\n")

    while True:
        # 红方
        query = input(f"{C.RED}🔴 红方兵种> {C.R}").strip()
        if query.lower() in ("quit", "q", "exit"):
            break
        red_unit = find_unit(repo, query)
        if red_unit is None:
            continue

        red_count_str = input(f"{C.RED}🔴 红方数量（默认10）> {C.R}").strip()
        red_count = int(red_count_str) if red_count_str.isdigit() else 10

        # 蓝方
        query = input(f"{C.BLUE}🔵 蓝方兵种> {C.R}").strip()
        if query.lower() in ("quit", "q", "exit"):
            break
        blue_unit = find_unit(repo, query)
        if blue_unit is None:
            continue

        blue_count_str = input(f"{C.BLUE}🔵 蓝方数量（默认10）> {C.R}").strip()
        blue_count = int(blue_count_str) if blue_count_str.isdigit() else 10

        # 显示双方信息
        print(f"\n{C.B}对阵信息：{C.R}")
        show_unit_brief(red_unit, f"{C.RED}🔴 红方{C.R}")
        show_unit_brief(blue_unit, f"{C.BLUE}🔵 蓝方{C.R}")

        # 跑模拟
        print(f"\n{C.DIM}模拟中...{C.R}")
        sim = BattleSimulator(
            red_unit, red_count, blue_unit, blue_count, seed=seed
        )
        result = sim.run()

        # 输出
        print_events(result, verbose=verbose)
        print_report(result)

        # 再来一局？
        again = input(f"\n{C.YEL}再来一局？(y/N) > {C.R}").strip().lower()
        if again not in ("y", "yes", "是"):
            break

    print(f"\n{C.CYAN}拜拜 🎮{C.R}")


# =====================================================================
# 参数式模式
# =====================================================================
def parse_unit_spec(repo: UnitRepo, spec: str) -> tuple[Unit, int] | None:
    """解析 'musketeer:10' 或 '火枪手:10' 格式。"""
    parts = spec.rsplit(":", 1)
    if len(parts) == 2:
        name, count_str = parts
        try:
            count = int(count_str)
        except ValueError:
            print(f"{C.RED}数量格式错误：{count_str}{C.R}")
            return None
    else:
        name = parts[0]
        count = 10

    unit = find_unit(repo, name)
    if unit is None:
        return None
    return unit, count




# =====================================================================
# 靶机模式
# =====================================================================
def run_dummy_mode(repo: UnitRepo, args) -> None:
    """靶机模式：红方攻击不动不攻击的靶机，用于验证 windup/DPS 等数据。"""
    from dataclasses import replace as dc_replace

    # 解析攻击方
    spec = parse_unit_spec(repo, args.dummy)
    if spec is None:
        return
    atk_unit, atk_count = spec

    # 创建靶机 Unit（HP 极高、不攻击、不移动）
    dummy_unit = Unit(
        id="__dummy__",
        name="靶机",
        name_en="TargetDummy",
        hp=args.dummy_hp,
        speed=0.0,
        attack_ranged=0.0,
        attack_melee=0.0,
        attack_siege=0.0,
    )

    print(f"\n{C.B}{'═' * 60}{C.R}")
    print(f"{C.B}  🎯 靶机模式{C.R}")
    print(f"{C.B}{'═' * 60}{C.R}")
    print(f"\n  {C.RED}🔴 攻击方{C.R}: {atk_unit.name} ({atk_unit.name_en}) ×{atk_count}")
    print(f"      攻击(远程)={atk_unit.attack_ranged}  射程={atk_unit.range}")
    print(f"      攻击(近战)={atk_unit.attack_melee}")
    print(f"      windup_ranged={atk_unit.windup_ranged}s  windup_melee={atk_unit.windup_melee}s")
    print(f"      rof_ranged={atk_unit.rof_ranged}s  rof_melee={atk_unit.rof_melee}s")
    print(f"      speed={atk_unit.speed}")
    print(f"\n  {C.BLUE}🔵 靶机{C.R}: HP={args.dummy_hp} ×{args.dummy_count}")
    print(f"      不攻击、不移动")

    # 运行模拟
    sim = BattleSimulator(
        red_army=[(atk_unit, atk_count)],
        blue_army=[(dummy_unit, args.dummy_count)],
        seed=args.seed,
    )
    result = sim.run()

    # 统计分析
    print(f"\n{C.B}{'─' * 60}{C.R}")
    print(f"{C.B}  📊 统计结果{C.R}")
    print(f"{C.B}{'─' * 60}{C.R}")

    # 找首发时间
    first_attack_tick = None
    total_damage = 0.0
    attack_count = 0
    last_attack_tick = 0
    first_attack_per_soldier: dict[int, int] = {}

    for ev in result.events:
        if ev.event_type != EventType.ATTACK:
            continue
        d = ev.data
        if d.get("attacker_side") != "red":
            continue
        tick = ev.tick
        sid = d.get("attacker_id", 0)
        if first_attack_tick is None:
            first_attack_tick = tick
        if sid not in first_attack_per_soldier:
            first_attack_per_soldier[sid] = tick
        total_damage += d.get("damage", 0)
        attack_count += 1
        last_attack_tick = tick

    from plugins.games.aoe3_battle.simulator import TICK_INTERVAL

    if first_attack_tick is not None:
        first_attack_time = first_attack_tick * TICK_INTERVAL
        duration = (last_attack_tick - first_attack_tick) * TICK_INTERVAL
        print(f"\n  首发时间: tick={first_attack_tick} ({first_attack_time:.2f}s)")

        # 预期首发时间 = 移动时间 + windup
        # 场地长度 36，红方从 0 出发，蓝方在 36
        # 移动时间 ≈ (36 - range) / speed
        if atk_unit.range > 0 and atk_unit.speed > 0:
            move_time = max(0, (36.0 - atk_unit.range) / atk_unit.speed)
            expected_first = move_time + atk_unit.windup_ranged
            print(f"  预期首发: 移动{move_time:.2f}s + windup{atk_unit.windup_ranged}s = {expected_first:.2f}s")
        elif atk_unit.speed > 0:
            move_time = max(0, (36.0 - 1.5) / atk_unit.speed)
            expected_first = move_time + atk_unit.windup_melee
            print(f"  预期首发: 移动{move_time:.2f}s + windup{atk_unit.windup_melee}s = {expected_first:.2f}s")

        print(f"\n  总攻击次数: {attack_count}")
        print(f"  总伤害: {total_damage:.1f}")
        if duration > 0:
            dps = total_damage / duration
            print(f"  DPS（首发后）: {dps:.1f}")
        print(f"  靶机剩余 HP: {args.dummy_hp - total_damage:.1f}")

        # 每个士兵的首发时间
        if len(first_attack_per_soldier) > 1:
            print(f"\n  各士兵首发时间:")
            for sid, tick in sorted(first_attack_per_soldier.items()):
                t = tick * TICK_INTERVAL
                print(f"    #{sid}: tick={tick} ({t:.2f}s)")
    else:
        print(f"\n  ⚠️ 没有发生攻击事件！")

    print(f"\n  战斗时长: {result.duration}s ({result.ticks} ticks)")
    print(f"  结果: {'超时' if result.ticks >= 1200 else '结束'}")
    print(f"\n{C.CYAN}{'═' * 60}{C.R}")


# =====================================================================
# 主入口
# =====================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="AoE3 斗蛐蛐模拟器")
    parser.add_argument("--red", type=str, help="红方兵种:数量，如 musketeer:10")
    parser.add_argument("--blue", type=str, help="蓝方兵种:数量，如 pikeman:8")
    parser.add_argument(
        "--random", action="store_true", help="随机生成押注模式阵容"
    )
    parser.add_argument(
        "--duel", action="store_true", help="随机生成单挑模式阵容"
    )
    parser.add_argument(
        "--blacklist", action="store_true", help="随机生成黑名单乱斗阵容"
    )
    parser.add_argument(
        "--broadcast", action="store_true", help="输出播报话术（模拟群消息效果）"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="显示详细事件流（含每次攻击）"
    )
    parser.add_argument("--seed", type=int, default=None, help="随机种子（可复现）")
    parser.add_argument(
        "--debug", action="store_true", help="启用 DEBUG 级别日志"
    )
    parser.add_argument(
        "--dummy", type=str, default=None,
        help="靶机模式：指定攻击方兵种:数量（如 musketeer:5），蓝方为不动不攻击的靶机"
    )
    parser.add_argument(
        "--dummy-hp", type=int, default=99999,
        help="靶机 HP（默认 99999）"
    )
    parser.add_argument(
        "--dummy-count", type=int, default=1,
        help="靶机数量（默认 1）"
    )
    args = parser.parse_args()

    # 日志配置
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    # 模拟器日志单独控制
    sim_logger = logging.getLogger("aoe3_battle.simulator")
    sim_logger.setLevel(log_level)

    # 加载数据
    repo = UnitRepo.get()
    print(f"{C.DIM}已加载 {len(repo.all_units)} 个兵种{C.R}")

    import random as _random
    rng = _random.Random(args.seed)

    if args.dummy:
        # 靶机模式
        run_dummy_mode(repo, args)
        return

    if args.random or args.duel or args.blacklist:
        # 随机阵容模式
        if args.duel:
            match = generate_duel_lineup(repo, rng=rng)
        elif args.blacklist:
            match = generate_blacklist_lineup(repo, rng=rng)
        else:
            match = generate_bet_lineup(repo, rng=rng)

        # 打印对阵面板
        panel = format_matchup_panel(match)
        print(f"\n{C.B}{panel}{C.R}")
        print()
        for slot in match.red.slots:
            show_unit_brief(slot.unit, f"{C.RED}🔴 红方{C.R}")
        for slot in match.blue.slots:
            show_unit_brief(slot.unit, f"{C.BLUE}🔵 蓝方{C.R}")

    elif args.red and args.blue:
        # 参数式
        red_spec = parse_unit_spec(repo, args.red)
        blue_spec = parse_unit_spec(repo, args.blue)
        if red_spec is None or blue_spec is None:
            sys.exit(1)

        red_unit, red_count = red_spec
        blue_unit, blue_count = blue_spec

        print(f"\n{C.B}对阵信息：{C.R}")
        show_unit_brief(red_unit, f"{C.RED}🔴 红方{C.R}")
        show_unit_brief(blue_unit, f"{C.BLUE}🔵 蓝方{C.R}")
    else:
        # 交互式
        interactive_mode(repo, verbose=args.verbose, seed=args.seed)
        return

    # 跑模拟
    print(f"\n{C.DIM}模拟中...{C.R}")
    is_duel = args.duel
    if args.random or args.duel or args.blacklist:
        # 随机阵容模式：始终用新式接口（支持多兵种）
        sim = BattleSimulator(
            red_army=[(s.unit, s.count) for s in match.red.slots],
            blue_army=[(s.unit, s.count) for s in match.blue.slots],
            seed=args.seed,
            duel_mode=is_duel,
        )
    else:
        sim = BattleSimulator(
            red_unit, red_count, blue_unit, blue_count,
            seed=args.seed,
            duel_mode=is_duel,
        )
    result = sim.run()

    # 输出事件流
    print_events(result, verbose=args.verbose)

    # 播报话术
    if args.broadcast:
        print(f"\n{C.B}{C.MAG}{'━' * 60}{C.R}")
        print(f"{C.B}{C.MAG}  播报话术（模拟群消息）{C.R}")
        print(f"{C.MAG}{'━' * 60}{C.R}")
        bc = Broadcaster(result, seed=args.seed)
        segments = bc.generate()
        for seg in segments:
            if seg.is_key_event:
                print(f"\n{C.B}{seg.text}{C.R}")
            else:
                print(f"\n{seg.text}")
            if seg.should_sleep:
                print(f"{C.DIM}  [sleep 2s]{C.R}")
        # 最终战报
        print(f"\n{C.B}{format_battle_report(result)}{C.R}")

    # 详细战报
    print_report(result)


if __name__ == "__main__":
    main()
