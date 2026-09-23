"""Read replay frames and report motion regressions without a browser."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.request
from collections import defaultdict
from itertools import pairwise
from pathlib import Path


def audit(frames: list[dict]) -> dict:
    samples = defaultdict(list)
    for frame in frames:
        if frame.get("status") != "running":
            continue
        for unit in frame["units"]:
            samples[unit["id"]].append((frame["tick"], unit))
    loops = []
    stalled = 0
    moving_windows = 0
    long_routes = []
    for unit_id, history in samples.items():
        for end in range(20, len(history), 5):
            window = history[end - 20 : end + 1]
            if window[-1][0] - window[0][0] != 20 or any(u["stopped"] for _, u in window):
                continue
            deltas = [(b["x"] - a["x"], b["y"] - a["y"]) for (_, a), (_, b) in pairwise(window)]
            path = sum(math.hypot(*d) for d in deltas)
            first, last = window[0][1], window[-1][1]
            net = math.hypot(last["x"] - first["x"], last["y"] - first["y"])
            moving_windows += 1
            if path <= 1.5 and net < 0.2:
                stalled += 1
            if path > 1.5 and net < 0.6:
                loops.append(
                    {
                        "unit": unit_id,
                        "ticks": [window[0][0], window[-1][0]],
                        "path": round(path, 3),
                        "net": round(net, 3),
                        "reversals": sum(
                            ax * bx + ay * by < -0.001 for (ax, ay), (bx, by) in pairwise(deltas)
                        ),
                    }
                )
    previous_routes = {}
    for frame in frames:
        units = {u["id"]: u for u in frame["units"]}
        for unit in units.values():
            route = unit.get("detour_path", [])
            if route == previous_routes.get(unit["id"]):
                continue
            previous_routes[unit["id"]] = route
            target = units.get(unit.get("move_target_id"))
            if not route or not target:
                continue
            points = [[unit["x"], unit["y"]], *route, [target["x"], target["y"]]]
            direct = math.dist(points[0], points[-1])
            length = sum(math.dist(a, b) for a, b in pairwise(points))
            if direct > 2 and length > direct * 3 and length - direct > 4:
                long_routes.append(
                    {
                        "tick": frame["tick"],
                        "unit": unit["id"],
                        "direct": round(direct, 2),
                        "planned": round(length, 2),
                    }
                )
    loops.sort(key=lambda row: (row["reversals"], row["path"]), reverse=True)
    return {
        "match": frames[0].get("match_label"),
        "frames": len(frames),
        "loop_windows": len(loops),
        "loop_units": len({r["unit"] for r in loops}),
        "stalled_windows": stalled,
        "moving_windows": moving_windows,
        "worst_loops": loops[:5],
        "long_routes": len(long_routes),
        "worst_routes": sorted(long_routes, key=lambda r: r["planned"] - r["direct"], reverse=True)[
            :5
        ],
        "max_overlap": max(f["summary"].get("max_overlap", 0) for f in frames),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8791/api/history")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--save", type=Path)
    parser.add_argument("--red-civ")
    parser.add_argument("--blue-civ")
    parser.add_argument("--age", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    elapsed = None
    if args.red_civ and args.blue_civ:
        root = Path(__file__).resolve().parent.parent
        sys.path[:0] = [str(root), str(root / "src")]
        from scripts.aoe3_battle_viewer_2d import build_simulator_from_request

        frames = []
        simulator = build_simulator_from_request(
            {
                "mode": "civ_war",
                "red_civ": args.red_civ,
                "blue_civ": args.blue_civ,
                "age": args.age,
                "seed": args.seed,
            },
            frame_callback=frames.append,
        )
        started = time.perf_counter()
        simulator.run()
        elapsed = time.perf_counter() - started
    elif args.input:
        frames = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        with urllib.request.urlopen(args.url, timeout=30) as response:
            frames = json.load(response)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(frames, ensure_ascii=False), encoding="utf-8")
    report = audit(frames)
    if elapsed is not None:
        report["simulation_seconds"] = round(elapsed, 2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
