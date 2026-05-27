"""押注/单挑阵容抽样模拟 —— 统计胜方余量、平局、耗时。

用法:
  uv run python scripts/ra2_lineup_audit.py
  uv run python scripts/ra2_lineup_audit.py --bet-seeds 40 --duel-seeds 20 --sim-seeds 3
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from plugins.games.ra2_battle.lineup import (  # noqa: E402
    MatchLineup,
    generate_bet_lineup,
    generate_duel_lineup,
)
from plugins.games.ra2_battle.simulator import BattleSimulator, Side  # noqa: E402


def _arena_for(units: int) -> tuple[int, int, int]:
    if units >= 50:
        return 18, 9, 4500
    if units >= 30:
        return 20, 10, 6000
    if units >= 18:
        return 18, 9, 7000
    return 16, 8, 8000


def _army_from_match(side, stars: int) -> list[tuple[str, int, int]]:
    return [(s.actor_id, s.count, stars) for s in side.slots]


def _count_army(match: MatchLineup, color: str) -> int:
    side = match.red if color == "red" else match.blue
    return sum(s.count for s in side.slots)


@dataclass
class CaseStats:
    label: str
    runs: int = 0
    draws: int = 0
    red_wins: int = 0
    blue_wins: int = 0
    win_surv: list[float] = field(default_factory=list)
    win_cas: list[float] = field(default_factory=list)
    lose_wipe: list[float] = field(default_factory=list)
    ticks: list[int] = field(default_factory=list)
    ms: list[float] = field(default_factory=list)

    def record(
        self,
        result,
        *,
        red_start: int,
        blue_start: int,
        elapsed_ms: float,
    ) -> None:
        self.runs += 1
        self.ticks.append(result.ticks)
        self.ms.append(elapsed_ms)
        if result.winner is None:
            self.draws += 1
            return
        # 用 result.*_count（初始编制），避免航母补蜂等导致 alive > start
        red_start = result.red_count
        blue_start = result.blue_count
        if result.winner == Side.RED:
            self.red_wins += 1
            w_start, l_start = red_start, blue_start
            w_alive, w_dead = len(result.red_alive), len(result.red_dead)
            l_dead = len(result.blue_dead)
        else:
            self.blue_wins += 1
            w_start, l_start = blue_start, red_start
            w_alive, w_dead = len(result.blue_alive), len(result.blue_dead)
            l_dead = len(result.red_dead)
        self.win_surv.append(min(1.0, w_alive / w_start))
        self.win_cas.append(min(1.0, w_dead / w_start))
        self.lose_wipe.append(min(1.0, l_dead / l_start))

    def summary(self) -> str:
        resolved = self.runs - self.draws
        dom = "红" if self.red_wins >= self.blue_wins else "蓝"
        dom_rate = max(self.red_wins, self.blue_wins) / self.runs if self.runs else 0
        surv = statistics.mean(self.win_surv) if self.win_surv else None
        cas = statistics.mean(self.win_cas) if self.win_cas else None
        wipe = statistics.mean(self.lose_wipe) if self.lose_wipe else None
        avg_tick = statistics.mean(self.ticks) if self.ticks else 0
        avg_ms = statistics.mean(self.ms) if self.ms else 0

        def pct(v: float | None) -> str:
            return f"{v:.0%}" if v is not None else "n/a"

        flags: list[str] = []
        if self.runs and self.draws / self.runs >= 0.10:
            flags.append("平局偏高")
        if dom_rate >= 0.85 and resolved >= 3:
            flags.append(f"{dom}碾压")
        if surv is not None and surv > 0.85:
            flags.append("胜方余量过高")
        if surv is not None and surv < 0.15 and cas and cas > 0.7:
            flags.append("惨胜")
        if wipe is not None and wipe < 0.70:
            flags.append("败方未打光")

        flag_s = f" [!{','.join(flags)}]" if flags else ""
        return (
            f"{self.label}: n={self.runs} 平{self.draws} R{self.red_wins}/B{self.blue_wins} "
            f"胜方余量={pct(surv)} 胜方伤亡={pct(cas)} 败方歼={pct(wipe)} "
            f"tick≈{avg_tick:.0f} {avg_ms:.0f}ms{flag_s}"
        )


def _simulate_match(match: MatchLineup, sim_seed: int) -> tuple[object, float]:
    stars = match.initial_stars
    red = _army_from_match(match.red, stars)
    blue = _army_from_match(match.blue, stars)
    units = _count_army(match, "red") + _count_army(match, "blue")
    w, h, max_ticks = _arena_for(units)
    t0 = time.perf_counter()
    result = BattleSimulator(
        red, blue, seed=sim_seed, max_ticks=max_ticks, width=w, height=h
    ).run()
    return result, (time.perf_counter() - t0) * 1000


def audit_bet(bet_seeds: int, sim_seeds: int) -> dict[str, CaseStats]:
    by_kind: dict[str, CaseStats] = defaultdict(CaseStats)
    seen_lineups: dict[str, CaseStats] = {}

    for lineup_seed in range(bet_seeds):
        match = generate_bet_lineup(budget=10000, seed=lineup_seed)
        kind = "classic" if match.scenario_title else "random"
        theater = match.theater
        key = f"{kind}/{theater}"
        if key not in by_kind:
            by_kind[key] = CaseStats(label=key)
        bucket = by_kind[key]

        lineup_key = match.scenario_title or _lineup_key(match)
        if lineup_key not in seen_lineups:
            seen_lineups[lineup_key] = CaseStats(label=lineup_key)

        for sim_seed in range(sim_seeds):
            result, ms = _simulate_match(match, lineup_seed * 1000 + sim_seed)
            rs, bs = _count_army(match, "red"), _count_army(match, "blue")
            bucket.record(result, red_start=rs, blue_start=bs, elapsed_ms=ms)
            seen_lineups[lineup_key].record(result, red_start=rs, blue_start=bs, elapsed_ms=ms)

    print("\n=== 押注模式分组 ===")
    for key in sorted(by_kind):
        print(by_kind[key].summary())

    print("\n=== 押注模式 · 重复阵容 Top（≥2 次 lineup seed 命中或经典局）===")
    dupes = [(k, v) for k, v in seen_lineups.items() if v.runs >= sim_seeds]
    dupes.sort(key=lambda x: -x[1].runs)
    for key, st in dupes[:12]:
        print(st.summary())

    return dict(by_kind)


def _lineup_key(match: MatchLineup) -> str:
    def fmt(side) -> str:
        return "+".join(f"{s.actor_id}×{s.count}" for s in side.slots)

    return f"{fmt(match.red)} vs {fmt(match.blue)}"


def audit_duel(duel_seeds: int) -> CaseStats:
    st = CaseStats(label="duel")
    for seed in range(duel_seeds):
        match = generate_duel_lineup(seed=seed)
        result, ms = _simulate_match(match, seed)
        st.record(
            result,
            red_start=_count_army(match, "red"),
            blue_start=_count_army(match, "blue"),
            elapsed_ms=ms,
        )
    print("\n=== 单挑模式 ===")
    print(st.summary())
    return st


def audit_classics(sim_seeds: int) -> None:
    from plugins.games.ra2_battle.lineup import (
        _load_classic_scenarios,
        _parse_army,
        _side_from_army,
        MatchLineup,
    )
    from plugins.games.ra2_battle.repo import load_actors

    actors = load_actors()
    print("\n=== 经典局逐条（各 %d seed）===" % sim_seeds)
    for sc in _load_classic_scenarios():
        red_army = _parse_army(sc["red"])
        blue_army = _parse_army(sc["blue"])
        match = MatchLineup(
            red=_side_from_army(red_army, actors),
            blue=_side_from_army(blue_army, actors),
            mode="bet",
            theater=sc["theater"],
            scenario_title=sc["title"],
            initial_stars=0,
        )
        st = CaseStats(label=str(sc["title"]))
        for seed in range(sim_seeds):
            match.initial_stars = (0, 1, 3)[seed % 3]
            result, ms = _simulate_match(match, seed)
            st.record(
                result,
                red_start=0,
                blue_start=0,
                elapsed_ms=ms,
            )
        print(st.summary())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bet-seeds", type=int, default=40, help="押注 lineup 抽样数")
    ap.add_argument("--duel-seeds", type=int, default=20, help="单挑抽样数")
    ap.add_argument("--sim-seeds", type=int, default=3, help="每个 lineup 模拟次数")
    ap.add_argument("--classic-only", action="store_true", help="仅跑 classic_scenarios.json")
    args = ap.parse_args()

    print(
        f"红警阵容审计 bet={args.bet_seeds}x{args.sim_seeds} duel={args.duel_seeds} "
        f"(预算10000, 含出战星级)"
    )
    t0 = time.perf_counter()
    if args.classic_only:
        audit_classics(args.sim_seeds)
    else:
        audit_bet(args.bet_seeds, args.sim_seeds)
        audit_duel(args.duel_seeds)
        audit_classics(6)
    print(f"\n总耗时 {(time.perf_counter() - t0):.1f}s")


if __name__ == "__main__":
    main()
