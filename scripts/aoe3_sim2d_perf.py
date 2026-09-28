"""Temporary profiler for the 2D battle loop.

Runs several matchups with timing enabled and writes a readable log.
Behavior is unchanged. Default off in production; this script turns it on.

    python scripts/aoe3_sim2d_perf.py
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from plugins.aoe3.repository import UnitRepo  # noqa: E402
from plugins.aoe3.upgrades import apply_upgrades  # noqa: E402
from plugins.games.aoe3_battle.simulator2d import BattleSimulator2D  # noqa: E402
from plugins.games.aoe3_battle.simulator2d.perf import activate  # noqa: E402

AGE = 3
SEED = 42
MAX_TICKS = 400
CASES = (
    ("gaucho_sailor", "derevgaucho", 69, "desaloonsailor", 93),
    ("musket_pike", "musketeer", 100, "pikeman", 100),
    ("musket_skirm", "musketeer", 100, "skirmisher", 100),
    ("pike_pike", "pikeman", 80, "pikeman", 80),
    ("musket_musket", "musketeer", 60, "musketeer", 60),
)


def _setup_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[
            logging.FileHandler(path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("aoe3_battle.simulator2d").setLevel(logging.WARNING)
    logging.getLogger("aoe3_battle.simulator2d.perf").setLevel(logging.INFO)


def main() -> None:
    max_ticks = int(sys.argv[1]) if len(sys.argv) > 1 else MAX_TICKS
    only = sys.argv[2] if len(sys.argv) > 2 else ""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = ROOT / "logs" / "aoe3_battle" / f"sim2d_perf_{stamp}.log"
    _setup_log(path)
    log = logging.getLogger("aoe3_sim2d_perf")
    repo = UnitRepo.get()
    log.info("log=%s age=%d seed=%d max_ticks=%d", path, AGE, SEED, max_ticks)
    log.info("阶段百分比相对本窗口 wall。内含项已经算在阶段里, 不要再加一次。")
    for name, red_id, red_count, blue_id, blue_count in CASES:
        if only and name != only:
            continue
        red = apply_upgrades(repo.get_by_id(red_id), AGE)
        blue = apply_upgrades(repo.get_by_id(blue_id), AGE)
        assert red is not None and blue is not None
        log.info(
            "CASE %s red=%s x%d speed=%.2f r=%.2f range=%.1f/%.1f melee=%.2f hp=%.0f "
            "blue=%s x%d speed=%.2f r=%.2f range=%.1f/%.1f melee=%.2f hp=%.0f",
            name,
            red.name,
            red_count,
            red.speed,
            red.obstruction_radius_x,
            red.range,
            red.range_min,
            red.range_melee,
            red.hp,
            blue.name,
            blue_count,
            blue.speed,
            blue.obstruction_radius_x,
            blue.range,
            blue.range_min,
            blue.range_melee,
            blue.hp,
        )
        activate()
        started = time.perf_counter()
        result = BattleSimulator2D(
            red_unit=red,
            red_count=red_count,
            blue_unit=blue,
            blue_count=blue_count,
            seed=SEED,
            max_ticks=max_ticks,
            session_id=name,
        ).run()
        elapsed = time.perf_counter() - started
        log.info(
            "RESULT %s wall=%.2fs ticks=%d timeout=%s winner=%s alive=%d/%d",
            name,
            elapsed,
            result.ticks,
            result.timeout,
            result.winner.value if result.winner else "draw",
            len(result.red_alive),
            len(result.blue_alive),
        )
    log.info("wrote %s", path)


if __name__ == "__main__":
    main()
