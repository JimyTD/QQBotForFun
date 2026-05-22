"""红警2斗蛐蛐 —— 全兵种抽检 + 星级/规模 + 性能。"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for p in (str(_ROOT), str(_SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from plugins.games.ra2_battle.battle_pool import (
    LINEUP_BLACKLIST,
    lineup_eligible_ids,
)
from plugins.games.ra2_battle.lineup import generate_bet_lineup, generate_duel_lineup
from plugins.games.ra2_battle.repo import load_actors
from plugins.games.ra2_battle.simulator import BattleSimulator

Army = list[tuple[str, int] | tuple[str, int, int]]


def _parse(spec: str) -> Army:
    out: Army = []
    for part in spec.split(","):
        bits = part.strip().split(":")
        uid = bits[0].strip()
        cnt = int(bits[1])
        if len(bits) >= 3:
            out.append((uid, cnt, max(1, min(3, int(bits[2])))))
        else:
            out.append((uid, cnt))
    return out


def _run_once(red: Army, blue: Army, seed: int):
    t0 = time.perf_counter()
    r = BattleSimulator(red, blue, seed=seed, width=14, height=8).run()
    ms = (time.perf_counter() - t0) * 1000
    return r, ms


# 代表性固定阵容（含特殊机制、星级、规模）
SCENARIOS: list[tuple[str, str, str]] = [
    ("htnk:3", "mtnk:3", "犀牛 vs 灰熊"),
    ("htnk:1:3", "htnk:1:1", "三星犀牛 vs 一星犀牛"),
    ("e1:1", "e2:25", "1大兵 vs 25动员兵"),
    ("e1:20:2", "e2:3:1", "20二星大兵 vs 3动员兵"),
    ("apoc:1:3", "htnk:5:1", "三星天启 vs 5犀牛"),
    ("yuri:1:2", "htnk:1", "尤里 vs 犀牛"),
    ("carrier:1", "e1:8", "航母 vs 8大兵"),
    ("htk:2", "e1:10", "防空履带 vs 大兵"),
    ("ttnk:1:2", "mtnk:3", "二星磁能 vs 3灰熊"),
    ("ccomand:1:3", "e1:8", "三星超时空兵 vs 大兵"),
    ("deso:2", "e1:12", "辐射兵 vs 大兵群"),
    ("flakt:6", "htnk:2", "防空步兵 vs 犀牛"),
    ("aegis:1", "e1:8", "神盾 vs 大兵"),
    ("dog:4", "e1:6", "警犬 vs 大兵"),
    ("dtruck:1", "htnk:2", "自爆车 vs 犀牛"),
]


def main() -> None:
    actors = load_actors()
    eligible = lineup_eligible_ids(actors)
    print(f"导出单位 {len(actors)}，斗蛐蛐池 {len(eligible)}，黑名单 {len(LINEUP_BLACKLIST)}\n")
    print("黑名单:", ", ".join(sorted(LINEUP_BLACKLIST)))

    print("\n=== 固定阵容抽检（各 10 种子）===")
    for red_s, blue_s, title in SCENARIOS:
        red = _parse(red_s)
        blue = _parse(blue_s)
        wins = {"red": 0, "blue": 0, "draw": 0}
        times: list[float] = []
        for seed in range(10):
            r, ms = _run_once(red, blue, seed)
            times.append(ms)
            if r.winner is None:
                wins["draw"] += 1
            else:
                wins[r.winner.value] += 1
        r0, _ = _run_once(red, blue, 0)
        print(
            f"{title}: 红{wins['red']} 蓝{wins['blue']} 平{wins['draw']} "
            f"| 均 {statistics.mean(times):.0f}ms "
            f"| tick={r0.ticks} 胜={r0.winner}"
        )

    print("\n=== 阵容池每兵种 1v3大兵（单种子）===")
    pool_times: list[float] = []
    fails: list[str] = []
    for aid in eligible:
        try:
            _, ms = _run_once([(aid, 1, 1)], [("e1", 3, 1)], hash(aid) % 100000)
            pool_times.append(ms)
        except Exception as exc:
            fails.append(f"{aid}: {exc}")
    print(f"完成 {len(pool_times)}/{len(eligible)}，失败 {fails or '无'}")
    if pool_times:
        print(f"均 {statistics.mean(pool_times):.0f}ms 最大 {max(pool_times):.0f}ms")

    print("\n=== 随机阵容 15 局（预算 5000）===")
    sim_times: list[float] = []
    for i in range(15):
        m = generate_bet_lineup(budget=5000, seed=i)
        red = [(s.actor_id, s.count) for s in m.red.slots]
        blue = [(s.actor_id, s.count) for s in m.blue.slots]
        r, ms = _run_once(red, blue, seed=i + 200)
        sim_times.append(ms)
        print(f"#{i+1} {r.winner} ticks={r.ticks} {ms:.0f}ms | 红{red} vs 蓝{blue}")

    print("\n=== 单挑随机 5 局 ===")
    for i in range(5):
        m = generate_duel_lineup(seed=i + 50)
        aid_r = m.red.slots[0].actor_id
        aid_b = m.blue.slots[0].actor_id
        r, ms = _run_once([(aid_r, 1, 2)], [(aid_b, 1, 2)], seed=i)
        print(f"duel #{i+1} {aid_r} vs {aid_b} -> {r.winner} {ms:.0f}ms")

    print("\n=== 压力 50v50 ===")
    big = [("e1", 50), ("e2", 50)]
    r, ms = _run_once(big, big, 42)
    print(f"tick={r.ticks} {ms:.0f}ms 胜={r.winner}")

    print("\n=== 汇总 ===")
    if sim_times:
        print(f"随机15局: 均 {statistics.mean(sim_times):.0f}ms 最大 {max(sim_times):.0f}ms")


if __name__ == "__main__":
    main()
