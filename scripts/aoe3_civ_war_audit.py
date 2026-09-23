"""List resolved generic civ-war archetypes for the 24 playable main civs.

Usage:
    uv run python scripts/aoe3_civ_war_audit.py
    uv run python scripts/aoe3_civ_war_audit.py --age 4 --all

This read-only audit does not register QQ commands or decide lineup shares/matchups.
"""

from __future__ import annotations

import argparse
import io
import logging
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (str(ROOT), str(ROOT / "src")):
    if path not in sys.path:
        sys.path.insert(0, path)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.disable(logging.CRITICAL)

from plugins.aoe3.repository import UnitRepo  # noqa: E402
from plugins.games.aoe3_battle.civ_war_lineups import generate_civ_candidates  # noqa: E402
from plugins.games.aoe3_battle.civ_war_matchup import rank_matchups  # noqa: E402
from plugins.games.aoe3_battle.civ_war_roles import (  # noqa: E402
    civ_regular_units,
    load_curated_civ_units,
    resolve_archetypes,
)
from plugins.games.aoe3_battle.lineup import _unit_cost, get_bet_pool  # noqa: E402
from plugins.games.aoe3_battle.battle_contract import Side  # noqa: E402
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D  # noqa: E402


def _remaining_value(soldiers: list) -> float:
    return sum(
        _unit_cost(soldier.unit) * soldier.hp / max(1.0, soldier.max_hp)
        for soldier in soldiers
    )


def _simulate_estimate(estimate, *, runs: int) -> tuple[int, int, int, float]:
    red_wins = blue_wins = draws = 0
    margins: list[float] = []
    red_army = [(slot.unit, slot.count) for slot in estimate.red_lineup.slots]
    blue_army = [(slot.unit, slot.count) for slot in estimate.blue_lineup.slots]
    for simulation_seed in range(runs):
        for swapped in (False, True):
            result = BattleSimulator2D(
                red_army=blue_army if swapped else red_army,
                blue_army=red_army if swapped else blue_army,
                seed=simulation_seed,
            ).run()
            if result.winner is None:
                draws += 1
            elif (result.winner == Side.RED) != swapped:
                red_wins += 1
            else:
                blue_wins += 1

            result_red = _remaining_value(result.red_alive)
            result_blue = _remaining_value(result.blue_alive)
            if swapped:
                result_red, result_blue = result_blue, result_red
            red_fraction = result_red / max(1, estimate.red_lineup.total_cost)
            blue_fraction = result_blue / max(1, estimate.blue_lineup.total_cost)
            margins.append(abs(red_fraction - blue_fraction))
    return red_wins, blue_wins, draws, sum(margins) / len(margins)


def _print_matchup_audit(
    repo: UnitRepo,
    civ_a: str,
    civ_b: str,
    *,
    age: int,
    budget: int,
    top: int,
    seed: int,
    simulate_top: int,
    runs: int,
) -> None:
    ranked = rank_matchups(
        generate_civ_candidates(repo, civ_a, age=age),
        generate_civ_candidates(repo, civ_b, age=age),
        age=age,
        budget=budget,
    )
    if not ranked:
        print("没有可用对阵")
        return
    shown = ranked[:max(1, top)]
    print(f"## {civ_a} vs {civ_b} | age={age} budget={budget}")
    for index, estimate in enumerate(shown, start=1):
        red = " + ".join(
            f"{slot.unit.id}x{slot.count}" for slot in estimate.red_lineup.slots
        )
        blue = " + ".join(
            f"{slot.unit.id}x{slot.count}" for slot in estimate.blue_lineup.slots
        )
        print(
            f"{index:2}. {estimate.red_candidate.title} [{red}] vs "
            f"{estimate.blue_candidate.title} [{blue}] | "
            f"gap={estimate.balance_gap:.3f} score={estimate.selection_score:.3f}"
        )
        if index <= simulate_top:
            red_wins, blue_wins, draws, margin = _simulate_estimate(estimate, runs=runs)
            print(
                f"    offline simulator (swapped sides): "
                f"{red_wins}W-{blue_wins}L-{draws}D, remaining-value margin={margin:.3f}"
            )
    chosen = random.Random(seed).choice(shown)
    print(
        f"\nseed={seed} 从上述 {len(shown)} 条抽中: "
        f"{chosen.red_candidate.title} vs {chosen.blue_candidate.title}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="AoE3 civ-war generic-archetype audit")
    parser.add_argument("--age", type=int, default=3, choices=range(2, 6))
    parser.add_argument("--budget", type=int, default=10000)
    parser.add_argument("--versus", nargs=2, metavar=("CIV_A", "CIV_B"))
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--simulate-top",
        type=int,
        default=0,
        help="离线实跑前 N 条静态候选, 每条会交换红蓝阵营",
    )
    parser.add_argument("--runs", type=int, default=2, help="每个阵营方向的模拟次数")
    parser.add_argument(
        "--all",
        action="store_true",
        help="输出每个骨架的全部具体候选, 默认每类最多展示 3 条",
    )
    args = parser.parse_args()

    repo = UnitRepo.get()
    civ_units = load_curated_civ_units()
    if args.versus:
        civ_a, civ_b = args.versus
        if civ_a not in civ_units or civ_b not in civ_units:
            raise SystemExit("--versus 必须使用 curated_civs 中的文明 id")
        _print_matchup_audit(
            repo,
            civ_a,
            civ_b,
            age=args.age,
            budget=args.budget,
            top=args.top,
            seed=args.seed,
            simulate_top=max(0, min(args.simulate_top, args.top)),
            runs=max(1, args.runs),
        )
        return
    pool = get_bet_pool(repo, age=args.age)

    for civ_id in civ_units:
        units = civ_regular_units(civ_id, pool, civ_units=civ_units)
        grouped: dict[str, list[tuple[str, ...]]] = defaultdict(list)
        titles: dict[str, str] = {}
        candidates = resolve_archetypes(units)
        candidates.sort(
            key=lambda candidate: sum(
                any(tag.startswith("AbstractConsulate") for tag in unit.type)
                for unit in candidate.units
            )
        )
        for candidate in candidates:
            if all(
                any(tag.startswith("AbstractConsulate") for tag in unit.type)
                for unit in candidate.units
            ):
                continue
            grouped[candidate.archetype.id].append(candidate.unit_ids)
            titles[candidate.archetype.id] = candidate.archetype.title

        print(f"\n## {civ_id} ({len(units)} 个正规军单位)")
        if not grouped:
            print("  无通用骨架候选")
            continue
        for archetype_id, candidates in grouped.items():
            shown = candidates if args.all else candidates[:3]
            examples = "; ".join(" + ".join(ids) for ids in shown)
            suffix = "" if len(shown) == len(candidates) else f", 另有 {len(candidates) - len(shown)} 条"
            print(f"  {titles[archetype_id]}: {len(candidates)} 条 - {examples}{suffix}")


if __name__ == "__main__":
    main()
