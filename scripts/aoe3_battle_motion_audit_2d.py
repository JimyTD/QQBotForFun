"""Audit per-unit 2D movement quality from frame snapshots.

Run the existing 2D simulator, then quantify:
  - overlap severity
  - jitter / direction reversals
  - displacement versus chosen speed
  - sudden positional jumps

This is a development-only, read-only analysis tool.  It does not touch the
production game or economy.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
for path in (str(_ROOT), str(_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from plugins.aoe3.repository import UnitRepo  # noqa: E402
from plugins.games.aoe3_battle.simulator2d import (  # noqa: E402
    BattleSimulator2D,
    Simulation2DConfig,
)


def parse_spec(repo: UnitRepo, spec: str):
    unit_id, _, count_text = spec.rpartition(":")
    unit = repo.get_by_id(unit_id) or next(
        iter(repo.search(unit_id, limit=1)),
        None,
    )
    if unit is None:
        raise ValueError(f"unit not found: {unit_id}")
    return unit, int(count_text)


def audit(frames: list[dict[str, Any]]) -> dict[str, Any]:
    positions: dict[int, list[tuple[float, float, float]]] = {}
    max_overlap = 0.0
    worst_overlap_frame: dict[str, Any] | None = None

    for frame in frames:
        units = {unit["id"]: unit for unit in frame.get("units", [])}
        for unit in units.values():
            positions.setdefault(unit["id"], []).append(
                (frame["tick"], unit["x"], unit["y"])
            )
        for index, first in enumerate(units.values()):
            for second in list(units.values())[index + 1 :]:
                distance = math.hypot(
                    first["x"] - second["x"],
                    first["y"] - second["y"],
                )
                overlap = 0.9 - distance
                if overlap > max_overlap:
                    max_overlap = overlap
                    worst_overlap_frame = {
                        "tick": frame["tick"],
                        "a": first["id"],
                        "b": second["id"],
                        "overlap": round(overlap, 4),
                    }

    jitter_rows = []
    jump_rows = []
    for unit_id, samples in positions.items():
        reversals = 0
        previous_dx = 0.0
        previous_dy = 0.0
        max_jump = 0.0
        total_distance = 0.0
        moving_steps = 0
        for (_, x1, y1), (_, x2, y2) in pairwise(samples):
            dx = x2 - x1
            dy = y2 - y1
            distance = math.hypot(dx, dy)
            total_distance += distance
            max_jump = max(max_jump, distance)
            if distance > 0.05:
                moving_steps += 1
                if previous_dx * dx + previous_dy * dy < 0:
                    reversals += 1
                previous_dx, previous_dy = dx, dy
        if moving_steps >= 4:
            jitter_rows.append(
                {
                    "unit": unit_id,
                    "reversals": reversals,
                    "moving_steps": moving_steps,
                    "total_distance": round(total_distance, 3),
                }
            )
        if max_jump > 0.9:
            jump_rows.append(
                {
                    "unit": unit_id,
                    "max_jump": round(max_jump, 3),
                    "total_distance": round(total_distance, 3),
                }
            )

    jitter_rows.sort(key=lambda row: row["reversals"], reverse=True)
    jump_rows.sort(key=lambda row: row["max_jump"], reverse=True)
    return {
        "frames": len(frames),
        "max_overlap": round(max_overlap, 4),
        "worst_overlap_frame": worst_overlap_frame,
        "jitter_units": jitter_rows[:12],
        "jump_units": jump_rows[:12],
        "avg_reversals": round(
            statistics.mean(row["reversals"] for row in jitter_rows),
            2,
        )
        if jitter_rows
        else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AoE3 2D motion audit")
    parser.add_argument("--red", default="musketeer:40")
    parser.add_argument("--blue", default="pikeman:40")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    repo = UnitRepo.get()
    red_unit, red_count = parse_spec(repo, args.red)
    blue_unit, blue_count = parse_spec(repo, args.blue)
    frames: list[dict[str, Any]] = []
    simulator = BattleSimulator2D(
        red_unit,
        red_count,
        blue_unit,
        blue_count,
        seed=args.seed,
        session_id=f"motion_audit_{args.seed}",
        config=Simulation2DConfig(),
        frame_callback=frames.append,
    )
    result = simulator.run()
    report = audit(frames)
    report["winner"] = result.winner.value if result.winner else "draw"
    report["duration"] = result.duration
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps({"report": report, "frames": frames}, ensure_ascii=False),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
