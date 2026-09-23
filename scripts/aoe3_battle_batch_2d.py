# ruff: noqa: RUF001
"""Batch-run the independent 2D simulator and report diagnostics.

This tool is deliberately separate from production game and economy code.
It is meant for large local regression and movement-quality sweeps.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for path in (str(_ROOT), str(_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from plugins.aoe3.models import Unit  # noqa: E402
from plugins.aoe3.repository import UnitRepo  # noqa: E402
from plugins.games.aoe3_battle.civ_war_civs import (  # noqa: E402
    get_civ_profile,
    pick_random_civs,
)
from plugins.games.aoe3_battle.civ_war_matchup import (  # noqa: E402
    generate_civ_war_lineup,
)
from plugins.games.aoe3_battle.simulator2d import (  # noqa: E402
    BattleSimulator2D,
    Simulation2DConfig,
)


def parse_unit(repo: UnitRepo, spec: str) -> tuple[Unit, int]:
    unit_id, separator, count_text = spec.rpartition(":")
    if not separator or not unit_id or not count_text:
        raise ValueError(f"invalid unit spec: {spec}")
    count = int(count_text)
    if count <= 0:
        raise ValueError(f"count must be positive: {spec}")
    unit = repo.get_by_id(unit_id) or next(
        iter(repo.search(unit_id, limit=1)),
        None,
    )
    if unit is None:
        raise ValueError(f"unit not found: {unit_id}")
    return unit, count


def run_one(
    *,
    red_unit: Unit,
    red_count: int,
    blue_unit: Unit,
    blue_count: int,
    seed: int,
    config: Simulation2DConfig,
) -> dict[str, Any]:
    frames: list[dict[str, Any]] = []
    simulator = BattleSimulator2D(
        red_unit,
        red_count,
        blue_unit,
        blue_count,
        seed=seed,
        session_id=f"batch_{seed}",
        config=config,
        frame_callback=frames.append,
    )
    started = time.perf_counter()
    result = simulator.run()
    elapsed = time.perf_counter() - started

    max_residual_overlap = max(
        (
            frame.get("summary", {}).get("max_overlap", 0.0)
            for frame in frames
        ),
        default=0.0,
    )
    max_no_progress_units = max(
        (
            frame.get("summary", {}).get("no_progress_units", 0)
            for frame in frames
        ),
        default=0,
    )
    max_no_progress_ticks = max(
        (
            frame.get("summary", {}).get("max_no_progress_ticks", 0)
            for frame in frames
        ),
        default=0,
    )
    total_fallbacks = sum(
        frame.get("summary", {}).get("solver_fallbacks", 0)
        for frame in frames
    )
    winner = result.winner.value if result.winner is not None else "draw"
    return {
        "seed": seed,
        "winner": winner,
        "duration": round(result.duration, 2),
        "ticks": result.ticks,
        "timeout": result.timeout,
        "red_alive": len(result.red_alive),
        "blue_alive": len(result.blue_alive),
        "red_dead": len(result.red_dead),
        "blue_dead": len(result.blue_dead),
        "max_residual_overlap": round(max_residual_overlap, 4),
        "max_no_progress_units": max_no_progress_units,
        "max_no_progress_ticks": max_no_progress_ticks,
        "solver_fallbacks": total_fallbacks,
        "elapsed_ms": round(elapsed * 1000, 1),
    }


def run_civ_war_one(
    *,
    repo: UnitRepo,
    red_civ: str,
    blue_civ: str,
    seed: int,
    age: int,
    config: Simulation2DConfig,
) -> dict[str, Any]:
    match, estimate = generate_civ_war_lineup(
        repo,
        red_civ,
        blue_civ,
        age=age,
        rng=random.Random(seed),
    )
    frames: list[dict[str, Any]] = []
    simulator = BattleSimulator2D(
        red_army=[(slot.unit, slot.count) for slot in match.red.slots],
        blue_army=[(slot.unit, slot.count) for slot in match.blue.slots],
        seed=seed,
        session_id=f"civwar_{seed}",
        match_label=(
            f"国战 · {match.red_civ_name}（{match.red_strategy}） "
            f"vs {match.blue_civ_name}（{match.blue_strategy}）"
        ),
        config=config,
        frame_callback=frames.append,
    )
    started = time.perf_counter()
    result = simulator.run()
    elapsed = time.perf_counter() - started
    winner = result.winner.value if result.winner is not None else "draw"

    def composition(lineup) -> list[dict[str, Any]]:
        return [
            {
                "unit_id": slot.unit.id,
                "name": slot.unit.name or slot.unit.name_en,
                "count": slot.count,
            }
            for slot in lineup.slots
        ]

    return {
        "seed": seed,
        "red_civ": get_civ_profile(red_civ).name,
        "blue_civ": get_civ_profile(blue_civ).name,
        "red_strategy": match.red_strategy,
        "blue_strategy": match.blue_strategy,
        "red_composition": composition(match.red),
        "blue_composition": composition(match.blue),
        "static_gap": round(estimate.balance_gap, 4),
        "winner": winner,
        "duration": round(result.duration, 2),
        "ticks": result.ticks,
        "timeout": result.timeout,
        "red_alive": len(result.red_alive),
        "blue_alive": len(result.blue_alive),
        "red_dead": len(result.red_dead),
        "blue_dead": len(result.blue_dead),
        "max_residual_overlap": round(
            max(
                (
                    frame.get("summary", {}).get("max_overlap", 0.0)
                    for frame in frames
                ),
                default=0.0,
            ),
            4,
        ),
        "max_no_progress_units": max(
            (
                frame.get("summary", {}).get("no_progress_units", 0)
                for frame in frames
            ),
            default=0,
        ),
        "max_no_progress_ticks": max(
            (
                frame.get("summary", {}).get("max_no_progress_ticks", 0)
                for frame in frames
            ),
            default=0,
        ),
        "solver_fallbacks": sum(
            frame.get("summary", {}).get("solver_fallbacks", 0)
            for frame in frames
        ),
        "elapsed_ms": round(elapsed * 1000, 1),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    winners = {"red": 0, "blue": 0, "draw": 0}
    for row in rows:
        winners[row["winner"]] += 1

    def values(key: str) -> list[float]:
        return [float(row[key]) for row in rows]

    return {
        "games": len(rows),
        "winners": winners,
        "timeout_games": sum(1 for row in rows if row["timeout"]),
        "duration_avg": round(statistics.mean(values("duration")), 2),
        "duration_max": round(max(values("duration")), 2),
        "elapsed_ms_avg": round(statistics.mean(values("elapsed_ms")), 1),
        "elapsed_ms_max": round(max(values("elapsed_ms")), 1),
        "max_residual_overlap": round(max(values("max_residual_overlap")), 4),
        "max_no_progress_units": int(max(values("max_no_progress_units"))),
        "max_no_progress_ticks": int(max(values("max_no_progress_ticks"))),
        "max_solver_fallbacks": int(max(values("solver_fallbacks"))),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AoE3 2D batch tester")
    parser.add_argument("--red", default="musketeer:40")
    parser.add_argument("--blue", default="pikeman:40")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument("--seed-start", type=int, default=0)
    parser.add_argument(
        "--civ-war",
        action="store_true",
        help="运行随机文明国战阵容，而不是固定兵种镜像",
    )
    parser.add_argument(
        "--versus",
        nargs=2,
        metavar=("RED_CIV", "BLUE_CIV"),
        help="固定国战文明对，例如 British Japanese",
    )
    parser.add_argument("--age", type=int, default=3, choices=range(2, 6))
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    repo = UnitRepo.get()
    red_unit, red_count = parse_unit(repo, args.red)
    blue_unit, blue_count = parse_unit(repo, args.blue)
    config = Simulation2DConfig()
    rows: list[dict[str, Any]] = []

    for offset in range(args.games):
        seed = args.seed_start + offset
        if args.civ_war or args.versus:
            if args.versus:
                red_civ, blue_civ = args.versus
            else:
                red_profile, blue_profile = pick_random_civs(
                    rng=random.Random(seed)
                )
                red_civ, blue_civ = red_profile.id, blue_profile.id
            row = run_civ_war_one(
                repo=repo,
                red_civ=red_civ,
                blue_civ=blue_civ,
                seed=seed,
                age=args.age,
                config=config,
            )
        else:
            row = run_one(
                red_unit=red_unit,
                red_count=red_count,
                blue_unit=blue_unit,
                blue_count=blue_count,
                seed=seed,
                config=config,
            )
        rows.append(row)
        if not args.quiet:
            if "red_civ" in row:
                print(
                    f"[{offset + 1:4d}/{args.games}] seed={seed:<4d} "
                    f"{row['red_civ']} {row['red_strategy']} vs "
                    f"{row['blue_civ']} {row['blue_strategy']} | "
                    f"winner={row['winner']:<4s} time={row['duration']:6.2f}s "
                    f"alive={row['red_alive']:3d}/{row['blue_alive']:<3d} "
                    f"overlap={row['max_residual_overlap']:.4f} "
                    f"no_progress={row['max_no_progress_units']:3d} "
                    f"fallback={row['solver_fallbacks']:6d}"
                )
            else:
                print(
                    f"[{offset + 1:4d}/{args.games}] seed={seed:<4d} "
                    f"winner={row['winner']:<4s} time={row['duration']:6.2f}s "
                    f"alive={row['red_alive']:3d}/{row['blue_alive']:<3d} "
                    f"overlap={row['max_residual_overlap']:.4f} "
                    f"no_progress={row['max_no_progress_units']:3d} "
                    f"fallback={row['solver_fallbacks']:6d} "
                    f"elapsed={row['elapsed_ms']:8.1f}ms"
                )

    summary = summarize(rows)
    print("\n=== 2D batch summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.json_out is not None:
        payload = {
            "config": asdict(config),
            "mode": "civ_war" if (args.civ_war or args.versus) else "units",
            "age": args.age,
            "red": args.red,
            "blue": args.blue,
            "summary": summary,
            "rows": rows,
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"json written: {args.json_out}")


if __name__ == "__main__":
    main()
