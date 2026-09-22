"""Generate a real civ-war opening PNG for QQ message review."""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for import_path in (str(ROOT), str(ROOT / "src")):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

from plugins.aoe3.repository import UnitRepo  # noqa: E402
from plugins.games.aoe3_battle.civ_war_civs import get_civ_profile  # noqa: E402
from plugins.games.aoe3_battle.civ_war_lineups import generate_civ_candidates  # noqa: E402
from plugins.games.aoe3_battle.civ_war_matchup import estimate_matchup, generate_civ_war_lineup  # noqa: E402
from plugins.games.aoe3_battle.opening_renderer import OpeningSide, render_civ_war_opening  # noqa: E402

OUTPUT = ROOT / "artifacts" / "aoe3_civ_war_opening_preview.png"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--red", default="Chinese")
    parser.add_argument("--blue", default="British")
    parser.add_argument("--red-strategy", default="")
    parser.add_argument("--blue-strategy", default="")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--age", type=int, default=3)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    if args.red_strategy or args.blue_strategy:
        repo = UnitRepo.get()

        def pick(civ_id: str, strategy_id: str):
            return next(
                candidate
                for candidate in generate_civ_candidates(repo, civ_id, age=args.age)
                if candidate.source == "national" and candidate.strategy_id == strategy_id
            )

        red_candidate = pick(args.red, args.red_strategy)
        blue_candidate = pick(args.blue, args.blue_strategy)
        match = estimate_matchup(red_candidate, blue_candidate, age=args.age)
        red_lineup = match.red_lineup
        blue_lineup = match.blue_lineup
        red_strategy = red_candidate.title
        blue_strategy = blue_candidate.title
    else:
        match, _ = generate_civ_war_lineup(
            UnitRepo.get(),
            args.red,
            args.blue,
            age=args.age,
            rng=random.Random(args.seed),
        )
        red_lineup = match.red
        blue_lineup = match.blue
        red_strategy = match.red_strategy or ""
        blue_strategy = match.blue_strategy or ""
    red_profile = get_civ_profile(args.red)
    blue_profile = get_civ_profile(args.blue)
    png = render_civ_war_opening(
        red=OpeningSide(
            civ_name=red_profile.name,
            civ_id=args.red,
            strategy=red_strategy,
            units=tuple((slot.unit, slot.count) for slot in red_lineup.slots),
        ),
        blue=OpeningSide(
            civ_name=blue_profile.name,
            civ_id=args.blue,
            strategy=blue_strategy,
            units=tuple((slot.unit, slot.count) for slot in blue_lineup.slots),
        ),
        age=args.age,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(png)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
